import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

type View = "home" | "memory" | "findings" | "permissions" | "computer" | "activity";

type Health = {
  ok: boolean;
  version: string;
  workspace: string;
  proactive_enabled: boolean;
  browser_channel: string;
  secret_store: string;
  provider: {
    ok: boolean;
    model: string;
    base_url: string;
    selected_available?: boolean;
    available_models?: string[];
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

type Finding = {
  id: string;
  title: string;
  summary: string;
  evidence: string[];
  status: string;
  created_at: string;
};

type MemoryRecord = {
  id: string;
  scope: string;
  kind: string;
  content: string;
  source: string;
  confidence: number;
  created_at: string;
  last_used_at?: string | null;
  score?: number;
  revisions?: Array<{
    id: string;
    previous_content: string;
    reason: string;
    revised_at: string;
  }>;
};

type Grant = {
  id: string;
  capability: string;
  resource_pattern: string;
  expires_at?: string | null;
  created_at: string;
};

type ProcessRecord = {
  id: string;
  argv: string[];
  cwd: string;
  status: string;
  pid?: number | null;
  returncode?: number | null;
  started_at: string;
  completed_at?: string | null;
};

type WindowRecord = {
  ref: string;
  name: string;
  control_type?: string | null;
  class_name?: string | null;
};

type ChatLine = {
  role: "user" | "assistant" | "system";
  content: string;
};

const VIEW_COPY: Record<View, { eyebrow: string; title: string; subtitle: string }> = {
  home: {
    eyebrow: "Persistent local intelligence",
    title: "Stay responsible, not merely responsive.",
    subtitle: "Conversation, active responsibilities, and decisions that need you."
  },
  memory: {
    eyebrow: "Inspectable memory",
    title: "What Homuncula carries forward.",
    subtitle: "Search, inspect, and correct durable memory without erasing its history."
  },
  findings: {
    eyebrow: "Proactive observation",
    title: "Things worth your attention.",
    subtitle: "Read-only discoveries surfaced by responsibilities and event sources."
  },
  permissions: {
    eyebrow: "Sentinel",
    title: "Authority stays outside the model.",
    subtitle: "Review pending actions and scope standing grants by capability and resource."
  },
  computer: {
    eyebrow: "Host computer",
    title: "The local machine is the agent's world.",
    subtitle: "Inspect workspace, browser, native windows, and background processes."
  },
  activity: {
    eyebrow: "Operational provenance",
    title: "A readable account of what happened.",
    subtitle: "Actions and events, without exposing hidden model reasoning."
  }
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

function App() {
  const [view, setView] = useState<View>("home");
  const [health, setHealth] = useState<Health | null>(null);
  const [autonomyPaused, setAutonomyPaused] = useState(false);
  const [responsibilities, setResponsibilities] = useState<Responsibility[]>([]);
  const [actions, setActions] = useState<Action[]>([]);
  const [activity, setActivity] = useState<Activity[]>([]);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [memories, setMemories] = useState<MemoryRecord[]>([]);
  const [grants, setGrants] = useState<Grant[]>([]);
  const [processes, setProcesses] = useState<ProcessRecord[]>([]);
  const [windows, setWindows] = useState<WindowRecord[]>([]);
  const [computer, setComputer] = useState<any>(null);

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
  const [memoryQuery, setMemoryQuery] = useState("");
  const [selectedMemory, setSelectedMemory] = useState<MemoryRecord | null>(null);
  const [memoryEdit, setMemoryEdit] = useState("");
  const [memoryReason, setMemoryReason] = useState("");
  const [grantCapability, setGrantCapability] = useState("filesystem.write");
  const [grantPattern, setGrantPattern] = useState("*");

  const [busy, setBusy] = useState(false);
  const [backendReady, setBackendReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [
        nextHealth,
        nextState,
        nextResponsibilities,
        nextActions,
        nextActivity,
        nextFindings,
        nextMemories,
        nextGrants,
        nextProcesses
      ] = await Promise.all([
        window.homuncula.health(),
        window.homuncula.state(),
        window.homuncula.responsibilities(),
        window.homuncula.actions("pending"),
        window.homuncula.activity(),
        window.homuncula.findings(),
        window.homuncula.memory(),
        window.homuncula.grants(),
        window.homuncula.processes()
      ]);

      setHealth(nextHealth as Health);
      setAutonomyPaused(Boolean(nextState.autonomy_paused));
      setResponsibilities(nextResponsibilities as Responsibility[]);
      setActions(nextActions as Action[]);
      setActivity(nextActivity as Activity[]);
      setFindings(nextFindings as Finding[]);
      setMemories(nextMemories as MemoryRecord[]);
      setGrants(nextGrants as Grant[]);
      setProcesses(nextProcesses as ProcessRecord[]);
      setBackendReady(true);
      setError(null);
    } catch (cause) {
      setBackendReady(false);
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }, []);

  const refreshComputer = useCallback(async () => {
    try {
      const [status, windowState] = await Promise.all([
        window.homuncula.computerStatus(),
        window.homuncula.windows().catch(() => ({ windows: [] }))
      ]);
      setComputer(status);
      setWindows(windowState.windows || []);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    if (view === "computer") void refreshComputer();
  }, [view, refreshComputer]);

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
        // Runtime startup is retried by the normal refresh loop.
      }
    })();
  }, []);

  const activeCount = useMemo(
    () => responsibilities.filter((item) => item.status === "active").length,
    [responsibilities]
  );

  const newFindingCount = useMemo(
    () => findings.filter((item) => item.status === "new").length,
    [findings]
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
      await window.homuncula.createResponsibility(title, objective, "observe");
      setResponsibilityTitle("");
      setResponsibilityObjective("");
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  async function toggleAutonomy(): Promise<void> {
    setBusy(true);
    try {
      if (autonomyPaused) {
        await window.homuncula.resumeAutonomy();
      } else {
        await window.homuncula.pauseAutonomy();
      }
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  async function toggleResponsibility(item: Responsibility): Promise<void> {
    setBusy(true);
    try {
      await window.homuncula.updateResponsibility(item.id, {
        status: item.status === "active" ? "paused" : "active"
      });
      await refresh();
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
    } finally {
      setBusy(false);
    }
  }

  async function searchMemory(event: FormEvent): Promise<void> {
    event.preventDefault();
    setBusy(true);
    try {
      const result = await window.homuncula.memory(memoryQuery.trim() || undefined);
      setMemories(result as MemoryRecord[]);
    } finally {
      setBusy(false);
    }
  }

  function editMemory(memory: MemoryRecord): void {
    setSelectedMemory(memory);
    setMemoryEdit(memory.content);
    setMemoryReason("");
  }

  async function saveMemoryRevision(): Promise<void> {
    if (!selectedMemory || !memoryEdit.trim() || !memoryReason.trim()) return;
    setBusy(true);
    try {
      await window.homuncula.reviseMemory(
        selectedMemory.id,
        memoryEdit.trim(),
        memoryReason.trim(),
        selectedMemory.kind,
        selectedMemory.confidence
      );
      setSelectedMemory(null);
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  async function addGrant(event: FormEvent): Promise<void> {
    event.preventDefault();
    if (!grantCapability.trim() || !grantPattern.trim()) return;
    setBusy(true);
    try {
      await window.homuncula.addGrant(grantCapability.trim(), grantPattern.trim());
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  async function revokeGrant(id: string): Promise<void> {
    setBusy(true);
    try {
      await window.homuncula.revokeGrant(id);
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  const copy = VIEW_COPY[view];

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

        <nav className="nav">
          {(
            [
              ["home", "Home"],
              ["memory", "Memory"],
              ["findings", "Findings"],
              ["permissions", "Permissions"],
              ["computer", "Computer"],
              ["activity", "Activity"]
            ] as Array<[View, string]>
          ).map(([key, label]) => (
            <button
              className={view === key ? "nav-item active" : "nav-item"}
              key={key}
              onClick={() => setView(key)}
              type="button"
            >
              <span>{label}</span>
              {key === "findings" && newFindingCount > 0 && (
                <b>{newFindingCount}</b>
              )}
              {key === "permissions" && actions.length > 0 && (
                <b>{actions.length}</b>
              )}
            </button>
          ))}
        </nav>

        <div className="rail-spacer" />

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

        <div className="workspace">
          <span>Workspace</span>
          <strong>{health?.workspace || "Connecting..."}</strong>
        </div>

        <button
          className={autonomyPaused ? "take-control paused" : "take-control"}
          disabled={!backendReady || busy}
          onClick={() => void toggleAutonomy()}
          type="button"
        >
          {autonomyPaused ? "Resume autonomy" : "Take control"}
        </button>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <span className="eyebrow">{copy.eyebrow}</span>
            <h1>{copy.title}</h1>
            <p>{copy.subtitle}</p>
          </div>
          <div className="provider-pill">
            <span className={health?.provider?.ok ? "status-dot live" : "status-dot"} />
            {health?.provider?.ok ? "Local model connected" : "Local model offline"}
          </div>
        </header>

        {autonomyPaused && (
          <div className="pause-banner">
            Autonomous wakes are paused. Direct conversation and inspection still work.
          </div>
        )}
        {error && <div className="error-banner">{error}</div>}

        {view === "home" && (
          <>
            <section className="metrics-row">
              <div><span>Active responsibilities</span><strong>{activeCount}</strong></div>
              <div><span>New findings</span><strong>{newFindingCount}</strong></div>
              <div><span>Waiting approvals</span><strong>{actions.length}</strong></div>
              <div><span>Durable memories</span><strong>{memories.length}</strong></div>
            </section>

            <section className="grid">
              <div className="card chat-card">
                <div className="card-heading">
                  <div>
                    <span className="eyebrow">Conversation</span>
                    <h2>Work with the same persistent agent</h2>
                  </div>
                  <span className="quiet">Tools are governed by Sentinel</span>
                </div>

                <div className="transcript">
                  {chat.map((line, index) => (
                    <div className={"message " + line.role} key={index}>
                      <span>
                        {line.role === "user"
                          ? "You"
                          : line.role === "assistant"
                            ? "Homuncula"
                            : "Runtime"}
                      </span>
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
                    placeholder="Ask, delegate, investigate, or create something"
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
                      <h2>Work that survives the chat</h2>
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
                      placeholder="What should Homuncula continue owning?"
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
                    {responsibilities.slice(0, 6).map((item) => (
                      <div className="responsibility" key={item.id}>
                        <div>
                          <strong>{item.title}</strong>
                          <p>{item.objective}</p>
                        </div>
                        <button
                          className="mini ghost"
                          disabled={busy}
                          onClick={() => void toggleResponsibility(item)}
                          type="button"
                        >
                          {item.status === "active" ? "Pause" : "Resume"}
                        </button>
                      </div>
                    ))}
                  </div>
                </div>

                <ApprovalCard
                  actions={actions}
                  busy={busy}
                  approve={approveAndRun}
                  deny={deny}
                />
              </div>
            </section>
          </>
        )}

        {view === "memory" && (
          <section className="panel-grid">
            <div className="card panel-main">
              <div className="card-heading">
                <div>
                  <span className="eyebrow">Hybrid retrieval</span>
                  <h2>Durable memory</h2>
                </div>
                <span className="count">{memories.length}</span>
              </div>
              <form className="search-bar" onSubmit={searchMemory}>
                <input
                  value={memoryQuery}
                  onChange={(event) => setMemoryQuery(event.target.value)}
                  placeholder="Search facts, commitments, decisions, relationships..."
                />
                <button type="submit">Search</button>
                <button
                  className="ghost"
                  onClick={() => {
                    setMemoryQuery("");
                    void refresh();
                  }}
                  type="button"
                >
                  All
                </button>
              </form>
              <div className="memory-grid">
                {memories.map((memory) => (
                  <button
                    className="memory-card"
                    key={memory.id}
                    onClick={() => editMemory(memory)}
                    type="button"
                  >
                    <div>
                      <span className="memory-kind">{memory.kind}</span>
                      <span className="confidence">
                        {Math.round(memory.confidence * 100)}%
                      </span>
                    </div>
                    <p>{memory.content}</p>
                    <footer>
                      <span>{memory.source}</span>
                      <span>{relativeTime(memory.created_at)}</span>
                    </footer>
                  </button>
                ))}
              </div>
            </div>

            <div className="card inspector">
              <div className="card-heading">
                <div>
                  <span className="eyebrow">Correction</span>
                  <h2>{selectedMemory ? "Revise memory" : "Select a memory"}</h2>
                </div>
              </div>
              {selectedMemory ? (
                <div className="inspector-body">
                  <label>
                    Durable content
                    <textarea
                      rows={8}
                      value={memoryEdit}
                      onChange={(event) => setMemoryEdit(event.target.value)}
                    />
                  </label>
                  <label>
                    Why this changed
                    <input
                      value={memoryReason}
                      onChange={(event) => setMemoryReason(event.target.value)}
                      placeholder="Correction, clarification, changed preference..."
                    />
                  </label>
                  <button
                    disabled={busy || !memoryEdit.trim() || !memoryReason.trim()}
                    onClick={() => void saveMemoryRevision()}
                    type="button"
                  >
                    Save revision
                  </button>
                  <div className="revision-note">
                    The previous value is retained in revision history.
                  </div>
                </div>
              ) : (
                <div className="empty inspector-empty">
                  Choose a memory to inspect or correct it.
                </div>
              )}
            </div>
          </section>
        )}

        {view === "findings" && (
          <section className="card">
            <div className="card-heading">
              <div>
                <span className="eyebrow">Read-only proactive research</span>
                <h2>Findings</h2>
              </div>
              <span className="count">{findings.length}</span>
            </div>
            <div className="finding-grid">
              {findings.length === 0 && (
                <div className="empty">Nothing currently needs your attention.</div>
              )}
              {findings.map((finding) => (
                <article className="finding-card" key={finding.id}>
                  <div>
                    <span className={"badge " + finding.status}>{finding.status}</span>
                    <time>{relativeTime(finding.created_at)}</time>
                  </div>
                  <h3>{finding.title}</h3>
                  <p>{finding.summary}</p>
                  {finding.evidence?.length > 0 && (
                    <details>
                      <summary>Evidence</summary>
                      {finding.evidence.map((item, index) => (
                        <p key={index}>{item}</p>
                      ))}
                    </details>
                  )}
                </article>
              ))}
            </div>
          </section>
        )}

        {view === "permissions" && (
          <section className="panel-grid permissions-grid">
            <ApprovalCard
              actions={actions}
              busy={busy}
              approve={approveAndRun}
              deny={deny}
              expanded
            />

            <div className="card">
              <div className="card-heading">
                <div>
                  <span className="eyebrow">Progressive trust</span>
                  <h2>Standing grants</h2>
                </div>
                <span className="count">{grants.length}</span>
              </div>
              <form className="grant-form" onSubmit={addGrant}>
                <label>
                  Capability
                  <input
                    value={grantCapability}
                    onChange={(event) => setGrantCapability(event.target.value)}
                    placeholder="filesystem.write"
                  />
                </label>
                <label>
                  Resource pattern
                  <input
                    value={grantPattern}
                    onChange={(event) => setGrantPattern(event.target.value)}
                    placeholder="src/*"
                  />
                </label>
                <button type="submit" disabled={busy}>Add grant</button>
              </form>
              <div className="compact-list">
                {grants.length === 0 && (
                  <div className="empty">
                    No standing grants. Sensitive actions will ask every time.
                  </div>
                )}
                {grants.map((grant) => (
                  <div className="grant-row" key={grant.id}>
                    <div>
                      <strong>{grant.capability}</strong>
                      <span>{grant.resource_pattern}</span>
                    </div>
                    <button
                      className="mini ghost"
                      disabled={busy}
                      onClick={() => void revokeGrant(grant.id)}
                      type="button"
                    >
                      Revoke
                    </button>
                  </div>
                ))}
              </div>
            </div>
          </section>
        )}

        {view === "computer" && (
          <section className="computer-layout">
            <div className="card">
              <div className="card-heading">
                <div>
                  <span className="eyebrow">Host status</span>
                  <h2>Local computer</h2>
                </div>
                <button className="ghost" onClick={() => void refreshComputer()} type="button">
                  Refresh
                </button>
              </div>
              <div className="computer-facts">
                <div><span>Workspace</span><strong>{computer?.workspace || health?.workspace}</strong></div>
                <div><span>Browser</span><strong>{computer?.browser?.started ? computer.browser.url || "Open" : "Idle"}</strong></div>
                <div><span>Browser engine</span><strong>{computer?.browser?.channel || health?.browser_channel || "Unknown"}</strong></div>
                <div><span>Autonomy</span><strong>{autonomyPaused ? "Paused" : "Running"}</strong></div>
              </div>
            </div>

            <div className="card">
              <div className="card-heading">
                <div>
                  <span className="eyebrow">UI Automation</span>
                  <h2>Visible Windows applications</h2>
                </div>
                <span className="count">{windows.length}</span>
              </div>
              <div className="window-grid">
                {windows.length === 0 && (
                  <div className="empty">
                    No Windows UI Automation snapshot is available on this platform.
                  </div>
                )}
                {windows.slice(0, 24).map((windowItem) => (
                  <div className="window-card" key={windowItem.ref}>
                    <strong>{windowItem.name || "Untitled window"}</strong>
                    <span>{windowItem.control_type || windowItem.class_name || "Window"}</span>
                    <code>{windowItem.ref.slice(0, 16)}...</code>
                  </div>
                ))}
              </div>
            </div>

            <div className="card span-two">
              <div className="card-heading">
                <div>
                  <span className="eyebrow">Background workers</span>
                  <h2>Processes</h2>
                </div>
                <span className="count">{processes.length}</span>
              </div>
              <div className="process-table">
                {processes.length === 0 && (
                  <div className="empty">No background process history yet.</div>
                )}
                {processes.map((process) => (
                  <div className="process-row" key={process.id}>
                    <span className={"badge " + process.status}>{process.status}</span>
                    <code>{process.argv.join(" ")}</code>
                    <span>{process.cwd}</span>
                    <time>{relativeTime(process.started_at)}</time>
                  </div>
                ))}
              </div>
            </div>
          </section>
        )}

        {view === "activity" && (
          <section className="card">
            <div className="card-heading">
              <div>
                <span className="eyebrow">Audit trail</span>
                <h2>Activity</h2>
              </div>
              <button className="ghost" onClick={() => void refresh()} type="button">
                Refresh
              </button>
            </div>
            <div className="activity-grid">
              {activity.length === 0 && (
                <div className="empty">Activity will appear here as the agent works.</div>
              )}
              {activity.map((item) => (
                <div className="activity-row" key={item.id}>
                  <span className="activity-kind">{item.kind}</span>
                  <strong>{item.message}</strong>
                  <time>{relativeTime(item.created_at)}</time>
                </div>
              ))}
            </div>
          </section>
        )}
      </main>
    </div>
  );
}

function ApprovalCard({
  actions,
  busy,
  approve,
  deny,
  expanded = false
}: {
  actions: Action[];
  busy: boolean;
  approve: (action: Action) => Promise<void>;
  deny: (action: Action) => Promise<void>;
  expanded?: boolean;
}) {
  return (
    <div className={"card approvals-card" + (expanded ? " panel-main" : "")}>
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
        {actions.map((action) => (
          <div className="approval" key={action.id}>
            <div>
              <strong>{action.preview}</strong>
              <p>{action.intent}</p>
              <span>{action.capability} · {action.target}</span>
            </div>
            <div className="approval-actions">
              <button
                disabled={busy}
                onClick={() => void approve(action)}
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
  );
}

export default App;
