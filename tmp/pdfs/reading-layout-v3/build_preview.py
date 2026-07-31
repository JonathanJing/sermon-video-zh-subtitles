#!/usr/bin/env python3
"""Build a layout-only compact SRT pair from the previously reviewed reading blocks."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SOURCE = (
    ROOT
    / "artifacts/model-evals/2026-07-31-gpt-transcribe-reading-pdf-audit"
    / "work-root/2026-07-26/0tqIipLfBVQ/pipeline/reading-edition-v2/reading_blocks.final.json"
)
OUTDIR = Path(__file__).resolve().parent
TARGET_ENGLISH_CHARS = 480
TARGET_CHINESE_CHARS = 160


def sentence_parts(text: str, *, chinese: bool) -> list[str]:
    pattern = r"(?<=[。！？])" if chinese else r"(?<=[.!?])\s+"
    return [part.strip() for part in re.split(pattern, text.strip()) if part.strip()] or [text.strip()]


def balanced_groups(parts: list[str], count: int, *, chinese: bool) -> list[str]:
    count = max(1, min(count, len(parts)))
    groups: list[str] = []
    cursor = 0
    for group_index in range(count):
        remaining_groups = count - group_index
        remaining_parts = len(parts) - cursor
        take = max(1, round(remaining_parts / remaining_groups))
        end = min(len(parts), cursor + take)
        selected = parts[cursor:end]
        groups.append(("" if chinese else " ").join(selected))
        cursor = end
    if cursor < len(parts):
        groups[-1] = ("" if chinese else " ").join([groups[-1], *parts[cursor:]])
    return groups


def srt_time(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def write_srt(path: Path, rows: list[dict], field: str) -> None:
    lines: list[str] = []
    for index, row in enumerate(rows, 1):
        lines.extend(
            [
                str(index),
                f"{srt_time(row['start'])} --> {srt_time(row['end'])}",
                row[field],
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    source_blocks = json.loads(SOURCE.read_text(encoding="utf-8"))
    compact: list[dict] = []
    for source in source_blocks:
        english_parts = sentence_parts(source["en"], chinese=False)
        chinese_parts = sentence_parts(source["zh"], chinese=True)
        requested = max(
            1,
            math.ceil(len(source["en"]) / TARGET_ENGLISH_CHARS),
            math.ceil(len(source["zh"]) / TARGET_CHINESE_CHARS),
        )
        count = min(requested, len(english_parts), len(chinese_parts))
        english_groups = balanced_groups(english_parts, count, chinese=False)
        chinese_groups = balanced_groups(chinese_parts, count, chinese=True)
        duration = float(source["end"]) - float(source["start"])
        for index, (english, chinese) in enumerate(zip(english_groups, chinese_groups)):
            compact.append(
                {
                    "start": float(source["start"]) + duration * index / count,
                    "end": float(source["start"]) + duration * (index + 1) / count,
                    "en": english,
                    "zh": chinese,
                }
            )

    normalized_source_en = re.sub(r"\s+", " ", " ".join(item["en"] for item in source_blocks)).strip()
    normalized_compact_en = re.sub(r"\s+", " ", " ".join(item["en"] for item in compact)).strip()
    source_zh = "".join(item["zh"] for item in source_blocks)
    compact_zh = "".join(item["zh"] for item in compact)
    if normalized_source_en != normalized_compact_en or source_zh != compact_zh:
        raise RuntimeError("Compact layout preview changed the reviewed bilingual text.")

    OUTDIR.mkdir(parents=True, exist_ok=True)
    write_srt(OUTDIR / "reading.compact.en.srt", compact, "en")
    write_srt(OUTDIR / "reading.compact.zh.srt", compact, "zh")
    (OUTDIR / "preview-manifest.json").write_text(
        json.dumps(
            {
                "sourceBlockCount": len(source_blocks),
                "compactBlockCount": len(compact),
                "englishTextPreserved": True,
                "chineseTextPreserved": True,
                "targetEnglishCharacters": TARGET_ENGLISH_CHARS,
                "targetChineseCharacters": TARGET_CHINESE_CHARS,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
