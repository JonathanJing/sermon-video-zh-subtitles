#!/usr/bin/env python3
"""Prepare overlapping real A/V windows for a full-sermon Gemini sidecar run."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

from prepare_round2 import build_prompt
from schema import SCHEMA_VERSION, sha256


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def media_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        check=True, capture_output=True, text=True)
    return float(result.stdout.strip())


def link_or_verify(source: Path, target: Path) -> None:
    if target.exists() or target.is_symlink():
        if target.resolve() != source.resolve():
            raise RuntimeError(f"Existing link points elsewhere: {target}")
        return
    target.symlink_to(source.resolve())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-video", type=Path, required=True)
    parser.add_argument("--alignment-dir", type=Path, required=True)
    parser.add_argument("--sermon-start", type=float, required=True)
    parser.add_argument("--sermon-duration", type=float, required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    source_video = args.source_video.resolve()
    alignment_dir = args.alignment_dir.resolve()
    words = alignment_dir / "words.json"
    alignment_report = alignment_dir / "report.json"
    model_review = alignment_dir / "anchor-model-review.json"
    for path in (source_video, words, alignment_report, model_review):
        if not path.is_file():
            raise SystemExit(f"Missing required evidence: {path}")

    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    windows: list[dict] = []
    for audio in sorted(alignment_dir.glob("window-*.wav")):
        relative_start = float(audio.stem.split("-")[1])
        if relative_start >= args.sermon_duration:
            continue
        duration = min(media_duration(audio), args.sermon_duration - relative_start)
        case_id = f"full-w{int(relative_start):04d}"
        window_dir = out / case_id
        input_dir = window_dir / "input"
        review_dir = window_dir / "review"
        input_dir.mkdir(parents=True, exist_ok=True)
        review_dir.mkdir(parents=True, exist_ok=True)
        linked_audio = input_dir / "real-audio.wav"
        link_or_verify(audio, linked_audio)
        video = input_dir / "real-av.mp4"
        if not video.exists():
            run(["ffmpeg", "-v", "error", "-y", "-ss",
                 str(args.sermon_start + relative_start), "-i", str(source_video),
                 "-t", f"{duration:.6f}", "-vf", "scale=960:-2,fps=2",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "27",
                 "-c:a", "aac", "-b:a", "96k", str(video)])
        contact_sheet = review_dir / "contact-sheet.jpg"
        if not contact_sheet.exists():
            run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vf",
                 "fps=1/10,scale=320:-2,tile=6x1:padding=2:margin=2",
                 "-frames:v", "1", str(contact_sheet)])

        asr_path = alignment_dir / f"window-{int(relative_start):04d}.asr.json"
        alignment_path = alignment_dir / f"window-{int(relative_start):04d}.alignment.json"
        asr = json.loads(asr_path.read_text(encoding="utf-8"))
        transcript = str(asr.get("text", "")).strip()
        prompt = window_dir / "prompt.txt"
        prompt.write_text(build_prompt(duration, transcript), encoding="utf-8")
        windows.append({
            "windowId": case_id,
            "relativeStartSeconds": relative_start,
            "relativeEndSeconds": relative_start + duration,
            "fullVideoStartSeconds": args.sermon_start + relative_start,
            "durationSeconds": duration,
            "transcriptKind": "window_asr_candidate",
            "paths": {
                "audio": str(linked_audio.relative_to(out)),
                "video": str(video.relative_to(out)),
                "prompt": str(prompt.relative_to(out)),
                "contactSheet": str(contact_sheet.relative_to(out)),
                "asr": str(asr_path),
                "alignment": str(alignment_path),
            },
            "hashes": {
                "audio": sha256(audio), "video": sha256(video), "prompt": sha256(prompt),
                "asr": sha256(asr_path), "alignment": sha256(alignment_path),
                "contactSheet": sha256(contact_sheet),
            },
        })

    matrix = [{
        "sampleId": item["windowId"], "conditionId": "av-transcript",
        "caseId": item["windowId"], "durationSeconds": item["durationSeconds"],
        "video": item["paths"]["video"], "audio": item["paths"]["audio"],
        "prompt": item["paths"]["prompt"], "expectedAudioStatus": "matched",
    } for item in windows]
    manifest = {
        "schemaVersion": "sermon-omni-full-corpus-v1",
        "annotationSchemaVersion": SCHEMA_VERSION,
        "reviewState": "machine_corpus_requires_operator_listening_review",
        "source": {
            "id": args.source_id, "path": str(source_video), "sha256": sha256(source_video),
            "sermonStartSeconds": args.sermon_start,
            "sermonDurationSeconds": args.sermon_duration,
        },
        "wordTiming": {
            "status": "candidate_alignment_model_reviewed_not_human_gold",
            "path": str(words), "sha256": sha256(words),
            "reportPath": str(alignment_report), "reportSha256": sha256(alignment_report),
            "modelReviewPath": str(model_review), "modelReviewSha256": sha256(model_review),
        },
        "windowCount": len(windows), "windows": windows, "matrix": matrix,
        "limitations": [
            "Window transcripts are ASR candidates and are not verbatim human Gold.",
            "Word timings and block boundaries are machine candidates, not human Gold.",
            "Windows overlap by approximately ten seconds; downstream normalization must deduplicate them.",
            "Gemini outputs are sidecar candidates and cannot become release timeline authority.",
        ],
    }
    write_json(out / "full-corpus-manifest.json", manifest)
    print(json.dumps({"manifest": str(out / "full-corpus-manifest.json"),
                      "windows": len(windows)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
