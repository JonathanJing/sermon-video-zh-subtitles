#!/usr/bin/env python3
"""Render one identical long Chinese passage with Qwen SFT or VoxCPM2 clone."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import time


SCHEMA = "sermon-layer3-qwen-voxcpm2-long-ab-plan-v1"


def load_module(filename, name):
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def text_sha256(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_plan(path):
    plan = json.loads(Path(path).read_text(encoding="utf-8"))
    if plan.get("schemaVersion") != SCHEMA:
        raise ValueError("unsupported long A/B plan")
    if plan.get("scope") != "layer_3_shadow_experiment":
        raise ValueError("long A/B must remain a Layer 3 shadow experiment")
    if plan.get("productionEligible") is not False or plan.get("humanApproval") is not False:
        raise ValueError("long A/B cannot be production eligible or human approved")
    passage = plan["passage"]
    if text_sha256(passage["text"]) != passage["textSha256"]:
        raise ValueError("long A/B text changed")
    return plan


def render_qwen(args, plan, helper):
    checkpoint_hash = helper.sha256(args.checkpoint / "model.safetensors")
    if checkpoint_hash != plan["voice"]["qwenCheckpointSha256"]:
        raise ValueError("Qwen checkpoint changed")
    config = json.loads((args.checkpoint / "config.json").read_text(encoding="utf-8"))
    speaker = plan["voice"]["qwenSpeakerKey"]
    if speaker not in config["talker_config"]["spk_id"]:
        raise ValueError("Eric speaker slot is absent")
    import numpy as np
    import soundfile as sf
    import torch
    from qwen_tts import Qwen3TTSModel
    torch.manual_seed(args.seed)
    model = Qwen3TTSModel.from_pretrained(
        str(args.checkpoint), device_map=args.device, dtype=torch.bfloat16, attn_implementation="sdpa"
    )
    started = time.monotonic()
    waves, rate = model.generate_custom_voice(
        text=[plan["passage"]["text"]], language=[plan["passage"]["language"]], speaker=[speaker],
        temperature=0.7, repetition_penalty=1.05, max_new_tokens=2048,
    )
    wave = np.asarray(waves[0], dtype=np.float32).reshape(-1)
    path = args.out / "qwen.wav"
    sf.write(path, wave, rate, subtype="PCM_24")
    return path, rate, len(wave) / rate, time.monotonic() - started, checkpoint_hash


def render_voxcpm2(args, plan, helper):
    if helper.sha256(args.reference) != plan["voice"]["referenceAudioSha256"]:
        raise ValueError("Eric reference audio changed")
    vox_helpers = load_module("render_voxcpm2.py", "long_ab_voxcpm2_helpers")
    audio_backend = vox_helpers.install_torchaudio_compat_if_needed()
    import numpy as np
    import soundfile as sf
    import torch
    from voxcpm import VoxCPM
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    model = VoxCPM.from_pretrained(str(args.model_path), load_denoiser=False)
    started = time.monotonic()
    wave = model.generate(
        text=plan["passage"]["text"], reference_wav_path=str(args.reference),
        cfg_value=2.0, inference_timesteps=args.timesteps,
    )
    path = args.out / "voxcpm2.wav"
    sf.write(str(path), wave, model.tts_model.sample_rate)
    duration = len(wave) / model.tts_model.sample_rate
    return path, model.tts_model.sample_rate, duration, time.monotonic() - started, audio_backend


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=["qwen", "voxcpm2"], required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--timesteps", type=int, default=10)
    args = parser.parse_args()
    plan = load_plan(args.plan)
    helper = load_module("poc.py", "long_ab_helpers")
    args.out.mkdir(parents=True, exist_ok=True)
    if args.engine == "qwen":
        if not args.checkpoint:
            parser.error("qwen requires --checkpoint")
        path, rate, duration, elapsed, runtime = render_qwen(args, plan, helper)
    else:
        if not args.model_path or not args.reference:
            parser.error("voxcpm2 requires --model-path and --reference")
        path, rate, duration, elapsed, runtime = render_voxcpm2(args, plan, helper)
    row = {
        "schemaVersion": "sermon-layer3-qwen-voxcpm2-long-ab-render-v1",
        "sampleId": plan["passage"]["sampleId"], "engine": args.engine,
        "textSha256": plan["passage"]["textSha256"], "audio": str(path),
        "audioSha256": helper.sha256(path), "sampleRate": rate,
        "durationSeconds": duration, "elapsedSeconds": elapsed,
        "seed": args.seed, "runtime": runtime,
        "productionEligible": False, "humanApproval": False,
    }
    helper.write_json(args.out / f"{args.engine}-manifest.json", row)
    print(json.dumps(row, ensure_ascii=False))


if __name__ == "__main__":
    main()
