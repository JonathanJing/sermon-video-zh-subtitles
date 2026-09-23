#!/usr/bin/env python3
"""Compute cross-language WavLM speaker-similarity screens for POC audio."""
import argparse
import importlib.util
import json
from pathlib import Path


def load_helpers():
    path = Path(__file__).with_name("layer3_poc.py")
    spec = importlib.util.spec_from_file_location("layer3_auk_helpers", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--model-id", default="microsoft/wavlm-base-plus-sv")
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    helpers = load_helpers()
    plan = helpers.load_plan(args.plan)
    if helpers.sha256(args.reference) != plan["voice"]["referenceAudioSha256"]:
        raise ValueError("Eric reference audio changed")

    import librosa
    import torch
    import torch.nn.functional as functional
    from transformers import AutoFeatureExtractor, WavLMForXVector
    extractor = AutoFeatureExtractor.from_pretrained(str(args.model_path), local_files_only=True)
    model = WavLMForXVector.from_pretrained(str(args.model_path), local_files_only=True).to("cuda:0").eval()
    reference, _ = librosa.load(args.reference, sr=16000, mono=True)
    results = []
    for unit, variant, path in helpers.candidate_paths(plan, args.run_dir):
        candidate, _ = librosa.load(path, sr=16000, mono=True)
        inputs = extractor([reference, candidate], sampling_rate=16000, padding=True, return_tensors="pt")
        with torch.inference_mode():
            embeddings = model(**{key: value.to("cuda:0") for key, value in inputs.items()}).embeddings
        similarity = functional.cosine_similarity(embeddings[0:1], embeddings[1:2]).item()
        row = {
            "sourceUnitId": unit["sourceUnitId"], "variant": variant, "status": "screened",
            "audioSha256": helpers.sha256(path), "referenceAudioSha256": helpers.sha256(args.reference),
            "cosineSimilarity": similarity,
        }
        results.append(row)
        print(json.dumps({"sourceUnitId": row["sourceUnitId"], "variant": variant, "cosineSimilarity": similarity}), flush=True)
    helpers.write_json(args.run_dir / "speaker-similarity.json", {
        "schemaVersion": "sermon-layer3-qwen-auk-speaker-similarity-v1",
        "model": args.model_id, "revision": args.revision, "sampleRate": 16000,
        "warning": "Cross-language speaker embedding screen only; not human voice identity acceptance.",
        "results": results, "humanApproval": False,
    })


if __name__ == "__main__":
    main()
