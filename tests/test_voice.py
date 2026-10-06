from __future__ import annotations

import io
import tarfile
from pathlib import Path

from fastapi.testclient import TestClient

from homuncula.api import create_app
from homuncula.config import Settings
from homuncula.secrets_store import MemorySecretStore
from homuncula.voice import (
    ASR_MODEL_NAME,
    TTS_MODEL_NAME,
    VoiceManager,
    VoiceModelError,
    _safe_extract_tar_bz2,
)


def settings(tmp_path: Path) -> Settings:
    return Settings(
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
        review_enabled=False,
    )


def write_archive(path: Path, members: list[tuple[str, bytes]]) -> None:
    with tarfile.open(path, "w:bz2") as tar:
        for name, data in members:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


def test_voice_archive_extracts_only_inside_destination(tmp_path: Path) -> None:
    archive = tmp_path / "model.tar.bz2"
    write_archive(
        archive,
        [
            ("model/model.onnx", b"model"),
            ("model/tokens.txt", b"tokens"),
        ],
    )
    destination = tmp_path / "out"
    _safe_extract_tar_bz2(archive, destination)
    assert (destination / "model" / "model.onnx").read_bytes() == b"model"


def test_voice_archive_rejects_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.tar.bz2"
    write_archive(archive, [("../escape.txt", b"no")])

    try:
        _safe_extract_tar_bz2(archive, tmp_path / "out")
    except VoiceModelError as exc:
        assert "unsafe path" in str(exc)
    else:
        raise AssertionError("Unsafe model archive path must be rejected")

    assert not (tmp_path / "escape.txt").exists()


def test_voice_status_detects_installed_model_layouts(tmp_path: Path) -> None:
    manager = VoiceManager(tmp_path)

    asr = manager.models / ASR_MODEL_NAME
    asr.mkdir(parents=True)
    for name in (
        "tiny.en-encoder.int8.onnx",
        "tiny.en-decoder.int8.onnx",
        "tiny.en-tokens.txt",
    ):
        (asr / name).write_bytes(b"x")

    tts = manager.models / TTS_MODEL_NAME
    tts.mkdir(parents=True)
    for name in ("model.onnx", "voices.bin", "tokens.txt"):
        (tts / name).write_bytes(b"x")
    (tts / "espeak-ng-data").mkdir()

    status = manager.status()
    assert status["asr"]["installed"] is True
    assert status["tts"]["installed"] is True
    assert status["tts"]["speakers"] == 11


def test_voice_api_reports_status_and_missing_models(tmp_path: Path) -> None:
    config = settings(tmp_path)
    app = create_app(config, secret_store=MemorySecretStore())
    headers = {"Authorization": f"Bearer {config.owner_token}"}

    with TestClient(app) as client:
        status = client.get("/voice/status", headers=headers)
        assert status.status_code == 200
        assert status.json()["asr"]["installed"] is False
        assert status.json()["tts"]["installed"] is False

        transcribe = client.post(
            "/voice/transcribe",
            headers={**headers, "Content-Type": "audio/wav"},
            content=b"not-a-wave",
        )
        assert transcribe.status_code == 503

        synthesize = client.post(
            "/voice/synthesize",
            headers=headers,
            json={"text": "hello", "speaker": 10, "speed": 1.0},
        )
        assert synthesize.status_code == 503
