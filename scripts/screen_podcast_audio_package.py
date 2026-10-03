#!/usr/bin/env python3
"""Run Qwen3-ASR back-transcription against a frozen dual-speaker podcast package."""
from __future__ import annotations

import argparse
import difflib
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import tempfile
import unicodedata
import re


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def json_sha(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        tmp = Path(stream.name)
        stream.write(json.dumps(value, ensure_ascii=False, indent=2).encode() + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.link(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def tokens(value: str) -> list[str]:
    folded = unicodedata.normalize("NFKC", value).casefold()
    return [char for char in folded if char.isalnum()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--review-waiver", type=Path,
                        help="Exact source-bound Layer 2 content-review waiver for ES/KO candidates")
    parser.add_argument("--audio-root", type=Path, required=True,
                        help="Root containing the rendered job's relative WAV paths")
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--model-revision", required=True)
    parser.add_argument("--out-receipt", type=Path, required=True)
    parser.add_argument("--out-runtime", type=Path, required=True)
    parser.add_argument("--unit-cache", type=Path, required=True)
    parser.add_argument("--min-similarity", type=float, default=0.88)
    args = parser.parse_args()

    package = json.loads(args.package.read_text(encoding="utf-8"))
    job = json.loads(args.job.read_text(encoding="utf-8"))
    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    waiver = json.loads(args.review_waiver.read_text(encoding="utf-8")) if args.review_waiver else None
    package_hash, job_hash, candidate_hash = map(json_sha, (package, job, candidate))
    require = lambda ok, msg: (_ for _ in ()).throw(ValueError(msg)) if not ok else None
    multilingual = package.get("schemaVersion") == "sermon-target-language-audio-package-v3-multilingual-podcast"
    if multilingual:
        require(package.get("targetLocale") in {"es", "ko"}
                and package.get("status") == "candidate"
                and package.get("humanReview", {}).get("humanApproval") is False
                and package.get("humanReview", {}).get("status") == "pending"
                and waiver is not None
                and package.get("contentReviewWaiverJsonSha256") == json_sha(waiver)
                and waiver.get("humanApproval") is False and waiver.get("releaseEligible") is False
                and waiver.get("audioHumanReviewRequired") is True
                and waiver.get("targetLocale") == package.get("targetLocale"),
                "multilingual candidate requires its matching non-approval waiver and pending audio review")
    else:
        require(package.get("schemaVersion") == "sermon-target-language-audio-package-v2-podcast"
                and package.get("status") == "human_reviewed"
                and package.get("humanReview", {}).get("humanApproval") is True,
                "approved podcast audio package required")
        require(package.get("targetLocale") == "zh-Hans",
                "legacy podcast audio package is zh-Hans only")
    require(package.get("track", {}).get("sha256")
            and len(package.get("units", [])) == 839,
            "podcast package identity or unit coverage mismatch")
    require(job.get("schemaVersion") in {"sermon-target-language-speech-job-v3-podcast",
                                         "sermon-target-language-speech-job-v4-multilingual-podcast"}
            and job.get("releaseEligible") is False and len(job.get("units", [])) == 839,
            "source-bound dual-worker speech job required")
    require(((candidate.get("status") == "human_translation_approved"
              and candidate.get("humanReview", {}).get("translation") == "approved")
             or (multilingual and candidate.get("status") == "machine_review_pass_human_review_pending"
                 and candidate.get("humanReview", {}).get("translation") == "pending"
                 and candidate.get("releaseEligible") is False
                 and candidate.get("targetLocale") == package.get("targetLocale")))
            and len(candidate.get("groups", [])) == 839,
            "Layer 2 candidate or explicit review-waiver binding required")
    if multilingual:
        require(waiver.get("englishSourcePackageJsonSha256") == candidate.get("englishSourcePackageJsonSha256")
                and waiver.get("anchorManifestSha256") == candidate.get("anchorManifestSha256")
                and waiver.get("translationPolicySha256") == candidate.get("translationPolicySha256")
                and job.get("inputs", {}).get("contentReviewWaiver", {}).get("jsonSha256") == json_sha(waiver),
                "Review waiver, Layer 2 candidate, and Layer 3 job differ")
    require(package.get("targetLanguageSpeechJobJsonSha256") == job_hash
            and package.get("targetLanguageCandidateJsonSha256") == candidate_hash
            and job.get("inputs", {}).get("targetLanguageCandidate", {}).get("jsonSha256") == candidate_hash,
            "Layer 2/3 package identity mismatch")
    require(len(package["units"]) == len(job["units"]) == len(candidate["groups"]),
            "Layer 2/3 group counts differ")
    require(0 < args.min_similarity <= 1, "invalid similarity threshold")
    require(not args.out_receipt.exists() and not args.out_runtime.exists(),
            "screening outputs are immutable")

    model_files = sorted(p for p in args.model_path.rglob("*") if p.is_file())
    weight_path = args.model_path / "model.safetensors"
    require(weight_path.is_file(), "ASR model weights are missing")
    model_hash = file_sha(weight_path)
    require(args.model_revision.startswith("Qwen/Qwen3-ASR-0.6B@"),
            "pinned Qwen3-ASR-0.6B revision required")

    import torch
    import soundfile as sf
    from qwen_asr import Qwen3ASRModel

    model = Qwen3ASRModel.from_pretrained(
        str(args.model_path.resolve()), dtype=torch.bfloat16, device_map="cuda:0",
        max_inference_batch_size=1, max_new_tokens=2048)
    audio_root = args.audio_root.resolve()
    require(audio_root.is_dir(), "rendered audio root is missing")
    cache_root = args.unit_cache.resolve()
    require(cache_root.is_relative_to(args.out_receipt.parent.resolve()),
            "unit cache must be inside the receipt artifact directory")
    results = []
    for index, (audio_row, job_unit, text_group) in enumerate(
            zip(package["units"], job["units"], candidate["groups"])):
        group_id = job_unit["translationGroupId"]
        text = job_unit["text"]
        expected_text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        require(audio_row["textGroupId"] == group_id == text_group["translationGroupId"]
                and audio_row["targetTextSha256"] == expected_text_hash
                and text_group["targetText"] == text,
                f"source text identity mismatch at unit {index}")
        rel = Path(job_unit["outputRelativePath"])
        audio_path = (audio_root / rel).resolve()
        require(audio_path.is_relative_to(audio_root) and audio_path.is_file(),
                f"audio file missing or escaped root: {group_id}")
        audio_hash = file_sha(audio_path)
        require(audio_hash == audio_row["audio"]["sha256"],
                f"audio hash mismatch: {group_id}")
        cache_path = cache_root / f"unit-{index:04d}.json"
        identity = {"unitIndex": index, "textGroupId": group_id,
                    "targetTextSha256": expected_text_hash, "audioSha256": audio_hash,
                    "jobJsonSha256": job_hash, "packageJsonSha256": package_hash,
                    "modelRevision": args.model_revision, "modelWeightSha256": model_hash,
                    "runnerSha256": file_sha(Path(__file__))}
        if cache_path.exists():
            saved = json.loads(cache_path.read_text(encoding="utf-8"))
            require(saved.get("identity") == identity,
                    f"cached ASR identity differs: {group_id}")
            recognized = saved.get("recognized")
            require(isinstance(recognized, str), f"cached ASR text invalid: {group_id}")
        else:
            sample, sample_rate = sf.read(audio_path, dtype="float32")
            language = {"zh-Hans": "Chinese", "es": "Spanish", "ko": "Korean"}[package["targetLocale"]]
            transcribed = model.transcribe(audio=(sample, sample_rate), language=language)
            require(isinstance(transcribed, list) and len(transcribed) == 1
                    and isinstance(transcribed[0].text, str),
                    f"ASR response invalid: {group_id}")
            recognized = transcribed[0].text.strip()
            write_atomic(cache_path, {"identity": identity, "recognized": recognized,
                                      "recognizedSha256": hashlib.sha256(recognized.encode()).hexdigest()})
        expected, actual = tokens(text), tokens(recognized)
        ratio = round(difflib.SequenceMatcher(None, expected, actual, autojunk=False).ratio(), 6)
        differences = [{"kind": op, "expected": expected[a:b], "recognized": actual[c:d]}
                       for op, a, b, c, d in difflib.SequenceMatcher(
                           None, expected, actual, autojunk=False).get_opcodes() if op != "equal"]
        passed = ratio >= args.min_similarity and (len(expected) >= 4 or not differences)
        results.append({"textGroupId": group_id, "targetTextSha256": expected_text_hash,
                        "audioSha256": audio_hash, "recognized": recognized,
                        "similarity": ratio, "differences": differences,
                        "status": "pass" if passed else "requires_review"})
        if (index + 1) % 50 == 0:
            print(json.dumps({"completedUnits": index + 1, "totalUnits": len(job["units"])}), flush=True)

    status = "pass" if all(row["status"] == "pass" for row in results) else "requires_review"
    receipt = {"schemaVersion": "sermon-target-language-audio-screening-v2-multilingual",
               "targetLocale": package["targetLocale"], "targetLanguageSpeechJobJsonSha256": job_hash,
               "trackSha256": package["track"]["sha256"], "status": status,
               "model": "Qwen/Qwen3-ASR-0.6B", "modelRevision": args.model_revision,
               "minSimilarity": args.min_similarity, "coverage": 1.0,
               "reviewedGroupIds": [row["textGroupId"] for row in results],
               "unitAudioSha256s": [row["audioSha256"] for row in results],
               "results": results, "humanListeningStatus": "pending"}
    runtime = {"schemaVersion": "podcast-audio-asr-runtime-v1", "receiptJsonSha256": json_sha(receipt),
               "receiptByteSha256": hashlib.sha256(json.dumps(
                   receipt, ensure_ascii=False, indent=2).encode() + b"\n").hexdigest(),
               "runnerSha256": file_sha(Path(__file__)), "modelRevision": args.model_revision,
               "modelWeightSha256": model_hash,
               "modelJsonSha256s": {str(p.relative_to(args.model_path)): file_sha(p)
                                     for p in model_files if p.suffix == ".json"},
               "torchVersion": str(torch.__version__),
               "transformersVersion": importlib.metadata.version("transformers"),
               "qwenAsrVersion": importlib.metadata.version("qwen-asr"),
               "soundfileVersion": importlib.metadata.version("soundfile"),
               "executionDevice": "cuda:0", "inferenceBatchSize": 1,
               "unitCount": len(results), "status": status}
    write_atomic(args.out_receipt, receipt)
    write_atomic(args.out_runtime, runtime)
    print(json.dumps({"status": status, "unitCount": len(results),
                      "reviewQueue": [row["textGroupId"] for row in results
                                      if row["status"] != "pass"],
                      "receipt": str(args.out_receipt.resolve())}), flush=True)


if __name__ == "__main__":
    main()
