from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from homuncula.api import create_app
from homuncula.config import Settings
from homuncula.provider import OllamaProvider
from homuncula.secrets_store import MemorySecretStore


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        home=tmp_path / "home",
        db_path=tmp_path / "home" / "agent.sqlite3",
        workspace=tmp_path,
        ollama_base_url="http://127.0.0.1:11434",
        model="qwen3:8b",
        host="127.0.0.1",
        port=43900,
        owner_token="owner-token-value-that-is-long-enough-1234567890",
        browser_channel="chromium",
        proactive_enabled=False,
        context_token_budget=4096,
        review_enabled=False,
    )


def test_provider_model_selection_validation() -> None:
    provider = OllamaProvider("http://127.0.0.1:11434", "qwen3:8b")
    assert provider.select_model(" llama3.2:3b ") == "llama3.2:3b"
    assert provider.model == "llama3.2:3b"

    with pytest.raises(ValueError):
        provider.select_model("   ")


def test_model_api_selects_persists_and_pulls(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    app = create_app(settings, secret_store=MemorySecretStore())
    provider = app.state.runtime.provider

    async def list_models() -> list[str]:
        return ["qwen3:8b", "llama3.2:3b"]

    async def pull_model(model: str) -> dict:
        assert model == "smollm2:360m"
        return {"status": "success"}

    provider.list_models = list_models  # type: ignore[method-assign]
    provider.pull_model = pull_model  # type: ignore[method-assign]

    headers = {"Authorization": f"Bearer {settings.owner_token}"}
    with TestClient(app) as client:
        models = client.get("/models", headers=headers)
        assert models.status_code == 200
        assert models.json()["available"] == ["qwen3:8b", "llama3.2:3b"]

        selected = client.post(
            "/models/select",
            headers=headers,
            json={"model": "llama3.2:3b"},
        )
        assert selected.status_code == 200
        assert selected.json()["model"] == "llama3.2:3b"
        assert app.state.db.setting("runtime.model") == "llama3.2:3b"

        missing = client.post(
            "/models/select",
            headers=headers,
            json={"model": "missing:latest"},
        )
        assert missing.status_code == 404

        pulled = client.post(
            "/models/pull",
            headers=headers,
            json={"model": "smollm2:360m"},
        )
        assert pulled.status_code == 200
        assert pulled.json()["model"] == "smollm2:360m"
        assert app.state.db.setting("runtime.model") == "smollm2:360m"
