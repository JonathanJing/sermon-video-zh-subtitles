#!/usr/bin/env python3
"""One batch on MPS, reporting allocator peaks and the recommended working set."""
from __future__ import annotations
import argparse, json
from pathlib import Path
import torch

def main() -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--checkpoint", type=Path, required=True)
    p.add_argument("--speech", type=Path, required=True)
    p.add_argument("--batch-size", type=int, default=8)
    a=p.parse_args()
    rows=[json.loads(l) for l in a.speech.read_text().splitlines() if l.strip()][:a.batch_size]
    from qwen_tts import Qwen3TTSModel
    model=Qwen3TTSModel.from_pretrained(str(a.checkpoint), device_map="mps", dtype=torch.float32)
    print(json.dumps({"afterLoadAllocatedGiB": round(torch.mps.current_allocated_memory()/2**30,2),
                      "afterLoadDriverGiB": round(torch.mps.driver_allocated_memory()/2**30,2),
                      "recommendedMaxGiB": round(torch.mps.recommended_max_memory()/2**30,2)}), flush=True)
    wavs, rate = model.generate_custom_voice(
        text=[r["spokenText"] for r in rows], language=[r["language"] for r in rows],
        speaker=[r["speaker"] for r in rows], temperature=0.7, repetition_penalty=1.05, max_new_tokens=768)
    torch.mps.synchronize()
    print(json.dumps({"afterBatchAllocatedGiB": round(torch.mps.current_allocated_memory()/2**30,2),
                      "afterBatchDriverGiB": round(torch.mps.driver_allocated_memory()/2**30,2),
                      "peakAllocatedGiB": round(torch.mps.max_memory_allocated()/2**30,2) if hasattr(torch.mps,'max_memory_allocated') else None,
                      "waves": len(wavs), "sampleRate": rate}), flush=True)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
