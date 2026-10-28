#!/usr/bin/env python3
"""Prepare and admit a full audio/listening review with human listening as the only gate.

2026-10-28: ASR screening, second-level ASR and the machine listening waiver were
retired. A package now records ``machineScreening.status = not_run`` and this
receipt binds only the track, the reviewed units and the person who listened at
1x. Deterministic audio QC stays available as a separate preflight check; it is
not an acceptance basis and this receipt does not claim machine listening.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from datetime import datetime

from jsonschema import Draft202012Validator, FormatChecker

from ..source import sentence_interpretation as identity
from . import backend as _audio


def __getattr__(name):
    # The checkout root callers read as a module constant; it lives in the host.
    if name == "ROOT":
        return _audio.current().core.repo_root
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
    document = load(_audio.current().schemas.path(schema))
    errors = list(Draft202012Validator(document, format_checker=FormatChecker()).iter_errors(value))
    require(not errors, f"{schema}: {errors[0].message if errors else ''}")


def queue(package: dict) -> list[str]:
    """No machine review queue remains; the gate is the full-track listen.

    A package may only enter review as a rendered candidate with its human
    decision and playback still pending. Machine screening evidence, if an old
    package still carries it, is never consulted.
    """
    validate(package, "sermon-target-language-audio-package-v1.schema.json")
    require(package["status"] == "candidate"
            and package["humanReview"]["status"] == "pending"
            and package["humanReview"]["humanApproval"] is False,
            "Audio package is not a pending candidate")
    return []


def prepare(package: dict) -> dict:
    queue(package)
    return {
        "schemaVersion": "sermon-target-language-audio-review-worksheet-v2",
        "audioPackageJsonSha256": identity.json_sha256(package),
        "targetLocale": package["targetLocale"],
        "trackSha256": package["track"]["sha256"],
        "reviewedUnitIds": [row["textGroupId"] for row in package["units"]],
        "decision": "pending",
        "reviewedBy": None,
        "reviewedAt": None,
        "fullPlayback": "pending",
        "videoSync1x": "pending",
        "checks": {name: "pending" for name in CHECKS},
        "issues": [],
    }


def approve(package: dict, worksheet: dict, *, publication_exception: dict | None = None,
            adjudication_details: dict | None = None, artifact_root: Path | None = None) -> tuple[dict, dict]:
    expected = prepare(package)
    require(adjudication_details is None,
            "ASR adjudication details no longer apply: machine listening was retired")
    reviewed = copy.deepcopy(package)
    reviewed["status"] = "human_reviewed"
    reviewed["humanReview"] = {
        "status": "approved", "humanApproval": True,
        "reviewedBy": worksheet.get("reviewedBy", "").strip() if isinstance(worksheet.get("reviewedBy"), str) else "",
        "reviewedAt": worksheet.get("reviewedAt"),
        "fullPlayback": "approved",
    }
    reviewed.pop("downstreamInvalidationKey")
    reviewed["downstreamInvalidationKey"] = identity.json_sha256(reviewed)
    for key in ("schemaVersion", "audioPackageJsonSha256", "targetLocale",
                "trackSha256", "reviewedUnitIds"):
        require(worksheet.get(key) == expected[key], f"Audio worksheet identity changed: {key}")
    expected_checks = {name: "approved" for name in CHECKS}
    sync_status = "approved"
    if publication_exception is not None:
        if publication_exception.get("schemaVersion") == "sermon-video-sync-publication-exception-v1":
            require(package["targetLocale"] == "zh-Hans"
                    and publication_exception.get("scope") == "publish_reviewed_chinese_audio_with_video_sync_not_run"
                    and publication_exception.get("humanApproval") is True
                    and publication_exception.get("userDecision") == "接受，先发布并如实保留未验收状态"
                    and publication_exception.get("trackSha256") == package["track"]["sha256"],
                    "Publication exception v1 requires the exact Chinese track and explicit acceptance")
        elif publication_exception.get("schemaVersion") == "sermon-video-sync-publication-exception-v2":
            identities = {
                "targetLocale": package["targetLocale"],
                "englishSourcePackageJsonSha256": package["englishSourcePackageJsonSha256"],
                "targetLanguageCandidateJsonSha256": package["targetLanguageCandidateJsonSha256"],
                "targetLanguageAudioPackageJsonSha256": identity.json_sha256(reviewed),
                "trackSha256": package["track"]["sha256"],
            }
            require(package["targetLocale"] in {"zh-Hans", "ko", "es"}
                    and publication_exception.get("scope") == "publish_reviewed_audio_with_video_sync_not_run"
                    and publication_exception.get("humanApproval") is True
                    and publication_exception.get("userDecision") == "接受，先发布并如实保留未验收状态"
                    and all(publication_exception.get(key) == value for key, value in identities.items()),
                    "Publication exception v2 is not bound to this locale and reviewed audio package")
        else:
            raise ValueError("Unsupported publication exception")
        sync_status = "not_run"
        expected_checks["synchronization"] = "not_run"
    require(worksheet.get("decision") == "approved"
            and worksheet.get("fullPlayback") == "approved"
            and worksheet.get("videoSync1x") == sync_status
            and isinstance(worksheet.get("reviewedBy"), str)
            and worksheet["reviewedBy"].strip()
            and isinstance(worksheet.get("reviewedAt"), str)
            and datetime.fromisoformat(worksheet["reviewedAt"].replace("Z", "+00:00")).tzinfo is not None
            and worksheet.get("checks") == expected_checks
            and worksheet.get("issues") == [],
            "Full playback, video sync decision, all checks, reviewer and time must be approved")
    validate(reviewed, "sermon-target-language-audio-package-v1.schema.json")
    receipt = {
        "schemaVersion": "sermon-target-language-audio-human-review-receipt-v5",
        "targetLocale": reviewed["targetLocale"],
        "englishSourcePackageJsonSha256": reviewed["englishSourcePackageJsonSha256"],
        "targetLanguageCandidateJsonSha256": reviewed["targetLanguageCandidateJsonSha256"],
        "targetLanguageAudioPackageJsonSha256": identity.json_sha256(reviewed),
        "trackSha256": reviewed["track"]["sha256"],
        "decision": "approved",
        "reviewedBy": worksheet["reviewedBy"].strip(),
        "reviewedAt": worksheet["reviewedAt"],
        "fullPlayback": "approved",
        "videoSync1x": sync_status,
        "reviewedUnitIds": expected["reviewedUnitIds"],
        "checks": worksheet["checks"],
        "issues": [],
    }
    if publication_exception is not None:
        receipt["publicationException"] = publication_exception
    validate(receipt, receipt["schemaVersion"] + ".schema.json")
    return reviewed, receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "approve"))
    parser.add_argument("--audio-package", type=Path, required=True)
    parser.add_argument("--worksheet", type=Path)
    parser.add_argument("--publication-exception", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    require(not args.out.exists(), "Review output is immutable")
    package = load(args.audio_package)
    if args.command == "prepare":
        require(args.worksheet is None, "Prepare cannot consume a worksheet")
        identity.write_json(args.out, prepare(package))
    else:
        require(args.worksheet is not None, "Approve requires a completed worksheet")
        reviewed, receipt = approve(package, load(args.worksheet),
            publication_exception=load(args.publication_exception) if args.publication_exception else None)
        args.out.mkdir(parents=True)
        identity.write_json(args.out / "audio-package.human-reviewed.json", reviewed)
        identity.write_json(args.out / "audio-human-review-receipt.json", receipt)
    print(json.dumps({"status": "human_review_pending" if args.command == "prepare"
                      else "human_reviewed", "out": str(args.out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
