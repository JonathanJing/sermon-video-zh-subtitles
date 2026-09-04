#!/usr/bin/env python3
"""Replay PCM WAV through the real gateway at 1x; this is not microphone/UI evidence."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import struct
import threading
import time
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import wave

from websockets.sync.client import connect


MODE = "audio_file_replay"
ORIGIN = "http://127.0.0.1:4173"
RATE = 16000
FRAME_SAMPLES = 1600
FRAME_BYTES = 3200
FAILURE_TYPES = {
    "stream.error", "storage.failed", "pipeline.failed", "asr.failed",
    "translation.failed", "translation.skipped", "audio.frame_rejected", "audio.stream_gap",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def request_json(url: str, payload: dict[str, Any] | bytes | None = None) -> dict[str, Any]:
    data = payload if isinstance(payload, bytes) else json.dumps(payload).encode() if payload is not None else None
    request = Request(url, data=data, method="POST" if data is not None else "GET", headers={
        "Content-Type": "audio/wav" if isinstance(payload, bytes) else "application/json",
        "Origin": ORIGIN,
    })
    with urlopen(request, timeout=30) as response:
        result = json.loads(response.read())
    if not isinstance(result, dict):
        raise ValueError("gateway response is not a JSON object")
    return result


def prepare_audio(source: Path, destination: Path, start: float, end: float | None,
                  duration: float | None) -> dict[str, Any]:
    for name, value in (("start", start), ("end", end), ("duration", duration)):
        if value is not None and (not math.isfinite(value) or value < 0):
            raise ValueError(f"{name} must be finite and nonnegative")
    if duration == 0:
        raise ValueError("duration must be positive")
    with wave.open(str(source), "rb") as incoming:
        if (incoming.getframerate(), incoming.getnchannels(), incoming.getsampwidth(), incoming.getcomptype()) != (RATE, 1, 2, "NONE"):
            raise ValueError("input must be an uncompressed 16000 Hz mono PCM16 WAV")
        total = incoming.getnframes()
        first = round(start * RATE)
        last = total if end is None else round(end * RATE)
        if duration is not None:
            last = min(last, first + round(duration * RATE))
        if first >= last or last > total:
            raise ValueError("source window must be nonempty and inside the WAV")
        incoming.setpos(first)
        selected = last - first
        padding = (-selected) % FRAME_SAMPLES
        pcm_digest = hashlib.sha256()
        selected_digest = hashlib.sha256()
        with destination.open("xb") as output, wave.open(output, "wb") as replay:
            replay.setnchannels(1)
            replay.setsampwidth(2)
            replay.setframerate(RATE)
            remaining = selected
            while remaining:
                amount = min(remaining, RATE * 30)
                pcm = incoming.readframes(amount)
                if len(pcm) != amount * 2:
                    raise ValueError("source WAV is truncated")
                selected_digest.update(pcm)
                pcm_digest.update(pcm)
                replay.writeframesraw(pcm)
                remaining -= amount
            silence = bytes(padding * 2)
            pcm_digest.update(silence)
            replay.writeframesraw(silence)
    return {
        "sourcePath": str(source), "sourceSha256": sha256(source),
        "sourceStartSample": first, "sourceEndSample": last,
        "sourceStartSeconds": first / RATE, "sourceEndSeconds": last / RATE,
        "selectedSampleCount": selected, "selectedPcmSha256": selected_digest.hexdigest(),
        "paddingSampleCount": padding, "frameCount": (selected + padding) // FRAME_SAMPLES,
        "durationMs": (selected + padding) * 1000 // RATE,
        "replayWavPath": str(destination), "replayWavSha256": sha256(destination),
        "replayPcmSha256": pcm_digest.hexdigest(), "sampleRateHz": RATE,
        "channels": 1, "encoding": "pcm_s16le", "frameDurationMs": 100, "playbackRate": 1,
    }


def run_replay(source: str | Path, gateway_url: str, output: str | Path, *,
               source_start_seconds: float = 0, source_end_seconds: float | None = None,
               duration_seconds: float | None = None, context_policy: str | None = None,
               stop_timeout_seconds: float = 120) -> dict[str, Any]:
    source, output = Path(source).expanduser().resolve(), Path(output).expanduser().resolve()
    gateway_url = gateway_url.rstrip("/")
    parsed = urlparse(gateway_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.path or parsed.query or parsed.fragment:
        raise ValueError("gateway must be a local http://host:port URL")
    if not math.isfinite(stop_timeout_seconds) or stop_timeout_seconds <= 0:
        raise ValueError("stop timeout must be positive")
    events_path = output.with_suffix(".events.jsonl")
    replay_path = output.with_suffix(".replay.wav")
    if len({source, output, events_path, replay_path}) != 4 or any(p.exists() for p in (output, events_path, replay_path)):
        raise ValueError("output, event log and replay WAV must be new distinct paths")
    output.parent.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "schemaVersion": 1, "mode": MODE, "status": "failed",
        "evidenceBoundary": "1x file PCM to gateway/models only; no microphone, browser or phone render validation",
        "browserRenderValidated": False, "qualityReviewStatus": "not_human_reviewed",
        "startedAt": datetime.now(timezone.utc).isoformat(), "gatewayUrl": gateway_url,
        "eventLogPath": str(events_path), "framesSent": 0, "errors": [],
    }
    session = None
    stream_started = False
    closed: dict[str, Any] | None = None
    events: list[dict[str, Any]] = []
    try:
        audio = prepare_audio(source, replay_path, source_start_seconds, source_end_seconds, duration_seconds)
        report["audio"] = audio
        health = request_json(gateway_url + "/api/health")
        if health.get("service") != "local-live-caption-gateway" or health.get("status") != "ready":
            raise ValueError("target gateway is not ready")
        active_count = health.get("liveProgress", {}).get("activeStreamCount")
        if active_count != 0:
            raise ValueError("target gateway has an active stream or unverified activity; use an isolated gateway")
        socket_url = str(health.get("liveStream", {}).get("webSocketUrl") or "")
        socket_target = urlparse(socket_url)
        if socket_target.scheme != "ws" or socket_target.hostname not in {"127.0.0.1", "localhost", "::1"} or socket_target.path != "/api/live":
            raise ValueError("gateway did not provide a local live WebSocket URL")
        policy = context_policy or str(health.get("defaultContextPolicy") or "none")
        report["runtime"] = {key: health.get(key) for key in ("asr", "ollama", "contentPack", "defaultContextPolicy", "liveStream")}
        session = request_json(gateway_url + "/api/sessions/start", {
            "mode": MODE, "captureSource": "wav_file", "audioMimeType": "audio/wav",
            "contextPolicy": policy, "sourceAudio": audio, "browserRenderValidated": False,
        })
        if session.get("status") != "recording" or any(session.get(key) for key in ("pcmFrameCount", "audioChunkCount", "eventCount")):
            raise ValueError("gateway did not create a new empty recording session")
        report["sessionId"] = session["sessionId"]
        session_url = gateway_url + "/api/sessions/" + session["sessionId"]
        # Save the complete replayable recovery WAV before model processing.
        with replay_path.open("rb") as recording:
            for sequence, chunk in enumerate(iter(lambda: recording.read(4 * 1024 * 1024), b""), 1):
                request_json(f"{session_url}/audio?sequence={sequence}", chunk)

        ready = threading.Event()
        finished = threading.Event()
        receiver_errors: list[str] = []
        with events_path.open("x", encoding="utf-8") as event_file, connect(
            socket_url, origin=ORIGIN, open_timeout=15, close_timeout=5, max_size=2 * 1024 * 1024,
        ) as socket:
            def receive() -> None:
                try:
                    for message in socket:
                        event = json.loads(message)
                        if not isinstance(event, dict):
                            raise ValueError("non-object server event")
                        events.append(event)
                        event_file.write(json.dumps(event, ensure_ascii=False) + "\n")
                        event_file.flush()
                        if event.get("type") == "stream.ready":
                            ready.set()
                        if event.get("type") == "stream.closed":
                            break
                except Exception as error:
                    receiver_errors.append(str(error))
                finally:
                    finished.set()

            reader = threading.Thread(target=receive, daemon=True)
            reader.start()
            try:
                socket.send(json.dumps({
                    "type": "stream.start", "sessionId": session["sessionId"], "contextPolicy": policy,
                    "encoding": "pcm_s16le", "sampleRateHz": RATE, "channels": 1, "frameDurationMs": 100,
                }))
                stream_started = True
                deadline = time.monotonic() + 15
                while not ready.is_set() and not finished.is_set() and time.monotonic() < deadline:
                    ready.wait(0.05)
                if not ready.is_set():
                    raise RuntimeError("stream.ready was not received")
                started = time.monotonic()
                with wave.open(str(replay_path), "rb") as replay:
                    for sequence in range(1, audio["frameCount"] + 1):
                        wait = max(0, started + sequence * 0.1 - time.monotonic())
                        if finished.wait(wait):
                            raise RuntimeError("WebSocket ended before all PCM frames were sent")
                        frame = replay.readframes(FRAME_SAMPLES)
                        socket.send(struct.pack(">I", sequence) + frame)
                        report["framesSent"] = sequence
                report["transmitElapsedMs"] = round((time.monotonic() - started) * 1000)
                socket.send(json.dumps({"type": "stream.stop"}))
                if not finished.wait(stop_timeout_seconds):
                    raise TimeoutError("stream.closed not received before drain timeout")
                if receiver_errors:
                    raise RuntimeError("server event reader failed: " + receiver_errors[0])
            finally:
                socket.close()
                reader.join(timeout=5)
                closed = next((event for event in reversed(events) if event.get("type") == "stream.closed"), None)

        failures = [event["type"] for event in events if event.get("type") in FAILURE_TYPES]
        report["errors"].extend(failures)
        drained = bool(closed and all(closed.get(key) is True for key in (
            "workerDrained", "asrWorkerDrained", "translationWorkerDrained", "storageHealthy",
        )) and closed.get("lastFrameSequence") == audio["frameCount"])
        if not drained:
            raise RuntimeError("server did not confirm complete PCM, healthy storage and worker drain")
        result = request_json(session_url + "/finalize", {
            "status": "incomplete" if failures else "completed", "durationMs": audio["durationMs"],
        })
        report["manifest"] = {key: result.get(key) for key in (
            "status", "manifestPath", "eventPath", "audioPath", "asrWavPath", "audioSha256",
            "pcmSha256", "pcmWavSha256", "pcmFrameCount", "pcmBytes", "audioBytes", "eventCount",
        )}
        checks = {
            "completed": result.get("status") == "completed", "drained": drained,
            "pcmFrameCount": result.get("pcmFrameCount") == audio["frameCount"],
            "pcmBytes": result.get("pcmBytes") == audio["frameCount"] * FRAME_BYTES,
            "recoveryHash": result.get("audioSha256") == audio["replayWavSha256"],
            "pcmHash": result.get("pcmSha256") == audio["replayPcmSha256"],
            "pcmWavHash": result.get("pcmWavSha256") == audio["replayWavSha256"],
        }
        report["checks"] = checks
        if not all(checks.values()):
            raise RuntimeError("finalized session failed completion or artifact-integrity checks")
        report["status"] = "completed"
    except Exception as error:
        report["errors"].append(f"{type(error).__name__}: {error}")
        if session and (closed is not None or not stream_started) and "manifest" not in report:
            try:
                result = request_json(gateway_url + "/api/sessions/" + session["sessionId"] + "/finalize", {
                    "status": "incomplete", "durationMs": report["framesSent"] * 100,
                })
                report["incompleteManifestPath"] = result.get("manifestPath")
            except Exception as finalize_error:
                report["errors"].append("incomplete finalization failed: " + str(finalize_error))
        elif session and closed is None:
            report["finalizeSkipped"] = "drain unconfirmed; preserve recording without racing active workers"
    finally:
        report["streamClosed"] = closed
        report["eventCounts"] = dict(Counter(event.get("type", "unknown") for event in events))
        report["captionOutputObserved"] = any(event.get("type") == "translation.final" for event in events)
        report["finishedAt"] = datetime.now(timezone.utc).isoformat()
        with output.open("x", encoding="utf-8") as report_file:
            json.dump(report, report_file, ensure_ascii=False, indent=2)
            report_file.write("\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_wav")
    parser.add_argument("--gateway-url", default="http://127.0.0.1:8766")
    parser.add_argument("--source-start-seconds", type=float, default=0)
    parser.add_argument("--source-end-seconds", type=float)
    parser.add_argument("--duration-seconds", type=float)
    parser.add_argument("--context-policy", choices=("none", "english_alignment_v1", "weekly_terms_v1", "saturday_alignment_v1"))
    parser.add_argument("--stop-timeout-seconds", type=float, default=120)
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args()
    try:
        report = run_replay(arguments.source_wav, arguments.gateway_url, arguments.output,
                            source_start_seconds=arguments.source_start_seconds,
                            source_end_seconds=arguments.source_end_seconds,
                            duration_seconds=arguments.duration_seconds,
                            context_policy=arguments.context_policy,
                            stop_timeout_seconds=arguments.stop_timeout_seconds)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(json.dumps({"mode": MODE, "status": report["status"], "sessionId": report.get("sessionId"),
                      "report": str(Path(arguments.output).resolve()), "errors": report["errors"]}, ensure_ascii=False))
    raise SystemExit(0 if report["status"] == "completed" else 1)


if __name__ == "__main__":
    main()
