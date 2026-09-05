"""Source-bound voice authorization and machine-reviewed research candidates."""
from __future__ import annotations

import json
from pathlib import Path

from poc import ROOT, sha256

AUTHORIZATION = ROOT / "artifacts/sermon-dubbing/authorizations/2026-09-05-user-confirmation.json"


def authorized_source(record: dict, source_id: str, source_hash: str, purpose: str) -> bool:
    return (
        record.get("schemaVersion") == "sermon-voice-authorization-v1"
        and record.get("status") == "confirmed_by_user"
        and bool(record.get("statement"))
        and purpose in record.get("purposes", [])
        and any(item.get("sourceId") == source_id and item.get("sha256") == source_hash for item in record.get("sources", []))
    )


def verify_reference(plan: dict) -> dict:
    """Grant only reference synthesis, never a human training/quality approval."""
    benchmark = json.loads((ROOT / "data/benchmarks/live-sermon-translation-v1/benchmark-manifest.json").read_text())
    protected_ids = {item["videoId"] for item in benchmark["items"]}
    protected_dates = {item["uploadDate"] for item in benchmark["items"]}
    if plan["sourceId"] in protected_ids or plan.get("serviceDate", "").replace("-", "") in protected_dates:
        raise ValueError("Protected evaluation source or possible same-sermon date")
    profile_path = Path(plan["voice"]["profile"])
    if sha256(profile_path) != plan["voice"]["profileSha256"]:
        raise ValueError("Voice profile changed")
    profile = json.loads(profile_path.read_text())
    authorization_path = Path(profile["authorization"])
    if sha256(authorization_path) != profile["authorizationSha256"]:
        raise ValueError("Authorization record changed")
    record = json.loads(authorization_path.read_text())
    if not authorized_source(record, profile["sourceId"], profile["sourceSha256"], "chinese_dubbing"):
        raise ValueError("This source is not authorized for Chinese dubbing")
    if profile.get("role") == "protected_evaluation" or profile.get("protectedEvaluationOverlap") is not False:
        raise ValueError("Protected or unresolved evaluation overlap")
    if profile["sourceId"] != plan["sourceId"] or profile["sourceSha256"] != plan["sourceAudioSha256"]:
        raise ValueError("Reference belongs to a different source")
    if sha256(Path(profile["referenceAudio"])) != profile["referenceSha256"]:
        raise ValueError("Reference audio changed")
    if not profile.get("referenceText", "").strip() or profile.get("referenceLanguage") != "English":
        raise ValueError("An English reference transcript is required")
    return profile
