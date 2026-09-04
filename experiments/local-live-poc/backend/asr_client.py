from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
import time
import wave
from pathlib import Path
from typing import Any


class AsrError(RuntimeError):
    pass


class WhisperCliClient:
    def __init__(
        self,
        model_path: str = "",
        binary: str = "whisper-cli",
        threads: int = 8,
    ) -> None:
        self.model_path = Path(model_path).expanduser().resolve() if model_path else None
        self.binary = shutil.which(binary) or binary
        self.threads = max(1, threads)
        self._model_sha256: str | None = None

    def status(self) -> dict[str, Any]:
        binary_path = shutil.which(self.binary) or (self.binary if Path(self.binary).is_file() else None)
        model_ready = bool(self.model_path and self.model_path.is_file())
        return {
            "available": bool(binary_path and model_ready),
            "provider": "whisper.cpp-cli",
            "binary": str(binary_path) if binary_path else self.binary,
            "modelPath": str(self.model_path) if self.model_path else None,
            "modelInstalled": model_ready,
            "modelSha256": self.model_sha256() if model_ready else None,
        }

    def transcribe(self, pcm_s16le: bytes, sample_rate_hz: int = 16000) -> dict[str, Any]:
        status = self.status()
        if not status["available"]:
            raise AsrError("whisper-cli or the configured ASR model is unavailable")
        if not pcm_s16le or len(pcm_s16le) % 2:
            raise AsrError("ASR PCM must contain complete signed 16-bit samples")

        started = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="local-live-asr-") as temporary:
            audio_path = Path(temporary) / "segment.wav"
            with wave.open(str(audio_path), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(sample_rate_hz)
                output.writeframes(pcm_s16le)
            command = [
                self.binary,
                "-m", str(self.model_path),
                "-f", str(audio_path),
                "-l", "en",
                "-nt",
                "-np",
                "-t", str(self.threads),
            ]
            try:
                completed = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                raise AsrError(f"whisper-cli failed: {error}") from error
        if completed.returncode != 0:
            detail = completed.stderr.strip().splitlines()[-1:] or ["unknown error"]
            raise AsrError(f"whisper-cli exited {completed.returncode}: {detail[0]}")
        text = " ".join(completed.stdout.split()).strip()
        return {
            "sourceTextEn": text,
            "provider": "whisper.cpp-cli",
            "modelPath": str(self.model_path),
            "modelSha256": self.model_sha256(),
            "latencyMs": round((time.perf_counter() - started) * 1000),
            "audioDurationMs": round(len(pcm_s16le) / 2 / sample_rate_hz * 1000),
        }

    def model_sha256(self) -> str | None:
        if not self.model_path or not self.model_path.is_file():
            return None
        if self._model_sha256:
            return self._model_sha256
        digest = hashlib.sha256()
        with self.model_path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        self._model_sha256 = digest.hexdigest()
        return self._model_sha256
