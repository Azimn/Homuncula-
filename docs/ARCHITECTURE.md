# Homuncula Architecture Contract

## Purpose

Homuncula is a persistent local agent runtime. A chat turn is an interface event, not the unit of identity or work. Durable state lives outside the model so responsibilities survive context compression, application restart, model replacement, and periods of inactivity.

The system is designed around three non-negotiable properties: persistent responsibility, local ownership, and authority outside the model.

## Trust domains

Homuncula has three primary trust domains.

The Electron desktop is the user's control surface. It owns the narrow IPC bridge, local host lifecycle, tray presence, native notifications, login startup setting, and explicit user actions such as model setup. The sandboxed renderer does not receive arbitrary Node.js access or arbitrary network access.

Agent Runtime owns cognition and durable work state. It compiles context, calls the local model, stores messages and memory, maintains responsibilities and plans, schedules wakes, receives local events, runs bounded review, records findings, applies loop guardrails, and proposes capabilities. A model response is never itself operating-system authorization.

Sentinel owns model-initiated authority. Externally meaningful mutations are represented as typed capability requests. Sentinel records the request before execution, checks deterministic policy and grants, and produces approved, pending, or denied state. Unknown capability names are denied.

## Local control plane

agentd binds to localhost. Localhost is not considered an authentication boundary. Every route except the minimal health probe requires a per-user owner token.

The Electron main process holds that owner token and adds it to local API calls. The sandboxed renderer talks through explicitly exposed IPC methods.

Windows connector-style credentials are stored through DPAPI behind opaque references. Secret values are not passed to the model simply because a capability has permission to use a credential.

## Durable state

SQLite is the system of record for application state.

Schema evolution is explicit and versioned. The durable `schema_migrations` ledger stores each applied version, stable migration name, checksum, and application time. Homuncula validates the ledger before applying ordinary baseline initialization when a ledger already exists, so a database created by a newer build is refused before the older runtime can mutate its baseline schema.

The v0.2 relational model is baseline version 1. Later schema changes are ordered migrations. Migration definitions must be contiguous, uniquely named, and checksum-stable. Each pending migration runs in an immediate transaction and inserts its ledger row only after every statement succeeds. Failure rolls back the migration. Ledger gaps, checksum drift, unknown versions, and future-version databases are startup errors rather than best-effort repair cases.

The schema contains settings, threads, messages, responsibilities, wakes, memories, memory revisions, memory vectors, plans, plan steps, grants, actions, activities, event subscriptions, event receipts, findings, background processes, verification events, evidence sources, verified read receipts, evidence observations, observation-receipt links, evidence dossiers, dossier-observation links, and evidence reviews.

The filesystem also stores the browser profile, local skills, protected secret blobs, and application data that is inappropriate for relational storage.

Threads and messages provide recent conversational continuity.

Responsibilities represent ongoing obligations and own persistent conversation threads.

Plans represent ordered execution state for responsibilities. Autonomous mutating work requires an active plan.

Wakes represent future continuation and are claimed transactionally.

Event subscriptions map local events to responsibilities. Current event sources include filesystem changes, Git changes, process completion, and runtime events.

Findings are user-visible results of proactive observation.

Activities are operational provenance and never serve as a substitute for hidden chain of thought.

Verification events are explicit evidence produced by command execution. They retain the command, working directory, classification, exit status, and bounded redacted output summaries.

## Memory

Memory records include kind, scope, source, confidence, metadata, timestamps, and revision history.

FTS5 provides lexical retrieval when available. The embedded vector table provides a service-free semantic index. The default hash n-gram embedder guarantees local operation without downloading an embedding service. The embedding interface is replaceable.

Retrieval combines semantic similarity, lexical rank, confidence, and prior use.

Corrections create memory revision records before updating the authoritative memory value.

## Epistemic evidence layer

External observation and durable memory are separate state transitions.

Evidence sources identify where information came from by source kind and redacted locator.

Verified read receipts are created inside the governed action executor after an actual read provider returns data and while the Sentinel action is still executing. Current receipt-producing capabilities are filesystem.read, browser.read, and process.read. The receipt binds the action ID, responsibility scope, capability, source kind, provider-derived locator/title, bounded redacted content, content hash, and metadata. The model cannot mint these receipts directly.

Agent evidence capture accepts a receipt ID and optional exact excerpt. The source locator and title come from the receipt rather than model arguments. An excerpt must be a literal substring of the stored receipt content after redaction. Invalid receipt IDs, cross-responsibility misuse, and invented excerpts fail closed.

Evidence observations preserve bounded redacted content, a content hash, observation time, responsibility scope, metadata, and any receipt links. Duplicate content from the same source resolves to the existing observation. Manual observations created through the authenticated owner API remain supported but are marked by the absence of a verified receipt link.

Evidence dossiers bind one claim to one or more observation IDs. Creation performs deterministic structural prechecks and always starts the dossier in HOLD. The dossier retains confidence, declared unknowns, current reviewer unknowns, its latest review round, and any memory produced by successful promotion.

The evidence council contains four local review roles: Scout, Verifier, Skeptic, and Integrator. Every role receives the same bounded evidence packet with no tools. Packet content is explicitly untrusted data.

Reviewer output must conform to the verdict schema, and every cited observation ID must exist in the packet. The packet explicitly states whether each observation has mechanically verified receipt provenance or manual provenance. A PASS review with no packet evidence is invalid. Provider failure, malformed JSON, invented evidence IDs, missing roles, or any other invalid reviewer output causes the aggregate result to remain HOLD.

Aggregation is deterministic and outside the model. A dossier passes only when Verifier, Skeptic, and Integrator all pass and every reviewer record is valid. It rejects when the critical reviewers provide sufficient independent rejection. Other combinations remain HOLD.

Only PASS dossiers can be promoted to durable memory. Promotion uses the exact reviewed claim, records the dossier and observation provenance in memory metadata, and links the dossier to the resulting memory so promotion is idempotent.

HOLD means unresolved. It is deliberately not treated as false. REJECT means the current evidence materially contradicts the claim. Neither state may be promoted through the evidence path.

## Context compiler

The context compiler operates under a configurable token budget.

It can assemble relevant durable memory, active responsibility state, active plan state, unresolved or accepted evidence dossiers, recent operational activity, matching local skills, verification evidence, and recent conversation.

This compiler, rather than the rendering model, decides which durable state enters a turn.

## Model boundary

The first inference provider is Ollama.

The provider normalizes local model text and tool calls. The model can be selected at runtime and the choice is persisted in SQLite. The desktop can detect local Ollama models, pull a model, and select one without changing durable agent identity.

The architecture does not permit the provider to own plans, permissions, memory, responsibilities, verification state, or wake schedules.

## Durable planning

Responsibilities and plans are separate objects.

A responsibility expresses what Homuncula owns. A plan expresses the current ordered execution strategy.

A plan persists its goal, ordered steps, active step, step summaries, blocked state, completion state, and failure state.

When a responsibility attempts model-initiated mutating work without an active plan, the runtime blocks the proposal before Sentinel authorization.

This requirement does not apply to ordinary direct user actions in the desktop.

## Capability vocabulary

Current internal capabilities include memory search and revision, wake scheduling, event subscription, finding creation, plan lifecycle operations, and skill reads.

Current read capabilities include workspace listing and reading, browser navigation and semantic inspection, process status, and Windows UI inspection.

Current mutation capabilities include filesystem writes, foreground process execution, background process start, browser interaction, browser upload, browser download, Windows UI interaction, network actions, and local skill installation.

Capability names are part of the security boundary. Unknown names remain denied.

## Approval lifecycle

A model-initiated action follows explicit state.

    proposed
       |
       +-> denied
       |
       +-> pending -> approved -> executing -> completed
                                      |
                                      +-> failed

A matching standing grant can move a known mutating proposal directly to approved during an ordinary turn.

Observation mode changes this behavior. A proactive observation may use read capabilities, but mutating proposals remain pending even when a standing mutation grant would otherwise match.

## Workspace containment

The host computer provider resolves filesystem targets against the configured workspace. Path traversal outside that root raises a workspace violation.

Foreground and background processes receive argv arrays. Shell execution is disabled.

Browser uploads resolve their source through the same workspace provider.

Browser downloads resolve their destination directory through the workspace provider before Playwright receives it. Suggested filenames are reduced to a basename, existing files are not overwritten, and a configured size ceiling removes oversized downloads after transfer.

## Browser trust model

Browser navigation accepts only HTTP and HTTPS URLs with a valid host. URLs with embedded credentials are rejected. file, data, JavaScript, and browser-internal schemes are rejected.

The browser provider prefers semantic structure over pixels. It returns page text, ARIA structure, and referenced controls.

External page text is untrusted. Common prompt-injection indicators are surfaced as security activity and do not alter Sentinel policy.

Browser mutations are separated into interaction, upload, and download capabilities so trust can be scoped precisely.

## Windows UI Automation

Native Windows applications are inspected through UI Automation using pywinauto.

Accessible windows and controls receive ephemeral references. Reads can inspect bounded control trees. Mutations can focus, invoke, set text, select, and scroll through referenced controls.

References are validated before use. Stale controls raise an explicit stale-reference error.

Structured accessibility control remains the primary desktop interface. Pixel-level fallback is not yet part of the trusted computer provider.

## Processes and verification

Foreground process execution is governed separately from read-only process status.

After a foreground command completes, the runtime records a verification event. Classification recognizes tests, quality checks, builds, inspections, and generic commands.

Verification evidence is injected into later responsibility context. The model is instructed not to claim broader verification than the recorded evidence supports.

Background processes persist process metadata and captured output. Completion produces an event that can wake subscribed responsibilities.

## Loop guardrails

Each agent turn owns an in-memory ToolLoopGuard.

The guard limits total calls in a turn, repeated use of one tool, identical repeated calls, and identical repeated results. When the guard detects non-progress, the runtime records a guardrail activity and forces the model to change strategy or stops the turn.

The guard is intentionally independent of Sentinel. Loop safety controls iteration; Sentinel controls authority.

## Proactivity

Proactivity is event driven rather than continuous model polling.

A responsibility can wake because of a persisted timer or local event.

Observation mode is read-only by authority even if the responsibility has previously earned mutation grants.

The user can globally pause autonomous wakes through Take Control. Deferred wakes are persisted and retried rather than discarded.

Native notifications surface new findings and pending approvals when the desktop is not focused. The packaged application can launch at login and remain in the tray without opening the main window.

## Post-turn review

Ordinary direct user chat may schedule a bounded local review after the main response.

The reviewer receives only a pruned recent conversation digest and no tool schemas.

It can save a small number of high-confidence durable memories after duplicate checks.

It can suggest a reusable local skill, but skill installation is converted into a Sentinel approval request. Review cannot silently install a skill or operate the computer.

Rapid successive chat turns coalesce review work by thread so stale reviews are canceled. Pending skill proposals are deduplicated.

## Local skills

Skills are local reusable instruction packages.

A skill has a normalized name, description, instructions, declared allowed-tool guidance, source, and update metadata.

Skill tool declarations influence context and procedure but do not grant authority. Sentinel remains authoritative.

Skills may be generated by the agent only through the governed skill.install capability.

## Secrets and redaction

On Windows, protected secrets use DPAPI for the current user.

Opaque secret references may pass through the system without exposing the secret value.

Structured sensitive fields are recursively redacted before action and activity persistence.

Common bearer tokens, API key assignments, password assignments, and similar patterns are scrubbed from unstructured verification output before it is written to SQLite.

## Desktop lifecycle

The Electron main process starts agentd and owns its lifecycle.

The user can explicitly restart the local host from the UI.

Closing the main window hides the application to the tray instead of stopping responsibilities.

The packaged application can be configured to launch at login. Login startup remains hidden until the user opens the window.

A local notification monitor watches authenticated state for new findings and pending approvals. Existing state is seeded on startup so historical items do not generate a notification storm.

## Packaging

The Windows package contains Electron plus a PyInstaller-frozen agentd executable.

Application binaries and durable user data are separated. The default durable home is %USERPROFILE%\.homuncula.

CI builds an NSIS installer and uploads it as an artifact.

The packaging configuration supports standard electron-builder certificate variables for signed public releases. The repository does not contain signing credentials.

## Locality contract

Core operation does not require a cloud inference service, Qdrant, a hosted vector database, or a remote virtual machine.

Network access is required only for tasks that inherently need the network, such as browsing, downloading external content, installing Ollama, or pulling a model.

The application does not inherit the Hermes fork's author-specific five-agent environment.

## Current intentional gaps

Pixel-level visual computer control is not yet implemented.

The default semantic embedder is lightweight and service-free rather than a dedicated neural embedding model.

Fully local speech recognition and high-quality local text-to-speech are not yet integrated.

Generated-code isolation is workspace-scoped but does not yet use a dedicated Windows sandbox profile.

Database schema creation is additive and does not yet provide a formal migration framework.

Public release signing requires an external code-signing certificate.

These gaps must preserve the existing trust boundaries when implemented.

## Versioning contract

Capability names are security-sensitive and should not be casually renamed.

Database migrations must remain explicit as schema evolution becomes non-additive.

Provider and desktop implementations may evolve independently while the authenticated local API contract remains compatible.

Unknown capabilities remain denied by default.
