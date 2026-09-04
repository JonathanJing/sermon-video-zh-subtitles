from __future__ import annotations

import hashlib
import json
import socket
import shutil
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

    def warmup(self) -> dict[str, Any]:
        status = self.status()
        return {
            "ready": status["available"],
            "provider": status["provider"],
            "mode": "binary_and_model_check",
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

    def __init__(
        self,
        model_path: str,
        url: str,
        finalize_silence_frames: int = 12,
        finalize_frame_interval_seconds: float = 0.1,
    ) -> None:
        self.model_path = Path(model_path).expanduser().resolve() if model_path else None
        self.url = url.strip()
        self.finalize_silence_frames = max(1, finalize_silence_frames)
        self.finalize_frame_interval_seconds = max(0.0, finalize_frame_interval_seconds)
        self._model_sha256: str | None = None
        self._warmup: dict[str, Any] = {
            "ready": False,
            "mode": "websocket_model_handshake",
            "reason": "not_run",
        }

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
            "available": model_ready and endpoint_ready and self._warmup.get("ready") is True,
            "provider": "mlx-audio-qwen-websocket",
            "url": self.url,
            "modelPath": str(self.model_path) if self.model_path else None,
            "modelInstalled": model_ready,
            "modelSha256": self.model_sha256() if model_ready else None,
            "endpointAvailable": endpoint_ready,
            "warmup": self._warmup,
            "finalization": {
                "mode": "vad_silence_frames",
                "silenceFrameCount": self.finalize_silence_frames,
                "frameIntervalMs": round(self.finalize_frame_interval_seconds * 1000),
            },
        }

    def warmup(self) -> dict[str, Any]:
        parsed = urlparse(self.url)
        if not self.model_path or not self.model_path.is_dir():
            self._warmup = {
                "ready": False,
                "mode": "websocket_model_handshake",
                "reason": "model_missing",
            }
            raise AsrError("configured Qwen ASR model directory is unavailable")
        if not parsed.hostname or not parsed.port:
            self._warmup = {
                "ready": False,
                "mode": "websocket_model_handshake",
                "reason": "invalid_endpoint",
            }
            raise AsrError("configured MLX Audio endpoint is invalid")

        started = time.perf_counter()
        try:
            with connect(self.url, max_size=None, open_timeout=5, close_timeout=2) as websocket:
                websocket.send(json.dumps({
                    "model": str(self.model_path),
                    "language": "English",
                    "sample_rate": 16000,
                }))
                response = json.loads(websocket.recv(timeout=120))
                if response.get("status") != "ready":
                    raise AsrError(f"MLX Audio endpoint did not become ready: {response}")
        except AsrError as error:
            self._warmup = {
                "ready": False,
                "mode": "websocket_model_handshake",
                "reason": str(error),
            }
            raise
        except Exception as error:
            self._warmup = {
                "ready": False,
                "mode": "websocket_model_handshake",
                "reason": str(error),
            }
            raise AsrError(f"MLX Audio warmup failed: {error}") from error

        self._warmup = {
            "ready": True,
            "mode": "websocket_model_handshake",
            "latencyMs": round((time.perf_counter() - started) * 1000),
        }
        return self._warmup

    def transcribe(self, pcm_s16le: bytes, sample_rate_hz: int = 16000) -> dict[str, Any]:
        if not pcm_s16le or len(pcm_s16le) % 2:
            raise AsrError("ASR PCM must contain complete signed 16-bit samples")
        if self._warmup.get("ready") is not True:
            self.warmup()
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
                # mlx-audio 0.3.1 uses WebRTC VAD plus wall-clock silence to
                # finalize an utterance; its stop action closes without
                # flushing. Send short silent frames long enough to clear the
                # VAD hangover and cross its 0.5-second silence interval. This
                # keeps synthetic speech and multi-second padding out of the
                # audio passed to the ASR model.
                silence_frame = bytes(round(sample_rate_hz * 0.03) * 2)
                for _ in range(self.finalize_silence_frames):
                    time.sleep(self.finalize_frame_interval_seconds)
                    websocket.send(silence_frame)
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
            "finalizationMode": "vad_silence_frames",
            "finalizationSilenceFrameCount": self.finalize_silence_frames,
            "finalizationFrameIntervalMs": round(self.finalize_frame_interval_seconds * 1000),
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
