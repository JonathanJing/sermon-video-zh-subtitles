#!/usr/bin/env python3
"""Render the two Simplified Chinese Qwen SFT baseline units."""
import argparse
import importlib.util
import json
from pathlib import Path
import time


def helpers():
    path = Path(__file__).with_name("poc.py")
    spec = importlib.util.spec_from_file_location("layer3_multimodel_helpers", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--device", default="cuda:0")
    args = parser.parse_args()
    helper = helpers()
    plan = helper.load_plan(args.plan)
    checkpoint_hash = helper.sha256(args.checkpoint / "model.safetensors")
    if checkpoint_hash != plan["voice"]["qwenCheckpointSha256"]:
        raise ValueError("Qwen checkpoint hash differs from the registered Eric checkpoint")
    config = json.loads((args.checkpoint / "config.json").read_text(encoding="utf-8"))
    speaker = plan["voice"]["qwenSpeakerKey"]
    if speaker not in config["talker_config"]["spk_id"]:
        raise ValueError("Eric speaker slot is absent from checkpoint")

    import numpy as np
    import soundfile as sf
    import torch
    from qwen_tts import Qwen3TTSModel
    args.out.mkdir(parents=True, exist_ok=True)
    model = Qwen3TTSModel.from_pretrained(
        str(args.checkpoint), device_map=args.device, dtype=torch.bfloat16, attn_implementation="sdpa"
    )
    results = []
    for index, unit in enumerate(plan["primaryUnits"]):
        torch.manual_seed(42 + index)
        started = time.monotonic()
        waves, rate = model.generate_custom_voice(
            text=[unit["targetText"]], language=[unit["language"]], speaker=[speaker],
            temperature=0.7, repetition_penalty=1.05, max_new_tokens=768,
        )
        wave = np.asarray(waves[0], dtype=np.float32).reshape(-1)
        path = args.out / f'{unit["sourceUnitId"]}.wav'
        sf.write(path, wave, rate, subtype="PCM_24")
        row = {
            "sampleId": unit["sourceUnitId"], "variant": "qwen_sft_unit",
            "audio": str(path), "audioSha256": helper.sha256(path), "sampleRate": rate,
            "durationSeconds": len(wave) / rate, "elapsedSeconds": time.monotonic() - started,
        }
        results.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    helper.write_json(args.out / "manifest.json", {
        "schemaVersion": "sermon-layer3-qwen-chinese-baseline-manifest-v1",
        "checkpointSha256": checkpoint_hash, "speakerKey": speaker, "results": results,
        "productionEligible": False, "humanApproval": False,
    })


if __name__ == "__main__":
    main()
