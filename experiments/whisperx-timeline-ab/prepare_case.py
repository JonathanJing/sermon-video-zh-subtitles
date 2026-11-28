#!/usr/bin/env python3
"""Build a frozen Layer 1 timeline case for the WhisperX versus OpenAI A/B test.

The case keeps the human-approved English unit table unchanged. It exports:

* the current production word timeline (OpenAI ``whisper-1`` word times mapped
  onto the corrected text by the historical anchor builder),
* chunked reference text suitable for independent forced alignment,
* a per-word ``timingSource`` flag so synthesized borrow-spans are not confused
  with words that kept an actual whisper timestamp.

No paid API is called; the input is an existing Layer 1 run.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys

SCHEMA = "sermon-whisperx-timeline-case-v1"
TOKEN_RE = re.compile(r"[a-z0-9]+(?:['’][a-z0-9]+)?", re.I)
NORMAL = re.compile(r"[^0-9a-z']")
AMBIGUOUS_NUMBER_RE = re.compile(r"\d[.,:/-]\d")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def normalized_tokens(text: str) -> list[str]:
    return [token.lower().replace("’", "'") for token in TOKEN_RE.findall(text or "")]


def norm_one(text: str) -> str:
    return NORMAL.sub("", str(text).lower().replace("’", "'"))


def media_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    )
    duration = float(result.stdout.strip())
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Audio must have a finite positive duration")
    return duration


def timing_sources(raw_path: Path, approved_tokens: list[str]) -> list[str]:
    """Classify every approved token as whisper-matched or synthesized by the anchor builder.

    The historical builder replaced whisper's surfaced text with the second-pass
    transcript and kept whisper times only where the two token streams matched;
    otherwise it distributed the nearest span or used a zero-length neighbor.
    """
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    whisper_tokens = [str(word.get("word", "")).strip() for word in raw.get("words", [])
                      if str(word.get("word", "")).strip()]
    a = [norm_one(text) for text in whisper_tokens]
    b = [norm_one(text) for text in approved_tokens]
    sources = ["synthetic_span"] * len(approved_tokens)
    matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for index in range(j1, j2):
                sources[index] = "whisper_match"
    return sources


def build_case(manifest: dict, duration: float, raw_whisper: Path,
               chunk_target_seconds: float, chunk_max_seconds: float,
               chunk_gap_seconds: float, mfa_every: int) -> dict:
    units_in = manifest.get("sourceUnits")
    if not isinstance(units_in, list) or not units_in:
        raise ValueError("Anchor manifest must contain sourceUnits")

    units, tokens, issues = [], [], []
    for unit_index, unit in enumerate(units_in):
        text = " ".join(str(unit.get("english", "")).split())
        surface = text.split()
        words = unit.get("words")
        if not isinstance(words, list) or not words:
            raise ValueError(f"{unit.get('sourceUnitId')}: missing word timings")
        if len(words) != len(surface):
            raise ValueError(
                f"{unit.get('sourceUnitId')}: {len(words)} timed words for {len(surface)} text tokens")
        start, end = float(unit["start"]), float(unit["end"])
        if not (math.isfinite(start) and math.isfinite(end) and 0 <= start <= end <= duration + 0.05):
            raise ValueError(f"{unit.get('sourceUnitId')}: invalid unit span")
        unit_words = []
        for offset, (surface_token, word) in enumerate(zip(surface, words)):
            word_text = str(word.get("text", ""))
            if norm_one(word_text) != norm_one(surface_token):
                issues.append({
                    "unitId": unit.get("sourceUnitId"),
                    "wordIndex": offset,
                    "approvedText": surface_token,
                    "timedWordText": word_text,
                    "issue": "timed_word_text_differs_from_approved_unit_text",
                })
            w_start, w_end = float(word["start"]), float(word["end"])
            # The historical timeline contains a few zero/negative-duration
            # words. Preserve them as evidence instead of repairing them here;
            # the scorer counts them as structural defects.
            if not (math.isfinite(w_start) and math.isfinite(w_end)
                    and 0 <= w_start <= duration + 0.05 and 0 <= w_end <= duration + 0.05):
                raise ValueError(f"{unit.get('sourceUnitId')}: invalid word span")
            index = len(tokens)
            token = {
                "index": index,
                "text": surface_token,
                "normalized": norm_one(surface_token),
                "start": round(w_start, 6),
                "end": round(w_end, 6),
                "unitId": unit.get("sourceUnitId"),
                "unitIndex": unit_index,
                "wordInUnit": offset,
            }
            tokens.append(token)
            unit_words.append({"index": index, "text": surface_token,
                               "start": round(w_start, 6), "end": round(w_end, 6)})
        units.append({
            "unitId": unit.get("sourceUnitId"),
            "unitIndex": unit_index,
            "text": text,
            "start": round(start, 6),
            "end": round(end, 6),
            "firstWordIndex": unit_words[0]["index"],
            "lastWordIndex": unit_words[-1]["index"],
            "words": unit_words,
        })

    sources = timing_sources(raw_whisper, [token["text"] for token in tokens])
    for token, source in zip(tokens, sources):
        token["timingSource"] = source

    # Group adjacent units into alignment chunks. Chunks never split a unit, so
    # a chunk boundary is always a place where the approved text already has a
    # word boundary. The speech inside a chunk is padded only for WhisperX;
    # MFA receives the exact span and edge words are excluded from reference
    # statistics by the scorer.
    chunks, current = [], []

    def flush() -> None:
        nonlocal current
        if not current:
            return
        first, last = current[0], current[-1]
        token_indexes = [word["index"]
                         for unit in (units[i] for i in range(first, last + 1))
                         for word in unit["words"]]
        chunks.append({
            "id": f"c{len(chunks):04d}",
            "start": round(units[first]["start"], 6),
            "end": round(units[last]["end"], 6),
            "text": " ".join(unit["text"] for unit in (units[i] for i in range(first, last + 1))),
            "unitStart": first,
            "unitEnd": last,
            "tokenIndexes": token_indexes,
            "normalizedText": " ".join(tokens[index]["normalized"] for index in token_indexes),
            "containsAmbiguousNumber": any(
                AMBIGUOUS_NUMBER_RE.search(tokens[index]["text"]) for index in token_indexes),
        })
        current = []

    for unit_index, unit in enumerate(units):
        # A long audible gap is a natural alignment window boundary. Grouping
        # across applause or a long pause lets a forced aligner stretch a short
        # word over the non-speech span, which is a reference error, not a
        # timeline finding.
        if current:
            gap = unit["start"] - units[current[-1]]["end"]
            if gap >= chunk_gap_seconds:
                flush()
        current.append(unit_index)
        span = units[current[-1]]["end"] - units[current[0]]["start"]
        if span >= chunk_target_seconds or len(current) >= 8 or span >= chunk_max_seconds:
            flush()
    flush()

    for chunk in chunks:
        chunk["paddedStart"] = round(max(0.0, chunk["start"] - 1.0), 6)
        chunk["paddedEnd"] = round(min(duration, chunk["end"] + 1.0), 6)

    # Stratified MFA sample: every Nth chunk, always including first and last,
    # and skipping chunks whose numeric tokens need an unverified spoken form.
    safe = [chunk for chunk in chunks if not chunk["containsAmbiguousNumber"]]
    selected = []
    for position, chunk in enumerate(chunks):
        must = position in (0, len(chunks) - 1)
        periodic = position % max(mfa_every, 1) == 0
        if (must or periodic) and not chunk["containsAmbiguousNumber"]:
            selected.append(chunk["id"])
    if chunks and chunks[0]["id"] not in selected and not chunks[0]["containsAmbiguousNumber"]:
        selected.insert(0, chunks[0]["id"])
    if chunks and chunks[-1]["id"] not in selected and not chunks[-1]["containsAmbiguousNumber"]:
        selected.append(chunks[-1]["id"])

    counts = {
        "units": len(units),
        "words": len(tokens),
        "chunks": len(chunks),
        "whisperMatchedWords": sum(token["timingSource"] == "whisper_match" for token in tokens),
        "syntheticWords": sum(token["timingSource"] == "synthetic_span" for token in tokens),
        "zeroDurationWords": sum(token["end"] <= token["start"] for token in tokens),
        "overlappingAdjacentPairs": sum(
            tokens[i]["start"] < tokens[i - 1]["end"] - 1e-6 for i in range(1, len(tokens))),
        "mfaSampleChunks": len(selected),
    }
    return {
        "schemaVersion": SCHEMA,
        "status": "machine_case_requires_human_gold",
        "limitations": [
            "Arm A is the historical production timeline; it is not a human word-level Gold.",
            "Arm B is a forced-alignment estimate on the approved text, not human-verified timing.",
            "MFA is an independent model estimate; agreement with it is not proof of accuracy.",
            "The approved English table has human approval, but its word times were inherited from whisper-1.",
        ],
        "source": {
            "date": manifest.get("input", {}).get("date"),
            "sourceUrl": manifest.get("input", {}).get("sourceUrl"),
            "mediaDurationSeconds": round(duration, 6),
            "anchorManifestSha256": None,
            "rawWhisperSha256": sha256(raw_whisper),
            "rawWhisperPath": str(raw_whisper),
        },
        "policy": manifest.get("policy", {}),
        "counts": counts,
        "issues": issues[:200],
        "issueCount": len(issues),
        "tokens": tokens,
        "units": units,
        "chunks": chunks,
        "mfaSampleChunkIds": selected,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--anchor-manifest", type=Path, required=True)
    parser.add_argument("--raw-whisper", type=Path, required=True)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--chunk-target-seconds", type=float, default=18.0)
    parser.add_argument("--chunk-max-seconds", type=float, default=24.0)
    parser.add_argument("--chunk-gap-seconds", type=float, default=1.0)
    parser.add_argument("--mfa-every", type=int, default=4)
    args = parser.parse_args()

    manifest = json.loads(args.anchor_manifest.read_text(encoding="utf-8"))
    duration = media_duration(args.audio)
    case = build_case(manifest, duration, args.raw_whisper,
                      args.chunk_target_seconds, args.chunk_max_seconds,
                      args.chunk_gap_seconds, args.mfa_every)
    case["source"]["anchorManifestSha256"] = sha256(args.anchor_manifest)
    case["source"]["audioSha256"] = sha256(args.audio)
    case["source"]["audioPath"] = str(args.audio)
    write_json(args.out / "case.json", case)
    selected_ids = set(case["mfaSampleChunkIds"])
    mfa_chunks = [
        {"id": chunk["id"], "start": chunk["start"], "end": chunk["end"], "text": chunk["text"]}
        for chunk in case["chunks"] if chunk["id"] in selected_ids
    ]
    write_json(args.out / "mfa-chunks.json", mfa_chunks)
    print(json.dumps({"out": str(args.out), **case["counts"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
