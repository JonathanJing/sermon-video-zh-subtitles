#!/usr/bin/env python3
"""Resumable CUDA rendering of a frozen weekly job using a selected checkpoint."""
import argparse
import json
from pathlib import Path
import time

from run_qwen_training_smoke import sha256


def write(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def render_identity(job_path, checkpoint_hash, batch_size=4):
    return {"jobSha256": sha256(job_path), "checkpointSha256": checkpoint_hash, "seed": 42, "seedPolicy": "42 plus fixed batch start index", "batchSize": batch_size,
        "rendererSha256": sha256(Path(__file__)), "temperature": .7, "repetitionPenalty": 1.05, "maxNewTokens": 768}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--job", type=Path, required=True)
    p.add_argument("--checkpoint", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--batch-size", type=int, choices=[1, 2, 4], default=4)
    args = p.parse_args()
    job = json.loads(args.job.read_text())
    if job.get("schemaVersion") != "sermon-weekly-dubbing-job-v1" or not job.get("units"):
        raise ValueError("Invalid job")
    checkpoint_hash = sha256(args.checkpoint / "model.safetensors")
    if checkpoint_hash != job["voice"]["checkpointSha256"]:
        raise ValueError("Wrong speaker checkpoint")
    config = json.loads((args.checkpoint / "config.json").read_text())
    if job["voice"]["speakerKey"] not in config["talker_config"]["spk_id"]:
        raise ValueError("Wrong speaker slot")
    args.out.mkdir(parents=True, exist_ok=True)
    identity = render_identity(args.job, checkpoint_hash, args.batch_size)
    identity_path = args.out / "identity.json"
    if identity_path.exists() and json.loads(identity_path.read_text()) != identity:
        raise ValueError("Cannot resume audio from changed inputs/settings")
    write(identity_path, identity)
    if (args.out / "report.json").exists():
        report = json.loads((args.out / "report.json").read_text())
        if report["jobSha256"] != identity["jobSha256"] or sha256(args.out / "chinese.raw.wav") != report["sha256"]:
            raise ValueError("Completed render changed")
        print("Verified completed render; no regeneration")
        return
    import numpy as np
    import soundfile as sf
    import torch
    from qwen_tts import Qwen3TTSModel
    model = Qwen3TTSModel.from_pretrained(str(args.checkpoint), device_map="cuda:0", dtype=torch.bfloat16, attn_implementation="sdpa")
    waves, cues, cursor, rate = [], [], 0, 24000
    started = time.monotonic()
    generated = {}
    for i, unit in enumerate(job["units"]):
        if i % args.batch_size == 0:
            batch = job["units"][i:i + args.batch_size]
            missing = any(not (args.out / f"unit-{i + j:04d}.json").exists() for j in range(len(batch)))
            generated = {}
            if missing:
                for j in range(len(batch)):
                    wav = args.out / f"unit-{i + j:04d}.wav"
                    if wav.exists() and not wav.with_suffix(".json").exists():
                        raise ValueError("Unreceipted audio preserved; move it aside before retry")
                torch.manual_seed(42 + i)
                wavs, rate = model.generate_custom_voice(text=[u.get("spokenText", u["text"]) for u in batch], language=["Chinese"] * len(batch), speaker=[job["voice"]["speakerKey"]] * len(batch), temperature=.7, repetition_penalty=1.05, max_new_tokens=768)
                if len(wavs) != len(batch):
                    raise ValueError("Incomplete batch synthesis")
                generated = {i + j: np.asarray(w, dtype=np.float32).reshape(-1) for j, w in enumerate(wavs)}
        raw = args.out / f"unit-{i:04d}.wav"
        receipt = raw.with_suffix(".json")
        if receipt.exists():
            saved = json.loads(receipt.read_text())
            if saved["unit"] != unit or saved["identity"] != identity or saved["sha256"] != sha256(raw):
                raise ValueError("Stale cached audio unit")
            wave, rate = sf.read(raw, dtype="float32")
        else:
            if raw.exists():
                raise ValueError("Unreceipted audio preserved; move it aside before retry")
            wave = generated[i]
            sf.write(raw, wave, rate, subtype="PCM_24")
            seconds = len(wave) / rate
            if not np.isfinite(wave).all() or not .3 < seconds < min(61, len(unit["text"]) / 1.2 + 10):
                write(args.out / "failure.json", {"unit": i, "reason": "duration_or_signal", "seconds": seconds, "wavPreserved": raw.name})
                raise ValueError("Suspicious synthesis; diagnostic preserved")
            write(receipt, {"unit": unit, "sha256": sha256(raw), "identity": identity, "durationSeconds": seconds})
        if rate != 24000:
            raise ValueError("Unexpected sample rate")
        cues.append({"unitId": i, "blockId": unit["blockId"], "start": cursor / rate, "end": (cursor + len(wave)) / rate, "text": unit["text"]})
        waves.append(wave)
        cursor += len(wave)
        if i + 1 < len(job["units"]):
            gap = np.zeros(round(unit["gapAfterSeconds"] * rate), dtype=np.float32)
            waves.append(gap)
            cursor += len(gap)
        print(json.dumps({"unit": i + 1, "total": len(job["units"]), "seconds": round(len(wave) / rate, 2)}), flush=True)
    raw = args.out / "chinese.raw.wav"
    sf.write(raw, np.concatenate(waves), rate, subtype="PCM_24")
    write(args.out / "report.json", {**identity, "status": "complete_candidate_render", "sha256": sha256(raw), "durationSeconds": cursor / rate,
        "generationSeconds": time.monotonic() - started, "cues": cues, "humanReviewStatus": "pending", "sourceTiming": "separate_alignment_required"})


if __name__ == "__main__":
    main()
