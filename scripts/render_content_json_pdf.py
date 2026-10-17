#!/usr/bin/env python3
"""Render a reading PDF from a published `/content/<pageId>/<locale>.json` full text.

The PDF is a local convenience export of text that is already published; it does
not create a new release identity and is not uploaded anywhere.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import urllib.request
from pathlib import Path


DEFAULT_BASE_URL = "https://ai-for-god-sermon-audio.web.app"
_RENDERER_PATH = Path(__file__).resolve().parent / "render_mobile_pdf_from_srt.py"
_SPEC = importlib.util.spec_from_file_location("render_mobile_pdf_from_srt", _RENDERER_PATH)
renderer = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
sys.modules[_SPEC.name] = renderer
_SPEC.loader.exec_module(renderer)


def main() -> int:
    args = parse_args()
    if args.content:
        raw = args.content.read_bytes()
        origin = str(args.content)
    else:
        origin = f"{args.base_url.rstrip('/')}/content/{args.page_id}/{args.locale}.json"
        with urllib.request.urlopen(origin, timeout=60) as response:
            raw = response.read()
    content = json.loads(raw)
    out = args.out or Path(f"{content.get('pageId') or args.page_id or 'sermon'}-{content.get('targetLocale') or content.get('locale') or args.locale}.pdf")
    out.parent.mkdir(parents=True, exist_ok=True)
    qa = render_content_pdf(
        content,
        out=out,
        include_english=not args.no_english,
        include_timecodes=not args.hide_timecodes,
        font_path=args.font_path,
    )
    qa["contentSource"] = origin
    qa["contentSha256"] = hashlib.sha256(raw).hexdigest()
    qa_path = out.with_suffix(".qa.json")
    qa_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"status": "ok", "out": str(out), "qa": str(qa_path), "qaStatus": qa["status"],
                      "cueCount": len(content.get("cues", []))}, ensure_ascii=False, indent=2))
    return 0


def render_content_pdf(
    content: dict,
    *,
    out: Path,
    include_english: bool = True,
    include_timecodes: bool = True,
    font_path: Path | None = None,
) -> dict:
    primary, secondary = content_cues(content)
    if not primary:
        raise SystemExit("Content JSON has no cues with text.")
    series, title = content.get("series"), content.get("title")
    heading = " · ".join(part for part in (series, title) if part) or content.get("pageId") or "Sermon"
    qa = renderer.render_reading_pdf(
        primary,
        secondary_cues=secondary if include_english else None,
        out=out,
        title=heading,
        subtitle=content.get("scripture"),
        sermon_date=content.get("date"),
        speaker=content.get("speaker"),
        font_path=font_path,
        include_timecodes=include_timecodes,
        disclaimer=footer_disclaimer(content),
    )
    qa["contentStatus"] = content.get("status") or content.get("translationStatus")
    return qa


def content_cues(content: dict) -> tuple[list, list]:
    primary, secondary = [], []
    for cue in content.get("cues", []):
        text = renderer.clean_caption_text(str(cue.get("text") or ""))
        if not text:
            continue
        start, end = srt_time(cue.get("start", 0)), srt_time(cue.get("end", cue.get("start", 0)))
        primary.append(renderer.Cue(start=start, end=end, text=text))
        source = renderer.clean_caption_text(str(cue.get("source") or ""))
        if source:
            secondary.append(renderer.Cue(start=start, end=end, text=source))
    return primary, secondary


def footer_disclaimer(content: dict) -> str:
    # Machine-checked content carries its own disclosure, which must stay visible.
    disclosure = (content.get("disclosure") or {}).get("text")
    base = renderer.COMPACT_DISCLAIMER
    return f"{disclosure} {base}" if disclosure else base


def srt_time(seconds: float) -> str:
    millis = max(0, round(float(seconds) * 1000))
    hours, rest = divmod(millis, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--content", type=Path, help="Local content JSON file.")
    source.add_argument("--page-id", help="Published pageId to download from --base-url.")
    parser.add_argument("--locale", default="zh-Hans", help="Content locale when downloading (default zh-Hans).")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--out", type=Path, help="Output PDF path (default <pageId>-<locale>.pdf).")
    parser.add_argument("--no-english", action="store_true", help="Omit the English source under each paragraph.")
    parser.add_argument("--hide-timecodes", action="store_true")
    parser.add_argument("--font-path", type=Path, help="Optional CJK TTF/TTC/OTF font to embed.")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
