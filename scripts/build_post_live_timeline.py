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

NON_SERMON_PATTERNS = [
    r"\b(worship|sing|song|lyrics?)\b",
    r"\bannouncements?\b",
    r"\bhost\b",
    r"\bwelcome to church\b",
    r"\bwe'?re so glad you'?re here\b",
    r"\bcampus\b",
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
    parser.add_argument("--model", default="gpt-4o-transcribe")
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
    prompt = (
        "English church service audio. Produce rough English transcript for timeline location. "
        "Preserve speaker introductions, Bible references, and transition phrases such as let's pray or let's respond."
    )
    for index in range(count):
        start = index * chunk_seconds
        length = min(chunk_seconds, duration - start)
        if length <= 0:
            continue
        audio_path = chunks_dir / f"timeline_chunk_{index:04d}.m4a"
        result_path = chunks_dir / f"timeline_chunk_{index:04d}.json"
        sermon_pipeline.cut_chunk(source, audio_path, start, length)
        if result_path.exists():
            result = read_json(result_path)
        else:
            result = sermon_pipeline.multipart_request(
                sermon_pipeline.TRANSCRIBE_URL,
                api_key,
                {
                    "model": model,
                    "response_format": "json",
                    "language": "en",
                    "prompt": prompt,
                },
                "file",
                audio_path,
            )
            write_json(result_path, result)
        chunks.append(
            {
                "id": index,
                "start": round(start, 3),
                "end": round(start + length, 3),
                "duration": round(length, 3),
                "text": sermon_pipeline.clean_text(result.get("text", "")),
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
    strongest_end = max(end_candidates, key=lambda item: (item["endScore"], item["end"])) if end_candidates else None
    suggested_window = None
    if strongest_start and strongest_end and strongest_end["end"] > strongest_start["start"]:
        suggested_window = {
            "startSeconds": max(0.0, round(strongest_start["start"] - start_buffer_seconds, 3)),
            "endSeconds": round(strongest_end["end"] + end_buffer_seconds, 3),
            "startTimecode": seconds_timecode(max(0.0, strongest_start["start"] - start_buffer_seconds)),
            "endTimecode": seconds_timecode(strongest_end["end"] + end_buffer_seconds),
            "confidence": "candidate_requires_review",
        }
    return {
        "suggestedWindow": suggested_window,
        "startCandidates": start_candidates[:8],
        "endCandidates": end_candidates[-8:],
        "nonSermonEvidence": [item for item in scored if item["nonSermonScore"] > 0][:8],
    }


def score_chunk(chunk: dict[str, Any]) -> dict[str, Any]:
    text = str(chunk.get("text") or "")
    lower = text.lower()
    start_hits = pattern_hits(lower, START_PATTERNS)
    end_hits = pattern_hits(lower, END_PATTERNS)
    non_sermon_hits = pattern_hits(lower, NON_SERMON_PATTERNS)
    return {
        "id": chunk.get("id"),
        "start": chunk.get("start"),
        "end": chunk.get("end"),
        "startTimecode": seconds_timecode(float(chunk.get("start") or 0)),
        "endTimecode": seconds_timecode(float(chunk.get("end") or 0)),
        "startScore": len(start_hits),
        "endScore": len(end_hits),
        "nonSermonScore": len(non_sermon_hits),
        "startHits": start_hits,
        "endHits": end_hits,
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
