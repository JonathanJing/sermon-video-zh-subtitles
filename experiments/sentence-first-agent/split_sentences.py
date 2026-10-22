#!/usr/bin/env python3
"""Split word times into sentences (experiment only, no identity checks).

Input is either a flat word list ``[{"text", "start", "end"}, ...]`` or a
``sermon-sentence-anchor-manifest-v2`` whose ``sourceUnits`` are reused as is.
Output is one JSON object per line: id, english, start, end, pauseAfter, words.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

SENTENCE_END = (".", "?", "!")
# Trailing quote or bracket after the end mark still closes the sentence.
CLOSERS = "\"'”’)]"


def load_words(path: Path) -> tuple[list[dict], list[dict] | None]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(value, dict) and value.get("schemaVersion") == "sermon-sentence-anchor-manifest-v2":
        units = []
        for unit in value["sourceUnits"]:
            units.append({"english": unit["english"], "start": unit["start"], "end": unit["end"],
                          "pauseAfter": unit["boundary"]["pauseAfterSeconds"],
                          "words": [{"text": w["text"], "start": w["start"], "end": w["end"]}
                                    for w in unit["words"]]})
        return [], units
    if isinstance(value, dict):
        value = value.get("words") or value.get("wordTimes")
    if not isinstance(value, list) or not value:
        raise SystemExit("words: expected a non-empty list of {text,start,end}")
    words = []
    for row in value:
        text = str(row.get("text") or row.get("word") or "").strip()
        if not text:
            continue
        words.append({"text": text, "start": float(row["start"]), "end": float(row["end"])})
    words.sort(key=lambda w: (w["start"], w["end"]))
    return words, None


def ends_sentence(text: str) -> bool:
    return text.rstrip(CLOSERS).endswith(SENTENCE_END)


def split(words: list[dict], *, max_seconds: float, min_pause: float) -> list[dict]:
    sentences, current = [], []
    for index, word in enumerate(words):
        current.append(word)
        if ends_sentence(word["text"]) or index == len(words) - 1:
            sentences.extend(split_long(current, max_seconds=max_seconds, min_pause=min_pause))
            current = []
    return sentences


def split_long(words: list[dict], *, max_seconds: float, min_pause: float) -> list[dict]:
    if words[-1]["end"] - words[0]["start"] <= max_seconds or len(words) < 2:
        return [make(words)]
    # Longest audible pause inside the sentence, away from its edges, wins.
    best, best_gap = None, min_pause
    for i in range(1, len(words) - 1):
        gap = words[i]["start"] - words[i - 1]["end"]
        if gap >= best_gap:
            best, best_gap = i, gap
    if best is None:
        return [make(words)]
    return (split_long(words[:best], max_seconds=max_seconds, min_pause=min_pause)
            + split_long(words[best:], max_seconds=max_seconds, min_pause=min_pause))


def make(words: list[dict]) -> dict:
    return {"english": " ".join(w["text"] for w in words), "start": words[0]["start"],
            "end": words[-1]["end"], "words": list(words)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--words", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-seconds", type=float, default=12.0)
    parser.add_argument("--min-pause", type=float, default=0.45)
    args = parser.parse_args()
    words, units = load_words(args.words)
    sentences = units if units is not None else split(words, max_seconds=args.max_seconds,
                                                      min_pause=args.min_pause)
    for i, sentence in enumerate(sentences):
        sentence["id"] = f"s{i + 1:04d}"
        if "pauseAfter" not in sentence:
            nxt = sentences[i + 1]["start"] if i + 1 < len(sentences) else sentence["end"]
            sentence["pauseAfter"] = round(max(0.0, nxt - sentence["end"]), 3)
        sentence["start"] = round(sentence["start"], 3)
        sentence["end"] = round(sentence["end"], 3)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as out:
        for sentence in sentences:
            ordered = {k: sentence[k] for k in ("id", "english", "start", "end", "pauseAfter", "words")}
            out.write(json.dumps(ordered, ensure_ascii=False) + "\n")
    print(json.dumps({"sentences": len(sentences), "out": str(args.out),
                      "source": "anchor_manifest" if units is not None else "word_list"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
