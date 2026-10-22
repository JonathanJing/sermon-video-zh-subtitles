#!/usr/bin/env python3
"""Back-transcribe sentence dubs with Qwen3-ASR and score them (experiment only).

``transcribe`` runs where ``qwen_asr`` and the model live (normally Spark) and
writes ``asr.jsonl`` (id, recognized). ``score`` runs anywhere with the
standard library: it compares each recognized text with ``spokenText`` after
removing punctuation and spaces and lists the sentences below ``--min``.
A score is a screening hint for listening, never a pass verdict.
"""
from __future__ import annotations

import argparse
import difflib
import json
from pathlib import Path
import re
import unicodedata

LANGUAGES = {"zh-Hans": "Chinese", "ko": "Korean", "es": "Spanish"}


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def transcribe(args) -> int:
    import soundfile as sf
    import torch
    from qwen_asr import Qwen3ASRModel
    speech = rows(args.speech)
    done = {r["id"] for r in rows(args.out)} if args.out.exists() else set()
    pending = [r for r in speech if r["id"] not in done]
    print(json.dumps({"sentences": len(speech), "pending": len(pending)}), flush=True)
    if not pending:
        return 0
    model = Qwen3ASRModel.from_pretrained(str(args.model), dtype=torch.bfloat16, device_map=args.device,
                                          max_inference_batch_size=args.batch_size, max_new_tokens=2048)
    with args.out.open("a", encoding="utf-8") as out:
        for start in range(0, len(pending), args.batch_size):
            batch = pending[start:start + args.batch_size]
            audio = [sf.read(str(args.tts / f"{r['id']}.wav"), dtype="float32") for r in batch]
            values = model.transcribe(audio=audio, language=[LANGUAGES[args.locale]] * len(batch))
            if len(values) != len(batch):
                raise SystemExit("ASR output count differs from input count")
            for r, value in zip(batch, values):
                out.write(json.dumps({"id": r["id"], "recognized": value.text}, ensure_ascii=False) + "\n")
            out.flush()
            print(json.dumps({"done": start + len(batch)}), flush=True)
    return 0


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    return "".join(ch for ch in text if not unicodedata.category(ch).startswith(("P", "Z", "S")))


def score(args) -> int:
    recognized = {r["id"]: r["recognized"] for r in rows(args.asr)}
    report = []
    for r in rows(args.speech):
        heard = recognized.get(r["id"])
        expected, got = normalize(r["spokenText"]), normalize(heard or "")
        ratio = difflib.SequenceMatcher(None, expected, got, autojunk=False).ratio() if heard is not None else 0.0
        report.append({"id": r["id"], "similarity": round(ratio, 3), "expected": r["spokenText"], "recognized": heard})
    flagged = [x for x in report if x["similarity"] < args.min]
    args.report.write_text(json.dumps({"min": args.min, "flagged": len(flagged), "sentences": report},
                                      ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"sentences": len(report), "flagged": len(flagged),
                      "meanSimilarity": round(sum(x["similarity"] for x in report) / len(report), 3)}))
    for x in sorted(flagged, key=lambda x: x["similarity"]):
        print(f'{x["id"]} {x["similarity"]:.3f}\n  want: {x["expected"]}\n  got:  {x["recognized"]}')
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    t = sub.add_parser("transcribe")
    t.add_argument("--speech", type=Path, required=True)
    t.add_argument("--tts", type=Path, required=True)
    t.add_argument("--model", type=Path, required=True)
    t.add_argument("--out", type=Path, required=True)
    t.add_argument("--locale", choices=sorted(LANGUAGES), default="zh-Hans")
    t.add_argument("--device", default="cuda:0")
    t.add_argument("--batch-size", type=int, default=8)
    s = sub.add_parser("score")
    s.add_argument("--speech", type=Path, required=True)
    s.add_argument("--asr", type=Path, required=True)
    s.add_argument("--report", type=Path, required=True)
    s.add_argument("--min", type=float, default=0.88)
    args = parser.parse_args()
    return transcribe(args) if args.command == "transcribe" else score(args)


if __name__ == "__main__":
    raise SystemExit(main())
