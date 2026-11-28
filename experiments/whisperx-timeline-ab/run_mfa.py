#!/usr/bin/env python3
"""Run independent MFA word alignment on the frozen A/B chunks.

MFA is used only as a third forced-alignment estimate. It is not human Gold and
the report must keep that label. This script imports the production MFA adapter
so the exact model identity, cache rules and normalization are the ones already
frozen in the repository.

Run with the repository's system Python (no torch needed):

    PYTHONPATH=packages/production/src python3 \
      experiments/whisperx-timeline-ab/run_mfa.py ...
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages" / "production" / "src"))
from tongxing_production.source import mfa_alignment  # noqa: E402

SCHEMA = "sermon-mfa-reference-alignment-v1"
TOKEN_RE = re.compile(r"[a-z0-9]+(?:['’][a-z0-9]+)?", re.I)


def normalized_tokens(text: str) -> list[str]:
    return [token.lower().replace("’", "'") for token in TOKEN_RE.findall(text or "")]


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--chunk-ids", type=Path,
                        help="JSON list of chunk ids to align; defaults to mfaSampleChunkIds.")
    parser.add_argument("--all-safe", action="store_true",
                        help="Align every chunk without an ambiguous numeric token.")
    parser.add_argument("--skip-chunk", action="append", default=[],
                        help="Exclude this chunk id (repeatable), for a known MFA parse failure.")
    parser.add_argument("--mfa-executable", type=Path,
                        default=Path("artifacts/local-runtime/mfa-macbook/env/bin/mfa"))
    parser.add_argument("--dictionary", type=Path,
                        default=Path("artifacts/local-runtime/mfa-macbook/data/pretrained_models/"
                                     "dictionary/english_mfa.dict"))
    parser.add_argument("--acoustic-model", type=Path,
                        default=Path("artifacts/local-runtime/mfa-macbook/data/pretrained_models/"
                                     "acoustic/english_mfa.zip"))
    parser.add_argument("--g2p-model", type=Path,
                        default=Path("artifacts/local-runtime/mfa-macbook/data/pretrained_models/"
                                     "g2p/english_us_mfa.zip"))
    parser.add_argument("--num-jobs", type=int, default=6)
    args = parser.parse_args()

    case = json.loads(args.case.read_text(encoding="utf-8"))
    chunks_by_id = {chunk["id"]: chunk for chunk in case["chunks"]}
    if args.chunk_ids:
        wanted = json.loads(args.chunk_ids.read_text(encoding="utf-8"))
    elif args.all_safe:
        wanted = [chunk["id"] for chunk in case["chunks"]
                  if not chunk["containsAmbiguousNumber"]]
    else:
        wanted = case.get("mfaSampleChunkIds") or []
    skipped = set(args.skip_chunk)
    wanted = [chunk_id for chunk_id in wanted if chunk_id not in skipped]
    selected = [chunks_by_id[chunk_id] for chunk_id in wanted if chunk_id in chunks_by_id]
    if not selected:
        raise ValueError("No chunks selected for MFA")

    # The production adapter dispatches one `mfa align` over a corpus and keeps
    # one cache per exact chunk/audio/model identity. Keep the number of jobs
    # bounded for a laptop run; the identity does not include job count.
    original_max_jobs = mfa_alignment.MFA_MAX_JOBS
    mfa_alignment.MFA_MAX_JOBS = max(1, args.num_jobs)
    try:
        segments = mfa_alignment.align_reference_chunks(
            [{"id": chunk["id"], "start": chunk["start"], "end": chunk["end"],
              "text": chunk["text"]} for chunk in selected],
            args.audio,
            args.out,
            mfa_executable=args.mfa_executable,
            dictionary_path=args.dictionary,
            acoustic_model=args.acoustic_model,
            g2p_model=args.g2p_model,
        )
    finally:
        mfa_alignment.MFA_MAX_JOBS = original_max_jobs

    segments_by_chunk: dict[str, list[dict]] = {}
    for segment in segments:
        segments_by_chunk.setdefault(str(segment.get("referenceChunkId")), []).append(segment)

    words, runs, failures = [], [], []
    for chunk in selected:
        chunk_segments = segments_by_chunk.get(chunk["id"], [])
        flat = [word for segment in chunk_segments for word in segment.get("wordTimes", [])]
        expected = normalized_tokens(chunk["text"])
        got = [token for word in flat for token in normalized_tokens(word.get("text", ""))]
        if got != expected:
            failures.append({"chunkId": chunk["id"], "error": "token_sequence_mismatch",
                             "expectedTokens": len(expected), "alignedTokens": len(got)})
            continue
        if len(chunk["tokenIndexes"]) != len(flat):
            failures.append({"chunkId": chunk["id"], "error": "token_count_mismatch",
                             "expectedTokens": len(chunk["tokenIndexes"]),
                             "alignedTokens": len(flat)})
            continue
        for token_index, word in zip(chunk["tokenIndexes"], flat):
            words.append({
                "tokenIndex": token_index,
                "chunkId": chunk["id"],
                "text": word.get("text"),
                "start": float(word["start"]),
                "end": float(word["end"]),
                "timingQuality": word.get("timingQuality"),
                "explicitSpokenForm": word.get("explicitSpokenForm"),
            })
        runs.append({"chunkId": chunk["id"], "start": chunk["start"], "end": chunk["end"],
                     "segments": len(chunk_segments), "words": len(flat)})

    identity_path = next((args.out / "mfa_alignment").glob("*/manifest.json"), None)
    identity = json.loads(identity_path.read_text(encoding="utf-8")) if identity_path else None
    payload = {
        "schemaVersion": SCHEMA,
        "status": "machine_reference_requires_human_gold",
        "referenceRole": "third model estimate, not human Gold",
        "source": {
            "case": str(args.case),
            "caseSha256": hashlib.sha256(args.case.read_bytes()).hexdigest(),
            "audio": str(args.audio),
            "audioSha256": hashlib.sha256(args.audio.read_bytes()).hexdigest(),
        },
        "mfa": {
            "executable": str(args.mfa_executable),
            "dictionary": str(args.dictionary),
            "acousticModel": str(args.acoustic_model),
            "g2pModel": str(args.g2p_model),
            "manifest": str(identity_path) if identity_path else None,
            "identity": identity.get("identity") if identity else None,
        },
        "chunkCount": len(runs),
        "wordCount": len(words),
        "failures": failures,
        "chunks": runs,
        "words": words,
    }
    write_json(args.out / "mfa-aligned.json", payload)
    print(json.dumps({"out": str(args.out), "chunks": len(runs), "words": len(words),
                      "failures": len(failures)}, ensure_ascii=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
