#!/usr/bin/env python3
"""Render one natural-rate Qwen SFT file per Layer 3 source unit."""
import argparse
import hashlib
import json
from pathlib import Path
import time


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def text_sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_plan(path):
    plan = json.loads(Path(path).read_text(encoding="utf-8"))
    if plan.get("schemaVersion") != "sermon-layer3-qwen-auk-poc-plan-v1":
        raise ValueError("unsupported plan")
    if plan.get("productionEligible") is not False or plan.get("humanApproval") is not False:
        raise ValueError("POC plan must remain non-production and non-human-approved")
    if plan.get("targetLocale") != "ko" or not plan.get("units"):
        raise ValueError("this renderer requires a non-empty Korean POC")
    for index, unit in enumerate(plan["units"]):
        if unit.get("unitIndex") != index or text_sha256(unit.get("targetText", "")) != unit.get("targetTextSha256"):
            raise ValueError(f"changed unit identity at index {index}")
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--challengers-only", action="store_true")
    args = parser.parse_args()
    plan = load_plan(args.plan)
    checkpoint_hash = sha256(args.checkpoint / "model.safetensors")
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
    identity = {
        "schemaVersion": "sermon-layer3-qwen-render-identity-v1",
        "planSha256": sha256(args.plan),
        "checkpointSha256": checkpoint_hash,
        "speakerKey": speaker,
        "language": "Korean",
        "seedPolicy": "42 plus unit index",
        "temperature": 0.7,
        "repetitionPenalty": 1.05,
        "maxNewTokens": 768,
        "ratePolicy": "natural_no_time_stretch",
        "productionEligible": False,
        "humanApproval": False,
    }
    identity_path = args.out / "identity.json"
    if identity_path.exists() and json.loads(identity_path.read_text(encoding="utf-8")) != identity:
        raise ValueError("cannot resume Qwen audio from changed inputs")
    write_json(identity_path, identity)
    model = Qwen3TTSModel.from_pretrained(
        str(args.checkpoint), device_map=args.device, dtype=torch.bfloat16, attn_implementation="sdpa"
    )
    receipts = []
    for unit in plan["units"]:
        if args.challengers_only and not unit.get("challenger"):
            continue
        stem = unit["sourceUnitId"]
        wav_path = args.out / f"{stem}.wav"
        receipt_path = args.out / f"{stem}.json"
        if receipt_path.exists():
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            if receipt.get("identity") != identity or receipt.get("unit") != unit or receipt.get("audioSha256") != sha256(wav_path):
                raise ValueError(f"stale cached Qwen unit: {stem}")
            receipts.append(receipt)
            continue
        if wav_path.exists():
            raise ValueError(f"unreceipted Qwen audio preserved: {wav_path}")
        torch.manual_seed(42 + unit["unitIndex"])
        started = time.monotonic()
        waves, rate = model.generate_custom_voice(
            text=[unit["targetText"]], language=["Korean"], speaker=[speaker],
            temperature=0.7, repetition_penalty=1.05, max_new_tokens=768,
        )
        wave = np.asarray(waves[0], dtype=np.float32).reshape(-1)
        if rate != 24000 or not np.isfinite(wave).all() or len(wave) <= rate // 4:
            raise ValueError(f"invalid Qwen waveform: {stem}")
        sf.write(wav_path, wave, rate, subtype="PCM_24")
        receipt = {
            "schemaVersion": "sermon-layer3-qwen-unit-receipt-v1",
            "identity": identity,
            "unit": unit,
            "audioSha256": sha256(wav_path),
            "sampleRate": rate,
            "durationSeconds": len(wave) / rate,
            "generationSeconds": time.monotonic() - started,
            "fullDecode": "pending_external_check",
            "humanListeningStatus": "pending",
        }
        write_json(receipt_path, receipt)
        receipts.append(receipt)
        print(json.dumps({"sourceUnitId": stem, "durationSeconds": receipt["durationSeconds"]}), flush=True)
    write_json(args.out / "manifest.json", {
        "schemaVersion": "sermon-layer3-qwen-render-manifest-v1",
        "identity": identity,
        "status": "generated_waveforms",
        "receipts": receipts,
        "productionEligible": False,
        "humanApproval": False,
    })


if __name__ == "__main__":
    main()
