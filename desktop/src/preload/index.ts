import { contextBridge } from "electron";

const baseUrl = "http://127.0.0.1:43900";

async function request(path: string, init?: RequestInit): Promise<unknown> {
  const response = await fetch(baseUrl + path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {})
    }
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || "Homuncula request failed");
  }
  return response.json();
}

contextBridge.exposeInMainWorld("homuncula", {
  health: () => request("/health"),
  state: () => request("/state"),
  threads: () => request("/threads"),
  createThread: (title: string) =>
    request("/threads", {
      method: "POST",
      body: JSON.stringify({ title })
    }),
  chat: (threadId: string, content: string) =>
    request("/threads/" + encodeURIComponent(threadId) + "/chat", {
      method: "POST",
      body: JSON.stringify({ content })
    }),
  responsibilities: () => request("/responsibilities"),
  createResponsibility: (title: string, objective: string) =>
    request("/responsibilities", {
      method: "POST",
      body: JSON.stringify({ title, objective, proactive_mode: "observe", start_now: true })
    }),
  actions: (status?: string) =>
    request("/actions" + (status ? "?status=" + encodeURIComponent(status) : "")),
  approve: (id: string) =>
    request("/actions/" + encodeURIComponent(id) + "/approve", { method: "POST" }),
  deny: (id: string) =>
    request("/actions/" + encodeURIComponent(id) + "/deny", { method: "POST" }),
  execute: (id: string) =>
    request("/actions/" + encodeURIComponent(id) + "/execute", { method: "POST" }),
  activity: () => request("/activity?limit=100")
});
