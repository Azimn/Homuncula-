from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from homuncula.api import create_app
from homuncula.config import Settings
from homuncula.db import Database
from homuncula.plans import PlanError, PlanStore
from homuncula.secrets_store import MemorySecretStore
from homuncula.skills import SkillStore


def seed_responsibility(db: Database) -> None:
    stamp = "2026-10-05T00:00:00+00:00"
    db.execute(
        "INSERT INTO threads (id, title, created_at, updated_at) VALUES ('t', 'Main', ?, ?)",
        (stamp, stamp),
    )
    db.execute(
        """
        INSERT INTO responsibilities
        (id, thread_id, title, objective, status, proactive_mode, created_at, updated_at)
        VALUES ('r', 't', 'Build', 'Complete the task', 'active', 'observe', ?, ?)
        """,
        (stamp, stamp),
    )


def test_plan_lifecycle_is_durable_and_single_active(tmp_path: Path) -> None:
    db = Database(tmp_path / "plan.sqlite3")
    db.initialize()
    seed_responsibility(db)
    plans = PlanStore(db)

    plan = plans.create(
        "r",
        title="Implementation",
        goal="Finish safely",
        steps=["Inspect", {"title": "Change", "detail": "Apply patch"}, "Verify"],
    )
    assert plan["status"] == "active"
    assert plan["current_step"] == 1
    assert plan["steps"][0]["status"] == "active"

    try:
        plans.create("r", title="Second", goal="No", steps=["x"])
    except PlanError:
        pass
    else:
        raise AssertionError("A second active plan must be rejected")

    plan = plans.advance(plan["id"], summary="Inspection complete")
    assert plan["current_step"] == 2
    assert plan["steps"][0]["status"] == "complete"
    assert plan["steps"][1]["status"] == "active"

    plan = plans.block_step(plan["id"], reason="Waiting for approval")
    assert plan["status"] == "blocked"
    assert plan["steps"][1]["status"] == "blocked"

    plan = plans.resume(plan["id"])
    assert plan["status"] == "active"
    assert plan["steps"][1]["status"] == "active"

    plan = plans.advance(plan["id"], summary="Patch complete")
    plan = plans.advance(plan["id"], summary="Verification complete")
    assert plan["status"] == "complete"
    assert plan["current_step"] is None
    assert all(step["status"] == "complete" for step in plan["steps"])


def test_local_skill_roundtrip_search_and_remove(tmp_path: Path) -> None:
    store = SkillStore(tmp_path / "skills")
    installed = store.install(
        name="Python Repair",
        description="Repair and validate Python projects",
        instructions="Inspect first. Make a small change. Run tests.",
        allowed_tools=["read_file", "write_file", "run_process"],
        source="test",
    )

    assert installed["name"] == "python-repair"
    assert installed["allowed_tools"] == ["read_file", "write_file", "run_process"]
    assert store.get("python-repair").instructions.startswith("Inspect first")
    assert store.search("repair Python tests")[0]["name"] == "python-repair"

    nested = tmp_path / "skills" / "python-repair" / "notes"
    nested.mkdir()
    (nested / "example.txt").write_text("extra", encoding="utf-8")
    store.remove("python-repair")
    assert not (tmp_path / "skills" / "python-repair").exists()


def test_local_api_rejects_unauthenticated_loopback(tmp_path: Path) -> None:
    settings = Settings(
        home=tmp_path / "home",
        db_path=tmp_path / "home" / "agent.sqlite3",
        workspace=tmp_path,
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

    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/state").status_code == 401
        response = client.get(
            "/state",
            headers={"Authorization": f"Bearer {settings.owner_token}"},
        )
        assert response.status_code == 200
        assert "responsibilities" in response.json()
