import { contextBridge, ipcRenderer } from "electron";

async function request(path: string, method = "GET", body?: unknown): Promise<any> {
  return ipcRenderer.invoke("homuncula:request", path, method, body);
}

contextBridge.exposeInMainWorld("homuncula", {
  health: () => request("/health"),
  state: () => request("/state"),
  pauseAutonomy: () => request("/runtime/pause", "POST"),
  resumeAutonomy: () => request("/runtime/resume", "POST"),
  threads: () => request("/threads"),
  messages: (threadId: string) =>
    request("/threads/" + encodeURIComponent(threadId) + "/messages"),
  createThread: (title: string) => request("/threads", "POST", { title }),
  chat: (threadId: string, content: string) =>
    request("/threads/" + encodeURIComponent(threadId) + "/chat", "POST", { content }),
  responsibilities: () => request("/responsibilities"),
  createResponsibility: (title: string, objective: string, proactiveMode = "observe") =>
    request("/responsibilities", "POST", {
      title,
      objective,
      proactive_mode: proactiveMode,
      start_now: true
    }),
  updateResponsibility: (
    id: string,
    patch: { status?: string; proactive_mode?: string }
  ) => request("/responsibilities/" + encodeURIComponent(id), "PATCH", patch),
  actions: (status?: string) =>
    request("/actions" + (status ? "?status=" + encodeURIComponent(status) : "")),
  approve: (id: string) =>
    request("/actions/" + encodeURIComponent(id) + "/approve", "POST"),
  deny: (id: string) =>
    request("/actions/" + encodeURIComponent(id) + "/deny", "POST"),
  execute: (id: string) =>
    request("/actions/" + encodeURIComponent(id) + "/execute", "POST"),
  activity: () => request("/activity?limit=150"),
  findings: (status?: string) =>
    request("/findings" + (status ? "?status=" + encodeURIComponent(status) : "")),
  memory: (query?: string) =>
    query
      ? request("/memory/search?q=" + encodeURIComponent(query) + "&limit=50")
      : request("/memory?limit=200"),
  reviseMemory: (
    id: string,
    content: string,
    reason: string,
    kind?: string,
    confidence?: number
  ) =>
    request("/memory/" + encodeURIComponent(id), "PATCH", {
      content,
      reason,
      kind,
      confidence
    }),
  grants: () => request("/grants"),
  addGrant: (capability: string, resourcePattern: string, expiresAt?: string) =>
    request("/grants", "POST", {
      capability,
      resource_pattern: resourcePattern,
      expires_at: expiresAt
    }),
  revokeGrant: (id: string) =>
    request("/grants/" + encodeURIComponent(id), "DELETE"),
  processes: () => request("/processes?limit=100"),
  subscriptions: () => request("/subscriptions"),
  computerStatus: () => request("/computer/status"),
  windows: () => request("/computer/windows")
});
