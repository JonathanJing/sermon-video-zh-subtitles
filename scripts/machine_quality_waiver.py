#!/usr/bin/env python3
"""Turn final machine QC results into an honest machine quality waiver.

Jony decided on 2026-10-06 that zh-Hans, ko and es publish on machine QC
instead of human text review and full-track listening; he spot-checks after
publication. A waiver is never a human approval: ``humanApproval`` stays
``false``, ``reviewKind`` is ``machine_quality_waiver`` and the page must show
``disclosure``.

Release rule, per locale and per sentence:

* every sentence gets up to four repairs (see the QC modules);
* a sentence whose audio still fails is published subtitle-only;
* a sentence whose text still fails shows the English source instead;
* if more than 5% of sentences end up without a dub, the locale ships
  text-only (``audio_unavailable``);
* if more than 5% of sentences lose their translation, the locale is blocked.

A waiver also requires a current seeded-error calibration: the QC
implementation must have caught planted errors at the configured rates with
the same code that screened this candidate, including the back-translation
check. Without it the locale is blocked rather than waived.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "sermon-machine-quality-waiver-v1"
CALIBRATION_SCHEMA = "sermon-auto-qc-calibration-v1"
IMPLEMENTATION_FILES = (
    "scripts/language_review_plugins/common.py",
    "scripts/language_review_plugins/auto_qc_text_common.py",
    "scripts/target_text_auto_qc.py",
    "scripts/target_audio_auto_qc.py",
    "scripts/target_audio_predicted_schedule.py",
    "scripts/auto_qc_seeded_errors.py",
)
MAX_UNDUBBED_SHARE = 0.05
MAX_SOURCE_FALLBACK_SHARE = 0.05
CALIBRATION_MINIMUMS = {"overallDetectionRate": 0.95, "perKindDetectionRate": 0.9,
                        "maxCleanFalsePositiveRate": 0.1}
DISCLOSURE = {
    "zh-Hans": "本语言内容经机器质检后自动发布，未经人工审核。",
    "ko": "이 언어 콘텐츠는 기계 품질 검사 후 자동으로 게시되었으며 사람의 검토를 거치지 않았습니다.",
    "es": "Este contenido se publicó automáticamente tras un control de calidad por máquina, sin revisión humana.",
    "en": "Published automatically after machine quality checks, without human review.",
}


def implementation_sha256(root: Path = ROOT) -> str:
    digest = hashlib.sha256()
    for name in IMPLEMENTATION_FILES:
        digest.update(name.encode("utf-8") + b"\0" + (root / name).read_bytes() + b"\0")
    return digest.hexdigest()


def json_sha256(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def calibration_problems(calibration: dict | None, locale: str, implementation: str) -> list[str]:
    if calibration is None:
        return ["seeded-error calibration missing"]
    problems = []
    if calibration.get("schemaVersion") != CALIBRATION_SCHEMA:
        problems.append("unsupported calibration schema")
    if calibration.get("locale") != locale:
        problems.append("calibration belongs to another locale")
    if calibration.get("implementationSha256") != implementation:
        problems.append("QC implementation changed since calibration")
    if calibration.get("semanticChecksIncluded") is not True:
        problems.append("calibration did not include the back-translation check")
    if calibration.get("overallDetectionRate", 0) < CALIBRATION_MINIMUMS["overallDetectionRate"]:
        problems.append("overall seeded-error detection below minimum")
    weak = [kind for kind, row in calibration.get("kinds", {}).items()
            if row.get("trials", 0) and row.get("rate", 0) < CALIBRATION_MINIMUMS["perKindDetectionRate"]]
    if weak:
        problems.append(f"seeded-error detection below minimum for {sorted(weak)}")
    if calibration.get("cleanFalsePositiveRate", 1) > CALIBRATION_MINIMUMS["maxCleanFalsePositiveRate"]:
        problems.append("clean false-positive rate above maximum")
    return problems


def waive(locale: str, candidate_sha256: str, text_qc: dict, audio_qc: dict | None,
          calibration: dict | None, *, implementation: str | None = None) -> dict:
    """Decide the locale outcome from final (no repair pending) QC receipts.

    ``audio_qc`` is ``None`` for a text-only locale.
    """
    implementation = implementation or implementation_sha256()
    if text_qc.get("locale") != locale or (audio_qc is not None and audio_qc.get("locale") != locale):
        raise ValueError("QC receipts belong to another locale")
    group_ids = [row["groupId"] for row in text_qc["results"]]
    if not group_ids or len(group_ids) != len(set(group_ids)):
        raise ValueError("Text QC needs unique groups")
    pending = [row["groupId"] for row in text_qc["results"]
               if row["nextAction"] not in {"keep", "source_text_fallback"}]
    if audio_qc is not None:
        if [row["groupId"] for row in audio_qc["results"]] != group_ids:
            raise ValueError("Audio QC must cover the same groups in the same order")
        pending += [row["groupId"] for row in audio_qc["results"]
                    if row["nextAction"] not in {"keep", "subtitle_only"}]
    fallback = list(text_qc["sourceTextFallbackGroupIds"])
    subtitle_only = list(audio_qc["subtitleOnlyGroupIds"]) if audio_qc is not None else []
    undubbed = sorted(set(fallback) | set(subtitle_only), key=group_ids.index)
    total = len(group_ids)
    calibration_issues = calibration_problems(calibration, locale, implementation)
    if pending:
        status, reasons = "repair_in_progress", [f"{len(pending)} groups still have repairs pending"]
    elif calibration_issues:
        status, reasons = "blocked_calibration", calibration_issues
    elif len(fallback) / total > MAX_SOURCE_FALLBACK_SHARE:
        status, reasons = "blocked_text_quality", [f"{len(fallback)}/{total} groups lost their translation"]
    elif audio_qc is None or len(undubbed) / total > MAX_UNDUBBED_SHARE:
        status = "machine_quality_waived_text_only"
        reasons = (["release plan is text-only"] if audio_qc is None
                   else [f"{len(undubbed)}/{total} groups have no dub; audio_unavailable"])
    else:
        status, reasons = "machine_quality_waived", []
    waived = status.startswith("machine_quality_waived")
    return {
        "schemaVersion": SCHEMA, "targetLocale": locale, "status": status, "reasons": reasons,
        "reviewKind": "machine_quality_waiver", "humanApproval": False,
        "releaseEligible": waived, "audioAvailable": status == "machine_quality_waived",
        "disclosure": DISCLOSURE[locale] if waived else None,
        "disclosureEnglish": DISCLOSURE["en"] if waived else None,
        "candidateSha256": candidate_sha256,
        "textQcSha256": json_sha256(text_qc), "audioQcSha256": None if audio_qc is None else json_sha256(audio_qc),
        "calibrationSha256": None if calibration is None else json_sha256(calibration),
        "implementationSha256": implementation,
        "groupCount": total, "subtitleOnlyGroupIds": subtitle_only, "sourceTextFallbackGroupIds": fallback,
        "undubbedShare": round(len(undubbed) / total, 6),
        "rules": {"maxRepairAttemptsPerSentence": 4, "maxUndubbedShare": MAX_UNDUBBED_SHARE,
                  "maxSourceFallbackShare": MAX_SOURCE_FALLBACK_SHARE, "calibration": CALIBRATION_MINIMUMS},
        "postPublicationSpotCheck": "owner_spot_check_after_release",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--locale", required=True, choices=sorted(set(DISCLOSURE) - {"en"}))
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--text-qc", required=True, type=Path)
    parser.add_argument("--audio-qc", type=Path, help="Omit for a text-only locale")
    parser.add_argument("--calibration", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    read = lambda path: None if path is None else json.loads(path.read_text(encoding="utf-8"))
    receipt = waive(args.locale, hashlib.sha256(args.candidate.read_bytes()).hexdigest(),
                    read(args.text_qc), read(args.audio_qc), read(args.calibration))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({key: receipt[key] for key in ("status", "reasons", "undubbedShare")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
