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
ROLES = ("human_operator", "delegated_agent")


def _require(ok: bool, code: str) -> None:
    if not ok:
        raise ValueError(code)


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build(*, candidate: dict, text_qc: dict, decided_by: str, decided_at: str, user_statement: str,
          group_ids: list[str], attribution: dict[str, dict] | None = None) -> dict:
    """``attribution`` may give a group its own ``decidedBy``/``decidedByRole``/``reason``; a group the
    person delegated to an agent is recorded as ``delegated_agent`` with the delegating statement."""
    rows = {row["groupId"]: row for row in text_qc["results"]}
    attribution = attribution or {}
    _require(group_ids and all(gid in rows and rows[gid]["status"] != "pass" for gid in group_ids),
             "human_acceptance_group_not_failed")
    _require(all(set(a) <= {"decidedBy", "decidedByRole", "reason"} and a.get("decidedByRole", "human_operator") in ROLES
                 for a in attribution.values()), "human_acceptance_attribution")
    return {"schemaVersion": SCHEMA, "targetLocale": candidate["targetLocale"], "candidateJsonSha256": _sha(candidate),
            "textQcJsonSha256": _sha(text_qc), "decidedBy": decided_by, "decidedByRole": "human_operator",
            "humanApproval": True, "decidedAt": decided_at, "userStatement": user_statement,
            "groups": [{"groupId": gid, "englishSha256": rows[gid]["englishSha256"],
                        "targetTextSha256": rows[gid]["targetTextSha256"], "problems": rows[gid]["problems"],
                        "decision": "accepted", "decidedBy": attribution.get(gid, {}).get("decidedBy", decided_by),
                        "decidedByRole": attribution.get(gid, {}).get("decidedByRole", "human_operator"),
                        **({"reason": attribution[gid]["reason"]} if attribution.get(gid, {}).get("reason") else {})}
                       for gid in group_ids]}


def check(acceptance: dict, *, candidate: dict, text_qc: dict) -> set[str]:
    """The group IDs this acceptance clears in exactly this candidate.

    The acceptance names the QC receipt the person reviewed. A later screen of
    the same candidate (another runtime) may reuse it for any group whose exact
    English and target text the person accepted; new failures stay failures."""
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
             and isinstance(acceptance.get("textQcJsonSha256"), str), "human_acceptance_binding_changed")
    texts = {group["translationGroupId"]: group["targetText"] for group in candidate["groups"]}
    rows = {row["groupId"]: row for row in text_qc["results"]}
    accepted = set()
    for item in acceptance.get("groups") or []:
        gid = item.get("groupId")
        _require(gid in rows and gid in texts and gid not in accepted and item.get("decision") == "accepted"
                 and item.get("decidedByRole", "human_operator") in ROLES
                 and isinstance(item.get("decidedBy", "x"), str) and item.get("decidedBy", "x").strip()
                 and item.get("targetTextSha256") == rows[gid]["targetTextSha256"] == _text_sha(texts[gid])
                 and item.get("englishSha256") == rows[gid]["englishSha256"], "human_acceptance_group_changed")
        accepted.add(gid)
    _require(bool(accepted), "human_acceptance_group_changed")
    return accepted
