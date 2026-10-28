"""Small local-listener helpers shared by L1 source-meaning adjudication.

Moved out of the retired machine-QC transports on 2026-10-28. Only the call
cache, multipart builder, transcription endpoint and the Qwen runtime identity
remain: L1 uses them for its independent source listener, not for audio release.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import uuid

TRANSCRIBE_URL = "https://api.openai.com/v1/audio/transcriptions"


def json_sha256(value) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class UnknownOutcome(RuntimeError):
    """A paid call started and never recorded a completed outcome."""


def _write_once(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink()


class CallCache:
    """One directory per request: ``started.json``, then ``response.json`` and ``outcome.json``.

    ``paid`` calls whose run raises keep an ``unknown_outcome`` marker: the
    request may have been billed, so it is never sent again automatically. A
    local (unpaid) call that raises leaves nothing behind and may be retried."""

    def __init__(self, root: Path, *, paid: bool):
        self.root, self.paid = Path(root), paid

    def get(self, key: str):
        folder = self.root / key
        try:
            outcome = json.loads((folder / "outcome.json").read_text(encoding="utf-8"))
            response = json.loads((folder / "response.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if outcome.get("status") != "completed" or outcome.get("responseJsonSha256") != json_sha256(response):
            raise ValueError(f"Cached call {key} does not match its recorded outcome")
        return response

    def run(self, key: str, request: dict, function):
        done = self.get(key)
        if done is not None:
            return done
        folder = self.root / key
        if (folder / "started.json").exists():
            raise UnknownOutcome(f"call {key} started earlier without a completed outcome; reconcile it first")
        _write_once(folder / "started.json", {"request": request})
        try:
            response = function()
        except BaseException as error:
            if self.paid:
                _write_once(folder / "outcome.json", {"status": "unknown_outcome", "errorType": type(error).__name__})
            else:
                (folder / "started.json").unlink(missing_ok=True)
            raise
        _write_once(folder / "response.json", response)
        _write_once(folder / "outcome.json", {"status": "completed", "responseJsonSha256": json_sha256(response)})
        return response

    def reconcile(self, key: str, request: dict, response):
        """Bind a response the paid-call ledger kept to a call this cache started and never completed.

        Never invokes anything: the started marker must carry ``request``, and a response or
        outcome already recorded must agree with ``response``. Returns the cached response."""
        folder = self.root / key
        started = folder / "started.json"
        if not started.exists():
            raise ValueError(f"call {key} never started; nothing to reconcile")
        if json.loads(started.read_text(encoding="utf-8")) != {"request": request}:
            raise ValueError(f"call {key} started with another request")
        try:
            outcome = json.loads((folder / "outcome.json").read_text(encoding="utf-8"))
        except OSError:
            outcome = None
        if outcome is not None and outcome.get("status") != "completed":
            raise ValueError(f"call {key} recorded an uncompleted outcome; reconcile it explicitly")
        if (folder / "response.json").exists():
            if json.loads((folder / "response.json").read_text(encoding="utf-8")) != response:
                raise ValueError(f"call {key} already recorded a different response")
        else:
            _write_once(folder / "response.json", response)
        if outcome is None:
            _write_once(folder / "outcome.json", {"status": "completed", "responseJsonSha256": json_sha256(response)})
        return self.get(key)

    def uncertain(self) -> list[str]:
        if not self.paid:
            return []
        found = []
        for started in sorted(self.root.glob("*/started.json")):
            try:
                status = json.loads((started.parent / "outcome.json").read_text(encoding="utf-8")).get("status")
            except (OSError, ValueError):
                status = None
            if status != "completed" or not (started.parent / "response.json").exists():
                found.append(started.parent.name)
        return found


def qwen_inference_identity(model_path: Path) -> dict:
    """The runtime identity of the local Qwen3-ASR listener (weights, metadata, versions)."""
    import importlib.metadata
    import torch
    try:
        asr_version = importlib.metadata.version("qwen-asr")
    except importlib.metadata.PackageNotFoundError:
        asr_version = "unavailable"
    model_path = Path(model_path).resolve()
    return {"backend": "qwen-asr-local", "torchVersion": getattr(torch, "__version__", "unavailable"),
            "qwenAsrVersion": asr_version,
            "modelMetadataSha256s": {str(path.relative_to(model_path)): file_sha256(path)
                                     for path in sorted(model_path.rglob("*.json"))}}


def _multipart(fields: list[tuple[str, str]], wav: bytes) -> tuple[bytes, str]:
    boundary = "sermon-audio-qc-" + _sha(wav)
    delimiter = ("--" + boundary).encode("ascii")
    if delimiter in wav:
        raise ValueError("multipart boundary collides with the audio bytes")
    parts = [delimiter + b'\r\nContent-Disposition: form-data; name="' + name.encode("ascii")
             + b'"\r\n\r\n' + value.encode("utf-8") + b"\r\n" for name, value in fields]
    parts.append(delimiter + b'\r\nContent-Disposition: form-data; name="file"; filename="unit.wav"\r\n'
                 b"Content-Type: audio/wav\r\n\r\n" + wav + b"\r\n")
    return b"".join(parts) + delimiter + b"--\r\n", "multipart/form-data; boundary=" + boundary
