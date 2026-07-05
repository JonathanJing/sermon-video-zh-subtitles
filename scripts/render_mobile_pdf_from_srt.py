#!/usr/bin/env python3
"""Render a mobile-friendly sermon transcript PDF from an SRT file."""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


SRT_TIMESTAMP_RE = re.compile(
    r"^\s*(?P<start>\d{1,2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(?P<end>\d{1,2}:\d{2}:\d{2}[,.]\d{3})"
)
MOBILE_PAGE_SIZE = (390, 844)
FONT_FALLBACK_CID = "STSong-Light"
FONT_EMBEDDED = "MobileCJK"
DEFAULT_DISCLAIMER = "AI 辅助生成的中文字幕，仅供个人学习和会后回顾；请以 Mariners Church 官方信息及原始英文讲道为准。"
TITLE_FONT_SIZE = 15.5
RUNNING_HEADER_FONT_SIZE = 8
SUBTITLE_FONT_SIZE = 9
BODY_FONT_SIZE = 13.5
SECONDARY_FONT_SIZE = 8.6
TIME_FONT_SIZE = 7.2
FOOTER_FONT_SIZE = 6.2
LINE_GAP = 3.5
SECONDARY_LINE_GAP = 2.2
SECONDARY_GAP = 4.2
CUE_GAP = 11
TIME_LABEL_HEIGHT = 11.5
TIME_LABEL_BOTTOM_GAP = 11
SECONDARY_INDENT = 8


@dataclass(frozen=True)
class Cue:
    start: str
    end: str
    text: str


def main() -> int:
    args = parse_args()
    cues = parse_srt(args.input.read_text(encoding="utf-8-sig"))
    if not cues:
        raise SystemExit("No SRT cues found.")
    secondary_cues = parse_srt(args.secondary_input.read_text(encoding="utf-8-sig")) if args.secondary_input else None
    args.out.parent.mkdir(parents=True, exist_ok=True)
    render_mobile_pdf(
        cues,
        secondary_cues=secondary_cues,
        out=args.out,
        title=args.title or args.input.stem,
        subtitle=args.subtitle,
        font_path=args.font_path,
        include_timecodes=not args.hide_timecodes,
        disclaimer=None if args.hide_disclaimer else args.disclaimer,
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "cueCount": len(cues),
                "secondaryCueCount": len(secondary_cues) if secondary_cues is not None else 0,
                "out": str(args.out),
                "pageSize": "mobile-390x844pt",
                "source": str(args.input),
                "secondarySource": str(args.secondary_input) if args.secondary_input else None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Input SRT file.")
    parser.add_argument("--secondary-input", type=Path, help="Optional secondary SRT rendered under each cue.")
    parser.add_argument("--out", type=Path, required=True, help="Output PDF path.")
    parser.add_argument("--title", help="PDF title.")
    parser.add_argument("--subtitle", help="Optional subtitle shown under the title.")
    parser.add_argument("--font-path", type=Path, help="Optional CJK TTF/TTC/OTF font to embed.")
    parser.add_argument("--hide-timecodes", action="store_true", help="Hide cue timecodes in the PDF body.")
    parser.add_argument(
        "--disclaimer",
        default=DEFAULT_DISCLAIMER,
        help="Footer disclaimer shown on every page.",
    )
    parser.add_argument("--hide-disclaimer", action="store_true", help="Hide the footer disclaimer.")
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
    return re.sub(r"\s+", " ", text).strip()


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


def render_mobile_pdf(
    cues: list[Cue],
    *,
    secondary_cues: list[Cue] | None = None,
    out: Path,
    title: str,
    subtitle: str | None = None,
    font_path: Path | None = None,
    include_timecodes: bool = True,
    disclaimer: str | None = DEFAULT_DISCLAIMER,
) -> None:
    font_name = register_cjk_font(font_path)
    page_width, page_height = MOBILE_PAGE_SIZE
    margin_x = 22
    margin_top = 30
    margin_bottom = 54 if disclaimer else 30
    body_width = page_width - margin_x * 2
    doc = canvas.Canvas(str(out), pagesize=MOBILE_PAGE_SIZE)
    doc.setTitle(title)
    doc.setAuthor("sermon-video-zh-subtitles")
    secondary_by_index = align_secondary_cues(cues, secondary_cues or [])

    page_number = 1
    y = draw_header(
        doc,
        title=title,
        subtitle=subtitle,
        page_width=page_width,
        y=page_height - margin_top,
        font_name=font_name,
        first_page=True,
    )
    for index, cue in enumerate(cues):
        time_line = f"{display_time(cue.start)} - {display_time(cue.end)}"
        lines = wrap_text(cue.text, font_name, BODY_FONT_SIZE, body_width)
        secondary_width = body_width - SECONDARY_INDENT
        secondary_lines = (
            wrap_text(secondary_by_index[index], font_name, SECONDARY_FONT_SIZE, secondary_width)
            if secondary_by_index[index]
            else []
        )
        block_height = len(lines) * (BODY_FONT_SIZE + LINE_GAP) + CUE_GAP
        if secondary_lines:
            block_height += SECONDARY_GAP + len(secondary_lines) * (SECONDARY_FONT_SIZE + SECONDARY_LINE_GAP)
        if include_timecodes:
            block_height += TIME_LABEL_HEIGHT + TIME_LABEL_BOTTOM_GAP
        if y - block_height < margin_bottom:
            draw_footer(
                doc,
                page_width=page_width,
                page_number=page_number,
                font_name=font_name,
                margin_x=margin_x,
                disclaimer=disclaimer,
            )
            doc.showPage()
            page_number += 1
            y = draw_header(
                doc,
                title=title,
                subtitle=subtitle,
                page_width=page_width,
                y=page_height - margin_top,
                font_name=font_name,
                first_page=False,
            )
        if include_timecodes:
            draw_time_label(doc, x=margin_x, y=y, text=time_line, font_name=font_name)
            y -= TIME_LABEL_HEIGHT + TIME_LABEL_BOTTOM_GAP
        doc.setFillColor(colors.HexColor("#111827"))
        doc.setFont(font_name, BODY_FONT_SIZE)
        for line in lines:
            doc.drawString(margin_x, y, line)
            y -= BODY_FONT_SIZE + LINE_GAP
        if secondary_lines:
            y -= SECONDARY_GAP
            secondary_top = y + 2
            secondary_bottom = y - len(secondary_lines) * (SECONDARY_FONT_SIZE + SECONDARY_LINE_GAP) + 2
            doc.setStrokeColor(colors.HexColor("#d6dee9"))
            doc.setLineWidth(0.6)
            doc.line(margin_x + 1, secondary_top, margin_x + 1, secondary_bottom)
            doc.setFillColor(colors.HexColor("#556070"))
            doc.setFont(font_name, SECONDARY_FONT_SIZE)
            for line in secondary_lines:
                doc.drawString(margin_x + SECONDARY_INDENT, y, line)
                y -= SECONDARY_FONT_SIZE + SECONDARY_LINE_GAP
        y -= CUE_GAP

    draw_footer(
        doc,
        page_width=page_width,
        page_number=page_number,
        font_name=font_name,
        margin_x=margin_x,
        disclaimer=disclaimer,
    )
    doc.save()


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
    page_width: int,
    y: int,
    font_name: str,
    first_page: bool,
) -> float:
    margin_x = 22
    if not first_page:
        canvas_obj.setFillColor(colors.HexColor("#7c8798"))
        canvas_obj.setFont(font_name, RUNNING_HEADER_FONT_SIZE)
        for line in wrap_text(title, font_name, RUNNING_HEADER_FONT_SIZE, page_width - margin_x * 2)[:1]:
            canvas_obj.drawString(margin_x, y, line)
        canvas_obj.setStrokeColor(colors.HexColor("#eef1f4"))
        canvas_obj.line(margin_x, y - 10, page_width - margin_x, y - 10)
        return y - 26

    canvas_obj.setFillColor(colors.HexColor("#111827"))
    canvas_obj.setFont(font_name, TITLE_FONT_SIZE)
    title_lines = wrap_text(title, font_name, TITLE_FONT_SIZE, page_width - margin_x * 2)
    for line in title_lines[:2]:
        canvas_obj.drawString(margin_x, y, line)
        y -= TITLE_FONT_SIZE + 5
    if subtitle:
        canvas_obj.setFillColor(colors.HexColor("#4b5563"))
        canvas_obj.setFont(font_name, SUBTITLE_FONT_SIZE)
        for line in wrap_text(subtitle, font_name, SUBTITLE_FONT_SIZE, page_width - margin_x * 2)[:2]:
            canvas_obj.drawString(margin_x, y, line)
            y -= 13
    canvas_obj.setStrokeColor(colors.HexColor("#e5e7eb"))
    canvas_obj.line(margin_x, y - 4, page_width - margin_x, y - 4)
    return y - 18


def draw_footer(
    canvas_obj: canvas.Canvas,
    *,
    page_width: int,
    page_number: int,
    font_name: str,
    margin_x: int,
    disclaimer: str | None,
) -> None:
    canvas_obj.setFillColor(colors.HexColor("#9ca3af"))
    canvas_obj.setFont(font_name, 8)
    canvas_obj.drawRightString(page_width - margin_x, 12, f"{page_number}")
    if not disclaimer:
        return
    canvas_obj.setFillColor(colors.HexColor("#8b95a3"))
    canvas_obj.setFont(font_name, FOOTER_FONT_SIZE)
    footer_width = page_width - margin_x * 2
    footer_lines = wrap_text(disclaimer, font_name, FOOTER_FONT_SIZE, footer_width)[:2]
    y = 31 if len(footer_lines) > 1 else 25
    for line in footer_lines:
        canvas_obj.drawString(margin_x, y, line)
        y -= FOOTER_FONT_SIZE + 2


def draw_time_label(canvas_obj: canvas.Canvas, *, x: float, y: float, text: str, font_name: str) -> None:
    label_width = pdfmetrics.stringWidth(text, font_name, TIME_FONT_SIZE) + 11
    label_y = y - TIME_LABEL_HEIGHT + 2
    canvas_obj.setFillColor(colors.HexColor("#eef4fb"))
    canvas_obj.roundRect(x, label_y, label_width, TIME_LABEL_HEIGHT, 4, stroke=0, fill=1)
    canvas_obj.setFillColor(colors.HexColor("#5f7188"))
    canvas_obj.setFont(font_name, TIME_FONT_SIZE)
    canvas_obj.drawString(x + 5.5, label_y + 3.1, text)


def wrap_text(text: str, font_name: str, font_size: float, max_width: float) -> list[str]:
    lines: list[str] = []
    current = ""
    for token in text_tokens(text):
        candidate = current + token if current else token.lstrip()
        if current and pdfmetrics.stringWidth(candidate, font_name, font_size) > max_width:
            lines.append(current.rstrip())
            current = token.lstrip()
        else:
            current = candidate
    if current.strip():
        lines.append(current.rstrip())
    return lines or [""]


def text_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    buffer = ""
    for char in text:
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
    if buffer:
        tokens.append(buffer)
    return tokens


def is_cjk(char: str) -> bool:
    return "\u3400" <= char <= "\u9fff" or "\uf900" <= char <= "\ufaff"


def display_time(value: str) -> str:
    return value.replace(",", ".").rsplit(".", 1)[0]


if __name__ == "__main__":
    raise SystemExit(main())
