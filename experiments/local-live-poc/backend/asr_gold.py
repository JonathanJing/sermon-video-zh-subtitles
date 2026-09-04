from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REQUIRED_REVIEW_FIELDS = ("caseId", "correctedReferenceText", "reviewer", "reviewedAt")


def _portable_session_path(value: Any) -> str | None:
    if not value:
        return None
    path = Path(str(value))
    parts = path.parts
    if "artifacts" in parts:
        return str(Path(*parts[parts.index("artifacts"):]))
    return path.name


def prepare_review_queue(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [{
        "schemaVersion": "asr-human-gold-review-v1",
        "caseId": case["caseId"],
        "speaker": case.get("speaker"),
        "sourceVideo": case.get("sourceVideo"),
        "sourceStartMs": case.get("startMs"),
        "sourceEndMs": case.get("endMs"),
        "sessionDirectory": _portable_session_path(case.get("sessionDirectory")),
        "candidateReferenceText": case.get("referenceText", ""),
        "candidateReferenceProvenance": case.get("referenceProvenance"),
        "asrHypothesis": case.get("asrTextSpeechOnly", ""),
        "correctedReferenceText": "",
        "reviewStatus": "pending_human_review",
        "reviewer": "",
        "reviewedAt": "",
        "notes": "",
    } for case in report.get("cases", [])]


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def validate_human_gold(records: list[dict[str, Any]]) -> dict[str, str]:
    if not records:
        raise ValueError("human Gold file is empty")
    gold: dict[str, str] = {}
    failures: list[str] = []
    for line_number, record in enumerate(records, 1):
        case_id = str(record.get("caseId") or "")
        missing = [field for field in REQUIRED_REVIEW_FIELDS if not str(record.get(field) or "").strip()]
        if record.get("schemaVersion") != "asr-human-gold-review-v1":
            failures.append(f"line {line_number}: unsupported schemaVersion")
        if record.get("reviewStatus") != "approved_human_gold":
            failures.append(f"line {line_number} ({case_id or 'missing caseId'}): not approved_human_gold")
        if missing:
            failures.append(f"line {line_number} ({case_id or 'missing caseId'}): missing {', '.join(missing)}")
        if case_id in gold:
            failures.append(f"line {line_number}: duplicate caseId {case_id}")
        if case_id and not missing:
            gold[case_id] = " ".join(str(record["correctedReferenceText"]).split())
    if failures:
        raise ValueError("human Gold gate failed:\n" + "\n".join(failures))
    return gold
