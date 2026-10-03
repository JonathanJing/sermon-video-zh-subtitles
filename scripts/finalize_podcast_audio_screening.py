#!/usr/bin/env python3
"""Bind a completed ASR screen to an unreleased podcast audio package."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError:
    Draft202012Validator = None
    FormatChecker = None


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "sermon-target-language-audio-package-v3-multilingual-podcast.schema.json"


def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def json_sha(value: Any) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to replace immutable artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--package", type=Path, required=True)
    p.add_argument("--receipt", type=Path, required=True)
    p.add_argument("--runtime", type=Path, required=True)
    p.add_argument("--job", type=Path, required=True)
    p.add_argument("--candidate", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    load = lambda path: json.loads(path.read_text(encoding="utf-8"))
    package, receipt, runtime, job, candidate = map(
        load, (args.package, args.receipt, args.runtime, args.job, args.candidate))
    require = lambda ok, message: (_ for _ in ()).throw(ValueError(message)) if not ok else None
    package_hash, job_hash, candidate_hash = map(json_sha, (package, job, candidate))
    require(package.get("schemaVersion") == "sermon-target-language-audio-package-v3-multilingual-podcast"
            and package.get("status") == "candidate" and package.get("releaseEligible") is False
            and package.get("humanReview", {}).get("status") == "pending"
            and package.get("humanReview", {}).get("humanApproval") is False,
            "Input package is not an unreleased, audio-review-pending candidate")
    require(package.get("targetLanguageSpeechJobJsonSha256") == job_hash
            and package.get("targetLanguageCandidateJsonSha256") == candidate_hash
            and receipt.get("targetLanguageSpeechJobJsonSha256") == job_hash
            and receipt.get("targetLocale") == package.get("targetLocale")
            and receipt.get("trackSha256") == package.get("track", {}).get("sha256"),
            "Package, ASR receipt, job, or Layer 2 candidate identity differs")
    unit_ids = [row["textGroupId"] for row in package["units"]]
    audio_hashes = [row["audio"]["sha256"] for row in package["units"]]
    results = receipt.get("results", [])
    require(len(unit_ids) == len(results) == 839
            and receipt.get("coverage") == 1.0
            and receipt.get("reviewedGroupIds") == unit_ids
            and receipt.get("unitAudioSha256s") == audio_hashes
            and [row.get("textGroupId") for row in results] == unit_ids
            and all(row.get("audioSha256") == digest for row, digest in zip(results, audio_hashes)),
            "ASR screening does not cover the complete ordered package audio")
    require(receipt.get("status") in {"pass", "requires_review", "fail"}
            and runtime.get("receiptJsonSha256") == json_sha(receipt)
            and runtime.get("unitCount") == 839
            and runtime.get("status") == receipt.get("status"),
            "ASR runtime receipt is invalid or does not bind the screening output")
    output = dict(package)
    output["status"] = "machine_screened"
    output["machineScreening"] = {"status": receipt["status"],
                                  "model": receipt["model"],
                                  "modelRevision": receipt["modelRevision"],
                                  "coverage": receipt["coverage"]}
    flagged = [row["textGroupId"] for row in results if row.get("status") != "pass"]
    output["issues"] = list(package.get("issues", []))
    output["issues"].append({"code": "machine_asr_screening",
                             "severity": "review_required" if flagged else "informational",
                             "screenedCandidatePackageJsonSha256": package_hash,
                             "receipt": {"path": str(args.receipt), "sha256": file_sha(args.receipt),
                                         "jsonSha256": json_sha(receipt)},
                             "runtime": {"path": str(args.runtime), "sha256": file_sha(args.runtime),
                                         "jsonSha256": json_sha(runtime)},
                             "flaggedGroupIds": flagged,
                             "humanListeningStatus": "pending"})
    output["downstreamInvalidationKey"] = json_sha({
        "candidatePackage": package["downstreamInvalidationKey"],
        "asrReceipt": json_sha(receipt), "asrRuntime": json_sha(runtime)})
    schema_path = ROOT / "schemas" / SCHEMA
    if Draft202012Validator is not None:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(output))
        require(not errors, "Final package schema errors: " + "; ".join(e.message for e in errors))
    else:
        require(output["releaseEligible"] is False and output["humanReview"]["humanApproval"] is False
                and output["humanReview"]["fullPlayback"] == "pending"
                and output["machineScreening"]["coverage"] == 1.0,
                "Final package fails structural review-pending checks")
    write_json(args.out, output)
    print(json.dumps({"status": output["status"], "machineScreening": receipt["status"],
                      "coverage": receipt["coverage"], "flaggedUnits": len(flagged),
                      "audioHumanReview": output["humanReview"]["status"],
                      "releaseEligible": output["releaseEligible"], "out": str(args.out)},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
