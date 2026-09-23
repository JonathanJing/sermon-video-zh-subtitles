#!/usr/bin/env python3
"""Compute WavLM speaker-similarity screens for all POC candidates."""
import argparse
import importlib.util
import json
from pathlib import Path


def helpers():
    path = Path(__file__).with_name("poc.py")
    spec = importlib.util.spec_from_file_location("layer3_multimodel_helpers", path)
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
    helper = helpers()
    plan = helper.load_plan(args.plan)
    if helper.sha256(args.reference) != plan["voice"]["referenceAudioSha256"]:
        raise ValueError("Eric reference audio changed")
    import librosa
    import torch
    import torch.nn.functional as functional
    from transformers import AutoFeatureExtractor, WavLMForXVector
    extractor = AutoFeatureExtractor.from_pretrained(str(args.model_path), local_files_only=True)
    model = WavLMForXVector.from_pretrained(str(args.model_path), local_files_only=True).to("cuda:0").eval()
    reference, _ = librosa.load(args.reference, sr=16000, mono=True)
    results = []
    for spec in helper.candidate_specs(plan, args.run_dir):
        candidate, _ = librosa.load(spec["path"], sr=16000, mono=True)
        inputs = extractor([reference, candidate], sampling_rate=16000, padding=True, return_tensors="pt")
        with torch.inference_mode():
            embeddings = model(**{key: value.to("cuda:0") for key, value in inputs.items()}).embeddings
        similarity = functional.cosine_similarity(embeddings[0:1], embeddings[1:2]).item()
        row = {
            "sampleId": spec["sampleId"], "variant": spec["variant"], "targetLocale": spec["targetLocale"],
            "status": "screened", "audioSha256": helper.sha256(spec["path"]),
            "referenceAudioSha256": helper.sha256(args.reference), "cosineSimilarity": similarity,
        }
        results.append(row)
        print(json.dumps({"sampleId": row["sampleId"], "variant": row["variant"], "cosineSimilarity": similarity}), flush=True)
    helper.write_json(args.run_dir / "speaker-similarity.json", {
        "schemaVersion": "sermon-layer3-voxcpm2-moss-speaker-similarity-v1", "model": args.model_id,
        "revision": args.revision, "sampleRate": 16000,
        "warning": "Cross-language speaker embedding screen only; not human voice identity acceptance.",
        "results": results, "humanApproval": False,
    })


if __name__ == "__main__":
    main()
