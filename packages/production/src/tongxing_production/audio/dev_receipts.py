"""Bind Dev profile consumption to actual immutable producer artifacts.

This receipt grants no audio approval and does not claim fresh GPU inference:
the producer may have reused a matching cache.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def check_destination(path, settings):
    """Reject changed profile/selection before the producer can load a model."""
    path = Path(path)
    if path.exists():
        old = read(path)
        if old.get("profile") != settings["profile"] or old.get("batchSize") != settings["batchSize"]:
            raise ValueError("Dev execution receipt belongs to a different profile or batch; use a new output")


def write(settings, artifact_path, receipt_path):
    artifact_path, receipt_path = Path(artifact_path), Path(receipt_path)
    profile = settings["profile"]
    if sha(profile["path"]) != profile["sha256"]:
        raise ValueError("Dev test profile changed during producer execution")
    artifact = read(artifact_path)
    batch = settings["batchSize"]
    witnesses = []
    if profile["stage"] == "tts":
        if not artifact.get("units"):
            raise ValueError("Dev TTS has no completed producer units")
        for index, unit in enumerate(artifact["units"]):
            path = artifact_path.parent / "receipts" / f"unit-{index:04d}.intent.json"
            intent = read(path)
            if (intent.get("batchSize", 1) != batch or intent.get("groupId") != unit["textGroupId"]
                    or intent.get("unitIndex") != index
                    or intent.get("textSha256") != unit["targetTextSha256"]):
                raise ValueError("Dev TTS unit intent differs from resolved batch or group")
            witnesses.append({"path": str(path.resolve()), "sha256": sha(path), "batchSize": batch})
        model = artifact.get("voice", {})
    else:
        if artifact.get("transcriptionBatchSize", 1) != batch or not artifact.get("results"):
            raise ValueError("Dev ASR receipt differs from resolved batch or lacks results")
        model = {key: artifact.get(key) for key in ("model", "modelRevision")}
    value = {
        "schemaVersion": "sermon-dev-audio-profile-consumption-v1",
        "status": "producer_artifact_verified",
        "profile": profile,
        "batchSize": batch,
        "producerArtifact": {"path": str(artifact_path.resolve()), "sha256": sha(artifact_path)},
        "unitIntentWitnesses": witnesses,
        "modelIdentity": model,
        "freshModelInferenceClaimed": False,
        "humanListeningStatus": "pending",
        "humanApproval": False,
        "releaseEligible": False,
    }
    if receipt_path.exists():
        if read(receipt_path) != value:
            raise ValueError("Dev profile consumption receipt changed; preserve it and use a new output")
        return value
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=receipt_path.parent, prefix=".dev-test-")
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, receipt_path)
    finally:
        temporary.unlink(missing_ok=True)
    return value
