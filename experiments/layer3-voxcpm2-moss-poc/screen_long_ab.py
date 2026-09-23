#!/usr/bin/env python3
"""Run a Qwen3-ASR content screen over the two long Chinese A/B samples."""
import argparse
import difflib
import importlib.util
from pathlib import Path
import unicodedata


def load_module(filename, name):
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def normalize(text):
    return "".join(
        character.lower()
        for character in unicodedata.normalize("NFKC", text or "")
        if unicodedata.category(character)[0] in {"L", "N"}
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    renderer = load_module("render_long_ab.py", "long_ab_screen_renderer")
    helper = load_module("poc.py", "long_ab_screen_helpers")
    plan = renderer.load_plan(args.plan)
    import torch
    from qwen_asr import Qwen3ASRModel
    model = Qwen3ASRModel.from_pretrained(
        str(args.model_path), dtype=torch.bfloat16, device_map="cuda:0",
        max_new_tokens=2048, max_inference_batch_size=1,
    )
    expected = normalize(plan["passage"]["text"])
    results = []
    for engine in ("qwen", "voxcpm2"):
        path = args.run_dir / f"{engine}.wav"
        recognized = model.transcribe(audio=str(path), language="Chinese")[0].text
        actual = normalize(recognized)
        matcher = difflib.SequenceMatcher(None, expected, actual, autojunk=False)
        results.append({
            "engine": engine, "audioSha256": helper.sha256(path), "recognized": recognized,
            "normalizedSimilarity": matcher.ratio(),
            "differences": [
                {"kind": op, "expected": expected[a:b], "recognized": actual[c:d]}
                for op, a, b, c, d in matcher.get_opcodes() if op != "equal"
            ],
        })
    helper.write_json(args.run_dir / "asr-screening.json", {
        "schemaVersion": "sermon-layer3-qwen-voxcpm2-long-ab-asr-screen-v1",
        "model": "Qwen/Qwen3-ASR-0.6B", "revision": args.revision,
        "results": results, "productionEligible": False, "humanApproval": False,
    })
    for row in results:
        print(f'{row["engine"]}: {row["normalizedSimilarity"]:.6f}')


if __name__ == "__main__":
    main()
