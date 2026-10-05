from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .computer import WindowsHostComputer
from .config import Settings
from .db import Database
from .memory import MemoryStore
from .provider import OllamaProvider
from .runtime import HomunculaRuntime, WakeScheduler
from .sentinel import Sentinel


class ChatRequest(BaseModel):
    content: str = Field(min_length=1)


class ThreadRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ResponsibilityRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1)
    proactive_mode: str = "observe"
    start_now: bool = True


class WakeRequest(BaseModel):
    delay_seconds: int = Field(ge=1)
    reason: str = Field(min_length=1)


class MemoryRequest(BaseModel):
    content: str = Field(min_length=1)
    scope: str = "global"
    kind: str = "fact"
    source: str = "user"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class GrantRequest(BaseModel):
    capability: str
    resource_pattern: str
    expires_at: str | None = None


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    db = Database(settings.db_path)
    db.initialize()
    memory = MemoryStore(db)
    sentinel = Sentinel(db)
    provider = OllamaProvider(settings.ollama_base_url, settings.model)
    computer = WindowsHostComputer(settings.workspace)
    runtime = HomunculaRuntime(db, computer, memory, sentinel, provider)
    scheduler = WakeScheduler(db, runtime.run_responsibility)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        scheduler_task = asyncio.create_task(
            scheduler.run(),
            name="homuncula-wake-scheduler",
        )
        try:
            yield
        finally:
            scheduler.stop()
            await scheduler_task

    app = FastAPI(
        title="Homuncula",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.db = db
    app.state.memory = memory
    app.state.sentinel = sentinel
    app.state.runtime = runtime

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "ok": True,
            "workspace": str(settings.workspace),
            "database": str(settings.db_path),
            "provider": await provider.health(),
        }

    @app.get("/state")
    async def state() -> dict[str, Any]:
        return {
            "responsibilities": runtime.list_responsibilities(),
            "pending_actions": sentinel.pending(),
            "activity": db.all(
                "SELECT * FROM activities ORDER BY created_at DESC LIMIT 50"
            ),
        }

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
        return runtime.create_responsibility(
            request.title,
            request.objective,
            proactive_mode=request.proactive_mode,
            start_now=request.start_now,
        )

    @app.get("/responsibilities")
    async def responsibilities() -> list[dict[str, Any]]:
        return runtime.list_responsibilities()

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

    @app.post("/memory")
    async def add_memory(request: MemoryRequest) -> dict[str, Any]:
        return memory.add(
            request.content,
            scope=request.scope,
            kind=request.kind,
            source=request.source,
            confidence=request.confidence,
        )

    @app.get("/memory/search")
    async def search_memory(
        q: str,
        scope: str = "global",
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        return memory.search(q, scope=scope, limit=limit)

    @app.get("/actions")
    async def actions(status: str | None = None) -> list[dict[str, Any]]:
        if status:
            return db.all(
                "SELECT * FROM actions WHERE status = ? ORDER BY created_at DESC",
                (status,),
            )
        return db.all(
            "SELECT * FROM actions ORDER BY created_at DESC LIMIT 100"
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

    @app.post("/grants")
    async def add_grant(request: GrantRequest) -> dict[str, Any]:
        return sentinel.add_grant(
            request.capability,
            request.resource_pattern,
            expires_at=request.expires_at,
        )

    @app.get("/activity")
    async def activity(limit: int = 100) -> list[dict[str, Any]]:
        return db.all(
            "SELECT * FROM activities ORDER BY created_at DESC LIMIT ?",
            (max(1, min(limit, 500)),),
        )

    return app
