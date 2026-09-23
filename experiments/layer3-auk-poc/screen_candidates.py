#!/usr/bin/env python3
"""Run Korean Qwen3-ASR content screens over every generated POC candidate."""
import argparse
import difflib
import hashlib
import importlib.util
import json
from pathlib import Path
import re


def load_helpers(directory):
    path = Path(__file__).with_name("layer3_poc.py")
    spec = importlib.util.spec_from_file_location("layer3_auk_helpers", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def normalize(text):
    return "".join(re.findall(r"[\uac00-\ud7a3A-Za-z0-9]", text or "")).lower()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--model", default="Qwen/Qwen3-ASR-0.6B")
    parser.add_argument("--revision", default="5eb144179a02acc5e5ba31e748d22b0cf3e303b0")
    parser.add_argument("--local-files-only", action="store_true")
    args = parser.parse_args()
    helpers = load_helpers(Path(__file__).parent)
    plan = helpers.load_plan(args.plan)

    import torch
    from huggingface_hub import snapshot_download
    from qwen_asr import Qwen3ASRModel
    snapshot = Path(snapshot_download(repo_id=args.model, revision=args.revision, local_files_only=args.local_files_only))
    model = Qwen3ASRModel.from_pretrained(
        str(snapshot), dtype=torch.bfloat16, device_map="cuda:0", max_new_tokens=1024, max_inference_batch_size=1,
    )
    results = []
    for unit, variant, path in helpers.candidate_paths(plan, args.run_dir):
        recognized = model.transcribe(audio=str(path), language="Korean")[0].text
        expected_normalized, actual_normalized = normalize(unit["targetText"]), normalize(recognized)
        matcher = difflib.SequenceMatcher(None, expected_normalized, actual_normalized, autojunk=False)
        differences = [
            {"kind": op, "expected": expected_normalized[a:b], "recognized": actual_normalized[c:d]}
            for op, a, b, c, d in matcher.get_opcodes() if op != "equal"
        ]
        row = {
            "sourceUnitId": unit["sourceUnitId"], "variant": variant, "status": "screened",
            "audioSha256": helpers.sha256(path), "expectedTextSha256": unit["targetTextSha256"],
            "recognized": recognized, "normalizedSimilarity": matcher.ratio(), "differences": differences,
        }
        results.append(row)
        print(json.dumps({"sourceUnitId": row["sourceUnitId"], "variant": variant, "similarity": row["normalizedSimilarity"]}, ensure_ascii=False), flush=True)
    helpers.write_json(args.run_dir / "asr-screening.json", {
        "schemaVersion": "sermon-layer3-qwen-auk-asr-screen-v1", "model": args.model,
        "revision": args.revision, "normalization": "Korean syllables, ASCII letters and digits; punctuation and whitespace ignored",
        "results": results, "humanApproval": False,
    })


if __name__ == "__main__":
    main()
