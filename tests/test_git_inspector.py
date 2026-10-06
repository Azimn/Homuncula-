from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from homuncula.api import create_app
from homuncula.config import Settings
from homuncula.git_inspector import GitInspector
from homuncula.secrets_store import MemorySecretStore


def _init_repo(path: Path) -> None:
    subprocess.run(
        ["git", "init"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "homuncula@example.invalid"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Homuncula Test"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    (path / "tracked.txt").write_text("before\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "tracked.txt"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "fixture"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )


def test_git_inspector_reports_workspace_changes_without_mutation(
    tmp_path: Path,
) -> None:
    _init_repo(tmp_path)
    (tmp_path / "tracked.txt").write_text("after\n", encoding="utf-8")
    (tmp_path / "untracked.txt").write_text("new\n", encoding="utf-8")

    inspector = GitInspector(tmp_path)
    status = inspector.status()

    paths = {item["path"] for item in status["files"]}
    assert "tracked.txt" in paths
    assert "untracked.txt" in paths
    assert status["branch"]

    diff = inspector.diff("tracked.txt")
    assert "-before" in diff["diff"]
    assert "+after" in diff["diff"]

    with pytest.raises(PermissionError, match="escapes workspace"):
        inspector.diff("../outside.txt")

    assert (tmp_path / "tracked.txt").read_text(encoding="utf-8") == "after\n"


def test_git_inspector_api_is_authenticated_and_read_only(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _init_repo(workspace)
    (workspace / "tracked.txt").write_text("changed\n", encoding="utf-8")

    settings = Settings(
        home=tmp_path / "home",
        db_path=tmp_path / "home" / "agent.sqlite3",
        workspace=workspace,
        ollama_base_url="http://127.0.0.1:11434",
        model="test-model",
        host="127.0.0.1",
        port=43900,
        owner_token="owner-token-value-that-is-long-enough-1234567890",
        browser_channel="chromium",
        proactive_enabled=False,
        context_token_budget=4096,
    )
    app = create_app(settings, secret_store=MemorySecretStore())
    headers = {"Authorization": f"Bearer {settings.owner_token}"}

    with TestClient(app) as client:
        assert client.get("/computer/git").status_code == 401

        status = client.get("/computer/git", headers=headers)
        assert status.status_code == 200
        assert any(
            item["path"] == "tracked.txt"
            for item in status.json()["files"]
        )

        diff = client.get(
            "/computer/git/diff",
            params={"path": "tracked.txt"},
            headers=headers,
        )
        assert diff.status_code == 200
        assert "+changed" in diff.json()["diff"]

        escaped = client.get(
            "/computer/git/diff",
            params={"path": "../outside.txt"},
            headers=headers,
        )
        assert escaped.status_code == 400

    assert (workspace / "tracked.txt").read_text(encoding="utf-8") == "changed\n"
