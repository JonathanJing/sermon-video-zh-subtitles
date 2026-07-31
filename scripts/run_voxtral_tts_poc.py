#!/usr/bin/env python3
"""Prepare and optionally run a bounded Voxtral TTS sermon proof of concept.

The OpenRouter route can only use an existing provider voice identifier. The
Mistral route can use a one-off reference clip, but requires explicit consent
confirmation because it exercises voice cloning.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


OPENROUTER_MODEL = "mistralai/voxtral-mini-tts-2603"
MISTRAL_MODEL = "voxtral-mini-tts-2603"
OPENROUTER_URL = "https://openrouter.ai/api/v1/audio/speech"
MISTRAL_URL = "https://api.mistral.ai/v1/audio/speech"
OPENROUTER_USD_PER_CHARACTER = 16 / 1_000_000


@dataclass(frozen=True)
class Cue:
    index: int
    start_ms: int
    end_ms: int
    text: str


def parse_timecode(value: str) -> int:
    match = re.fullmatch(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})", value.strip())
    if not match:
        raise ValueError(f"Invalid SRT timecode: {value!r}")
    hours, minutes, seconds, millis = (int(part) for part in match.groups())
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis


def format_timecode(value_ms: int) -> str:
    total_seconds, millis = divmod(max(0, value_ms), 1000)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def parse_srt(path: Path) -> list[Cue]:
    blocks = re.split(r"\n\s*\n", path.read_text(encoding="utf-8").strip())
    cues: list[Cue] = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 3 or " --> " not in lines[1]:
            continue
        start, end = lines[1].split(" --> ", 1)
        cues.append(
            Cue(
                index=int(lines[0]),
                start_ms=parse_timecode(start),
                end_ms=parse_timecode(end),
                text=" ".join(lines[2:]),
            )
        )
    if not cues:
        raise ValueError(f"No cues parsed from {path}")
    return cues


def select_cues(cues: list[Cue], start_ms: int, end_ms: int) -> list[Cue]:
    selected = [cue for cue in cues if cue.end_ms > start_ms and cue.start_ms < end_ms]
    if not selected:
        raise ValueError("No SRT cues overlap the requested PoC window")
    return selected


def write_relative_srt(cues: list[Cue], origin_ms: int, output: Path) -> None:
    blocks = []
    for relative_index, cue in enumerate(cues, start=1):
        start_ms = max(0, cue.start_ms - origin_ms)
        end_ms = max(start_ms + 1, cue.end_ms - origin_ms)
        blocks.append(
            f"{relative_index}\n{format_timecode(start_ms)} --> {format_timecode(end_ms)}\n{cue.text}"
        )
    output.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


def split_text(text: str, max_chars: int) -> list[str]:
    sentences = [part.strip() for part in re.split(r"(?<=[。！？；])", text) if part.strip()]
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if len(sentence) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(sentence[index : index + max_chars] for index in range(0, len(sentence), max_chars))
            continue
        candidate = current + sentence
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def run_ffmpeg_extract(source: Path, output: Path, start_seconds: float, duration_seconds: float) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            str(start_seconds),
            "-i",
            str(source),
            "-t",
            str(duration_seconds),
            "-ac",
            "1",
            "-ar",
            "24000",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "128k",
            str(output),
        ],
        check=True,
    )


def post_json(url: str, api_key: str, payload: dict) -> tuple[bytes, dict[str, str]]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "sermon-video-zh-subtitles/voxtral-poc",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return response.read(), dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"HTTP {exc.code} from {url}: {detail}") from exc


def generate_openrouter(text: str, api_key: str, voice_id: str) -> tuple[bytes, dict[str, str]]:
    return post_json(
        OPENROUTER_URL,
        api_key,
        {
            "model": OPENROUTER_MODEL,
            "input": text,
            "voice": voice_id,
            "response_format": "mp3",
        },
    )


def generate_mistral(text: str, api_key: str, reference_audio: bytes) -> tuple[bytes, dict[str, str]]:
    body, headers = post_json(
        MISTRAL_URL,
        api_key,
        {
            "model": MISTRAL_MODEL,
            "input": text,
            "ref_audio": base64.b64encode(reference_audio).decode("ascii"),
            "response_format": "mp3",
            "stream": False,
        },
    )
    parsed = json.loads(body)
    audio_data = parsed.get("audio_data")
    if not isinstance(audio_data, str) or not audio_data:
        raise RuntimeError("Mistral response did not contain audio_data")
    return base64.b64decode(audio_data), headers


def concat_mp3(parts: list[Path], output: Path) -> None:
    inputs: list[str] = []
    for part in parts:
        inputs.extend(["-i", str(part)])
    filter_inputs = "".join(f"[{index}:a]" for index in range(len(parts)))
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            *inputs,
            "-filter_complex",
            f"{filter_inputs}concat=n={len(parts)}:v=0:a=1[out]",
            "-map",
            "[out]",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "128k",
            str(output),
        ],
        check=True,
    )


def trim_mp3(source: Path, duration_seconds: float) -> None:
    trimmed = source.with_name(source.stem + ".trimmed.mp3")
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-t",
            str(duration_seconds),
            "-c:a",
            "libmp3lame",
            "-b:a",
            "128k",
            str(trimmed),
        ],
        check=True,
    )
    trimmed.replace(source)


def request_fingerprint(provider: str, voice_id: str | None, text: str, reference_sha256: str | None) -> str:
    payload = {
        "provider": provider,
        "model": OPENROUTER_MODEL if provider == "openrouter" else MISTRAL_MODEL,
        "voiceId": voice_id,
        "text": text,
        "referenceSha256": reference_sha256,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--srt", type=Path, required=True)
    parser.add_argument("--source-audio", type=Path, required=True)
    parser.add_argument("--outdir", type=Path, required=True)
    parser.add_argument("--start", default="00:01:09,100")
    parser.add_argument("--end", default="00:04:06,160")
    parser.add_argument("--reference-start", default="00:00:47,600")
    parser.add_argument("--reference-end", default="00:01:09,100")
    parser.add_argument("--max-chars-per-request", type=int, default=240)
    parser.add_argument(
        "--max-output-chunks",
        type=int,
        help="Generate only the first N prepared chunks for a bounded PoC",
    )
    parser.add_argument("--resume-existing-parts", action="store_true")
    parser.add_argument(
        "--trim-final-seconds",
        type=float,
        help="Trim the concatenated PoC at a verified sentence/silence boundary",
    )
    parser.add_argument("--provider", choices=("prepare", "openrouter", "mistral"), default="prepare")
    parser.add_argument("--voice-id", help="Existing Mistral voice ID for the OpenRouter route")
    parser.add_argument(
        "--voice-is-preset",
        action="store_true",
        help="Assert that --voice-id is a provider preset, not a cloned person's voice",
    )
    parser.add_argument("--confirm-explicit-voice-consent", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    for required in (args.srt, args.source_audio):
        if not required.is_file():
            raise SystemExit(f"Missing input file: {required}")

    start_ms = parse_timecode(args.start)
    end_ms = parse_timecode(args.end)
    reference_start_ms = parse_timecode(args.reference_start)
    reference_end_ms = parse_timecode(args.reference_end)
    if end_ms <= start_ms or reference_end_ms <= reference_start_ms:
        raise SystemExit("PoC and reference windows must have positive durations")

    args.outdir.mkdir(parents=True, exist_ok=True)
    selected = select_cues(parse_srt(args.srt), start_ms, end_ms)
    target_text = "".join(cue.text.strip() for cue in selected)
    chunks = split_text(target_text, args.max_chars_per_request)
    synthesis_chunks = chunks[: args.max_output_chunks] if args.max_output_chunks else chunks
    target_srt = args.outdir / "target.zh.relative.srt"
    target_txt = args.outdir / "target.zh.txt"
    reference_mp3 = args.outdir / "reference.en.mp3"
    write_relative_srt(selected, start_ms, target_srt)
    target_txt.write_text(target_text + "\n", encoding="utf-8")
    run_ffmpeg_extract(
        args.source_audio,
        reference_mp3,
        reference_start_ms / 1000,
        (reference_end_ms - reference_start_ms) / 1000,
    )

    manifest = {
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "model": OPENROUTER_MODEL,
        "provider": args.provider,
        "voice": {
            "id": args.voice_id,
            "type": (
                "provider_preset"
                if args.provider == "openrouter" and args.voice_is_preset
                else "reference_audio"
                if args.provider == "mistral"
                else "unspecified"
            ),
            "clonedSpeaker": args.provider == "mistral",
            "referenceAudioUploaded": args.provider == "mistral",
        },
        "sourceSrt": str(args.srt.resolve()),
        "sourceAudio": str(args.source_audio.resolve()),
        "pocWindow": {
            "start": args.start,
            "end": args.end,
            "durationSeconds": (end_ms - start_ms) / 1000,
            "cueCount": len(selected),
            "characterCount": len(target_text),
        },
        "referenceWindow": {
            "start": args.reference_start,
            "end": args.reference_end,
            "durationSeconds": (reference_end_ms - reference_start_ms) / 1000,
        },
        "requestChunks": [
            {"index": index, "characterCount": len(chunk), "text": chunk}
            for index, chunk in enumerate(chunks)
        ],
        "estimatedOpenRouterUsd": round(len(target_text) * OPENROUTER_USD_PER_CHARACTER, 6),
        "limitations": [
            "OpenRouter model metadata exposes text input only and no ref_audio parameter.",
            "Mistral's documented Voxtral TTS language list does not include Chinese as of 2026-07-19.",
            "Cross-lingual cloning must not run without the speaker's explicit consent.",
        ],
        "status": "prepared",
    }

    if args.provider != "prepare":
        manifest["synthesis"] = {
            "chunkCount": len(synthesis_chunks),
            "characterCount": sum(len(chunk) for chunk in synthesis_chunks),
            "estimatedOpenRouterUsd": round(
                sum(len(chunk) for chunk in synthesis_chunks) * OPENROUTER_USD_PER_CHARACTER,
                6,
            ),
        }
        if args.provider == "openrouter":
            api_key = os.environ.get("OPENROUTER_API_KEY", "")
            if not api_key:
                raise SystemExit("OPENROUTER_API_KEY is not set")
            if not args.voice_id:
                raise SystemExit("The OpenRouter route requires --voice-id; it cannot upload ref_audio")
            if not args.voice_is_preset and not args.confirm_explicit_voice_consent:
                raise SystemExit(
                    "A non-preset voice requires --confirm-explicit-voice-consent"
                )
            generator = lambda chunk: generate_openrouter(chunk, api_key, args.voice_id)
        else:
            if not args.confirm_explicit_voice_consent:
                raise SystemExit(
                    "Mistral ref_audio generation requires --confirm-explicit-voice-consent"
                )
            api_key = os.environ.get("MISTRAL_API_KEY", "")
            if not api_key:
                raise SystemExit("MISTRAL_API_KEY is not set")
            reference_bytes = reference_mp3.read_bytes()
            generator = lambda chunk: generate_mistral(chunk, api_key, reference_bytes)

        reference_sha256 = (
            hashlib.sha256(reference_mp3.read_bytes()).hexdigest()
            if args.provider == "mistral"
            else None
        )

        parts_dir = args.outdir / "parts"
        parts_dir.mkdir(exist_ok=True)
        parts: list[Path] = []
        generations = []
        for index, chunk in enumerate(synthesis_chunks):
            part = parts_dir / f"part_{index:03d}.mp3"
            part_meta = parts_dir / f"part_{index:03d}.json"
            fingerprint = request_fingerprint(
                args.provider, args.voice_id, chunk, reference_sha256
            )
            existing_meta = (
                json.loads(part_meta.read_text(encoding="utf-8"))
                if part_meta.is_file()
                else {}
            )
            if (
                args.resume_existing_parts
                and part.is_file()
                and part.stat().st_size > 0
                and existing_meta.get("requestFingerprint") == fingerprint
            ):
                parts.append(part)
                generations.append(
                    {
                        "index": index,
                        "bytes": part.stat().st_size,
                        "reused": True,
                        "requestFingerprint": fingerprint,
                    }
                )
                continue
            try:
                audio, headers = generator(chunk)
            except Exception as exc:
                manifest["status"] = "generation_failed"
                manifest["generations"] = generations
                manifest["error"] = str(exc)
                (args.outdir / "manifest.json").write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                print(json.dumps(manifest, ensure_ascii=False, indent=2))
                return 1
            part.write_bytes(audio)
            part_meta.write_text(
                json.dumps(
                    {
                        "requestFingerprint": fingerprint,
                        "provider": args.provider,
                        "model": OPENROUTER_MODEL,
                        "voiceId": args.voice_id,
                        "characterCount": len(chunk),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            parts.append(part)
            generations.append(
                {
                    "index": index,
                    "bytes": len(audio),
                    "generationId": headers.get("X-Generation-Id"),
                    "requestFingerprint": fingerprint,
                }
            )
        final_audio = args.outdir / "voxtral.zh.poc.mp3"
        concat_mp3(parts, final_audio)
        if args.trim_final_seconds:
            trim_mp3(final_audio, args.trim_final_seconds)
            manifest["trimFinalSeconds"] = args.trim_final_seconds
        manifest["status"] = "generated"
        manifest["generations"] = generations
        manifest["outputAudio"] = str(final_audio.resolve())

    (args.outdir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
