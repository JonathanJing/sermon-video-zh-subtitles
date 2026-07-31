#!/usr/bin/env python3
"""Render a mobile-friendly sermon transcript PDF from an SRT file."""

from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.pdfdoc import PDFString
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


SRT_TIMESTAMP_RE = re.compile(
    r"^\s*(?P<start>\d{1,2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(?P<end>\d{1,2}:\d{2}:\d{2}[,.]\d{3})"
)
MOBILE_PAGE_SIZE = (390, 844)
FONT_FALLBACK_CID = "STSong-Light"
FONT_EMBEDDED = "MobileCJK"
DEFAULT_DISCLAIMER = "AI 辅助生成的中文字幕，仅供个人学习和会后回顾；请以 Mariners Church 官方信息及原始英文讲道为准。"
COMPACT_DISCLAIMER = "AI 辅助翻译 · 仅供学习回顾 · 以 Mariners Church 官方英文为准"
TITLE_FONT_SIZE = 16.2
RUNNING_HEADER_FONT_SIZE = 8.8
HEADER_META_FONT_SIZE = 8.4
SUBTITLE_FONT_SIZE = 9.8
BODY_FONT_SIZE = 15.5
SECONDARY_FONT_SIZE = 10.5
TIME_FONT_SIZE = 8.0
FOOTER_FONT_SIZE = 7.2
LINE_GAP = 4.2
SECONDARY_LINE_GAP = 3.0
SECONDARY_GAP = 5.0
CUE_GAP = 13
TIME_LABEL_HEIGHT = 13
TIME_LABEL_BOTTOM_GAP = 10
SECONDARY_INDENT = 8
MARGIN_X = 24
MARGIN_TOP = 30
MARGIN_BOTTOM_WITH_DISCLAIMER = 58
MARGIN_BOTTOM_WITHOUT_DISCLAIMER = 32
KINSOKU_NO_LINE_START = frozenset("，。！？；：、）》】〉』”’…—％‰℃")
KINSOKU_NO_LINE_END = frozenset("（《【〈『“‘")
NO_BREAK_TERMS = tuple(
    sorted(
        {
            "Mariners Church",
            "Christine Caine",
            "Chris Hemsworth",
            "Jane Foster",
            "Natalie Portman",
            "Elizabeth Cady Stanton",
            "克里斯·海姆斯沃斯",
            "简·福斯特",
            "娜塔莉·波特曼",
            "伊丽莎白·凯迪·斯坦顿",
            "西罗非哈",
            "以利亚撒",
            "哥林多后书",
            "希伯来书",
            "民数记",
            "玛拿西",
            "玛吉",
            "玛拉",
            "挪阿",
            "曷拉",
            "密迦",
            "得撒",
        },
        key=len,
        reverse=True,
    )
)


@dataclass(frozen=True)
class Cue:
    start: str
    end: str
    text: str


@dataclass(frozen=True)
class ReadingBlock:
    start: str
    end: str
    primary: str
    secondary: str = ""


@dataclass(frozen=True)
class RenderBlock:
    start: str
    end: str
    primary_lines: tuple[str, ...]
    secondary_lines: tuple[str, ...]
    height: float
    bottom_gap: float
    continued: bool = False


def main() -> int:
    args = parse_args()
    cues = parse_srt(args.input.read_text(encoding="utf-8-sig"))
    if not cues:
        raise SystemExit("No SRT cues found.")
    secondary_cues = parse_srt(args.secondary_input.read_text(encoding="utf-8-sig")) if args.secondary_input else None
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.layout == "reading":
        qa = render_reading_pdf(
            cues,
            secondary_cues=secondary_cues,
            out=args.out,
            title=args.title or args.input.stem,
            subtitle=args.subtitle,
            sermon_date=args.sermon_date,
            speaker=args.speaker,
            sermon_window=args.sermon_window,
            font_path=args.font_path,
            include_timecodes=not args.hide_timecodes,
            disclaimer=None if args.hide_disclaimer else args.disclaimer,
            source_url=args.source_url,
            source_offset_seconds=args.source_offset_seconds,
            max_gap_seconds=args.reading_max_gap_seconds,
            max_block_seconds=args.reading_max_block_seconds,
            max_primary_chars=args.reading_max_primary_chars,
            max_secondary_chars=args.reading_max_secondary_chars,
            preferred_block_seconds=args.reading_preferred_block_seconds,
            preferred_primary_chars=args.reading_preferred_primary_chars,
            preferred_secondary_chars=args.reading_preferred_secondary_chars,
        )
    else:
        qa = render_mobile_pdf(
            cues,
            secondary_cues=secondary_cues,
            out=args.out,
            title=args.title or args.input.stem,
            subtitle=args.subtitle,
            sermon_date=args.sermon_date,
            speaker=args.speaker,
            sermon_window=args.sermon_window,
            font_path=args.font_path,
            include_timecodes=not args.hide_timecodes,
            disclaimer=None if args.hide_disclaimer else args.disclaimer,
            source_url=args.source_url,
            source_offset_seconds=args.source_offset_seconds,
        )
    qa = add_content_qa(
        qa,
        cues,
        secondary_cues or [],
        required_terms=args.required_term,
        required_scriptures=args.required_scripture,
    )
    qa_path = args.out.with_suffix(".qa.json")
    qa_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "ok",
                "cueCount": len(cues),
                "secondaryCueCount": len(secondary_cues) if secondary_cues is not None else 0,
                "layout": args.layout,
                "out": str(args.out),
                "pageSize": "mobile-390x844pt",
                "source": str(args.input),
                "secondarySource": str(args.secondary_input) if args.secondary_input else None,
                "sourceOffsetSeconds": args.source_offset_seconds,
                "qa": str(qa_path),
                "qaStatus": qa["status"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def add_content_qa(
    qa: dict,
    primary_cues: Sequence[Cue],
    secondary_cues: Sequence[Cue],
    *,
    required_terms: Sequence[str],
    required_scriptures: Sequence[str],
) -> dict:
    primary = " ".join(cue.text for cue in primary_cues)
    secondary = " ".join(cue.text for cue in secondary_cues)
    all_text = f"{primary} {secondary}"
    missing_terms = [term for term in required_terms if term not in all_text]
    missing_scriptures = [term for term in required_scriptures if term not in all_text]
    contextual_name_errors = []
    aligned_secondary = align_secondary_cues(list(primary_cues), list(secondary_cues))
    for index, cue in enumerate(primary_cues):
        start = max(0, index - 2)
        end = min(len(primary_cues), index + 3)
        context = " ".join(aligned_secondary[start:end]).lower()
        daughters_context = any(term in context for term in ("zelophehad", "daughters", "mahlah", "hoglah"))
        faith_context = any(term in context for term in ("hebrews 11", "ark", "flood", "abraham", "moses"))
        if faith_context and not daughters_context and "挪阿" in cue.text:
            contextual_name_errors.append(f"cue {index + 1}: Noah in Hebrews/Genesis context must be 挪亚")
        if daughters_context and not faith_context and "挪亚" in cue.text:
            contextual_name_errors.append(f"cue {index + 1}: Noah, daughter of Zelophehad, must be 挪阿")
    content_failures = []
    if missing_terms:
        content_failures.append("missing_required_terms")
    if missing_scriptures:
        content_failures.append("missing_required_scriptures")
    if contextual_name_errors:
        content_failures.append("contextual_name_errors")
    qa["contentChecks"] = {
        "requiredTerms": list(required_terms),
        "requiredScriptures": list(required_scriptures),
        "missingTerms": missing_terms,
        "missingScriptures": missing_scriptures,
        "contextualNameErrors": contextual_name_errors,
    }
    qa["failures"] = [*qa.get("failures", []), *content_failures]
    qa["status"] = "pass" if not qa["failures"] else "needs_review"
    return qa


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Input SRT file.")
    parser.add_argument("--secondary-input", type=Path, help="Optional secondary SRT rendered under each cue.")
    parser.add_argument("--out", type=Path, required=True, help="Output PDF path.")
    parser.add_argument("--title", help="PDF title.")
    parser.add_argument("--subtitle", help="Optional subtitle shown under the title.")
    parser.add_argument("--sermon-date", help="Service or sermon date shown in the page header.")
    parser.add_argument("--speaker", help="Confirmed sermon speaker shown when available.")
    parser.add_argument("--sermon-window", help="Optional confirmed sermon time range in the source video.")
    parser.add_argument(
        "--layout",
        choices=("cue", "reading"),
        default="cue",
        help="Use cue for subtitle-like output or reading for merged reading paragraphs.",
    )
    parser.add_argument("--reading-max-gap-seconds", type=float, default=2.0)
    parser.add_argument("--reading-max-block-seconds", type=float, default=55.0)
    parser.add_argument("--reading-max-primary-chars", type=int, default=320)
    parser.add_argument("--reading-max-secondary-chars", type=int, default=1400)
    parser.add_argument("--reading-preferred-block-seconds", type=float, default=32.0)
    parser.add_argument("--reading-preferred-primary-chars", type=int, default=180)
    parser.add_argument("--reading-preferred-secondary-chars", type=int, default=850)
    parser.add_argument("--font-path", type=Path, help="Optional CJK TTF/TTC/OTF font to embed.")
    parser.add_argument("--source-url", help="Optional video URL used to make time labels clickable.")
    parser.add_argument(
        "--source-offset-seconds",
        type=float,
        default=0.0,
        help="Seconds to add when PDF timecodes are relative to a clip inside the source video.",
    )
    parser.add_argument("--hide-timecodes", action="store_true", help="Hide cue timecodes in the PDF body.")
    parser.add_argument(
        "--disclaimer",
        default=DEFAULT_DISCLAIMER,
        help="Footer disclaimer shown on every page.",
    )
    parser.add_argument("--hide-disclaimer", action="store_true", help="Hide the footer disclaimer.")
    parser.add_argument("--required-term", action="append", default=[], help="Name or term that must appear in the PDF source text.")
    parser.add_argument("--required-scripture", action="append", default=[], help="Scripture reference that must appear in the PDF source text.")
    return parser.parse_args()


def parse_srt(text: str) -> list[Cue]:
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n").strip())
    cues: list[Cue] = []
    for block in blocks:
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        timestamp_index = next((index for index, line in enumerate(lines) if SRT_TIMESTAMP_RE.match(line)), -1)
        if timestamp_index < 0:
            continue
        match = SRT_TIMESTAMP_RE.match(lines[timestamp_index])
        if not match:
            continue
        body = clean_caption_text(" ".join(lines[timestamp_index + 1 :]))
        if body:
            cues.append(Cue(start=match.group("start"), end=match.group("end"), text=body))
    return cues


def clean_caption_text(text: str) -> str:
    text = re.sub(r"</?[^>]+>", "", text)
    text = re.sub(r"\{\\[^}]+\}", "", text)
    return normalize_cjk_punctuation_spacing(re.sub(r"\s+", " ", text).strip())


def normalize_cjk_punctuation_spacing(text: str) -> str:
    """Remove spacing artifacts around Chinese punctuation without changing English prose."""
    text = re.sub(r"(?<=[\u3400-\u9fff\uf900-\ufaff])\s+(?=[\u3400-\u9fff\uf900-\ufaff])", "", text)
    text = re.sub(r"\s+([，。！？；：、）》】〉』”’％‰℃])", r"\1", text)
    text = re.sub(r"([（《【〈『“‘])\s+", r"\1", text)
    text = re.sub(r"([，。！？；：、）》】〉』”’])\s+(?=[\u3400-\u9fff\uf900-\ufaff])", r"\1", text)
    text = re.sub(r"(?<=[\u3400-\u9fff\uf900-\ufaff])\s+(?=[（《【〈『“‘])", "", text)
    return text.strip()


def align_secondary_cues(primary_cues: list[Cue], secondary_cues: list[Cue]) -> list[str]:
    if not secondary_cues:
        return ["" for _ in primary_cues]
    aligned: list[str] = []
    secondary_ranges = [(timestamp_to_seconds(cue.start), timestamp_to_seconds(cue.end), cue) for cue in secondary_cues]
    for primary in primary_cues:
        primary_start = timestamp_to_seconds(primary.start)
        primary_end = timestamp_to_seconds(primary.end)
        primary_mid = (primary_start + primary_end) / 2
        matches = [
            cue
            for secondary_start, secondary_end, cue in secondary_ranges
            if overlap_seconds(primary_start, primary_end, secondary_start, secondary_end) > 0.01
        ]
        if not matches:
            nearest = min(
                secondary_ranges,
                key=lambda item: abs(((item[0] + item[1]) / 2) - primary_mid),
            )
            if abs(((nearest[0] + nearest[1]) / 2) - primary_mid) <= 1.0:
                matches = [nearest[2]]
        aligned.append(join_unique_text(cue.text for cue in matches))
    return aligned


def timestamp_to_seconds(value: str) -> float:
    time_part, milliseconds = value.replace(",", ".").split(".", 1)
    hours, minutes, seconds = [int(part) for part in time_part.split(":")]
    return hours * 3600 + minutes * 60 + seconds + int(milliseconds[:3].ljust(3, "0")) / 1000


def overlap_seconds(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def join_unique_text(values) -> str:
    seen: set[str] = set()
    parts: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            parts.append(text)
    return " ".join(parts)


def build_reading_blocks(
    primary_cues: list[Cue],
    secondary_cues: list[Cue] | None = None,
    *,
    max_gap_seconds: float = 2.0,
    max_block_seconds: float = 55.0,
    max_primary_chars: int = 320,
    max_secondary_chars: int = 1400,
    preferred_block_seconds: float = 32.0,
    preferred_primary_chars: int = 180,
    preferred_secondary_chars: int = 850,
) -> list[ReadingBlock]:
    secondary_by_index = align_secondary_cues(primary_cues, secondary_cues or [])
    blocks: list[ReadingBlock] = []
    current_primary: list[str] = []
    current_secondary: list[str] = []
    current_start = ""
    current_end = ""
    current_start_seconds = 0.0
    current_end_seconds = 0.0

    def flush() -> None:
        nonlocal current_primary, current_secondary, current_start, current_end, current_start_seconds, current_end_seconds
        if current_primary:
            blocks.append(
                ReadingBlock(
                    start=current_start,
                    end=current_end,
                    primary=join_primary_text(current_primary),
                    secondary=join_secondary_text(current_secondary),
                )
            )
        current_primary = []
        current_secondary = []
        current_start = ""
        current_end = ""
        current_start_seconds = 0.0
        current_end_seconds = 0.0

    for index, cue in enumerate(primary_cues):
        cue_start = timestamp_to_seconds(cue.start)
        cue_end = timestamp_to_seconds(cue.end)
        secondary_text = secondary_by_index[index]
        if not current_primary:
            current_primary = [cue.text]
            current_secondary = [secondary_text] if secondary_text else []
            current_start = cue.start
            current_end = cue.end
            current_start_seconds = cue_start
            current_end_seconds = cue_end
            continue

        gap = cue_start - current_end_seconds
        current_primary_text = join_primary_text(current_primary)
        current_secondary_text = join_secondary_text(current_secondary)
        merged_primary = join_primary_text([*current_primary, cue.text])
        merged_secondary = join_secondary_text([*current_secondary, secondary_text] if secondary_text else current_secondary)
        current_duration = current_end_seconds - current_start_seconds
        next_duration = cue_end - current_start_seconds
        current_sentence_complete = is_sentence_end(current_primary_text)
        paragraph_ready = (
            current_duration >= preferred_block_seconds
            or len(current_primary_text) >= preferred_primary_chars
            or len(current_secondary_text) >= preferred_secondary_chars
        )
        next_would_exceed_block = (
            next_duration > max_block_seconds
            or len(merged_primary) > max_primary_chars
            or len(merged_secondary) > max_secondary_chars
        )
        hard_overflow = (
            next_duration > max_block_seconds * 1.25
            or len(merged_primary) > int(max_primary_chars * 1.25)
            or len(merged_secondary) > int(max_secondary_chars * 1.25)
        )
        should_break = (
            gap > max_gap_seconds
            or (current_sentence_complete and (paragraph_ready or next_would_exceed_block))
            or (not current_sentence_complete and hard_overflow)
        )
        if should_break:
            flush()
            current_primary = [cue.text]
            current_secondary = [secondary_text] if secondary_text else []
            current_start = cue.start
            current_end = cue.end
            current_start_seconds = cue_start
            current_end_seconds = cue_end
        else:
            current_primary.append(cue.text)
            if secondary_text:
                current_secondary.append(secondary_text)
            current_end = cue.end
            current_end_seconds = cue_end
    flush()
    return blocks


def join_primary_text(parts: list[str]) -> str:
    text = ""
    for part in parts:
        clean = part.strip()
        if not clean:
            continue
        if not text:
            text = clean
            continue
        if needs_ascii_space(text[-1], clean[0]):
            text += " " + clean
        else:
            text += clean
    return text


def join_secondary_text(parts: list[str]) -> str:
    return re.sub(r"\s+", " ", " ".join(part.strip() for part in parts if part.strip())).strip()


def needs_ascii_space(left: str, right: str) -> bool:
    return left.isascii() and right.isascii() and (left.isalnum() or left in "'\"") and (right.isalnum() or right in "'\"")


def is_sentence_end(text: str) -> bool:
    return bool(re.search(r"[。！？.!?][\"'”’）)]?$", text.strip()))


def render_mobile_pdf(
    cues: list[Cue],
    *,
    secondary_cues: list[Cue] | None = None,
    out: Path,
    title: str,
    subtitle: str | None = None,
    sermon_date: str | None = None,
    speaker: str | None = None,
    sermon_window: str | None = None,
    font_path: Path | None = None,
    include_timecodes: bool = True,
    disclaimer: str | None = DEFAULT_DISCLAIMER,
    source_url: str | None = None,
    source_offset_seconds: float = 0.0,
) -> dict:
    font_name = register_cjk_font(font_path)
    body_width = MOBILE_PAGE_SIZE[0] - MARGIN_X * 2
    secondary_by_index = align_secondary_cues(cues, secondary_cues or [])
    blocks: list[RenderBlock] = []
    for index, cue in enumerate(cues):
        blocks.append(
            make_render_block(
                start=cue.start,
                end=cue.end,
                primary=cue.text,
                secondary=secondary_by_index[index],
                font_name=font_name,
                body_width=body_width,
                include_timecodes=include_timecodes,
            )
        )
    return render_paginated_pdf(
        blocks,
        out=out,
        title=title,
        subtitle=subtitle,
        sermon_date=sermon_date,
        speaker=speaker,
        sermon_window=sermon_window,
        font_name=font_name,
        include_timecodes=include_timecodes,
        disclaimer=disclaimer,
        source_url=source_url,
        source_offset_seconds=source_offset_seconds,
    )


def render_reading_pdf(
    cues: list[Cue],
    *,
    secondary_cues: list[Cue] | None = None,
    out: Path,
    title: str,
    subtitle: str | None = None,
    sermon_date: str | None = None,
    speaker: str | None = None,
    sermon_window: str | None = None,
    font_path: Path | None = None,
    include_timecodes: bool = True,
    disclaimer: str | None = DEFAULT_DISCLAIMER,
    source_url: str | None = None,
    source_offset_seconds: float = 0.0,
    max_gap_seconds: float = 2.0,
    max_block_seconds: float = 55.0,
    max_primary_chars: int = 320,
    max_secondary_chars: int = 1400,
    preferred_block_seconds: float = 32.0,
    preferred_primary_chars: int = 180,
    preferred_secondary_chars: int = 850,
) -> dict:
    blocks = build_reading_blocks(
        cues,
        secondary_cues,
        max_gap_seconds=max_gap_seconds,
        max_block_seconds=max_block_seconds,
        max_primary_chars=max_primary_chars,
        max_secondary_chars=max_secondary_chars,
        preferred_block_seconds=preferred_block_seconds,
        preferred_primary_chars=preferred_primary_chars,
        preferred_secondary_chars=preferred_secondary_chars,
    )
    font_name = register_cjk_font(font_path)
    body_width = MOBILE_PAGE_SIZE[0] - MARGIN_X * 2
    secondary_width = body_width - SECONDARY_INDENT
    render_blocks: list[RenderBlock] = []
    for block in blocks:
        render_blocks.append(
            make_render_block(
                start=block.start,
                end=block.end,
                primary=block.primary,
                secondary=block.secondary,
                font_name=font_name,
                body_width=body_width,
                secondary_width=secondary_width,
                include_timecodes=include_timecodes,
                extra_gap=4,
            )
        )
    return render_paginated_pdf(
        render_blocks,
        out=out,
        title=title,
        subtitle=subtitle,
        sermon_date=sermon_date,
        speaker=speaker,
        sermon_window=sermon_window,
        font_name=font_name,
        include_timecodes=include_timecodes,
        disclaimer=disclaimer,
        source_url=source_url,
        source_offset_seconds=source_offset_seconds,
    )


def make_render_block(
    *,
    start: str,
    end: str,
    primary: str,
    secondary: str,
    font_name: str,
    body_width: float,
    include_timecodes: bool,
    secondary_width: float | None = None,
    extra_gap: float = 0,
) -> RenderBlock:
    primary_lines = tuple(wrap_text(primary, font_name, BODY_FONT_SIZE, body_width))
    secondary_lines = tuple(
        wrap_text(secondary, font_name, SECONDARY_FONT_SIZE, secondary_width or body_width - SECONDARY_INDENT)
        if secondary
        else []
    )
    height = len(primary_lines) * (BODY_FONT_SIZE + LINE_GAP) + CUE_GAP + extra_gap
    if secondary_lines:
        height += SECONDARY_GAP + len(secondary_lines) * (SECONDARY_FONT_SIZE + SECONDARY_LINE_GAP)
    if include_timecodes:
        height += TIME_LABEL_HEIGHT + TIME_LABEL_BOTTOM_GAP
    return RenderBlock(
        start=start,
        end=end,
        primary_lines=primary_lines,
        secondary_lines=secondary_lines,
        height=height,
        bottom_gap=CUE_GAP + extra_gap,
    )


def render_paginated_pdf(
    blocks: Sequence[RenderBlock],
    *,
    out: Path,
    title: str,
    subtitle: str | None,
    sermon_date: str | None,
    speaker: str | None,
    sermon_window: str | None,
    font_name: str,
    include_timecodes: bool,
    disclaimer: str | None,
    source_url: str | None,
    source_offset_seconds: float,
) -> dict:
    page_width, page_height = MOBILE_PAGE_SIZE
    margin_bottom = MARGIN_BOTTOM_WITH_DISCLAIMER if disclaimer else MARGIN_BOTTOM_WITHOUT_DISCLAIMER
    first_y = header_body_start_y(
        title=title,
        subtitle=subtitle,
        sermon_date=sermon_date,
        speaker=speaker,
        sermon_window=sermon_window,
        page_width=page_width,
        y=page_height - MARGIN_TOP,
        font_name=font_name,
        first_page=True,
    )
    regular_y = header_body_start_y(
        title=title,
        subtitle=subtitle,
        sermon_date=sermon_date,
        speaker=speaker,
        sermon_window=sermon_window,
        page_width=page_width,
        y=page_height - MARGIN_TOP,
        font_name=font_name,
        first_page=False,
    )
    first_capacity = first_y - margin_bottom
    regular_capacity = regular_y - margin_bottom
    fitted_blocks = fit_render_blocks_to_capacity(
        blocks,
        first_capacity=first_capacity,
        regular_capacity=regular_capacity,
        include_timecodes=include_timecodes,
    )
    pages = balance_render_pages(
        fitted_blocks,
        first_capacity=first_capacity,
        regular_capacity=regular_capacity,
    )
    doc = canvas.Canvas(str(out), pagesize=MOBILE_PAGE_SIZE, pageCompression=1)
    doc.setTitle(title)
    doc.setAuthor(speaker or "sermon-video-zh-subtitles")
    doc.setCreator("sermon-video-zh-subtitles")
    doc.setSubject("Mobile Chinese-English sermon reading edition")
    doc._doc.Catalog.Lang = PDFString("zh-CN")

    last_outline_bucket = -1
    page_count = len(pages)
    for page_index, page_blocks in enumerate(pages):
        if page_index:
            doc.showPage()
        page_number = page_index + 1
        first_page = page_number == 1
        y = draw_header(
            doc,
            title=title,
            subtitle=subtitle,
            sermon_date=sermon_date,
            speaker=speaker,
            sermon_window=sermon_window,
            page_width=page_width,
            y=page_height - MARGIN_TOP,
            font_name=font_name,
            first_page=first_page,
        )
        if first_page:
            doc.bookmarkPage("sermon-start")
            doc.addOutlineEntry("讲道开始", "sermon-start", level=0, closed=False)
        for block in page_blocks:
            start_seconds = timestamp_to_seconds(block.start)
            outline_bucket = int(start_seconds // 300)
            if outline_bucket > 0 and outline_bucket > last_outline_bucket:
                key = f"minute-{outline_bucket * 5}"
                doc.bookmarkPage(key)
                doc.addOutlineEntry(f"{outline_bucket * 5:02d}:00", key, level=0, closed=False)
                last_outline_bucket = outline_bucket
            y = draw_render_block(
                doc,
                block=block,
                y=y,
                font_name=font_name,
                include_timecodes=include_timecodes,
                source_url=source_url,
                source_offset_seconds=source_offset_seconds,
            )
        footer_disclaimer = disclaimer
        if disclaimer == DEFAULT_DISCLAIMER and page_number not in {1, page_count}:
            footer_disclaimer = COMPACT_DISCLAIMER
        draw_footer(
            doc,
            page_width=page_width,
            page_number=page_number,
            font_name=font_name,
            margin_x=MARGIN_X,
            disclaimer=footer_disclaimer,
        )
    doc.save()
    return build_layout_qa(
        pages,
        first_capacity=first_capacity,
        regular_capacity=regular_capacity,
        font_name=font_name,
    )


def build_layout_qa(
    pages: Sequence[Sequence[RenderBlock]],
    *,
    first_capacity: float,
    regular_capacity: float,
    font_name: str,
) -> dict:
    """Record deterministic checks for every rendered page."""
    page_checks = []
    risk_pages: set[int] = set()
    missing_markers = []
    long_lines = []
    for page_index, blocks in enumerate(pages):
        page_number = page_index + 1
        capacity = first_capacity if page_index == 0 else regular_capacity
        used = sum(block.height for block in blocks)
        blank = not blocks
        overflow = used > capacity + 0.01
        sparse_orphan = page_index > 0 and len(blocks) == 1 and used < capacity * 0.25
        continued_count = sum(1 for block in blocks if block.continued)
        for block in blocks:
            for line in (*block.primary_lines, *block.secondary_lines):
                if "\ufffd" in line or "□" in line:
                    missing_markers.append({"page": page_number, "text": line[:120]})
                cjk_count = len(re.findall(r"[\u3400-\u9fff\uf900-\ufaff]", line))
                if cjk_count > 32 or (cjk_count == 0 and len(line) > 100):
                    long_lines.append({"page": page_number, "text": line[:120]})
        if blank or overflow or sparse_orphan or missing_markers and missing_markers[-1]["page"] == page_number:
            risk_pages.add(page_number)
        page_checks.append(
            {
                "page": page_number,
                "blockCount": len(blocks),
                "usedPoints": round(used, 2),
                "capacityPoints": round(capacity, 2),
                "blank": blank,
                "overflow": overflow,
                "sparseOrphanRisk": sparse_orphan,
                "continuedBlockCount": continued_count,
            }
        )
    failures = [
        issue
        for issue, present in (
            ("blank_pages", any(page["blank"] for page in page_checks)),
            ("layout_overflow", any(page["overflow"] for page in page_checks)),
            ("missing_glyph_markers", bool(missing_markers)),
            ("overlong_rendered_lines", bool(long_lines)),
        )
        if present
    ]
    return {
        "schemaVersion": 1,
        "status": "pass" if not failures else "needs_review",
        "allPagesChecked": True,
        "pageCount": len(pages),
        "font": font_name,
        "failures": failures,
        "riskPages": sorted(risk_pages),
        "missingGlyphMarkers": missing_markers,
        "longRenderedLines": long_lines,
        "pages": page_checks,
    }


def draw_render_block(
    doc: canvas.Canvas,
    *,
    block: RenderBlock,
    y: float,
    font_name: str,
    include_timecodes: bool,
    source_url: str | None,
    source_offset_seconds: float,
) -> float:
    if include_timecodes:
        time_line = f"{display_time(block.start)} - {display_time(block.end)}"
        if block.continued:
            time_line += " · 续"
        draw_time_label(
            doc,
            x=MARGIN_X,
            y=y,
            text=time_line,
            font_name=font_name,
            link_url=(
                video_url_at_time(source_url, timestamp_to_seconds(block.start) + source_offset_seconds)
                if source_url
                else None
            ),
        )
        y -= TIME_LABEL_HEIGHT + TIME_LABEL_BOTTOM_GAP
    doc.setFillColor(colors.HexColor("#111827"))
    doc.setFont(font_name, BODY_FONT_SIZE)
    for line in block.primary_lines:
        doc.drawString(MARGIN_X, y, line)
        y -= BODY_FONT_SIZE + LINE_GAP
    if block.secondary_lines:
        y -= SECONDARY_GAP
        secondary_top = y + 2
        secondary_bottom = y - len(block.secondary_lines) * (SECONDARY_FONT_SIZE + SECONDARY_LINE_GAP) + 2
        doc.setStrokeColor(colors.HexColor("#cbd5e1"))
        doc.setLineWidth(0.8)
        doc.line(MARGIN_X + 1, secondary_top, MARGIN_X + 1, secondary_bottom)
        doc.setFillColor(colors.HexColor("#475569"))
        doc.setFont(font_name, SECONDARY_FONT_SIZE)
        for line in block.secondary_lines:
            doc.drawString(MARGIN_X + SECONDARY_INDENT, y, line)
            y -= SECONDARY_FONT_SIZE + SECONDARY_LINE_GAP
    y -= block.bottom_gap
    return y


def fit_render_blocks_to_capacity(
    blocks: Sequence[RenderBlock],
    *,
    first_capacity: float,
    regular_capacity: float,
    include_timecodes: bool,
) -> list[RenderBlock]:
    fitted: list[RenderBlock] = []
    for index, block in enumerate(blocks):
        capacity = first_capacity if index == 0 else regular_capacity
        fitted.extend(split_render_block(block, max_height=capacity, include_timecodes=include_timecodes))
    return fitted


def split_render_block(block: RenderBlock, *, max_height: float, include_timecodes: bool) -> list[RenderBlock]:
    if block.height <= max_height + 0.01:
        return [block]
    primary = list(block.primary_lines)
    secondary = list(block.secondary_lines)
    chunks: list[RenderBlock] = []
    first_chunk = True
    time_height = TIME_LABEL_HEIGHT + TIME_LABEL_BOTTOM_GAP if include_timecodes else 0
    while primary or secondary:
        budget = max_height - time_height - block.bottom_gap
        primary_chunk: list[str] = []
        secondary_chunk: list[str] = []
        while primary and budget >= BODY_FONT_SIZE + LINE_GAP:
            primary_chunk.append(primary.pop(0))
            budget -= BODY_FONT_SIZE + LINE_GAP
        if not primary and secondary and budget >= SECONDARY_GAP + SECONDARY_FONT_SIZE + SECONDARY_LINE_GAP:
            budget -= SECONDARY_GAP
            while secondary and budget >= SECONDARY_FONT_SIZE + SECONDARY_LINE_GAP:
                secondary_chunk.append(secondary.pop(0))
                budget -= SECONDARY_FONT_SIZE + SECONDARY_LINE_GAP
        if not primary_chunk and not secondary_chunk:
            raise ValueError(f"A rendered line cannot fit within the PDF page capacity: {max_height:.1f}pt")
        height = time_height + block.bottom_gap
        height += len(primary_chunk) * (BODY_FONT_SIZE + LINE_GAP)
        if secondary_chunk:
            height += SECONDARY_GAP + len(secondary_chunk) * (SECONDARY_FONT_SIZE + SECONDARY_LINE_GAP)
        chunks.append(
            RenderBlock(
                start=block.start,
                end=block.end,
                primary_lines=tuple(primary_chunk),
                secondary_lines=tuple(secondary_chunk),
                height=height,
                bottom_gap=block.bottom_gap,
                continued=block.continued or not first_chunk,
            )
        )
        first_chunk = False
    return chunks


def balance_render_pages(
    blocks: Sequence[RenderBlock],
    *,
    first_capacity: float,
    regular_capacity: float,
) -> list[list[RenderBlock]]:
    """Partition consecutive blocks with look-ahead so the last pages stay balanced."""
    if not blocks:
        return [[]]
    heights = [block.height for block in blocks]
    page_count = greedy_page_count(heights, first_capacity=first_capacity, regular_capacity=regular_capacity)
    capacities = [first_capacity, *([regular_capacity] * (page_count - 1))]
    prefix = [0.0]
    for height in heights:
        prefix.append(prefix[-1] + height)

    infinity = float("inf")
    costs = [[infinity] * (len(blocks) + 1) for _ in range(page_count + 1)]
    previous = [[-1] * (len(blocks) + 1) for _ in range(page_count + 1)]
    costs[0][0] = 0.0
    for page_number in range(1, page_count + 1):
        capacity = capacities[page_number - 1]
        min_end = page_number
        max_end = len(blocks) - (page_count - page_number)
        for end in range(min_end, max_end + 1):
            for start in range(page_number - 1, end):
                if costs[page_number - 1][start] == infinity:
                    continue
                used = prefix[end] - prefix[start]
                if used > capacity + 0.01:
                    continue
                unused_ratio = (capacity - used) / capacity
                cost = costs[page_number - 1][start] + unused_ratio * unused_ratio
                if cost < costs[page_number][end]:
                    costs[page_number][end] = cost
                    previous[page_number][end] = start

    if costs[page_count][len(blocks)] == infinity:
        return greedy_render_pages(blocks, first_capacity=first_capacity, regular_capacity=regular_capacity)
    boundaries = [len(blocks)]
    end = len(blocks)
    for page_number in range(page_count, 0, -1):
        end = previous[page_number][end]
        boundaries.append(end)
    boundaries.reverse()
    return [list(blocks[boundaries[index] : boundaries[index + 1]]) for index in range(page_count)]


def greedy_page_count(heights: Sequence[float], *, first_capacity: float, regular_capacity: float) -> int:
    page_count = 1
    used = 0.0
    capacity = first_capacity
    for height in heights:
        if used and used + height > capacity + 0.01:
            page_count += 1
            capacity = regular_capacity
            used = 0.0
        used += height
    return page_count


def greedy_render_pages(
    blocks: Sequence[RenderBlock],
    *,
    first_capacity: float,
    regular_capacity: float,
) -> list[list[RenderBlock]]:
    pages: list[list[RenderBlock]] = [[]]
    used = 0.0
    capacity = first_capacity
    for block in blocks:
        if pages[-1] and used + block.height > capacity + 0.01:
            pages.append([])
            capacity = regular_capacity
            used = 0.0
        pages[-1].append(block)
        used += block.height
    return pages


def register_cjk_font(font_path: Path | None = None) -> str:
    for path in candidate_font_paths(font_path):
        if not path.is_file():
            continue
        try:
            pdfmetrics.registerFont(TTFont(FONT_EMBEDDED, str(path), subfontIndex=0))
            return FONT_EMBEDDED
        except Exception:
            continue
    pdfmetrics.registerFont(UnicodeCIDFont(FONT_FALLBACK_CID))
    return FONT_FALLBACK_CID


def candidate_font_paths(font_path: Path | None) -> list[Path]:
    candidates: list[Path] = []
    if font_path:
        candidates.append(font_path)
    env_path = os.environ.get("SERMON_MOBILE_PDF_FONT")
    if env_path:
        candidates.append(Path(env_path))
    candidates.extend(
        [
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
            Path("/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf"),
            Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
            Path("/System/Library/Fonts/PingFang.ttc"),
            Path("/System/Library/Fonts/STHeiti Medium.ttc"),
        ]
    )
    return candidates


def draw_header(
    canvas_obj: canvas.Canvas,
    *,
    title: str,
    subtitle: str | None,
    sermon_date: str | None,
    speaker: str | None,
    sermon_window: str | None,
    page_width: int,
    y: int,
    font_name: str,
    first_page: bool,
) -> float:
    start_y = y
    header_meta = format_header_metadata(
        sermon_date=sermon_date,
        speaker=speaker,
        sermon_window=sermon_window,
    )
    if not first_page:
        canvas_obj.setFillColor(colors.HexColor("#667085"))
        canvas_obj.setFont(font_name, RUNNING_HEADER_FONT_SIZE)
        running_title = short_running_title(title)
        meta_width = (
            min(page_width * 0.44, pdfmetrics.stringWidth(header_meta, font_name, HEADER_META_FONT_SIZE))
            if header_meta
            else 0
        )
        title_width = page_width - MARGIN_X * 2 - meta_width - (12 if header_meta else 0)
        for line in wrap_text(running_title, font_name, RUNNING_HEADER_FONT_SIZE, title_width)[:1]:
            canvas_obj.drawString(MARGIN_X, y, line)
        if header_meta:
            canvas_obj.setFont(font_name, HEADER_META_FONT_SIZE)
            canvas_obj.drawRightString(page_width - MARGIN_X, y, header_meta)
        canvas_obj.setStrokeColor(colors.HexColor("#e2e8f0"))
        canvas_obj.line(MARGIN_X, y - 10, page_width - MARGIN_X, y - 10)
        return header_body_start_y(
            title=title,
            subtitle=subtitle,
            sermon_date=sermon_date,
            speaker=speaker,
            sermon_window=sermon_window,
            page_width=page_width,
            y=start_y,
            font_name=font_name,
            first_page=False,
        )

    if header_meta:
        canvas_obj.setFillColor(colors.HexColor("#64748b"))
        canvas_obj.setFont(font_name, HEADER_META_FONT_SIZE)
        for line in wrap_text(header_meta, font_name, HEADER_META_FONT_SIZE, page_width - MARGIN_X * 2)[:2]:
            canvas_obj.drawString(MARGIN_X, y, line)
            y -= HEADER_META_FONT_SIZE + 3.5
        y -= 2
    canvas_obj.setFillColor(colors.HexColor("#111827"))
    canvas_obj.setFont(font_name, TITLE_FONT_SIZE)
    title_lines = wrap_text(title, font_name, TITLE_FONT_SIZE, page_width - MARGIN_X * 2)
    for line in title_lines[:2]:
        canvas_obj.drawString(MARGIN_X, y, line)
        y -= TITLE_FONT_SIZE + 5
    if subtitle:
        canvas_obj.setFillColor(colors.HexColor("#4b5563"))
        canvas_obj.setFont(font_name, SUBTITLE_FONT_SIZE)
        for line in wrap_text(subtitle, font_name, SUBTITLE_FONT_SIZE, page_width - MARGIN_X * 2)[:2]:
            canvas_obj.drawString(MARGIN_X, y, line)
            y -= SUBTITLE_FONT_SIZE + 4
    canvas_obj.setStrokeColor(colors.HexColor("#dbe2ea"))
    canvas_obj.line(MARGIN_X, y - 4, page_width - MARGIN_X, y - 4)
    return header_body_start_y(
        title=title,
        subtitle=subtitle,
        sermon_date=sermon_date,
        speaker=speaker,
        sermon_window=sermon_window,
        page_width=page_width,
        y=start_y,
        font_name=font_name,
        first_page=True,
    )


def header_body_start_y(
    *,
    title: str,
    subtitle: str | None,
    sermon_date: str | None,
    speaker: str | None,
    sermon_window: str | None,
    page_width: float,
    y: float,
    font_name: str,
    first_page: bool,
) -> float:
    if not first_page:
        return y - 26
    header_meta = format_header_metadata(
        sermon_date=sermon_date,
        speaker=speaker,
        sermon_window=sermon_window,
    )
    if header_meta:
        y -= len(wrap_text(header_meta, font_name, HEADER_META_FONT_SIZE, page_width - MARGIN_X * 2)[:2]) * (
            HEADER_META_FONT_SIZE + 3.5
        )
        y -= 2
    y -= len(wrap_text(title, font_name, TITLE_FONT_SIZE, page_width - MARGIN_X * 2)[:2]) * (TITLE_FONT_SIZE + 5)
    if subtitle:
        y -= len(wrap_text(subtitle, font_name, SUBTITLE_FONT_SIZE, page_width - MARGIN_X * 2)[:2]) * (
            SUBTITLE_FONT_SIZE + 4
        )
    return y - 18


def format_header_metadata(
    *,
    sermon_date: str | None,
    speaker: str | None,
    sermon_window: str | None,
) -> str:
    parts: list[str] = []
    if sermon_date and sermon_date.strip():
        parts.append(sermon_date.strip())
    if speaker and speaker.strip():
        parts.append(f"讲员：{speaker.strip()}")
    if sermon_window and sermon_window.strip():
        parts.append(f"证道时段：{sermon_window.strip()}")
    return " · ".join(parts)


def short_running_title(title: str) -> str:
    for separator in (" - ", " | "):
        head, found, _ = title.partition(separator)
        if found and head.strip():
            return head.strip()
    return title.strip()


def draw_footer(
    canvas_obj: canvas.Canvas,
    *,
    page_width: int,
    page_number: int,
    font_name: str,
    margin_x: int,
    disclaimer: str | None,
) -> None:
    canvas_obj.setFillColor(colors.HexColor("#667085"))
    canvas_obj.setFont(font_name, 8.5)
    canvas_obj.drawRightString(page_width - margin_x, 13, f"{page_number}")
    if not disclaimer:
        return
    canvas_obj.setFillColor(colors.HexColor("#667085"))
    canvas_obj.setFont(font_name, FOOTER_FONT_SIZE)
    footer_width = page_width - margin_x * 2
    footer_lines = wrap_text(disclaimer, font_name, FOOTER_FONT_SIZE, footer_width)[:2]
    y = 33 if len(footer_lines) > 1 else 27
    for line in footer_lines:
        canvas_obj.drawString(margin_x, y, line)
        y -= FOOTER_FONT_SIZE + 2.5


def draw_time_label(
    canvas_obj: canvas.Canvas,
    *,
    x: float,
    y: float,
    text: str,
    font_name: str,
    link_url: str | None = None,
) -> None:
    label_width = pdfmetrics.stringWidth(text, font_name, TIME_FONT_SIZE) + 12
    label_y = y - TIME_LABEL_HEIGHT + 2
    canvas_obj.setFillColor(colors.HexColor("#eaf2fb"))
    canvas_obj.roundRect(x, label_y, label_width, TIME_LABEL_HEIGHT, 4, stroke=0, fill=1)
    canvas_obj.setFillColor(colors.HexColor("#52657d"))
    canvas_obj.setFont(font_name, TIME_FONT_SIZE)
    canvas_obj.drawString(x + 6, label_y + 3.2, text)
    if link_url:
        canvas_obj.linkURL(link_url, (x, label_y, x + label_width, label_y + TIME_LABEL_HEIGHT), relative=0, thickness=0)


def video_url_at_time(source_url: str, seconds: float) -> str:
    parts = urlsplit(source_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["t"] = f"{max(0, int(seconds))}s"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def wrap_text(text: str, font_name: str, font_size: float, max_width: float) -> list[str]:
    lines: list[str] = []
    current = ""
    for token in text_tokens(normalize_cjk_punctuation_spacing(text)):
        candidate = current + token if current else token.lstrip()
        if current and pdfmetrics.stringWidth(candidate, font_name, font_size) > max_width:
            lines.append(current.rstrip())
            current = token.lstrip()
        else:
            current = candidate
    if current.strip():
        lines.append(current.rstrip())
    return enforce_kinsoku(lines) or [""]


def enforce_kinsoku(lines: list[str]) -> list[str]:
    """Prevent common Chinese closing punctuation from starting a rendered line."""
    lines = [line.strip() for line in lines if line.strip()]
    index = 1
    while index < len(lines):
        while lines[index] and lines[index][0] in KINSOKU_NO_LINE_START:
            lines[index - 1] += lines[index][0]
            lines[index] = lines[index][1:].lstrip()
        while lines[index - 1] and lines[index - 1][-1] in KINSOKU_NO_LINE_END:
            lines[index] = lines[index - 1][-1] + lines[index]
            lines[index - 1] = lines[index - 1][:-1].rstrip()
        if not lines[index]:
            lines.pop(index)
            continue
        index += 1
    return lines


def text_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    buffer = ""
    index = 0
    while index < len(text):
        protected = next((term for term in NO_BREAK_TERMS if text.startswith(term, index)), None)
        if protected:
            if buffer:
                tokens.append(buffer)
                buffer = ""
            tokens.append(protected)
            index += len(protected)
            continue
        char = text[index]
        if char.isspace():
            if buffer:
                tokens.append(buffer)
                buffer = ""
            tokens.append(" ")
        elif is_cjk(char):
            if buffer:
                tokens.append(buffer)
                buffer = ""
            tokens.append(char)
        else:
            buffer += char
        index += 1
    if buffer:
        tokens.append(buffer)
    return tokens


def is_cjk(char: str) -> bool:
    return "\u3400" <= char <= "\u9fff" or "\uf900" <= char <= "\ufaff"


def display_time(value: str) -> str:
    return value.replace(",", ".").rsplit(".", 1)[0]


if __name__ == "__main__":
    raise SystemExit(main())
