"""Per-group human acceptance of text QC findings for a machine text waiver.

A person reads the failed groups of one text QC receipt and accepts each exact
target text as correct. The acceptance binds the candidate, that QC receipt and
every accepted group's English and target text; the waiver records it (v2) and
stays a machine waiver for every other group.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from typing import Any

SCHEMA = "sermon-text-qc-human-acceptance-v1"


def _require(ok: bool, code: str) -> None:
    if not ok:
        raise ValueError(code)


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build(*, candidate: dict, text_qc: dict, decided_by: str, decided_at: str, user_statement: str,
          group_ids: list[str]) -> dict:
    rows = {row["groupId"]: row for row in text_qc["results"]}
    _require(group_ids and all(gid in rows and rows[gid]["status"] != "pass" for gid in group_ids),
             "human_acceptance_group_not_failed")
    return {"schemaVersion": SCHEMA, "targetLocale": candidate["targetLocale"], "candidateJsonSha256": _sha(candidate),
            "textQcJsonSha256": _sha(text_qc), "decidedBy": decided_by, "decidedByRole": "human_operator",
            "humanApproval": True, "decidedAt": decided_at, "userStatement": user_statement,
            "groups": [{"groupId": gid, "englishSha256": rows[gid]["englishSha256"],
                        "targetTextSha256": rows[gid]["targetTextSha256"], "problems": rows[gid]["problems"],
                        "decision": "accepted"} for gid in group_ids]}


def check(acceptance: dict, *, candidate: dict, text_qc: dict) -> set[str]:
    """The group IDs this acceptance clears in exactly this candidate and QC receipt."""
    _require(isinstance(acceptance, dict) and acceptance.get("schemaVersion") == SCHEMA
             and acceptance.get("humanApproval") is True and acceptance.get("decidedByRole") == "human_operator"
             and isinstance(acceptance.get("decidedBy"), str) and acceptance["decidedBy"].strip()
             and isinstance(acceptance.get("userStatement"), str) and acceptance["userStatement"].strip(),
             "human_acceptance_identity")
    try:
        datetime.fromisoformat(acceptance["decidedAt"].replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("human_acceptance_identity") from exc
    _require(acceptance.get("targetLocale") == candidate["targetLocale"]
             and acceptance.get("candidateJsonSha256") == _sha(candidate)
             and acceptance.get("textQcJsonSha256") == _sha(text_qc), "human_acceptance_binding_changed")
    texts = {group["translationGroupId"]: group["targetText"] for group in candidate["groups"]}
    rows = {row["groupId"]: row for row in text_qc["results"]}
    accepted = set()
    for item in acceptance.get("groups") or []:
        gid = item.get("groupId")
        _require(gid in rows and gid in texts and gid not in accepted and item.get("decision") == "accepted"
                 and rows[gid]["status"] != "pass"
                 and item.get("targetTextSha256") == rows[gid]["targetTextSha256"] == _text_sha(texts[gid])
                 and item.get("englishSha256") == rows[gid]["englishSha256"], "human_acceptance_group_changed")
        accepted.add(gid)
    _require(bool(accepted), "human_acceptance_group_changed")
    return accepted
