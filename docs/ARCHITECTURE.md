# Homuncula Architecture Contract

## Purpose

Homuncula is a persistent local agent runtime. A chat turn is an interface event, not the unit of identity or work. Durable state lives outside the rendering model so responsibilities survive context compression, application restart, model replacement, and long periods of inactivity.

## Trust domains

The Desktop is the user's control surface. It displays conversation, responsibilities, plans, skills, verification, findings, memory, permissions, computer state, voice setup, and takeover controls.

Agent Runtime owns cognition and persistence. It compiles context, talks to the selected local model, maintains responsibilities, schedules wakes, records verification, manages local skills, performs bounded review, and proposes tool calls.

Sentinel owns authority. Externally meaningful mutations are typed capability requests. Sentinel evaluates grants and policy before execution. Unknown capabilities are denied. Observation retains read access but cannot silently consume standing mutation grants.

## Durable state

SQLite is the system of record for threads, messages, responsibilities, wakes, memories, memory revisions, vectors, grants, actions, activities, event subscriptions, event receipts, findings, plans, plan steps, background processes, verification events, and runtime settings.

Responsibilities represent ongoing obligations and own a conversation thread. Plans represent durable execution state for mutating autonomous work. Wakes are transactionally claimed persisted events. Findings are user-visible outcomes of proactive observation.

Memories preserve kind, scope, source, confidence, metadata, timestamps, and revision history. Retrieval combines SQLite FTS5 with an embedded deterministic semantic vector index. The context compiler combines relevant memory, responsibility state, plan state, skills, verification evidence, activity history, and recent conversation within a token budget.

## Provider boundary

The model provider receives normalized messages and tool schemas and returns normalized text and tool calls. Ollama is the current provider, but the rest of Homuncula does not store identity, plan state, authority, memory, or permissions inside Ollama.

The selected model is persisted in SQLite and can be changed from the desktop.

## Capability boundary

Current capability families include filesystem reads and writes, foreground and background processes, browser navigation and interaction, browser upload and download, Windows UI inspection and interaction, memory operations, responsibility state, event subscriptions, findings, local skill installation, and wake scheduling.

Workspace paths are resolved against the configured workspace. Browser direct navigation is limited to HTTP and HTTPS. Browser content is treated as untrusted data and scanned for common prompt-injection indicators. Native application interaction uses Windows UI Automation references rather than coordinate-first control.

Sensitive operations cross Sentinel. Standing grants are scoped by capability and resource. Autonomous mutation associated with a responsibility also requires an active durable plan.

## Verification and loop control

Process checks are recorded separately from ordinary activity. Verification records retain command, working directory, exit status, and bounded redacted output. The model is instructed not to claim verification beyond the scope of successful recorded evidence.

A per-turn loop guard limits total calls, repeated use of one tool, repeated identical calls, and repeated identical results. Repeated no-progress behavior becomes an explicit guardrail event rather than an infinite agent loop.

## Proactivity

Proactivity is event driven. Responsibilities can wake from scheduled times, filesystem changes, Git changes, process completion, or runtime events. Event subscriptions and receipts are durable and duplicate events are suppressed.

Observation mode is read-only. It may inspect state, create findings, or propose mutations, but the proposed mutation remains pending even if a standing grant would normally allow it.

The user can globally pause autonomous wakes without disabling direct conversation or inspection.

## Bounded learning

A post-turn reviewer receives a pruned recent conversation with no tools. It may store a small number of high-confidence durable memories. Exact known memories are not duplicated.

The reviewer may suggest reusable local skills, but skill installation is a Sentinel action and requires approval. Concurrent reviews for one thread are coalesced and duplicate pending skill proposals are suppressed.

## Voice boundary

Voice is optional and local. The Electron renderer owns microphone permission and capture. Recorded audio is decoded and converted to mono 16 kHz PCM WAV in the renderer. A narrow Electron IPC method sends those bytes to the owner-authenticated local API.

Speech recognition uses sherpa-onnx with Whisper tiny.en int8. Speech synthesis uses sherpa-onnx with Kokoro. Voice models are downloaded on demand into the user data directory and are not part of persistent model context.

Voice model archives are extracted only after path containment checks, and symbolic or hard links are rejected. Audio is not sent to a remote speech API.

## Secret boundary

The local API requires a random owner token even on loopback. Electron main owns the token and the renderer receives only a narrow IPC surface. Windows connector secrets use DPAPI-backed storage and are referenced by opaque handles. Structured payloads and verification output are redacted before persistence.

## Desktop lifecycle

The packaged desktop starts the frozen `agentd` process, remains available in the tray, can launch hidden at login, emits native notifications for new findings and pending approvals, and exposes explicit host recovery. Closing the main window does not terminate the local runtime.

## Versioning

Database migrations, tool schemas, capability names, IPC paths, and local API paths are security-sensitive interfaces. Unknown capability names remain denied by default. New runtime features must preserve that default-deny contract.
