#!/usr/bin/env python3
"""Turn final machine QC results into an honest machine quality waiver.

Jony decided on 2026-10-06 that zh-Hans, ko and es publish on machine QC
instead of human text review and full-track listening; he spot-checks after
publication. A waiver is never a human approval: ``humanApproval`` stays
``false``, ``reviewKind`` is ``machine_quality_waiver`` and the page must show
``disclosure``.

Release rule, per locale and per sentence (one English source unit):

* every sentence gets up to four repairs (see the QC modules);
* a sentence whose audio still fails is published subtitle-only;
* a sentence whose text still fails shows the English source instead;
* if more than 5% of sentences end up without a dub, the locale ships
  text-only (``audio_unavailable``);
* if more than 5% of sentences lose their translation, the locale is blocked.

A waiver also requires a current seeded-error calibration: the QC
implementation must have caught planted errors of every kind at the configured
rates with the same code that screened this candidate, including the
back-translation check. Without it the locale is blocked rather than waived.

The waiver binds the exact candidate (and audio package) the QC receipts
screened: every text result must match a candidate group's text hash and every
audio result the package unit's audio hash.
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
# Every seeded error kind must be tried and caught; a kind with no trial was never tested.
TEXT_KINDS = ("wrong_number", "added_reference", "english_leak", "placeholder", "dropped_name", "dropped_half")
AUDIO_KINDS = ("stretched", "silent", "clipped", "truncated")
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


def calibration_problems(calibration: dict | None, locale: str, implementation: str, *,
                         require_audio: bool = False) -> list[str]:
    """Reasons the calibration cannot back a waiver; ``require_audio`` when audio ships."""
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
    if require_audio and calibration.get("audioIncluded") is not True:
        problems.append("calibration did not include the audio checks")
    expected = [f"text.{kind}" for kind in TEXT_KINDS] + ([f"audio.{kind}" for kind in AUDIO_KINDS]
                                                         if require_audio else [])
    kinds = calibration.get("kinds", {})
    missing = [kind for kind in expected if kind not in kinds]
    untested = [kind for kind in expected if kind in kinds and not kinds[kind].get("trials", 0) > 0]
    weak = [kind for kind, row in kinds.items()
            if row.get("trials", 0) > 0 and row.get("rate", 0) < CALIBRATION_MINIMUMS["perKindDetectionRate"]]
    if missing:
        problems.append(f"calibration lacks seeded-error kinds {missing}")
    if untested:
        problems.append(f"calibration has no trials for {untested}")
    if weak:
        problems.append(f"seeded-error detection below minimum for {sorted(weak)}")
    if calibration.get("cleanFalsePositiveRate", 1) > CALIBRATION_MINIMUMS["maxCleanFalsePositiveRate"]:
        problems.append("clean false-positive rate above maximum")
    return problems


def _share(part: int, total: int) -> float:
    return round(part / total, 6)


def bind_receipts(locale: str, candidate: dict, text_qc: dict, audio_qc: dict | None,
                  audio_package: dict | None) -> tuple[list[str], dict[str, int]]:
    """Check that the QC receipts screened exactly this candidate and package.

    Returns the candidate's group ids and the sentence count of each group.
    """
    if candidate.get("targetLocale") != locale or text_qc.get("locale") != locale:
        raise ValueError("Candidate or text QC belongs to another locale")
    groups = candidate["groups"]
    group_ids = [group["translationGroupId"] for group in groups]
    if not group_ids or len(group_ids) != len(set(group_ids)):
        raise ValueError("Candidate needs unique groups")
    sentences = {group["translationGroupId"]: len(group["sourceUnitIds"]) for group in groups}
    if any(count < 1 for count in sentences.values()):
        raise ValueError("Every candidate group needs at least one source sentence")
    if [row["groupId"] for row in text_qc["results"]] != group_ids:
        raise ValueError("Text QC must cover the candidate's groups in the same order")
    for group, row in zip(groups, text_qc["results"]):
        if row.get("targetTextSha256") != hashlib.sha256(group["targetText"].encode("utf-8")).hexdigest():
            raise ValueError(f"Text QC screened different text for {group['translationGroupId']}")
    if audio_qc is None:
        if audio_package is not None:
            raise ValueError("An audio package needs its audio QC")
        return group_ids, sentences
    if audio_package is None:
        raise ValueError("Audio QC needs the audio package it screened")
    if audio_qc.get("locale") != locale or audio_package.get("targetLocale") != locale:
        raise ValueError("Audio QC or package belongs to another locale")
    if audio_package.get("targetLanguageCandidateJsonSha256") != json_sha256(candidate):
        raise ValueError("Audio package was rendered from another candidate")
    units = audio_package["units"]
    if [unit["textGroupId"] for unit in units] != group_ids:
        raise ValueError("Audio package must cover the candidate's groups in the same order")
    if [row["groupId"] for row in audio_qc["results"]] != group_ids:
        raise ValueError("Audio QC must cover the same groups in the same order")
    for group, unit, row in zip(groups, units, audio_qc["results"]):
        if unit["targetTextSha256"] != hashlib.sha256(group["targetText"].encode("utf-8")).hexdigest():
            raise ValueError(f"Audio unit {unit['textGroupId']} was rendered from different text")
        if row.get("audioSha256") != unit["audio"]["sha256"]:
            raise ValueError(f"Audio QC screened different audio for {unit['textGroupId']}")
    return group_ids, sentences


def waive(locale: str, candidate: dict, text_qc: dict, audio_qc: dict | None,
          calibration: dict | None, *, audio_package: dict | None = None,
          implementation: str | None = None) -> dict:
    """Decide the locale outcome from final (no repair pending) QC receipts.

    ``audio_qc`` and ``audio_package`` are ``None`` for a text-only locale. The
    5% limits count sentences (source units), so a failed multi-sentence group
    weighs as much as its sentences.
    """
    implementation = implementation or implementation_sha256()
    group_ids, sentences = bind_receipts(locale, candidate, text_qc, audio_qc, audio_package)
    pending = [row["groupId"] for row in text_qc["results"]
               if row["nextAction"] not in {"keep", "source_text_fallback"}]
    if audio_qc is not None:
        pending += [row["groupId"] for row in audio_qc["results"]
                    if row["nextAction"] not in {"keep", "subtitle_only"}]
    fallback = list(text_qc["sourceTextFallbackGroupIds"])
    subtitle_only = list(audio_qc["subtitleOnlyGroupIds"]) if audio_qc is not None else []
    undubbed = sorted(set(fallback) | set(subtitle_only), key=group_ids.index)
    total = sum(sentences.values())
    fallback_sentences = sum(sentences[group_id] for group_id in fallback)
    undubbed_sentences = sum(sentences[group_id] for group_id in undubbed)
    calibration_issues = calibration_problems(calibration, locale, implementation,
                                              require_audio=audio_qc is not None)
    if pending:
        status, reasons = "repair_in_progress", [f"{len(pending)} groups still have repairs pending"]
    elif calibration_issues:
        status, reasons = "blocked_calibration", calibration_issues
    elif fallback_sentences / total > MAX_SOURCE_FALLBACK_SHARE:
        status, reasons = "blocked_text_quality", [f"{fallback_sentences}/{total} sentences lost their translation"]
    elif audio_qc is None or undubbed_sentences / total > MAX_UNDUBBED_SHARE:
        status = "machine_quality_waived_text_only"
        reasons = (["release plan is text-only"] if audio_qc is None
                   else [f"{undubbed_sentences}/{total} sentences have no dub; audio_unavailable"])
    else:
        status, reasons = "machine_quality_waived", []
    waived = status.startswith("machine_quality_waived")
    return {
        "schemaVersion": SCHEMA, "targetLocale": locale, "status": status, "reasons": reasons,
        "reviewKind": "machine_quality_waiver", "humanApproval": False,
        "releaseEligible": waived, "audioAvailable": status == "machine_quality_waived",
        "disclosure": DISCLOSURE[locale] if waived else None,
        "disclosureEnglish": DISCLOSURE["en"] if waived else None,
        "candidateSha256": json_sha256(candidate),
        "audioPackageSha256": None if audio_package is None else json_sha256(audio_package),
        "textQcSha256": json_sha256(text_qc), "audioQcSha256": None if audio_qc is None else json_sha256(audio_qc),
        "calibrationSha256": None if calibration is None else json_sha256(calibration),
        "implementationSha256": implementation,
        "groupCount": len(group_ids), "sentenceCount": total,
        "subtitleOnlyGroupIds": subtitle_only, "sourceTextFallbackGroupIds": fallback,
        "undubbedSentenceCount": undubbed_sentences, "sourceFallbackSentenceCount": fallback_sentences,
        "undubbedShare": _share(undubbed_sentences, total),
        "sourceFallbackShare": _share(fallback_sentences, total),
        "rules": {"maxRepairAttemptsPerSentence": 4, "maxUndubbedShare": MAX_UNDUBBED_SHARE,
                  "maxSourceFallbackShare": MAX_SOURCE_FALLBACK_SHARE, "shareUnit": "source_sentence",
                  "calibration": CALIBRATION_MINIMUMS},
        "postPublicationSpotCheck": "owner_spot_check_after_release",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--locale", required=True, choices=sorted(set(DISCLOSURE) - {"en"}))
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--text-qc", required=True, type=Path)
    parser.add_argument("--audio-qc", type=Path, help="Omit for a text-only locale")
    parser.add_argument("--audio-package", type=Path, help="The audio package the audio QC screened")
    parser.add_argument("--calibration", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    read = lambda path: None if path is None else json.loads(path.read_text(encoding="utf-8"))
    receipt = waive(args.locale, read(args.candidate), read(args.text_qc), read(args.audio_qc),
                    read(args.calibration), audio_package=read(args.audio_package))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({key: receipt[key] for key in ("status", "reasons", "undubbedShare")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
