#!/usr/bin/env python3
"""Stream frozen audio/video to Gemini Live and retain an inspectable result."""
from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import json
import os
import subprocess
import tempfile
import time
import wave
from pathlib import Path

from schema import extract_json, sha256, validate, validate_expected_modalities


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_key(env_file: Path | None = None) -> str:
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        if os.environ.get(name):
            return os.environ[name]
    if env_file is not None:
        for raw_line in env_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            name = name.removeprefix("export ").strip()
            if name in {"GEMINI_API_KEY", "GOOGLE_API_KEY"}:
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                if value:
                    return value
        raise RuntimeError("GEMINI_API_KEY or GOOGLE_API_KEY was not found in the specified env file")
    raise RuntimeError("Set GEMINI_API_KEY/GOOGLE_API_KEY or pass --env-file")


def pcm_bytes(path: Path) -> bytes:
    with wave.open(str(path), "rb") as stream:
        if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate(), stream.getcomptype()) != (1, 2, 16000, "NONE"):
            raise ValueError("Expected mono 16-bit PCM 16 kHz WAV")
        return stream.readframes(stream.getnframes())


def jsonable(value: object) -> object:
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json", exclude_none=True)
        return scrub_audio_data(dumped)
    return str(value)


def scrub_audio_data(value: object) -> object:
    if isinstance(value, list):
        return [scrub_audio_data(item) for item in value]
    if not isinstance(value, dict):
        return value
    scrubbed = {key: scrub_audio_data(item) for key, item in value.items()}
    mime_type = str(scrubbed.get("mime_type", ""))
    if mime_type.startswith("audio/") and "data" in scrubbed:
        data = scrubbed["data"]
        scrubbed["data"] = f"<audio omitted; serialized_length={len(data)}>"
    return scrubbed


async def call_model(*, key: str, model: str, prompt: str, audio: Path, video: Path,
                     duration: float) -> tuple[str, list[object]]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=key)
    raw_pcm = pcm_bytes(audio)
    chunk_bytes = 16000 * 2 // 10  # 100 ms
    with tempfile.TemporaryDirectory(prefix="omni-gemini-frames-") as directory:
        frame_pattern = str(Path(directory) / "%04d.jpg")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vf", "fps=1",
                        "-q:v", "3", frame_pattern], check=True)
        frames = sorted(Path(directory).glob("*.jpg"))
        config = {
            "response_modalities": ["AUDIO"],
            "output_audio_transcription": {},
            "thinking_config": {"thinking_level": "HIGH"},
            "media_resolution": "MEDIA_RESOLUTION_MEDIUM",
            "system_instruction": prompt,
            "realtime_input_config": {"automatic_activity_detection": {"disabled": True}},
        }
        messages: list[object] = []
        texts: list[str] = []
        async with client.aio.live.connect(model=model, config=config) as session:
            async def receive_output() -> None:
                async for response in session.receive():
                    messages.append(jsonable(response))
                    content = getattr(response, "server_content", None)
                    transcription = getattr(content, "output_transcription", None) if content else None
                    if transcription and getattr(transcription, "text", None):
                        texts.append(transcription.text)
                    elif getattr(response, "text", None):
                        texts.append(response.text)
                    turn = getattr(content, "model_turn", None) if content else None
                    if not transcription:
                        for part in getattr(turn, "parts", None) or []:
                            if getattr(part, "text", None):
                                texts.append(part.text)
                    status = (getattr(content, "interaction_status", None) if content else None)
                    status = status or getattr(response, "interaction_status", None)
                    if str(status).endswith("IDLE") and texts:
                        break
                    if content and getattr(content, "generation_complete", False) and texts:
                        try:
                            extract_json("".join(texts))
                            break
                        except (json.JSONDecodeError, TypeError):
                            pass

            receiver = asyncio.create_task(receive_output())
            await session.send_realtime_input(activity_start=types.ActivityStart())
            frame_index = 0
            for offset in range(0, len(raw_pcm), chunk_bytes):
                second = offset // (16000 * 2)
                while frame_index < len(frames) and frame_index <= second:
                    await session.send_realtime_input(
                        video=types.Blob(data=frames[frame_index].read_bytes(), mime_type="image/jpeg"))
                    frame_index += 1
                await session.send_realtime_input(
                    audio=types.Blob(data=raw_pcm[offset:offset + chunk_bytes],
                                     mime_type="audio/pcm;rate=16000"))
                await asyncio.sleep(0.1)
            await session.send_realtime_input(activity_end=types.ActivityEnd())
            try:
                async with asyncio.timeout(300):
                    await receiver
            finally:
                if not receiver.done():
                    receiver.cancel()
    return "".join(texts), messages


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="gemini-3.8-live-extended-thinking")
    parser.add_argument("--env-file", type=Path,
                        help="Read GEMINI_API_KEY from an existing env file without persisting it")
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--expected-audio-status", choices=("matched", "mismatch", "no_speech"))
    parser.add_argument("--expected-video-status", choices=("matched", "mismatch", "no_visual"))
    parser.add_argument("--expected-transcript-status",
                        choices=("matched", "partial", "mismatch", "not_provided"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    result_path = args.out / f"{args.case_id}.result.json"
    if result_path.exists():
        print(result_path)
        return
    key = resolve_key(args.env_file)
    identity = {
        "model": args.model, "caseId": args.case_id,
        "promptSha256": sha256(args.prompt), "videoSha256": sha256(args.video),
        "audioSha256": sha256(args.audio), "googleGenaiVersion": importlib.metadata.version("google-genai"),
        "apiKeyMaterialIncluded": False,
    }
    attempt_path = args.out / f"{args.case_id}.attempt.json"
    response_path = args.out / f"{args.case_id}.response.json"
    if attempt_path.exists() or response_path.exists():
        raise RuntimeError("Incomplete prior attempt exists; inspect it before retrying")
    write_json(attempt_path, {**identity, "startedUnix": time.time()})
    started = time.monotonic()
    content, raw_messages = asyncio.run(call_model(
        key=key, model=args.model, prompt=args.prompt.read_text(encoding="utf-8"),
        audio=args.audio, video=args.video, duration=args.duration))
    write_json(response_path, {"messages": raw_messages, "text": content})
    parse_error = None
    try:
        analysis = extract_json(content)
        errors = sorted(set(validate(analysis, args.duration)
                            + validate_expected_modalities(
                                analysis,
                                expected_audio_status=args.expected_audio_status,
                                expected_video_status=args.expected_video_status,
                                expected_transcript_status=args.expected_transcript_status)))
    except Exception as exc:
        analysis = None
        errors = ["invalid_json"]
        parse_error = f"{type(exc).__name__}: {exc}"
    result = {
        **identity, "latencySeconds": round(time.monotonic() - started, 3),
        "analysis": analysis, "validationErrors": errors, "parseError": parse_error,
        "reviewState": "machine_candidate_requires_review",
    }
    write_json(result_path, result)
    print(json.dumps({"result": str(result_path), "validationErrors": errors,
                      "latencySeconds": result["latencySeconds"]}))


if __name__ == "__main__":
    main()
