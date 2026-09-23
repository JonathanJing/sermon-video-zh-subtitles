#!/usr/bin/env python3
"""Back-transcribe every formal Layer 3 unit without granting human approval.

The renderer's original manifest remains immutable. This command writes a
separate ASR receipt and a screened manifest only after binding every unit to
the exact approved speech job and audio bytes. Uncertain ASR output stays in a
review queue; it cannot be promoted to a machine pass by a coverage count.
"""
from __future__ import annotations

import argparse
import copy
import difflib
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from typing import Callable

try:
    from scripts import prepare_target_language_speech_job as speech
    from scripts import sermon_sentence_interpretation as identity
except ImportError:
    import prepare_target_language_speech_job as speech
    import sermon_sentence_interpretation as identity


SCHEMA = "sermon-target-language-audio-screening-v1"
MODEL = "Qwen/Qwen3-ASR-0.6B"


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"Expected JSON object: {path}")
    return value


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tokens(value: str, locale: str) -> list[str]:
    folded = unicodedata.normalize("NFKC", value).casefold()
    if locale in {"zh-Hans", "ko"}:
        return [char for char in folded if char.isalnum()]
    return re.findall(r"[^\W_]+", folded, flags=re.UNICODE)


def screen(job: dict, manifest: dict, artifact_root: Path,
           transcribe: Callable[[Path, str], str], *, model: str,
           model_revision: str, min_similarity: float = 0.88) -> tuple[dict, dict]:
    require(0 < min_similarity <= 1, "Invalid ASR similarity threshold")
    require(job.get("schemaVersion") == speech.SPEECH_JOB_SCHEMA
            and job.get("status") == "prepared_for_target_language_speech"
            and job.get("synthesisEligible") is True,
            "Formal synthesis-eligible speech job required")
    locale = job["targetLocale"]
    require(manifest.get("schemaVersion") == "sermon-target-language-render-manifest-v1"
            and manifest.get("targetLocale") == locale
            and manifest.get("targetLanguageSpeechJobJsonSha256") == identity.json_sha256(job)
            and manifest.get("englishSourcePackageJsonSha256")
            == job["inputs"]["englishSourcePackage"]["jsonSha256"]
            and manifest.get("targetLanguageCandidateJsonSha256")
            == job["inputs"]["targetLanguageCandidate"]["jsonSha256"],
            "Render manifest differs from formal speech job")
    require(manifest.get("machineScreening", {}).get("status") == "not_run"
            and "machineScreeningReceipt" not in manifest,
            "Screen only an unmodified renderer manifest")
    rows = manifest.get("units")
    require(isinstance(rows, list) and len(rows) == len(job["units"]),
            "Render manifest does not cover all job units")
    track = manifest.get("track", {})
    track_path = (artifact_root / track.get("path", "")).resolve()
    require(track_path.is_relative_to(artifact_root.resolve())
            and track_path.is_file() and file_sha(track_path) == track.get("sha256"),
            "Rendered track hash mismatch")
    results = []
    for index, (unit, row) in enumerate(zip(job["units"], rows)):
        group_id = unit["translationGroupId"]
        expected_hash = hashlib.sha256(unit["text"].encode("utf-8")).hexdigest()
        audio = row.get("audio", {})
        expected_path = (artifact_root / unit["outputRelativePath"]).resolve()
        require(row.get("textGroupId") == group_id
                and row.get("targetTextSha256") == expected_hash
                and audio.get("path") == unit["outputRelativePath"]
                and expected_path.is_relative_to(artifact_root.resolve())
                and expected_path.is_file() and file_sha(expected_path) == audio.get("sha256"),
                f"ASR unit identity or audio hash mismatch: {index}")
        recognized = transcribe(expected_path, locale).strip()
        expected_tokens, actual_tokens = tokens(unit["text"], locale), tokens(recognized, locale)
        require(expected_tokens, f"Empty expected text: {group_id}")
        matcher = difflib.SequenceMatcher(None, expected_tokens, actual_tokens, autojunk=False)
        similarity = round(matcher.ratio(), 6)
        differences = [{"kind": kind,
                        "expected": expected_tokens[left_start:left_end],
                        "recognized": actual_tokens[right_start:right_end]}
                       for kind, left_start, left_end, right_start, right_end
                       in matcher.get_opcodes() if kind != "equal"]
        # Short units are more vulnerable to a high score hiding one material
        # missing word, so require exact normalized ASR for them.
        passed = similarity >= min_similarity and (len(expected_tokens) >= 4 or not differences)
        results.append({
            "textGroupId": group_id,
            "targetTextSha256": expected_hash,
            "audioSha256": audio["sha256"],
            "recognized": recognized,
            "similarity": similarity,
            "differences": differences,
            "status": "pass" if passed else "requires_review",
        })
    status = "pass" if all(row["status"] == "pass" for row in results) else "requires_review"
    receipt = {
        "schemaVersion": SCHEMA,
        "targetLocale": locale,
        "targetLanguageSpeechJobJsonSha256": identity.json_sha256(job),
        "trackSha256": track["sha256"],
        "status": status,
        "model": model,
        "modelRevision": model_revision,
        "minSimilarity": min_similarity,
        "coverage": 1.0,
        "reviewedGroupIds": [row["textGroupId"] for row in results],
        "unitAudioSha256s": [row["audioSha256"] for row in results],
        "results": results,
        "humanListeningStatus": "pending",
    }
    screened = copy.deepcopy(manifest)
    screened["machineScreening"] = {"status": status, "model": model, "coverage": 1.0}
    return receipt, screened


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--render-manifest", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--model-revision", required=True)
    parser.add_argument("--min-similarity", type=float, default=0.88)
    parser.add_argument("--out-receipt", type=Path, required=True)
    parser.add_argument("--out-manifest", type=Path, required=True)
    args = parser.parse_args()
    require(not args.out_receipt.exists() and not args.out_manifest.exists(),
            "ASR receipt and screened manifest are immutable")
    require(args.out_receipt.resolve().is_relative_to(args.artifact_root.resolve()),
            "ASR receipt must live inside the renderer artifact root")
    weights = args.model_path.resolve() / "model.safetensors"
    require(weights.is_file()
            and args.model_revision == f"model.safetensors:sha256:{file_sha(weights)}",
            "ASR model revision differs from deployed weights")
    import soundfile as sf
    import torch
    from qwen_asr import Qwen3ASRModel

    model = Qwen3ASRModel.from_pretrained(
        str(args.model_path.resolve()), dtype=torch.bfloat16,
        device_map="cuda:0", max_inference_batch_size=1, max_new_tokens=2048)
    languages = {"zh-Hans": "Chinese", "ko": "Korean", "es": "Spanish"}

    def transcribe(path: Path, locale: str) -> str:
        audio, sample_rate = sf.read(path, dtype="float32")
        return model.transcribe(audio=(audio, sample_rate), language=languages[locale])[0].text

    receipt, screened = screen(load(args.job), load(args.render_manifest),
                               args.artifact_root.resolve(), transcribe,
                               model=MODEL, model_revision=args.model_revision,
                               min_similarity=args.min_similarity)
    args.out_receipt.parent.mkdir(parents=True, exist_ok=True)
    args.out_receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    # The manifest's evidence path is relative to the renderer artifact root.
    relative = args.out_receipt.resolve().relative_to(args.artifact_root.resolve())
    screened["machineScreeningReceipt"] = {
        "path": str(relative), "sha256": file_sha(args.out_receipt),
        "jsonSha256": identity.json_sha256(receipt),
    }
    args.out_manifest.parent.mkdir(parents=True, exist_ok=True)
    args.out_manifest.write_text(json.dumps(screened, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": receipt["status"], "groups": len(receipt["results"]),
                      "reviewQueue": [row["textGroupId"] for row in receipt["results"]
                                      if row["status"] != "pass"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
