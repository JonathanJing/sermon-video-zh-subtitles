#!/usr/bin/env python3
"""Bounded English transcript plus word-timeline POC.

Qwen3-ASR proposes English text for overlapping audio windows. The pinned
Qwen3 ForcedAligner maps that exact candidate back to word start/end times.
The result always requires review: forced alignment cannot prove that ASR did
not omit spoken words.
"""
from __future__ import annotations

import argparse
from array import array
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import wave


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DUBBING = ROOT / "experiments" / "sermon-dubbing-poc"
if str(DUBBING) not in sys.path:
    sys.path.insert(0, str(DUBBING))

from prepare_voice_candidates import ALIGNER, ASR  # noqa: E402


SCHEMA = "sermon-english-word-timeline-poc-v1"
TOKEN_RE = re.compile(r"[a-z0-9]+(?:['’][a-z0-9]+)?", re.I)


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


def normalized_tokens(text: str) -> list[str]:
    return [token.lower().replace("’", "'") for token in TOKEN_RE.findall(text or "")]


def media_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    duration = float(json.loads(result.stdout)["format"]["duration"])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Input audio must have a finite positive duration")
    return duration


def plan_windows(start: float, duration: float, window_seconds: float, overlap_seconds: float) -> list[dict]:
    if start < 0 or duration <= 0 or window_seconds <= 0:
        raise ValueError("Start, duration, and window size must describe a positive interval")
    if overlap_seconds < 0 or overlap_seconds >= window_seconds:
        raise ValueError("Overlap must be nonnegative and smaller than the window")
    end = start + duration
    step = window_seconds - overlap_seconds
    windows = []
    cursor = start
    while cursor < end - 1e-6:
        actual = min(window_seconds, end - cursor)
        index = len(windows)
        windows.append({
            "id": f"window-{index:04d}",
            "audioStart": round(cursor, 6),
            "duration": round(actual, 6),
            "keepStart": round(cursor if index == 0 else cursor + overlap_seconds / 2, 6),
            "keepEnd": None,
        })
        if cursor + actual >= end - 1e-6:
            break
        cursor += step
    for index, window in enumerate(windows):
        window_end = window["audioStart"] + window["duration"]
        window["keepEnd"] = round(end if index == len(windows) - 1 else window_end - overlap_seconds / 2, 6)
    return windows


def extract_window(source: Path, window: dict, target: Path) -> None:
    if target.exists():
        return
    subprocess.run([
        "ffmpeg", "-v", "error", "-n", "-i", str(source),
        "-ss", str(window["audioStart"]), "-t", str(window["duration"]),
        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(target),
    ], check=True)


def pcm_stats(path: Path) -> dict:
    with wave.open(str(path), "rb") as stream:
        if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate(), stream.getcomptype()) != (1, 2, 16000, "NONE"):
            raise ValueError("Expected mono 16-bit PCM 16 kHz WAV")
        samples = array("h")
        samples.frombytes(stream.readframes(stream.getnframes()))
    if sys.byteorder != "little":
        samples.byteswap()
    if not samples:
        raise ValueError("Extracted window is empty")
    squares = sum(value * value for value in samples)
    nonzero = sum(value != 0 for value in samples)
    return {
        "sampleCount": len(samples),
        "nonzeroSampleCount": nonzero,
        "peakPcm": max(abs(value) for value in samples),
        "rmsPcm": round(math.sqrt(squares / len(samples)), 6),
        "exactlyZeroPcm": nonzero == 0,
    }


def aligned_words(text: str, segments: list[dict], window: dict, timeline_offset: float) -> tuple[list[dict], list[dict]]:
    issues = []
    transcript_tokens = normalized_tokens(text)
    aligned_tokens = [token for segment in segments for token in normalized_tokens(str(segment.get("text", "")))]
    if transcript_tokens != aligned_tokens:
        issues.append({
            "type": "aligner_token_sequence_differs_from_asr",
            "windowId": window["id"],
            "asrTokenCount": len(transcript_tokens),
            "alignedTokenCount": len(aligned_tokens),
        })
    words = []
    previous_end = 0.0
    for index, segment in enumerate(segments):
        text_value = str(segment.get("text", "")).strip()
        tokens = normalized_tokens(text_value)
        start = segment.get("start")
        end = segment.get("end")
        valid = (
            not isinstance(start, bool) and not isinstance(end, bool)
            and isinstance(start, (int, float)) and isinstance(end, (int, float))
            and math.isfinite(start) and math.isfinite(end)
            and 0 <= start < end <= window["duration"] + 0.1
            and start >= previous_end - 1e-3
            and len(tokens) == 1
        )
        if not valid:
            reasons = []
            if len(tokens) != 1:
                reasons.append("not_exactly_one_normalized_word")
            if (isinstance(start, bool) or isinstance(end, bool)
                    or not isinstance(start, (int, float)) or not isinstance(end, (int, float))
                    or not math.isfinite(start) or not math.isfinite(end)):
                reasons.append("nonfinite_or_nonnumeric_time")
            elif start < 0 or end > window["duration"] + 0.1:
                reasons.append("time_outside_window")
            elif end <= start:
                reasons.append("zero_or_negative_duration")
            elif start < previous_end - 1e-3:
                reasons.append("nonmonotonic_or_overlapping_word")
            issues.append({
                "type": "invalid_aligned_word", "windowId": window["id"], "segmentIndex": index,
                "text": text_value, "start": start, "end": end, "reasons": reasons,
            })
            continue
        previous_end = float(end)
        absolute_start = window["audioStart"] + float(start)
        absolute_end = window["audioStart"] + float(end)
        midpoint = (absolute_start + absolute_end) / 2
        if not window["keepStart"] <= midpoint <= window["keepEnd"]:
            continue
        words.append({
            "text": text_value,
            "normalized": tokens[0],
            "audioStart": round(absolute_start, 6),
            "audioEnd": round(absolute_end, 6),
            "timelineStart": round(timeline_offset + absolute_start, 6),
            "timelineEnd": round(timeline_offset + absolute_end, 6),
            "windowId": window["id"],
        })
    return words, issues


def build_report(*, source: Path, source_id: str | None, source_duration: float, requested_start: float,
                 requested_duration: float, timeline_offset: float, windows: list[dict], gap_seconds: float) -> dict:
    words = []
    issues = []
    model_runs = []
    for window in windows:
        window_dir = Path(window["directory"])
        asr = json.loads((window_dir / "asr.json").read_text(encoding="utf-8"))
        alignment_path = window_dir / "alignment.json"
        segments = json.loads(alignment_path.read_text(encoding="utf-8"))["words"] if alignment_path.exists() else []
        selected, window_issues = aligned_words(asr.get("text", ""), segments, window, timeline_offset)
        words.extend(selected)
        issues.extend(window_issues)
        if asr.get("status") == "rejected_exact_zero_pcm":
            issues.append({"type": "exact_zero_pcm_window", "windowId": window["id"]})
        if not normalized_tokens(asr.get("text", "")):
            issues.append({"type": "empty_asr_window", "windowId": window["id"]})
        model_runs.append({
            "windowId": window["id"],
            "audioSha256": asr["audioSha256"],
            "pcm": asr["pcm"],
            "asr": asr.get("model"),
            "aligner": json.loads(alignment_path.read_text(encoding="utf-8")).get("model") if alignment_path.exists() else None,
            "rawTranscript": asr.get("text", ""),
        })
    words.sort(key=lambda item: (item["audioStart"], item["audioEnd"]))
    for index, word in enumerate(words, start=1):
        word["index"] = index
        if index > 1:
            previous = words[index - 2]
            gap = word["audioStart"] - previous["audioEnd"]
            if gap < -1e-3:
                issues.append({"type": "merged_word_timeline_overlap", "leftIndex": index - 1, "rightIndex": index, "seconds": round(gap, 6)})
            elif gap > gap_seconds:
                issues.append({
                    "type": "possible_silence_or_missing_transcript",
                    "leftIndex": index - 1,
                    "rightIndex": index,
                    "audioStart": previous["audioEnd"],
                    "audioEnd": word["audioStart"],
                    "seconds": round(gap, 6),
                })
    requested_end = requested_start + requested_duration
    if words:
        if words[0]["audioStart"] - requested_start > gap_seconds:
            issues.append({"type": "leading_uncovered_interval", "audioStart": requested_start, "audioEnd": words[0]["audioStart"]})
        if requested_end - words[-1]["audioEnd"] > gap_seconds:
            issues.append({"type": "trailing_uncovered_interval", "audioStart": words[-1]["audioEnd"], "audioEnd": requested_end})
    structural = {"aligner_token_sequence_differs_from_asr", "invalid_aligned_word", "merged_word_timeline_overlap"}
    status = "invalid_alignment" if any(issue["type"] in structural for issue in issues) else "machine_candidate_requires_review"
    if not words:
        status = "no_word_timeline_requires_review"
    issues.append({
        "type": "transcript_completeness_unproven",
        "detail": "Forced alignment times the ASR candidate; it cannot prove that ASR preserved every spoken word.",
    })
    return {
        "schemaVersion": SCHEMA,
        "status": status,
        "humanReview": "pending",
        "transcriptCompletenessProven": False,
        "input": {
            "sourceId": source_id,
            "path": str(source),
            "sha256": sha256(source),
            "durationSeconds": round(source_duration, 6),
            "requestedStartSeconds": requested_start,
            "requestedDurationSeconds": requested_duration,
            "timelineOffsetSeconds": timeline_offset,
        },
        "models": {"asrRequested": list(ASR), "alignerRequested": list(ALIGNER)},
        "windowCount": len(windows),
        "wordCount": len(words),
        "wordSequenceText": " ".join(word["text"] for word in words),
        "words": words,
        "reviewItems": issues,
        "modelRuns": model_runs,
        "limitations": [
            "ASR omissions and substitutions require comparison with audio or an independently reviewed transcript.",
            "Large gaps can be silence or missing speech; this POC does not classify them.",
            "Model timing is an estimate and has not been human accepted.",
        ],
    }


def write_tsv(path: Path, words: list[dict]) -> None:
    lines = ["index\ttext\taudio_start\taudio_end\ttimeline_start\ttimeline_end\twindow_id"]
    for word in words:
        safe = word["text"].replace("\t", " ").replace("\n", " ")
        lines.append(f'{word["index"]}\t{safe}\t{word["audioStart"]:.6f}\t{word["audioEnd"]:.6f}\t{word["timelineStart"]:.6f}\t{word["timelineEnd"]:.6f}\t{word["windowId"]}')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source-id")
    parser.add_argument("--start-seconds", type=float, default=0.0)
    parser.add_argument("--duration-seconds", type=float, default=60.0)
    parser.add_argument("--timeline-offset-seconds", type=float, default=0.0)
    parser.add_argument("--window-seconds", type=float, default=60.0)
    parser.add_argument("--overlap-seconds", type=float, default=10.0)
    parser.add_argument("--review-gap-seconds", type=float, default=2.0)
    args = parser.parse_args()
    source = args.audio.expanduser().resolve()
    if not source.is_file():
        raise ValueError(f"Audio does not exist: {source}")
    source_duration = media_duration(source)
    if args.duration_seconds <= 0 or args.duration_seconds > 300:
        raise ValueError("Bounded POC duration must be greater than 0 and at most 300 seconds")
    if args.start_seconds < 0 or args.start_seconds + args.duration_seconds > source_duration + 0.05:
        raise ValueError("Requested interval is outside the input audio")
    out = args.out.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    if (out / "report.json").exists():
        raise ValueError("Preserve completed POC output; choose a fresh output directory")
    windows = plan_windows(args.start_seconds, args.duration_seconds, args.window_seconds, args.overlap_seconds)
    for window in windows:
        directory = out / window["id"]
        directory.mkdir(exist_ok=True)
        window["directory"] = str(directory)
        wav = directory / "audio.wav"
        extract_window(source, window, wav)
        window["audioSha256"] = sha256(wav)
        window["pcm"] = pcm_stats(wav)

    from speech_backend import SpeechModel

    asr_model = None
    for window in windows:
        directory = Path(window["directory"])
        receipt = directory / "asr.json"
        if receipt.exists():
            cached = json.loads(receipt.read_text(encoding="utf-8"))
            if cached.get("audioSha256") != window["audioSha256"] or cached.get("requestedModel") != list(ASR):
                raise ValueError(f"Stale ASR cache: {window['id']}")
            continue
        if window["pcm"]["exactlyZeroPcm"]:
            write_json(receipt, {
                "status": "rejected_exact_zero_pcm", "audioSha256": window["audioSha256"],
                "pcm": window["pcm"], "requestedModel": list(ASR), "model": None, "text": "",
            })
            continue
        if asr_model is None:
            asr_model = SpeechModel(ASR)
        result = asr_model.generate(str(directory / "audio.wav"), language="English", max_tokens=2048)
        write_json(receipt, {
            "status": "asr_candidate", "audioSha256": window["audioSha256"], "pcm": window["pcm"],
            "requestedModel": list(ASR), "model": list(asr_model.model), "inferenceReceipt": asr_model.last_receipt,
            "text": str(result.text or "").strip(),
        })
    del asr_model

    aligner_model = None
    for window in windows:
        directory = Path(window["directory"])
        asr = json.loads((directory / "asr.json").read_text(encoding="utf-8"))
        text = asr.get("text", "")
        if not normalized_tokens(text):
            continue
        receipt = directory / "alignment.json"
        if receipt.exists():
            cached = json.loads(receipt.read_text(encoding="utf-8"))
            if cached.get("audioSha256") != window["audioSha256"] or cached.get("transcriptSha256") != hashlib.sha256(text.encode()).hexdigest():
                raise ValueError(f"Stale alignment cache: {window['id']}")
            continue
        if aligner_model is None:
            aligner_model = SpeechModel(ALIGNER)
        result = aligner_model.generate(str(directory / "audio.wav"), text=text, language="English")
        write_json(receipt, {
            "status": "aligned_candidate", "audioSha256": window["audioSha256"],
            "transcriptSha256": hashlib.sha256(text.encode()).hexdigest(),
            "requestedModel": list(ALIGNER), "model": list(aligner_model.model),
            "inferenceReceipt": aligner_model.last_receipt, "words": result.segments,
        })
    del aligner_model

    report = build_report(
        source=source, source_id=args.source_id, source_duration=source_duration,
        requested_start=args.start_seconds, requested_duration=args.duration_seconds,
        timeline_offset=args.timeline_offset_seconds, windows=windows, gap_seconds=args.review_gap_seconds,
    )
    write_json(out / "report.json", report)
    write_tsv(out / "word-timeline.tsv", report["words"])
    (out / "transcript.txt").write_text(report["wordSequenceText"] + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"], "words": report["wordCount"],
        "reviewItems": len(report["reviewItems"]), "report": str(out / "report.json"),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
