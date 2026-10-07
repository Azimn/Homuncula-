from __future__ import annotations

import asyncio
import bz2
import io
import math
import os
import shutil
import tarfile
import tempfile
import wave
from pathlib import Path
from typing import Any, Literal

import httpx

ASR_MODEL_NAME = "sherpa-onnx-whisper-tiny.en"
ASR_MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
    "sherpa-onnx-whisper-tiny.en.tar.bz2"
)
TTS_MODEL_NAME = "kokoro-en-v0_19"
TTS_MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/"
    "kokoro-en-v0_19.tar.bz2"
)

VoiceComponent = Literal["asr", "tts"]


class VoiceUnavailable(RuntimeError):
    pass


class VoiceModelError(RuntimeError):
    pass


def _safe_extract_tar_bz2(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    resolved_destination = destination.resolve()
    with bz2.open(archive, "rb") as compressed, tarfile.open(
        fileobj=compressed,
        mode="r:",
    ) as tar:
        members = tar.getmembers()
        for member in members:
            target = (destination / member.name).resolve()
            try:
                target.relative_to(resolved_destination)
            except ValueError as exc:
                raise VoiceModelError(
                    f"Voice model archive contains unsafe path: {member.name}"
                ) from exc
            if member.issym() or member.islnk():
                raise VoiceModelError(
                    f"Voice model archive contains unsupported link: {member.name}"
                )
        tar.extractall(destination, members=members, filter="data")


def _wav_bytes(samples: Any, sample_rate: int) -> bytes:
    try:
        import numpy as np
    except ImportError as exc:
        raise VoiceUnavailable("sherpa-onnx voice runtime is not installed") from exc

    array = np.asarray(samples, dtype=np.float32)
    array = np.clip(array, -1.0, 1.0)
    pcm = (array * 32767.0).astype(np.int16).tobytes()
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(int(sample_rate))
        wav.writeframes(pcm)
    return output.getvalue()


def _read_wav(data: bytes) -> tuple[Any, int]:
    try:
        import numpy as np
    except ImportError as exc:
        raise VoiceUnavailable("sherpa-onnx voice runtime is not installed") from exc

    try:
        with wave.open(io.BytesIO(data), "rb") as wav:
            channels = wav.getnchannels()
            width = wav.getsampwidth()
            sample_rate = wav.getframerate()
            frames = wav.readframes(wav.getnframes())
    except (wave.Error, EOFError) as exc:
        raise VoiceModelError("Voice input must be a valid WAV file") from exc

    if channels != 1 or width != 2:
        raise VoiceModelError("Voice input must be mono 16-bit PCM WAV")

    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    return samples, sample_rate


class VoiceManager:
    def __init__(self, home: Path):
        self.root = Path(home) / "voice"
        self.models = self.root / "models"
        self.models.mkdir(parents=True, exist_ok=True)
        self._recognizer: Any | None = None
        self._tts: Any | None = None
        self._locks = {
            "asr": asyncio.Lock(),
            "tts": asyncio.Lock(),
        }

    @property
    def asr_dir(self) -> Path:
        return self.models / ASR_MODEL_NAME

    @property
    def tts_dir(self) -> Path:
        return self.models / TTS_MODEL_NAME

    @staticmethod
    def engine_available() -> bool:
        try:
            import sherpa_onnx  # noqa: F401
        except ImportError:
            return False
        return True

    def status(self) -> dict[str, Any]:
        return {
            "engine_available": self.engine_available(),
            "asr": {
                "installed": self._asr_files() is not None,
                "model": ASR_MODEL_NAME,
            },
            "tts": {
                "installed": self._tts_files() is not None,
                "model": TTS_MODEL_NAME,
                "speakers": 11,
                "default_speaker": 10,
            },
        }

    async def install(self, component: VoiceComponent) -> dict[str, Any]:
        if component not in {"asr", "tts"}:
            raise ValueError("Voice component must be asr or tts")
        async with self._locks[component]:
            if component == "asr" and self._asr_files() is not None:
                return self.status()
            if component == "tts" and self._tts_files() is not None:
                return self.status()

            url = ASR_MODEL_URL if component == "asr" else TTS_MODEL_URL
            expected_dir = self.asr_dir if component == "asr" else self.tts_dir
            await self._download_and_extract(url, expected_dir)
            self._recognizer = None
            self._tts = None

            if component == "asr" and self._asr_files() is None:
                raise VoiceModelError("Downloaded ASR model did not contain required files")
            if component == "tts" and self._tts_files() is None:
                raise VoiceModelError("Downloaded TTS model did not contain required files")
            return self.status()

    async def _download_and_extract(self, url: str, expected_dir: Path) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.root) as raw_temp:
            temp = Path(raw_temp)
            archive = temp / "model.tar.bz2"
            async with (
                httpx.AsyncClient(timeout=None, follow_redirects=True) as client,
                client.stream("GET", url) as response,
            ):
                response.raise_for_status()
                with archive.open("wb") as output:
                    async for chunk in response.aiter_bytes(1024 * 1024):
                        output.write(chunk)

            extracted = temp / "extracted"
            await asyncio.to_thread(_safe_extract_tar_bz2, archive, extracted)
            candidates = [
                path
                for path in extracted.iterdir()
                if path.is_dir()
            ]
            if len(candidates) != 1:
                raise VoiceModelError("Voice model archive has unexpected structure")
            source = candidates[0]
            if expected_dir.exists():
                shutil.rmtree(expected_dir)
            shutil.move(str(source), str(expected_dir))

    def transcribe_wav(self, data: bytes) -> dict[str, Any]:
        recognizer = self._get_recognizer()
        samples, sample_rate = _read_wav(data)
        stream = recognizer.create_stream()
        stream.accept_waveform(sample_rate, samples)
        recognizer.decode_stream(stream)
        text = str(stream.result.text or "").strip()
        duration = len(samples) / max(1, sample_rate)
        return {
            "text": text,
            "duration_seconds": round(duration, 3),
            "model": ASR_MODEL_NAME,
        }

    def synthesize(
        self,
        text: str,
        *,
        speaker: int = 10,
        speed: float = 1.0,
    ) -> bytes:
        clean = text.strip()
        if not clean:
            raise ValueError("Text is required")
        if len(clean) > 12_000:
            raise ValueError("Text is too long for one voice response")
        speaker = max(0, min(10, int(speaker)))
        speed = max(0.5, min(2.0, float(speed)))

        sherpa_onnx = self._sherpa()
        tts = self._get_tts()
        generation = sherpa_onnx.GenerationConfig()
        generation.sid = speaker
        generation.speed = speed
        generation.silence_scale = 0.2
        audio = tts.generate(clean, generation)
        if len(audio.samples) == 0:
            raise VoiceModelError("Local TTS returned no audio")
        return _wav_bytes(audio.samples, int(audio.sample_rate))

    def _sherpa(self) -> Any:
        try:
            import sherpa_onnx
        except ImportError as exc:
            raise VoiceUnavailable(
                "Local voice runtime is not installed in this Homuncula build"
            ) from exc
        return sherpa_onnx

    def _asr_files(self) -> dict[str, Path] | None:
        files = {
            "encoder": self.asr_dir / "tiny.en-encoder.int8.onnx",
            "decoder": self.asr_dir / "tiny.en-decoder.int8.onnx",
            "tokens": self.asr_dir / "tiny.en-tokens.txt",
        }
        return files if all(path.is_file() for path in files.values()) else None

    def _tts_files(self) -> dict[str, Path] | None:
        files = {
            "model": self.tts_dir / "model.onnx",
            "voices": self.tts_dir / "voices.bin",
            "tokens": self.tts_dir / "tokens.txt",
            "data_dir": self.tts_dir / "espeak-ng-data",
        }
        return files if all(path.exists() for path in files.values()) else None

    def _get_recognizer(self) -> Any:
        if self._recognizer is not None:
            return self._recognizer
        files = self._asr_files()
        if not files:
            raise VoiceUnavailable("Local speech recognition model is not installed")
        sherpa_onnx = self._sherpa()
        threads = max(1, min(4, math.ceil((os.cpu_count() or 2) / 2)))
        self._recognizer = sherpa_onnx.OfflineRecognizer.from_whisper(
            encoder=str(files["encoder"]),
            decoder=str(files["decoder"]),
            tokens=str(files["tokens"]),
            num_threads=threads,
            decoding_method="greedy_search",
            debug=False,
            language="en",
            task="transcribe",
        )
        return self._recognizer

    def _get_tts(self) -> Any:
        if self._tts is not None:
            return self._tts
        files = self._tts_files()
        if not files:
            raise VoiceUnavailable("Local Kokoro voice model is not installed")
        sherpa_onnx = self._sherpa()
        config = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
                    model=str(files["model"]),
                    voices=str(files["voices"]),
                    tokens=str(files["tokens"]),
                    data_dir=str(files["data_dir"]),
                    lexicon="",
                ),
                provider="cpu",
                debug=False,
                num_threads=max(1, min(4, (os.cpu_count() or 2) // 2)),
            ),
            max_num_sentences=1,
        )
        if not config.validate():
            raise VoiceModelError("Kokoro TTS configuration is invalid")
        self._tts = sherpa_onnx.OfflineTts(config)
        return self._tts
