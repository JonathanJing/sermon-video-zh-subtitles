#!/usr/bin/env python3
"""Render a reading PDF from a published `/content/<pageId>/zh-Hans.json` full text.

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
LOCALE = "zh-Hans"
REFERENCE_SCHEMA = "sermon-published-english-reference-v1"
_RENDERER_PATH = Path(__file__).resolve().parent / "render_mobile_pdf_from_srt.py"
_SPEC = importlib.util.spec_from_file_location("render_mobile_pdf_from_srt", _RENDERER_PATH)
renderer = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
sys.modules[_SPEC.name] = renderer
_SPEC.loader.exec_module(renderer)


def main() -> int:
    args = parse_args()
    base = args.base_url.rstrip("/")
    if args.content:
        raw, origin = args.content.read_bytes(), str(args.content)
    else:
        origin = f"{base}/content/{args.page_id}/{LOCALE}.json"
        raw = fetch(origin)
    content = json.loads(raw)
    locale = content.get("targetLocale") or content.get("locale")
    if locale != LOCALE:
        raise SystemExit(f"Only {LOCALE} content is supported (the renderer's fonts and metadata are Chinese); got {locale!r}.")
    content_sha = hashlib.sha256(raw).hexdigest()
    reference = reference_raw = reference_origin = None
    if args.english_reference:
        reference_raw, reference_origin = args.english_reference.read_bytes(), str(args.english_reference)
    elif not args.no_english and args.page_id and not has_inline_english(content):
        reference_origin = f"{base}/english-reference/{args.page_id}.json"
        reference_raw = fetch(reference_origin)
    if reference_raw is not None:
        reference = json.loads(reference_raw)
    page_id = content.get("pageId") or args.page_id or "sermon"
    out = args.out or Path(f"{page_id}-{LOCALE}.pdf")
    out.parent.mkdir(parents=True, exist_ok=True)
    qa = render_content_pdf(
        content,
        out=out,
        include_english=not args.no_english,
        english_reference=reference,
        content_sha256=content_sha,
        include_timecodes=not args.hide_timecodes,
        font_path=args.font_path,
    )
    qa["contentSource"] = origin
    qa["contentSha256"] = content_sha
    if reference_raw is not None:
        qa["englishReferenceSource"] = reference_origin
        qa["englishReferenceSha256"] = hashlib.sha256(reference_raw).hexdigest()
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
    english_reference: dict | None = None,
    content_sha256: str | None = None,
    include_timecodes: bool = True,
    font_path: Path | None = None,
) -> dict:
    english = reference_english(english_reference, content, content_sha256) if english_reference else {}
    primary, secondary = content_cues(content, english)
    if not primary:
        raise SystemExit("Content JSON has no cues with text.")
    if include_english and len(secondary) != len(primary):
        raise SystemExit(f"English is missing for {len(primary) - len(secondary)} of {len(primary)} cues; "
                         "pass a matching --english-reference or use --no-english.")
    disclaimer = footer_disclaimer(content)
    footer_font = renderer.register_cjk_font(font_path)
    footer_width = renderer.MOBILE_PAGE_SIZE[0] - renderer.MARGIN_X * 2
    if len(renderer.wrap_text(disclaimer, footer_font, renderer.FOOTER_FONT_SIZE, footer_width)) > renderer.FOOTER_MAX_LINES:
        raise SystemExit("Footer disclosure does not fit; it must be shown in full.")
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
        disclaimer=disclaimer,
        subject="Mobile Chinese-English sermon reading edition" if include_english else "Mobile Chinese sermon reading edition",
    )
    qa["contentStatus"] = content.get("status") or content.get("translationStatus")
    return qa


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def has_inline_english(content: dict) -> bool:
    return any(str(cue.get("source") or "").strip() for cue in content.get("cues", []))


def reference_english(reference: dict, content: dict, content_sha256: str | None) -> dict[str, str]:
    """Map textGroupId to English from a published english-reference bound to this content."""
    if (reference.get("schemaVersion"), reference.get("reviewState")) != (REFERENCE_SCHEMA, "human_approved"):
        raise SystemExit("English reference is not a human-approved published reference.")
    if content.get("englishSourcePackageJsonSha256") and (
            reference.get("sourceIdentitySha256") != content["englishSourcePackageJsonSha256"]):
        raise SystemExit("English reference source identity differs from the content's.")
    target = (reference.get("targets") or {}).get(LOCALE)
    if reference.get("pageId") != content.get("pageId") or not target:
        raise SystemExit("English reference does not cover this page and locale.")
    if content_sha256 and target.get("contentSha256") != content_sha256:
        raise SystemExit("English reference is bound to different content bytes.")
    return {block["textGroupId"]: block["english"] for block in target.get("blocks", [])}


def content_cues(content: dict, english: dict[str, str] | None = None) -> tuple[list, list]:
    primary, secondary = [], []
    for cue in content.get("cues", []):
        text = renderer.clean_caption_text(str(cue.get("text") or ""))
        if not text:
            continue
        start, end = srt_time(cue.get("start", 0)), srt_time(cue.get("end", cue.get("start", 0)))
        primary.append(renderer.Cue(start=start, end=end, text=text))
        source = renderer.clean_caption_text(str(cue.get("source") or (english or {}).get(cue.get("textGroupId"), "")))
        if source:  # a cue without English is counted, never borrowed from a neighbour
            secondary.append(renderer.Cue(start=start, end=end, text=source))
    return primary, secondary


def footer_disclaimer(content: dict) -> str:
    # Machine-checked content carries its own disclosure, which must stay visible.
    disclosure = (content.get("disclosure") or {}).get("text")
    if content.get("status") == "machine_checked" and not (isinstance(disclosure, str) and disclosure.strip()):
        raise SystemExit("Machine-checked content has no disclosure text; refusing to render it unlabeled.")
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
    parser.add_argument("--english-reference", type=Path,
                        help="Local english-reference JSON; with --page-id it is downloaded when cues lack English.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--out", type=Path, help="Output PDF path (default <pageId>-zh-Hans.pdf).")
    parser.add_argument("--no-english", action="store_true", help="Omit the English source under each paragraph.")
    parser.add_argument("--hide-timecodes", action="store_true")
    parser.add_argument("--font-path", type=Path, help="Optional CJK TTF/TTC/OTF font to embed.")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
