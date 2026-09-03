from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import threading
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
            "eventCount": 0,
            "metadata": metadata,
        }
        (directory / audio_name).touch(mode=0o600)
        (directory / "events.jsonl").touch(mode=0o600)
        self._write_manifest(directory, manifest)
        return self._public(manifest, directory)

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

    def append_event(self, session_id: str, event: dict[str, Any]) -> dict[str, Any]:
        sequence = event.get("sequence")
        if not isinstance(sequence, int) or sequence < 1:
            raise SessionStoreError("event sequence must be a positive integer")
        with self._lock:
            directory, manifest = self._load(session_id)
            self._require_recording(manifest)
            expected = int(manifest["eventCount"]) + 1
            if sequence != expected:
                raise SessionStoreError(f"event sequence must be {expected}")
            line = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            with (directory / manifest["eventFile"]).open("a", encoding="utf-8") as output:
                output.write(line)
                output.flush()
                os.fsync(output.fileno())
            manifest["eventCount"] = sequence
            self._write_manifest(directory, manifest)
            return {"sessionId": session_id, "eventCount": sequence}

    def finalize(self, session_id: str, details: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            directory, manifest = self._load(session_id)
            if manifest.get("status") == "completed":
                return self._public(manifest, directory)
            self._require_recording(manifest)
            try:
                duration_ms = max(0, int(details.get("durationMs") or 0))
            except (TypeError, ValueError) as error:
                raise SessionStoreError("durationMs must be an integer") from error
            audio_path = directory / manifest["audioFile"]
            manifest.update({
                "status": "completed",
                "stoppedAt": str(details.get("stoppedAt") or _now_iso()),
                "durationMs": duration_ms,
                "audioSha256": self._sha256(audio_path),
            })
            self._write_manifest(directory, manifest)
            return self._public(manifest, directory)

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
            "eventPath": str(directory / manifest["eventFile"]),
        }
