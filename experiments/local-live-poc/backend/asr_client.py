from __future__ import annotations

import hashlib
import json
import socket
import shutil
import struct
import subprocess
import tempfile
import time
import wave
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect


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


class MlxAudioWebSocketClient:
    """Synchronous segment client for the MLX Audio realtime STT endpoint."""

    def __init__(self, model_path: str, url: str) -> None:
        self.model_path = Path(model_path).expanduser().resolve() if model_path else None
        self.url = url.strip()
        self._model_sha256: str | None = None

    def status(self) -> dict[str, Any]:
        parsed = urlparse(self.url)
        model_ready = bool(self.model_path and self.model_path.is_dir())
        endpoint_ready = False
        if parsed.hostname and parsed.port:
            try:
                with socket.create_connection((parsed.hostname, parsed.port), timeout=0.5):
                    endpoint_ready = True
            except OSError:
                pass
        return {
            "available": model_ready and endpoint_ready,
            "provider": "mlx-audio-qwen-websocket",
            "url": self.url,
            "modelPath": str(self.model_path) if self.model_path else None,
            "modelInstalled": model_ready,
            "modelSha256": self.model_sha256() if model_ready else None,
            "endpointAvailable": endpoint_ready,
        }

    def transcribe(self, pcm_s16le: bytes, sample_rate_hz: int = 16000) -> dict[str, Any]:
        if not pcm_s16le or len(pcm_s16le) % 2:
            raise AsrError("ASR PCM must contain complete signed 16-bit samples")
        status = self.status()
        if not status["available"]:
            raise AsrError("MLX Audio endpoint or configured Qwen ASR model is unavailable")
        started = time.perf_counter()
        final_texts: list[str] = []
        try:
            with connect(self.url, max_size=None, open_timeout=5, close_timeout=2) as websocket:
                websocket.send(json.dumps({
                    "model": str(self.model_path),
                    "language": "English",
                    "sample_rate": sample_rate_hz,
                }))
                ready = json.loads(websocket.recv(timeout=120))
                if ready.get("status") != "ready":
                    raise AsrError(f"MLX Audio endpoint did not become ready: {ready}")
                websocket.send(pcm_s16le)
                marker = self._highest_energy_frame(pcm_s16le, sample_rate_hz)
                max_buffer_bytes = sample_rate_hz * 2 * 5
                padding_bytes = max(0, max_buffer_bytes - len(pcm_s16le))
                if padding_bytes:
                    padding = (marker + bytes(padding_bytes))[:padding_bytes]
                    websocket.send(padding)
                # With sub-1.5-second input, the padded message emits the
                # endpoint's initial partial first. One extra speech marker
                # then deterministically triggers its max-buffer final.
                if len(pcm_s16le) < round(sample_rate_hz * 2 * 1.5):
                    websocket.send(marker)
                while True:
                    try:
                        payload = json.loads(websocket.recv(timeout=5.0))
                    except TimeoutError:
                        if final_texts:
                            break
                        raise AsrError("MLX Audio returned no final transcription")
                    except ConnectionClosed:
                        if final_texts:
                            break
                        raise AsrError("MLX Audio closed before returning a final transcription")
                    if not payload.get("is_partial", False):
                        text = str(payload.get("text") or "").strip()
                        if text:
                            final_texts.append(text)
                            break
        except AsrError:
            raise
        except Exception as error:
            raise AsrError(f"MLX Audio transcription failed: {error}") from error
        text = " ".join(final_texts).strip()
        return {
            "sourceTextEn": text,
            "provider": "mlx-audio-qwen-websocket",
            "modelPath": str(self.model_path),
            "modelSha256": self.model_sha256(),
            "latencyMs": round((time.perf_counter() - started) * 1000),
            "audioDurationMs": round(len(pcm_s16le) / 2 / sample_rate_hz * 1000),
            "finalEventCount": len(final_texts),
        }

    def model_sha256(self) -> str | None:
        if not self.model_path or not self.model_path.is_dir():
            return None
        if self._model_sha256:
            return self._model_sha256
        weights = self.model_path / "model.safetensors"
        if not weights.is_file():
            return None
        digest = hashlib.sha256()
        with weights.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        self._model_sha256 = digest.hexdigest()
        return self._model_sha256

    @staticmethod
    def _highest_energy_frame(pcm_s16le: bytes, sample_rate_hz: int) -> bytes:
        frame_bytes = round(sample_rate_hz * 0.03) * 2
        frames = [
            pcm_s16le[offset : offset + frame_bytes]
            for offset in range(0, len(pcm_s16le) - frame_bytes + 1, frame_bytes)
        ]
        if not frames:
            return pcm_s16le + bytes(max(0, frame_bytes - len(pcm_s16le)))

        def energy(frame: bytes) -> int:
            samples = struct.unpack(f"<{len(frame) // 2}h", frame)
            return sum(sample * sample for sample in samples)

        return max(frames, key=energy)
