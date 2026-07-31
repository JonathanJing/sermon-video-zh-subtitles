#!/usr/bin/env python3
"""Build a coarse full-audio timeline before cutting the sermon window."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.cloud import access_secret  # noqa: E402
from scripts import sermon_pipeline  # noqa: E402


START_PATTERNS = [
    r"\bwelcome to mariners online\b",
    r"\bmy name is\b",
    r"\bif you have your bible\b",
    r"\bturn (with me )?(in your bible|to)\b",
    r"\btoday we (are|re) (in|looking at|studying)\b",
    r"\bwe (are|re) going to be in\b",
    r"\bthe title of (today'?s|this) message\b",
    r"\bwe continue (our )?series\b",
    r"\bnumbers chapter\b",
    r"\bjohn chapter\b",
]

START_BOOST_PATTERNS = [
    r"\bmy name is steve\b",
    r"\bmy name is steve bang lee\b",
    r"\bone of the pastors\b",
]

START_PENALTY_PATTERNS = [
    r"\bjeremy robertson\b",
    r"\blead pastor\b",
    r"\bserve as (the )?.{0,40}pastor\b",
    r"\byorba linda\b",
    r"\bsouthern california\b",
    r"\bi'?d love to invite you\b",
    r"\bjoin me at mariners\b",
    r"\byou can learn more\b",
    r"\bcourse created by\b",
    r"\bdeep dive\b",
    r"\bwomen'?s discipleship pastor\b",
    r"\bmother'?s day\b",
    r"\bblessings? (unto|on|for) moms?\b",
]

END_PATTERNS = [
    r"\blet'?s pray\b",
    r"\bwould you pray with me\b",
    r"\blet'?s sing\b",
    r"\blet'?s respond\b",
    r"\bas we respond\b",
    r"\bamen\b",
    r"\bif you need prayer\b",
    r"\bthank you for joining\b",
]

STRONG_END_PATTERNS = [
    r"\blet'?s sing\b",
    r"\blet'?s respond\b",
    r"\bas we respond\b",
    r"\bwould you pray with me\b",
]

RESPONSE_SONG_PATTERNS = [
    r"\ball my life\b",
    r"\bgoodness of god\b",
    r"\boh there'?s nothing better than you\b",
    r"\bisn'?t he glorious\b",
    r"\bholy, holy\b",
    r"\byou are worthy\b",
    r"\bworthy of it all\b",
    r"\bthe god of the valley\b",
    r"\blet me see jesus\b",
]

NON_SERMON_PATTERNS = [
    r"\b(worship|sing|song|lyrics?)\b",
    r"\bannouncements?\b",
    r"\bhost\b",
    r"\bwelcome to church\b",
    r"\bwe'?re so glad you'?re here\b",
    r"\bcampus\b",
]

TIMELINE_TRANSCRIPTION_PROMPT_VERSION = "post-live-timeline-gpt-transcribe-v1"
TIMELINE_TRANSCRIPTION_PROMPT = (
    "English Mariners Church service audio. Produce a faithful rough transcript for locating the sermon. "
    "Preserve speaker introductions, Bible references, sermon titles, prayer transitions, closing-response "
    "language, and the first words of songs after the message."
)
TIMELINE_TRANSCRIPTION_KEYWORDS = [
    "Mariners Church",
    "Mariners Online",
    "Bible",
    "Jesus",
    "Holy Spirit",
    "let's pray",
    "would you pray with me",
    "let's respond",
]


def main() -> int:
    args = parse_args()
    report = build_post_live_timeline(args)
    out = resolve_repo_path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Full downloaded audio file.")
    parser.add_argument("--out", type=Path, default=Path("artifacts/post-live-timeline/report.json"))
    parser.add_argument("--outdir", type=Path, default=Path("artifacts/post-live-timeline"))
    parser.add_argument("--chunk-seconds", type=float, default=120.0)
    parser.add_argument("--model", default="gpt-transcribe")
    parser.add_argument("--api-key-secret", help="Secret Manager resource for OPENAI_API_KEY.")
    parser.add_argument(
        "--transcript-json",
        type=Path,
        help="Use a saved timeline chunk JSON file instead of calling OpenAI. Useful for audit/tests.",
    )
    parser.add_argument("--start-buffer-seconds", type=float, default=30.0)
    parser.add_argument("--end-buffer-seconds", type=float, default=45.0)
    return parser.parse_args()


def build_post_live_timeline(args: argparse.Namespace) -> dict[str, Any]:
    source = resolve_repo_path(args.input)
    outdir = resolve_repo_path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    if args.transcript_json:
        chunks = normalize_chunks(read_json(resolve_repo_path(args.transcript_json)))
    else:
        api_key = resolve_api_key(args.api_key_secret)
        chunks = transcribe_full_audio_chunks(
            api_key=api_key,
            source=source,
            outdir=outdir,
            chunk_seconds=args.chunk_seconds,
            model=args.model,
        )
    timeline_path = outdir / "timeline_chunks.json"
    write_json(timeline_path, chunks)
    analysis = analyze_timeline(
        chunks,
        start_buffer_seconds=args.start_buffer_seconds,
        end_buffer_seconds=args.end_buffer_seconds,
    )
    return {
        "schemaVersion": 1,
        "status": "requires_operator_review",
        "stage": "timeline_probed",
        "input": display_path(source),
        "timelineChunks": display_path(timeline_path),
        "chunkCount": len(chunks),
        "chunkSeconds": args.chunk_seconds,
        "model": args.model if not args.transcript_json else "provided-transcript-json",
        "transcriptionContext": {
            "promptVersion": TIMELINE_TRANSCRIPTION_PROMPT_VERSION,
            "languages": ["en"],
            "keywordCount": len(TIMELINE_TRANSCRIPTION_KEYWORDS),
        },
        "analysis": analysis,
        "nextAction": "Review suggestedWindow and run sermon_pipeline.py only after confirming local start/end.",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def transcribe_full_audio_chunks(
    *,
    api_key: str,
    source: Path,
    outdir: Path,
    chunk_seconds: float,
    model: str,
) -> list[dict[str, Any]]:
    duration = sermon_pipeline.ffprobe_duration(source)
    chunks_dir = outdir / "chunks"
    chunks: list[dict[str, Any]] = []
    count = int((duration + chunk_seconds - 0.001) // chunk_seconds)
    prompt = TIMELINE_TRANSCRIPTION_PROMPT
    keywords = TIMELINE_TRANSCRIPTION_KEYWORDS
    languages = ["en"]
    for index in range(count):
        start = index * chunk_seconds
        length = min(chunk_seconds, duration - start)
        if length <= 0:
            continue
        audio_path = chunks_dir / f"timeline_chunk_{index:04d}.m4a"
        result_path = chunks_dir / f"timeline_chunk_{index:04d}.json"
        metadata_path = chunks_dir / f"timeline_chunk_{index:04d}.request.json"
        sermon_pipeline.cut_chunk(source, audio_path, start, length)
        identity = sermon_pipeline.transcription_cache_identity(
            model=model,
            response_format="json",
            prompt=prompt,
            keywords=keywords,
            languages=languages,
            audio_path=audio_path,
            start=round(start, 3),
            end=round(start + length, 3),
        )
        result = sermon_pipeline.read_transcription_cache(result_path, metadata_path, identity)
        if result is None:
            try:
                result = sermon_pipeline.transcribe_openai_audio(
                    api_key,
                    model,
                    prompt,
                    audio_path,
                    keywords=keywords,
                    languages=languages,
                )
            except RuntimeError as exc:
                if "Audio file might be corrupted or unsupported" not in str(exc):
                    raise
                fallback_audio = audio_path.with_suffix(".wav")
                sermon_pipeline.reencode_transcription_fallback(audio_path, fallback_audio)
                identity = sermon_pipeline.transcription_cache_identity(
                    model=model,
                    response_format="json",
                    prompt=prompt,
                    keywords=keywords,
                    languages=languages,
                    audio_path=fallback_audio,
                    start=round(start, 3),
                    end=round(start + length, 3),
                )
                result = sermon_pipeline.transcribe_openai_audio(
                    api_key,
                    model,
                    prompt,
                    fallback_audio,
                    keywords=keywords,
                    languages=languages,
                )
            sermon_pipeline.write_transcription_cache(
                result_path,
                metadata_path,
                result,
                identity,
            )
        chunks.append(
            {
                "id": index,
                "start": round(start, 3),
                "end": round(start + length, 3),
                "duration": round(length, 3),
                "text": sermon_pipeline.clean_text(result.get("text", "")),
                "detectedLanguages": result.get("languages", []),
            }
        )
        print(f"timeline chunk {index + 1}/{count}", flush=True)
    return chunks


def analyze_timeline(
    chunks: list[dict[str, Any]],
    *,
    start_buffer_seconds: float,
    end_buffer_seconds: float,
) -> dict[str, Any]:
    scored = [score_chunk(chunk) for chunk in chunks]
    start_candidates = [item for item in scored if item["startScore"] > 0]
    end_candidates = [item for item in scored if item["endScore"] > 0]
    strongest_start = max(start_candidates, key=lambda item: (item["startScore"], -item["start"])) if start_candidates else None
    strongest_end = choose_end_marker(scored, end_candidates, strongest_start)
    suggested_window = None
    if strongest_start and strongest_end and strongest_end["end"] > strongest_start["start"]:
        end_anchor = strongest_end["start"] if strongest_end.get("endMarkerKind") == "response_song" else strongest_end["end"]
        suggested_window = {
            "startSeconds": max(0.0, round(strongest_start["start"] - start_buffer_seconds, 3)),
            "endSeconds": round(end_anchor + end_buffer_seconds, 3),
            "startTimecode": seconds_timecode(max(0.0, strongest_start["start"] - start_buffer_seconds)),
            "endTimecode": seconds_timecode(end_anchor + end_buffer_seconds),
            "confidence": "candidate_requires_review",
            "endMarkerKind": strongest_end.get("endMarkerKind"),
        }
    return {
        "suggestedWindow": suggested_window,
        "startCandidates": start_candidates[:8],
        "endCandidates": end_candidates[-8:],
        "responseSongCandidates": [item for item in scored if item["responseSongScore"] > 0][:8],
        "nonSermonEvidence": [item for item in scored if item["nonSermonScore"] > 0][:8],
    }


def choose_end_marker(
    scored: list[dict[str, Any]],
    end_candidates: list[dict[str, Any]],
    strongest_start: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not strongest_start:
        return None
    minimum_end_start = float(strongest_start.get("start") or 0) + 600.0
    strong_explicit = [
        {**item, "endMarkerKind": "explicit_transition"}
        for item in end_candidates
        if float(item.get("start") or 0) >= minimum_end_start and item.get("strongEndScore", 0) > 0
    ]
    response_song = [
        {**item, "endMarkerKind": "response_song"}
        for item in scored
        if float(item.get("start") or 0) >= minimum_end_start and item.get("responseSongScore", 0) > 0
    ]
    if strong_explicit and response_song:
        return min([*strong_explicit, *response_song], key=lambda item: float(item.get("start") or 0))
    if strong_explicit:
        return min(strong_explicit, key=lambda item: float(item.get("start") or 0))
    if response_song:
        return min(response_song, key=lambda item: float(item.get("start") or 0))
    later_end_candidates = [
        {**item, "endMarkerKind": "weak_end_phrase"}
        for item in end_candidates
        if float(item.get("start") or 0) >= minimum_end_start
    ]
    if later_end_candidates:
        return max(later_end_candidates, key=lambda item: (item.get("endScore", 0), float(item.get("end") or 0)))
    return None


def score_chunk(chunk: dict[str, Any]) -> dict[str, Any]:
    text = str(chunk.get("text") or "")
    lower = text.lower()
    start_hits = pattern_hits(lower, START_PATTERNS)
    start_boost_hits = pattern_hits(lower, START_BOOST_PATTERNS)
    start_penalty_hits = pattern_hits(lower, START_PENALTY_PATTERNS)
    end_hits = pattern_hits(lower, END_PATTERNS)
    strong_end_hits = pattern_hits(lower, STRONG_END_PATTERNS)
    response_song_hits = pattern_hits(lower, RESPONSE_SONG_PATTERNS)
    non_sermon_hits = pattern_hits(lower, NON_SERMON_PATTERNS)
    start_score = len(start_hits) + (2 * len(start_boost_hits)) - (2 * len(start_penalty_hits)) - len(end_hits)
    return {
        "id": chunk.get("id"),
        "start": chunk.get("start"),
        "end": chunk.get("end"),
        "startTimecode": seconds_timecode(float(chunk.get("start") or 0)),
        "endTimecode": seconds_timecode(float(chunk.get("end") or 0)),
        "startScore": max(0, start_score),
        "endScore": len(end_hits),
        "strongEndScore": len(strong_end_hits),
        "responseSongScore": len(response_song_hits),
        "nonSermonScore": len(non_sermon_hits),
        "startHits": start_hits,
        "startBoostHits": start_boost_hits,
        "startPenaltyHits": start_penalty_hits,
        "endHits": end_hits,
        "strongEndHits": strong_end_hits,
        "responseSongHits": response_song_hits,
        "nonSermonHits": non_sermon_hits,
        "excerpt": excerpt(text),
    }


def pattern_hits(text: str, patterns: list[str]) -> list[str]:
    return [pattern for pattern in patterns if re.search(pattern, text, flags=re.IGNORECASE)]


def excerpt(text: str, limit: int = 220) -> str:
    cleaned = sermon_pipeline.clean_text(text)
    return cleaned[:limit] + ("..." if len(cleaned) > limit else "")


def normalize_chunks(data: Any) -> list[dict[str, Any]]:
    items = data.get("chunks") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise SystemExit("timeline transcript JSON must be a list or an object with chunks.")
    chunks = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        start = float(item.get("start") or item.get("startSeconds") or 0)
        end = float(item.get("end") or item.get("endSeconds") or start)
        chunks.append(
            {
                "id": item.get("id", index),
                "start": round(start, 3),
                "end": round(end, 3),
                "duration": round(max(0.0, end - start), 3),
                "text": sermon_pipeline.clean_text(str(item.get("text") or "")),
            }
        )
    return chunks


def resolve_api_key(secret_name: str | None) -> str:
    if os.environ.get("OPENAI_API_KEY"):
        return str(os.environ["OPENAI_API_KEY"])
    if secret_name:
        return access_secret(secret_name)
    raise SystemExit("OPENAI_API_KEY or --api-key-secret is required unless --transcript-json is used.")


def seconds_timecode(seconds: float) -> str:
    seconds = max(0.0, seconds)
    total = int(seconds)
    millis = int(round((seconds - total) * 1000))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02}:{minutes:02}:{secs:02}.{millis:03}"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_repo_path(path: Path | str) -> Path:
    value = Path(path)
    return value if value.is_absolute() else REPO_ROOT / value


def display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(resolved)


if __name__ == "__main__":
    raise SystemExit(main())
