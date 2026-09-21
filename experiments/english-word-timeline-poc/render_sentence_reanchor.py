#!/usr/bin/env python3
"""Render a bounded audible review of one sentence-anchored Chinese group."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
from pathlib import Path
import subprocess


SCHEMA = "sermon-sentence-reanchor-render-poc-v1"


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


def plan_coordinates(report: dict, clip_duration: float) -> dict:
    if report.get("structuralPass") is not True or report.get("releaseEligible") is not False:
        raise ValueError("Only a non-release structural-pass POC report may be rendered")
    groups = report.get("translationGroups")
    if not isinstance(groups, list) or len(groups) != 1:
        raise ValueError("Audible POC currently requires exactly one translation group")
    group = groups[0]
    track_clip_start = (
        float(report["input"]["clipSourceStartSeconds"])
        - float(report["input"]["sermonSourceStartSeconds"])
    )
    planned_start = float(group["sentenceAnchoredPlan"]["start"])
    planned_end = float(group["sentenceAnchoredPlan"]["end"])
    cue_start = float(group["measuredChineseAudio"]["currentStart"])
    cue_end = float(group["measuredChineseAudio"]["currentEnd"])
    delay = planned_start - track_clip_start
    planned_local_end = planned_end - track_clip_start
    if (not all(math.isfinite(value) for value in (delay, planned_local_end, cue_start, cue_end, clip_duration))
            or delay < -0.05 or planned_local_end > clip_duration + 0.05 or cue_end <= cue_start):
        raise ValueError("Sentence plan does not fit the bounded source clip")
    return {
        "translationGroupId": group["translationGroupId"],
        "chinese": group["chinese"],
        "trackClipStart": round(track_clip_start, 6),
        "plannedDelaySeconds": round(max(0.0, delay), 6),
        "plannedLocalEndSeconds": round(planned_local_end, 6),
        "cueStart": cue_start,
        "cueEnd": cue_end,
        "cueDurationSeconds": round(cue_end - cue_start, 6),
        "clipDurationSeconds": round(clip_duration, 6),
    }


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--source-clip", type=Path, required=True)
    parser.add_argument("--chinese-track", type=Path, required=True)
    parser.add_argument("--chinese-track-sha256", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    report = json.loads(args.report.read_text(encoding="utf-8"))
    if sha256(args.chinese_track) != args.chinese_track_sha256:
        raise ValueError("Published Chinese track hash mismatch")
    clip_duration = media_duration(args.source_clip)
    plan = plan_coordinates(report, clip_duration)
    args.out.mkdir(parents=True, exist_ok=True)

    english = args.out / "source-en.wav"
    cue = args.out / "published-zh-cue.wav"
    planned = args.out / "planned-zh.wav"
    stereo = args.out / "review-en-left-zh-right.wav"
    run([
        "ffmpeg", "-v", "error", "-y", "-i", str(args.source_clip),
        "-t", str(plan["clipDurationSeconds"]), "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(english),
    ])
    run([
        "ffmpeg", "-v", "error", "-y", "-i", str(args.chinese_track),
        "-filter:a", f"atrim=start={plan['cueStart']}:end={plan['cueEnd']},asetpts=PTS-STARTPTS",
        "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(cue),
    ])
    delay_ms = round(plan["plannedDelaySeconds"] * 1000)
    run([
        "ffmpeg", "-v", "error", "-y", "-i", str(cue),
        "-filter:a", (
            f"adelay={delay_ms}:all=1,apad=whole_dur={plan['clipDurationSeconds']},"
            f"atrim=duration={plan['clipDurationSeconds']}"
        ),
        "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(planned),
    ])
    run([
        "ffmpeg", "-v", "error", "-y", "-i", str(english), "-i", str(planned),
        "-filter_complex", (
            f"[0:a]apad=whole_dur={plan['clipDurationSeconds']},atrim=duration={plan['clipDurationSeconds']}[en];"
            f"[1:a]apad=whole_dur={plan['clipDurationSeconds']},atrim=duration={plan['clipDurationSeconds']}[zh];"
            "[en][zh]join=inputs=2:channel_layout=stereo[out]"
        ),
        "-map", "[out]", "-ar", "48000", "-c:a", "pcm_s16le", str(stereo),
    ])

    rendered_duration = media_duration(planned)
    if abs(rendered_duration - clip_duration) > 0.05:
        raise ValueError("Rendered review track duration differs from source clip")
    receipt = {
        "schemaVersion": SCHEMA,
        "status": "audible_candidate_requires_listening_review",
        "releaseEligible": False,
        "input": {
            "sentenceMapReport": str(args.report.resolve()),
            "sentenceMapReportSha256": sha256(args.report),
            "sourceClip": str(args.source_clip.resolve()),
            "sourceClipSha256": sha256(args.source_clip),
            "publishedChineseTrack": str(args.chinese_track.resolve()),
            "publishedChineseTrackSha256": sha256(args.chinese_track),
        },
        "plan": plan,
        "outputs": {
            "sourceEnglish": {"path": str(english), "sha256": sha256(english)},
            "publishedChineseCue": {"path": str(cue), "sha256": sha256(cue)},
            "plannedChinese": {"path": str(planned), "sha256": sha256(planned)},
            "stereoReview": {"path": str(stereo), "sha256": sha256(stereo)},
        },
        "limitations": [
            "This reuses the published Chinese cue; it does not resynthesize or semantically re-review the translation.",
            "The stereo review places English on the left and planned Chinese on the right for inspection only.",
            "No listening acceptance has been recorded and no production track was changed.",
        ],
    }
    write_json(args.out / "render-receipt.json", receipt)
    review_html = f"""<!doctype html>
<meta charset=\"utf-8\">
<title>{html.escape(plan['translationGroupId'])} sentence reanchor review</title>
<style>body{{font:16px system-ui;max-width:840px;margin:40px auto;padding:0 20px;line-height:1.55}}audio{{width:100%}}code{{background:#eee;padding:2px 5px}}</style>
<h1>{html.escape(plan['translationGroupId'])}</h1>
<p>中文在英文片段内延后 <code>{plan['plannedDelaySeconds']:.2f}s</code> 开始。此页只是试听候选，尚未人工验收。</p>
<p>{html.escape(plan['chinese'])}</p>
<h2>英文原声</h2><audio controls src=\"source-en.wav\"></audio>
<h2>句起点重锚后的中文</h2><audio controls src=\"planned-zh.wav\"></audio>
<h2>左右声道对照</h2><p>左：英文；右：中文。</p><audio controls src=\"review-en-left-zh-right.wav\"></audio>
"""
    (args.out / "review.html").write_text(review_html, encoding="utf-8")
    print(args.out / "render-receipt.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
