#!/usr/bin/env python3
"""Run a fail-closed local ASR benchmark over a frozen audio manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RSS_RE = re.compile(r"^\s*(\d+)\s+maximum resident set size\s*$", re.MULTILINE)
SCORABLE_REFERENCE_STATUSES = {
    "human_gold",
    "model_reviewed_reference",
    "gpt_reaudited_reference",
}
NON_SPEECH_CUE_RE = re.compile(
    r"[\[(][^\])]*(?:music|applause|laughter|cheering|silence)[^\])]*[\])]",
    re.IGNORECASE,
)
STANDALONE_NON_SPEECH_CUE_RE = re.compile(
    r"^\s*(?:(?:music|applause|laughter|cheering|silence)[\s.,!?;:/&+_-]*)+$",
    re.IGNORECASE,
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audio_duration_seconds(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(json.loads(result.stdout)["format"]["duration"])


def normalize_words(text: str) -> list[str]:
    without_cues = NON_SPEECH_CUE_RE.sub(" ", text)
    if STANDALONE_NON_SPEECH_CUE_RE.fullmatch(without_cues):
        return []
    return re.findall(r"[a-z0-9']+", without_cues.casefold())


def contains_term(text: str, term: str) -> bool:
    words = normalize_words(text)
    term_words = normalize_words(term)
    return bool(term_words) and any(
        words[index : index + len(term_words)] == term_words
        for index in range(len(words) - len(term_words) + 1)
    )


def edit_distance(reference: list[str], hypothesis: list[str]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for row, ref_word in enumerate(reference, start=1):
        current = [row]
        for column, hyp_word in enumerate(hypothesis, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (ref_word != hyp_word),
                )
            )
        previous = current
    return previous[-1]


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * quantile)))
    return round(ordered[index], 4)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument(
        "--backend",
        choices=("whisper-cpp", "nemo-speech", "mlx-whisper", "mlx-audio-qwen3"),
        default="whisper-cpp",
    )
    parser.add_argument(
        "--model-artifact",
        help="File inside a model directory whose SHA-256 pins the model weights",
    )
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--model-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--binary", default="whisper-cli")
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--beam-size", type=int, default=1)
    parser.add_argument("--best-of", type=int, default=1)
    parser.add_argument("--language", default="en")
    parser.add_argument("--device", default="metal")
    parser.add_argument("--allow-temperature-fallback", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest_path = args.manifest.resolve()
    model_path = args.model.resolve()
    model_artifact_path = (
        (model_path / args.model_artifact).resolve()
        if args.model_artifact
        else model_path
    )
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(exist_ok=True)
    prepared_audio_dir = output_dir / "prepared-audio"
    prepared_audio_dir.mkdir(exist_ok=True)

    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schemaVersion") != "local-asr-audio-manifest-v1":
        raise SystemExit("Unsupported ASR manifest schema")
    if not model_path.exists():
        raise SystemExit(f"Model not found: {model_path}")
    if not model_artifact_path.is_file():
        raise SystemExit(f"Model artifact not found: {model_artifact_path}")
    observed_model_sha = sha256_file(model_artifact_path)
    if observed_model_sha != args.model_sha256:
        raise SystemExit("Model SHA-256 mismatch")

    runtime_command = (
        [args.binary, "--version"]
        if args.backend not in {"mlx-whisper", "mlx-audio-qwen3"}
        else ["uv", "tool", "list"]
    )
    runtime = subprocess.run(runtime_command, capture_output=True, text=True, timeout=30)
    runtime_output = (runtime.stdout + runtime.stderr).strip()
    if args.backend in {"mlx-whisper", "mlx-audio-qwen3"}:
        runtime_prefix = "mlx-whisper " if args.backend == "mlx-whisper" else "mlx-audio "
        executable_prefix = (
            "- mlx_whisper" if args.backend == "mlx-whisper" else "- mlx_audio.stt.generate"
        )
        runtime_output = "\n".join(
            line
            for line in runtime_output.splitlines()
            if line.startswith((runtime_prefix, executable_prefix))
        )
    runtime_fingerprint = runtime_output or f"{args.backend}: {args.binary}"
    predictions: list[dict] = []

    for item in manifest["items"]:
        item_id = item["id"]
        audio_path = (REPO_ROOT / item["audioPath"]).resolve()
        if not audio_path.is_file():
            raise SystemExit(f"Audio not found: {audio_path}")
        observed_audio_sha = sha256_file(audio_path)
        if observed_audio_sha != item["audioSha256"]:
            raise SystemExit(f"Audio SHA-256 mismatch: {item_id}")
        duration = audio_duration_seconds(audio_path)
        if abs(duration - float(item["durationSeconds"])) > 0.05:
            raise SystemExit(f"Audio duration mismatch: {item_id}")

        inference_audio_path = audio_path
        audio_preprocessed = False
        if audio_path.suffix.casefold() not in {".wav", ".mp3", ".flac", ".ogg"}:
            inference_audio_path = prepared_audio_dir / f"{item_id}.wav"
            conversion = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-v",
                    "error",
                    "-i",
                    str(audio_path),
                    "-ar",
                    "16000",
                    "-ac",
                    "1",
                    "-c:a",
                    "pcm_s16le",
                    str(inference_audio_path),
                ],
                capture_output=True,
                text=True,
            )
            if conversion.returncode != 0 or not inference_audio_path.is_file():
                raise SystemExit(f"Audio conversion failed: {item_id}: {conversion.stderr}")
            if abs(audio_duration_seconds(inference_audio_path) - duration) > 0.05:
                raise SystemExit(f"Converted audio duration mismatch: {item_id}")
            audio_preprocessed = True

        prefix = raw_dir / item_id
        json_path = prefix.with_suffix(".json")
        if args.backend == "whisper-cpp":
            command = [
                "/usr/bin/time", "-lp", args.binary,
                "-m", str(model_path), "-f", str(inference_audio_path),
                "-l", args.language, "-t", str(args.threads),
                "-bs", str(args.beam_size), "-bo", str(args.best_of),
                "-tp", "0", "-ojf", "-of", str(prefix), "-np",
            ]
            if not args.allow_temperature_fallback:
                command.append("-nf")
        elif args.backend == "nemo-speech":
            command = [
                "/usr/bin/time", "-lp", args.binary, "transcribe",
                str(inference_audio_path), "--model", str(model_path),
                "--device", args.device, "--language", args.language,
                "--format", "json", "--output", str(json_path), "--force",
            ]
        elif args.backend == "mlx-whisper":
            command = [
                "/usr/bin/time", "-lp", args.binary, str(inference_audio_path),
                "--model", str(model_path), "--output-name", item_id,
                "--output-dir", str(raw_dir), "--output-format", "json",
                "--verbose", "False", "--language", args.language,
                "--temperature", "0", "--condition-on-previous-text", "False",
            ]
        else:
            command = [
                "/usr/bin/time", "-lp", args.binary,
                "--model", str(model_path), "--audio", str(inference_audio_path),
                "--output-path", str(prefix), "--format", "json",
                "--language", args.language,
            ]
        started = time.monotonic()
        completed = subprocess.run(command, capture_output=True, text=True)
        latency = time.monotonic() - started
        (prefix.with_suffix(".stdout.txt")).write_text(completed.stdout)
        (prefix.with_suffix(".stderr.txt")).write_text(completed.stderr)

        transcript = ""
        parse_error = None
        if completed.returncode == 0 and json_path.is_file():
            try:
                payload = json.loads(json_path.read_text())
                if args.backend == "whisper-cpp":
                    transcript = "".join(
                        segment.get("text", "")
                        for segment in payload.get("transcription", [])
                    ).strip()
                else:
                    transcript = str(payload.get("text", "")).strip()
            except (json.JSONDecodeError, TypeError) as exc:
                parse_error = str(exc)
        elif not json_path.is_file():
            parse_error = "missing_json_output"
        rss_match = RSS_RE.search(completed.stderr)
        peak_rss_bytes = int(rss_match.group(1)) if rss_match else None

        record = {
            "id": item_id,
            "sermonId": item["sermonId"],
            "audioPath": item["audioPath"],
            "audioSha256": observed_audio_sha,
            "durationSeconds": round(duration, 3),
            "referenceStatus": item["referenceStatus"],
            "speechExpected": item.get("speechExpected", True),
            "audioPreprocessedToPcmWav": audio_preprocessed,
            "transcript": transcript,
            "nonempty": bool(normalize_words(transcript)),
            "exitCode": completed.returncode,
            "parseError": parse_error,
            "latencySeconds": round(latency, 4),
            "rtf": round(latency / duration, 4),
            "peakRssGiB": round(peak_rss_bytes / (1024**3), 4) if peak_rss_bytes else None,
        }
        record["outputValid"] = bool(
            completed.returncode == 0
            and parse_error is None
            and (record["nonempty"] or not record["speechExpected"])
        )

        reference = item.get("referenceText")
        if item["referenceStatus"] in SCORABLE_REFERENCE_STATUSES:
            if "referenceText" not in item:
                raise SystemExit(f"Scorable item lacks referenceText: {item_id}")
            if item.get("speechExpected", True) and not normalize_words(reference):
                raise SystemExit(f"Speech item has empty reference: {item_id}")
            ref_words = normalize_words(reference)
            hyp_words = normalize_words(transcript)
            record["wordErrorCount"] = edit_distance(ref_words, hyp_words)
            record["referenceWordCount"] = len(ref_words)
            record["criticalTermHits"] = sum(
                contains_term(transcript, term) for term in item.get("criticalTerms", [])
            )
            record["criticalTermCount"] = len(item.get("criticalTerms", []))
        elif "referenceText" in item:
            raise SystemExit(f"Non-gold item must not include referenceText: {item_id}")
        predictions.append(record)

    prediction_path = output_dir / "predictions.jsonl"
    prediction_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in predictions)
    )
    latencies = [row["latencySeconds"] for row in predictions]
    rtfs = [row["rtf"] for row in predictions]
    scored = [row for row in predictions if row["referenceStatus"] in SCORABLE_REFERENCE_STATUSES]
    human_gold = [row for row in scored if row["referenceStatus"] == "human_gold"]
    model_reviewed = [row for row in scored if row["referenceStatus"] == "model_reviewed_reference"]
    gpt_reaudited = [row for row in scored if row["referenceStatus"] == "gpt_reaudited_reference"]
    reference_words = sum(row.get("referenceWordCount", 0) for row in scored)
    term_count = sum(row.get("criticalTermCount", 0) for row in scored)
    silence_items = [row for row in predictions if not row["speechExpected"]]
    hallucinations = sum(row["nonempty"] for row in silence_items)
    report = {
        "schemaVersion": "local-asr-run-report-v1",
        "completedAt": datetime.now(timezone.utc).isoformat(),
        "manifest": str(manifest_path.relative_to(REPO_ROOT)),
        "manifestSha256": sha256_file(manifest_path),
        "modelId": args.model_id,
        "modelSha256": observed_model_sha,
        "modelArtifact": str(model_artifact_path),
        "runtime": runtime_fingerprint,
        "decoding": {
            "backend": args.backend,
            "device": args.device if args.backend == "nemo-speech" else None,
            "language": args.language,
            "threads": args.threads,
            "beamSize": args.beam_size,
            "bestOf": args.best_of,
            "temperature": 0,
            "temperatureFallback": args.allow_temperature_fallback,
            "vad": False,
        },
        "itemCount": len(predictions),
        "successCount": sum(row["outputValid"] for row in predictions),
        "nonemptyCount": sum(row["nonempty"] for row in predictions),
        "emptyExpectedSpeechCount": sum(
            row["speechExpected"] and not row["nonempty"] for row in predictions
        ),
        "errorCount": sum(not row["outputValid"] for row in predictions),
        "totalAudioMinutes": round(sum(row["durationSeconds"] for row in predictions) / 60, 3),
        "latencySeconds": {
            "mean": round(statistics.mean(latencies), 4),
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "max": round(max(latencies), 4),
        },
        "rtf": {
            "mean": round(statistics.mean(rtfs), 4),
            "p50": percentile(rtfs, 0.50),
            "p95": percentile(rtfs, 0.95),
            "max": round(max(rtfs), 4),
        },
        "peakPerInvocationRssGiB": max(
            (row["peakRssGiB"] for row in predictions if row["peakRssGiB"] is not None),
            default=None,
        ),
        "quality": {
            "status": (
                "scored_human_gold"
                if human_gold and not model_reviewed
                else "scored_model_reviewed_reference"
                if model_reviewed and not human_gold
                else "scored_mixed_reference_tiers"
                if scored
                else "unavailable_no_scorable_reference"
            ),
            "scoredItemCount": len(scored),
            "humanGoldItemCount": len(human_gold),
            "modelReviewedReferenceItemCount": len(model_reviewed),
            "gptReauditedReferenceItemCount": len(gpt_reaudited),
            "wer": (
                round(sum(row["wordErrorCount"] for row in scored) / reference_words, 6)
                if reference_words
                else None
            ),
            "criticalTermRecall": (
                round(sum(row["criticalTermHits"] for row in scored) / term_count, 6)
                if term_count
                else None
            ),
            "silenceItemCount": len(silence_items),
            "silenceHallucinationCount": hallucinations if silence_items else None,
        },
        "performanceInterpretation": "Per-clip CLI cold-load offline run; not a persistent-provider or streaming latency result. Audio conversion, when required, is excluded from ASR latency.",
        "predictionsSha256": sha256_file(prediction_path),
    }
    (output_dir / "run-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["errorCount"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
