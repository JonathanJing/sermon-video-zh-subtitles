#!/usr/bin/env python3
"""Generate identical Chinese with the Torch Base and the research checkpoint."""
import argparse
import gc
import json
from pathlib import Path
import time

from run_qwen_training_smoke import BASE, sha256, validate_inputs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--out-name", default="chinese-probe-v2")
    parser.add_argument("--repetition-penalty", type=float, default=1.05)
    parser.add_argument("--trained-only", action="store_true", help="Reuse existing Base diagnostic; generate only the new checkpoint")
    args = parser.parse_args()
    work = args.work.resolve()
    inputs = validate_inputs(work)
    permission = json.loads((work / "authorization.json").read_text())
    if "chinese_dubbing" not in permission["purposes"]:
        raise ValueError("Chinese dubbing purpose required")
    training = json.loads((work / "training-report.json").read_text())
    checkpoint = work / "checkpoints/checkpoint-epoch-0"
    if sha256(checkpoint / "model.safetensors") != training["checkpointSha256"]:
        raise ValueError("Checkpoint changed")
    prompt = json.loads((work / "chinese-probe-input.json").read_text())
    if prompt["sourceId"] != inputs["sourceId"] or prompt["sourceSha256"] != inputs["sourceSha256"]:
        raise ValueError("Chinese probe is from a different source")
    out = (work / args.out_name).resolve()
    if not out.is_relative_to(work):
        raise ValueError("Probe outputs must stay in the run directory")
    out.mkdir(exist_ok=True)
    if (out / "report.json").exists():
        raise ValueError("Preserve the completed probe; choose a new run")
    import numpy as np
    import soundfile as sf
    import torch
    from huggingface_hub import snapshot_download
    from qwen_tts import Qwen3TTSModel
    tracks = []
    for variant in (["sft_pilot"] if args.trained_only else ["torch_base", "sft_pilot"]):
        path = snapshot_download(repo_id=BASE[0], revision=BASE[1], local_files_only=True) if variant == "torch_base" else str(checkpoint)
        model = Qwen3TTSModel.from_pretrained(path, device_map="cuda:0", dtype=torch.bfloat16, attn_implementation="sdpa")
        chunks, cues = [], []
        cursor = 0
        started = time.monotonic()
        for i, text in enumerate(prompt["units"]):
            torch.manual_seed(42)
            kwargs = {"text": text, "language": "Chinese", "temperature": 0.7, "repetition_penalty": args.repetition_penalty, "max_new_tokens": 512}
            if variant == "torch_base":
                wavs, rate = model.generate_voice_clone(**kwargs, ref_audio=str(work / inputs["reference"]["file"]), ref_text=prompt["referenceText"])
            else:
                wavs, rate = model.generate_custom_voice(**kwargs, speaker=inputs.get("speakerKey", "eric_pilot"))
            wave = np.asarray(wavs[0], dtype=np.float32).reshape(-1)
            sf.write(out / f"{variant}-{i:02d}.wav", wave, rate, subtype="PCM_24")
            if not np.isfinite(wave).all() or not 0.3 < len(wave) / rate < min(41, len(text) / 1.2 + 10):
                (out / "failure.json").write_text(json.dumps({"variant": variant, "chunk": i, "seconds": len(wave) / rate, "file": f"{variant}-{i:02d}.wav", "status": "suspicious_duration_or_signal"}) + "\n")
                raise ValueError("Suspicious Chinese synthesis; diagnostic WAV preserved")
            cues.append({"start": cursor / rate, "end": (cursor + len(wave)) / rate, "text": text})
            chunks.append(wave)
            cursor += len(wave)
            if i + 1 < len(prompt["units"]):
                gap = np.zeros(round(0.18 * rate), dtype=np.float32)
                chunks.append(gap)
                cursor += len(gap)
            print(json.dumps({"variant": variant, "chunk": i + 1, "seconds": len(wave) / rate}), flush=True)
        raw = out / f"{variant}.raw.wav"
        sf.write(raw, np.concatenate(chunks), rate, subtype="PCM_24")
        tracks.append({"id": variant, "file": raw.name, "sha256": sha256(raw), "durationSeconds": cursor / rate, "generationSeconds": time.monotonic() - started, "cues": cues})
        del model
        gc.collect()
        torch.cuda.empty_cache()
    (out / "report.json").write_text(json.dumps({"status": "generated_waveforms", "comparisonScope": "single_checkpoint_generation" if args.trained_only else "paired_base_and_trained",
        "humanListeningStatus": "pending", "checkpointSha256": training["checkpointSha256"], "inputSha256": sha256(work / "chinese-probe-input.json"), "repetitionPenalty": args.repetition_penalty, "maxNewTokens": 512,
        "controlled": [] if args.trained_only else ["Chinese text", "Torch runtime", "seed", "temperature", "repetition penalty", "postprocessing"],
        "changed": [] if args.trained_only else ["learned weights", "reference conditioning becomes learned speaker slot"], "tracks": tracks}, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
