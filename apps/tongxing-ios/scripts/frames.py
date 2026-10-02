#!/usr/bin/env python3
"""Optional Frames CLI post-processing; never capture, build, install, or publish."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def has_error(value: object) -> bool:
    """Upstream may report errors in JSON even when the process exits zero."""
    if isinstance(value, dict):
        return bool(value.get("error") or value.get("setup_required")) or any(
            has_error(item) for item in value.values()
        )
    if isinstance(value, list):
        return any(has_error(item) for item in value)
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path, help="Existing PNGs, or videos with --video")
    parser.add_argument("--video", action="store_true", help="Accept MP4/MOV/M4V instead of PNG")
    parser.add_argument("--merge", action="store_true", help="Place inputs side by side in given order")
    parser.add_argument("--playback-offset", action="store_true", help="Play merged videos sequentially")
    parser.add_argument("--device", help="Exact name from upstream frames list; recommended for repeatability")
    parser.add_argument("--color", help="Exact bezel color from upstream frames list-colors")
    parser.add_argument("--preset", choices=("compact", "balanced", "best"), help="Video only; default balanced")
    parser.add_argument("--assets", type=Path, help="Existing upstream asset directory")
    parser.add_argument("--dry-run", action="store_true", help="Validate inputs and print command; do not write or run tools")
    args = parser.parse_args(argv)
    if args.playback_offset and not (args.video and args.merge):
        parser.error("--playback-offset requires --video --merge")
    if args.preset and not args.video:
        parser.error("--preset requires --video")
    if args.merge and len(args.inputs) < 2:
        parser.error("--merge requires at least two inputs")
    inputs = [path.expanduser().resolve() for path in args.inputs]
    suffixes = {".mp4", ".mov", ".m4v"} if args.video else {".png"}
    for path in inputs:
        if not path.is_file() or path.suffix.lower() not in suffixes:
            parser.error(f"Expected an existing {'video' if args.video else 'PNG'} file: {path}")
    if not args.merge and len({path.stem.casefold() for path in inputs}) != len(inputs):
        parser.error("Inputs share an output basename; rename copies or process them in separate runs")
    if args.assets and not args.assets.expanduser().is_dir():
        parser.error("--assets must be an existing directory")

    requested = os.environ.get("TONGXING_FRAMES_BIN", "frames")
    binary = shutil.which(requested)
    if not binary and not args.dry_run:
        print("Frames CLI not found. Follow apps/tongxing-ios/FRAMES.zh.md; no automatic installation.", file=sys.stderr)
        return 127
    parent = ROOT / "artifacts" / "tongxing-ios" / datetime.now().strftime("%Y-%m-%d") / "frames"
    output = parent / "<unique-run>"
    if not args.dry_run:
        parent.mkdir(parents=True, exist_ok=True)
        output = Path(tempfile.mkdtemp(prefix="run-", dir=parent))
    command = [binary or requested, "--json", "video" if args.video else "frame", "-o", str(output)]
    if args.merge:
        command.append("-m")
    if args.playback_offset:
        command.append("--playback-offset")
    for flag, value in (("--device", args.device), ("--color", args.color), ("--assets", args.assets)):
        if value is not None:
            command.extend([flag, str(Path(value).expanduser().resolve()) if flag == "--assets" else str(value)])
    if args.video:
        command.extend(["--preset", args.preset or "balanced"])
    command.extend(str(path) for path in inputs)
    if args.dry_run:
        print(shlex.join(command))
        return 0

    receipt = {"scope": "presentation_only", "status": "running", "command": command, "sources": []}
    code = 1
    try:
        receipt["sources"] = [{"path": str(path), "sha256": sha256(path)} for path in inputs]
        result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
        (output / "frames-result.json").write_text(result.stdout, encoding="utf-8")
        (output / "run.log").write_text(result.stderr, encoding="utf-8")
        receipt["upstream_exit_code"] = result.returncode
        code = result.returncode if result.returncode >= 0 else 128 - result.returncode
        if code:
            raise RuntimeError(f"Frames exited {result.returncode}; see run.log and frames-result.json")
        payload = json.loads(result.stdout)
        if has_error(payload):
            raise RuntimeError("Frames reported a JSON error; inspect frames-result.json and configure assets manually")
        output_suffixes = {".mp4", ".mov"} if args.video else {".png"}
        files = sorted(path for path in output.iterdir() if path.is_file() and path.suffix.lower() in output_suffixes)
        expected = 1 if args.merge else len(inputs)
        if len(files) != expected or any(path.stat().st_size == 0 for path in files):
            raise RuntimeError(f"Expected {expected} nonempty framed output(s), found {len(files)}")
        if any(sha256(Path(source["path"])) != source["sha256"] for source in receipt["sources"]):
            raise RuntimeError("Source changed during framing; retain evidence and rerun from frozen inputs")
        receipt["outputs"] = [{"path": str(path), "sha256": sha256(path)} for path in files]
        receipt["status"] = "completed"
    except (OSError, ValueError, RuntimeError) as exc:
        code = code or 1
        receipt["status"] = "failed"
        receipt["error"] = str(exc)
        print(str(exc), file=sys.stderr)
    receipt["exit_code"] = code
    (output / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(str(output))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
