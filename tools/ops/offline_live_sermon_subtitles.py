#!/usr/bin/env python3
"""POC: extract sermon subtitles from a YouTube live archive link.

The script is intentionally conservative:
- It never bypasses access controls.
- It prefers existing public captions.
- If a live archive has no captions, it can discover a matching edited sermon VOD
  from the same channel and reuse that caption track while aligning it back to the
  live archive timeline.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import requests


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.cloud import access_secret as cloud_access_secret

DEFAULT_LANGS = ["en-orig", "en"]
DEFAULT_ASR_MODEL = "gpt-4o-transcribe"
FORBIDDEN_ASR_MODEL = "gpt-realtime-translate"
MAX_ASR_CHUNK_SECONDS = 600
OPENAI_TRANSCRIPTIONS_URL = "https://api.openai.com/v1/audio/transcriptions"
SECRET_RESOURCE_RE = re.compile(
    r"^projects/(?P<project>[^/\s]+)/secrets/(?P<secret>[^/\s]+)(?:/versions/(?P<version>[^/\s]+))?$"
)
ASR_AUDIO_EXTENSIONS = {".m4a", ".mp3", ".webm", ".opus", ".wav", ".mp4"}
TIMESTAMP_RE = re.compile(
    r"(?P<start>(?:\d{2}:)?\d{2}:\d{2}[\.,]\d{3})\s+-->\s+"
    r"(?P<end>(?:\d{2}:)?\d{2}:\d{2}[\.,]\d{3})(?P<settings>.*)"
)


@dataclass
class Cue:
    start_ms: int
    end_ms: int
    text: str
    settings: str = ""
    identifier: str | None = None


def main() -> int:
    args = parse_args()
    yt_dlp = require_yt_dlp(args.yt_dlp)
    out_dir = args.out_dir
    raw_dir = out_dir / "raw"
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    live_meta = fetch_metadata(yt_dlp, args.live_url)
    sermon_meta: dict[str, Any] | None = None
    discovery: dict[str, Any] = {"enabled": not args.no_discover, "candidates": []}

    if args.sermon_url:
        sermon_meta = fetch_metadata(yt_dlp, args.sermon_url)
        discovery["selected_by"] = "explicit_sermon_url"
    elif not args.no_discover:
        sermon_meta, discovery = discover_matching_sermon_vod(
            yt_dlp=yt_dlp,
            live_meta=live_meta,
            playlist_end=args.playlist_end,
        )

    start_ms, start_method = determine_sermon_start(
        live_meta=live_meta,
        sermon_meta=sermon_meta,
        manual_start=args.sermon_start,
        tail_padding_seconds=args.tail_padding_seconds,
    )
    end_ms = parse_time_to_ms(args.sermon_end) if args.sermon_end else None
    if end_ms is not None and end_ms <= start_ms:
        raise ValueError("--sermon-end must be later than --sermon-start or inferred sermon start")
    sermon_duration_override_ms = end_ms - start_ms if end_ms is not None else None

    caption_source_url, caption_source_meta, caption_source_kind = select_caption_source(
        live_url=args.live_url,
        live_meta=live_meta,
        sermon_meta=sermon_meta,
        requested_langs=args.lang,
    )

    report: dict[str, Any] = {
        "status": "initialized",
        "live": summarize_video(live_meta),
        "sermon_candidate": summarize_video(sermon_meta) if sermon_meta else None,
        "discovery": discovery,
        "sermon_start": {
            "seconds": round(start_ms / 1000, 3),
            "timecode": format_clock(start_ms),
            "method": start_method,
        },
        "sermon_end": {
            "seconds": round(end_ms / 1000, 3),
            "timecode": format_clock(end_ms),
            "method": "manual",
        } if end_ms is not None else None,
        "sermon_window": {
            "start_seconds": round(start_ms / 1000, 3),
            "start_timecode": format_clock(start_ms),
            "end_seconds": round(end_ms / 1000, 3) if end_ms is not None else None,
            "end_timecode": format_clock(end_ms) if end_ms is not None else None,
            "duration_seconds": round(sermon_duration_override_ms / 1000, 3) if sermon_duration_override_ms is not None else None,
        },
        "caption_source": {
            "kind": caption_source_kind,
            "video": summarize_video(caption_source_meta) if caption_source_meta else None,
        },
        "offline_route": caption_route_decision(
            live_meta=live_meta,
            sermon_meta=sermon_meta,
            requested_langs=args.lang,
            selected_source_kind=caption_source_kind,
        ),
        "asr": {
            "provider": "openai",
            "model": args.asr_model,
        },
        "outputs": [],
        "warnings": [],
    }

    if not caption_source_url or not caption_source_meta:
        if not args.api_key_secret:
            report["status"] = "needs_asr"
            report["offline_route"]["status"] = "needs_asr_credentials"
            report["warnings"].append(
                "No requested caption track was found on the live archive or matching sermon VOD. "
                f"Next step is extracting the sermon audio window and sending it to {args.asr_model} ASR."
            )
            write_reports(out_dir, report)
            return 2
        sermon_duration_ms = sermon_duration_override_ms or int((sermon_meta or live_meta).get("duration") or 0) * 1000
        if sermon_duration_override_ms is None and sermon_meta is None and start_ms > 0 and sermon_duration_ms > start_ms:
            sermon_duration_ms = sermon_duration_ms - start_ms
        if sermon_duration_ms <= 0:
            sermon_duration_ms = None  # type: ignore[assignment]
        try:
            audio_path = extract_audio_window(
                yt_dlp=yt_dlp,
                url=args.live_url,
                raw_dir=raw_dir,
                live_meta=live_meta,
                start_ms=start_ms,
                duration_ms=sermon_duration_ms,
            )
            cues = transcribe_audio_to_cues(
                audio_path=audio_path,
                api_key_secret=args.api_key_secret,
                model=args.asr_model,
                fallback_duration_ms=sermon_duration_ms,
            )
            report["offline_route"]["audioExtractionAttempted"] = True
            report["offline_route"]["asrModel"] = args.asr_model
        except Exception as exc:
            report["status"] = "asr_failed"
            report["offline_route"]["status"] = "asr_failed"
            report["warnings"].append(f"ASR fallback failed: {exc}")
            write_reports(out_dir, report)
            return 5
        write_asr_outputs(
            out_dir=out_dir,
            report=report,
            live_meta=live_meta,
            audio_path=audio_path,
            cues=cues,
            start_ms=start_ms,
        )
        report["caption_source"] = {
            "kind": "openai_asr",
            "video": summarize_video(live_meta),
        }
        report["offline_route"]["selectedSourceKind"] = "openai_asr"
        report["offline_route"]["status"] = "asr_completed"
        report["status"] = "ok" if report["outputs"] else "no_cues"
        write_reports(out_dir, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["status"] == "ok" else 4

    downloaded, download_warnings = download_subtitles(
        yt_dlp=yt_dlp,
        url=caption_source_url,
        raw_dir=raw_dir,
        langs=args.lang,
    )
    report["warnings"].extend(download_warnings)
    if not downloaded:
        report["status"] = "subtitle_download_failed"
        report["warnings"].append("Caption metadata existed, but yt-dlp did not write a VTT file.")
        write_reports(out_dir, report)
        return 3

    sermon_duration_ms = sermon_duration_override_ms or int((sermon_meta or live_meta).get("duration") or 0) * 1000
    if sermon_duration_ms <= 0:
        sermon_duration_ms = None  # type: ignore[assignment]

    for source_file in downloaded:
        cues = parse_vtt(source_file.read_text(encoding="utf-8", errors="replace"))
        lang = infer_lang_from_path(source_file)

        if caption_source_kind == "live_archive":
            sermon_local = slice_live_cues(cues, start_ms, sermon_duration_ms)
            live_aligned = [cue for cue in cues if cue_overlaps(cue, start_ms, sermon_duration_ms)]
        else:
            sermon_local = slice_live_cues(cues, 0, sermon_duration_ms)
            live_aligned = offset_cues(sermon_local, start_ms)

        base = f"{safe_id(live_meta)}.sermon.{lang}"
        local_vtt = out_dir / f"{base}.local.vtt"
        live_vtt = out_dir / f"{base}.live-aligned.vtt"
        local_srt = out_dir / f"{base}.local.srt"
        live_srt = out_dir / f"{base}.live-aligned.srt"

        local_vtt.write_text(render_vtt(sermon_local), encoding="utf-8")
        live_vtt.write_text(render_vtt(live_aligned), encoding="utf-8")
        local_srt.write_text(render_srt(sermon_local), encoding="utf-8")
        live_srt.write_text(render_srt(live_aligned), encoding="utf-8")

        report["outputs"].append(
            {
                "lang": lang,
                "source_file": str(source_file),
                "cue_count": len(sermon_local),
                "local_vtt": str(local_vtt),
                "live_aligned_vtt": str(live_vtt),
                "local_srt": str(local_srt),
                "live_aligned_srt": str(live_srt),
            }
        )

    report["status"] = "ok" if report["outputs"] else "no_cues"
    write_reports(out_dir, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "ok" else 4


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract sermon subtitle files from a YouTube live archive link."
    )
    parser.add_argument("--live-url", required=True, help="YouTube live archive URL.")
    parser.add_argument(
        "--sermon-url",
        help="Optional edited sermon VOD URL. If omitted, the script tries to discover one from the same channel.",
    )
    parser.add_argument(
        "--no-discover",
        action="store_true",
        help="Disable same-channel edited sermon VOD discovery.",
    )
    parser.add_argument(
        "--playlist-end",
        type=int,
        default=40,
        help="Number of channel videos to inspect during discovery.",
    )
    parser.add_argument(
        "--lang",
        action="append",
        default=[],
        help=(
            "Subtitle language to request. Repeatable. Defaults to en-orig, en. "
            "Request zh-Hans explicitly only when you want to try platform-generated Chinese captions."
        ),
    )
    parser.add_argument(
        "--sermon-start",
        help="Manual sermon start override, e.g. 00:23:25 or seconds.",
    )
    parser.add_argument(
        "--sermon-end",
        help="Manual sermon end override on the live timeline, e.g. 49:15 or seconds.",
    )
    parser.add_argument(
        "--tail-padding-seconds",
        type=float,
        default=0,
        help="Subtract this tail padding when inferring start from live_duration - sermon_duration.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("artifacts/offline-live-sermon-poc"),
        help="Output directory for reports and subtitle files.",
    )
    parser.add_argument("--yt-dlp", default="yt-dlp", help="Path to yt-dlp executable.")
    parser.add_argument(
        "--asr-model",
        default=DEFAULT_ASR_MODEL,
        help="OpenAI transcription model to use when captions are unavailable.",
    )
    parser.add_argument(
        "--api-key-secret",
        help="Google Secret Manager resource name for the OpenAI key used by ASR fallback.",
    )
    args = parser.parse_args()
    if not args.lang:
        args.lang = DEFAULT_LANGS
    validate_asr_model(args.asr_model)
    if args.api_key_secret:
        validate_secret_resource_name(args.api_key_secret)
    return args


def validate_asr_model(model: str) -> None:
    if model == FORBIDDEN_ASR_MODEL:
        raise SystemExit(
            "Offline no-caption ASR fallback must not use gpt-realtime-translate; "
            "use gpt-4o-transcribe."
        )
    if model != DEFAULT_ASR_MODEL:
        raise SystemExit("Offline no-caption ASR fallback must use gpt-4o-transcribe.")


def validate_secret_resource_name(value: str) -> None:
    if not SECRET_RESOURCE_RE.fullmatch(value):
        raise SystemExit(
            "--api-key-secret must be a Google Secret Manager resource name like "
            "projects/PROJECT_ID/secrets/SECRET_ID/versions/latest. Do not pass raw API key material."
        )


def require_yt_dlp(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise SystemExit(f"yt-dlp executable not found: {name}")
    return found


def run_json_lines(command: list[str]) -> list[dict[str, Any]]:
    proc = subprocess.run(command, check=True, text=True, capture_output=True)
    rows = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def fetch_metadata(yt_dlp: str, url: str) -> dict[str, Any]:
    rows = run_json_lines([yt_dlp, "--dump-json", "--skip-download", "--no-cache-dir", url])
    if not rows:
        raise RuntimeError(f"No metadata returned for {url}")
    return rows[0]


def discover_matching_sermon_vod(
    yt_dlp: str,
    live_meta: dict[str, Any],
    playlist_end: int,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    uploader_url = live_meta.get("uploader_url") or live_meta.get("channel_url")
    title = live_meta.get("title") or ""
    live_id = live_meta.get("id")
    live_duration = live_meta.get("duration") or 0
    discovery: dict[str, Any] = {
        "enabled": True,
        "selected_by": None,
        "playlist_url": None,
        "candidates": [],
    }

    if not uploader_url:
        discovery["warning"] = "live metadata did not include uploader_url/channel_url"
        return None, discovery

    playlist_url = uploader_url.rstrip("/") + "/videos"
    discovery["playlist_url"] = playlist_url
    rows = run_json_lines(
        [
            yt_dlp,
            "--flat-playlist",
            "--dump-json",
            "--skip-download",
            "--playlist-end",
            str(playlist_end),
            "--no-cache-dir",
            playlist_url,
        ]
    )

    best: dict[str, Any] | None = None
    best_score = -1.0
    for row in rows:
        if row.get("id") == live_id:
            continue
        row_title = row.get("title") or ""
        duration = row.get("duration") or 0
        title_score = title_similarity(title, row_title)
        duration_score = 0.0
        if live_duration and duration:
            ratio = duration / live_duration
            if 0.35 <= ratio <= 0.8:
                duration_score = 1.0 - abs(ratio - 0.58)
        score = title_score * 0.78 + duration_score * 0.22
        candidate = {
            "id": row.get("id"),
            "title": row_title,
            "duration": duration,
            "url": row.get("url") or row.get("webpage_url"),
            "title_score": round(title_score, 3),
            "score": round(score, 3),
        }
        discovery["candidates"].append(candidate)
        if score > best_score and title_score >= 0.92:
            best_score = score
            best = row

    if not best:
        return None, discovery

    best_url = best.get("url") or best.get("webpage_url")
    if best_url and not str(best_url).startswith("http"):
        best_url = "https://www.youtube.com/watch?v=" + str(best_url)
    discovery["selected_by"] = "same_title_shorter_vod"
    discovery["selected"] = {
        "id": best.get("id"),
        "title": best.get("title"),
        "duration": best.get("duration"),
        "url": best_url,
        "score": round(best_score, 3),
    }
    return fetch_metadata(yt_dlp, str(best_url)), discovery


def determine_sermon_start(
    live_meta: dict[str, Any],
    sermon_meta: dict[str, Any] | None,
    manual_start: str | None,
    tail_padding_seconds: float,
) -> tuple[int, str]:
    if manual_start:
        return parse_time_to_ms(manual_start), "manual"

    live_duration = float(live_meta.get("duration") or 0)
    sermon_duration = float((sermon_meta or {}).get("duration") or 0)
    if live_duration > 0 and sermon_duration > 0 and live_duration > sermon_duration:
        start_seconds = max(0.0, live_duration - sermon_duration - tail_padding_seconds)
        return int(start_seconds * 1000), "duration_backsolve_live_minus_sermon"

    return 0, "unknown_default_zero"


def select_caption_source(
    live_url: str,
    live_meta: dict[str, Any],
    sermon_meta: dict[str, Any] | None,
    requested_langs: list[str],
) -> tuple[str | None, dict[str, Any] | None, str]:
    if has_requested_captions(live_meta, requested_langs):
        return live_url, live_meta, "live_archive"
    if sermon_meta and has_requested_captions(sermon_meta, requested_langs):
        return str(sermon_meta.get("webpage_url") or sermon_meta.get("original_url")), sermon_meta, "sermon_vod"
    return None, None, "none"


def has_requested_captions(meta: dict[str, Any], requested_langs: list[str]) -> bool:
    subtitles = meta.get("subtitles") or {}
    automatic = meta.get("automatic_captions") or {}
    available = set(subtitles) | set(automatic)
    return any(lang in available for lang in requested_langs)


def caption_route_decision(
    *,
    live_meta: dict[str, Any],
    sermon_meta: dict[str, Any] | None,
    requested_langs: list[str],
    selected_source_kind: str,
) -> dict[str, Any]:
    uses_captions = selected_source_kind in {"live_archive", "sermon_vod"}
    return {
        "strategy": "captions_first_then_asr",
        "requestedLangs": requested_langs,
        "liveCaptionLangs": caption_langs(live_meta),
        "sermonVodCaptionLangs": caption_langs(sermon_meta),
        "selectedSourceKind": selected_source_kind,
        "decision": "use_caption_track" if uses_captions else "use_asr_fallback",
        "asrFallbackRequired": not uses_captions,
        "audioExtractionAttempted": False,
        "fallbackReason": None if uses_captions else "no_requested_caption_track",
        "status": "caption_track_selected" if uses_captions else "asr_pending",
    }


def caption_langs(meta: dict[str, Any] | None) -> list[str]:
    if not meta:
        return []
    return sorted(set((meta.get("subtitles") or {}) | (meta.get("automatic_captions") or {})))


def download_subtitles(yt_dlp: str, url: str, raw_dir: Path, langs: list[str]) -> tuple[list[Path], list[str]]:
    downloaded: set[Path] = set()
    warnings: list[str] = []
    for lang in langs:
        before = {path for path in raw_dir.glob("*.vtt") if path.stat().st_size > 0}
        proc = subprocess.run(
            [
                yt_dlp,
                "--skip-download",
                "--write-subs",
                "--write-auto-subs",
                "--sub-langs",
                lang,
                "--sub-format",
                "vtt",
                "--output",
                str(raw_dir / "%(id)s.%(ext)s"),
                "--no-cache-dir",
                url,
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        after = {path for path in raw_dir.glob("*.vtt") if path.stat().st_size > 0}
        new_files = after - before
        lang_files = {path for path in after if infer_lang_from_path(path) == lang}
        usable_files = new_files or lang_files
        downloaded.update(usable_files)
        if proc.returncode != 0:
            warnings.append(
                f"Subtitle download failed for lang={lang}: "
                f"{last_error_line(proc.stderr) or 'yt-dlp returned non-zero exit'}"
            )
        elif not usable_files:
            warnings.append(f"No new VTT file was written for lang={lang}.")
        elif new_files:
            print(proc.stdout, end="")
        else:
            warnings.append(f"Reused existing VTT file for lang={lang}.")
    return sorted(downloaded), warnings


def extract_audio_window(
    yt_dlp: str,
    url: str,
    raw_dir: Path,
    live_meta: dict[str, Any],
    start_ms: int,
    duration_ms: int | None,
) -> Path:
    base = f"{safe_id(live_meta)}.sermon-audio"
    output_template = raw_dir / f"{base}.%(ext)s"
    before = usable_audio_files(raw_dir, base)
    command = [
        yt_dlp,
        "--extract-audio",
        "--audio-format",
        "m4a",
        "--output",
        str(output_template),
        "--no-cache-dir",
    ]
    section = download_section_spec(start_ms, duration_ms)
    if section:
        command.extend(["--download-sections", section])
    command.append(url)
    proc = subprocess.run(command, text=True, capture_output=True, check=False)
    after = usable_audio_files(raw_dir, base)
    candidates = [path for path in after if path not in before] or after
    if proc.returncode != 0 or not candidates:
        raise RuntimeError(last_error_line(proc.stderr) or "yt-dlp did not write an audio file")
    return max(candidates, key=lambda path: (path.stat().st_mtime, path.stat().st_size))


def usable_audio_files(raw_dir: Path, base: str) -> set[Path]:
    return {
        path
        for path in raw_dir.glob(f"{base}.*")
        if path.suffix.lower() in ASR_AUDIO_EXTENSIONS and path.stat().st_size > 0
    }


def download_section_spec(start_ms: int, duration_ms: int | None) -> str | None:
    if start_ms <= 0 and duration_ms is None:
        return None
    start = format_section_time(start_ms)
    end = "inf" if duration_ms is None else format_section_time(start_ms + duration_ms)
    return f"*{start}-{end}"


def format_section_time(ms: int) -> str:
    seconds = max(0, int(ms // 1000))
    hours = seconds // 3600
    seconds %= 3600
    minutes = seconds // 60
    seconds %= 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def transcribe_audio_to_cues(
    audio_path: Path,
    api_key_secret: str,
    model: str,
    fallback_duration_ms: int | None,
) -> list[Cue]:
    api_key = access_secret(api_key_secret)
    if fallback_duration_ms and fallback_duration_ms > MAX_ASR_CHUNK_SECONDS * 1000:
        return transcribe_audio_chunks_to_cues(
            audio_path=audio_path,
            api_key=api_key,
            model=model,
            fallback_duration_ms=fallback_duration_ms,
        )
    return transcribe_single_audio_to_cues(
        audio_path=audio_path,
        api_key=api_key,
        model=model,
        fallback_duration_ms=fallback_duration_ms,
    )


def transcribe_audio_chunks_to_cues(
    audio_path: Path,
    api_key: str,
    model: str,
    fallback_duration_ms: int,
) -> list[Cue]:
    cues: list[Cue] = []
    chunk_ms = MAX_ASR_CHUNK_SECONDS * 1000
    chunk_dir = audio_path.parent / f"{audio_path.stem}.chunks"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    total_chunks = (fallback_duration_ms + chunk_ms - 1) // chunk_ms
    for index in range(total_chunks):
        start_ms = index * chunk_ms
        duration_ms = min(chunk_ms, fallback_duration_ms - start_ms)
        if duration_ms <= 0:
            continue
        chunk_path = split_audio_chunk(
            audio_path=audio_path,
            chunk_dir=chunk_dir,
            index=index,
            start_ms=start_ms,
            duration_ms=duration_ms,
        )
        chunk_cues = transcribe_single_audio_to_cues(
            audio_path=chunk_path,
            api_key=api_key,
            model=model,
            fallback_duration_ms=duration_ms,
        )
        cues.extend(
            Cue(
                start_ms=cue.start_ms + start_ms,
                end_ms=cue.end_ms + start_ms,
                text=cue.text,
                settings=cue.settings,
                identifier=f"asr_{index + 1:02d}_{cue.identifier or f'{len(cues) + 1:04d}'}",
            )
            for cue in chunk_cues
        )
    return cues


def split_audio_chunk(
    audio_path: Path,
    chunk_dir: Path,
    index: int,
    start_ms: int,
    duration_ms: int,
) -> Path:
    chunk_path = chunk_dir / f"{audio_path.stem}.part{index + 1:03d}.m4a"
    command = [
        "ffmpeg",
        "-y",
        "-ss",
        format_section_time(start_ms),
        "-t",
        format_seconds(duration_ms),
        "-i",
        str(audio_path),
        "-vn",
        "-acodec",
        "aac",
        str(chunk_path),
    ]
    proc = subprocess.run(command, text=True, capture_output=True, check=False)
    if proc.returncode != 0 or not chunk_path.exists() or chunk_path.stat().st_size <= 0:
        raise RuntimeError(last_error_line(proc.stderr) or "ffmpeg did not write an ASR audio chunk")
    return chunk_path


def format_seconds(ms: int) -> str:
    return f"{max(0.001, ms / 1000):.3f}"


def transcribe_single_audio_to_cues(
    audio_path: Path,
    api_key: str,
    model: str,
    fallback_duration_ms: int | None,
) -> list[Cue]:
    mime_type = mimetypes.guess_type(audio_path.name)[0] or "application/octet-stream"
    with audio_path.open("rb") as audio_file:
        response = requests.post(
            OPENAI_TRANSCRIPTIONS_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            data=transcription_request_fields(model),
            files={"file": (audio_path.name, audio_file, mime_type)},
            timeout=300,
        )
    if response.status_code >= 400:
        raise RuntimeError(f"OpenAI ASR request failed with HTTP {response.status_code}: {safe_error_message(response)}")
    return cues_from_transcription_response(response.json(), fallback_duration_ms)


def transcription_request_fields(model: str) -> list[tuple[str, str]]:
    response_format = transcription_response_format(model)
    fields = [("model", model), ("response_format", response_format)]
    if response_format == "verbose_json":
        fields.append(("timestamp_granularities[]", "segment"))
    return fields


def transcription_response_format(model: str) -> str:
    # The current gpt-4o transcription endpoint rejects verbose_json; json returns
    # the transcript text, which we convert into a single timed cue.
    if model.startswith(("gpt-4o-transcribe", "gpt-4o-mini-transcribe")):
        return "json"
    return "verbose_json"


def access_secret(resource_name: str) -> str:
    match = SECRET_RESOURCE_RE.fullmatch(resource_name)
    if not match:
        raise RuntimeError("Invalid Secret Manager resource name.")
    return cloud_access_secret(resource_name)


def cues_from_transcription_response(data: dict[str, Any], fallback_duration_ms: int | None) -> list[Cue]:
    segments = data.get("segments") if isinstance(data, dict) else None
    cues: list[Cue] = []
    if isinstance(segments, list):
        for index, segment in enumerate(segments):
            text = str(segment.get("text") or "").strip()
            if not text:
                continue
            start_ms = int(float(segment.get("start") or 0) * 1000)
            end_ms = int(float(segment.get("end") or 0) * 1000)
            if end_ms <= start_ms:
                end_ms = start_ms + estimate_text_duration_ms(text)
            cues.append(Cue(start_ms=start_ms, end_ms=end_ms, text=text, identifier=f"asr_{index + 1:04d}"))
    if cues:
        return cues
    text = str((data or {}).get("text") or "").strip()
    if not text:
        return []
    return [Cue(0, fallback_duration_ms or estimate_text_duration_ms(text), text, identifier="asr_0001")]


def estimate_text_duration_ms(text: str) -> int:
    return max(1500, min(15000, len(text) * 55))


def write_asr_outputs(
    out_dir: Path,
    report: dict[str, Any],
    live_meta: dict[str, Any],
    audio_path: Path,
    cues: list[Cue],
    start_ms: int,
) -> None:
    base = f"{safe_id(live_meta)}.sermon.en"
    local_vtt = out_dir / f"{base}.local.vtt"
    live_vtt = out_dir / f"{base}.live-aligned.vtt"
    local_srt = out_dir / f"{base}.local.srt"
    live_srt = out_dir / f"{base}.live-aligned.srt"
    live_aligned = offset_cues(cues, start_ms)
    local_vtt.write_text(render_vtt(cues), encoding="utf-8")
    live_vtt.write_text(render_vtt(live_aligned), encoding="utf-8")
    local_srt.write_text(render_srt(cues), encoding="utf-8")
    live_srt.write_text(render_srt(live_aligned), encoding="utf-8")
    report["outputs"].append(
        {
            "lang": "en",
            "source_file": str(audio_path),
            "source_kind": "openai_asr",
            "cue_count": len(cues),
            "local_vtt": str(local_vtt),
            "live_aligned_vtt": str(live_vtt),
            "local_srt": str(local_srt),
            "live_aligned_srt": str(live_srt),
        }
    )


def safe_error_message(response: requests.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text[:400]
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error.get("type") or "unknown error")
    return str(data)[:400]


def last_error_line(stderr: str) -> str:
    for line in reversed(stderr.splitlines()):
        line = line.strip()
        if line:
            return line
    return ""


def parse_vtt(text: str) -> list[Cue]:
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n"))
    cues: list[Cue] = []
    for block in blocks:
        lines = [line for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        if lines[0].startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
            continue
        identifier = None
        timing_index = 0
        if "-->" not in lines[0] and len(lines) > 1:
            identifier = lines[0]
            timing_index = 1
        if timing_index >= len(lines):
            continue
        match = TIMESTAMP_RE.search(lines[timing_index])
        if not match:
            continue
        cue_text = "\n".join(lines[timing_index + 1 :]).strip()
        if not cue_text:
            continue
        cues.append(
            Cue(
                start_ms=parse_time_to_ms(match.group("start")),
                end_ms=parse_time_to_ms(match.group("end")),
                settings=match.group("settings").strip(),
                text=clean_vtt_text(cue_text),
                identifier=identifier,
            )
        )
    return cues


def slice_live_cues(cues: list[Cue], start_ms: int, duration_ms: int | None) -> list[Cue]:
    sliced = []
    for cue in cues:
        if not cue_overlaps(cue, start_ms, duration_ms):
            continue
        new_start = max(0, cue.start_ms - start_ms)
        new_end = max(new_start + 1, cue.end_ms - start_ms)
        sliced.append(Cue(new_start, new_end, cue.text, cue.settings, cue.identifier))
    return sliced


def cue_overlaps(cue: Cue, start_ms: int, duration_ms: int | None) -> bool:
    if cue.end_ms <= start_ms:
        return False
    if duration_ms is not None and cue.start_ms >= start_ms + duration_ms:
        return False
    return True


def offset_cues(cues: list[Cue], offset_ms: int) -> list[Cue]:
    return [
        Cue(cue.start_ms + offset_ms, cue.end_ms + offset_ms, cue.text, cue.settings, cue.identifier)
        for cue in cues
    ]


def render_vtt(cues: list[Cue]) -> str:
    rows = ["WEBVTT", ""]
    for cue in cues:
        rows.append(f"{format_vtt_time(cue.start_ms)} --> {format_vtt_time(cue.end_ms)}")
        rows.append(cue.text)
        rows.append("")
    return "\n".join(rows)


def render_srt(cues: list[Cue]) -> str:
    rows: list[str] = []
    for index, cue in enumerate(cues, start=1):
        rows.append(str(index))
        rows.append(f"{format_srt_time(cue.start_ms)} --> {format_srt_time(cue.end_ms)}")
        rows.append(cue.text)
        rows.append("")
    return "\n".join(rows)


def clean_vtt_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"\s+\n", "\n", text)
    return text.strip()


def parse_time_to_ms(value: str) -> int:
    value = value.strip().replace("：", ":").replace(",", ".")
    if re.fullmatch(r"\d+(?:\.\d+)?", value):
        return int(float(value) * 1000)
    parts = value.split(":")
    if len(parts) == 2:
        hours = 0
        minutes = int(parts[0])
        seconds = float(parts[1])
    elif len(parts) == 3:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = float(parts[2])
    else:
        raise ValueError(f"Unsupported time value: {value}")
    return int(((hours * 3600) + (minutes * 60) + seconds) * 1000)


def format_vtt_time(ms: int) -> str:
    return format_time(ms, ".")


def format_srt_time(ms: int) -> str:
    return format_time(ms, ",")


def format_time(ms: int, separator: str) -> str:
    ms = max(0, ms)
    hours = ms // 3_600_000
    ms %= 3_600_000
    minutes = ms // 60_000
    ms %= 60_000
    seconds = ms // 1000
    millis = ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{millis:03d}"


def format_clock(ms: int) -> str:
    return str(timedelta(milliseconds=max(0, ms))).split(".")[0]


def infer_lang_from_path(path: Path) -> str:
    parts = path.name.split(".")
    if len(parts) >= 3:
        return parts[-2]
    return "unknown"


def title_similarity(a: str, b: str) -> float:
    a_tokens = set(tokenize_title(a))
    b_tokens = set(tokenize_title(b))
    if not a_tokens or not b_tokens:
        return 0.0
    return len(a_tokens & b_tokens) / len(a_tokens | b_tokens)


def tokenize_title(value: str) -> list[str]:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower())
    return [token for token in normalized.split() if token not in {"the", "a", "an", "and"}]


def safe_id(meta: dict[str, Any]) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", str(meta.get("id") or "live"))


def summarize_video(meta: dict[str, Any] | None) -> dict[str, Any] | None:
    if not meta:
        return None
    return {
        "id": meta.get("id"),
        "title": meta.get("title"),
        "url": meta.get("webpage_url") or meta.get("original_url"),
        "duration_seconds": meta.get("duration"),
        "live_status": meta.get("live_status"),
        "media_type": meta.get("media_type"),
        "timestamp": meta.get("timestamp"),
        "release_timestamp": meta.get("release_timestamp"),
        "caption_langs": caption_langs(meta),
    }


def write_reports(out_dir: Path, report: dict[str, Any]) -> None:
    (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "report.md").write_text(render_report_md(report), encoding="utf-8")


def render_report_md(report: dict[str, Any]) -> str:
    lines = [
        "# Offline Live Sermon Subtitle POC Report",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Live: `{report.get('live', {}).get('id')}` {report.get('live', {}).get('title')}",
        f"- Sermon start: `{report.get('sermon_start', {}).get('timecode')}` "
        f"({report.get('sermon_start', {}).get('method')})",
        f"- Sermon end: `{(report.get('sermon_end') or {}).get('timecode') or 'not set'}`",
        f"- Caption source: `{report.get('caption_source', {}).get('kind')}`",
        "",
        "## Outputs",
        "",
    ]
    outputs = report.get("outputs") or []
    if outputs:
        for output in outputs:
            lines.extend(
                [
                    f"### {output['lang']}",
                    "",
                    f"- Cue count: {output['cue_count']}",
                    f"- Local VTT: `{output['local_vtt']}`",
                    f"- Live-aligned VTT: `{output['live_aligned_vtt']}`",
                    f"- Local SRT: `{output['local_srt']}`",
                    f"- Live-aligned SRT: `{output['live_aligned_srt']}`",
                    "",
                ]
            )
    else:
        lines.append("No subtitle output was generated.")
        lines.append("")
    warnings = report.get("warnings") or []
    if warnings:
        lines.extend(["## Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(exc.stderr or str(exc), file=sys.stderr)
        raise SystemExit(exc.returncode)
