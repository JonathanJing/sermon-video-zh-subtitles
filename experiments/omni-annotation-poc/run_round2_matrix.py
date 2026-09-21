#!/usr/bin/env python3
"""Run selected round-two corpus cases through Gemini Live or an OpenAI-compatible model."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--provider", choices=("gemini", "openai-compatible"), required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--base-url")
    parser.add_argument("--server-media-root", default="/data",
                        help="Container-visible root corresponding to the manifest directory")
    parser.add_argument("--sample", action="append", default=[])
    parser.add_argument("--condition", action="append", default=[])
    parser.add_argument("--enable-thinking", action="store_true")
    parser.add_argument("--max-tokens", type=int, default=2048)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    manifest_root = args.manifest.resolve().parent
    script_dir = Path(__file__).resolve().parent
    selected = [case for case in manifest["matrix"]
                if (not args.sample or case["sampleId"] in args.sample)
                and (not args.condition or case["conditionId"] in args.condition)]
    if not selected:
        raise SystemExit("No matrix cases selected")
    failures = 0
    for index, case in enumerate(selected, start=1):
        print(f'[{index}/{len(selected)}] {case["caseId"]}', flush=True)
        prompt = (manifest_root / case["prompt"]).resolve()
        video = (manifest_root / case["video"]).resolve()
        audio = (manifest_root / case["audio"]).resolve()
        common = [
            "--model", args.model, "--prompt", str(prompt), "--video", str(video),
            "--audio", str(audio), "--duration", str(case["durationSeconds"]),
            "--case-id", case["caseId"], "--out", str(args.out),
        ]
        for key, flag in (("expectedAudioStatus", "--expected-audio-status"),
                          ("expectedVideoStatus", "--expected-video-status"),
                          ("expectedTranscriptStatus", "--expected-transcript-status")):
            if case.get(key):
                common.extend([flag, case[key]])
        if args.provider == "gemini":
            command = [sys.executable, str(script_dir / "run_gemini_live.py")]
            if args.env_file:
                command.extend(["--env-file", str(args.env_file)])
        else:
            if not args.base_url:
                raise SystemExit("--base-url is required for openai-compatible provider")
            command = [sys.executable, str(script_dir / "run_openai_compatible.py"),
                       "--base-url", args.base_url,
                       "--server-video-uri", f'file://{Path(args.server_media_root) / video.relative_to(manifest_root)}',
                       "--server-audio-uri", f'file://{Path(args.server_media_root) / audio.relative_to(manifest_root)}',
                       "--max-tokens", str(args.max_tokens)]
            if args.enable_thinking:
                command.append("--enable-thinking")
        completed = subprocess.run(command + common, check=False)
        if completed.returncode:
            failures += 1
            print(f'case_failed={case["caseId"]} exit={completed.returncode}', file=sys.stderr)
    if failures:
        raise SystemExit(f"{failures} matrix case(s) failed")


if __name__ == "__main__":
    main()
