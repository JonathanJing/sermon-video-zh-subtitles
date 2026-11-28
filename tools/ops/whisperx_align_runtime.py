#!/usr/bin/env python3
"""WhisperX alignment runtime adapter for the production timeline producer.

This script is executed by the isolated WhisperX Python (torch 2.8 + whisperx
3.8). It receives one JSON request, aligns each frozen text chunk exactly, and
writes one JSON result. It never rewrites text and never interpolates a missing
word; any token mismatch is an error for the caller.

Request schema:  sermon-whisperx-alignment-request-v1
Result schema:   sermon-whisperx-alignment-result-v1
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
from pathlib import Path
import re
import time

TOKEN_RE = re.compile(r"[a-z0-9]+(?:['’][a-z0-9]+)?", re.I)
REQUEST_SCHEMA = "sermon-whisperx-alignment-request-v1"
RESULT_SCHEMA = "sermon-whisperx-alignment-result-v1"


def normalized_tokens(text: str) -> list[str]:
    return [token.lower().replace("’", "'") for token in TOKEN_RE.findall(text or "")]


def version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def model_identity(align_model_name: str) -> dict:
    return {
        "whisperxVersion": version("whisperx"),
        "torchVersion": version("torch"),
        "torchaudioVersion": version("torchaudio"),
        "fasterWhisperVersion": version("faster-whisper"),
        "ctranslate2Version": version("ctranslate2"),
        "alignmentModel": align_model_name,
    }


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
            })
    return words


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--language", default="en")
    parser.add_argument("--align-model", default="WAV2VEC2_ASR_BASE_960H")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()

    if args.self_check:
        print(json.dumps({"ok": True, "model": model_identity(args.align_model)}, ensure_ascii=False))
        return 0

    request = json.loads(args.request.read_text(encoding="utf-8"))
    if request.get("schemaVersion") != REQUEST_SCHEMA:
        raise SystemExit(f"unexpected request schema: {request.get('schemaVersion')}")
    chunks = request.get("chunks")
    if not isinstance(chunks, list) or not chunks:
        raise SystemExit("request has no chunks")
    audio_path = Path(request["audio"])
    if not audio_path.is_file():
        raise SystemExit(f"audio not found: {audio_path}")

    import numpy as np
    import whisperx

    started = time.monotonic()
    audio = whisperx.load_audio(str(audio_path))
    max_duration = audio.shape[-1] / 16000.0
    model, metadata = whisperx.load_align_model(language_code=args.language, device=args.device)
    output_chunks = []
    attempts: dict[str, int] = {}
    for chunk in chunks:
        chunk_id = str(chunk["id"])
        start, end = float(chunk["start"]), float(chunk["end"])
        if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end <= max_duration + 0.05):
            raise SystemExit(f"{chunk_id}: invalid chunk span {start}-{end} / {max_duration:.3f}")
        text = str(chunk.get("text", ""))
        expected = normalized_tokens(text)
        if not expected:
            raise SystemExit(f"{chunk_id}: empty text")
        segment = {"text": text, "start": start, "end": end}
        result = whisperx.align([segment], model, metadata, audio, args.device,
                                return_char_alignments=False, print_progress=False)
        words = words_from_result(result)
        got = [token for word in words for token in normalized_tokens(word["text"])]
        if got != expected:
            first = next(({"position": i, "expected": a, "aligned": b}
                          for i, (a, b) in enumerate(zip(expected, got)) if a != b), None)
            raise SystemExit(json.dumps({
                "error": "token_sequence_mismatch", "chunkId": chunk_id,
                "expectedTokens": len(expected), "alignedTokens": len(got),
                "firstDifference": first,
            }, ensure_ascii=False))
        if len(words) != int(chunk.get("tokenCount", len(words))):
            raise SystemExit(f"{chunk_id}: token count {len(words)} != request {chunk.get('tokenCount')}")
        output_chunks.append({"id": chunk_id, "start": start, "end": end, "words": words})
        attempts["chunk_exact"] = attempts.get("chunk_exact", 0) + 1

    payload = {
        "schemaVersion": RESULT_SCHEMA,
        "model": model_identity(args.align_model),
        "audio": str(audio_path),
        "audioSamples": int(audio.shape[-1]),
        "elapsedSeconds": round(time.monotonic() - started, 3),
        "attemptCounts": attempts,
        "chunks": output_chunks,
    }
    write_json(args.out, payload)
    print(json.dumps({"out": str(args.out), "chunks": len(output_chunks),
                      "words": sum(len(chunk["words"]) for chunk in output_chunks),
                      "elapsedSeconds": payload["elapsedSeconds"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
