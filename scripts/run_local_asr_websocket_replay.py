#!/usr/bin/env python3
"""Replay PCM audio at wall-clock speed into an ASR WebSocket provider."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import statistics
import subprocess
import sys
import time
import urllib.request
import wave
from datetime import datetime, timezone
from pathlib import Path

import websockets

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


def post_json(url: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def probe_url(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return 200 <= response.status < 400
    except Exception:
        return False


def reference_text(manifest: dict, replay_duration: float) -> str:
    spec = manifest["referenceChunks"]
    payload = json.loads((REPO_ROOT / spec["path"]).read_text())
    by_id = {int(item["id"]): item for item in payload}
    ids = [int(item_id) for item_id in spec["ids"]]
    if replay_duration < float(manifest["durationSeconds"]):
        seconds_per_chunk = float(manifest["durationSeconds"]) / len(ids)
        chunk_count = max(1, int((replay_duration + seconds_per_chunk - 1e-9) // seconds_per_chunk))
        ids = ids[:chunk_count]
    if any(item_id not in by_id for item_id in ids):
        raise SystemExit("Replay reference chunk is missing")
    return " ".join(by_id[item_id]["text"].strip() for item_id in ids).strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--provider-pid", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--step-ms", type=int, default=500)
    parser.add_argument("--language", default="English")
    parser.add_argument("--drain-seconds", type=float, default=5.0)
    parser.add_argument(
        "--max-audio-seconds",
        type=float,
        help="Replay only the opening duration for a non-formal smoke run",
    )
    parser.add_argument("--translate-url")
    parser.add_argument("--translation-model-id")
    parser.add_argument("--translation-provider-pid", type=int)
    parser.add_argument("--frontend-url")
    parser.add_argument("--recording-copy", type=Path)
    return parser.parse_args()


async def main_async(args: argparse.Namespace) -> int:
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
        channels = handle.getnchannels()
        sample_width = handle.getsampwidth()
        sample_rate = handle.getframerate()
        frame_count = handle.getnframes()
        pcm = handle.readframes(frame_count)
    if (channels, sample_width, sample_rate) != (1, 2, 16000):
        raise SystemExit("Replay input must be mono 16-bit 16 kHz PCM WAV")
    source_duration = frame_count / sample_rate
    if abs(source_duration - float(manifest["durationSeconds"])) > 0.01:
        raise SystemExit("Replay duration mismatch")
    duration = source_duration
    if args.max_audio_seconds is not None:
        if args.max_audio_seconds <= 0 or args.max_audio_seconds > source_duration:
            raise SystemExit("--max-audio-seconds must be within the replay duration")
        duration = args.max_audio_seconds
        pcm = pcm[: round(duration * sample_rate) * sample_width]
    frames_per_step = round(sample_rate * args.step_ms / 1000)
    bytes_per_step = frames_per_step * sample_width

    events: list[dict] = []
    translation_events: list[dict] = []
    resource_samples: list[dict] = []
    pacing_delays: list[float] = []
    sent_audio_seconds = 0.0
    replay_started = time.monotonic()
    receiver_done = asyncio.Event()
    translation_queue: asyncio.Queue[dict | None] = asyncio.Queue(maxsize=4)
    recording_handle = None
    if args.recording_copy:
        recording_path = args.recording_copy.resolve()
        recording_path.parent.mkdir(parents=True, exist_ok=True)
        recording_handle = wave.open(str(recording_path), "wb")
        recording_handle.setnchannels(1)
        recording_handle.setsampwidth(2)
        recording_handle.setframerate(sample_rate)

    async with websockets.connect(args.url, max_size=None) as socket:
        await socket.send(
            json.dumps(
                {
                    "model": args.model,
                    "language": args.language,
                    "sample_rate": sample_rate,
                }
            )
        )
        ready = json.loads(await asyncio.wait_for(socket.recv(), timeout=120))
        if ready.get("status") != "ready":
            raise SystemExit(f"Provider did not become ready: {ready}")
        replay_started = time.monotonic()

        async def receive_events() -> None:
            nonlocal sent_audio_seconds
            try:
                while True:
                    raw = await socket.recv()
                    received = time.monotonic()
                    payload = json.loads(raw)
                    event = {
                            "eventIndex": len(events),
                            "receivedWallSeconds": round(received - replay_started, 4),
                            "audioSentSeconds": round(sent_audio_seconds, 3),
                            "deliveryLagAgainstLatestAudioSeconds": round(
                                received - replay_started - sent_audio_seconds, 4
                            ),
                            "isPartial": bool(payload.get("is_partial", False)),
                            "isFinal": not bool(payload.get("is_partial", False)),
                            "text": str(payload.get("text", "")).strip(),
                            "providerPayload": payload,
                        }
                    events.append(event)
                    if args.translate_url and event["isFinal"] and event["text"]:
                        try:
                            translation_queue.put_nowait(event)
                        except asyncio.QueueFull:
                            translation_events.append({
                                "asrEventIndex": event["eventIndex"],
                                "status": "skipped_queue_full",
                                "sourceTextEn": event["text"],
                            })
            except websockets.ConnectionClosed:
                receiver_done.set()

        async def translate_events() -> None:
            while True:
                event = await translation_queue.get()
                if event is None:
                    translation_queue.task_done()
                    return
                started = time.monotonic()
                row = {
                    "asrEventIndex": event["eventIndex"],
                    "sourceTextEn": event["text"],
                    "startedWallSeconds": round(started - replay_started, 4),
                }
                try:
                    response = await asyncio.to_thread(
                        post_json,
                        args.translate_url,
                        {"sourceTextEn": event["text"], "contextPolicy": "none"},
                    )
                    finished = time.monotonic()
                    row.update({
                        "status": "completed",
                        "targetTextZh": str(response.get("targetTextZh", "")).strip(),
                        "model": response.get("model"),
                        "promptVersion": response.get("promptVersion"),
                        "latencySeconds": round(finished - started, 4),
                        "asrFinalToTranslationFinalSeconds": round(
                            finished - replay_started - event["receivedWallSeconds"], 4
                        ),
                        "completedWallSeconds": round(finished - replay_started, 4),
                    })
                except Exception as error:
                    row.update({"status": "failed", "message": str(error)})
                translation_events.append(row)
                translation_queue.task_done()

        async def sample_resources() -> None:
            while not receiver_done.is_set():
                resource_samples.append(
                    {
                        "wallSeconds": round(time.monotonic() - replay_started, 4),
                        "providerRssGiB": process_rss_gib(args.provider_pid),
                        "translationProviderRssGiB": (
                            process_rss_gib(args.translation_provider_pid)
                            if args.translation_provider_pid else None
                        ),
                        "swapUsedGiB": swap_used_gib(),
                        "frontendHealthy": (
                            await asyncio.to_thread(probe_url, args.frontend_url)
                            if args.frontend_url else None
                        ),
                    }
                )
                await asyncio.sleep(1)

        receiver_task = asyncio.create_task(receive_events())
        translation_task = asyncio.create_task(translate_events())
        resource_task = asyncio.create_task(sample_resources())
        for index, offset in enumerate(range(0, len(pcm), bytes_per_step)):
            scheduled = replay_started + index * args.step_ms / 1000
            await asyncio.sleep(max(0, scheduled - time.monotonic()))
            send_started = time.monotonic()
            pacing_delays.append(max(0.0, send_started - scheduled))
            chunk = pcm[offset : offset + bytes_per_step]
            await socket.send(chunk)
            if recording_handle:
                recording_handle.writeframesraw(chunk)
            sent_audio_seconds += len(chunk) / sample_width / sample_rate
            progress_interval = max(1, round(30_000 / args.step_ms))
            if (index + 1) % progress_interval == 0:
                print(
                    json.dumps(
                        {
                            "status": "replaying",
                            "audioSentSeconds": round(sent_audio_seconds, 1),
                            "targetSeconds": round(duration, 1),
                            "eventCount": len(events),
                        }
                    ),
                    flush=True,
                )

        # Give endpointing a real-time silence tail, then allow responses to drain.
        silence = b"\0" * bytes_per_step
        for _ in range(2):
            await asyncio.sleep(args.step_ms / 1000)
            await socket.send(silence)
        await asyncio.sleep(args.drain_seconds)
        await translation_queue.join()
        await translation_queue.put(None)
        await translation_task
        await socket.close()
        await receiver_task
        receiver_done.set()
        await resource_task
    if recording_handle:
        recording_handle.close()

    completed = time.monotonic()
    final_events = [event for event in events if event["isFinal"]]
    partial_events = [event for event in events if event["isPartial"]]
    final_text = " ".join(event["text"] for event in final_events if event["text"])
    ref_text = reference_text(manifest, duration)
    ref_words = normalize_words(ref_text)
    hyp_words = normalize_words(final_text)
    partial_churn = 0
    previous_partial: list[str] = []
    for event in events:
        if event["isFinal"]:
            previous_partial = []
        elif event["isPartial"]:
            words = normalize_words(event["text"])
            partial_churn += edit_distance(previous_partial, words)
            previous_partial = words
    lags = [event["deliveryLagAgainstLatestAudioSeconds"] for event in final_events]
    latest_block_lags = [lag + args.step_ms / 1000 for lag in lags]
    rss_values = [
        row["providerRssGiB"]
        for row in resource_samples
        if row["providerRssGiB"] is not None
    ]
    swap_values = [
        row["swapUsedGiB"] for row in resource_samples if row["swapUsedGiB"] is not None
    ]
    translation_rss_values = [
        row["translationProviderRssGiB"]
        for row in resource_samples
        if row.get("translationProviderRssGiB") is not None
    ]
    events_path = output_dir / "events.jsonl"
    events_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in events)
    )
    resources_path = output_dir / "resources.jsonl"
    resources_path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            for row in resource_samples
        )
    )
    translations_path = output_dir / "translations.jsonl"
    translations_path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            for row in translation_events
        )
    )
    completed_translations = [
        row for row in translation_events if row.get("status") == "completed"
    ]
    translation_latencies = [row["latencySeconds"] for row in completed_translations]
    recording_matches_pcm = None
    if args.recording_copy:
        with wave.open(str(recording_path), "rb") as recorded:
            recording_matches_pcm = recorded.readframes(recorded.getnframes()) == pcm
    report = {
        "schemaVersion": "local-asr-streaming-replay-run-v1",
        "completedAt": datetime.now(timezone.utc).isoformat(),
        "manifest": str(manifest_path.relative_to(REPO_ROOT)),
        "manifestSha256": sha256_file(manifest_path),
        "modelId": args.model_id,
        "provider": "mlx-audio-realtime-websocket",
        "providerModel": args.model,
        "audioSha256": sha256_file(audio_path),
        "audioDurationSeconds": round(duration, 3),
        "sourceAudioDurationSeconds": round(source_duration, 3),
        "formalFullDuration": abs(duration - source_duration) < 0.01,
        "stepMs": args.step_ms,
        "wallDurationSeconds": round(completed - replay_started, 4),
        "wallToAudioRatio": round((completed - replay_started) / duration, 6),
        "partialEventCount": len(partial_events),
        "finalEventCount": len(final_events),
        "emptyFinalEventCount": sum(not normalize_words(row["text"]) for row in final_events),
        "partialWordEditChurn": partial_churn,
        "pacingDelaySeconds": {
            "mean": round(statistics.mean(pacing_delays), 6),
            "p95": percentile(pacing_delays, 0.95),
            "max": round(max(pacing_delays), 6),
        },
        "finalDeliveryLagAgainstLatestAudioSeconds": {
            "p50": percentile(lags, 0.50),
            "p95": percentile(lags, 0.95),
            "max": round(max(lags), 4) if lags else None,
        },
        "finalDeliveryLagAfterLatestPcmBlockAvailableSeconds": {
            "p50": percentile(latest_block_lags, 0.50),
            "p95": percentile(latest_block_lags, 0.95),
            "max": round(max(latest_block_lags), 4) if latest_block_lags else None,
        },
        "quality": {
            "referenceStatus": manifest["referenceChunks"]["status"],
            "referenceWordCount": len(ref_words),
            "hypothesisWordCount": len(hyp_words),
            "wer": round(edit_distance(ref_words, hyp_words) / len(ref_words), 6),
        },
        "resources": {
            "sampleCount": len(resource_samples),
            "providerPeakRssGiB": round(max(rss_values), 4) if rss_values else None,
            "translationProviderPeakRssGiB": (
                round(max(translation_rss_values), 4) if translation_rss_values else None
            ),
            "combinedProviderPeakRssGiB": (
                round(
                    max(
                        (row.get("providerRssGiB") or 0)
                        + (row.get("translationProviderRssGiB") or 0)
                        for row in resource_samples
                    ),
                    4,
                )
                if resource_samples else None
            ),
            "swapUsedGiBStart": round(swap_values[0], 4) if swap_values else None,
            "swapUsedGiBEnd": round(swap_values[-1], 4) if swap_values else None,
            "swapGrowthGiB": (
                round(swap_values[-1] - swap_values[0], 4) if swap_values else None
            ),
        },
        "translation": {
            "enabled": bool(args.translate_url),
            "modelId": args.translation_model_id,
            "requestCount": len(translation_events),
            "completedCount": len(completed_translations),
            "failedCount": sum(row.get("status") == "failed" for row in translation_events),
            "queueFullSkipCount": sum(
                row.get("status") == "skipped_queue_full" for row in translation_events
            ),
            "latencySeconds": {
                "p50": percentile(translation_latencies, 0.50),
                "p95": percentile(translation_latencies, 0.95),
                "max": round(max(translation_latencies), 4) if translation_latencies else None,
            },
        },
        "frontend": {
            "url": args.frontend_url,
            "probeCount": sum(row.get("frontendHealthy") is not None for row in resource_samples),
            "healthyCount": sum(row.get("frontendHealthy") is True for row in resource_samples),
        },
        "recordingCopy": (
            {
                "path": str(recording_path),
                "sha256": sha256_file(recording_path),
                "matchesReplayAudioPcm": recording_matches_pcm,
            }
            if args.recording_copy else None
        ),
        "eventsSha256": sha256_file(events_path),
        "resourcesSha256": sha256_file(resources_path),
        "translationsSha256": sha256_file(translations_path),
        "limitations": [
            "Final delivery lag is measured against the latest audio sent when the provider event arrives.",
            "The latest-PCM-block lag adds one replay step because the first PCM block is available at wall time zero.",
            "Reference is exact-chunk GPT-Transcribe text, not human Gold.",
            (
                "This run includes MiLMMT co-residency through the frozen Gateway A0 endpoint."
                if args.translate_url
                else "This run measures ASR alone, not MiLMMT co-residency."
            ),
            (
                "Frontend availability is an HTTP health probe; this run does not claim active browser microphone or MediaRecorder capture."
                if args.frontend_url
                else "No frontend availability probe was requested."
            ),
        ],
    }
    (output_dir / "run-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    return asyncio.run(main_async(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
