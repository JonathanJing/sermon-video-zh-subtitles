#!/usr/bin/env python3
"""Review one sermon pipeline's names, scripture references, and Chinese cue text."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.sermon_pipeline import (
    chat_json,
    clean_text,
    qa_report,
    read_json,
    write_json,
    write_srt,
    write_vtt,
)


PROMPT_VERSION = "sermon-human-review-names-scripture-v2"

AUTHORITATIVE_NAMES = {
    "speaker": "Christine Caine",
    "church": "Mariners Church",
    "people": [
        "Ava",
        "Andrew",
        "Chris Hemsworth",
        "Jane Foster",
        "Natalie Portman",
        "Tom Cruise",
        "Meryl Streep",
        "Brad Pitt",
        "Denzel Washington",
        "Julia Roberts",
        "Catherine",
        "Sophia",
        "Nick",
        "Elizabeth Cady Stanton",
    ],
    "biblePeopleZh": {
        "Zelophehad": "西罗非哈",
        "Hepher": "希弗",
        "Gilead": "基列",
        "Machir": "玛吉",
        "Manasseh": "玛拿西",
        "Mahlah": "玛拉",
        "Hoglah": "曷拉",
        "Milcah": "密迦",
        "Tirzah": "得撒",
        "Moses": "摩西",
        "Eleazar": "以利亚撒",
        "Korah": "可拉",
        "Joshua": "约书亚",
        "Caleb": "迦勒",
    },
    "contextualNames": {
        "Noah (Genesis/Hebrews faith figure)": "挪亚",
        "Noah (daughter of Zelophehad, Numbers 26/27/36)": "挪阿",
    },
}

SCRIPTURE_REFERENCES = [
    "民数记 27:1-11",
    "民数记 26:1-2",
    "民数记 26:33",
    "民数记 27:8",
    "希伯来书 4:16",
    "罗马书 8:17",
    "哥林多后书 1:20",
    "民数记 13",
    "民数记 36:6-12",
]

MANUAL_ZH_FIXES = {
    8: "这部电影由澳大利亚巨星克里斯·海姆斯沃斯主演，她将在片中",
    30: "挪亚、摩西、亚伯拉罕、撒拉、底波拉、约瑟或以撒。他们都是A级人物。不过今天，",
    273: "在耶稣被出卖的那一夜，祂拿起这饼说：“这是我的身体，是",
    287: "但在那日到来以前，我们就要照门徒所做的那样，以歌声回应，把自己的生命",
    288: "满怀感恩地献给耶稣。因此，让我们歌颂祂所成就的一切，以及祂的一切所是。",
}

SYSTEM_PROMPT = """You are the final bilingual sermon-subtitle reviewer.
Return one JSON object with exactly this shape:
{"segments":[{"id":0,"zh":"..."}],"notes":["..."]}

Rules:
- Return every requested id exactly once, in the same order. Do not merge or split ids.
- Correct Simplified Chinese against the English source while using the adjacent context.
- Each cue may be a grammatical fragment, but it must join naturally to neighboring cues.
- Never insert an ellipsis merely because a sentence continues across cue boundaries.
- Preserve intentional quoted ellipses only when the English itself contains an intentional pause.
- Correct names, Bible names, book names, chapter/verse references, and theology terms.
- Use the supplied authoritative name map and scripture list.
- Use natural congregation-readable Chinese, with concise wording suitable for subtitles.
- Do not add facts, explanations, verse numbers, or quotation marks that the speaker did not say.
- Keep Mariners Church and Christine Caine in English for exact retrieval.
- Use 神 consistently for God, 主 for Lord, and 祂 for divine pronouns.
- Avoid stray spaces inside Chinese words and around Chinese punctuation.
- Do not put newline characters in zh; line wrapping is handled by the renderer.
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", type=Path, required=True)
    parser.add_argument("--model", default="gpt-5.6")
    parser.add_argument("--reasoning-effort", choices=["low", "medium", "high"], default="high")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--workers", type=int, default=3)
    return parser.parse_args()


def corrected_english(segments: list[dict]) -> list[dict]:
    reviewed = []
    for segment in segments:
        text = clean_text(segment.get("text", "")).replace("Christine Kane", "Christine Caine")
        if segment["id"] == 223:
            text = text.replace("case in chapter 26", "case in chapter 27")
        if segment["id"] == 256:
            text = text.replace("their capital", "their capitol")
        reviewed.append({**segment, "text": text, "reviewStatus": "reviewed"})
    return reviewed


def enforce_contextual_name_rules(en_segments: list[dict], zh_segments: list[dict]) -> list[dict]:
    """Resolve homonymous Bible names using nearby English context."""
    result: list[dict] = []
    for index, (english, chinese) in enumerate(zip(en_segments, zh_segments)):
        start = max(0, index - 2)
        end = min(len(en_segments), index + 3)
        context = " ".join(str(item.get("text") or "") for item in en_segments[start:end]).lower()
        text = str(chinese.get("zh") or "")
        daughters_context = any(
            term in context
            for term in ("zelophehad", "daughter", "mahlah", "hoglah", "milcah", "tirzah", "numbers 27")
        )
        faith_context = any(
            term in context
            for term in ("hebrews 11", "ark", "flood", "abraham", "sarah", "moses")
        )
        if daughters_context and not faith_context:
            text = text.replace("挪亚", "挪阿")
        elif faith_context and not daughters_context:
            text = text.replace("挪阿", "挪亚")
        result.append({**chinese, "zh": text})
    return result


def batch_payload(
    all_segments: list[dict],
    batch: list[dict],
    start_index: int,
    model: str,
    reasoning_effort: str,
) -> dict:
    before = all_segments[start_index - 1] if start_index > 0 else None
    after_index = start_index + len(batch)
    after = all_segments[after_index] if after_index < len(all_segments) else None
    context = {
        "authoritativeNames": AUTHORITATIVE_NAMES,
        "scriptureReferences": SCRIPTURE_REFERENCES,
        "previous": {"id": before["id"], "en": before["text"], "zh": before.get("zh", "")} if before else None,
        "segments": [
            {"id": item["id"], "en": item["text"], "draftZh": item.get("zh", "")}
            for item in batch
        ],
        "next": {"id": after["id"], "en": after["text"], "zh": after.get("zh", "")} if after else None,
    }
    return {
        "model": model,
        "reasoning_effort": reasoning_effort,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
        ],
    }


def review_batch(
    api_key: str,
    all_segments: list[dict],
    batch: list[dict],
    start_index: int,
    cache_dir: Path,
    model: str,
    reasoning_effort: str,
) -> dict:
    identity = hashlib.sha256(
        f"{PROMPT_VERSION}|{model}|{reasoning_effort}".encode("utf-8")
    ).hexdigest()[:12]
    cache = cache_dir / f"review_{batch[0]['id']:04d}_{batch[-1]['id']:04d}.{identity}.json"
    if cache.exists():
        parsed = read_json(cache)
    else:
        result = chat_json(
            api_key,
            batch_payload(all_segments, batch, start_index, model, reasoning_effort),
        )
        parsed = json.loads(result["choices"][0]["message"]["content"])
        parsed["_model"] = result.get("model", model)
        write_json(cache, parsed)
    expected = [item["id"] for item in batch]
    returned = [item.get("id") for item in parsed.get("segments", [])]
    if returned != expected:
        raise RuntimeError(f"Review id mismatch for {expected[0]}-{expected[-1]}: {returned}")
    for item in parsed["segments"]:
        zh = clean_text(item.get("zh", ""))
        if not zh:
            raise RuntimeError(f"Empty reviewed Chinese for segment {item.get('id')}")
        item["zh"] = zh
    return parsed


def main() -> int:
    args = parse_args()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY is not set")

    en_path = args.outdir / "segments_timed_en_corrected.json"
    zh_path = args.outdir / "segments_timed_zh.json"
    en_segments = corrected_english(read_json(en_path))
    draft_zh = read_json(zh_path)
    if [item["id"] for item in en_segments] != [item["id"] for item in draft_zh]:
        raise RuntimeError("English and Chinese segment ids do not match")
    combined = [{**en, "zh": zh.get("zh", "")} for en, zh in zip(en_segments, draft_zh)]

    batches = []
    for start in range(0, len(combined), max(1, args.batch_size)):
        batches.append((start, combined[start : start + max(1, args.batch_size)]))
    cache_dir = args.outdir / "review_windows"
    cache_dir.mkdir(parents=True, exist_ok=True)

    def run_one(item: tuple[int, list[dict]]) -> tuple[int, dict]:
        start, batch = item
        parsed = review_batch(
            api_key,
            combined,
            batch,
            start,
            cache_dir,
            args.model,
            args.reasoning_effort,
        )
        print(f"reviewed {batch[0]['id']}-{batch[-1]['id']}", flush=True)
        return start, parsed

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        for result in executor.map(run_one, batches):
            results.append(result)
    results.sort(key=lambda item: item[0])

    reviewed_by_id = {
        item["id"]: item["zh"]
        for _, parsed in results
        for item in parsed["segments"]
    }
    reviewed_zh = [
        {
            **segment,
            "zh": MANUAL_ZH_FIXES.get(segment["id"], reviewed_by_id[segment["id"]]),
            "reviewStatus": "reviewed",
            "reviewModel": args.model,
            "reviewPromptVersion": PROMPT_VERSION,
        }
        for segment in en_segments
    ]
    reviewed_zh = enforce_contextual_name_rules(en_segments, reviewed_zh)

    write_json(args.outdir / "segments_timed_en.reviewed.json", en_segments)
    write_json(args.outdir / "segments_timed_zh.reviewed.json", reviewed_zh)
    write_srt(args.outdir / "sermon_en_relative.reviewed.srt", en_segments, "text", lang="en")
    write_vtt(args.outdir / "sermon_en_relative.reviewed.vtt", en_segments, "text", lang="en")
    write_srt(args.outdir / "sermon_zh_relative.reviewed.srt", reviewed_zh, "zh", lang="zh")
    write_vtt(args.outdir / "sermon_zh_relative.reviewed.vtt", reviewed_zh, "zh", lang="zh")
    write_srt(args.outdir / "full_video_en_from_sermon.reviewed.srt", en_segments, "text", offset=1545.0, lang="en")
    write_vtt(args.outdir / "full_video_en_from_sermon.reviewed.vtt", en_segments, "text", offset=1545.0, lang="en")
    write_srt(args.outdir / "full_video_zh_from_sermon.reviewed.srt", reviewed_zh, "zh", offset=1545.0, lang="zh")
    write_vtt(args.outdir / "full_video_zh_from_sermon.reviewed.vtt", reviewed_zh, "zh", offset=1545.0, lang="zh")

    qa = qa_report(en_segments, reviewed_zh, [])
    ellipsis_ids = [
        item["id"] for item in reviewed_zh if "……" in item["zh"] or "..." in item["zh"]
    ]
    report = {
        "status": "reviewed-needs-operator-approval",
        "promptVersion": PROMPT_VERSION,
        "model": args.model,
        "segmentCount": len(reviewed_zh),
        "speaker": "Christine Caine",
        "scriptureReferences": SCRIPTURE_REFERENCES,
        "authoritativeNames": AUTHORITATIVE_NAMES,
        "remainingEllipsisSegmentIds": ellipsis_ids,
        "qa": qa,
        "notes": [note for _, parsed in results for note in parsed.get("notes", [])],
    }
    write_json(args.outdir / "review_report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
