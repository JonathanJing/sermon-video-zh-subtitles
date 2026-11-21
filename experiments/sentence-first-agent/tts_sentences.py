#!/usr/bin/env python3
"""Synthesize one WAV per sentence with Qwen3-TTS (experiment only).

``--batch-size`` defaults to 1; batch>1 sends several sentences per model call
(the formal renderer's batch API). Batch>1 changes the sound identity of the
members, so a later single-sentence repair re-synthesizes its batch window.

Runs on the machine that holds the checkpoint and ``qwen_tts``. 2026-11-21: the
sentence-first line renders on the 14-inch M5 Max laptop (``--device mps``,
``--dtype float32``, one model copy); the DGX Spark path (``--device cuda:0``,
bfloat16, one model copy per job inside ``spark_run.sh``) stays available but is
no longer the default. Reads ``speech.jsonl`` rows: id, spokenText, language,
speaker, hint. Existing ``<out>/<id>.wav`` files are skipped, so a stopped run
resumes. No time stretching, no identity binding, no cache beyond the files.

After every model call the worker returns its unused allocator blocks
(``torch.cuda.empty_cache`` on CUDA, ``torch.mps.empty_cache`` on MPS): measured
2026-10-23 on the formal 8x8 renderer, without it the caching allocator keeps
about 1 GiB more reserved per batch and a full sermon runs the host out of
memory; with it MemAvailable stays flat, the WAVs are byte-identical and the
release costs about 0.1 s per batch. Each ``tts-log.jsonl`` row records host
MemAvailable and this process's allocator counters so a run's memory curve can
be read back.

On MPS the host memory gate is on by default (``--min-available-gib 20``,
``--abort-below-gib 6``): a 36 GiB laptop has one model copy, not two, and the
admission check refuses to load the model into a host that is still carrying
browser and deploy processes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
import wave

# One 1.7B model copy at batch 8 peaked at ~11.45 GiB of MPS driver allocation
# plus ~5.7 GiB of process RSS (2026-10-28 / 2026-11-09 measurements); 20 GiB of
# free+inactive+speculative leaves margin on a 36 GiB host, and the two-copy path
# needs a 64 GiB machine, not this one.
DEFAULT_MPS_MIN_AVAILABLE_GIB = 20.0
DEFAULT_MPS_ABORT_BELOW_GIB = 6.0


def _darwin_available_bytes() -> int | None:
    """macOS free+inactive+speculative, the same definition as the two-way launcher."""
    try:
        output = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    page = re.search(r"page size of (\d+) bytes", output)
    if page is None:
        return None
    pages = {key: int(value) for key, value in re.findall(r"^([^:\n]+):\s+(\d+)\.", output, re.M)}
    total = sum(pages.get(key, 0) for key in ("Pages free", "Pages inactive", "Pages speculative"))
    return total * int(page.group(1))


def mem_available_bytes() -> int | None:
    """Host available memory: Linux ``MemAvailable``, else macOS page counts."""
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError):
        pass
    return _darwin_available_bytes()


def gib(value: int | None) -> float | None:
    return None if value is None else round(value / 2**30, 1)


def device_gate_gib(device: str, configured: float | None, fallback: float) -> float:
    """Explicit flag wins; otherwise MPS gates and CUDA stays ungated (Spark has its own admission)."""
    if configured is not None:
        return float(configured)
    return float(fallback) if device.startswith("mps") else 0.0


def checkpoint_weights_sha256(checkpoint: Path) -> str | None:
    """SHA-256 of ``model.safetensors``; None when the file is not there."""
    weights = checkpoint / "model.safetensors"
    if not weights.is_file():
        return None
    digest = hashlib.sha256()
    with weights.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def admission(device: str, min_available_gib: float) -> dict:
    available = mem_available_bytes()
    passed = None
    if min_available_gib > 0 and available is not None:
        passed = available >= int(min_available_gib * 2**30)
    return {"device": device, "availableGiB": gib(available),
            "requiredGiB": min_available_gib, "pass": passed}


def memory_fields(torch_module) -> dict:
    """Metadata for a log row: host MemAvailable and this process's allocator state."""
    fields = {"memAvailableBytes": mem_available_bytes(), "cudaAllocatedBytes": None,
              "cudaReservedBytes": None, "cudaMaxReservedBytes": None}
    cuda = getattr(torch_module, "cuda", None)
    try:
        if cuda is not None and cuda.is_available():
            fields.update(cudaAllocatedBytes=int(cuda.memory_allocated()),
                          cudaReservedBytes=int(cuda.memory_reserved()),
                          cudaMaxReservedBytes=int(cuda.max_memory_reserved()))
    except Exception:
        pass
    mps = getattr(torch_module, "mps", None)
    try:
        if mps is not None and mps.is_available():
            fields["mpsAllocatedBytes"] = int(mps.current_allocated_memory())
            try:
                fields["mpsDriverAllocatedBytes"] = int(mps.driver_allocated_memory())
            except Exception:
                fields["mpsDriverAllocatedBytes"] = None
    except Exception:
        pass
    return fields


def release_device_cache(torch_module) -> float | None:
    """Return unused allocator blocks to the active device; seconds taken, or None."""
    cuda = getattr(torch_module, "cuda", None)
    mps = getattr(torch_module, "mps", None)
    started = time.monotonic()
    if cuda is not None and cuda.is_available():
        cuda.synchronize()
        cuda.empty_cache()
        return round(time.monotonic() - started, 3)
    if mps is not None and mps.is_available():
        mps.synchronize()
        mps.empty_cache()
        return round(time.monotonic() - started, 3)
    return None


def synchronize_device(torch_module, device: str) -> None:
    """Wait for queued device work so per-batch wall time is real, not just launch time."""
    target = getattr(torch_module, "mps" if device.startswith("mps") else "cuda", None)
    try:
        if target is not None and target.is_available():
            target.synchronize()
    except Exception:
        pass


def write_wav(path: Path, samples, rate: int) -> None:
    import numpy as np
    pcm = np.clip(np.asarray(samples, dtype="float64"), -1.0, 1.0)
    pcm = (pcm * 32767).astype("<i2")
    tmp = path.with_suffix(".partial.wav")
    with wave.open(str(tmp), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm.tobytes())
    tmp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--speech", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--dtype", choices=("bfloat16", "float32"), default="bfloat16")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--max-new-tokens", type=int, default=768)
    parser.add_argument("--only-speaker", help="synthesize only rows whose speaker key is this (one checkpoint per run)")
    parser.add_argument("--batch-size", type=int, default=1, help="sentences per model call (batch>1 changes sound identity)")
    parser.add_argument("--only-ids-file", type=Path, help="process only these ids in speech order (repair a batch window)")
    parser.add_argument("--min-available-gib", type=float, default=None,
                        help="refuse to start below this much host memory (default 20 on MPS, 0 on CUDA)")
    parser.add_argument("--abort-below-gib", type=float, default=None,
                        help="stop before a batch when host memory falls below this (default 6 on MPS, 0 on CUDA)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the plan and the memory admission without loading the model")
    parser.add_argument("--expect-checkpoint-sha256",
                        help="refuse to start unless model.safetensors matches this Registry hash")
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.speech.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.only_speaker:
        rows = [row for row in rows if row["speaker"] == args.only_speaker]
        if not rows:
            raise SystemExit(f"no rows with speaker {args.only_speaker!r}")
    if args.only_ids_file:
        wanted = json.loads(args.only_ids_file.read_text(encoding="utf-8"))
        if not isinstance(wanted, list) or not all(isinstance(x, str) for x in wanted):
            raise SystemExit("--only-ids-file must be a JSON list of ids")
        unknown = sorted(set(wanted) - {row["id"] for row in rows})
        if unknown:
            raise SystemExit(f"unknown ids in --only-ids-file: {unknown[:10]}")
        rows = [row for row in rows if row["id"] in set(wanted)]
        if not rows:
            raise SystemExit("--only-ids-file selected no rows")
    checkpoint_sha = None
    if args.expect_checkpoint_sha256:
        checkpoint_sha = checkpoint_weights_sha256(args.checkpoint)
        if checkpoint_sha is None:
            raise SystemExit(f"no model.safetensors under {args.checkpoint}")
        if checkpoint_sha != args.expect_checkpoint_sha256:
            raise SystemExit(f"checkpoint weights differ: {checkpoint_sha} != {args.expect_checkpoint_sha256}")
        print(json.dumps({"checkpointSha256": checkpoint_sha}), flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    pending = [row for row in rows if not (args.out / f"{row['id']}.wav").exists()]
    min_available = device_gate_gib(args.device, args.min_available_gib, DEFAULT_MPS_MIN_AVAILABLE_GIB)
    abort_below = device_gate_gib(args.device, args.abort_below_gib, DEFAULT_MPS_ABORT_BELOW_GIB)
    gate = admission(args.device, min_available)
    batch_size = max(1, args.batch_size)
    plan = {"sentences": len(rows), "pending": len(pending),
            "batches": -(-len(pending) // batch_size), "batchSize": batch_size,
            "seed": args.seed, "device": args.device, "dtype": args.dtype,
            "checkpoint": str(args.checkpoint), "checkpointSha256": checkpoint_sha,
            "out": str(args.out), "abortBelowGiB": abort_below}
    print(json.dumps({"sentences": len(rows), "pending": len(pending)}), flush=True)
    print(json.dumps({"memoryAdmission": gate}, ensure_ascii=False), flush=True)
    refusal = (f"memory admission failed: {gate['availableGiB']} GiB available, "
               f"{min_available} GiB required on this host. Quit Chrome/deploys and retry; "
               f"do not lower --min-available-gib to force a start on a 36 GiB laptop.")
    if args.dry_run:
        print(json.dumps({"plan": plan, "admission": gate}, ensure_ascii=False), flush=True)
        if gate["pass"] is False:
            raise SystemExit(refusal)
        return 0
    if not pending:
        return 0
    if gate["pass"] is False:
        raise SystemExit(refusal)
    import torch
    from qwen_tts import Qwen3TTSModel
    model = Qwen3TTSModel.from_pretrained(
        str(args.checkpoint), device_map=args.device,
        dtype=torch.bfloat16 if args.dtype == "bfloat16" else torch.float32)
    log = (args.out / "tts-log.jsonl").open("a", encoding="utf-8")
    batch_log = (args.out / "tts-batches.jsonl").open("a", encoding="utf-8")
    for start in range(0, len(pending), batch_size):
        batch = pending[start:start + batch_size]
        if abort_below > 0:
            now = mem_available_bytes()
            if now is not None and now < int(abort_below * 2**30):
                raise SystemExit(f"host memory fell to {gib(now)} GiB (< {abort_below}); "
                                 f"stopping before the batch starting at {batch[0]['id']}. "
                                 f"Rerun to resume: existing WAVs are kept.")
        torch.manual_seed(args.seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(args.seed)
        kwargs = {"text": [row["spokenText"] for row in batch],
                  "language": [row["language"] for row in batch],
                  "speaker": [row["speaker"] for row in batch],
                  "temperature": 0.7, "repetition_penalty": 1.05, "max_new_tokens": args.max_new_tokens}
        hints = [row.get("hint") or "" for row in batch]
        if any(hints):
            kwargs["instruct"] = hints
        synchronize_device(torch, args.device)
        started = time.monotonic()
        wavs, rate = model.generate_custom_voice(**kwargs)
        synchronize_device(torch, args.device)
        wall = time.monotonic() - started
        if len(wavs) != len(batch):
            raise SystemExit(f"batch {batch[0]['id']}: TTS returned {len(wavs)} outputs for {len(batch)} rows")
        before_release = memory_fields(torch)
        release_seconds = release_device_cache(torch)
        memory = memory_fields(torch) | {"releaseSeconds": release_seconds}
        if before_release.get("cudaReservedBytes") is not None:
            memory["cudaReservedBeforeReleaseBytes"] = before_release["cudaReservedBytes"]
        if before_release.get("mpsDriverAllocatedBytes") is not None:
            memory["mpsDriverBeforeReleaseBytes"] = before_release["mpsDriverAllocatedBytes"]
        per_row = wall / len(batch)
        batch_seconds = 0.0
        for row, wav in zip(batch, wavs):
            target = args.out / f"{row['id']}.wav"
            write_wav(target, wav, rate)
            with wave.open(str(target), "rb") as handle:
                seconds = handle.getnframes() / handle.getframerate()
            batch_seconds += seconds
            entry = {"id": row["id"], "seconds": round(seconds, 3),
                     "wallSeconds": round(per_row, 3), "seed": args.seed, "batchSize": len(batch), **memory}
            log.write(json.dumps(entry, ensure_ascii=False) + "\n")
            log.flush()
            print(json.dumps(entry), flush=True)
        batch_entry = {"batchIndex": start // batch_size, "ids": [row["id"] for row in batch],
                       "seed": args.seed, "batchSize": len(batch),
                       "wallSeconds": round(wall, 3), "audioSeconds": round(batch_seconds, 3), **memory}
        batch_log.write(json.dumps(batch_entry, ensure_ascii=False) + "\n")
        batch_log.flush()
        print(json.dumps(batch_entry), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
