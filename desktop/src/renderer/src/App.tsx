import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

type Health = {
  ok: boolean;
  workspace: string;
  database: string;
  provider: {
    ok: boolean;
    model: string;
    base_url: string;
    selected_available?: boolean;
    error?: string;
  };
};

type Responsibility = {
  id: string;
  title: string;
  objective: string;
  status: string;
  proactive_mode: string;
  updated_at: string;
};

type Action = {
  id: string;
  capability: string;
  target: string;
  intent: string;
  preview: string;
  risk: string;
  status: string;
  created_at: string;
};

type Activity = {
  id: string;
  kind: string;
  message: string;
  responsibility_id?: string | null;
  created_at: string;
};

type ChatLine = {
  role: "user" | "assistant" | "system";
  content: string;
};

function relativeTime(value: string): string {
  const when = new Date(value).getTime();
  const seconds = Math.max(0, Math.round((Date.now() - when) / 1000));
  if (seconds < 60) return seconds + "s ago";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return minutes + "m ago";
  const hours = Math.round(minutes / 60);
  if (hours < 24) return hours + "h ago";
  return Math.round(hours / 24) + "d ago";
}

function App(): JSX.Element {
  const [health, setHealth] = useState<Health | null>(null);
  const [responsibilities, setResponsibilities] = useState<Responsibility[]>([]);
  const [actions, setActions] = useState<Action[]>([]);
  const [activity, setActivity] = useState<Activity[]>([]);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [chat, setChat] = useState<ChatLine[]>([
    {
      role: "system",
      content:
        "Homuncula is local. Start a conversation or create a responsibility for work that should persist."
    }
  ]);
  const [prompt, setPrompt] = useState("");
  const [responsibilityTitle, setResponsibilityTitle] = useState("");
  const [responsibilityObjective, setResponsibilityObjective] = useState("");
  const [busy, setBusy] = useState(false);
  const [backendReady, setBackendReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [nextHealth, nextResponsibilities, nextActions, nextActivity] =
        await Promise.all([
          window.homuncula.health(),
          window.homuncula.responsibilities(),
          window.homuncula.actions("pending"),
          window.homuncula.activity()
        ]);

      setHealth(nextHealth as Health);
      setResponsibilities(nextResponsibilities as Responsibility[]);
      setActions(nextActions as Action[]);
      setActivity(nextActivity as Activity[]);
      setBackendReady(true);
      setError(null);
    } catch (cause) {
      setBackendReady(false);
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 4000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    void (async () => {
      try {
        const threads = await window.homuncula.threads();
        if (!threads.length) return;

        const id = threads[0].id as string;
        const persisted = await window.homuncula.messages(id);
        setThreadId(id);

        if (persisted.length) {
          setChat(
            persisted.map((item: any) => ({
              role: item.role === "user" ? "user" : "assistant",
              content: item.content
            }))
          );
        }
      } catch {
        // The runtime may still be starting. Periodic health refresh will recover.
      }
    })();
  }, []);

  const activeCount = useMemo(
    () => responsibilities.filter((item) => item.status === "active").length,
    [responsibilities]
  );

  async function ensureThread(): Promise<string> {
    if (threadId) return threadId;
    const thread = await window.homuncula.createThread("Main");
    setThreadId(thread.id);
    return thread.id as string;
  }

  async function sendMessage(event: FormEvent): Promise<void> {
    event.preventDefault();
    const content = prompt.trim();
    if (!content || busy) return;

    setPrompt("");
    setChat((current) => [...current, { role: "user", content }]);
    setBusy(true);
    setError(null);

    try {
      const id = await ensureThread();
      const result = await window.homuncula.chat(id, content);
      setChat((current) => [
        ...current,
        { role: "assistant", content: result.content }
      ]);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  async function createResponsibility(event: FormEvent): Promise<void> {
    event.preventDefault();
    const title = responsibilityTitle.trim();
    const objective = responsibilityObjective.trim();
    if (!title || !objective || busy) return;

    setBusy(true);
    try {
      await window.homuncula.createResponsibility(title, objective);
      setResponsibilityTitle("");
      setResponsibilityObjective("");
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  async function approveAndRun(action: Action): Promise<void> {
    setBusy(true);
    try {
      await window.homuncula.approve(action.id);
      await window.homuncula.execute(action.id);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  async function deny(action: Action): Promise<void> {
    setBusy(true);
    try {
      await window.homuncula.deny(action.id);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app-shell">
      <aside className="rail">
        <div className="brand">
          <div className="brand-mark">H</div>
          <div>
            <strong>Homuncula</strong>
            <span>Local agent</span>
          </div>
        </div>

        <div className="status-block">
          <span className={backendReady ? "status-dot live" : "status-dot"} />
          <div>
            <strong>{backendReady ? "Runtime online" : "Runtime starting"}</strong>
            <span>
              {health?.provider?.ok
                ? health.provider.model
                : "Waiting for local model"}
            </span>
          </div>
        </div>

        <div className="rail-metrics">
          <div>
            <span>Active</span>
            <strong>{activeCount}</strong>
          </div>
          <div>
            <span>Approvals</span>
            <strong>{actions.length}</strong>
          </div>
        </div>

        <div className="workspace">
          <span>Workspace</span>
          <strong>{health?.workspace || "Connecting..."}</strong>
        </div>

        <div className="rail-footer">
          <span>Everything here runs through the local Sentinel.</span>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <span className="eyebrow">Persistent local intelligence</span>
            <h1>What should stay on your mind?</h1>
          </div>
          <div className="provider-pill">
            <span className={health?.provider?.ok ? "status-dot live" : "status-dot"} />
            {health?.provider?.ok ? "Ollama connected" : "Ollama offline"}
          </div>
        </header>

        {error && <div className="error-banner">{error}</div>}

        <section className="grid">
          <div className="card chat-card">
            <div className="card-heading">
              <div>
                <span className="eyebrow">Conversation</span>
                <h2>Local agent</h2>
              </div>
              <span className="quiet">Tool calls are governed</span>
            </div>

            <div className="transcript">
              {chat.map((line, index) => (
                <div className={"message " + line.role} key={index}>
                  <span>{line.role === "user" ? "You" : line.role === "assistant" ? "Homuncula" : "Runtime"}</span>
                  <p>{line.content}</p>
                </div>
              ))}
              {busy && (
                <div className="message assistant thinking">
                  <span>Homuncula</span>
                  <p>Working locally...</p>
                </div>
              )}
            </div>

            <form className="composer" onSubmit={sendMessage}>
              <textarea
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                placeholder="Ask about this computer or give Homuncula a task"
                rows={3}
              />
              <button disabled={busy || !prompt.trim()} type="submit">
                Send
              </button>
            </form>
          </div>

          <div className="stack">
            <div className="card">
              <div className="card-heading">
                <div>
                  <span className="eyebrow">Responsibilities</span>
                  <h2>Work that persists</h2>
                </div>
                <span className="count">{responsibilities.length}</span>
              </div>

              <form className="responsibility-form" onSubmit={createResponsibility}>
                <input
                  value={responsibilityTitle}
                  onChange={(event) => setResponsibilityTitle(event.target.value)}
                  placeholder="Responsibility title"
                />
                <textarea
                  value={responsibilityObjective}
                  onChange={(event) => setResponsibilityObjective(event.target.value)}
                  placeholder="What should Homuncula keep track of or continue working on?"
                  rows={3}
                />
                <button
                  className="secondary"
                  disabled={
                    busy ||
                    !responsibilityTitle.trim() ||
                    !responsibilityObjective.trim()
                  }
                  type="submit"
                >
                  Create responsibility
                </button>
              </form>

              <div className="compact-list">
                {responsibilities.length === 0 && (
                  <div className="empty">No persistent responsibilities yet.</div>
                )}
                {responsibilities.slice(0, 5).map((item) => (
                  <div className="responsibility" key={item.id}>
                    <div>
                      <strong>{item.title}</strong>
                      <p>{item.objective}</p>
                    </div>
                    <span className={"badge " + item.status}>{item.status}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="card approvals-card">
              <div className="card-heading">
                <div>
                  <span className="eyebrow">Sentinel</span>
                  <h2>Pending approvals</h2>
                </div>
                <span className="count">{actions.length}</span>
              </div>

              <div className="compact-list">
                {actions.length === 0 && (
                  <div className="empty">Nothing is waiting for permission.</div>
                )}
                {actions.slice(0, 4).map((action) => (
                  <div className="approval" key={action.id}>
                    <div>
                      <strong>{action.preview}</strong>
                      <p>{action.intent}</p>
                      <span>{action.capability}</span>
                    </div>
                    <div className="approval-actions">
                      <button
                        disabled={busy}
                        onClick={() => void approveAndRun(action)}
                        type="button"
                      >
                        Approve and run
                      </button>
                      <button
                        className="ghost"
                        disabled={busy}
                        onClick={() => void deny(action)}
                        type="button"
                      >
                        Deny
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section className="card activity-card">
          <div className="card-heading">
            <div>
              <span className="eyebrow">Activity</span>
              <h2>What happened, not hidden reasoning</h2>
            </div>
            <button className="ghost" onClick={() => void refresh()} type="button">
              Refresh
            </button>
          </div>

          <div className="activity-grid">
            {activity.length === 0 && (
              <div className="empty">Activity will appear here as the agent works.</div>
            )}
            {activity.slice(0, 12).map((item) => (
              <div className="activity-row" key={item.id}>
                <span className="activity-kind">{item.kind}</span>
                <strong>{item.message}</strong>
                <time>{relativeTime(item.created_at)}</time>
              </div>
            ))}
          </div>
        </section>
      </main>
    </div>
  );
}

export default App;
