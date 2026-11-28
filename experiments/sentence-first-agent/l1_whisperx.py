#!/usr/bin/env python3
"""Replace the whisper-1 word times with WhisperX forced alignment before the English review.

The timing pass still gives the segments and their text; this script aligns those exact
segments with WhisperX wav2vec2 and writes a whisper-1-shaped ``raw-whisperx.json`` whose
``words`` are the aligned times. ``l1_anchor.py build`` then builds the sentence table the
reviewer sees; the English-table approval therefore covers the WhisperX timing as well.

Text is never rewritten. The source segment text is the alignment reference; a chunk whose
aligned token sequence differs from it stops the run. The isolated WhisperX runtime is passed
explicitly; this script only uses the standard library.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import time

TOKEN_RE = re.compile(r"[a-z0-9]+(?:['’][a-z0-9]+)?", re.I)
REQUEST_SCHEMA = "sermon-whisperx-alignment-request-v1"
RESULT_SCHEMA = "sermon-whisperx-alignment-result-v1"


class AlignmentError(RuntimeError):
    pass


def normalized_tokens(text: str) -> list[str]:
    return [token.lower().replace("’", "'") for token in TOKEN_RE.findall(text or "")]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def build_chunks(segments: list[dict], *, target_seconds: float = 18.0,
                 max_seconds: float = 24.0, gap_seconds: float = 1.0) -> list[dict]:
    usable = [segment for segment in segments
              if str(segment.get("text", "")).strip()
              and math.isfinite(float(segment.get("start", -1)))
              and math.isfinite(float(segment.get("end", -1)))
              and float(segment["end"]) > float(segment["start"])]
    if not usable:
        raise AlignmentError("no usable whisper-1 segments")
    chunks: list[dict] = []
    current: list[dict] = []

    def flush() -> None:
        nonlocal current
        if not current:
            return
        text = " ".join(" ".join(str(segment["text"]).split()) for segment in current)
        tokens = normalized_tokens(text)
        if not tokens:
            current = []
            return
        chunks.append({
            "id": f"c{len(chunks):04d}",
            "start": round(float(current[0]["start"]), 6),
            "end": round(float(current[-1]["end"]), 6),
            "text": text,
            "tokenCount": len(tokens),
        })
        current = []

    for segment in usable:
        if current:
            gap = float(segment["start"]) - float(current[-1]["end"])
            if gap >= gap_seconds:
                flush()
        current.append(segment)
        span = float(current[-1]["end"]) - float(current[0]["start"])
        if span >= target_seconds or span >= max_seconds or len(current) >= 12:
            flush()
    flush()
    if not chunks:
        raise AlignmentError("no alignment chunks")
    return chunks


def run_adapter(runtime_python: Path, adapter: Path, request: Path, result: Path,
                *, device: str, language: str) -> dict:
    command = [str(runtime_python), str(adapter), "--request", str(request), "--out", str(result),
               "--device", device, "--language", language]
    started = time.monotonic()
    proc = subprocess.run(command, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = " | ".join((proc.stderr or proc.stdout).strip().splitlines()[-8:])
        raise AlignmentError(f"WhisperX adapter failed: {tail}")
    payload = json.loads(result.read_text(encoding="utf-8"))
    if payload.get("schemaVersion") != RESULT_SCHEMA:
        raise AlignmentError("unexpected WhisperX result schema")
    payload["producerElapsedSeconds"] = round(time.monotonic() - started, 3)
    return payload


def validate(chunks: list[dict], result: dict, duration: float) -> list[dict]:
    by_id = {str(chunk.get("id")): chunk for chunk in result.get("chunks", [])}
    if set(by_id) != {chunk["id"] for chunk in chunks}:
        raise AlignmentError("WhisperX chunk coverage differs from the request")
    words: list[dict] = []
    previous_end = 0.0
    for chunk in chunks:
        payload = by_id[chunk["id"]]
        aligned = payload.get("words")
        if not isinstance(aligned, list) or not aligned:
            raise AlignmentError(f"{chunk['id']}: no aligned words")
        expected = normalized_tokens(chunk["text"])
        got = [token for word in aligned for token in normalized_tokens(str(word.get("text", "")))]
        if got != expected:
            first = next(({"position": i, "expected": a, "aligned": b}
                          for i, (a, b) in enumerate(zip(expected, got)) if a != b), None)
            raise AlignmentError(json.dumps({"error": "token_sequence_mismatch", "chunkId": chunk["id"],
                                             "expectedTokens": len(expected), "alignedTokens": len(got),
                                             "firstDifference": first}, ensure_ascii=False))
        for word in aligned:
            text = str(word.get("text", "")).strip()
            start, end = word.get("start"), word.get("end")
            if not text or not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
                raise AlignmentError(f"{chunk['id']}: invalid aligned word")
            start, end = float(start), float(end)
            if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end <= duration + 0.05):
                raise AlignmentError(f"{chunk['id']}: aligned time out of bounds: {text} {start}-{end}")
            if start < previous_end - 0.001:
                raise AlignmentError(f"{chunk['id']}: non-monotonic aligned word: {text}")
            previous_end = end
            words.append({"text": text, "start": round(start, 6), "end": round(end, 6)})
    return words


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--raw-whisper", type=Path, required=True)
    parser.add_argument("--audio", type=Path, required=True, help="16 kHz mono source audio")
    parser.add_argument("--out", type=Path, required=True, help="raw-whisperx.json")
    parser.add_argument("--words-out", type=Path, help="words.json (default: next to --out)")
    parser.add_argument("--runtime-python", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--language", default="en")
    parser.add_argument("--target-seconds", type=float, default=18.0)
    parser.add_argument("--max-seconds", type=float, default=24.0)
    parser.add_argument("--gap-seconds", type=float, default=1.0)
    args = parser.parse_args(argv)

    raw = json.loads(args.raw_whisper.read_text(encoding="utf-8"))
    duration = float(raw.get("duration") or 0.0)
    if duration <= 0:
        raise SystemExit("raw-whisper has no positive duration")
    chunks = build_chunks(raw.get("segments", []), target_seconds=args.target_seconds,
                          max_seconds=args.max_seconds, gap_seconds=args.gap_seconds)
    out = args.out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    request = {
        "schemaVersion": REQUEST_SCHEMA,
        "audio": str(args.audio.resolve()),
        "language": args.language,
        "device": args.device,
        "chunks": chunks,
    }
    request_path = out.parent / "whisperx-request.json"
    result_path = out.parent / "whisperx-result.json"
    write_json(request_path, request)
    # Do not resolve the runtime symlink: resolving a venv's bin/python escapes
    # the venv and loses its site-packages (WhisperX/torch/numpy).
    result = run_adapter(Path(args.runtime_python), args.adapter.resolve(), request_path, result_path,
                         device=args.device, language=args.language)
    words = validate(chunks, result, duration)
    aligned = {
        **raw,
        "words": [{"word": word["text"], "start": word["start"], "end": word["end"]} for word in words],
        "timingQuality": "whisperx_wav2vec2_forced_alignment",
        "whisperx": {
            **(result.get("model") or {}),
            "adapterSha256": sha256_file(args.adapter.resolve()),
            "requestSha256": sha256_file(request_path),
            "resultSha256": sha256_file(result_path),
            "audioSha256": sha256_file(args.audio.resolve()),
            "runtimePython": str(args.runtime_python),
            "device": args.device,
            "language": args.language,
            "chunkCount": len(chunks),
            "elapsedSeconds": result.get("elapsedSeconds"),
            "producerElapsedSeconds": result.get("producerElapsedSeconds"),
        },
    }
    write_json(out, aligned)
    words_path = args.words_out or (out.parent / "words.json")
    write_json(words_path, [{"text": word["text"], "start": word["start"], "end": word["end"]} for word in words])
    print(json.dumps({"out": str(out), "words": str(words_path), "chunks": len(chunks),
                      "wordCount": len(words), "elapsedSeconds": result.get("elapsedSeconds")},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
