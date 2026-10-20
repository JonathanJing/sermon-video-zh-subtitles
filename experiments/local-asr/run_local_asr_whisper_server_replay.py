#!/usr/bin/env python3
"""Replay audio at 1.0x into a persistent whisper.cpp HTTP server."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import statistics
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_local_asr_benchmark import edit_distance, normalize_words, percentile

SWAP_USED_RE = re.compile(r"used = ([0-9.]+)([MG])")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def process_rss_gib(pid: int) -> float | None:
    result = subprocess.run(
        ["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True
    )
    try:
        return int(result.stdout.strip()) / (1024**2)
    except ValueError:
        return None


def swap_used_gib() -> float | None:
    result = subprocess.run(
        ["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True
    )
    match = SWAP_USED_RE.search(result.stdout)
    if not match:
        return None
    value = float(match.group(1))
    return value if match.group(2) == "G" else value / 1024


def wav_bytes(pcm: bytes, sample_rate: int = 16000) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm)
    return output.getvalue()


def transcribe(url: str, pcm: bytes) -> str:
    boundary = f"----sermon-asr-{uuid.uuid4().hex}"
    parts: list[bytes] = []
    fields = {"response_format": "json", "language": "en", "temperature": "0"}
    for name, value in fields.items():
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode()
        )
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"window.wav\"\r\nContent-Type: audio/wav\r\n\r\n".encode()
    )
    parts.append(wav_bytes(pcm))
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    body = b"".join(parts)
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = json.loads(response.read())
    return str(payload.get("text", "")).strip()


def reference_text(manifest: dict, replay_duration: float) -> str:
    spec = manifest["referenceChunks"]
    payload = json.loads((REPO_ROOT / spec["path"]).read_text())
    by_id = {int(item["id"]): item for item in payload}
    ids = [int(item_id) for item_id in spec["ids"]]
    if replay_duration < float(manifest["durationSeconds"]):
        seconds_per_chunk = float(manifest["durationSeconds"]) / len(ids)
        count = max(1, int((replay_duration + seconds_per_chunk - 1e-9) // seconds_per_chunk))
        ids = ids[:count]
    return " ".join(by_id[item_id]["text"].strip() for item_id in ids).strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--provider-pid", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--window-seconds", type=float, default=5.0)
    parser.add_argument("--partial-seconds", type=float, default=1.5)
    parser.add_argument("--max-audio-seconds", type=float)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest_path = args.manifest.resolve()
    audio_path = args.audio.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schemaVersion") != "local-asr-streaming-replay-v1":
        raise SystemExit("Unsupported replay manifest")
    if sha256_file(audio_path) != manifest["replayWavSha256"]:
        raise SystemExit("Replay WAV SHA-256 mismatch")
    with wave.open(str(audio_path), "rb") as handle:
        if (handle.getnchannels(), handle.getsampwidth(), handle.getframerate()) != (1, 2, 16000):
            raise SystemExit("Replay input must be mono 16-bit 16 kHz PCM WAV")
        frame_count = handle.getnframes()
        pcm = handle.readframes(frame_count)
    source_duration = frame_count / 16000
    if abs(source_duration - float(manifest["durationSeconds"])) > 0.01:
        raise SystemExit("Replay duration mismatch")
    duration = source_duration if args.max_audio_seconds is None else args.max_audio_seconds
    if duration <= 0 or duration > source_duration:
        raise SystemExit("Replay duration override is invalid")
    pcm = pcm[: round(duration * 16000) * 2]

    events: list[dict] = []
    samples: list[dict] = []
    stop_sampling = threading.Event()
    started = time.monotonic()

    def sample_resources() -> None:
        while not stop_sampling.is_set():
            samples.append(
                {
                    "wallSeconds": round(time.monotonic() - started, 4),
                    "providerRssGiB": process_rss_gib(args.provider_pid),
                    "swapUsedGiB": swap_used_gib(),
                }
            )
            stop_sampling.wait(1)

    sampler = threading.Thread(target=sample_resources, daemon=True)
    sampler.start()
    bytes_per_second = 16000 * 2
    block_count = int((duration + args.window_seconds - 1e-9) // args.window_seconds)
    for block_index in range(block_count):
        block_start = block_index * args.window_seconds
        block_end = min(duration, block_start + args.window_seconds)
        for is_partial, available_end in (
            (True, min(block_end, block_start + args.partial_seconds)),
            (False, block_end),
        ):
            if not is_partial and available_end <= block_start + args.partial_seconds:
                continue
            scheduled = started + available_end
            time.sleep(max(0, scheduled - time.monotonic()))
            request_started = time.monotonic()
            start_byte = round(block_start * bytes_per_second)
            end_byte = round(available_end * bytes_per_second)
            text = transcribe(args.url, pcm[start_byte:end_byte])
            received = time.monotonic()
            events.append(
                {
                    "eventIndex": len(events),
                    "windowIndex": block_index,
                    "audioAvailableSeconds": round(available_end, 3),
                    "receivedWallSeconds": round(received - started, 4),
                    "isPartial": is_partial,
                    "isFinal": not is_partial,
                    "text": text,
                    "requestDurationSeconds": round(received - request_started, 4),
                    "deliveryLagAfterAudioAvailableSeconds": round(received - scheduled, 4),
                }
            )
        if (block_index + 1) % 6 == 0:
            print(
                json.dumps(
                    {
                        "status": "replaying",
                        "audioSentSeconds": round(block_end, 1),
                        "targetSeconds": round(duration, 1),
                        "eventCount": len(events),
                    }
                ),
                flush=True,
            )
    completed = time.monotonic()
    stop_sampling.set()
    sampler.join(timeout=2)

    final_events = [row for row in events if row["isFinal"]]
    partial_events = [row for row in events if row["isPartial"]]
    final_text = " ".join(row["text"] for row in final_events if row["text"])
    ref_words = normalize_words(reference_text(manifest, duration))
    hyp_words = normalize_words(final_text)
    churn = 0
    partial_by_window = {row["windowIndex"]: row for row in partial_events}
    for row in final_events:
        partial = partial_by_window.get(row["windowIndex"])
        if partial:
            churn += edit_distance(normalize_words(partial["text"]), normalize_words(row["text"]))
    lags = [row["deliveryLagAfterAudioAvailableSeconds"] for row in final_events]
    rss = [row["providerRssGiB"] for row in samples if row["providerRssGiB"] is not None]
    swap = [row["swapUsedGiB"] for row in samples if row["swapUsedGiB"] is not None]
    events_path = output_dir / "events.jsonl"
    resources_path = output_dir / "resources.jsonl"
    events_path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in events))
    resources_path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in samples))
    report = {
        "schemaVersion": "local-asr-streaming-replay-run-v1",
        "completedAt": datetime.now(timezone.utc).isoformat(),
        "manifest": str(manifest_path.relative_to(REPO_ROOT)),
        "manifestSha256": sha256_file(manifest_path),
        "modelId": args.model_id,
        "provider": "whisper.cpp-persistent-http-window-replay",
        "protocol": {
            "windowSeconds": args.window_seconds,
            "partialProbeSeconds": args.partial_seconds,
            "partialFinalStatus": "harness_emulated_by_retranscribing_same_window",
        },
        "audioSha256": sha256_file(audio_path),
        "audioDurationSeconds": round(duration, 3),
        "sourceAudioDurationSeconds": round(source_duration, 3),
        "formalFullDuration": abs(duration - source_duration) < 0.01,
        "wallDurationSeconds": round(completed - started, 4),
        "wallToAudioRatio": round((completed - started) / duration, 6),
        "partialEventCount": len(partial_events),
        "finalEventCount": len(final_events),
        "emptyFinalEventCount": sum(not normalize_words(row["text"]) for row in final_events),
        "partialToFinalWordEditChurn": churn,
        "finalDeliveryLagAfterAudioAvailableSeconds": {
            "p50": percentile(lags, 0.50),
            "p95": percentile(lags, 0.95),
            "max": round(max(lags), 4) if lags else None,
        },
        "quality": {
            "referenceStatus": manifest["referenceChunks"]["status"],
            "referenceWordCount": len(ref_words),
            "hypothesisWordCount": len(hyp_words),
            "wer": round(edit_distance(ref_words, hyp_words) / len(ref_words), 6),
        },
        "resources": {
            "sampleCount": len(samples),
            "providerPeakRssGiB": round(max(rss), 4) if rss else None,
            "swapUsedGiBStart": round(swap[0], 4) if swap else None,
            "swapUsedGiBEnd": round(swap[-1], 4) if swap else None,
            "swapGrowthGiB": round(swap[-1] - swap[0], 4) if swap else None,
        },
        "eventsSha256": sha256_file(events_path),
        "resourcesSha256": sha256_file(resources_path),
        "limitations": [
            "whisper.cpp HTTP has no file-stream partial protocol; partials are harness-emulated probes.",
            "Reference is exact-chunk GPT-Transcribe text, not human Gold.",
            "This run measures ASR alone, not MiLMMT co-residency.",
        ],
    }
    (output_dir / "run-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
