#!/usr/bin/env python3
"""Preflight a YouTube live archive for the offline captions-first path."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SCRIPT_DIR = REPO_ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import offline_live_sermon_subtitles as offline  # noqa: E402


def main() -> int:
    args = parse_args()
    report = run_preflight(args)
    if args.out:
        out = resolve_repo_path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "ok" else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-url", required=True)
    parser.add_argument("--sermon-url")
    parser.add_argument("--no-discover", action="store_true")
    parser.add_argument("--playlist-end", type=int, default=40)
    parser.add_argument("--lang", action="append", default=[])
    parser.add_argument("--sermon-start")
    parser.add_argument("--tail-padding-seconds", type=float, default=0)
    parser.add_argument("--yt-dlp", default="yt-dlp")
    parser.add_argument("--asr-model", default=offline.DEFAULT_ASR_MODEL)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if not args.lang:
        args.lang = list(offline.DEFAULT_LANGS)
    offline.validate_asr_model(args.asr_model)
    return args


def run_preflight(args: argparse.Namespace) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    try:
        yt_dlp = offline.require_yt_dlp(args.yt_dlp)
        add_check(checks, "yt_dlp_available", True, yt_dlp)
        live_meta = offline.fetch_metadata(yt_dlp, args.live_url)
        add_check(checks, "live_metadata", True, offline.summarize_video(live_meta))
        sermon_meta, discovery = resolve_sermon_meta(args, yt_dlp, live_meta)
        add_check(
            checks,
            "sermon_discovery",
            True,
            {
                "enabled": discovery.get("enabled"),
                "selectedBy": discovery.get("selected_by"),
                "candidateCount": len(discovery.get("candidates") or []),
            },
        )
        start_ms, start_method = offline.determine_sermon_start(
            live_meta=live_meta,
            sermon_meta=sermon_meta,
            manual_start=args.sermon_start,
            tail_padding_seconds=args.tail_padding_seconds,
        )
        _caption_source_url, caption_source_meta, caption_source_kind = offline.select_caption_source(
            live_url=args.live_url,
            live_meta=live_meta,
            sermon_meta=sermon_meta,
            requested_langs=args.lang,
        )
        route = offline.caption_route_decision(
            live_meta=live_meta,
            sermon_meta=sermon_meta,
            requested_langs=args.lang,
            selected_source_kind=caption_source_kind,
        )
        add_check(checks, "offline_route_decision", True, route)
        if route["decision"] == "use_caption_track":
            add_check(checks, "caption_track_available", True, {"selectedSourceKind": caption_source_kind})
        else:
            add_check(
                checks,
                "asr_fallback_planned",
                True,
                {
                    "asrModel": args.asr_model,
                    "fallbackReason": route.get("fallbackReason"),
                    "audioExtractionAttempted": False,
                },
                state="warn",
            )
    except Exception as exc:
        add_check(checks, "preflight_exception", False, str(exc)[:500])
        return report_from_checks(args, checks)

    report = report_from_checks(args, checks)
    report["live"] = offline.summarize_video(live_meta)
    report["sermonCandidate"] = offline.summarize_video(sermon_meta) if sermon_meta else None
    report["sermonStart"] = {
        "seconds": round(start_ms / 1000, 3),
        "timecode": offline.format_clock(start_ms),
        "method": start_method,
    }
    report["captionSource"] = {
        "kind": caption_source_kind,
        "video": offline.summarize_video(caption_source_meta) if caption_source_meta else None,
    }
    report["offlineRoute"] = route
    report["asr"] = {"provider": "openai", "model": args.asr_model}
    return report


def resolve_sermon_meta(
    args: argparse.Namespace,
    yt_dlp: str,
    live_meta: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if args.sermon_url:
        return offline.fetch_metadata(yt_dlp, args.sermon_url), {
            "enabled": False,
            "selected_by": "explicit_sermon_url",
            "candidates": [],
        }
    if args.no_discover:
        return None, {"enabled": False, "selected_by": None, "candidates": []}
    return offline.discover_matching_sermon_vod(
        yt_dlp=yt_dlp,
        live_meta=live_meta,
        playlist_end=args.playlist_end,
    )


def report_from_checks(args: argparse.Namespace, checks: list[dict[str, Any]]) -> dict[str, Any]:
    failed = [check for check in checks if check["state"] == "fail"]
    warnings = [check for check in checks if check["state"] == "warn"]
    return {
        "schemaVersion": 1,
        "status": "failed" if failed else "ok",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "requestedLangs": args.lang,
        "checks": checks,
        "failedChecks": [check["name"] for check in failed],
        "warnings": [check["name"] for check in warnings],
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def add_check(
    checks: list[dict[str, Any]],
    name: str,
    passed: bool,
    observed: Any,
    *,
    state: str | None = None,
) -> None:
    checks.append({"name": name, "state": state or ("pass" if passed else "fail"), "observed": observed})


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


if __name__ == "__main__":
    raise SystemExit(main())
