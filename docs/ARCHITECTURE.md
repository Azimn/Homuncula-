# Homuncula Architecture Contract

## Purpose

Homuncula is a persistent local agent runtime. A chat turn is an interface event, not the unit of identity or work. Durable state lives outside the model so a responsibility can survive context compression, application restart, model replacement, or a long period of inactivity.

## Runtime boundaries

The system has three trust domains.

The Desktop is the user's control surface. It displays conversation, activity, memory, responsibilities, approvals, permissions, computer state, and takeover controls.

Agent Runtime owns cognition. It compiles context, talks to the local model, maintains responsibilities, schedules wakes, retrieves memory, records activity, and proposes tool calls. It is not allowed to treat possession of a model response as proof that an operating-system action is authorized.

Sentinel owns authority. Every externally meaningful mutation is represented as a typed capability request. Sentinel evaluates explicit grants and policy. It records the proposal before execution. Unknown capabilities are denied. Sensitive operations default to approval.

## Durable state

SQLite is the initial system of record. The schema separates threads and messages from memories, responsibilities, wakes, activities, grants, and actions.

Responsibilities represent ongoing obligations. A responsibility can be active, idle, paused, complete, or failed. It owns a conversation thread so resumed work can reconstruct recent context while memory and activity history remain separately queryable.

Wakes are persisted events. A wake can be time based today and event based later. Claiming a wake is transactional so process restarts do not silently duplicate work.

Memories are structured records with kind, scope, source, confidence, and timestamps. Lexical retrieval uses SQLite FTS5 when available. A local vector index can be added later without changing the memory API.

Activities are operational provenance. They explain what happened without exposing hidden chain of thought. Examples include a wake firing, a tool being requested, an approval being required, a process completing, or a responsibility failing.

## Model boundary

The provider interface receives messages and tool schemas and returns normalized text plus normalized tool calls.

The first provider targets Ollama because it is local, easy to install, and exposes tool calling. The rest of Homuncula does not import Ollama-specific concepts.

The model does not own the authoritative plan, grants, action state, memory database, or wake schedule. It renders decisions against external state.

## Capability boundary

The initial capability vocabulary is intentionally small.

    filesystem.list
    filesystem.read
    filesystem.write
    process.exec
    memory.search
    memory.remember
    runtime.schedule_wake

Filesystem reads are restricted to the registered workspace by the computer provider. Filesystem writes and process execution require Sentinel authorization. Memory and wake operations are internal capabilities and remain auditable.

Future providers can add browser.navigate, browser.interact, windows.ui.read, windows.ui.interact, connector.read, connector.write, notification.send, and skill.install without changing the core permission model.

## Approval lifecycle

An action moves through explicit states.

    proposed -> pending -> approved -> executing -> completed
                         \-> denied
                                      \-> failed

An existing grant may move a proposal directly to approved. A denied or unknown capability never reaches an executor.

The execution record stores the capability, target, intent, arguments, preview, decision, result, and timestamps. The local model does not receive credentials or unrestricted authority just because an action was approved.

## Workspace containment

The first Windows host provider uses pathlib resolution and rejects paths that escape the configured workspace. Process execution receives an argv array and uses shell=False.

Native UI Automation and browser automation will be separate providers with their own scoped permissions. A later restricted execution provider will use Windows isolation primitives for generated code.

## Proactivity

Proactivity is event driven.

A responsibility can schedule a future wake. Later versions will support filesystem changes, process completion, Git changes, email events, calendar events, connector notifications, and user-defined event sources.

Observation mode is read-only. An observation may create a finding or proposed action, but it may not silently cross into a mutating capability. This preserves useful proactive behavior without letting curiosity become authority.

## Locality

Core operation must not require a cloud service. Local state stays on disk. Model inference can use Ollama or llama.cpp on localhost. External network access is a capability used for tasks that inherently require the network, not an infrastructure dependency.

## Versioning contract

Database migrations must be explicit. Tool schemas must remain versioned. Action names are part of the security boundary and cannot be casually renamed. Unknown actions remain denied by default.

The desktop may evolve independently from the runtime as long as it speaks the versioned local API.
