import { contextBridge, ipcRenderer } from "electron";

async function request(path: string, method = "GET", body?: unknown): Promise<unknown> {
  return ipcRenderer.invoke("homuncula:request", path, method, body);
}

contextBridge.exposeInMainWorld("homuncula", {
  health: () => request("/health"),
  state: () => request("/state"),
  threads: () => request("/threads"),
  messages: (threadId: string) =>
    request("/threads/" + encodeURIComponent(threadId) + "/messages"),
  createThread: (title: string) => request("/threads", "POST", { title }),
  chat: (threadId: string, content: string) =>
    request("/threads/" + encodeURIComponent(threadId) + "/chat", "POST", { content }),
  responsibilities: () => request("/responsibilities"),
  createResponsibility: (title: string, objective: string) =>
    request("/responsibilities", "POST", {
      title,
      objective,
      proactive_mode: "observe",
      start_now: true
    }),
  actions: (status?: string) =>
    request("/actions" + (status ? "?status=" + encodeURIComponent(status) : "")),
  approve: (id: string) =>
    request("/actions/" + encodeURIComponent(id) + "/approve", "POST"),
  deny: (id: string) =>
    request("/actions/" + encodeURIComponent(id) + "/deny", "POST"),
  execute: (id: string) =>
    request("/actions/" + encodeURIComponent(id) + "/execute", "POST"),
  activity: () => request("/activity?limit=100")
});
