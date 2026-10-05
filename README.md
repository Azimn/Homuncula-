# Homuncula

Homuncula is a Windows-first, local-first persistent AI agent platform. The goal is not another chat client. It is a user-owned agent runtime that can hold responsibilities, wake itself when something changes, remember work across sessions, use the host computer through governed capabilities, and remain independent of any one language model.

The behavioral target is the proactive experience of systems such as Meta Muse and OpenAI Dots, but with the computer, memory, model, task state, skills, and audit trail under the user's control.

## Current status

This repository now contains the first executable foundation: a local FastAPI runtime, SQLite persistence, an Ollama provider, durable responsibilities and wake events, structured memory, a deterministic Sentinel approval boundary, a workspace-scoped Windows host provider, and an iterative tool-using agent loop.

The desktop shell, native Windows UI Automation provider, Playwright browser provider, packaged local inference runtime, hybrid vector memory, and signed installer are the next implementation layers.

## Product contract

| Principle | Direction |
| --- | --- |
| Local by default | SQLite, localhost services, Ollama or llama.cpp, no cloud runtime requirement |
| Responsibility over chat | Durable goals and work survive individual turns and restarts |
| Event driven | Work resumes from schedules and events rather than wasteful polling |
| Model independent | Persistent state lives outside the rendering model |
| Governed action | The model proposes capabilities, Sentinel decides whether they may execute |
| Host native | The Windows PC is the agent's computer, not a remote VM |
| Inspectable memory | Persistent facts retain source and provenance |
| Progressive trust | Grants can be scoped by capability, resource, and expiration |

## Architecture

The local architecture deliberately separates cognition from authority.

    Desktop application
            |
            v
       agentd runtime
            |
       responsibility engine
        /      |       \
     memory  planner   wake scheduler
        \      |       /
         context compiler
              |
          local model
              |
        tool proposals
              |
              v
           Sentinel
              |
      governed capabilities
       /        |        \
    files    processes   browser/UI
              |
         Windows host

The model never becomes the operating-system authority. Read operations are scoped by the computer provider. Mutating and execution capabilities cross Sentinel and either match an explicit grant or become a pending approval.

See docs/ARCHITECTURE.md for the design contract.

## Quick start

Homuncula currently requires Python 3.11 or newer and a local Ollama installation.

From PowerShell in the repository root:

    .\run-local.ps1

The runtime starts at http://127.0.0.1:43900 and expects Ollama at http://127.0.0.1:11434.

The default model is qwen3:8b. Override it before launch when needed:

    $env:HOMUNCULA_MODEL = "your-model"
    .\run-local.ps1

## Why the host replaces the VM

Homuncula treats the user's Windows host as the agent's world, but does not give a language model unrestricted shell or desktop authority.

Structured interfaces are preferred over visual clicking. Files use scoped filesystem APIs. Development work uses argv-based process execution with shell disabled. Browser work will use Playwright and accessibility representations. Native Windows applications will use UI Automation. Screenshot and coordinate control are fallback capabilities.

Generated or untrusted code will later run inside a restricted Windows execution profile rather than inherit the user's normal desktop authority.

## Project lineage

Homuncula is not a fork of Hermes Agent, Open Dots, MuseDesk, Muse, or Dots. Those systems informed the design, but this codebase keeps its own small interfaces so components can be replaced independently.

Open Dots contributed the central action-gateway idea. The Hermes fork contributed durable-plan and wake concepts. Muse contributed the privilege-separated Sentinel model and host-like computer interaction goal. Dots contributed responsibility-based work, self-selected wakeups, and read-only proactive observation. MuseDesk informed the Windows desktop and packaging direction.

The result is intended to remain small enough to audit and modify.

## License

The initial project code is released under the MIT License.
