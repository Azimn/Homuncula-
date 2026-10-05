import { app, BrowserWindow, ipcMain } from "electron";
import { spawn, type ChildProcess } from "node:child_process";
import { join, resolve } from "node:path";
import { electronApp, is } from "@electron-toolkit/utils";

const API_BASE = "http://127.0.0.1:43900";
let backend: ChildProcess | null = null;

function startBackend(): void {
  if (backend) return;

  const configuredPython = process.env.HOMUNCULA_PYTHON;
  const command = configuredPython || (process.platform === "win32" ? "py" : "python3");
  const repoRoot = process.env.HOMUNCULA_ROOT || resolve(app.getAppPath(), "..");

  const args = configuredPython
    ? ["-m", "homuncula.main"]
    : process.platform === "win32"
      ? ["-3.11", "-m", "homuncula.main"]
      : ["-m", "homuncula.main"];

  backend = spawn(command, args, {
    cwd: repoRoot,
    windowsHide: true,
    env: process.env,
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

function installApiBridge(): void {
  ipcMain.handle(
    "homuncula:request",
    async (_event, path: string, method: string = "GET", body?: unknown) => {
      if (!path.startsWith("/") || path.includes("://")) {
        throw new Error("Invalid local API path");
      }

      const response = await fetch(API_BASE + path, {
        method,
        headers: body === undefined ? undefined : { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body)
      });

      if (!response.ok) {
        const message = await response.text();
        throw new Error(message || "Homuncula request failed");
      }

      return response.json();
    }
  );
}

function createWindow(): void {
  const window = new BrowserWindow({
    width: 1320,
    height: 860,
    minWidth: 980,
    minHeight: 680,
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

  window.on("ready-to-show", () => window.show());

  if (is.dev && process.env.ELECTRON_RENDERER_URL) {
    void window.loadURL(process.env.ELECTRON_RENDERER_URL);
  } else {
    void window.loadFile(join(__dirname, "../renderer/index.html"));
  }
}

app.whenReady().then(() => {
  electronApp.setAppUserModelId("ai.homuncula.desktop");
  installApiBridge();
  startBackend();
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("before-quit", () => {
  if (backend && !backend.killed) {
    backend.kill();
  }
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
