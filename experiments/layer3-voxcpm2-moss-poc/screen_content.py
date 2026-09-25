#!/usr/bin/env python3
"""Run multilingual Qwen3-ASR content screens over all POC candidates."""
import argparse
import difflib
import importlib.util
import json
from pathlib import Path
import unicodedata


def helpers():
    path = Path(__file__).with_name("poc.py")
    spec = importlib.util.spec_from_file_location("layer3_multimodel_helpers", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def normalize(text):
    return "".join(character.lower() for character in unicodedata.normalize("NFKC", text or "") if unicodedata.category(character)[0] in {"L", "N"})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--model-id", default="Qwen/Qwen3-ASR-0.6B")
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    helper = helpers()
    plan = helper.load_plan(args.plan)
    import torch
    from qwen_asr import Qwen3ASRModel
    model = Qwen3ASRModel.from_pretrained(
        str(args.model_path), dtype=torch.bfloat16, device_map="cuda:0",
        max_new_tokens=1024, max_inference_batch_size=1,
    )
    results = []
    for spec in helper.candidate_specs(plan, args.run_dir):
        recognized = model.transcribe(audio=str(spec["path"]), language=spec["language"])[0].text
        expected, actual = normalize(spec["targetText"]), normalize(recognized)
        matcher = difflib.SequenceMatcher(None, expected, actual, autojunk=False)
        row = {
            "sampleId": spec["sampleId"], "variant": spec["variant"], "targetLocale": spec["targetLocale"],
            "status": "screened", "audioSha256": helper.sha256(spec["path"]),
            "expectedTextSha256": spec["targetTextSha256"], "recognized": recognized,
            "normalizedSimilarity": matcher.ratio(),
            "differences": [{"kind": op, "expected": expected[a:b], "recognized": actual[c:d]} for op, a, b, c, d in matcher.get_opcodes() if op != "equal"],
        }
        results.append(row)
        print(json.dumps({"sampleId": row["sampleId"], "variant": row["variant"], "similarity": row["normalizedSimilarity"]}, ensure_ascii=False), flush=True)
    helper.write_json(args.run_dir / "asr-screening.json", {
        "schemaVersion": "sermon-layer3-voxcpm2-moss-asr-screen-v1", "model": args.model_id,
        "revision": args.revision, "normalization": "Unicode NFKC letters and numbers; punctuation and whitespace ignored",
        "results": results, "humanApproval": False,
    })


if __name__ == "__main__":
    main()
