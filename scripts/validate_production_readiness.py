#!/usr/bin/env python3
"""Validate the combined Sunday production readiness evidence."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"


def import_script(module_name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


offline_validator = import_script("validate_offline_chain", SCRIPTS_DIR / "validate_offline_chain.py")
sunday_validator = import_script("validate_sunday_manifest", SCRIPTS_DIR / "validate_sunday_manifest.py")
realtime_validator = import_script("validate_realtime_session", SCRIPTS_DIR / "validate_realtime_session.py")


def main() -> int:
    args = parse_args()
    report = validate_production_readiness(args)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "ok" else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline-report", required=True, help="offline_live_sermon_subtitles.py report.json.")
    parser.add_argument("--playback-js", required=True, help="Translated playback simulation JS.")
    parser.add_argument("--zh-vtt", required=True, help="Exported Chinese VTT.")
    parser.add_argument("--zh-srt", required=True, help="Exported Chinese SRT.")
    parser.add_argument("--run-manifest", help="Optional run cloud-manifest.json used by offline verifier.")
    parser.add_argument("--sunday-manifest", required=True, help="Promoted Sunday cloud-manifest.json.")
    parser.add_argument("--sunday", help="Expected Sunday date, YYYY-MM-DD.")
    parser.add_argument("--expected-source-mode", default="youtube-live-archive")
    parser.add_argument(
        "--require-readable-sunday-artifacts",
        action="store_true",
        help="Ask the Sunday manifest verifier to read playback JS and VTT/SRT outputs.",
    )
    parser.add_argument("--realtime-events-jsonl", help="Realtime session JSONL archive.")
    parser.add_argument(
        "--allow-missing-realtime",
        action="store_true",
        help="Warn instead of fail when realtime JSONL evidence is not provided.",
    )
    parser.add_argument(
        "--allow-missing-stable-correction",
        action="store_true",
        help="Do not require gpt-5.5-mini stable correction events in realtime JSONL.",
    )
    parser.add_argument("--out", help="Optional JSON report path.")
    return parser.parse_args()


def validate_production_readiness(args: argparse.Namespace) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    offline_report = run_offline_validation(args)
    add_check(checks, "offline_chain", offline_report["status"] == "ok", offline_report.get("failedChecks"))

    sunday_report = run_sunday_manifest_validation(args)
    add_check(checks, "sunday_manifest", sunday_report["status"] == "ok", sunday_report.get("failedChecks"))

    realtime_report = None
    if args.realtime_events_jsonl:
        realtime_report = run_realtime_validation(args)
        add_check(checks, "realtime_session", realtime_report["status"] == "ok", realtime_report.get("failedChecks"))
    elif args.allow_missing_realtime:
        add_check(checks, "realtime_session", True, "not provided; allowed by --allow-missing-realtime", state="warn")
    else:
        add_check(checks, "realtime_session", False, "missing --realtime-events-jsonl")

    add_check(
        checks,
        "secret_flags",
        all(
            report.get("apiKeyMaterialIncluded") is False and report.get("secretResourceNamesIncluded") is False
            for report in [offline_report, sunday_report, realtime_report]
            if isinstance(report, dict)
        ),
        None,
    )

    failed = [check for check in checks if check["state"] == "fail"]
    warnings = [check for check in checks if check["state"] == "warn"]
    return {
        "schemaVersion": 1,
        "status": "failed" if failed else "ok",
        "failedChecks": [check["name"] for check in failed],
        "warnings": [check["name"] for check in warnings],
        "checks": checks,
        "sunday": args.sunday,
        "offline": compact_report(offline_report),
        "sundayManifest": compact_report(sunday_report),
        "realtime": compact_report(realtime_report) if realtime_report else None,
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def run_offline_validation(args: argparse.Namespace) -> dict[str, Any]:
    report_text = offline_validator.read_text(args.offline_report)
    playback_text = offline_validator.read_text(args.playback_js)
    zh_vtt_text = offline_validator.read_text(args.zh_vtt)
    zh_srt_text = offline_validator.read_text(args.zh_srt)
    manifest_text = offline_validator.read_text(args.run_manifest) if args.run_manifest else None
    return offline_validator.validate_offline_chain(
        report=offline_validator.parse_json_object(report_text, "offline report"),
        report_text=report_text,
        report_uri=args.offline_report,
        playback=offline_validator.parse_playback_js(playback_text),
        playback_text=playback_text,
        playback_uri=args.playback_js,
        zh_vtt_text=zh_vtt_text,
        zh_vtt_uri=args.zh_vtt,
        zh_srt_text=zh_srt_text,
        zh_srt_uri=args.zh_srt,
        manifest=offline_validator.parse_json_object(manifest_text, "run manifest") if manifest_text else None,
        manifest_text=manifest_text,
        manifest_uri=args.run_manifest,
    )


def run_sunday_manifest_validation(args: argparse.Namespace) -> dict[str, Any]:
    manifest = sunday_validator.read_json(args.sunday_manifest)
    return sunday_validator.validate_manifest_contract(
        manifest=manifest,
        manifest_uri=args.sunday_manifest,
        sunday=args.sunday,
        expected_source_mode=args.expected_source_mode,
        require_readable_artifacts=args.require_readable_sunday_artifacts,
    )


def run_realtime_validation(args: argparse.Namespace) -> dict[str, Any]:
    raw_text = realtime_validator.read_text(args.realtime_events_jsonl)
    events = realtime_validator.parse_jsonl(raw_text)
    return realtime_validator.validate_realtime_session(
        events=events,
        raw_text=raw_text,
        events_uri=args.realtime_events_jsonl,
        require_stable_correction=not args.allow_missing_stable_correction,
    )


def compact_report(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if report is None:
        return None
    keys = [
        "status",
        "failedChecks",
        "offlineSourceKind",
        "offlineRoute",
        "asr",
        "translation",
        "outputs",
        "playback",
        "counts",
        "models",
        "realtimeSources",
        "targetLanguages",
        "audioSourceKinds",
    ]
    return {key: report[key] for key in keys if key in report}


def add_check(
    checks: list[dict[str, Any]],
    name: str,
    passed: bool,
    observed: Any = None,
    *,
    state: str | None = None,
) -> None:
    checks.append({"name": name, "state": state or ("pass" if passed else "fail"), "observed": observed})


if __name__ == "__main__":
    raise SystemExit(main())
