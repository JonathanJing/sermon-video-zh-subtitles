#!/usr/bin/env python3
"""Repair one failed, unreceipted synthesis unit without discarding other audio.

The original batch identity still binds job/model/runtime. generationOverride
records the exact changed sampling parameters; this is not a controlled A/B.
"""
import argparse
import json
from pathlib import Path
import shutil

from run_qwen_training_smoke import sha256
from render_weekly_audio import write


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--job", type=Path, required=True)
    p.add_argument("--checkpoint", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--unit", type=int, required=True)
    p.add_argument("--seed", type=int, default=142)
    args = p.parse_args()
    job = json.loads(args.job.read_text())
    identity = json.loads((args.out / "identity.json").read_text())
    if identity["jobSha256"] != sha256(args.job) or identity["checkpointSha256"] != sha256(args.checkpoint / "model.safetensors") or not 0 <= args.unit < len(job["units"]):
        raise ValueError("Wrong repair job/checkpoint/unit")
    raw = args.out / f"unit-{args.unit:04d}.wav"
    if raw.with_suffix(".json").exists():
        raise ValueError("A completed unit cannot be overwritten by failure recovery")
    failure = json.loads((args.out / "failure.json").read_text())
    if failure.get("unit") != args.unit:
        raise ValueError("Failure receipt is for a different unit")
    unit = job["units"][args.unit]
    diagnostics = args.out / "diagnostics"
    diagnostics.mkdir(exist_ok=True)
    failed_hash = sha256(raw)
    saved = diagnostics / f"{failed_hash[:16]}-{raw.name}"
    if not saved.exists():
        shutil.copyfile(raw, saved)
    write(diagnostics / (saved.stem + ".failure.json"), failure)
    candidate = diagnostics / f"retry-{args.unit:04d}-seed-{args.seed}.wav"
    if candidate.exists():
        raise ValueError("Retry already exists; inspect it or use a distinct seed")
    import numpy as np
    import soundfile as sf
    import torch
    from qwen_tts import Qwen3TTSModel
    model = Qwen3TTSModel.from_pretrained(str(args.checkpoint), device_map="cuda:0", dtype=torch.bfloat16, attn_implementation="sdpa")
    torch.manual_seed(args.seed)
    wavs, rate = model.generate_custom_voice(text=unit.get("spokenText", unit["text"]), language="Chinese", speaker=job["voice"]["speakerKey"], temperature=.7, repetition_penalty=1.1, max_new_tokens=768)
    wave = np.asarray(wavs[0], dtype=np.float32).reshape(-1)
    sf.write(candidate, wave, rate, subtype="PCM_24")
    seconds = len(wave) / rate
    if not np.isfinite(wave).all() or not .3 < seconds < min(61, len(unit["text"]) / 1.2 + 10):
        raise ValueError("Retry is also suspicious; both diagnostic WAVs preserved")
    # Original failure already copied byte-for-byte; only this unreceipted
    # candidate is replaced. All accepted/cached units are left intact.
    shutil.copyfile(candidate, raw)
    write(raw.with_suffix(".json"), {"unit": unit, "sha256": sha256(raw), "identity": identity, "durationSeconds": seconds,
        "generationOverride": {"kind": "isolated_unit_retry", "seed": args.seed, "batchSize": 1, "temperature": .7, "repetitionPenalty": 1.1, "maxNewTokens": 768,
            "scriptSha256": sha256(Path(__file__)), "failedAudioSha256": failed_hash, "failedAudioPreserved": str(saved.relative_to(args.out)), "humanReview": "pending"}})
    print(json.dumps({"repairedUnit": args.unit, "seconds": seconds, "failedAudioPreserved": True}), flush=True)


if __name__ == "__main__":
    main()
