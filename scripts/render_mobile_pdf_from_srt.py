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
TITLE_FONT_SIZE = 17
BODY_FONT_SIZE = 13
TIME_FONT_SIZE = 8.5
LINE_GAP = 4
CUE_GAP = 10


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
    args.out.parent.mkdir(parents=True, exist_ok=True)
    render_mobile_pdf(
        cues,
        out=args.out,
        title=args.title or args.input.stem,
        subtitle=args.subtitle,
        font_path=args.font_path,
        include_timecodes=not args.hide_timecodes,
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "cueCount": len(cues),
                "out": str(args.out),
                "pageSize": "mobile-390x844pt",
                "source": str(args.input),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Input SRT file.")
    parser.add_argument("--out", type=Path, required=True, help="Output PDF path.")
    parser.add_argument("--title", help="PDF title.")
    parser.add_argument("--subtitle", help="Optional subtitle shown under the title.")
    parser.add_argument("--font-path", type=Path, help="Optional CJK TTF/TTC/OTF font to embed.")
    parser.add_argument("--hide-timecodes", action="store_true", help="Hide cue timecodes in the PDF body.")
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


def render_mobile_pdf(
    cues: list[Cue],
    *,
    out: Path,
    title: str,
    subtitle: str | None = None,
    font_path: Path | None = None,
    include_timecodes: bool = True,
) -> None:
    font_name = register_cjk_font(font_path)
    page_width, page_height = MOBILE_PAGE_SIZE
    margin_x = 24
    margin_top = 28
    margin_bottom = 28
    body_width = page_width - margin_x * 2
    doc = canvas.Canvas(str(out), pagesize=MOBILE_PAGE_SIZE)
    doc.setTitle(title)

    page_number = 1
    y = draw_header(doc, title=title, subtitle=subtitle, page_width=page_width, y=page_height - margin_top, font_name=font_name)
    for cue in cues:
        time_line = f"{display_time(cue.start)} - {display_time(cue.end)}"
        lines = wrap_text(cue.text, font_name, BODY_FONT_SIZE, body_width)
        block_height = len(lines) * (BODY_FONT_SIZE + LINE_GAP) + CUE_GAP
        if include_timecodes:
            block_height += TIME_FONT_SIZE + 3
        if y - block_height < margin_bottom:
            draw_footer(doc, page_width=page_width, page_number=page_number, font_name=font_name)
            doc.showPage()
            page_number += 1
            y = draw_header(doc, title=title, subtitle=subtitle, page_width=page_width, y=page_height - margin_top, font_name=font_name)
        if include_timecodes:
            doc.setFillColor(colors.HexColor("#6b7280"))
            doc.setFont(font_name, TIME_FONT_SIZE)
            doc.drawString(margin_x, y, time_line)
            y -= TIME_FONT_SIZE + 4
        doc.setFillColor(colors.HexColor("#111827"))
        doc.setFont(font_name, BODY_FONT_SIZE)
        for line in lines:
            doc.drawString(margin_x, y, line)
            y -= BODY_FONT_SIZE + LINE_GAP
        y -= CUE_GAP

    draw_footer(doc, page_width=page_width, page_number=page_number, font_name=font_name)
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
) -> float:
    margin_x = 24
    canvas_obj.setFillColor(colors.HexColor("#111827"))
    canvas_obj.setFont(font_name, TITLE_FONT_SIZE)
    title_lines = wrap_text(title, font_name, TITLE_FONT_SIZE, page_width - margin_x * 2)
    for line in title_lines[:2]:
        canvas_obj.drawString(margin_x, y, line)
        y -= TITLE_FONT_SIZE + 5
    if subtitle:
        canvas_obj.setFillColor(colors.HexColor("#4b5563"))
        canvas_obj.setFont(font_name, 10)
        for line in wrap_text(subtitle, font_name, 10, page_width - margin_x * 2)[:2]:
            canvas_obj.drawString(margin_x, y, line)
            y -= 14
    canvas_obj.setStrokeColor(colors.HexColor("#e5e7eb"))
    canvas_obj.line(margin_x, y - 4, page_width - margin_x, y - 4)
    return y - 20


def draw_footer(canvas_obj: canvas.Canvas, *, page_width: int, page_number: int, font_name: str) -> None:
    canvas_obj.setFillColor(colors.HexColor("#9ca3af"))
    canvas_obj.setFont(font_name, 8)
    canvas_obj.drawCentredString(page_width / 2, 14, f"{page_number}")


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
