#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.content_pack import load_pack
from backend.replay_ab import (
    default_output_dir,
    ollama_translator,
    read_asr_finals,
    run_replay,
    write_replay_artifacts,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay frozen English ASR finals across context policies.")
    parser.add_argument("session_dir")
    parser.add_argument("--pack", default="artifacts/weekly-pack.json")
    parser.add_argument("--policies", default="none,saturday_alignment_v1")
    parser.add_argument("--model", default=os.environ.get("LOCAL_LIVE_OLLAMA_MODEL", "sermon-milmmt-46-4b-v1-q8:benchmark"))
    parser.add_argument("--ollama-url", default=os.environ.get("LOCAL_LIVE_OLLAMA_URL", "http://127.0.0.1:11434"))
    parser.add_argument("--output")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    policies = [value.strip() for value in args.policies.split(",") if value.strip()]
    segments = read_asr_finals(args.session_dir)
    if args.limit > 0:
        segments = segments[:args.limit]
    pack = load_pack(args.pack) if Path(args.pack).is_file() else None
    if args.dry_run:
        print(json.dumps({
            "session": str(Path(args.session_dir).resolve()),
            "segments": len(segments),
            "policies": policies,
            "model": args.model,
            "packVersion": pack.get("packVersion") if pack else None,
        }, ensure_ascii=False, indent=2))
        return
    output = Path(args.output) if args.output else default_output_dir(args.session_dir)
    results = run_replay(segments, policies, ollama_translator(args.model, args.ollama_url), pack)
    run = write_replay_artifacts(args.session_dir, output, policies, results, args.model, pack)
    print(json.dumps({"output": str(output.resolve()), **run}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
