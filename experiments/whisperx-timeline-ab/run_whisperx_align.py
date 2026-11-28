#!/usr/bin/env python3
"""Align the frozen approved English text with WhisperX.

This is the candidate timeline arm of the Layer 1 A/B test: the transcript text
stays the human-approved text, and only the word timing method changes from
OpenAI ``whisper-1`` native word timestamps to WhisperX wav2vec2 forced
alignment. The script never rewrites the reference text and never repairs a
missing word by interpolation.

Run it with the isolated WhisperX runtime:

    artifacts/whisperx-timeline-ab/runtime/bin/python \
      experiments/whisperx-timeline-ab/run_whisperx_align.py ...
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import sys
import time

import numpy as np
import whisperx

SCHEMA = "sermon-whisperx-approved-text-alignment-v1"
TOKEN_RE = re.compile(r"[a-z0-9]+(?:['’][a-z0-9]+)?", re.I)


def normalized_tokens(text: str) -> list[str]:
    return [token.lower().replace("’", "'") for token in TOKEN_RE.findall(text or "")]


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def words_from_result(result: dict) -> list[dict]:
    words = []
    for segment in result.get("segments", []):
        for word in segment.get("words", []):
            text = str(word.get("word", word.get("text", ""))).strip()
            if not text:
                continue
            words.append({
                "text": text,
                "start": float(word.get("start", 0.0)),
                "end": float(word.get("end", 0.0)),
                "score": word.get("score"),
            })
    return words


def align_one(text: str, start: float, end: float, audio: np.ndarray, model, metadata,
              device: str) -> list[dict]:
    if end <= start:
        raise ValueError("Alignment segment must have a positive duration")
    segment = {"text": text, "start": float(start), "end": float(end)}
    result = whisperx.align([segment], model, metadata, audio, device,
                            return_char_alignments=False, print_progress=False)
    return words_from_result(result)


def align_chunk(chunk: dict, unit_spans: dict[int, dict], audio: np.ndarray, model,
                metadata, device: str) -> tuple[list[dict], dict]:
    """Try padded, exact, then unit-by-unit alignment; return first exact token match."""
    # Exact first: a padded window lets a word cross the chunk boundary, which
    # creates non-monotonic starts when chunks are stitched. Padding is only a
    # fallback for an edge-clipped word that fails the exact token match.
    attempts = [
        ("chunk_exact", chunk["text"], chunk["start"], chunk["end"]),
        ("chunk_padded", chunk["text"], chunk["paddedStart"], chunk["paddedEnd"]),
    ]
    expected = normalized_tokens(chunk["text"])
    failures = []
    for label, text, start, end in attempts:
        try:
            words = align_one(text, start, end, audio, model, metadata, device)
        except Exception as exc:  # alignment failure is data, not a reason to invent times
            failures.append({"attempt": label, "error": f"{type(exc).__name__}: {exc}"})
            continue
        got = [token for word in words for token in normalized_tokens(word["text"])]
        if got == expected:
            return words, {"attempt": label, "failures": failures}
        failures.append({
            "attempt": label,
            "error": "token_sequence_mismatch",
            "expectedTokens": len(expected),
            "alignedTokens": len(got),
            "firstDifference": next(
                ({"position": i, "expected": a, "aligned": b}
                 for i, (a, b) in enumerate(zip(expected, got, strict=False)) if a != b),
                None),
        })

    # Last resort: align one approved unit at a time. Unit text is the smallest
    # frozen semantic span, and the padding keeps nearby speech from clipping
    # the first or last word.
    words, failures_by_unit = [], []
    for unit_index in range(chunk["unitStart"], chunk["unitEnd"] + 1):
        unit = unit_spans[unit_index]
        unit_expected = normalized_tokens(unit["text"])
        unit_words = None
        for label, pad in (("unit_exact", 0.0), ("unit_padded", 0.35)):
            start = max(0.0, unit["start"] - pad)
            end = unit["end"] + pad
            try:
                candidate = align_one(unit["text"], start, end, audio, model, metadata, device)
            except Exception as exc:
                failures_by_unit.append({"unitId": unit["unitId"], "attempt": label,
                                         "error": f"{type(exc).__name__}: {exc}"})
                continue
            got = [token for word in candidate for token in normalized_tokens(word["text"])]
            if got == unit_expected:
                unit_words = candidate
                break
            failures_by_unit.append({"unitId": unit["unitId"], "attempt": label,
                                     "error": "token_sequence_mismatch",
                                     "expectedTokens": len(unit_expected),
                                     "alignedTokens": len(got)})
        if unit_words is None:
            raise RuntimeError(
                f"WhisperX could not align approved text for {unit['unitId']}: "
                f"{failures_by_unit[-2:]}")
        words.extend(unit_words)
    failures.extend(failures_by_unit)
    return words, {"attempt": "unit_fallback", "failures": failures}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--language", default="en")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--chunk-id", action="append", default=[],
                        help="Only run these chunk ids (repeatable).")
    args = parser.parse_args()

    case = json.loads(args.case.read_text(encoding="utf-8"))
    chunks = case["chunks"]
    if args.chunk_id:
        wanted = set(args.chunk_id)
        chunks = [chunk for chunk in chunks if chunk["id"] in wanted]
    if args.limit:
        chunks = chunks[:args.limit]
    if not chunks:
        raise ValueError("No chunks selected")

    print(f"loading audio {args.audio}", file=sys.stderr)
    audio = whisperx.load_audio(str(args.audio))
    print(f"loading align model for {args.language}", file=sys.stderr)
    model, metadata = whisperx.load_align_model(language_code=args.language, device=args.device)
    unit_spans = {unit["unitIndex"]: unit for unit in case["units"]}

    aligned_words, chunk_runs, failures = [], [], []
    for number, chunk in enumerate(chunks, start=1):
        started = time.monotonic()
        words, run = align_chunk(chunk, unit_spans, audio, model, metadata, args.device)
        run.update({
            "chunkId": chunk["id"],
            "start": chunk["start"],
            "end": chunk["end"],
            "paddedStart": chunk["paddedStart"],
            "paddedEnd": chunk["paddedEnd"],
            "wordCount": len(words),
            "elapsedSeconds": round(time.monotonic() - started, 3),
            "words": words,
        })
        chunk_runs.append(run)
        expected = normalized_tokens(chunk["text"])
        got = [token for word in words for token in normalized_tokens(word["text"])]
        if got != expected:
            failures.append({"chunkId": chunk["id"], "error": "token_sequence_mismatch"})
            continue
        for index, word in enumerate(words):
            if not (math.isfinite(word["start"]) and math.isfinite(word["end"])):
                failures.append({"chunkId": chunk["id"], "word": word, "error": "nonfinite_time"})
                continue
            aligned_words.append({
                **word,
                "tokenIndex": chunk["tokenIndexes"][index],
                "chunkId": chunk["id"],
            })
        print(f"[{number}/{len(chunks)}] {chunk['id']} {chunk['start']:.1f}-{chunk['end']:.1f}s "
              f"{len(words)} words via {run['attempt']} ({run['elapsedSeconds']}s)", file=sys.stderr)

    payload = {
        "schemaVersion": SCHEMA,
        "status": "machine_candidate_requires_human_gold",
        "model": {
            "transcriber": "faster-whisper via WhisperX (not used here)",
            "alignmentModel": str(metadata.get("language", args.language)) + ":wav2vec2",
            "language": args.language,
            "whisperxVersion": getattr(__import__("whisperx"), "__version__", "unknown"),
        },
        "source": {
            "case": str(args.case),
            "caseSha256": __import__("hashlib").sha256(args.case.read_bytes()).hexdigest(),
            "audio": str(args.audio),
            "audioSha256": __import__("hashlib").sha256(args.audio.read_bytes()).hexdigest(),
            "audioSamples": int(audio.shape[-1]),
        },
        "chunkCount": len(chunk_runs),
        "wordCount": len(aligned_words),
        "failures": failures,
        "chunkRuns": chunk_runs,
        "words": aligned_words,
    }
    write_json(args.out / "whisperx-aligned.json", payload)
    print(json.dumps({"out": str(args.out), "chunks": len(chunk_runs),
                      "words": len(aligned_words), "failures": len(failures)},
                     ensure_ascii=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
