#!/usr/bin/env python3
"""Prepare one immutable audio/video/transcript input for Omni model comparison."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from schema import PROMPT, SCHEMA_VERSION, sha256


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def transcript_for_range(report: dict, start: float, duration: float) -> tuple[str, int | None]:
    """Crop a timestamped candidate transcript to the frozen source interval."""
    words = report.get("words")
    if not isinstance(words, list) or not words:
        return report["wordSequenceText"], None
    end = start + duration
    selected = [word for word in words
                if isinstance(word, dict)
                and isinstance(word.get("timelineStart"), (int, float))
                and isinstance(word.get("timelineEnd"), (int, float))
                and float(word["timelineEnd"]) >= start - 0.05
                and float(word["timelineStart"]) <= end + 0.05]
    return " ".join(str(word["text"]) for word in selected), len(selected)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-video", type=Path, required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--start", type=float, required=True)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--transcript-report", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    source = args.source_video.resolve()
    transcript_report = json.loads(args.transcript_report.read_text(encoding="utf-8"))
    out = args.out.resolve()
    input_dir = out / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    video = input_dir / "real-av.mp4"
    audio = input_dir / "real-audio.wav"
    silence = input_dir / "silence-audio.wav"
    if not video.exists():
        run(["ffmpeg", "-v", "error", "-y", "-ss", str(args.start), "-i", str(source),
             "-t", str(args.duration), "-vf", "scale=1280:-2,fps=2", "-c:v", "libx264",
             "-preset", "fast", "-crf", "23", "-c:a", "aac", "-b:a", "128k", str(video)])
    if not audio.exists():
        run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vn", "-ar", "16000",
             "-ac", "1", "-c:a", "pcm_s16le", str(audio)])
    if not silence.exists():
        run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
             "-t", str(args.duration), "-c:a", "pcm_s16le", str(silence)])
    transcript_text, selected_word_count = transcript_for_range(
        transcript_report, args.start, args.duration)
    prompt = (PROMPT.replace("__DURATION__", f"{args.duration:.3f}")
              .replace("__TRANSCRIPT__", transcript_text))
    prompt_path = out / "prompt.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "reviewState": "machine_candidate_requires_review",
        "source": {"id": args.source_id, "path": str(source), "sha256": sha256(source),
                   "clipStartSeconds": args.start, "clipDurationSeconds": args.duration},
        "inputs": {
            "video": {"path": str(video), "sha256": sha256(video)},
            "audio": {"path": str(audio), "sha256": sha256(audio)},
            "silence": {"path": str(silence), "sha256": sha256(silence)},
            "transcriptReport": {"path": str(args.transcript_report.resolve()),
                                 "sha256": sha256(args.transcript_report.resolve()),
                                 "status": transcript_report.get("status"),
                                 "transcriptCompletenessProven": transcript_report.get("transcriptCompletenessProven"),
                                 "selectedWordCount": selected_word_count},
            "prompt": {"path": str(prompt_path), "sha256": sha256(prompt_path)},
        },
        "limitations": [
            "The transcript is an unreviewed ASR candidate and does not prove word-for-word completeness.",
            "The reference intervals remain human-review candidates, not accepted ground truth.",
            "Model outputs are sidecar annotations and cannot modify subtitles or dubbing automatically.",
        ],
    }
    write_json(out / "input-manifest.json", manifest)
    print(json.dumps({"manifest": str(out / "input-manifest.json"), "promptSha256": manifest["inputs"]["prompt"]["sha256"]}))


if __name__ == "__main__":
    main()
