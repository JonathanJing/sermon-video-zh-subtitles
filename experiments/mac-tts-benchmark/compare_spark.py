#!/usr/bin/env python3
"""Transcribe the Spark reference WAVs for flagged units (diagnostic comparison)."""
from __future__ import annotations
import argparse, json
from pathlib import Path

def main() -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--spark-tts", type=Path, required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--language", default="Chinese")
    a=p.parse_args()
    from mlx_audio.stt.utils import load_model
    import mlx.core as mx
    q=json.loads((a.run/"quality.json").read_text())
    ids=[row["id"] for row in q["failures"]]
    refs=a.run/"spark-refs"; refs.mkdir(exist_ok=True)
    asr=load_model(a.checkpoint)
    out=a.run/"spark-transcripts.jsonl"
    with out.open("w",encoding="utf-8") as stream:
        for i in ids:
            src=a.spark_tts/f"{i}.wav"
            if not src.exists():
                continue
            dst=refs/f"{i}.wav"
            if not dst.exists():
                dst.write_bytes(src.read_bytes())
            text=asr.generate(str(dst),language=a.language,max_tokens=512).text
            stream.write(json.dumps({"id":i,"recognized":text},ensure_ascii=False)+"\n")
            mx.clear_cache()
    print("done",len(ids))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
