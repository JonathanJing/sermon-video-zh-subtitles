"""Human rulings that answer a Layer 2 ``request_human_review`` stop.

When a group stops because the independent reviewer stays uncertain after its
repairs, a person decides what the frozen English means. The ruling binds the
English Source Package and anchor, each unit's frozen text and the person's own
statement. ``reopen-repair`` then gives that group one more repair carrying the
ruling; the reviewer still judges the result, and nothing here approves text.
"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any

from scripts import sermon_source_text_review as source_review
from scripts import target_language_policy as policies

SCHEMA = "sermon-layer2-human-ruling-v1"
DECISION = "human_ruling"


def _require(ok: bool, code: str) -> None:
    if not ok:
        raise ValueError(code)


def build(*, source: dict[str, Any], anchor: dict[str, Any], decided_by: str, decided_at: str,
          user_statement: str, rulings: dict[str, str]) -> dict[str, Any]:
    units = {unit["sourceUnitId"]: unit for unit in anchor["sourceUnits"]}
    _require(bool(rulings) and all(uid in units for uid in rulings), "human_ruling_unit_unknown")
    return {"schemaVersion": SCHEMA,
            "bindings": {"source.json": policies.canonical_sha256(source), "anchor.json": policies.canonical_sha256(anchor)},
            "decidedBy": decided_by, "decidedByRole": "human_operator", "humanApproval": True,
            "decidedAt": decided_at, "userStatement": user_statement,
            "units": [{"sourceUnitId": uid, "decision": DECISION, "meaningNote": note.strip(),
                       "frozenTextSha256": source_review.text_sha256(units[uid]["english"])}
                      for uid, note in rulings.items()]}


def load(path: Path, *, source: dict[str, Any], anchor: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Rulings bound to exactly these Layer 1 inputs and frozen units, keyed by unit."""
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    _require(isinstance(value, dict) and value.get("schemaVersion") == SCHEMA, "human_ruling_schema")
    _require(value.get("bindings") == {"source.json": policies.canonical_sha256(source),
                                       "anchor.json": policies.canonical_sha256(anchor)}, "human_ruling_binding_changed")
    _require(value.get("decidedByRole") == "human_operator" and value.get("humanApproval") is True
             and isinstance(value.get("decidedBy"), str) and value["decidedBy"].strip()
             and isinstance(value.get("userStatement"), str) and value["userStatement"].strip(), "human_ruling_identity")
    try:
        datetime.fromisoformat(value["decidedAt"].replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("human_ruling_identity") from exc
    units = {unit["sourceUnitId"]: unit for unit in anchor.get("sourceUnits", [])}
    out: dict[str, dict[str, Any]] = {}
    for row in value.get("units") or []:
        uid = row.get("sourceUnitId")
        _require(uid in units and uid not in out and row.get("decision") == DECISION
                 and isinstance(row.get("meaningNote"), str) and row["meaningNote"].strip()
                 and row.get("frozenTextSha256") == source_review.text_sha256(units[uid]["english"]),
                 "human_ruling_unit_changed")
        out[uid] = {**row, "humanRuling": True, "decidedBy": value["decidedBy"]}
    _require(bool(out), "human_ruling_unit_changed")
    return out
