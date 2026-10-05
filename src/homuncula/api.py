from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .auth import token_matches
from .browser import BrowserProvider
from .computer import WindowsHostComputer
from .config import Settings
from .context import ContextCompiler
from .db import Database
from .events import EventHub, WorkspaceEventSource
from .memory import MemoryStore
from .processes import BackgroundProcessManager
from .provider import OllamaProvider
from .runtime import HomunculaRuntime, WakeScheduler
from .secrets_store import (
    MemorySecretStore,
    SecretNotFound,
    SecretStoreUnavailable,
    WindowsDPAPISecretStore,
)
from .sentinel import Sentinel
from .windows_ui import WindowsUIProvider


class ChatRequest(BaseModel):
    content: str = Field(min_length=1)


class ThreadRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ResponsibilityRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1)
    proactive_mode: str = "observe"
    start_now: bool = True


class ResponsibilityPatch(BaseModel):
    status: str | None = None
    proactive_mode: str | None = None


class WakeRequest(BaseModel):
    delay_seconds: int = Field(ge=1)
    reason: str = Field(min_length=1)


class MemoryRequest(BaseModel):
    content: str = Field(min_length=1)
    scope: str = "global"
    kind: str = "fact"
    source: str = "user"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class MemoryRevisionRequest(BaseModel):
    content: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    kind: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class GrantRequest(BaseModel):
    capability: str
    resource_pattern: str
    expires_at: str | None = None


class SecretRequest(BaseModel):
    value: str = Field(min_length=1)


def create_app(
    settings: Settings | None = None,
    *,
    secret_store: Any | None = None,
    browser: BrowserProvider | None = None,
    windows_ui: WindowsUIProvider | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    db = Database(settings.db_path)
    db.initialize()
    memory = MemoryStore(db)
    sentinel = Sentinel(db)
    provider = OllamaProvider(settings.ollama_base_url, settings.model)
    computer = WindowsHostComputer(settings.workspace)
    context = ContextCompiler(
        db,
        memory,
        token_budget=settings.context_token_budget,
    )
    browser = browser or BrowserProvider(
        settings.home / "browser",
        channel=settings.browser_channel,
        headless=os.environ.get("HOMUNCULA_BROWSER_HEADLESS", "").lower()
        in {"1", "true", "yes"},
    )
    windows_ui = windows_ui or WindowsUIProvider()

    runtime_holder: dict[str, HomunculaRuntime] = {}

    async def event_wake(
        responsibility_id: str,
        reason: str,
        payload: dict[str, Any],
    ) -> None:
        await runtime_holder["runtime"].enqueue_event(
            responsibility_id,
            reason,
            payload,
        )

    event_hub = EventHub(db, event_wake)
    processes = BackgroundProcessManager(
        db,
        settings.workspace,
        event_hub,
    )
    runtime = HomunculaRuntime(
        db,
        computer,
        memory,
        sentinel,
        provider,
        context,
        browser,
        windows_ui,
        event_hub,
        processes,
    )
    runtime_holder["runtime"] = runtime
    scheduler = WakeScheduler(db, runtime.run_responsibility)
    workspace_events = WorkspaceEventSource(settings.workspace, event_hub)

    if secret_store is None:
        try:
            secret_store = WindowsDPAPISecretStore(settings.home)
        except SecretStoreUnavailable:
            secret_store = MemorySecretStore()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        scheduler_task = asyncio.create_task(
            scheduler.run(),
            name="homuncula-wake-scheduler",
        )
        event_task = None
        if settings.proactive_enabled:
            event_task = asyncio.create_task(
                workspace_events.run(),
                name="homuncula-workspace-events",
            )

        await event_hub.publish(
            "runtime",
            "started",
            {
                "name": "Homuncula",
                "workspace": str(settings.workspace),
            },
            event_key=f"runtime-start:{os.getpid()}",
        )
        try:
            yield
        finally:
            workspace_events.stop()
            scheduler.stop()
            await processes.shutdown()
            await browser.close()
            await scheduler_task
            if event_task is not None:
                await asyncio.gather(event_task, return_exceptions=True)

    app = FastAPI(
        title="Homuncula",
        version="0.2.0",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.db = db
    app.state.memory = memory
    app.state.sentinel = sentinel
    app.state.runtime = runtime
    app.state.events = event_hub
    app.state.secrets = secret_store

    @app.middleware("http")
    async def owner_auth(request: Request, call_next):
        if request.url.path == "/healthz":
            return await call_next(request)

        authorization = request.headers.get("Authorization", "")
        supplied = None
        if authorization.startswith("Bearer "):
            supplied = authorization.removeprefix("Bearer ").strip()
        supplied = supplied or request.headers.get("X-Homuncula-Token")
        if not token_matches(settings.owner_token, supplied):
            return JSONResponse(
                status_code=401,
                content={"detail": "Local owner authentication required"},
            )
        return await call_next(request)

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "ok": True,
            "version": "0.2.0",
            "workspace": str(settings.workspace),
            "database": str(settings.db_path),
            "proactive_enabled": settings.proactive_enabled,
            "browser_channel": settings.browser_channel,
            "secret_store": type(secret_store).__name__,
            "provider": await provider.health(),
        }

    @app.get("/state")
    async def state() -> dict[str, Any]:
        return {
            "autonomy_paused": runtime.autonomy_paused(),
            "responsibilities": runtime.list_responsibilities(),
            "pending_actions": sentinel.pending(),
            "findings": runtime.list_findings(status="new"),
            "activity": db.all(
                "SELECT * FROM activities ORDER BY created_at DESC LIMIT 50"
            ),
        }

    @app.post("/runtime/pause")
    async def pause_runtime() -> dict[str, bool]:
        return {"paused": runtime.set_autonomy_paused(True)}

    @app.post("/runtime/resume")
    async def resume_runtime() -> dict[str, bool]:
        return {"paused": runtime.set_autonomy_paused(False)}

    @app.post("/threads")
    async def create_thread(request: ThreadRequest) -> dict[str, Any]:
        return runtime.create_thread(request.title)

    @app.get("/threads")
    async def threads() -> list[dict[str, Any]]:
        return db.all("SELECT * FROM threads ORDER BY updated_at DESC")

    @app.get("/threads/{thread_id}/messages")
    async def thread_messages(thread_id: str) -> list[dict[str, Any]]:
        if not db.one("SELECT id FROM threads WHERE id = ?", (thread_id,)):
            raise HTTPException(status_code=404, detail="Thread not found")
        return db.all(
            """
            SELECT id, role, content, created_at
            FROM messages
            WHERE thread_id = ?
            ORDER BY created_at ASC
            LIMIT 500
            """,
            (thread_id,),
        )

    @app.post("/threads/{thread_id}/chat")
    async def chat(thread_id: str, request: ChatRequest) -> dict[str, Any]:
        try:
            return await runtime.chat(thread_id, request.content)
        except KeyError:
            raise HTTPException(status_code=404, detail="Thread not found") from None
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/responsibilities")
    async def create_responsibility(
        request: ResponsibilityRequest,
    ) -> dict[str, Any]:
        try:
            return runtime.create_responsibility(
                request.title,
                request.objective,
                proactive_mode=request.proactive_mode,
                start_now=request.start_now,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/responsibilities")
    async def responsibilities() -> list[dict[str, Any]]:
        return runtime.list_responsibilities()

    @app.patch("/responsibilities/{responsibility_id}")
    async def patch_responsibility(
        responsibility_id: str,
        request: ResponsibilityPatch,
    ) -> dict[str, Any]:
        try:
            return runtime.update_responsibility(
                responsibility_id,
                status=request.status,
                proactive_mode=request.proactive_mode,
            )
        except KeyError:
            raise HTTPException(
                status_code=404,
                detail="Responsibility not found",
            ) from None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/responsibilities/{responsibility_id}/wake")
    async def wake(
        responsibility_id: str,
        request: WakeRequest,
    ) -> dict[str, Any]:
        try:
            return runtime.schedule_wake(
                responsibility_id,
                request.delay_seconds,
                request.reason,
            )
        except KeyError:
            raise HTTPException(
                status_code=404,
                detail="Responsibility not found",
            ) from None

    @app.get("/subscriptions")
    async def subscriptions(
        responsibility_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return event_hub.list_subscriptions(responsibility_id)

    @app.post("/memory")
    async def add_memory(request: MemoryRequest) -> dict[str, Any]:
        return memory.add(
            request.content,
            scope=request.scope,
            kind=request.kind,
            source=request.source,
            confidence=request.confidence,
        )

    @app.get("/memory")
    async def list_memory(
        scope: str | None = None,
        kind: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return memory.list(scope=scope, kind=kind, limit=limit)

    @app.get("/memory/search")
    async def search_memory(
        q: str,
        scope: str = "global",
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        return memory.search(q, scope=scope, limit=limit)

    @app.patch("/memory/{memory_id}")
    async def revise_memory(
        memory_id: str,
        request: MemoryRevisionRequest,
    ) -> dict[str, Any]:
        try:
            return memory.revise(
                memory_id,
                content=request.content,
                reason=request.reason,
                kind=request.kind,
                confidence=request.confidence,
                source="user",
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="Memory not found") from None

    @app.get("/findings")
    async def findings(status: str | None = None) -> list[dict[str, Any]]:
        return runtime.list_findings(status=status)

    @app.get("/actions")
    async def actions(status: str | None = None) -> list[dict[str, Any]]:
        if status:
            return db.all(
                "SELECT * FROM actions WHERE status = ? ORDER BY created_at DESC",
                (status,),
            )
        return db.all(
            "SELECT * FROM actions ORDER BY created_at DESC LIMIT 200"
        )

    @app.post("/actions/{action_id}/approve")
    async def approve_action(action_id: str) -> dict[str, Any]:
        try:
            return sentinel.approve(action_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Action not found") from None
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/actions/{action_id}/deny")
    async def deny_action(action_id: str) -> dict[str, Any]:
        try:
            return sentinel.deny(action_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Action not found") from None
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/actions/{action_id}/execute")
    async def execute_action(action_id: str) -> dict[str, Any]:
        try:
            return await runtime.execute_action(action_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Action not found") from None
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/grants")
    async def grants() -> list[dict[str, Any]]:
        return sentinel.list_grants()

    @app.post("/grants")
    async def add_grant(request: GrantRequest) -> dict[str, Any]:
        try:
            return sentinel.add_grant(
                request.capability,
                request.resource_pattern,
                expires_at=request.expires_at,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/grants/{grant_id}", status_code=204)
    async def revoke_grant(grant_id: str) -> None:
        sentinel.revoke_grant(grant_id)

    @app.get("/processes")
    async def process_list(limit: int = 100) -> list[dict[str, Any]]:
        return processes.list(limit=limit)

    @app.post("/secrets")
    async def put_secret(request: SecretRequest) -> dict[str, str]:
        return {"secret_ref": secret_store.put(request.value)}

    @app.get("/secrets")
    async def secret_refs() -> dict[str, list[str]]:
        return {"secret_refs": secret_store.list_refs()}

    @app.delete("/secrets/{secret_ref}", status_code=204)
    async def delete_secret(secret_ref: str) -> None:
        try:
            secret_store.delete(secret_ref)
        except SecretNotFound:
            raise HTTPException(status_code=404, detail="Secret not found") from None

    @app.get("/activity")
    async def activity(limit: int = 100) -> list[dict[str, Any]]:
        return db.all(
            "SELECT * FROM activities ORDER BY created_at DESC LIMIT ?",
            (max(1, min(limit, 500)),),
        )

    return app
