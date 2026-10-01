#!/usr/bin/env python3
"""Resumable MPS/CUDA rendering of a frozen weekly job using a selected checkpoint."""
import argparse
import json
import math
from pathlib import Path
import time
import sys
import threading

from run_qwen_training_smoke import sha256


def write(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def render_identity(job_path, checkpoint_hash, batch_size=4, device="cuda:0"):
    if device not in ("mps", "cuda:0"):
        raise ValueError("Unsupported render device")
    return {"executionDevice": device, "precision": "float32" if device == "mps" else "bfloat16", "jobSha256": sha256(job_path), "checkpointSha256": checkpoint_hash, "seed": 42, "seedPolicy": "42 plus fixed batch start index", "batchSize": batch_size,
        "rendererSha256": sha256(Path(__file__)),
        "cpuPipelineImplementationSha256": sha256(Path(__file__).with_name("bounded_cpu_pipeline.py")),
        "batchAdmissionPolicy": "fixed_window_missing_units_only_v1",
        "synthesisPolicyValidatorSha256": sha256(Path(__file__).with_name("sentence_synthesis_policy.py")),
        "temperature": .7, "repetitionPenalty": 1.05, "maxNewTokens": 768}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--job", type=Path, required=True)
    p.add_argument("--checkpoint", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--device", choices=["mps", "cuda:0"], default="cuda:0")
    p.add_argument("--batch-size", type=int, choices=[1, 2, 4], default=4)
    p.add_argument("--cpu-workers", type=int, choices=[0, 1, 2], default=1,
                   help="0 saves serially; 1/2 overlap bounded CPU writes with synthesis")
    p.add_argument("--cpu-queue-batches", type=int, choices=[1, 2, 3, 4], default=2)
    args = p.parse_args()
    job = json.loads(args.job.read_text())
    if job.get("schemaVersion") != "sermon-weekly-dubbing-job-v1" or not job.get("units"):
        raise ValueError("Invalid job")
    from sentence_synthesis_policy import validate_synthesis_policy
    validate_synthesis_policy(job)
    checkpoint_hash = sha256(args.checkpoint / "model.safetensors")
    if checkpoint_hash != job["voice"]["checkpointSha256"]:
        raise ValueError("Wrong speaker checkpoint")
    config = json.loads((args.checkpoint / "config.json").read_text())
    if job["voice"]["speakerKey"] not in config["talker_config"]["spk_id"]:
        raise ValueError("Wrong speaker slot")
    args.out.mkdir(parents=True, exist_ok=True)
    identity = render_identity(args.job, checkpoint_hash, args.batch_size, args.device)
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
    # Validate every existing unit before model loading can trigger fallback.
    expected = {f"unit-{i:04d}" for i in range(len(job["units"]))}
    if any(path.stem not in expected for path in args.out.glob("unit-*.*")):
        raise ValueError("Unknown cached audio unit")
    for i, unit in enumerate(job["units"]):
        gap = unit.get("gapAfterSeconds", 0)
        if type(gap) not in (int, float) or not math.isfinite(gap) or gap < 0:
            raise ValueError("Invalid unit gap")
        raw = args.out / f"unit-{i:04d}.wav"
        receipt = raw.with_suffix(".json")
        if raw.exists() and not receipt.exists():
            diagnostic_path = args.out / f"failure-{i:04d}.json"
            if diagnostic_path.exists():
                diagnostic = json.loads(diagnostic_path.read_text())
                if (diagnostic.get("unit") == i and diagnostic.get("identity") == identity
                        and diagnostic.get("wavPreserved") == raw.name
                        and diagnostic.get("audioSha256") == sha256(raw)
                        and diagnostic.get("reason") == "duration_or_signal"):
                    # A previous parallel batch can leave several diagnosed
                    # failures. Refresh the next exact failure for the bounded
                    # legacy repair loop, without admitting unknown audio.
                    write(args.out / "failure.json", diagnostic)
                    raise ValueError(f"Suspicious synthesis in unit {i}; diagnostic preserved")
            raise ValueError("Unreceipted audio preserved; inspect before retry")
        if receipt.exists():
            saved = json.loads(receipt.read_text())
            if saved["unit"] != unit or saved["identity"] != identity or saved["sha256"] != sha256(raw):
                raise ValueError("Stale cached audio unit")
    missing_indices = {i for i in range(len(job["units"]))
                       if not (args.out / f"unit-{i:04d}.json").exists()}
    try:
        import numpy as np
        import soundfile as sf
        if missing_indices:
            import torch
            from qwen_tts import Qwen3TTSModel
        if missing_indices and args.device == "mps" and not torch.backends.mps.is_available():
            write(args.out / "runtime-unavailable.json", {"device": args.device, "reason": "MPS_unavailable"})
            raise SystemExit(75)
        model = (Qwen3TTSModel.from_pretrained(str(args.checkpoint), device_map=args.device,
                 dtype=torch.float32 if args.device == "mps" else torch.bfloat16,
                 attn_implementation="sdpa") if missing_indices else None)
    except ImportError as exc:
        write(args.out / "runtime-unavailable.json", {"device": args.device, "reason": type(exc).__name__})
        raise SystemExit(75) from exc
    except RuntimeError as exc:
        if not any(word in str(exc).lower() for word in ("out of memory", "not implemented for", "not currently implemented for the mps", "mps backend", "mps device")):
            raise
        write(args.out / "runtime-unavailable.json", {"device": args.device, "reason": "model_runtime_resource_failure"})
        raise SystemExit(75) from exc

    from bounded_cpu_pipeline import BoundedCpuPipeline
    cues, cursor, rate = [], 0, 24000
    started = time.monotonic()
    synthesis_seconds = 0.0
    current_failures = []
    failure_lock = threading.Lock()

    def save_unit(i, wave, sample_rate, batch_indices):
        unit = job["units"][i]
        raw = args.out / f"unit-{i:04d}.wav"
        if raw.exists() or raw.with_suffix(".json").exists():
            raise ValueError("Refusing to overwrite a committed or unreceipted audio unit")
        if sample_rate != 24000:
            raise ValueError("Unexpected sample rate")
        sf.write(raw, wave, sample_rate, subtype="PCM_24")
        seconds = len(wave) / sample_rate
        if not np.isfinite(wave).all() or not .3 < seconds < min(61, len(unit["text"]) / 1.2 + 10):
            diagnostic = {"unit": i, "reason": "duration_or_signal",
                          "seconds": seconds, "wavPreserved": raw.name,
                          "identity": identity, "audioSha256": sha256(raw)}
            write(args.out / f"failure-{i:04d}.json", diagnostic)
            with failure_lock:
                current_failures.append(diagnostic)
            raise ValueError(f"Suspicious synthesis in unit {i}; diagnostic preserved")
        write(raw.with_suffix(".json"), {"unit": unit, "sha256": sha256(raw), "identity": identity,
              "durationSeconds": seconds, "executionDevice": args.device,
              "generationBatchUnitIndices": batch_indices})
        return i

    pipeline = BoundedCpuPipeline(workers=args.cpu_workers,
                                 max_pending=args.batch_size * args.cpu_queue_batches)
    try:
        with pipeline:
            for i in range(0, len(job["units"]), args.batch_size):
                pipeline.check()
                if sha256(args.job) != identity["jobSha256"]:
                    raise ValueError("Frozen job changed during synthesis")
                indices = [j for j in range(i, min(i + args.batch_size, len(job["units"])))
                           if j in missing_indices]
                if not indices:
                    continue
                batch = [job["units"][j] for j in indices]
                torch.manual_seed(42 + i)
                synth_started = time.monotonic()
                try:
                    wavs, rate = model.generate_custom_voice(text=[u.get("spokenText", u["text"]) for u in batch], language=["Chinese"] * len(batch), speaker=[job["voice"]["speakerKey"]] * len(batch), temperature=.7, repetition_penalty=1.05, max_new_tokens=768)
                except RuntimeError as exc:
                    if not any(word in str(exc).lower() for word in ("out of memory", "not implemented for", "not currently implemented for the mps", "mps backend", "mps device")):
                        raise
                    write(args.out / "runtime-unavailable.json", {"device": args.device, "reason": "inference_runtime_resource_failure"})
                    raise SystemExit(75) from exc
                synthesis_seconds += time.monotonic() - synth_started
                if len(wavs) != len(batch):
                    raise ValueError("Incomplete batch synthesis")
                for index, wave in zip(indices, wavs):
                    # Copy ownership before a model/runtime reuses its output buffers.
                    owned = np.asarray(wave, dtype=np.float32).reshape(-1).copy()
                    pipeline.submit(save_unit, index, owned, rate, list(indices))
    except ValueError:
        # Preserve the legacy repair entry point, deterministically selecting the
        # first invalid unit when several CPU workers found failures.
        if current_failures:
            write(args.out / "failure.json", min(current_failures, key=lambda item: item["unit"]))
        raise

    if sha256(args.job) != identity["jobSha256"]:
        raise ValueError("Frozen job changed before assembly")
    raw_track = args.out / "chinese.raw.wav"
    if raw_track.exists():
        raise ValueError("Unreceipted assembled audio preserved; inspect before retry")
    partial_track = args.out / "chinese.raw.wav.tmp"
    # Stream the final track; pending CPU writes are drained and verified first.
    with sf.SoundFile(partial_track, mode="w", samplerate=24000, channels=1,
                      subtype="PCM_24", format="WAV") as output:
        for i, unit in enumerate(job["units"]):
            raw = args.out / f"unit-{i:04d}.wav"
            receipt = raw.with_suffix(".json")
            saved = json.loads(receipt.read_text())
            if saved["unit"] != unit or saved["identity"] != identity or saved["sha256"] != sha256(raw):
                raise ValueError("Stale cached audio unit")
            wave, rate = sf.read(raw, dtype="float32")
            if rate != 24000 or wave.ndim != 1 or not np.isfinite(wave).all():
                raise ValueError("Unexpected unit audio signal or sample rate")
            if abs(saved["durationSeconds"] - len(wave) / rate) > .000001:
                raise ValueError("Unit duration differs from its receipt")
            cues.append({"unitId": i, "blockId": unit["blockId"], "start": cursor / rate,
                         "end": (cursor + len(wave)) / rate, "text": unit["text"]})
            output.write(wave)
            cursor += len(wave)
            if i + 1 < len(job["units"]):
                gap_samples = round(unit["gapAfterSeconds"] * rate)
                # Keep memory bounded even for an unusually long configured gap.
                while gap_samples:
                    size = min(gap_samples, rate)
                    output.write(np.zeros(size, dtype=np.float32))
                    cursor += size
                    gap_samples -= size
            print(json.dumps({"unit": i + 1, "total": len(job["units"]), "seconds": round(len(wave) / rate, 2)}), flush=True)
    if sha256(args.job) != identity["jobSha256"]:
        raise ValueError("Frozen job changed before completion")
    partial_track.replace(raw_track)
    write(args.out / "report.json", {**identity, "status": "complete_candidate_render", "sha256": sha256(raw_track), "durationSeconds": cursor / rate,
        "executionDevice": args.device, "generationSeconds": time.monotonic() - started,
        "synthesisSeconds": synthesis_seconds, "cpuPipeline": dict(pipeline.stats),
        "cues": cues, "humanReviewStatus": "pending", "sourceTiming": "separate_alignment_required"})


if __name__ == "__main__":
    main()
