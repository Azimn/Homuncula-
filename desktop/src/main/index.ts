import { app, BrowserWindow, ipcMain, Menu, nativeImage, Notification, Tray } from "electron";
import { spawn, type ChildProcess } from "node:child_process";
import { randomBytes } from "node:crypto";
import {
  chmodSync,
  existsSync,
  mkdirSync,
  readFileSync,
  writeFileSync
} from "node:fs";
import { homedir } from "node:os";
import { join, resolve } from "node:path";
import { electronApp, is } from "@electron-toolkit/utils";

const API_BASE = "http://127.0.0.1:43900";
const ALLOWED_API_PATH =
  /^\/(health|state|runtime|threads|responsibilities|actions|grants|activity|memory|findings|processes|subscriptions|secrets|computer|plans|skills|verification|models)(\/|\?|$)/;

let backend: ChildProcess | null = null;
let mainWindow: BrowserWindow | null = null;
let tray: Tray | null = null;
let quitting = false;
let ownerToken = "";
let notificationTimer: NodeJS.Timeout | null = null;
let notificationPrimed = false;
const seenFindingIds = new Set<string>();
const seenActionIds = new Set<string>();

function dataHome(): string {
  const configured = process.env.HOMUNCULA_HOME;
  const home = configured ? resolve(configured) : join(homedir(), ".homuncula");
  mkdirSync(home, { recursive: true });
  return home;
}

function loadOwnerToken(): string {
  const supplied = process.env.HOMUNCULA_OWNER_TOKEN?.trim();
  if (supplied) return supplied;

  const path = join(dataHome(), "owner.token");
  if (existsSync(path)) {
    const token = readFileSync(path, "utf8").trim();
    if (token.length >= 32) return token;
  }

  const token = randomBytes(48).toString("base64url");
  writeFileSync(path, token + "\n", { encoding: "utf8", mode: 0o600 });
  try {
    chmodSync(path, 0o600);
  } catch {
    // Windows ACLs remain the authoritative protection mechanism.
  }
  return token;
}

function workspacePath(): string {
  if (process.env.HOMUNCULA_WORKSPACE) {
    return resolve(process.env.HOMUNCULA_WORKSPACE);
  }
  if (!app.isPackaged) {
    return process.env.HOMUNCULA_ROOT || resolve(app.getAppPath(), "..");
  }
  const workspace = join(homedir(), "Homuncula Workspace");
  mkdirSync(workspace, { recursive: true });
  return workspace;
}

function startBackend(): void {
  if (backend) return;

  ownerToken = loadOwnerToken();
  const configuredPython = process.env.HOMUNCULA_PYTHON;
  const repoRoot = process.env.HOMUNCULA_ROOT || resolve(app.getAppPath(), "..");

  const command = app.isPackaged
    ? join(process.resourcesPath, "agentd.exe")
    : configuredPython || (process.platform === "win32" ? "py" : "python3");

  const args = app.isPackaged
    ? []
    : configuredPython
      ? ["-m", "homuncula.main"]
      : process.platform === "win32"
        ? ["-3.11", "-m", "homuncula.main"]
        : ["-m", "homuncula.main"];

  backend = spawn(command, args, {
    cwd: app.isPackaged ? workspacePath() : repoRoot,
    windowsHide: true,
    env: {
      ...process.env,
      HOMUNCULA_OWNER_TOKEN: ownerToken,
      HOMUNCULA_HOME: dataHome(),
      HOMUNCULA_WORKSPACE: workspacePath()
    },
    stdio: "pipe"
  });

  backend.stdout?.on("data", (chunk) => {
    process.stdout.write("[agentd] " + chunk.toString());
  });
  backend.stderr?.on("data", (chunk) => {
    process.stderr.write("[agentd] " + chunk.toString());
  });
  backend.on("exit", () => {
    backend = null;
  });
}

async function runHostCommand(command: string, args: string[]): Promise<{
  returncode: number | null;
  stdout: string;
  stderr: string;
}> {
  return new Promise((resolveCommand, rejectCommand) => {
    const child = spawn(command, args, {
      windowsHide: false,
      stdio: "pipe"
    });
    let stdout = "";
    let stderr = "";
    child.stdout?.on("data", (chunk) => {
      stdout = (stdout + chunk.toString()).slice(-100000);
    });
    child.stderr?.on("data", (chunk) => {
      stderr = (stderr + chunk.toString()).slice(-100000);
    });
    child.once("error", rejectCommand);
    child.once("exit", (code) => {
      resolveCommand({ returncode: code, stdout, stderr });
    });
  });
}

async function installOllama(): Promise<{
  returncode: number | null;
  stdout: string;
  stderr: string;
}> {
  if (process.platform !== "win32") {
    throw new Error("One-click Ollama installation is currently available on Windows only.");
  }
  return runHostCommand("winget", [
    "install",
    "--id",
    "Ollama.Ollama",
    "-e",
    "--accept-package-agreements",
    "--accept-source-agreements"
  ]);
}

async function restartBackend(): Promise<void> {
  const current = backend;
  backend = null;
  if (current && !current.killed) {
    await new Promise<void>((resolveRestart) => {
      let settled = false;
      const finish = (): void => {
        if (settled) return;
        settled = true;
        resolveRestart();
      };
      current.once("exit", finish);
      current.kill();
      setTimeout(finish, 2000);
    });
  }
  startBackend();
}

async function apiRequest(
  path: string,
  method: string = "GET",
  body?: unknown
): Promise<any> {
  if (!ALLOWED_API_PATH.test(path) || path.includes("://")) {
    throw new Error("Invalid local API path");
  }

  const headers: Record<string, string> = {
    Authorization: "Bearer " + ownerToken
  };
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const response = await fetch(API_BASE + path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body)
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || "Homuncula request failed");
  }

  if (response.status === 204) return null;
  return response.json();
}

function showNotification(title: string, body: string): void {
  if (!Notification.isSupported()) return;
  const notification = new Notification({
    title,
    body: body.slice(0, 240),
    silent: false
  });
  notification.on("click", showWindow);
  notification.show();
}

async function pollNotifications(): Promise<void> {
  try {
    const state = await apiRequest("/state");
    const findings = Array.isArray(state.findings) ? state.findings : [];
    const actions = Array.isArray(state.pending_actions) ? state.pending_actions : [];

    if (!notificationPrimed) {
      for (const finding of findings) seenFindingIds.add(String(finding.id));
      for (const action of actions) seenActionIds.add(String(action.id));
      notificationPrimed = true;
      return;
    }

    const focused = Boolean(mainWindow && mainWindow.isVisible() && mainWindow.isFocused());

    for (const finding of findings) {
      const id = String(finding.id);
      if (seenFindingIds.has(id)) continue;
      seenFindingIds.add(id);
      if (!focused) {
        showNotification(
          String(finding.title || "Homuncula found something"),
          String(finding.summary || "A new finding needs your attention.")
        );
      }
    }

    for (const action of actions) {
      const id = String(action.id);
      if (seenActionIds.has(id)) continue;
      seenActionIds.add(id);
      if (!focused) {
        showNotification(
          "Homuncula needs approval",
          String(action.preview || action.intent || "A local action is waiting for approval.")
        );
      }
    }
  } catch {
    // Runtime startup and restarts are handled by the normal health/recovery path.
  }
}

function startNotificationMonitor(): void {
  if (notificationTimer) return;
  void pollNotifications();
  notificationTimer = setInterval(() => void pollNotifications(), 8000);
}

function startupSettings(): { supported: boolean; openAtLogin: boolean } {
  if (!app.isPackaged) {
    return { supported: false, openAtLogin: false };
  }
  return {
    supported: true,
    openAtLogin: app.getLoginItemSettings().openAtLogin
  };
}

function setLaunchAtLogin(enabled: boolean): { supported: boolean; openAtLogin: boolean } {
  if (!app.isPackaged) {
    return { supported: false, openAtLogin: false };
  }
  app.setLoginItemSettings({
    openAtLogin: enabled,
    openAsHidden: true
  });
  return startupSettings();
}

function installApiBridge(): void {
  ipcMain.handle("homuncula:install-ollama", async () => installOllama());

  ipcMain.handle("homuncula:restart-backend", async () => {
    await restartBackend();
    return { restarted: true };
  });

  ipcMain.handle("homuncula:startup-settings", () => startupSettings());
  ipcMain.handle("homuncula:set-launch-at-login", (_event, enabled: boolean) =>
    setLaunchAtLogin(Boolean(enabled))
  );

  ipcMain.handle(
    "homuncula:request",
    async (_event, path: string, method: string = "GET", body?: unknown) =>
      apiRequest(path, method, body)
  );
}

function showWindow(): void {
  if (!mainWindow) {
    createWindow();
    return;
  }
  mainWindow.show();
  mainWindow.focus();
}

function createWindow(): void {
  const window = new BrowserWindow({
    width: 1380,
    height: 900,
    minWidth: 1040,
    minHeight: 700,
    show: false,
    backgroundColor: "#111214",
    title: "Homuncula",
    webPreferences: {
      preload: join(__dirname, "../preload/index.js"),
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false
    }
  });
  mainWindow = window;

  window.on("ready-to-show", () => {
    const launchedAtLogin =
      app.isPackaged && app.getLoginItemSettings().wasOpenedAtLogin;
    if (!launchedAtLogin) window.show();
  });
  window.on("close", (event) => {
    if (!quitting) {
      event.preventDefault();
      window.hide();
    }
  });
  window.on("closed", () => {
    mainWindow = null;
  });

  if (is.dev && process.env.ELECTRON_RENDERER_URL) {
    void window.loadURL(process.env.ELECTRON_RENDERER_URL);
  } else {
    void window.loadFile(join(__dirname, "../renderer/index.html"));
  }
}

function createTray(): void {
  const tinyPng =
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Z0qAAAAAASUVORK5CYII=";
  const icon = nativeImage.createFromDataURL(tinyPng).resize({ width: 16, height: 16 });
  tray = new Tray(icon);
  tray.setToolTip("Homuncula");
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: "Show Homuncula", click: showWindow },
      {
        label: "Quit",
        click: () => {
          quitting = true;
          app.quit();
        }
      }
    ])
  );
  tray.on("double-click", showWindow);
}

app.whenReady().then(() => {
  electronApp.setAppUserModelId("ai.homuncula.desktop");
  startBackend();
  installApiBridge();
  createTray();
  createWindow();
  startNotificationMonitor();

  app.on("activate", showWindow);
});

app.on("before-quit", () => {
  quitting = true;
  if (notificationTimer) {
    clearInterval(notificationTimer);
    notificationTimer = null;
  }
  if (backend && !backend.killed) {
    backend.kill();
  }
});

app.on("window-all-closed", () => {
  // Homuncula remains active in the tray on every desktop platform.
});
