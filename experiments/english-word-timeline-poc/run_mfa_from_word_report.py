#!/usr/bin/env python3
"""Run MFA on one frozen transcript/audio receipt from the word-timeline POC.

The input report supplies the frozen machine transcript and the audio hash.  This
adapter refuses changed audio, sends one bounded clip to the existing Spark MFA
transport, and writes a small local receipt pointing at the immutable MFA output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import mfa_spark  # noqa: E402


SCHEMA = "sermon-mfa-from-word-report-poc-v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def media_duration(path: Path) -> float:
    completed = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(json.loads(completed.stdout)["format"]["duration"])


def frozen_input(report: dict, audio: Path) -> tuple[str, str]:
    runs = report.get("modelRuns")
    if not isinstance(runs, list) or len(runs) != 1:
        raise ValueError("POC requires exactly one bounded model run")
    transcript = str(runs[0].get("rawTranscript", "")).strip()
    if not transcript:
        raise ValueError("Frozen transcript is empty")
    expected_audio = str(runs[0].get("audioSha256", ""))
    observed_audio = sha256(audio)
    if expected_audio != observed_audio:
        raise ValueError("Audio hash differs from the word-timeline receipt")
    return transcript, observed_audio


def write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--word-report", type=Path, required=True)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--chunk-id", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--host", default="achillesjing@192.168.1.152")
    args = parser.parse_args()

    report = json.loads(args.word_report.read_text(encoding="utf-8"))
    transcript, audio_sha = frozen_input(report, args.audio)
    duration = media_duration(args.audio)
    args.out.mkdir(parents=True, exist_ok=True)
    segments = mfa_spark.align_reference_chunks(
        [{"id": args.chunk_id, "start": 0.0, "end": duration, "text": transcript}],
        args.audio,
        args.out / "mfa",
        host=args.host,
        python=mfa_spark.DEFAULT_ROOT + "/env/bin/python",
        root=mfa_spark.DEFAULT_ROOT + "/jobs",
        mfa_executable=mfa_spark.DEFAULT_ROOT + "/bin/mfa-run",
        dictionary_path=mfa_spark.DEFAULT_ROOT + "/models/english_mfa.dict",
        acoustic_model=mfa_spark.DEFAULT_ROOT + "/models/english_mfa.zip",
        g2p_model=mfa_spark.DEFAULT_ROOT + "/models/english_us_mfa.zip",
    )
    manifest_path = Path(segments[0]["mfaManifest"])
    segments_path = manifest_path.with_name("segments.json")
    runtime_path = manifest_path.with_name("spark-runtime.json")
    receipt = {
        "schemaVersion": SCHEMA,
        "status": "mfa_machine_candidate_requires_review",
        "requiresOperatorReview": True,
        "input": {
            "wordReport": str(args.word_report.resolve()),
            "wordReportSha256": sha256(args.word_report),
            "audio": str(args.audio.resolve()),
            "audioSha256": audio_sha,
            "durationSeconds": duration,
            "frozenTranscriptSha256": hashlib.sha256(transcript.encode("utf-8")).hexdigest(),
        },
        "output": {
            "segments": str(segments_path),
            "segmentsSha256": sha256(segments_path),
            "manifest": str(manifest_path),
            "manifestSha256": sha256(manifest_path),
            "runtime": str(runtime_path),
            "runtimeSha256": sha256(runtime_path),
            "sentenceCount": len(segments),
            "wordCount": sum(len(segment.get("wordTimes", [])) for segment in segments),
        },
        "limitations": [
            "MFA timings are machine estimates, not human word-boundary Gold.",
            "The frozen transcript remains an ASR candidate and may omit or substitute speech.",
        ],
    }
    write_json(args.out / "mfa-receipt.json", receipt)
    print(args.out / "mfa-receipt.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
