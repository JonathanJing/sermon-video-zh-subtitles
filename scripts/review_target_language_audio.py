#!/usr/bin/env python3
"""Prepare and admit a full audio/listening review without relabeling ASR uncertainty.

The operator fills the worksheet. A machine `requires_review` result can be
resolved only by explicit group adjudications in the independent v2 receipt.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from datetime import datetime

from jsonschema import Draft202012Validator, FormatChecker

try:
    from scripts import sermon_sentence_interpretation as identity
except ImportError:
    import sermon_sentence_interpretation as identity


ROOT = Path(__file__).resolve().parents[1]
CHECKS = ("pronunciation", "naturalness", "completeness", "scripture",
          "voiceIdentity", "synchronization")


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"Expected JSON object: {path}")
    return value


def validate(value: dict, schema: str) -> None:
    document = load(ROOT / "schemas" / schema)
    errors = list(Draft202012Validator(document, format_checker=FormatChecker()).iter_errors(value))
    require(not errors, f"{schema}: {errors[0].message if errors else ''}")


def queue(package: dict, screening: dict) -> list[str]:
    validate(package, "sermon-target-language-audio-package-v1.schema.json")
    validate(screening, "sermon-target-language-audio-screening-v1.schema.json")
    unit_ids = [row["textGroupId"] for row in package["units"]]
    require(package["status"] in {"candidate", "machine_screened"}
            and package["humanReview"]["status"] == "pending"
            and package["humanReview"]["humanApproval"] is False
            and package["machineScreening"]["status"] in {"pass", "requires_review"}
            and package["machineScreening"]["status"] == screening["status"]
            and package["machineScreening"]["coverage"] == screening["coverage"] == 1.0
            and package["machineScreening"]["model"] == screening["model"]
            and package["targetLocale"] == screening["targetLocale"]
            and package["targetLanguageSpeechJobJsonSha256"] == screening["targetLanguageSpeechJobJsonSha256"]
            and package["track"]["sha256"] == screening["trackSha256"]
            and unit_ids == screening["reviewedGroupIds"]
            and [row["audio"]["sha256"] for row in package["units"]] == screening["unitAudioSha256s"]
            and len(screening["results"]) == len(unit_ids),
            "Audio package and complete screening receipt differ")
    require(all(result["textGroupId"] == unit["textGroupId"]
                and result["audioSha256"] == unit["audio"]["sha256"]
                and result["targetTextSha256"] == unit["targetTextSha256"]
                for result, unit in zip(screening["results"], package["units"])),
            "ASR result differs from a reviewed unit")
    pending = [row["textGroupId"] for row in screening["results"]
               if row["status"] == "requires_review"]
    require((screening["status"] == "pass") == (not pending),
            "ASR overall status differs from review queue")
    return pending


def prepare(package: dict, screening: dict) -> dict:
    pending = queue(package, screening)
    return {
        "schemaVersion": "sermon-target-language-audio-review-worksheet-v1",
        "audioPackageJsonSha256": identity.json_sha256(package),
        "machineScreeningReceiptJsonSha256": identity.json_sha256(screening),
        "targetLocale": package["targetLocale"],
        "trackSha256": package["track"]["sha256"],
        "reviewedUnitIds": [row["textGroupId"] for row in package["units"]],
        "asrReviewQueue": pending,
        "decision": "pending",
        "reviewedBy": None,
        "reviewedAt": None,
        "fullPlayback": "pending",
        "videoSync1x": "pending",
        "checks": {name: "pending" for name in CHECKS},
        "asrAdjudications": [
            {"textGroupId": group_id, "decision": "pending", "evidence": None}
            for group_id in pending
        ],
        "issues": [],
    }


def approve(package: dict, screening: dict, worksheet: dict) -> tuple[dict, dict]:
    expected = prepare(package, screening)
    for key in ("schemaVersion", "audioPackageJsonSha256",
                "machineScreeningReceiptJsonSha256", "targetLocale",
                "trackSha256", "reviewedUnitIds", "asrReviewQueue"):
        require(worksheet.get(key) == expected[key], f"Audio worksheet identity changed: {key}")
    require(worksheet.get("decision") == "approved"
            and worksheet.get("fullPlayback") == "approved"
            and worksheet.get("videoSync1x") == "approved"
            and isinstance(worksheet.get("reviewedBy"), str)
            and worksheet["reviewedBy"].strip()
            and isinstance(worksheet.get("reviewedAt"), str)
            and datetime.fromisoformat(worksheet["reviewedAt"].replace("Z", "+00:00")).tzinfo is not None
            and worksheet.get("checks") == {name: "approved" for name in CHECKS}
            and worksheet.get("issues") == [],
            "Full playback, 1x video sync, all checks, reviewer and time must be approved")
    adjudications = worksheet.get("asrAdjudications")
    require(isinstance(adjudications, list)
            and [row.get("textGroupId") for row in adjudications] == expected["asrReviewQueue"]
            and all(row.get("decision") == "approved"
                    and isinstance(row.get("evidence"), str) and row["evidence"].strip()
                    for row in adjudications),
            "Every ASR uncertainty needs explicit human adjudication")
    reviewed = copy.deepcopy(package)
    reviewed["status"] = "human_reviewed"
    reviewed["humanReview"] = {
        "status": "approved", "humanApproval": True,
        "reviewedBy": worksheet["reviewedBy"].strip(),
        "reviewedAt": worksheet["reviewedAt"],
        "fullPlayback": "approved",
    }
    reviewed.pop("downstreamInvalidationKey")
    reviewed["downstreamInvalidationKey"] = identity.json_sha256(reviewed)
    validate(reviewed, "sermon-target-language-audio-package-v1.schema.json")
    receipt = {
        "schemaVersion": "sermon-target-language-audio-human-review-receipt-v2",
        "targetLocale": reviewed["targetLocale"],
        "englishSourcePackageJsonSha256": reviewed["englishSourcePackageJsonSha256"],
        "targetLanguageCandidateJsonSha256": reviewed["targetLanguageCandidateJsonSha256"],
        "targetLanguageAudioPackageJsonSha256": identity.json_sha256(reviewed),
        "trackSha256": reviewed["track"]["sha256"],
        "machineScreeningStatus": screening["status"],
        "machineScreeningReceiptJsonSha256": identity.json_sha256(screening),
        "asrAdjudications": adjudications,
        "decision": "approved",
        "reviewedBy": worksheet["reviewedBy"].strip(),
        "reviewedAt": worksheet["reviewedAt"],
        "fullPlayback": "approved",
        "videoSync1x": "approved",
        "reviewedUnitIds": expected["reviewedUnitIds"],
        "checks": worksheet["checks"],
        "issues": [],
    }
    validate(receipt, "sermon-target-language-audio-human-review-receipt-v2.schema.json")
    return reviewed, receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "approve"))
    parser.add_argument("--audio-package", type=Path, required=True)
    parser.add_argument("--screening-receipt", type=Path, required=True)
    parser.add_argument("--worksheet", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    require(not args.out.exists(), "Review output is immutable")
    package, screening = load(args.audio_package), load(args.screening_receipt)
    if args.command == "prepare":
        require(args.worksheet is None, "Prepare cannot consume a worksheet")
        identity.write_json(args.out, prepare(package, screening))
    else:
        require(args.worksheet is not None, "Approve requires a completed worksheet")
        reviewed, receipt = approve(package, screening, load(args.worksheet))
        args.out.mkdir(parents=True)
        identity.write_json(args.out / "audio-package.human-reviewed.json", reviewed)
        identity.write_json(args.out / "audio-human-review-receipt.json", receipt)
    print(json.dumps({"status": "human_review_pending" if args.command == "prepare"
                      else "human_reviewed", "out": str(args.out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
