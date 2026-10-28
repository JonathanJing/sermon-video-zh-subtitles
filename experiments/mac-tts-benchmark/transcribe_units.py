#!/usr/bin/env python3
"""Transcribe benchmark WAVs with the local MLX Qwen3-ASR (diagnostic only)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--language", default="Chinese")
    args = parser.parse_args()
    from mlx_audio.stt.utils import load_model
    import mlx.core as mx

    log = [json.loads(line) for line in (args.run / "tts-log.jsonl").read_text().splitlines() if line.strip()]
    asr = load_model(args.checkpoint)
    out = args.run / "transcripts.jsonl"
    with out.open("w", encoding="utf-8") as stream:
        for index, entry in enumerate(log, 1):
            text = asr.generate(str(args.run / "units" / f"{entry['id']}.wav"),
                                language=args.language, max_tokens=512).text
            stream.write(json.dumps({"id": entry["id"], "recognized": text}, ensure_ascii=False) + "\n")
            mx.clear_cache()
            print(f"{index}/{len(log)} {entry['id']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
