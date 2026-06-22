#!/usr/bin/env python3
"""Prepare web playback simulation data from a YouTube live archive link."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
OFFLINE_POC = REPO_ROOT / "scripts" / "offline_live_sermon_subtitles.py"
BUILD_PLAYBACK = REPO_ROOT / "scripts" / "build_playback_simulation.py"


def main() -> int:
    args = parse_args()
    out_dir = resolve_repo_path(args.out_dir)
    web_out = resolve_repo_path(args.web_out)
    out_dir.mkdir(parents=True, exist_ok=True)

    run(
        [
            sys.executable,
            str(OFFLINE_POC),
            "--live-url",
            args.live_url,
            "--out-dir",
            str(out_dir),
            "--playlist-end",
            str(args.playlist_end),
        ]
        + optional("--sermon-url", args.sermon_url)
        + optional("--sermon-start", args.sermon_start)
        + repeat("--lang", args.lang),
        cwd=REPO_ROOT,
    )

    run(
        [
            sys.executable,
            str(BUILD_PLAYBACK),
            "--report",
            str(out_dir / "report.json"),
            "--out",
            str(web_out),
            "--max-segments",
            str(args.max_segments),
            "--playback-speed",
            str(args.playback_speed),
        ]
        + optional("--lang", args.playback_lang),
        cwd=REPO_ROOT,
    )

    print(f"Prepared playback simulation: {web_out}")
    print("Open web/index.html and click 模拟播放.")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Given a YouTube live archive link, prepare web playback simulation data."
    )
    parser.add_argument("--live-url", required=True, help="YouTube live archive URL.")
    parser.add_argument(
        "--sermon-url",
        help="Optional edited sermon VOD URL when discovery should be skipped or pinned.",
    )
    parser.add_argument(
        "--sermon-start",
        help="Optional live timeline sermon start override, e.g. 00:23:25.",
    )
    parser.add_argument(
        "--lang",
        action="append",
        default=[],
        help="Caption language requested from YouTube. Repeatable; defaults to POC preferences.",
    )
    parser.add_argument(
        "--playback-lang",
        help="Preferred language from generated POC outputs for browser playback.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("artifacts/offline-live-sermon-poc"),
        help="POC artifact directory.",
    )
    parser.add_argument(
        "--web-out",
        type=Path,
        default=Path("web/playback-simulation.generated.js"),
        help="Generated JS file loaded by web/index.html.",
    )
    parser.add_argument("--playlist-end", type=int, default=40)
    parser.add_argument("--max-segments", type=int, default=80)
    parser.add_argument("--playback-speed", type=float, default=18.0)
    return parser.parse_args()


def optional(flag: str, value: str | None) -> list[str]:
    return [flag, value] if value else []


def repeat(flag: str, values: list[str]) -> list[str]:
    args = []
    for value in values:
        args.extend([flag, value])
    return args


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def run(command: list[str], cwd: Path) -> None:
    printable = " ".join(command)
    print(f"$ {printable}")
    subprocess.run(command, cwd=cwd, check=True)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode)
