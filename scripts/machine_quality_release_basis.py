#!/usr/bin/env python3
"""Stage-bound machine quality waivers that stand in for human review.

Jony decided on 2026-10-06 that zh-Hans, ko and es publish on machine QC
instead of human translation review and full-track listening. Two immutable
receipts carry that decision through the existing gates:

* the text waiver binds one exact Layer 2 candidate (L2 -> L3, and L4 for both
  the full and the spoken script);
* the audio waiver binds one exact machine-screened Layer 3 audio package and
  the text waiver of its spoken script (L3 -> L4).

Neither receipt is a human approval. The candidate keeps
``humanReview.translation = pending``, the audio package keeps its builder
status with ``humanApproval = false``, and the page must show the disclosure. Version 1 waives only a locale whose every sentence passed;
subtitle-only sentences and text-only locales are not wired yet.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

from jsonschema import Draft202012Validator, FormatChecker

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import machine_quality_waiver as waiver

ROOT = Path(__file__).resolve().parents[1]
TEXT_WAIVER_SCHEMA = "sermon-target-language-machine-text-waiver-v1"
AUDIO_WAIVER_SCHEMA = "sermon-target-language-machine-audio-waiver-v2"
LEGACY_AUDIO_WAIVER_SCHEMA = "sermon-target-language-machine-audio-waiver-v1"
CONDENSATION_BINDING_SCHEMA = "sermon-spoken-condensation-binding-v1"
REVIEW_KIND = "machine_quality_waiver"
LOCALES = ("zh-Hans", "ko", "es")
MACHINE_PENDING_CANDIDATE = "machine_review_pass_human_review_pending"
RULES = {"maxRepairAttemptsPerSentence": 4, "calibration": waiver.CALIBRATION_MINIMUMS}
json_sha256 = waiver.json_sha256


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _schema(value: dict, version: str) -> None:
    definition = json.loads((ROOT / "schemas" / f"{version}.schema.json").read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(definition, format_checker=FormatChecker()).iter_errors(value))
    _require(not errors, f"Invalid {version}: {errors[0].message}" if errors else "")


def _asr_threshold() -> float:
    # Imported lazily: the audio QC module pulls in the Layer 3 renderer, which
    # itself imports the speech-job module that imports this one.
    from scripts.target_audio_auto_qc import THRESHOLDS
    return THRESHOLDS["asrMinSimilarity"]


def is_text_waiver(receipt: dict) -> bool:
    return isinstance(receipt, dict) and receipt.get("schemaVersion") == TEXT_WAIVER_SCHEMA


def is_audio_waiver(receipt: dict) -> bool:
    return isinstance(receipt, dict) and receipt.get("schemaVersion") in (AUDIO_WAIVER_SCHEMA, LEGACY_AUDIO_WAIVER_SCHEMA)


def disclosure(locale: str) -> dict:
    return {"locale": locale, "text": waiver.DISCLOSURE[locale], "english": waiver.DISCLOSURE["en"]}


def _text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def calibration_summary(calibration: dict, locale: str, implementation: str, *,
                        require_audio: bool = False, require_spoken: bool = False) -> dict:
    problems = waiver.calibration_problems(calibration, locale, implementation,
                                           require_audio=require_audio, require_spoken=require_spoken)
    _require(not problems, "Calibration does not allow a waiver: " + "; ".join(problems))
    expected = ([f"text.{kind}" for kind in waiver.TEXT_KINDS]
                + ([f"audio.{kind}" for kind in waiver.AUDIO_KINDS] if require_audio else [])
                + ([f"spoken.{kind}" for kind in waiver.SPOKEN_KINDS] if require_spoken else []))
    rates = [calibration["kinds"][kind]["rate"] for kind in expected]
    return {"jsonSha256": json_sha256(calibration), "implementationSha256": implementation,
            "semanticChecksIncluded": True,
            "overallDetectionRate": calibration["overallDetectionRate"],
            "minimumKindDetectionRate": min(rates),
            "cleanFalsePositiveRate": calibration["cleanFalsePositiveRate"],
            "runtimeIdentitySha256": waiver.runtime_identity_sha256(calibration)}


def _validate_summary(receipt: dict) -> None:
    summary = receipt["calibration"]
    minimums = waiver.CALIBRATION_MINIMUMS
    _require(receipt["rules"] == RULES, "Waiver rules differ from the decided release rules")
    _require(summary["implementationSha256"] == receipt["implementationSha256"]
             and summary["overallDetectionRate"] >= minimums["overallDetectionRate"]
             and summary["minimumKindDetectionRate"] >= minimums["perKindDetectionRate"]
             and summary["cleanFalsePositiveRate"] <= minimums["maxCleanFalsePositiveRate"],
             "Waiver calibration does not meet the release minimums")
    _require(receipt["disclosure"] == disclosure(receipt["targetLocale"]),
             "Waiver disclosure differs from the required text")


def machine_pending_candidate(candidate: dict) -> bool:
    """A model-reviewed candidate that no human has approved or rejected."""
    groups = candidate.get("groups") or []
    group_ids = [group.get("translationGroupId") for group in groups]
    human = candidate.get("humanReview") or {}
    return (bool(group_ids) and len(group_ids) == len(set(group_ids))
            and candidate.get("status") == MACHINE_PENDING_CANDIDATE
            and candidate.get("releaseEligible") is False
            and (candidate.get("modelReview") or {}).get("status") == "pass"
            and (candidate.get("modelReview") or {}).get("reviewedGroupIds") == group_ids
            and human.get("translation") == "pending"
            and all(group["semanticReview"]["status"] == "pass"
                    and group["languageReview"]["status"] == "pass"
                    and all(check["status"] == "pass" for check in group["languageReview"]["checks"])
                    for group in groups))


def condensation_problems(candidate: dict, condensed: list[str], binding: dict | None) -> list[str]:
    """Groups judged as condensed spoken text must be exactly those a passing
    ``spoken_condensation`` binding bound in this candidate."""
    if not condensed:
        return [] if binding is None else ["a condensation binding was given but no group was judged condensed"]
    if binding is None:
        return ["condensed groups need their condensation binding"]
    texts = {group["translationGroupId"]: _text_sha(group["targetText"]) for group in candidate["groups"]}
    rows = binding.get("groups") or []
    problems = []
    if (binding.get("schemaVersion") != CONDENSATION_BINDING_SCHEMA or binding.get("status") != "pass"
            or binding.get("issues") or binding.get("humanApproval") is not False):
        problems.append("condensation binding did not pass")
    if (binding.get("targetLocale") != candidate.get("targetLocale")
            or binding.get("spokenCandidateJsonSha256") != json_sha256(candidate)):
        problems.append("condensation binding belongs to another spoken candidate")
    if [row.get("translationGroupId") for row in rows] != condensed:
        problems.append("condensed groups differ from the binding's groups")
    elif any(row.get("finalSpokenTextSha256") != texts[row["translationGroupId"]] for row in rows):
        problems.append("condensation binding bound other spoken text")
    return problems


def build_text_waiver(source: dict, anchor: dict, candidate: dict, text_qc: dict,
                      calibration: dict, *, condensation_binding: dict | None = None,
                      implementation: str | None = None, created_at: str | None = None) -> dict:
    """Issue a text waiver from final text QC; refuse anything not fully passing.

    A spoken candidate with groups condensed for dubbing needs the passing
    ``spoken_condensation`` binding of exactly those groups. Such a waiver
    admits the script for dubbing only: Layer 4 refuses it as the full text and
    releases it only with that binding, so captions keep the complete
    translation on the dub's timing."""
    implementation = implementation or waiver.implementation_sha256()
    locale = candidate.get("targetLocale")
    _require(locale in LOCALES, "Machine waivers cover zh-Hans, ko and es only")
    _require(machine_pending_candidate(candidate),
             "Text waiver requires a model-reviewed candidate with human review still pending")
    _require(candidate.get("englishSourcePackageJsonSha256") == json_sha256(source)
             and candidate.get("anchorManifestSha256") == json_sha256(anchor),
             "Candidate belongs to another source or anchor")
    groups = candidate["groups"]
    group_ids = [group["translationGroupId"] for group in groups]
    _require(text_qc.get("schemaVersion") == "sermon-target-text-auto-qc-v1"
             and text_qc.get("locale") == locale and text_qc.get("humanApproval") is False,
             "Text QC belongs to another locale or schema")
    results = text_qc.get("results") or []
    _require([row.get("groupId") for row in results] == group_ids,
             "Text QC must cover every candidate group in order")
    _require(text_qc.get("status") == "pass"
             and all(row.get("status") == "pass" and row.get("nextAction") == "keep"
                     and row.get("backTranslation") is not None for row in results),
             "Every group must pass text QC, including back-translation")
    english_units = {unit["sourceUnitId"]: unit["english"] for unit in anchor["sourceUnits"]}
    for row, group in zip(results, groups):
        source_ids = group.get("sourceUnitIds")
        _require(isinstance(source_ids, list) and bool(source_ids)
                 and all(unit_id in english_units for unit_id in source_ids),
                 f"Candidate group does not bind frozen source units: {group['translationGroupId']}")
        english = " ".join(english_units[unit_id] for unit_id in source_ids)
        _require(row.get("englishSha256") == _text_sha(english)
                 and row.get("sourceUnitIdsSha256") == json_sha256(source_ids),
                 f"Text QC screened different frozen English/source units: {group['translationGroupId']}")
        _require(row.get("targetTextSha256") == _text_sha(group["targetText"]),
                 f"Text QC screened different text: {group['translationGroupId']}")
    condensed = [row["groupId"] for row in results if row.get("mode") == "spoken_condensed"]
    _require(list(text_qc.get("condensedGroupIds") or []) == condensed,
             "Text QC condensed-group list differs from its per-group results")
    condensation = condensation_problems(candidate, condensed, condensation_binding)
    _require(not condensation, "Condensed spoken groups are not bound: " + "; ".join(condensation))
    summary = calibration_summary(calibration, locale, implementation, require_spoken=bool(condensed))
    runtime = waiver.runtime_identity_problems(calibration, text_qc=text_qc)
    _require(not runtime, "Text QC runtime differs from calibration: " + "; ".join(runtime))
    receipt = {
        "schemaVersion": TEXT_WAIVER_SCHEMA, "reviewKind": REVIEW_KIND, "humanApproval": False,
        "decision": "machine_quality_waived", "targetLocale": locale,
        "englishSourcePackageJsonSha256": json_sha256(source),
        "anchorManifestJsonSha256": json_sha256(anchor),
        "translationPolicySha256": candidate["translationPolicySha256"],
        "candidateJsonSha256": json_sha256(candidate),
        "reviewedGroupIds": group_ids,
        "groupResults": [{"translationGroupId": group["translationGroupId"], "status": "pass",
                          "targetTextSha256": row["targetTextSha256"],
                          "failedAttempts": int(row.get("failedAttempts", 0))}
                         for row, group in zip(results, groups)],
        "textQcJsonSha256": json_sha256(text_qc),
        "condensedGroupIds": condensed,
        "condensationBindingJsonSha256": None if condensation_binding is None else json_sha256(condensation_binding),
        "calibration": summary,
        "implementationSha256": implementation, "rules": RULES,
        "disclosure": disclosure(locale), "createdAt": created_at or _now(),
        "postPublicationSpotCheck": "owner_spot_check_after_release",
    }
    _schema(receipt, TEXT_WAIVER_SCHEMA)
    return receipt


def validate_text_waiver(receipt: dict, *, candidate: dict, source_sha: str | None = None,
                         anchor_sha: str | None = None) -> None:
    """Gate-time check that the waiver binds exactly this machine-pending candidate."""
    _schema(receipt, TEXT_WAIVER_SCHEMA)
    _require(machine_pending_candidate(candidate),
             "Text waiver applies only to a candidate whose human review is still pending")
    group_ids = [group["translationGroupId"] for group in candidate["groups"]]
    _require(receipt["targetLocale"] == candidate["targetLocale"]
             and receipt["englishSourcePackageJsonSha256"] == candidate["englishSourcePackageJsonSha256"]
             and receipt["anchorManifestJsonSha256"] == candidate["anchorManifestSha256"]
             and receipt["translationPolicySha256"] == candidate["translationPolicySha256"]
             and receipt["candidateJsonSha256"] == json_sha256(candidate)
             and (source_sha is None or receipt["englishSourcePackageJsonSha256"] == source_sha)
             and (anchor_sha is None or receipt["anchorManifestJsonSha256"] == anchor_sha),
             "Text waiver does not bind this candidate and source")
    _require(receipt["reviewedGroupIds"] == group_ids
             and [row["translationGroupId"] for row in receipt["groupResults"]] == group_ids
             and all(row["targetTextSha256"] == _text_sha(group["targetText"])
                     for row, group in zip(receipt["groupResults"], candidate["groups"])),
             "Text waiver has missing or mismatched group results")
    condensed = receipt["condensedGroupIds"]
    _require(condensed == [group_id for group_id in group_ids if group_id in set(condensed)]
             and (not condensed) == (receipt["condensationBindingJsonSha256"] is None),
             "Text waiver condensed groups and binding disagree")
    _validate_summary(receipt)


def screening_queue(package: dict, screening: dict) -> list[str]:
    """Bind the full ASR screening to the package; return the units it flagged."""
    group_ids = [row["textGroupId"] for row in package["units"]]
    status = package["machineScreening"]["status"]
    _require(status in {"pass", "requires_review"}
             and screening.get("schemaVersion") == "sermon-target-language-audio-screening-v1"
             and screening["status"] == status
             and screening["model"] == package["machineScreening"]["model"]
             and screening["targetLocale"] == package["targetLocale"]
             and screening["trackSha256"] == package["track"]["sha256"]
             and screening["targetLanguageSpeechJobJsonSha256"] == package["targetLanguageSpeechJobJsonSha256"]
             and screening["coverage"] == 1
             and screening["reviewedGroupIds"] == group_ids
             and screening["unitAudioSha256s"] == [row["audio"]["sha256"] for row in package["units"]]
             and len(screening["results"]) == len(group_ids),
             "Audio ASR screening is not bound to this package")
    queue = []
    for result, unit in zip(screening["results"], package["units"]):
        _require(result["textGroupId"] == unit["textGroupId"]
                 and result["targetTextSha256"] == unit["targetTextSha256"]
                 and result["audioSha256"] == unit["audio"]["sha256"],
                 "ASR result differs from audio unit")
        if result["status"] == "requires_review":
            queue.append(result["textGroupId"])
    _require((status == "pass") == (not queue), "ASR screening status differs from its results")
    return queue


def _machine_screened(package: dict) -> bool:
    """Built and fully ASR-screened, with no human decision recorded.

    The builder writes ``machine_screened`` when ASR passed every unit and
    ``candidate`` when ASR flagged some; the waiver's secondary ASR covers those.
    """
    human = package.get("humanReview") or {}
    screened = (package.get("status"), (package.get("machineScreening") or {}).get("status"))
    return (screened in {("machine_screened", "pass"), ("candidate", "requires_review")}
            and human.get("humanApproval") is False and human.get("status") == "pending"
            and human.get("fullPlayback") == "pending"
            and not package.get("issues") and bool(package.get("track")) and bool(package.get("captions"))
            and package.get("machineScreening", {}).get("coverage") == 1)


def track_check_problems(package: dict, track_check: dict | None, implementation: str) -> list[str]:
    """The assembled track must be proven to be this package's screened units, by current QC code."""
    if track_check is None:
        return ["assembled-track check missing"]
    expected = {"schemaVersion": "sermon-target-audio-track-check-v1", "status": "pass", "issues": [],
                "humanApproval": False, "targetLocale": package["targetLocale"],
                "targetLanguageAudioPackageJsonSha256": json_sha256(package),
                "trackSha256": package["track"]["sha256"],
                "scheduleJsonSha256": (package.get("schedule") or {}).get("jsonSha256"),
                "unitAudioSha256s": [row["audio"]["sha256"] for row in package["units"]],
                "implementationSha256": implementation}
    return [f"track check {key} differs" for key, value in expected.items() if track_check.get(key) != value]


def build_audio_waiver(package: dict, screening: dict, audio_qc: dict, text_waiver: dict,
                       calibration: dict, *, track_check: dict | None = None,
                       secondary_asr_model: str | None = None,
                       implementation: str | None = None, created_at: str | None = None) -> dict:
    """Issue an audio waiver when every unit passed audio QC with no subtitle-only units
    and the assembled track is proven to be those units in schedule order."""
    implementation = implementation or waiver.implementation_sha256()
    locale = package.get("targetLocale")
    _require(locale in LOCALES, "Machine waivers cover zh-Hans, ko and es only")
    _require(_machine_screened(package),
             "Audio waiver requires a complete machine-screened package with no human decision")
    _schema(text_waiver, TEXT_WAIVER_SCHEMA)
    _require(text_waiver["targetLocale"] == locale
             and text_waiver["candidateJsonSha256"] == package["targetLanguageCandidateJsonSha256"]
             and text_waiver["englishSourcePackageJsonSha256"] == package["englishSourcePackageJsonSha256"]
             and text_waiver["reviewedGroupIds"] == [row["textGroupId"] for row in package["units"]],
             "Audio waiver requires the text waiver of the package's spoken script")
    flagged = set(screening_queue(package, screening))
    by_group = {row["textGroupId"]: row for row in screening["results"]}
    results = audio_qc.get("results") or []
    _require(audio_qc.get("schemaVersion") == "sermon-target-audio-auto-qc-v1"
             and audio_qc.get("locale") == locale and audio_qc.get("humanApproval") is False
             and [row.get("groupId") for row in results] == [row["textGroupId"] for row in package["units"]],
             "Audio QC must cover every package unit in order")
    _require(audio_qc.get("status") == "pass" and not audio_qc.get("subtitleOnlyGroupIds")
             and all(row.get("status") == "pass" and row.get("nextAction") == "keep" for row in results),
             "Every unit must pass audio QC; subtitle-only units are not wired yet")
    from scripts.target_audio_auto_qc import THRESHOLDS
    _require(audio_qc.get("thresholds") == THRESHOLDS,
             "Audio QC thresholds differ from the calibrated release thresholds")
    summary = calibration_summary(calibration, locale, implementation, require_audio=True)
    runtime = waiver.runtime_identity_problems(calibration, audio_qc=audio_qc)
    _require(not runtime, "Audio QC runtime differs from calibration: " + "; ".join(runtime))
    # Unit checks say nothing about the track listeners hear.
    track = track_check_problems(package, track_check, implementation)
    _require(not track, "Assembled track is not verified: " + "; ".join(track))
    threshold = _asr_threshold()
    secondary_identity = None
    rows = []
    for row, unit in zip(results, package["units"]):
        group_id = unit["textGroupId"]
        primary = by_group[group_id]["similarity"]
        secondary = row.get("asrSecondary")
        _require(row.get("audioSha256") == unit["audio"]["sha256"],
                 f"Audio QC screened different audio: {group_id}")
        _require(row.get("textSha256") == unit["targetTextSha256"],
                 f"Audio QC checked the audio against different text: {group_id}")
        _require(row.get("asrPrimary") == primary and row.get("asrPrimaryModel") == {
                     "model": screening["model"], "modelRevision": screening.get("modelRevision")},
                 f"Audio QC primary ASR differs from the bound screening: {group_id}")
        if group_id in flagged:
            identity = row.get("asrSecondaryModel")
            _require(isinstance(identity, dict) and set(identity) == {"model", "modelRevision"}
                     and isinstance(identity["model"], str) and bool(identity["model"])
                     and (identity["modelRevision"] is None or
                          isinstance(identity["modelRevision"], str) and bool(identity["modelRevision"])),
                     f"Flagged unit needs its secondary ASR identity: {group_id}")
            _require(secondary_asr_model is None or secondary_asr_model == identity["model"],
                     "Secondary ASR CLI label differs from the QC runtime")
            _require(secondary_identity is None or secondary_identity == identity,
                     "Flagged units used different secondary ASR runtimes")
            secondary_identity = dict(identity)
            _require(isinstance(secondary, (int, float)) and secondary >= threshold,
                     f"Flagged unit needs a passing secondary ASR: {group_id}")
        rows.append({"textGroupId": group_id, "audioSha256": unit["audio"]["sha256"], "status": "pass",
                     "asr": "secondary_pass" if group_id in flagged else "primary_pass",
                     "primarySimilarity": primary,
                     "secondarySimilarity": secondary if group_id in flagged else None,
                     "secondaryAsrModel": dict(secondary_identity) if group_id in flagged else None,
                     "failedAttempts": int(row.get("failedAttempts", 0))})
    receipt = {
        "schemaVersion": AUDIO_WAIVER_SCHEMA, "reviewKind": REVIEW_KIND, "humanApproval": False,
        "decision": "machine_quality_waived", "targetLocale": locale,
        "englishSourcePackageJsonSha256": package["englishSourcePackageJsonSha256"],
        "targetLanguageCandidateJsonSha256": package["targetLanguageCandidateJsonSha256"],
        "targetLanguageAudioPackageJsonSha256": json_sha256(package),
        "trackSha256": package["track"]["sha256"],
        "textWaiverJsonSha256": json_sha256(text_waiver),
        "machineScreeningStatus": package["machineScreening"]["status"],
        "machineScreeningReceiptJsonSha256": json_sha256(screening),
        "secondaryAsrModel": secondary_identity,
        "reviewedUnitIds": [row["textGroupId"] for row in package["units"]],
        "unitResults": rows, "audioQcJsonSha256": json_sha256(audio_qc),
        "trackCheckJsonSha256": json_sha256(track_check),
        "calibration": summary,
        "implementationSha256": implementation, "rules": RULES,
        "disclosure": disclosure(locale), "createdAt": created_at or _now(),
        "postPublicationSpotCheck": "owner_spot_check_after_release",
    }
    _schema(receipt, AUDIO_WAIVER_SCHEMA)
    return receipt


def validate_audio_waiver(package: dict, receipt: dict, screening: dict | None) -> None:
    """Gate-time check that the waiver binds exactly this machine-screened package."""
    version = receipt.get("schemaVersion")
    _require(is_audio_waiver(receipt), "Unsupported audio waiver schema")
    _schema(receipt, version)
    _require(screening is not None, "Audio waiver requires the bound full ASR screening receipt")
    _require(_machine_screened(package),
             "Audio waiver applies only to a machine-screened package with no human decision")
    expected = {"targetLocale": package["targetLocale"],
                "englishSourcePackageJsonSha256": package["englishSourcePackageJsonSha256"],
                "targetLanguageCandidateJsonSha256": package["targetLanguageCandidateJsonSha256"],
                "targetLanguageAudioPackageJsonSha256": json_sha256(package),
                "trackSha256": package["track"]["sha256"],
                "machineScreeningStatus": package["machineScreening"]["status"],
                "machineScreeningReceiptJsonSha256": json_sha256(screening)}
    _require(all(receipt[key] == value for key, value in expected.items()),
             "Audio waiver does not bind this package, track and screening")
    flagged = set(screening_queue(package, screening))
    _require(not flagged or version == AUDIO_WAIVER_SCHEMA,
             "Legacy flagged audio waiver needs reissuance from bound QC with secondary ASR revision")
    _require(bool(receipt["secondaryAsrModel"]) == bool(flagged),
             "Secondary ASR identity differs from the screening queue")
    by_group = {row["textGroupId"]: row for row in screening["results"]}
    units = package["units"]
    threshold = _asr_threshold()
    _require(receipt["reviewedUnitIds"] == [unit["textGroupId"] for unit in units]
             and [row["textGroupId"] for row in receipt["unitResults"]] == receipt["reviewedUnitIds"],
             "Audio waiver coverage differs from the package")
    for row, unit in zip(receipt["unitResults"], units):
        group_id = unit["textGroupId"]
        _require(row["audioSha256"] == unit["audio"]["sha256"]
                 and row["primarySimilarity"] == by_group[group_id]["similarity"],
                 f"Audio waiver unit differs from the package: {group_id}")
        if group_id in flagged:
            _require(row.get("secondaryAsrModel") == receipt["secondaryAsrModel"],
                     f"Secondary ASR identity differs from its QC-bound unit: {group_id}")
            _require(row["asr"] == "secondary_pass" and receipt["secondaryAsrModel"]
                     and row["secondarySimilarity"] is not None and row["secondarySimilarity"] >= threshold,
                     f"Flagged unit lacks a passing secondary ASR: {group_id}")
        else:
            _require(row.get("secondaryAsrModel") is None, "Unflagged unit claims a secondary ASR identity")
            _require(row["asr"] == "primary_pass", f"Unflagged unit claims a secondary ASR: {group_id}")
    _validate_summary(receipt)


def _read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(value, dict), f"Expected JSON object: {path}")
    return value


def _write_once(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    text = sub.add_parser("text", help="Issue a text waiver for one candidate")
    for name in ("source", "anchor", "candidate", "text-qc", "calibration", "out"):
        text.add_argument(f"--{name}", required=True, type=Path)
    text.add_argument("--condensation-binding", type=Path,
                      help="The passing spoken_condensation binding when the candidate has condensed groups")
    audio = sub.add_parser("audio", help="Issue an audio waiver for one audio package")
    for name in ("package", "screening", "audio-qc", "track-check", "text-waiver", "calibration", "out"):
        audio.add_argument(f"--{name}", required=True, type=Path)
    audio.add_argument("--secondary-asr-model", help="Optional model-name assertion; runtime identity is derived from QC")
    args = parser.parse_args()
    if args.command == "text":
        receipt = build_text_waiver(_read(args.source), _read(args.anchor), _read(args.candidate),
                                    _read(args.text_qc), _read(args.calibration),
                                    condensation_binding=_read(args.condensation_binding)
                                    if args.condensation_binding else None)
    else:
        receipt = build_audio_waiver(_read(args.package), _read(args.screening), _read(args.audio_qc),
                                     _read(args.text_waiver), _read(args.calibration),
                                     track_check=_read(args.track_check),
                                     secondary_asr_model=args.secondary_asr_model)
    _write_once(args.out, receipt)
    print(json.dumps({"schemaVersion": receipt["schemaVersion"], "targetLocale": receipt["targetLocale"],
                      "decision": receipt["decision"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
