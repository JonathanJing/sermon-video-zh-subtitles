#!/usr/bin/env python3
"""Build the Chinese-English reading PDF from a live-service capture.

This adapter connects the capture experiment to the existing production
reading chain:

  sermon.english.jsonl
    -> caption-time reading segments (deterministic, synthetic timing)
    -> English correction (OpenAI, optional)
    -> Chinese translation (OpenAI, cached by the production pipeline)
    -> reading-edition-v2 SRTs (existing 2-pass editor)
    -> sermon_zh_en_reading.pdf (existing mobile_pdf reading layout)

The capture keeps the whole 10:00–11:20 service.  A human supplies the sermon
window first (mark_window.py); extract_sermon.py selects the source lines;
this adapter turns them into the two JSON files the reading editor consumes.

Default behaviour is a plan: it writes the deterministic segments and prints
the commands, without calling a model.  Paid stages require ``--execute`` and
an explicit OpenAI environment launched by
``tools/ops/run_with_openai_environment.py --environment dev|prod``.

No YouTube URL, ASR, MFA or subtitle timing is fabricated: the English source
is the provider's live ASR captions and its timing is marked
``caption_arrival_synthetic_not_for_subtitles``.  The Chinese is our machine
translation, not the service's Mandarin feed and not a human approval.

Usage
-----
  # 1) after the human window is recorded
  .venv/bin/python experiments/live-translate-capture/build_reading_pdf.py \\
      --capture-dir artifacts/live-capture/mariners-north-irvine/2026-11-15

  # 2) paid run through the explicit environment
  python3 tools/ops/run_with_openai_environment.py --environment dev -- \\
      .venv/bin/python experiments/live-translate-capture/build_reading_pdf.py \\
      --capture-dir artifacts/live-capture/mariners-north-irvine/2026-11-15 --execute
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

EXPERIMENT = Path(__file__).resolve().parent
ROOT = EXPERIMENT.parents[1]
for path in (EXPERIMENT, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from scripts import tongxing_host  # noqa: E402,F401  binds the production package ports

import extract_sermon  # noqa: E402
from mark_window import iso_utc, parse_ts, read_json, sha256_file, write_json  # noqa: E402
from tongxing_production.compute.openai_runtime import selected_route  # noqa: E402
from tongxing_production.source.post_live_english import correct_english  # noqa: E402
from tongxing_production.workflows.dual_pdf.pipeline import (  # noqa: E402
    accounting_session,
    clean_text,
    load_glossary,
    qa_report,
    reference_chunks_to_reading_segments,
    translate_chinese,
)

SCHEMA = "live-capture-reading-build/v1"
DEFAULT_MODEL = "gpt-6.1-sol"
READING_DIRNAME = "reading-edition-v2"
CHUNK_TARGET_SECONDS = 45.0
CHUNK_TARGET_CHARS = 700
READING_SEGMENT_TARGET_CHARS = 420
CORRECTION_WINDOW_SECONDS = 240.0
DEFAULT_TITLE = "Mariners Church North Irvine 主日讲道"


@dataclass
class BuildSettings:
    capture_dir: Path
    outdir: Path
    title: str
    sermon_date: str
    speaker: str | None
    glossary: Path | None
    en_model: str
    zh_model: str
    reading_model: str
    reasoning_effort: str
    translation_workers: int
    no_english_cleanup: bool
    hide_timecodes: bool
    max_segments: int
    max_chars: int
    allow_large: bool


def estimate_duration(text: str) -> float:
    return max(1.5, min(8.0, len(text) / 17.0))


def build_caption_lines(rows: list[dict[str, Any]], window_start_offset: float) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    for row in rows:
        text = clean_text(str(row.get("text") or ""))
        if not text:
            continue
        try:
            start = max(0.0, float(row["offset_s"]) - window_start_offset)
        except (KeyError, TypeError, ValueError):
            continue
        lines.append({"start": round(start, 3), "text": text, "ts": row.get("ts")})
    lines.sort(key=lambda item: item["start"])
    for index, line in enumerate(lines):
        next_start = lines[index + 1]["start"] if index + 1 < len(lines) else None
        if next_start is not None and 0 < next_start - line["start"] <= 8.0:
            end = next_start
        else:
            end = line["start"] + estimate_duration(line["text"])
        line["end"] = round(max(line["start"] + 0.5, end), 3)
    return lines


def build_chunks(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []

    def flush() -> None:
        if not current:
            return
        chunks.append(
            {
                "start": current[0]["start"],
                "end": current[-1]["end"],
                "text": " ".join(item["text"] for item in current),
            }
        )
        current.clear()

    for line in lines:
        if current:
            duration = line["end"] - current[0]["start"]
            chars = sum(len(item["text"]) for item in current) + 1 + len(line["text"])
            if duration >= CHUNK_TARGET_SECONDS or chars > CHUNK_TARGET_CHARS:
                flush()
        current.append(line)
    flush()
    return chunks


def window_label(start: datetime, end: datetime, timezone_name: str) -> str:
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(timezone_name)
    return f"{start.astimezone(tz):%H:%M:%S}-{end.astimezone(tz):%H:%M:%S}"


def load_build_inputs(settings: BuildSettings) -> dict[str, Any]:
    capture_dir = settings.capture_dir.resolve()
    capture_path = capture_dir / "capture.json"
    if not capture_path.exists():
        raise ValueError(f"no capture manifest at {capture_path}")
    capture = read_json(capture_path, "capture manifest")
    window_path = capture_dir / "sermon.window.json"
    if not window_path.exists():
        raise ValueError(
            f"no sermon window at {window_path}; review the service and run mark_window.py first"
        )
    from mark_window import check_window

    check_window(capture_dir, out=window_path)
    window_payload = read_json(window_path, "sermon window")
    window = window_payload["sermon_window"]
    window_start = parse_ts(window["start"])
    window_end = parse_ts(window["end"])
    actual_start = parse_ts(capture["window"]["actual_start"])

    sermon_path = capture_dir / "sermon.english.jsonl"
    # Re-run the deterministic window extraction so a changed sermon.window.json
    # can never leave a stale sermon.english.jsonl behind.
    extract_sermon.extract(capture_dir)
    rows = extract_sermon.read_jsonl(sermon_path)
    if not rows:
        raise ValueError(f"sermon.english.jsonl is empty: {sermon_path}")

    lines = build_caption_lines(rows, (window_start - actual_start).total_seconds())
    if not lines:
        raise ValueError("no usable English lines inside the sermon window")
    chunks = build_chunks(lines)
    segments = reference_chunks_to_reading_segments(
        chunks, target_chars=READING_SEGMENT_TARGET_CHARS
    )
    if not segments:
        raise ValueError("reading segment builder returned no segments")

    outdir = settings.outdir.resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    raw_path = outdir / "segments_timed_en_raw.json"
    write_json(raw_path, segments)
    return {
        "capture": capture,
        "capture_path": capture_path,
        "window": window_payload,
        "window_path": window_path,
        "window_start": window_start,
        "window_end": window_end,
        "actual_start": actual_start,
        "lines": lines,
        "chunks": chunks,
        "segments": segments,
        "raw_path": raw_path,
        "outdir": outdir,
        "sermon_path": sermon_path,
    }


def reading_edition_command(settings: BuildSettings, outdir: Path) -> list[str]:
    return [
        sys.executable,
        str(ROOT / "scripts" / "build_sermon_reading_edition_with_openai.py"),
        "--source-pipeline",
        str(outdir),
        "--outdir",
        str(outdir / READING_DIRNAME),
        "--provider",
        "openai",
        "--model",
        settings.reading_model,
        "--reasoning-effort",
        settings.reasoning_effort,
        "--passes",
        "2",
        "--preferred-seconds",
        "24.0",
        "--preferred-english-chars",
        "420",
        "--hard-seconds",
        "55.0",
        "--hard-english-chars",
        "840",
    ]


def pdf_command(
    settings: BuildSettings,
    outdir: Path,
    *,
    start: datetime,
    end: datetime,
    timezone_name: str,
) -> list[str]:
    command = [
        sys.executable,
        str(ROOT / "tools" / "ops" / "run.py"),
        "workflows.dual_pdf.mobile_pdf",
        "--layout",
        "reading",
        "--input",
        str(outdir / READING_DIRNAME / "sermon_zh_reading_revised.srt"),
        "--secondary-input",
        str(outdir / READING_DIRNAME / "sermon_en_reading_revised.srt"),
        "--out",
        str(outdir / "sermon_zh_en_reading.pdf"),
        "--title",
        settings.title,
        "--subtitle",
        "中英对照阅读版",
        "--sermon-date",
        settings.sermon_date,
        "--sermon-window",
        window_label(start, end, timezone_name),
    ]
    if settings.speaker:
        command.extend(["--speaker", settings.speaker])
    if settings.hide_timecodes:
        command.append("--hide-timecodes")
    return command


def make_plan(settings: BuildSettings) -> dict[str, Any]:
    inputs = load_build_inputs(settings)
    segments = inputs["segments"]
    chars = sum(len(item["text"]) for item in segments)
    if len(segments) > settings.max_segments and not settings.allow_large:
        raise ValueError(
            f"{len(segments)} reading segments exceeds --max-segments {settings.max_segments}; "
            "review the input or pass --allow-large"
        )
    if chars > settings.max_chars and not settings.allow_large:
        raise ValueError(
            f"{chars} English characters exceeds --max-chars {settings.max_chars}; "
            "review the input or pass --allow-large"
        )
    timezone_name = (inputs["capture"].get("host") or {}).get(
        "timezone", "America/Los_Angeles"
    )
    plan = {
        "schema": SCHEMA,
        "status": "planned",
        "capture": {
            "dir": str(settings.capture_dir.resolve()),
            "manifest_sha256": sha256_file(inputs["capture_path"]),
        },
        "window": {
            "file": str(inputs["window_path"]),
            "sha256": sha256_file(inputs["window_path"]),
            "start": iso_utc(inputs["window_start"]),
            "end": iso_utc(inputs["window_end"]),
            "label": window_label(inputs["window_start"], inputs["window_end"], timezone_name),
            "approved_by": inputs["window"].get("approved_by"),
        },
        "source": {
            "english": str(inputs["sermon_path"]),
            "sha256": sha256_file(inputs["sermon_path"]),
            "caption_lines": len(inputs["lines"]),
            "reading_segments": len(segments),
            "english_characters": chars,
        },
        "models": {
            "englishCorrection": None if settings.no_english_cleanup else settings.en_model,
            "chineseTranslation": settings.zh_model,
            "readingEdition": settings.reading_model,
            "reasoningEffort": settings.reasoning_effort,
        },
        "commands": {
            "englishCorrection": "in-process tongxing_production.source.post_live_english.correct_english",
            "chineseTranslation": "in-process tongxing_production.workflows.dual_pdf.pipeline.translate_chinese",
            "readingEdition": reading_edition_command(settings, inputs["outdir"]),
            "pdf": pdf_command(
                settings,
                inputs["outdir"],
                start=inputs["window_start"],
                end=inputs["window_end"],
                timezone_name=timezone_name,
            ),
        },
        "notes": [
            "Plan only: no model was called.",
            "English is the provider's live ASR captions with synthetic reading-layout timing, not subtitle timing.",
            "Mandarin from the service is not used here; the Chinese is our own translation.",
            "Run --execute under tools/ops/run_with_openai_environment.py --environment dev|prod.",
        ],
        "rawSegments": str(inputs["raw_path"]),
    }
    write_json(inputs["outdir"] / "reading.plan.json", plan)
    return plan


def _require_explicit_route() -> str:
    if selected_route() is None:
        raise ValueError(
            "paid stages require an explicit OpenAI environment; run through "
            "tools/ops/run_with_openai_environment.py --environment dev|prod"
        )
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not set by the explicit environment launcher")
    return api_key


def execute_plan(
    settings: BuildSettings,
    *,
    correct_fn: Callable[..., list[dict[str, Any]]] = correct_english,
    translate_fn: Callable[..., list[dict[str, Any]]] = translate_chinese,
    qa_fn: Callable[..., dict[str, Any]] = qa_report,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    api_key: str | None = None,
    route_check: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    if route_check is not None:
        route_check()
    else:
        api_key = _require_explicit_route()
    api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not set")

    inputs = load_build_inputs(settings)
    outdir = inputs["outdir"]
    glossary = load_glossary(settings.glossary)
    segments = inputs["segments"]
    chars = sum(len(item["text"]) for item in segments)
    if len(segments) > settings.max_segments and not settings.allow_large:
        raise ValueError(f"{len(segments)} segments exceeds --max-segments {settings.max_segments}")
    if chars > settings.max_chars and not settings.allow_large:
        raise ValueError(f"{chars} characters exceeds --max-chars {settings.max_chars}")

    with accounting_session(outdir / "accounting", "live_capture_reading"):
        if settings.no_english_cleanup:
            corrected = segments
            write_json(outdir / "segments_timed_en_corrected.json", corrected)
        else:
            corrected = correct_fn(
                api_key,
                segments,
                inputs["chunks"],
                outdir,
                settings.en_model,
                glossary,
                CORRECTION_WINDOW_SECONDS,
                reasoning_effort=settings.reasoning_effort,
            )
        write_json(outdir / "segments_timed_en_corrected.json", corrected)
        translated = translate_fn(
            api_key,
            corrected,
            outdir,
            settings.zh_model,
            glossary,
            reasoning_effort=settings.reasoning_effort,
            workers=max(1, settings.translation_workers),
        )
        write_json(outdir / "segments_timed_zh.json", translated)
        qa = qa_fn(corrected, translated, glossary)
        write_json(outdir / "qa_report.json", qa)
    if qa.get("hardFailures"):
        raise ValueError(f"pipeline QA has hard failures: {qa['hardFailures']}")

    reading_command = reading_edition_command(settings, outdir)
    reading_run = runner(reading_command, check=False)
    if reading_run.returncode != 0:
        raise RuntimeError(
            f"reading edition failed with exit {reading_run.returncode}; see {outdir / READING_DIRNAME}"
        )
    quality_path = outdir / READING_DIRNAME / "reading_quality_report.json"
    quality = read_json(quality_path, "reading quality report")
    if quality.get("status") != "pass":
        raise RuntimeError(
            f"reading edition quality status is {quality.get('status')!r}; refusing to build the PDF"
        )

    timezone_name = (inputs["capture"].get("host") or {}).get(
        "timezone", "America/Los_Angeles"
    )
    render_command = pdf_command(
        settings,
        outdir,
        start=inputs["window_start"],
        end=inputs["window_end"],
        timezone_name=timezone_name,
    )
    render_run = runner(render_command, check=False)
    if render_run.returncode != 0:
        raise RuntimeError(f"PDF render failed with exit {render_run.returncode}")
    pdf_path = outdir / "sermon_zh_en_reading.pdf"
    if not pdf_path.exists() or pdf_path.stat().st_size == 0:
        raise RuntimeError(f"PDF was not produced: {pdf_path}")

    manifest = {
        "schema": SCHEMA,
        "status": "completed",
        "generated_at": iso_utc(datetime.now(timezone.utc)),
        "capture": {
            "dir": str(settings.capture_dir.resolve()),
            "manifest_sha256": sha256_file(inputs["capture_path"]),
        },
        "window": {
            "file": str(inputs["window_path"]),
            "sha256": sha256_file(inputs["window_path"]),
            "start": iso_utc(inputs["window_start"]),
            "end": iso_utc(inputs["window_end"]),
            "approved_by": inputs["window"].get("approved_by"),
        },
        "source": {
            "english": str(inputs["sermon_path"]),
            "sha256": sha256_file(inputs["sermon_path"]),
            "caption_lines": len(inputs["lines"]),
            "reading_segments": len(corrected),
            "english_characters": sum(len(item["text"]) for item in corrected),
            "timing": "caption_arrival_synthetic_not_for_subtitles",
        },
        "models": {
            "englishCorrection": None if settings.no_english_cleanup else settings.en_model,
            "chineseTranslation": settings.zh_model,
            "readingEdition": settings.reading_model,
            "reasoningEffort": settings.reasoning_effort,
            "translationWorkers": max(1, settings.translation_workers),
        },
        "qa": qa,
        "readingQuality": {
            "status": quality.get("status"),
            "file": str(quality_path),
            "sha256": sha256_file(quality_path),
        },
        "outputs": {
            "englishCorrected": str(outdir / "segments_timed_en_corrected.json"),
            "chinese": str(outdir / "segments_timed_zh.json"),
            "readingDirectory": str(outdir / READING_DIRNAME),
            "pdf": str(pdf_path),
            "pdf_sha256": sha256_file(pdf_path),
        },
        "commands": {
            "readingEdition": reading_command,
            "pdf": render_command,
        },
        "argv": sys.argv[1:],
        "note": (
            "English is live provider ASR with synthetic reading timing; Chinese is our machine "
            "translation; no human review is recorded here."
        ),
    }
    write_json(outdir / "reading.manifest.json", manifest)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the Chinese-English reading PDF from a live capture."
    )
    parser.add_argument("--capture-dir", type=Path, required=True)
    parser.add_argument("--outdir", type=Path, default=None)
    parser.add_argument("--title", default=DEFAULT_TITLE)
    parser.add_argument("--sermon-date", default=None)
    parser.add_argument("--speaker", default=None)
    parser.add_argument("--glossary", type=Path, default=None)
    parser.add_argument("--en-model", default=DEFAULT_MODEL)
    parser.add_argument("--zh-model", default=DEFAULT_MODEL)
    parser.add_argument("--reading-model", default=DEFAULT_MODEL)
    parser.add_argument("--reasoning-effort", choices=("low", "medium", "high"), default="high")
    parser.add_argument("--translation-workers", type=int, default=1)
    parser.add_argument("--no-english-cleanup", action="store_true")
    parser.add_argument("--hide-timecodes", action="store_true")
    parser.add_argument("--max-segments", type=int, default=400)
    parser.add_argument("--max-chars", type=int, default=120_000)
    parser.add_argument("--allow-large", action="store_true")
    parser.add_argument("--execute", action="store_true", help="run paid model stages")
    return parser


def settings_from_args(args: argparse.Namespace) -> BuildSettings:
    capture_dir = args.capture_dir.resolve()
    capture = read_json(capture_dir / "capture.json", "capture manifest")
    timezone_name = (capture.get("host") or {}).get("timezone", "America/Los_Angeles")
    from zoneinfo import ZoneInfo

    actual_start = parse_ts(capture["window"]["actual_start"])
    sermon_date = args.sermon_date or actual_start.astimezone(ZoneInfo(timezone_name)).date().isoformat()
    return BuildSettings(
        capture_dir=capture_dir,
        outdir=(args.outdir or capture_dir / "reading").resolve(),
        title=args.title,
        sermon_date=sermon_date,
        speaker=args.speaker,
        glossary=args.glossary,
        en_model=args.en_model,
        zh_model=args.zh_model,
        reading_model=args.reading_model,
        reasoning_effort=args.reasoning_effort,
        translation_workers=max(1, args.translation_workers),
        no_english_cleanup=args.no_english_cleanup,
        hide_timecodes=args.hide_timecodes,
        max_segments=args.max_segments,
        max_chars=args.max_chars,
        allow_large=args.allow_large,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = settings_from_args(args)
        result = execute_plan(settings) if args.execute else make_plan(settings)
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
