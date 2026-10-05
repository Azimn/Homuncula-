from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    home: Path
    db_path: Path
    workspace: Path
    ollama_base_url: str
    model: str
    host: str
    port: int

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
        )
