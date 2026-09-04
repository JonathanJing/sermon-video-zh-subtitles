from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import threading
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SESSION_ID_PATTERN = re.compile(r"[0-9]{8}T[0-9]{6}\.[0-9]{3}Z-[0-9a-f]{8}")


class SessionStoreError(ValueError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _audio_extension(mime_type: str) -> str:
    normalized = mime_type.lower().split(";", 1)[0].strip()
    return {
        "audio/webm": ".webm",
        "audio/mp4": ".m4a",
        "audio/ogg": ".ogg",
        "audio/wav": ".wav",
    }.get(normalized, ".audio")


class SessionStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def create(self, metadata: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        session_id = f"{now.strftime('%Y%m%dT%H%M%S')}.{now.microsecond // 1000:03d}Z-{secrets.token_hex(4)}"
        directory = self.root / session_id
        directory.mkdir(mode=0o700)
        mime_type = str(metadata.get("audioMimeType") or "audio/webm").strip()
        audio_name = "recording" + _audio_extension(mime_type)
        manifest = {
            "schemaVersion": 1,
            "sessionId": session_id,
            "viewerToken": secrets.token_urlsafe(18),
            "status": "recording",
            "startedAt": _now_iso(),
            "stoppedAt": None,
            "durationMs": None,
            "audioMimeType": mime_type,
            "audioFile": audio_name,
            "eventFile": "events.jsonl",
            "audioChunkCount": 0,
            "audioBytes": 0,
            "audioSha256": None,
            "asrPcmFile": "asr-audio.pcm",
            "asrWavFile": "asr-audio.wav",
            "pcmFrameCount": 0,
            "pcmBytes": 0,
            "pcmSha256": None,
            "pcmWavSha256": None,
            "eventCount": 0,
            "metadata": metadata,
        }
        (directory / audio_name).touch(mode=0o600)
        (directory / manifest["asrPcmFile"]).touch(mode=0o600)
        (directory / "events.jsonl").touch(mode=0o600)
        self._write_manifest(directory, manifest)
        return self._public(manifest, directory)

    def health(
        self,
        minimum_free_bytes: int = 10 * 1024 * 1024 * 1024,
        probe_write: bool = False,
    ) -> dict[str, Any]:
        probe_path: Path | None = None
        try:
            usage = shutil.disk_usage(self.root)
            if probe_write:
                probe_path = self.root / f".storage-probe-{secrets.token_hex(4)}"
                with probe_path.open("xb") as output:
                    output.write(b"local-live-storage-probe\n")
                    output.flush()
                    os.fsync(output.fileno())
            available = os.access(self.root, os.W_OK) and usage.free >= minimum_free_bytes
            return {
                "available": available,
                "directory": str(self.root),
                "freeBytes": usage.free,
                "minimumFreeBytes": minimum_free_bytes,
                "reason": None if available else "insufficient_space_or_not_writable",
            }
        except OSError as error:
            return {
                "available": False,
                "directory": str(self.root),
                "freeBytes": None,
                "minimumFreeBytes": minimum_free_bytes,
                "reason": str(error),
            }
        finally:
            if probe_path is not None:
                try:
                    probe_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def recover_incomplete(self) -> list[dict[str, Any]]:
        recovered: list[dict[str, Any]] = []
        with self._lock:
            for directory in sorted(self.root.iterdir()):
                if not directory.is_dir() or not SESSION_ID_PATTERN.fullmatch(directory.name):
                    continue
                manifest_path = directory / "manifest.json"
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if manifest.get("status") != "recording":
                    continue
                manifest["recoveryReason"] = "gateway_restart_before_finalize"
                inferred_duration_ms = max(
                    int(manifest.get("pcmFrameCount") or 0) * 100,
                    int(manifest.get("audioChunkCount") or 0) * 1000,
                )
                self._finalize_manifest(directory, manifest, {
                    "status": "incomplete",
                    "stoppedAt": _now_iso(),
                    "durationMs": manifest.get("durationMs") or inferred_duration_ms,
                })
                recovered.append(self._public(manifest, directory))
        return recovered

    def get_recording(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            directory, manifest = self._load(session_id)
            self._require_recording(manifest)
            return self._public(manifest, directory)

    def resume(self, session_id: str, available_audio_chunks: int) -> dict[str, Any]:
        """Reopen only a recoverable recording; never rewrite its saved audio.

        The browser retains the original MediaRecorder chunks and resends only
        those after the durable count. A torn append fails closed for manual
        recovery instead of duplicating bytes in a seemingly valid recording.
        """
        with self._lock:
            directory, manifest = self._load(session_id)
            if manifest.get("status") not in {"recording", "incomplete"}:
                raise SessionStoreError("a completed session cannot be resumed")
            if manifest.get("status") == "incomplete" and manifest.get("recoveryReason") != "gateway_restart_before_finalize":
                raise SessionStoreError("only a gateway-interrupted session can be resumed")
            if available_audio_chunks < int(manifest["audioChunkCount"]):
                raise SessionStoreError("browser does not retain the original recording chunks")
            for filename, count_key in (("audioFile", "audioBytes"), ("asrPcmFile", "pcmBytes")):
                if (directory / manifest[filename]).stat().st_size != int(manifest[count_key]):
                    raise SessionStoreError("recording size differs from durable manifest; preserve browser recovery copy")
            try:
                events = [json.loads(line) for line in (directory / "events.jsonl").read_text(encoding="utf-8").splitlines()]
            except (OSError, json.JSONDecodeError) as error:
                raise SessionStoreError("event log is incomplete; preserve browser recovery copy") from error
            if len(events) != int(manifest["eventCount"]):
                raise SessionStoreError("event log differs from durable manifest")
            resume_count = int(manifest.get("resumeCount") or 0) + 1
            snapshot = directory / f"recovery-{resume_count:04d}.manifest.json"
            reusable_snapshot = False
            if snapshot.exists():
                try:
                    reusable_snapshot = json.loads(snapshot.read_text(encoding="utf-8")) == manifest
                except (OSError, json.JSONDecodeError):
                    pass
                if not reusable_snapshot:
                    # Preserve a prior or interrupted snapshot; never overwrite
                    # evidence merely because a manifest update was interrupted.
                    snapshot = directory / f"recovery-{resume_count:04d}-{secrets.token_hex(4)}.manifest.json"
            if not reusable_snapshot:
                with snapshot.open("x", encoding="utf-8") as output:
                    json.dump(manifest, output, ensure_ascii=False, indent=2)
            manifest.update({
                "status": "recording", "stoppedAt": None, "durationMs": None,
                "audioSha256": None, "pcmSha256": None, "pcmWavSha256": None,
                "resumeCount": resume_count, "lastResumedAt": _now_iso(),
                "recoverySnapshotFile": snapshot.name,
                "resumeEventBaseline": len(events),
                "captionContinuity": "interrupted",
            })
            self._write_manifest(directory, manifest)
            return self._public(manifest, directory)

    def stream_position(self, session_id: str) -> dict[str, int]:
        with self._lock:
            directory, manifest = self._load(session_id)
            self._require_recording(manifest)
            maximum = 0
            for line in (directory / "events.jsonl").read_text(encoding="utf-8").splitlines():
                event = json.loads(line)
                match = re.fullmatch(r"seg-(\d+)", str(event.get("segmentId") or ""))
                if match:
                    maximum = max(maximum, int(match.group(1)))
            return {"pcmFrameCount": int(manifest["pcmFrameCount"]), "segmentCount": maximum}

    def append_audio(self, session_id: str, sequence: int, data: bytes) -> dict[str, Any]:
        if sequence < 1:
            raise SessionStoreError("audio sequence must be positive")
        if not data:
            raise SessionStoreError("audio chunk is empty")
        with self._lock:
            directory, manifest = self._load(session_id)
            self._require_recording(manifest)
            expected = int(manifest["audioChunkCount"]) + 1
            if sequence != expected:
                raise SessionStoreError(f"audio sequence must be {expected}")
            with (directory / manifest["audioFile"]).open("ab") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            manifest["audioChunkCount"] = sequence
            manifest["audioBytes"] = int(manifest["audioBytes"]) + len(data)
            self._write_manifest(directory, manifest)
            return {
                "sessionId": session_id,
                "audioChunkCount": sequence,
                "audioBytes": manifest["audioBytes"],
            }

    def append_pcm_frames(
        self,
        session_id: str,
        first_sequence: int,
        frame_count: int,
        data: bytes,
        frame_bytes: int = 3200,
    ) -> dict[str, Any]:
        if first_sequence < 1 or frame_count < 1:
            raise SessionStoreError("PCM frame sequence and count must be positive")
        if len(data) != frame_count * frame_bytes:
            raise SessionStoreError("PCM payload does not match frame count")
        with self._lock:
            directory, manifest = self._load(session_id)
            self._require_recording(manifest)
            expected = int(manifest["pcmFrameCount"]) + 1
            if first_sequence != expected:
                raise SessionStoreError(f"PCM frame sequence must be {expected}")
            with (directory / manifest["asrPcmFile"]).open("ab") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            manifest["pcmFrameCount"] = first_sequence + frame_count - 1
            manifest["pcmBytes"] = int(manifest["pcmBytes"]) + len(data)
            self._write_manifest(directory, manifest)
            return {
                "sessionId": session_id,
                "pcmFrameCount": manifest["pcmFrameCount"],
                "pcmBytes": manifest["pcmBytes"],
            }

    def append_event(
        self,
        session_id: str,
        event: dict[str, Any],
        assign_sequence: bool = False,
    ) -> dict[str, Any]:
        sequence = event.get("sequence")
        if not assign_sequence and (not isinstance(sequence, int) or sequence < 1):
            raise SessionStoreError("event sequence must be a positive integer")
        with self._lock:
            directory, manifest = self._load(session_id)
            self._require_recording(manifest)
            expected = int(manifest["eventCount"]) + 1
            stored_event = dict(event)
            if assign_sequence:
                if isinstance(sequence, int) and sequence != expected:
                    stored_event["clientSequence"] = sequence
                sequence = expected
                stored_event["sequence"] = sequence
            elif sequence != expected:
                raise SessionStoreError(f"event sequence must be {expected}")
            stored_event.setdefault("at", _now_iso())
            line = json.dumps(stored_event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            with (directory / manifest["eventFile"]).open("a", encoding="utf-8") as output:
                output.write(line)
                output.flush()
                os.fsync(output.fileno())
            manifest["eventCount"] = sequence
            self._write_manifest(directory, manifest)
            return {"sessionId": session_id, "eventCount": sequence, "event": stored_event}

    def finalize(self, session_id: str, details: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            directory, manifest = self._load(session_id)
            if manifest.get("status") in {"completed", "incomplete"}:
                return self._public(manifest, directory)
            self._require_recording(manifest)
            self._finalize_manifest(directory, manifest, details)
            return self._public(manifest, directory)

    def _finalize_manifest(
        self,
        directory: Path,
        manifest: dict[str, Any],
        details: dict[str, Any],
    ) -> None:
        status = str(details.get("status") or "completed")
        if status not in {"completed", "incomplete"}:
            raise SessionStoreError("status must be completed or incomplete")
        if manifest.get("metadata", {}).get("mode") == "local_live_asr_translation":
            events = []
            try:
                events = [json.loads(line) for line in (directory / "events.jsonl").read_text(encoding="utf-8").splitlines()]
            except (OSError, json.JSONDecodeError):
                status = "incomplete"
            closed = next((event for event in reversed(events) if event.get("type") == "stream.closed"), {})
            latest_ready = max((index for index, event in enumerate(events) if event.get("type") in {"stream.ready", "stream.resume_requested"}), default=-1)
            latest_closed = max((index for index, event in enumerate(events) if event.get("type") == "stream.closed"), default=-1)
            stream_confirmed = bool(
                manifest.get("pcmFrameCount") and closed.get("workerDrained") is True
                and closed.get("storageHealthy") is True
                and closed.get("lastFrameSequence") == manifest.get("pcmFrameCount")
                and latest_closed > latest_ready >= 0
                and latest_ready >= int(manifest.get("resumeEventBaseline") or 0)
            )
            if not stream_confirmed:
                status = "incomplete"
            # These are delivery outcomes, never accuracy or human review.
            counts = {kind: sum(e.get("type") == kind for e in events) for kind in (
                "asr.final", "asr.empty", "asr.failed", "translation.final",
                "translation.failed", "translation.skipped", "audio.stream_gap",
            )}
            manifest["liveOutcome"] = {
                "drainConfirmed": stream_confirmed, "eventCounts": counts,
                "captionContinuity": "interrupted" if manifest.get("resumeCount") or counts["audio.stream_gap"] else "uninterrupted",
                "qualityReviewStatus": "not_human_reviewed",
            }
        try:
            duration_ms = max(0, int(details.get("durationMs") or 0))
        except (TypeError, ValueError) as error:
            raise SessionStoreError("durationMs must be an integer") from error
        audio_path = directory / manifest["audioFile"]
        pcm_path = directory / manifest["asrPcmFile"]
        wav_path = directory / manifest["asrWavFile"]
        if pcm_path.stat().st_size:
            with wave.open(str(wav_path), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(16000)
                with pcm_path.open("rb") as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        output.writeframesraw(chunk)
        manifest.update({
            "status": status,
            "stoppedAt": str(details.get("stoppedAt") or _now_iso()),
            "durationMs": duration_ms,
            "audioSha256": self._sha256(audio_path),
            "pcmSha256": self._sha256(pcm_path) if pcm_path.stat().st_size else None,
            "pcmWavSha256": self._sha256(wav_path) if wav_path.is_file() else None,
        })
        self._write_manifest(directory, manifest)

    def _load(self, session_id: str) -> tuple[Path, dict[str, Any]]:
        if not SESSION_ID_PATTERN.fullmatch(session_id):
            raise SessionStoreError("invalid session id")
        directory = self.root / session_id
        try:
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise SessionStoreError("session does not exist") from error
        return directory, manifest

    @staticmethod
    def _require_recording(manifest: dict[str, Any]) -> None:
        if manifest.get("status") != "recording":
            raise SessionStoreError("session is not recording")

    @staticmethod
    def _write_manifest(directory: Path, manifest: dict[str, Any]) -> None:
        temporary = directory / "manifest.json.tmp"
        temporary.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(directory / "manifest.json")

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _public(manifest: dict[str, Any], directory: Path) -> dict[str, Any]:
        return {
            **manifest,
            "directory": str(directory),
            "manifestPath": str(directory / "manifest.json"),
            "audioPath": str(directory / manifest["audioFile"]),
            "asrPcmPath": str(directory / manifest["asrPcmFile"]),
            "asrWavPath": str(directory / manifest["asrWavFile"]),
            "eventPath": str(directory / manifest["eventFile"]),
        }
