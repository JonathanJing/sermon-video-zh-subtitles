#!/usr/bin/env python3
"""Run a stratified, multi-block MFA sentence-anchor shadow POC.

The published English block text is frozen.  Existing block cue starts provide
bounded audio windows only; MFA supplies word/sentence times inside each window.
No translation is changed and no production asset is written.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import html
import json
import math
from pathlib import Path
import re
import statistics
import subprocess
import sys


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import mfa_alignment, mfa_spark  # noqa: E402


SCHEMA = "sermon-expanded-sentence-anchor-poc-v1"
DEFAULT_BLOCKS = [0, 1, 8, 14, 18, 30, 31, 37, 39, 46, 56, 59, 61]
SELECTION_REASONS = {
    0: ["opening", "high_chinese_character_rate"],
    1: ["opening_story", "long_multi_sentence_block"],
    8: ["scripture_names_and_quotation"],
    14: ["high_sentence_count", "long_multi_sentence_block"],
    18: ["highest_english_word_count"],
    30: ["middle_quartile", "high_chinese_character_rate"],
    31: ["mid_sermon_repetition", "high_sentence_count"],
    37: ["known_early_finish_gap"],
    39: ["highest_chinese_character_rate"],
    46: ["late_middle_quartile"],
    56: ["long_theological_conclusion", "scripture_numbers"],
    59: ["known_early_finish_gap", "closing_scripture_image"],
    61: ["ending"],
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def media_duration(path: Path) -> float:
    completed = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    duration = float(json.loads(completed.stdout)["format"]["duration"])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Media duration must be finite and positive")
    return duration


def selected_week(catalog: dict, week_id: str) -> dict:
    matches = [week for week in catalog.get("weeks", []) if week.get("id") == week_id]
    if len(matches) != 1:
        raise ValueError("Catalog must contain exactly one requested week")
    week = matches[0]
    blocks = week.get("transcript", {}).get("blocks")
    tracks = week.get("tracks")
    if not isinstance(blocks, list) or not blocks or not isinstance(tracks, list) or len(tracks) != 1:
        raise ValueError("Week must contain transcript blocks and exactly one selected track")
    return week


def block_windows(week: dict) -> dict[int, dict]:
    blocks = {int(block["blockId"]): block for block in week["transcript"]["blocks"]}
    cues_by_block: dict[int, list[dict]] = defaultdict(list)
    for cue in week["tracks"][0]["cues"]:
        cues_by_block[int(cue["blockId"])].append(cue)
    if set(blocks) != set(cues_by_block):
        raise ValueError("Published blocks and cue block IDs differ")
    ordered = sorted(blocks)
    if ordered != list(range(len(ordered))):
        raise ValueError("POC requires contiguous numeric block IDs")
    starts = {block_id: min(float(cue["start"]) for cue in cues_by_block[block_id]) for block_id in ordered}
    sermon_duration = float(week["sourceEndSeconds"]) - float(week["sourceStartSeconds"])
    windows = {}
    for position, block_id in enumerate(ordered):
        start = starts[block_id]
        end = starts[ordered[position + 1]] if position + 1 < len(ordered) else sermon_duration
        if start < 0 or end <= start or end > sermon_duration + 0.05:
            raise ValueError(f"Invalid published block window: {block_id}")
        cues = sorted(cues_by_block[block_id], key=lambda cue: float(cue["start"]))
        windows[block_id] = {
            "blockId": block_id,
            "start": round(start, 6),
            "end": round(end, 6),
            "english": str(blocks[block_id]["english"]),
            "chinese": str(blocks[block_id]["chinese"]),
            "cues": cues,
        }
    return windows


def parse_block_ids(value: str) -> list[int]:
    ids = [int(item.strip()) for item in value.split(",") if item.strip()]
    if not ids or len(ids) != len(set(ids)) or ids != sorted(ids):
        raise ValueError("Block IDs must be a nonempty sorted unique comma-separated list")
    return ids


def extract_sermon_audio(source: Path, target: Path, start: float, duration: float) -> None:
    if target.exists():
        observed = media_duration(target)
        if abs(observed - duration) > 0.05:
            raise ValueError("Cached sermon audio duration differs from requested window")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-i", str(source), "-ss", str(start), "-t", str(duration),
        "-vn", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(target),
    ], check=True)
    observed = media_duration(target)
    if abs(observed - duration) > 0.05:
        raise ValueError("Extracted sermon audio duration differs from approved window")


def percentile(values: list[float], proportion: float) -> float:
    if not values:
        raise ValueError("Percentile requires values")
    ordered = sorted(values)
    position = (len(ordered) - 1) * proportion
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def build_anchor_report(*, week: dict, windows: dict[int, dict], selected_ids: list[int], segments: list[dict],
                        catalog_path: Path, source_path: Path, sermon_audio: Path, segments_path: Path,
                        manifest_path: Path, runtime_path: Path) -> dict:
    by_chunk: dict[str, list[dict]] = defaultdict(list)
    for segment in segments:
        by_chunk[str(segment.get("referenceChunkId"))].append(segment)
    issues = []
    samples = []
    for block_id in selected_ids:
        window = windows[block_id]
        chunk_id = f"block-{block_id:02d}"
        source_sentences = sorted(by_chunk.get(chunk_id, []), key=lambda item: float(item["start"]))
        if not source_sentences:
            issues.append({"type": "missing_mfa_sentences", "blockId": block_id})
            continue
        words = [word for sentence in source_sentences for word in sentence.get("wordTimes", [])]
        if not words:
            issues.append({"type": "missing_mfa_words", "blockId": block_id})
            continue
        first_word = float(words[0]["start"])
        last_word = float(words[-1]["end"])
        cue_start = min(float(cue["start"]) for cue in window["cues"])
        cue_end = max(float(cue["end"]) for cue in window["cues"])
        cue_duration = sum(float(cue["end"]) - float(cue["start"]) for cue in window["cues"])
        sentence_rows = []
        for index, sentence in enumerate(source_sentences, start=1):
            sentence_words = sentence.get("wordTimes", [])
            sentence_rows.append({
                "sourceSentenceId": f"20260920-b{block_id:02d}-s{index:03d}",
                "english": sentence["text"],
                "start": round(float(sentence["start"]), 6),
                "end": round(float(sentence["end"]), 6),
                "durationSeconds": round(float(sentence["end"]) - float(sentence["start"]), 6),
                "wordCount": len(sentence_words),
                "firstWordId": f"20260920-b{block_id:02d}-w{sum(len(row['wordTimes']) for row in source_sentences[:index - 1]) + 1:04d}",
                "lastWordId": f"20260920-b{block_id:02d}-w{sum(len(row['wordTimes']) for row in source_sentences[:index]):04d}",
            })
        duration_values = [row["durationSeconds"] for row in sentence_rows]
        end_lead = last_word - cue_end
        start_lead = first_word - cue_start
        source_span = last_word - first_word
        risk_flags = []
        if abs(start_lead) > 1.0:
            risk_flags.append("current_chinese_start_differs_from_first_english_word_over_1s")
        if end_lead > 2.0:
            risk_flags.append("current_chinese_finishes_over_2s_before_last_english_word")
        elif end_lead < -2.0:
            risk_flags.append("current_chinese_finishes_over_2s_after_last_english_word")
        if first_word - float(window["start"]) > 2.0:
            risk_flags.append("over_2s_leading_window_slack_requires_listening")
        if float(window["end"]) - last_word > 3.0:
            risk_flags.append("over_3s_trailing_window_slack_requires_listening")
        if float(window["end"]) - last_word < 0.1:
            risk_flags.append("mfa_last_word_within_100ms_of_window_end_requires_listening")
        if max(duration_values) > 15.0:
            risk_flags.append("source_sentence_over_15s")
        if len(source_sentences) != len(window["cues"]):
            risk_flags.append("english_sentence_count_differs_from_current_cue_count")
        samples.append({
            "blockId": block_id,
            "selectionReasons": SELECTION_REASONS.get(block_id, ["operator_selected"]),
            "window": {"start": window["start"], "end": window["end"], "durationSeconds": round(window["end"] - window["start"], 6)},
            "mfaSpeech": {
                "firstWordStart": round(first_word, 6),
                "lastWordEnd": round(last_word, 6),
                "speechSpanSeconds": round(source_span, 6),
                "leadingWindowSlackSeconds": round(first_word - float(window["start"]), 6),
                "trailingWindowSlackSeconds": round(float(window["end"]) - last_word, 6),
            },
            "publishedChinese": {
                "cueCount": len(window["cues"]),
                "firstCueStart": round(cue_start, 6),
                "lastCueEnd": round(cue_end, 6),
                "summedSpeechSeconds": round(cue_duration, 6),
                "startsBeforeFirstEnglishWordBySeconds": round(start_lead, 6),
                "finishesBeforeLastEnglishWordBySeconds": round(end_lead, 6),
                "sourceSpanMinusChineseSpeechSeconds": round(source_span - cue_duration, 6),
            },
            "counts": {
                "englishWords": len(words),
                "englishSentences": len(source_sentences),
                "currentChineseCues": len(window["cues"]),
            },
            "sentenceDuration": {
                "medianSeconds": round(statistics.median(duration_values), 6),
                "p95Seconds": round(percentile(duration_values, 0.95), 6),
                "maxSeconds": round(max(duration_values), 6),
            },
            "sentences": sentence_rows,
            "riskFlags": risk_flags,
        })
    structural_pass = not issues and len(samples) == len(selected_ids)
    all_sentence_durations = [sentence["durationSeconds"] for sample in samples for sentence in sample["sentences"]]
    all_end_leads = [sample["publishedChinese"]["finishesBeforeLastEnglishWordBySeconds"] for sample in samples]
    selected_duration = sum(sample["window"]["durationSeconds"] for sample in samples)
    sermon_duration = float(week["sourceEndSeconds"]) - float(week["sourceStartSeconds"])
    return {
        "schemaVersion": SCHEMA,
        "status": "expanded_machine_anchor_candidate_requires_listening_review" if structural_pass else "invalid_expanded_sentence_anchor",
        "releaseEligible": False,
        "structuralPass": structural_pass,
        "humanWordBoundaryGold": "not_supplied",
        "humanSentenceBoundaryReview": "pending",
        "input": {
            "weekId": week["id"],
            "sourceId": week["sourceId"],
            "sourceSha256": week["sourceSha256"],
            "sourceStartSeconds": week["sourceStartSeconds"],
            "sourceEndSeconds": week["sourceEndSeconds"],
            "catalog": str(catalog_path.resolve()),
            "catalogSha256": sha256(catalog_path),
            "sourceMedia": str(source_path.resolve()),
            "sourceMediaSha256": sha256(source_path),
            "sermonAudio": str(sermon_audio.resolve()),
            "sermonAudioSha256": sha256(sermon_audio),
            "mfaSegments": str(segments_path),
            "mfaSegmentsSha256": sha256(segments_path),
            "mfaManifest": str(manifest_path),
            "mfaManifestSha256": sha256(manifest_path),
            "mfaRuntime": str(runtime_path),
            "mfaRuntimeSha256": sha256(runtime_path),
        },
        "coverage": {
            "selectedBlocks": len(samples),
            "totalBlocks": len(week["transcript"]["blocks"]),
            "blockPercent": round(len(samples) / len(week["transcript"]["blocks"]) * 100, 3),
            "selectedWindowSeconds": round(selected_duration, 6),
            "sermonSeconds": round(sermon_duration, 6),
            "timePercent": round(selected_duration / sermon_duration * 100, 3),
            "englishSentences": sum(sample["counts"]["englishSentences"] for sample in samples),
            "englishWords": sum(sample["counts"]["englishWords"] for sample in samples),
        },
        "aggregate": {
            "sentenceDurationMedianSeconds": round(statistics.median(all_sentence_durations), 6) if all_sentence_durations else None,
            "sentenceDurationP95Seconds": round(percentile(all_sentence_durations, 0.95), 6) if all_sentence_durations else None,
            "currentChineseEndLeadMedianSeconds": round(statistics.median(all_end_leads), 6) if all_end_leads else None,
            "currentChineseEndLeadP95Seconds": round(percentile(all_end_leads, 0.95), 6) if all_end_leads else None,
            "blocksEndingOver2sEarly": sum(value > 2.0 for value in all_end_leads),
            "blocksEndingOver5sEarly": sum(value > 5.0 for value in all_end_leads),
            "sourceSentencesOver15s": sum(value > 15.0 for value in all_sentence_durations),
            "blocksWithLastWordAtWindowEnd": sum(
                sample["mfaSpeech"]["trailingWindowSlackSeconds"] < 0.1 for sample in samples
            ),
        },
        "samples": samples,
        "issues": issues,
        "limitations": [
            "Published block cue starts are used only as bounded MFA windows and require listening review.",
            "MFA word times are machine estimates, not human word-boundary Gold.",
            "Frozen English remains the published ASR-derived candidate, not a human verbatim transcript.",
            "This stage establishes English sentence anchors; it does not assign or semantically approve Chinese sentence mappings.",
            "Selected blocks are stratified risk samples, not full-sermon coverage.",
        ],
    }


def srt_time(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    whole_seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{milliseconds:03d}"


def write_review(out: Path, report: dict, sermon_audio: Path) -> None:
    review_dir = out / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    srt_lines = []
    html_sections = []
    cue_index = 1
    for sample in report["samples"]:
        block_id = sample["blockId"]
        start, end = sample["window"]["start"], sample["window"]["end"]
        audio_name = f"block-{block_id:02d}-source.wav"
        subprocess.run([
            "ffmpeg", "-v", "error", "-y", "-ss", str(start), "-i", str(sermon_audio),
            "-t", str(end - start), "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(review_dir / audio_name),
        ], check=True)
        rows = []
        for sentence in sample["sentences"]:
            srt_lines.extend([
                str(cue_index),
                f"{srt_time(sentence['start'])} --> {srt_time(sentence['end'])}",
                f"[block {block_id}] {sentence['english']}",
                "",
            ])
            cue_index += 1
            rows.append(
                "<tr><td>" + html.escape(sentence["sourceSentenceId"]) + "</td><td>"
                + f"{sentence['start'] - start:.2f}–{sentence['end'] - start:.2f}s</td><td>"
                + html.escape(sentence["english"]) + "</td></tr>"
            )
        flags = ", ".join(sample["riskFlags"]) or "none"
        html_sections.append(f"""
<section><h2>Block {block_id}</h2>
<p>Reasons: {html.escape(', '.join(sample['selectionReasons']))}<br>Risk flags: <code>{html.escape(flags)}</code></p>
<audio controls src=\"{audio_name}\"></audio>
<table><thead><tr><th>ID</th><th>clip time</th><th>English</th></tr></thead><tbody>{''.join(rows)}</tbody></table></section>
""")
    (out / "sentence-anchors.srt").write_text("\n".join(srt_lines), encoding="utf-8")
    document = f"""<!doctype html><meta charset=\"utf-8\"><title>Expanded sentence anchor POC</title>
<style>body{{font:15px system-ui;max-width:1100px;margin:36px auto;padding:0 20px;line-height:1.5}}section{{border-top:1px solid #ccc;padding:20px 0}}audio{{width:100%}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ddd;padding:7px;text-align:left;vertical-align:top}}code{{background:#eee;padding:2px 4px}}</style>
<h1>Expanded sentence anchor POC</h1>
<p>Status: <code>{html.escape(report['status'])}</code>. Machine candidate only; listen to every boundary before acceptance.</p>
{''.join(html_sections)}
"""
    (review_dir / "index.html").write_text(document, encoding="utf-8")


def write_markdown(path: Path, report: dict) -> None:
    coverage = report["coverage"]
    aggregate = report["aggregate"]
    lines = [
        "# 扩大句级锚定 POC 报告",
        "",
        f"状态：`{report['status']}`；`releaseEligible=false`。",
        "",
        f"覆盖 {coverage['selectedBlocks']}/{coverage['totalBlocks']} 个区块（{coverage['blockPercent']:.1f}%），"
        f"{coverage['selectedWindowSeconds']:.2f}/{coverage['sermonSeconds']:.2f} 秒（{coverage['timePercent']:.1f}%），"
        f"共 {coverage['englishSentences']} 个英文句、{coverage['englishWords']} 个英文词。",
        "",
        f"当前中文末尾相对最后英文词的提前量：中位数 {aggregate['currentChineseEndLeadMedianSeconds']:.2f} 秒，"
        f"P95 {aggregate['currentChineseEndLeadP95Seconds']:.2f} 秒；"
        f">2 秒区块 {aggregate['blocksEndingOver2sEarly']} 个，>5 秒区块 {aggregate['blocksEndingOver5sEarly']} 个。",
        f"超过 15 秒的英文标点句 {aggregate['sourceSentencesOver15s']} 个；"
        f"最后一词贴近窗口末端、需要重点听审的区块 {aggregate['blocksWithLastWordAtWindowEnd']} 个。",
        "",
        "| Block | 选择原因 | 英文句/词 | 当前 cue | 中文提前结束 | 风险 |",
        "|---:|---|---:|---:|---:|---|",
    ]
    for sample in report["samples"]:
        lines.append(
            f"| {sample['blockId']} | {', '.join(sample['selectionReasons'])} | "
            f"{sample['counts']['englishSentences']}/{sample['counts']['englishWords']} | "
            f"{sample['counts']['currentChineseCues']} | "
            f"{sample['publishedChinese']['finishesBeforeLastEnglishWordBySeconds']:.2f}s | "
            f"{', '.join(sample['riskFlags']) or 'none'} |"
        )
    lines.extend([
        "",
        "本报告只扩大英文句锚的机器测试范围。中文逐句语义映射、边界听审和生产接入仍未完成。",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--week-id", required=True)
    parser.add_argument("--source-media", type=Path, required=True)
    parser.add_argument("--block-ids", default=",".join(str(value) for value in DEFAULT_BLOCKS))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--host", default="achillesjing@192.168.1.152")
    args = parser.parse_args()

    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    week = selected_week(catalog, args.week_id)
    if sha256(args.source_media) != week["sourceSha256"]:
        raise ValueError("Source media hash differs from published week")
    windows = block_windows(week)
    selected_ids = parse_block_ids(args.block_ids)
    missing = [block_id for block_id in selected_ids if block_id not in windows]
    if missing:
        raise ValueError(f"Selected block IDs do not exist: {missing}")
    args.out.mkdir(parents=True, exist_ok=True)
    sermon_duration = float(week["sourceEndSeconds"]) - float(week["sourceStartSeconds"])
    sermon_audio = args.out / "sermon-16k-mono.wav"
    extract_sermon_audio(args.source_media, sermon_audio, float(week["sourceStartSeconds"]), sermon_duration)
    chunks = [{
        "id": f"block-{block_id:02d}",
        "start": windows[block_id]["start"],
        "end": windows[block_id]["end"],
        "text": windows[block_id]["english"],
    } for block_id in selected_ids]
    write_json(args.out / "selection.json", {
        "schemaVersion": "sermon-expanded-sentence-anchor-selection-poc-v1",
        "weekId": week["id"],
        "selectedBlocks": [{**chunk, "reasons": SELECTION_REASONS.get(int(chunk["id"].split("-")[1]), ["operator_selected"])} for chunk in chunks],
    })
    segments = mfa_spark.align_reference_chunks(
        chunks,
        sermon_audio,
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
    report = build_anchor_report(
        week=week,
        windows=windows,
        selected_ids=selected_ids,
        segments=segments,
        catalog_path=args.catalog,
        source_path=args.source_media,
        sermon_audio=sermon_audio,
        segments_path=segments_path,
        manifest_path=manifest_path,
        runtime_path=runtime_path,
    )
    write_json(args.out / "report.json", report)
    write_markdown(args.out / "report.zh.md", report)
    write_review(args.out, report, sermon_audio)
    print(json.dumps({
        "status": report["status"],
        "coverage": report["coverage"],
        "aggregate": report["aggregate"],
        "report": str((args.out / "report.json").resolve()),
    }, ensure_ascii=False, indent=2))
    return 0 if report["structuralPass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
