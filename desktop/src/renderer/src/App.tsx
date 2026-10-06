import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

type View = "home" | "work" | "memory" | "findings" | "permissions" | "computer" | "activity";

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

type PlanStep = {
  id: string;
  position: number;
  title: string;
  detail: string;
  status: string;
  summary?: string | null;
};

type Plan = {
  id: string;
  responsibility_id: string;
  title: string;
  goal: string;
  status: string;
  current_step?: number | null;
  updated_at: string;
  steps: PlanStep[];
};

type Skill = {
  name: string;
  description: string;
  instructions: string;
  allowed_tools: string[];
  source: string;
};

type Verification = {
  id: string;
  responsibility_id?: string | null;
  kind: string;
  command: string[];
  cwd: string;
  status: string;
  returncode: number;
  stdout_summary: string;
  stderr_summary: string;
  created_at: string;
};

type StartupState = {
  supported: boolean;
  openAtLogin: boolean;
};

type ModelState = {
  ok: boolean;
  selected: string;
  available: string[];
  error?: string;
};

type VoiceState = {
  engine_available: boolean;
  asr: {
    installed: boolean;
    model: string;
  };
  tts: {
    installed: boolean;
    model: string;
    speakers: number;
    default_speaker: number;
  };
};

function encodeMonoWav(buffer: AudioBuffer, targetRate = 16000): Uint8Array {
  const sourceRate = buffer.sampleRate;
  const length = Math.max(1, Math.round(buffer.duration * targetRate));
  const mono = new Float32Array(length);

  for (let index = 0; index < length; index += 1) {
    const sourcePosition = (index * sourceRate) / targetRate;
    const left = Math.floor(sourcePosition);
    const right = Math.min(left + 1, buffer.length - 1);
    const mix = sourcePosition - left;
    let sample = 0;
    for (let channel = 0; channel < buffer.numberOfChannels; channel += 1) {
      const values = buffer.getChannelData(channel);
      const a = values[Math.min(left, values.length - 1)] || 0;
      const b = values[Math.min(right, values.length - 1)] || 0;
      sample += a + (b - a) * mix;
    }
    mono[index] = Math.max(-1, Math.min(1, sample / buffer.numberOfChannels));
  }

  const bytes = new Uint8Array(44 + mono.length * 2);
  const view = new DataView(bytes.buffer);
  const writeText = (offset: number, value: string): void => {
    for (let index = 0; index < value.length; index += 1) {
      view.setUint8(offset + index, value.charCodeAt(index));
    }
  };

  writeText(0, "RIFF");
  view.setUint32(4, 36 + mono.length * 2, true);
  writeText(8, "WAVE");
  writeText(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, targetRate, true);
  view.setUint32(28, targetRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeText(36, "data");
  view.setUint32(40, mono.length * 2, true);
  for (let index = 0; index < mono.length; index += 1) {
    view.setInt16(44 + index * 2, Math.round(mono[index] * 32767), true);
  }
  return bytes;
}

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
  work: {
    eyebrow: "Durable execution",
    title: "Plans, skills, and proof of work.",
    subtitle: "See what the agent intends to do, what reusable procedures it knows, and what checks actually passed."
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
  const [plans, setPlans] = useState<Plan[]>([]);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [verification, setVerification] = useState<Verification[]>([]);
  const [windows, setWindows] = useState<WindowRecord[]>([]);
  const [computer, setComputer] = useState<any>(null);
  const [models, setModels] = useState<ModelState | null>(null);
  const [modelInput, setModelInput] = useState("qwen3:8b");
  const [modelBusy, setModelBusy] = useState(false);
  const [modelMessage, setModelMessage] = useState<string | null>(null);
  const [voice, setVoice] = useState<VoiceState | null>(null);
  const [voiceBusy, setVoiceBusy] = useState(false);
  const [voiceMessage, setVoiceMessage] = useState<string | null>(null);
  const [recording, setRecording] = useState(false);
  const [voiceReplies, setVoiceReplies] = useState(
    () => window.localStorage.getItem("homuncula.voiceReplies") === "1"
  );
  const [voiceSpeaker, setVoiceSpeaker] = useState(
    () => Number(window.localStorage.getItem("homuncula.voiceSpeaker") || "10")
  );
  const [voiceSpeed, setVoiceSpeed] = useState(
    () => Number(window.localStorage.getItem("homuncula.voiceSpeed") || "1")
  );
  const recorderRef = useRef<MediaRecorder | null>(null);
  const voiceStreamRef = useRef<MediaStream | null>(null);
  const voiceChunksRef = useRef<Blob[]>([]);
  const [startup, setStartup] = useState<StartupState>({
    supported: false,
    openAtLogin: false
  });

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
        nextProcesses,
        nextPlans,
        nextSkills,
        nextVerification,
        nextModels,
        nextVoice
      ] = await Promise.all([
        window.homuncula.health(),
        window.homuncula.state(),
        window.homuncula.responsibilities(),
        window.homuncula.actions("pending"),
        window.homuncula.activity(),
        window.homuncula.findings(),
        window.homuncula.memory(),
        window.homuncula.grants(),
        window.homuncula.processes(),
        window.homuncula.plans(),
        window.homuncula.skills(),
        window.homuncula.verification(),
        window.homuncula.models(),
        window.homuncula.voiceStatus()
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
      setPlans(nextPlans as Plan[]);
      setSkills(nextSkills as Skill[]);
      setVerification(nextVerification as Verification[]);
      setModels(nextModels as ModelState);
      setVoice(nextVoice as VoiceState);
      if ((nextModels as ModelState).selected) {
        setModelInput((nextModels as ModelState).selected);
      }
      setBackendReady(true);
      setError(null);
    } catch (cause) {
      setBackendReady(false);
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }, []);

  const refreshComputer = useCallback(async () => {
    try {
      const [status, windowState, startupState] = await Promise.all([
        window.homuncula.computerStatus(),
        window.homuncula.windows().catch(() => ({ windows: [] })),
        window.homuncula.startupSettings()
      ]);
      setComputer(status);
      setWindows(windowState.windows || []);
      setStartup(startupState as StartupState);
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
      if (voiceReplies && voice?.tts.installed) {
        void speakText(String(result.content || ""));
      }
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

  async function installOllama(): Promise<void> {
    setModelBusy(true);
    setModelMessage("Installing Ollama on Windows...");
    try {
      const result = await window.homuncula.installOllama();
      if (result.returncode !== 0) {
        throw new Error(result.stderr || result.stdout || "Ollama installation failed.");
      }
      setModelMessage("Ollama installed. Restarting the local host...");
      await window.homuncula.restartHost();
      setBackendReady(false);
    } catch (cause) {
      setModelMessage(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setModelBusy(false);
    }
  }

  async function pullModel(): Promise<void> {
    const name = modelInput.trim();
    if (!name) return;
    setModelBusy(true);
    setModelMessage("Pulling " + name + " locally. Large models can take a while.");
    try {
      await window.homuncula.pullModel(name);
      setModelMessage(name + " is installed and selected.");
      await refresh();
    } catch (cause) {
      setModelMessage(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setModelBusy(false);
    }
  }

  async function selectModel(name: string): Promise<void> {
    setModelBusy(true);
    try {
      await window.homuncula.selectModel(name);
      setModelInput(name);
      setModelMessage(name + " selected.");
      await refresh();
    } catch (cause) {
      setModelMessage(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setModelBusy(false);
    }
  }

  async function installVoice(component: "asr" | "tts"): Promise<void> {
    setVoiceBusy(true);
    setVoiceMessage(
      component === "asr"
        ? "Downloading the local speech recognition model..."
        : "Downloading the local Kokoro voice model..."
    );
    try {
      const next = await window.homuncula.installVoice(component);
      setVoice(next as VoiceState);
      setVoiceMessage(
        component === "asr"
          ? "Local speech recognition is ready."
          : "Local Kokoro speech output is ready."
      );
    } catch (cause) {
      setVoiceMessage(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setVoiceBusy(false);
    }
  }

  async function speakText(text: string): Promise<void> {
    if (!voice?.tts.installed || !text.trim()) return;
    setVoiceBusy(true);
    try {
      const bytes = await window.homuncula.synthesizeVoice(
        text,
        voiceSpeaker,
        voiceSpeed
      );
      const copy = new Uint8Array(bytes);
      const blob = new Blob([copy.buffer], { type: "audio/wav" });
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.addEventListener(
        "ended",
        () => URL.revokeObjectURL(url),
        { once: true }
      );
      audio.addEventListener(
        "error",
        () => URL.revokeObjectURL(url),
        { once: true }
      );
      await audio.play();
    } catch (cause) {
      setVoiceMessage(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setVoiceBusy(false);
    }
  }

  async function startRecording(): Promise<void> {
    if (!voice?.asr.installed || recording) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true
        },
        video: false
      });
      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : "";
      const recorder = mimeType
        ? new MediaRecorder(stream, { mimeType })
        : new MediaRecorder(stream);
      voiceChunksRef.current = [];
      voiceStreamRef.current = stream;
      recorderRef.current = recorder;
      recorder.addEventListener("dataavailable", (event) => {
        if (event.data.size > 0) voiceChunksRef.current.push(event.data);
      });
      recorder.start();
      setRecording(true);
      setVoiceMessage("Listening locally...");
    } catch (cause) {
      setVoiceMessage(cause instanceof Error ? cause.message : String(cause));
    }
  }

  async function stopRecording(): Promise<void> {
    const recorder = recorderRef.current;
    if (!recorder || recorder.state === "inactive") return;

    setVoiceBusy(true);
    try {
      await new Promise<void>((resolveStop) => {
        recorder.addEventListener("stop", () => resolveStop(), { once: true });
        recorder.stop();
      });
      const blob = new Blob(voiceChunksRef.current, {
        type: recorder.mimeType || "audio/webm"
      });
      const encoded = await blob.arrayBuffer();
      const context = new AudioContext();
      try {
        const decoded = await context.decodeAudioData(encoded.slice(0));
        const wav = encodeMonoWav(decoded, 16000);
        const result = await window.homuncula.transcribeVoice(wav);
        const text = String(result.text || "").trim();
        if (text) {
          setPrompt((current) => current.trim() ? current.trim() + " " + text : text);
          setVoiceMessage("Transcribed locally.");
        } else {
          setVoiceMessage("No speech was detected.");
        }
      } finally {
        await context.close();
      }
    } catch (cause) {
      setVoiceMessage(cause instanceof Error ? cause.message : String(cause));
    } finally {
      voiceStreamRef.current?.getTracks().forEach((track) => track.stop());
      voiceStreamRef.current = null;
      recorderRef.current = null;
      voiceChunksRef.current = [];
      setRecording(false);
      setVoiceBusy(false);
    }
  }

  function setSpokenReplies(enabled: boolean): void {
    setVoiceReplies(enabled);
    window.localStorage.setItem("homuncula.voiceReplies", enabled ? "1" : "0");
  }

  function updateVoiceSpeaker(value: number): void {
    const next = Math.max(0, Math.min(10, Math.round(value)));
    setVoiceSpeaker(next);
    window.localStorage.setItem("homuncula.voiceSpeaker", String(next));
  }

  function updateVoiceSpeed(value: number): void {
    const next = Math.max(0.5, Math.min(2.0, value));
    setVoiceSpeed(next);
    window.localStorage.setItem("homuncula.voiceSpeed", String(next));
  }

  async function restartHost(): Promise<void> {
    setBusy(true);
    setBackendReady(false);
    try {
      await window.homuncula.restartHost();
      setError("Local host restarted. Health checks will reconnect automatically.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  async function toggleLaunchAtLogin(): Promise<void> {
    setBusy(true);
    try {
      const next = await window.homuncula.setLaunchAtLogin(!startup.openAtLogin);
      setStartup(next as StartupState);
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
              ["work", "Work"],
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
        {error && (
          <div className="error-banner">
            <span>{error}</span>
            {!backendReady && (
              <button className="ghost" disabled={busy} onClick={() => void restartHost()} type="button">
                Restart host
              </button>
            )}
          </div>
        )}

        {view === "home" && (
          <>

            {(!health?.provider?.ok || health.provider.selected_available === false || modelMessage) && (
              <section className="model-setup card">
                <div className="card-heading">
                  <div>
                    <span className="eyebrow">Local model setup</span>
                    <h2>
                      {!health?.provider?.ok
                        ? "Connect the local inference engine"
                        : health.provider.selected_available === false
                          ? "Install the selected model"
                          : "Local model ready"}
                    </h2>
                  </div>
                  <span className={health?.provider?.ok ? "badge active" : "badge failed"}>
                    {health?.provider?.ok ? "Ollama detected" : "Ollama unavailable"}
                  </span>
                </div>
                <div className="model-setup-body">
                  {!health?.provider?.ok && (
                    <div className="model-step">
                      <div>
                        <strong>1. Install Ollama</strong>
                        <p>Homuncula uses the local Ollama service by default. Installation is performed directly on this Windows PC.</p>
                      </div>
                      <button disabled={modelBusy} onClick={() => void installOllama()} type="button">
                        Install Ollama
                      </button>
                    </div>
                  )}
                  <div className="model-step">
                    <div>
                      <strong>{health?.provider?.ok ? "Choose or install a model" : "2. Install a model after Ollama starts"}</strong>
                      <p>The model stays on this machine. The default is qwen3:8b, but any installed Ollama chat model can be selected.</p>
                    </div>
                    <div className="model-controls">
                      <input
                        value={modelInput}
                        onChange={(event) => setModelInput(event.target.value)}
                        placeholder="qwen3:8b"
                      />
                      <button
                        disabled={modelBusy || !health?.provider?.ok || !modelInput.trim()}
                        onClick={() => void pullModel()}
                        type="button"
                      >
                        Pull model
                      </button>
                    </div>
                  </div>
                  {models?.available?.length ? (
                    <div className="model-list">
                      {models.available.map((name) => (
                        <button
                          className={name === models.selected ? "model-choice selected" : "model-choice"}
                          disabled={modelBusy}
                          key={name}
                          onClick={() => void selectModel(name)}
                          type="button"
                        >
                          <strong>{name}</strong>
                          <span>{name === models.selected ? "Selected" : "Use model"}</span>
                        </button>
                      ))}
                    </div>
                  ) : null}
                  {modelMessage && <div className="model-message">{modelMessage}</div>}
                </div>
              </section>
            )}

            {voice && (!voice.asr.installed || !voice.tts.installed || voiceMessage) && (
              <section className="voice-setup card">
                <div className="card-heading">
                  <div>
                    <span className="eyebrow">Local voice</span>
                    <h2>Private speech input and output</h2>
                  </div>
                  <span className={voice.engine_available ? "badge active" : "badge failed"}>
                    {voice.engine_available ? "Voice runtime ready" : "Voice runtime unavailable"}
                  </span>
                </div>
                <div className="voice-setup-body">
                  <div className="voice-component">
                    <div>
                      <strong>Speech recognition</strong>
                      <p>{voice.asr.installed ? "Whisper tiny.en int8 is installed." : "Download the local Whisper speech recognition model."}</p>
                    </div>
                    <button
                      disabled={voiceBusy || voice.asr.installed || !voice.engine_available}
                      onClick={() => void installVoice("asr")}
                      type="button"
                    >
                      {voice.asr.installed ? "Installed" : "Install speech input"}
                    </button>
                  </div>
                  <div className="voice-component">
                    <div>
                      <strong>Speech output</strong>
                      <p>{voice.tts.installed ? "Kokoro voice output is installed." : "Download the high-quality local Kokoro voice model."}</p>
                    </div>
                    <button
                      disabled={voiceBusy || voice.tts.installed || !voice.engine_available}
                      onClick={() => void installVoice("tts")}
                      type="button"
                    >
                      {voice.tts.installed ? "Installed" : "Install Kokoro voice"}
                    </button>
                  </div>
                  {voice.tts.installed && (
                    <div className="voice-preferences">
                      <label>
                        Speaker
                        <input
                          max={10}
                          min={0}
                          onChange={(event) => updateVoiceSpeaker(Number(event.target.value))}
                          type="number"
                          value={voiceSpeaker}
                        />
                      </label>
                      <label>
                        Speed
                        <input
                          max={2}
                          min={0.5}
                          onChange={(event) => updateVoiceSpeed(Number(event.target.value))}
                          step={0.05}
                          type="number"
                          value={voiceSpeed}
                        />
                      </label>
                      <button
                        className="ghost"
                        disabled={voiceBusy}
                        onClick={() => void speakText("Homuncula local voice is ready.")}
                        type="button"
                      >
                        Test voice
                      </button>
                    </div>
                  )}
                  {voiceMessage && <div className="model-message">{voiceMessage}</div>}
                </div>
              </section>
            )}

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
                  <div className="composer-main">
                  <textarea
                    value={prompt}
                    onChange={(event) => setPrompt(event.target.value)}
                    placeholder="Ask, delegate, investigate, or create something"
                    rows={3}
                  />
                  <div className="voice-controls">
                    <button
                      className={recording ? "voice-button recording" : "voice-button ghost"}
                      disabled={voiceBusy || !voice?.asr.installed}
                      onClick={() => void (recording ? stopRecording() : startRecording())}
                      type="button"
                    >
                      {recording ? "Stop" : "Mic"}
                    </button>
                    <button
                      className={voiceReplies ? "voice-button active" : "voice-button ghost"}
                      disabled={!voice?.tts.installed}
                      onClick={() => setSpokenReplies(!voiceReplies)}
                      type="button"
                    >
                      {voiceReplies ? "Voice on" : "Voice off"}
                    </button>
                  </div>
                  </div>
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


        {view === "work" && (
          <section className="computer-layout">
            <div className="card span-two">
              <div className="card-heading">
                <div>
                  <span className="eyebrow">Execution state</span>
                  <h2>Durable plans</h2>
                </div>
                <span className="count">{plans.length}</span>
              </div>
              <div className="compact-list">
                {plans.length === 0 && (
                  <div className="empty">
                    Plans appear when a persistent responsibility prepares mutating work.
                  </div>
                )}
                {plans.map((plan) => (
                  <div className="approval" key={plan.id}>
                    <div>
                      <strong>{plan.title}</strong>
                      <p>{plan.goal}</p>
                      <span>{plan.status} · {plan.steps.filter((step) => step.status === "complete").length}/{plan.steps.length} complete</span>
                    </div>
                    <div className="compact-list">
                      {plan.steps.map((step) => (
                        <div className="grant-row" key={step.id}>
                          <div>
                            <strong>{step.position}. {step.title}</strong>
                            <span>{step.status}{step.summary ? " · " + step.summary : ""}</span>
                          </div>
                          <span className={"badge " + step.status}>{step.status}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="card">
              <div className="card-heading">
                <div>
                  <span className="eyebrow">Reusable procedures</span>
                  <h2>Local skills</h2>
                </div>
                <span className="count">{skills.length}</span>
              </div>
              <div className="compact-list">
                {skills.length === 0 && (
                  <div className="empty">No local skills have been installed yet.</div>
                )}
                {skills.map((skill) => (
                  <div className="grant-row" key={skill.name}>
                    <div>
                      <strong>{skill.name}</strong>
                      <span>{skill.description}</span>
                      <span>{skill.allowed_tools.length ? skill.allowed_tools.join(", ") : "No declared tool guidance"}</span>
                    </div>
                    <span className="badge">{skill.source}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="card">
              <div className="card-heading">
                <div>
                  <span className="eyebrow">Verification ledger</span>
                  <h2>Latest evidence</h2>
                </div>
                <span className="count">{verification.length}</span>
              </div>
              <div className="compact-list">
                {verification.length === 0 && (
                  <div className="empty">No test, quality, build, or inspection evidence has been recorded.</div>
                )}
                {verification.slice(0, 20).map((item) => (
                  <div className="grant-row" key={item.id}>
                    <div>
                      <strong>{item.kind} · {item.command.join(" ")}</strong>
                      <span>{item.cwd} · exit {item.returncode} · {relativeTime(item.created_at)}</span>
                    </div>
                    <span className={"badge " + item.status}>{item.status}</span>
                  </div>
                ))}
              </div>
            </div>
          </section>
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
                <div>
                  <span>Launch at login</span>
                  <strong>
                    {startup.supported
                      ? startup.openAtLogin
                        ? "Enabled"
                        : "Disabled"
                      : "Available in packaged app"}
                  </strong>
                </div>
              </div>
              <div className="computer-actions">
                <button
                  className="ghost"
                  disabled={busy || !startup.supported}
                  onClick={() => void toggleLaunchAtLogin()}
                  type="button"
                >
                  {startup.openAtLogin ? "Disable launch at login" : "Enable launch at login"}
                </button>
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
