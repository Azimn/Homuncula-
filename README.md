# Homuncula

Homuncula is a Windows-first, local-first persistent AI agent platform. It is designed to provide the proactive, continuous experience associated with systems such as Meta Muse and OpenAI Dots while keeping the computer, model, memory, permissions, plans, skills, browser profile, activity history, and long-running responsibilities under the user's control.

Homuncula is not a chat wrapper. Chat is one interface into a durable local runtime.

## Current status

Homuncula v0.2 is an integrated working local agent rather than a design-only foundation.

The repository contains a FastAPI agent runtime, SQLite system of record, authenticated Electron desktop, Ollama model provider, durable responsibilities and plans, persisted wake events, filesystem and Git event observation, background process events, hybrid lexical and semantic memory, memory revision history, provenance-preserving evidence dossiers, adversarial local evidence review, local reusable skills, bounded post-turn review, verification evidence, per-turn loop guardrails, native Windows UI Automation, a governed Playwright browser, workspace-scoped file and process tools, Windows DPAPI secret storage, native notifications, tray persistence, launch-at-login support, first-run Ollama and model setup, and a deterministic Sentinel approval boundary.

CI validates Python on Windows and Ubuntu, a real Chromium interaction and download harness, Electron typecheck and production build, and a full Windows PyInstaller plus NSIS package build. The packaged installer is generated as a CI artifact. Public code signing is supported by the release design but requires a signing certificate that is not stored in this repository.

## Product contract

| Principle | Current implementation |
| --- | --- |
| Local by default | SQLite, localhost agentd, Ollama, local browser profile, local secret store |
| Responsibility over chat | Responsibilities, threads, plans, wakes, events, findings |
| Event driven | Filesystem, Git, process completion, runtime startup, scheduled wakes |
| Model independent | Durable state remains outside the rendering model |
| Governed action | Sentinel records and evaluates typed capability requests before execution |
| Host native | Windows filesystem, process APIs, UI Automation, Playwright on the host |
| Inspectable memory | Source, scope, confidence, semantic index, lexical index, revisions |
| Evidence before belief | External claims retain source observations, review verdicts, unknowns, and promotion provenance |
| Progressive trust | Capability grants can be scoped by target and expiration |
| Verifiable execution | Command checks are recorded separately from ordinary activity |
| Local learning | Post-turn review may save durable memory and may only propose new skills |

## Architecture

The design separates cognition from authority.

    Electron desktop
          |
          | authenticated IPC
          v
       agentd
          |
          +-------------------------------+
          |                               |
    durable state                    event sources
    SQLite + skills              files / Git / process
          |                               |
          +-----------+-------------------+
                      |
             responsibility engine
              /       |        \
           memory    plans      wakes
              \       |        /
               context compiler
                      |
                 local model
                      |
                tool proposals
                      |
                 loop guard
                      |
                   Sentinel
                      |
       +--------------+----------------+
       |              |                |
    workspace       browser        Windows UI
    files/process   Playwright     UI Automation
       |
    verification evidence

The local model does not become the operating-system authority. Read operations are restricted by their providers. Mutating operations are represented as explicit capabilities. Sentinel either matches a standing grant, asks for approval, or denies the request. Unknown capabilities are denied.

Long-running responsibilities require a durable plan before autonomous mutating work. Observation-triggered turns may inspect state and create findings, but they cannot consume standing mutation grants silently.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the detailed contract.

## Windows installation

The CI workflow creates a complete Windows NSIS installer containing the Electron desktop and a PyInstaller-frozen agentd runtime.

User data is stored separately under:

    %USERPROFILE%\.homuncula

The default packaged workspace is:

    %USERPROFILE%\Homuncula Workspace

Uninstalling the application does not silently delete durable agent data.

The packaged desktop can remain in the system tray after its main window closes. It can optionally launch at login and stay hidden until needed. New proactive findings and approval requests can generate native desktop notifications when the Homuncula window is not focused.

## First run and local model setup

The packaged application does not require Python or Node.js to be installed by the end user.

Homuncula uses Ollama as its first local inference provider. When Ollama is unavailable on Windows, the Home view offers an explicit installation action through Windows Package Manager. Once Ollama is available, the same view can pull an Ollama model, display locally installed models, select a model, and persist that selection in the local database.

The default model name is:

    qwen3:8b

Model choice is not part of Homuncula's identity. Changing the model does not replace memories, responsibilities, plans, permissions, findings, or activity history.

## Development quick start

Development currently requires Python 3.11 or newer and Node.js 22 or newer.

From PowerShell in the repository root:

    .\run-desktop.ps1

The launcher creates the Python environment, installs the runtime and desktop dependencies when necessary, starts Electron, and lets Electron manage agentd.

For backend-only development:

    .\run-local.ps1

The local runtime listens on:

    http://127.0.0.1:43900

All API routes except the minimal health probe require the per-user owner token. Localhost alone is not treated as authentication.

A development model can still be selected through an environment variable:

    $env:HOMUNCULA_MODEL = "your-model"
    .\run-desktop.ps1

The desktop model selector persists subsequent choices in SQLite.

## Responsibilities, plans, and proactivity

A responsibility is durable work that survives a chat turn or application restart. It owns a conversation thread and can wake because of time, filesystem changes, Git changes, process completion, or runtime events.

Autonomous mutating work requires an active durable plan. Plans persist their ordered steps, current step, summaries, blocked state, completion state, and failure state.

Observation mode is intentionally read-only. It can inspect the workspace, browser, processes, memory, and Windows UI, then create a finding or a proposed action. A proactive observation cannot silently use an existing mutation grant.

The desktop includes a global Take Control switch that pauses autonomous wakes without disabling direct conversation or inspection.

## Memory and local learning

Memory uses SQLite as the system of record. FTS5 provides lexical retrieval when available. An embedded semantic vector table provides local semantic retrieval without requiring Qdrant or another service. Retrieval combines lexical match, semantic similarity, confidence, and use history.

Memory records retain kind, scope, source, confidence, metadata, creation time, and last-use time. User corrections preserve the previous value in revision history instead of silently overwriting it.

A bounded post-turn reviewer can inspect a pruned recent conversation after ordinary user chat. It may save a small number of high-confidence durable memories. Reusable skill suggestions are not installed automatically. They are converted into Sentinel approval requests.

Local skills live under the Homuncula data directory and contain reusable instructions plus declared tool guidance. Sentinel remains the security authority even when a skill recommends particular tools.

## Evidence and epistemic gating

Homuncula separates externally observed information from durable belief. File reads, browser snapshots, and process-status reads mint durable evidence receipts inside the governed execution path from the provider's actual returned data. Each receipt retains the read action, capability, exact redacted locator, bounded content, content hash, timestamp, metadata, and optional responsibility scope.

Agent-created evidence observations must reference one of those receipts. The model may select an exact excerpt from receipt content, but it cannot supply its own source locator or substitute text that was not in the verified read result. A bogus receipt ID or non-matching excerpt fails closed without creating an observation.

The authenticated owner API may still create manual observations directly. Those observations are explicitly distinguishable from receipt-backed observations and are not mislabeled as mechanically verified provenance.

A claim is evaluated through an evidence dossier rather than written directly into durable memory. A dossier references one to twenty captured observations and begins in HOLD. HOLD means unresolved, not false.

The local evidence council runs four role-specific reviews against the same bounded packet and exposes no tools to the reviewers:

    Scout       relevance and signal quality
    Verifier    evidential support and scope discipline
    Skeptic     contradictions and alternate explanations
    Integrator  readiness for durable knowledge

Review outputs are schema checked. A PASS must cite observation IDs that were actually present in the packet. Invented evidence IDs, malformed output, an unavailable local model, a missing reviewer, or another invalid review condition fails closed to HOLD.

Final PASS, HOLD, or REJECT is computed deterministically from stored reviewer records. The language model does not decide the aggregation rule.

Only a PASS dossier can promote its exact reviewed claim into durable memory. The resulting memory stores the dossier ID, observation IDs, and review round, while the dossier stores the promoted memory ID. Repeated promotion returns the existing memory instead of creating a duplicate.

The runtime exposes receipt-backed evidence capture, dossier creation, review, status, and promotion as internal tools. The authenticated local API exposes receipt, observation, and dossier inspection plus explicit review. Receipt listings are bounded previews; individual receipt lookup exposes the stored content for local inspection. A dedicated desktop dossier browser is not yet implemented.

## Browser

The browser provider uses Playwright with a local persistent profile and semantic page representations. It exposes text, ARIA structure, and stable referenced controls before any visual fallback is considered.

Direct navigation is restricted to HTTP and HTTPS. Embedded URL credentials, file URLs, browser-internal URLs, JavaScript URLs, and data URLs are rejected.

Page text is treated as untrusted content. The runtime detects common prompt-injection indicators and records security activity when they appear.

Browser mutations use separate capabilities for interaction, upload, and download. Downloads are saved only inside the configured workspace, use sanitized collision-safe filenames, and have a configurable size ceiling. The CI browser harness verifies real navigation, form interaction, prompt-injection detection, attachment download, collision handling, and download-size rejection.

## Windows host control

Files are resolved relative to the configured workspace and paths that escape the workspace are rejected.

Processes are executed with argv arrays and shell execution disabled. Foreground command results are recorded as verification evidence when appropriate. Long-running processes can run in the background and produce process-completion events.

Native applications are inspected through Windows UI Automation. Homuncula assigns explicit references to accessible controls and treats stale references as errors rather than silently clicking coordinates.

Structured interfaces are preferred to pixel clicking. A visual fallback for applications that do not expose adequate accessibility structure remains a future layer.

## Verification and loop safety

Ordinary activity records what Homuncula did. Verification evidence is separate. Process results are classified as tests, quality checks, builds, inspections, or generic commands and retain exit codes plus bounded redacted output summaries.

The system prompt explicitly forbids upgrading a narrow successful check into a broader claim of verification.

Each model turn also has a loop guard that limits total tool volume, repeated use of one tool, identical repeated calls, and identical repeated results. This is intended to stop weak local models from getting trapped in expensive or destructive retry loops.

## Sentinel and permissions

Sentinel is outside the language model. It records a capability request before execution and evaluates that request against deterministic policy and user grants.

Internal memory, planning, finding, and responsibility operations have explicitly defined policy. Read-only workspace, browser, process, and Windows UI inspection are separately defined. Filesystem writes, process execution, background process start, browser interaction, browser upload, browser download, Windows UI interaction, network actions, and skill installation are mutating capabilities.

Standing grants can be restricted by capability, resource pattern, and expiration. Observation-triggered mutation proposals still require explicit approval.

Credentials are stored behind opaque references. On Windows, protected secrets use DPAPI and are encrypted for the current user. Secret values are not intentionally placed in model context, action previews, or activity metadata. Common credential patterns are also scrubbed from persisted command verification output.

## Desktop surfaces

The desktop exposes conversation, responsibilities, approvals, findings, memory, durable plans, local skills, verification evidence, host status, background processes, Windows application inventory, activity provenance, model setup, permissions, autonomy takeover, host restart, launch-at-login, and tray presence.

Closing the main window hides Homuncula to the tray instead of terminating its local responsibilities.

## Building the Windows installer

From PowerShell in the repository root:

    .\build-windows.ps1

The build runs Python tests and Ruff, freezes agentd with PyInstaller, installs desktop dependencies, typechecks the Electron application, and creates the NSIS installer under:

    desktop\release

See [docs/PACKAGING.md](docs/PACKAGING.md) for packaging and signing details.

## Project lineage

Homuncula is not a fork of Hermes Agent, Open Dots, MuseDesk, Muse, or Dots. Those systems informed the architecture, but Homuncula keeps its own compact interfaces so components can be audited and replaced independently.

Open Dots informed the action-gateway pattern. The Hermes Agent fork informed durable planning, bounded review, verification evidence, and loop guardrails. Muse informed privilege separation and the goal of a host-like computer interface. Dots informed responsibility-oriented work, self-selected wakeups, and read-only proactive observation. MuseDesk informed the Windows desktop, tray, task visibility, and packaging direction.

The implementation deliberately avoids inheriting the Hermes fork's multi-agent environment, Qdrant service dependency, or author-specific configuration.

## Known remaining work

The current system is usable as a local persistent agent foundation and desktop product, but several production layers remain intentionally open. Visual computer-use fallback, higher-quality optional local embeddings, a dedicated desktop evidence-dossier browser, stronger automatic source capture from read tools, fully local voice input and output, stronger Windows sandboxing for generated code, connector-specific integrations, production code signing, database migration tooling beyond additive schema initialization, and broader release hardening remain future work.

Those layers are expected to preserve the same contracts: durable state outside the model, local-first operation, explicit authority, inspectable provenance, and no hidden cloud dependency.

## License

Homuncula is released under the MIT License.
