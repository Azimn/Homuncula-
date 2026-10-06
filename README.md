# Homuncula

Homuncula is a Windows-first, local-first persistent AI agent platform. It is designed to provide the proactive desktop experience associated with systems such as Meta Muse and OpenAI Dots while keeping the computer, memory, model, task state, skills, voice, permissions, and audit trail under the user's control.

## Current status

Homuncula v0.3 is an integrated local desktop agent. The Electron application manages a packaged local `agentd` runtime, persistent responsibilities, durable plans, event-driven wakes, hybrid memory, local skills, governed browser and Windows UI control, native notifications, launch-at-login, local model setup, and fully local voice.

The runtime stores durable state in SQLite and keeps authority outside the language model through Sentinel. Read-only inspection is scoped. Mutations become typed actions that either match an explicit grant or wait for approval. Observation-triggered work cannot silently consume standing mutation grants.

## Product contract

| Principle | Implementation |
| --- | --- |
| Local by default | SQLite, localhost `agentd`, Ollama, local speech recognition, local TTS |
| Responsibility over chat | Goals, plans, wakes, findings, and verification survive individual turns |
| Event driven | Filesystem, Git, process, runtime, and scheduled events resume work |
| Model independent | Persistent state and authority live outside the rendering model |
| Governed action | Sentinel evaluates typed capability requests before execution |
| Host native | Playwright and Windows UI Automation operate on the user's PC |
| Inspectable memory | Hybrid lexical and semantic retrieval preserves provenance and revisions |
| Progressive trust | Grants are scoped by capability, resource, and optional expiration |
| Verifiable work | Test, quality, build, and inspection evidence are persisted separately |
| Private voice | Microphone transcription and Kokoro speech output run locally after model setup |

## Architecture

    Electron desktop
          |
          | authenticated IPC
          v
       agentd
          |
     responsibility engine
      /    |     |     \
  memory  plans  events  skills
      \    |     |     /
       context compiler
              |
          local model
              |
        tool proposals
              |
           Sentinel
              |
      governed capabilities
       /      |       |      \
    files  processes browser Windows UI

Voice is a parallel local interface. The renderer records microphone audio, converts it to 16 kHz mono PCM WAV locally, and sends it through a narrow Electron IPC bridge to authenticated `agentd`. Speech recognition uses sherpa-onnx with Whisper tiny.en int8. Speech output uses sherpa-onnx with Kokoro. Generated WAV audio returns to the renderer for local playback.

See `docs/ARCHITECTURE.md` for the trust and persistence contract.

## Windows quick start

For development from the repository:

    .\run-desktop.ps1

The launcher creates the Python environment, installs the runtime including the local voice engine, installs desktop dependencies when needed, and starts Electron.

For a packaged release, install the generated NSIS executable. Homuncula can detect Ollama, install it through Windows Package Manager when missing, pull a local model, and persist the selected model from inside the app.

Voice models are intentionally not embedded in the installer. The Home screen can download the local speech-recognition model and Kokoro voice model into `%USERPROFILE%\.homuncula\voice\models`. After that initial model download, speech recognition and synthesis do not require an API or subscription.

The default language model is `qwen3:8b`, but any installed Ollama chat model can be selected in the desktop.

## Persistent local data

User-owned state lives outside the application install directory under `%USERPROFILE%\.homuncula`. This includes the SQLite database, skills, browser profile, protected secrets, and downloaded voice models. Application upgrades do not replace that directory, and uninstall does not silently remove it.

The default packaged workspace is `%USERPROFILE%\Homuncula Workspace`.

## Local voice

Speech input is optional. When installed, Whisper tiny.en int8 transcribes microphone audio locally. The renderer uses the browser media APIs only for capture and local decoding, then sends PCM WAV to `agentd` over authenticated local IPC.

Speech output is optional. Kokoro generates speech locally with selectable speaker and speed. Spoken replies can be enabled or disabled independently of text chat.

The voice model downloader streams official sherpa-onnx model archives, rejects path traversal and archive links before extraction, and stores models outside the application bundle.

## Host control and safety

Homuncula prefers structured interfaces over screenshot clicking. Workspace files use scoped path APIs. Processes use argv-based execution with no shell. The browser uses Playwright semantic structure and restricts direct navigation to HTTP and HTTPS. Native Windows applications use UI Automation references with stale-reference detection.

Sentinel records externally meaningful actions before execution. Unknown capabilities are denied. Sensitive mutations require approval unless a matching explicit grant exists. Persistent autonomous mutation also requires a durable plan.

A per-turn loop guard stops repeated no-progress tool calls. A separate verification ledger records real command results so the model cannot treat an attempted check as proof of success.

## Proactivity and learning

Responsibilities can wake from concrete future dependencies and local events. Observation mode remains read-only, but it can surface findings or propose actions for approval.

A bounded post-turn reviewer can extract a small number of high-confidence durable memories. Reusable skill suggestions become pending Sentinel actions rather than silent self-modification. Concurrent reviews are coalesced per thread and duplicate pending skill proposals are suppressed.

## Packaging and validation

Windows packaging freezes `agentd` with PyInstaller, including Playwright, pywinauto, and sherpa-onnx native components, then packages Electron through NSIS. CI validates Python and Ruff on Windows and Ubuntu, a real Chromium integration test, Electron typecheck and production build, and the full Windows installer build.

See `docs/PACKAGING.md` for the release path.

## Project lineage

Homuncula is not a fork of Hermes Agent, Open Dots, MuseDesk, Muse, or Dots. Those projects informed individual architectural choices. Homuncula keeps its own small interfaces so model providers, memory mechanisms, host-control providers, voice engines, and desktop components can be replaced independently.

## License

MIT.
