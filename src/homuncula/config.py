from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .auth import load_or_create_owner_token


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    home: Path
    db_path: Path
    workspace: Path
    ollama_base_url: str
    model: str
    host: str
    port: int
    owner_token: str
    browser_channel: str
    proactive_enabled: bool
    context_token_budget: int
    review_enabled: bool = True

    @classmethod
    def from_env(cls) -> Settings:
        home = Path(os.environ.get("HOMUNCULA_HOME", Path.home() / ".homuncula")).expanduser()
        home.mkdir(parents=True, exist_ok=True)
        workspace = Path(
            os.environ.get("HOMUNCULA_WORKSPACE", os.getcwd())
        ).expanduser().resolve()

        return cls(
            home=home,
            db_path=Path(os.environ.get("HOMUNCULA_DB", home / "homuncula.sqlite3")),
            workspace=workspace,
            ollama_base_url=os.environ.get(
                "HOMUNCULA_OLLAMA_URL", "http://127.0.0.1:11434"
            ).rstrip("/"),
            model=os.environ.get("HOMUNCULA_MODEL", "qwen3:8b"),
            host=os.environ.get("HOMUNCULA_HOST", "127.0.0.1"),
            port=int(os.environ.get("HOMUNCULA_PORT", "43900")),
            owner_token=load_or_create_owner_token(home),
            browser_channel=os.environ.get(
                "HOMUNCULA_BROWSER_CHANNEL",
                "msedge" if os.name == "nt" else "chromium",
            ),
            proactive_enabled=_bool_env("HOMUNCULA_PROACTIVE", True),
            context_token_budget=max(
                2048,
                int(os.environ.get("HOMUNCULA_CONTEXT_TOKENS", "12000")),
            ),
            review_enabled=_bool_env("HOMUNCULA_REVIEW", True),
        )
