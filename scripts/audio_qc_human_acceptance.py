"""Per-unit human acceptance of audio QC findings for a machine listening waiver.

A person listens to the units the audio QC failed (ASR disagreement that both
ASRs attribute to the same, correctly spoken audio, or a pronunciation the
person decides to ship as is) and accepts each exact unit audio. The acceptance
binds the audio package, that QC receipt and every accepted unit's audio and
text bytes; the waiver records it (v3) and stays a machine waiver for every
other unit. It never changes the audio, the text or the QC receipt.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from typing import Any

SCHEMA = "sermon-audio-qc-human-acceptance-v1"
ROLES = ("human_operator", "delegated_agent")


def _require(ok: bool, code: str) -> None:
    if not ok:
        raise ValueError(code)


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build(*, package: dict, audio_qc: dict, decided_by: str, decided_at: str, user_statement: str,
          group_ids: list[str], attribution: dict[str, dict] | None = None) -> dict:
    """``attribution`` may give a unit its own ``decidedBy``/``decidedByRole``/``reason``; a unit the
    person delegated to an agent is recorded as ``delegated_agent`` with the delegating statement."""
    rows = {row["groupId"]: row for row in audio_qc["results"]}
    units = {unit["textGroupId"]: unit for unit in package["units"]}
    attribution = attribution or {}
    _require(bool(group_ids) and all(gid in rows and gid in units and rows[gid]["status"] != "pass" for gid in group_ids),
             "human_acceptance_unit_not_failed")
    _require(all(set(a) <= {"decidedBy", "decidedByRole", "reason"} and a.get("decidedByRole", "human_operator") in ROLES
                 for a in attribution.values()), "human_acceptance_attribution")
    return {"schemaVersion": SCHEMA, "targetLocale": package["targetLocale"],
            "targetLanguageAudioPackageJsonSha256": _sha(package),
            "targetLanguageCandidateJsonSha256": package["targetLanguageCandidateJsonSha256"],
            "audioQcJsonSha256": _sha(audio_qc), "decidedBy": decided_by, "decidedByRole": "human_operator",
            "humanApproval": True, "decidedAt": decided_at, "userStatement": user_statement,
            "units": [{"groupId": gid, "audioSha256": rows[gid]["audioSha256"], "textSha256": rows[gid]["textSha256"],
                       "asrPrimaryRecognized": rows[gid].get("asrPrimaryRecognized"),
                       "asrSecondaryRecognized": rows[gid].get("asrSecondaryRecognized"),
                       "issues": rows[gid].get("issues") or [],
                       "decision": "accepted", "decidedBy": attribution.get(gid, {}).get("decidedBy", decided_by),
                       "decidedByRole": attribution.get(gid, {}).get("decidedByRole", "human_operator"),
                       **({"reason": attribution[gid]["reason"]} if attribution.get(gid, {}).get("reason") else {})}
                      for gid in group_ids]}


def check(acceptance: dict, *, package: dict, audio_qc: dict) -> set[str]:
    """The unit IDs this acceptance clears in exactly this package and QC receipt.

    The acceptance names the QC receipt the person reviewed and the exact unit
    audio and text bytes; a changed unit, a re-rendered unit or another package
    is not accepted."""
    _require(isinstance(acceptance, dict) and acceptance.get("schemaVersion") == SCHEMA
             and acceptance.get("humanApproval") is True and acceptance.get("decidedByRole") == "human_operator"
             and isinstance(acceptance.get("decidedBy"), str) and acceptance["decidedBy"].strip()
             and isinstance(acceptance.get("userStatement"), str) and acceptance["userStatement"].strip(),
             "human_acceptance_identity")
    try:
        datetime.fromisoformat(acceptance["decidedAt"].replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("human_acceptance_identity") from exc
    _require(acceptance.get("targetLocale") == package["targetLocale"]
             and acceptance.get("targetLanguageAudioPackageJsonSha256") == _sha(package)
             and acceptance.get("targetLanguageCandidateJsonSha256") == package["targetLanguageCandidateJsonSha256"]
             and acceptance.get("audioQcJsonSha256") == _sha(audio_qc), "human_acceptance_binding_changed")
    rows = {row["groupId"]: row for row in audio_qc["results"]}
    units = {unit["textGroupId"]: unit for unit in package["units"]}
    accepted: set[str] = set()
    for item in acceptance.get("units") or []:
        gid = item.get("groupId")
        _require(gid in rows and gid in units and gid not in accepted and item.get("decision") == "accepted"
                 and item.get("decidedByRole", "human_operator") in ROLES
                 and isinstance(item.get("decidedBy", "x"), str) and item.get("decidedBy", "x").strip()
                 and item.get("audioSha256") == rows[gid]["audioSha256"] == units[gid]["audio"]["sha256"]
                 and item.get("textSha256") == rows[gid]["textSha256"] == units[gid]["targetTextSha256"],
                 "human_acceptance_unit_changed")
        accepted.add(gid)
    _require(bool(accepted), "human_acceptance_unit_changed")
    return accepted
