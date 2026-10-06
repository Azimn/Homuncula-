from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx


class ProviderError(RuntimeError):
    pass


@dataclass
class ProviderMessage:
    content: str
    tool_calls: list[dict[str, Any]]
    raw: dict[str, Any]


class OllamaProvider:
    def __init__(self, base_url: str, model: str, *, timeout: float = 180.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._chat_lock = asyncio.Lock()

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ProviderMessage:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools

        async with self._chat_lock, httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{self.base_url}/api/chat", json=payload)

        if response.status_code >= 400:
            raise ProviderError(
                f"Ollama returned HTTP {response.status_code}: {response.text[:1000]}"
            )

        data = response.json()
        message = data.get("message") or {}
        return ProviderMessage(
            content=message.get("content") or "",
            tool_calls=message.get("tool_calls") or [],
            raw=message,
        )

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{self.base_url}/api/tags")
        response.raise_for_status()
        return [
            str(item.get("name"))
            for item in response.json().get("models", [])
            if item.get("name")
        ]

    async def pull_model(self, model: str) -> dict[str, Any]:
        name = model.strip()
        if not name or len(name) > 200:
            raise ValueError("Invalid model name")
        async with httpx.AsyncClient(timeout=1800.0) as client:
            response = await client.post(
                f"{self.base_url}/api/pull",
                json={"name": name, "stream": False},
            )
        if response.status_code >= 400:
            raise ProviderError(
                f"Ollama pull returned HTTP {response.status_code}: {response.text[:1000]}"
            )
        return response.json()

    def select_model(self, model: str) -> str:
        name = model.strip()
        if not name or len(name) > 200:
            raise ValueError("Invalid model name")
        self.model = name
        return self.model

    async def health(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            models = [
                str(item.get("name"))
                for item in response.json().get("models", [])
                if item.get("name")
            ]
            return {
                "ok": True,
                "base_url": self.base_url,
                "model": self.model,
                "available_models": models,
                "selected_available": self.model in models,
            }
        except (httpx.HTTPError, ValueError) as exc:
            return {
                "ok": False,
                "base_url": self.base_url,
                "model": self.model,
                "error": str(exc),
            }
