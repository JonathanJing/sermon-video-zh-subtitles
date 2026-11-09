#!/usr/bin/env python3
"""Build a bilingual, speaker-labeled PDF manuscript from a sentence-first run.

Reads ``sentences.jsonl`` (English + speakerId) and ``translations.jsonl`` (target),
and writes one table row per sentence: ``Eric:`` / ``Steve:`` | English | 中文.
No transcript text is invented; the optional name repairs are printed in the PDF.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import (BaseDocTemplate, Frame, LongTable, PageBreak,
                                PageTemplate, Paragraph, Spacer, Table, TableStyle)

FONT = "/Library/Fonts/Arial Unicode.ttf"
SONG = "/System/Library/Fonts/Supplemental/Songti.ttc"
SPEAKERS = {"eric_geiger": "Eric", "steve_bang_lee": "Steve"}
CLOSING = set("，。！？；：、”’）】》")
OPENING = set("“‘（【《")
COL = [22, 46, 224, 235]


def cjk_tokens(text: str) -> list[str]:
    out, i = [], 0
    while i < len(text):
        ch = text[i]
        if ch.isspace():
            if out and out[-1] != " ":
                out.append(" ")
            i += 1
        elif ch in CLOSING and out:
            out[-1] += ch
            i += 1
        elif ch.isascii() and (ch.isalnum() or ch in "'’-"):
            j = i
            while j < len(text) and text[j].isascii() and (text[j].isalnum() or text[j] in "'’-"):
                j += 1
            out.append(text[i:j])
            i = j
        else:
            out.append(ch)
            i += 1
    return out


def cjk_lines(text: str, max_width: float, font: str = "Song", size: float = 9.2) -> list[str]:
    """Greedy CJK wrapping with basic kinsoku: no line starts with closing punctuation."""
    lines, line, width = [], "", 0.0
    for token in cjk_tokens(text):
        if token == " ":
            if line and not line.endswith(" "):
                line += " "
                width += stringWidth(" ", font, size)
            continue
        token_width = stringWidth(token, font, size)
        if line and width + token_width > max_width:
            stripped = line.rstrip()
            if stripped and stripped[-1] in OPENING:
                line = stripped[:-1].rstrip()
                lines.append(line)
                line, width = stripped[-1], stringWidth(stripped[-1], font, size)
            else:
                lines.append(stripped)
                line, width = "", 0.0
        if not line and token in CLOSING:
            if lines:
                lines[-1] += token
                continue
        line += token
        width += token_width
    if line.strip():
        lines.append(line.rstrip())
    return lines or [""]
NAME_REPAIRS = {
    "Eric Gager's back.": "Eric Geiger's back.",
    "So you So Bang asked me": "So you, Steve Bang, asked me",
}


def load(run: Path) -> list[dict]:
    sentences = [json.loads(line) for line in (run / "sentences.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    targets = {row["id"]: row.get("target", "") for row in
               (json.loads(line) for line in (run / "translations.jsonl").read_text(encoding="utf-8").splitlines() if line.strip())}
    rows = []
    for item in sentences:
        english = " ".join(item.get("english", "").split())
        for old, new in NAME_REPAIRS.items():
            english = english.replace(old, new)
        chinese = " ".join((targets.get(item["id"]) or "").split())
        chinese = re.sub(r"\s+([，。！？；：、”’）】》])", r"\1", chinese)
        chinese = re.sub(r"([“‘（【《])\s+", r"\1", chinese)
        rows.append({"id": item["id"], "speaker": SPEAKERS.get(item.get("speakerId"), item.get("speakerId", "Speaker")),
                     "english": english, "chinese": chinese})
    return rows


def build(run: Path, out: Path, title_en: str, title_zh: str, date: str, source_url: str, duration: str) -> dict:
    rows = load(run)
    counts = Counter(row["speaker"] for row in rows)
    pdfmetrics.registerFont(TTFont("Body", FONT))
    pdfmetrics.registerFont(TTFont("Song", SONG, subfontIndex=6))
    for row in rows:
        row["chinese_html"] = "<br/>".join(escape(line) for line in cjk_lines(row["chinese"], COL[3] - 9))
    pdfmetrics.registerFontFamily("Body", normal="Body", bold="Body", italic="Body", boldItalic="Body")

    ink, muted, faint = colors.HexColor("#111827"), colors.HexColor("#6B7280"), colors.HexColor("#E5E7EB")
    steve, eric = colors.HexColor("#1D4ED8"), colors.HexColor("#B45309")
    dark = colors.HexColor("#1F2937")
    en_style = ParagraphStyle("en", fontName="Body", fontSize=8.6, leading=11.2, textColor=ink, wordWrap="LTR")
    zh_style = ParagraphStyle("zh", fontName="Song", fontSize=9.2, leading=12.2, textColor=ink, wordWrap="LTR")
    sp_steve = ParagraphStyle("spsteve", fontName="Helvetica-Bold", fontSize=8.2, leading=10, textColor=steve)
    sp_eric = ParagraphStyle("speric", fontName="Helvetica-Bold", fontSize=8.2, leading=10, textColor=eric)
    header_style = ParagraphStyle("header", fontName="Body", fontSize=8, leading=10, textColor=colors.white)
    cover_small = ParagraphStyle("small", fontName="Body", fontSize=8.5, leading=13, textColor=muted)
    cover_title = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=25, leading=29, textColor=ink)
    cover_zh = ParagraphStyle("zhcover", fontName="Song", fontSize=21, leading=27, textColor=ink)
    cover_meta = ParagraphStyle("meta", fontName="Body", fontSize=9.5, leading=15, textColor=ink)
    cover_note = ParagraphStyle("note", fontName="Body", fontSize=8.5, leading=13, textColor=colors.HexColor("#374151"))

    def header_footer(canvas, doc):
        if doc.page == 1:
            return
        canvas.saveState()
        canvas.setStrokeColor(faint)
        canvas.setLineWidth(0.5)
        canvas.line(12 * mm, A4[1] - 15 * mm, A4[0] - 12 * mm, A4[1] - 15 * mm)
        canvas.setFont("Body", 7.2)
        canvas.setFillColor(muted)
        canvas.drawString(12 * mm, A4[1] - 13 * mm, "If I Had More Time · Jesus wins — 中英文讲稿")
        canvas.drawRightString(A4[0] - 12 * mm, A4[1] - 13 * mm, "Eric Geiger · Steve Bang Lee")
        canvas.line(12 * mm, 14 * mm, A4[0] - 12 * mm, 14 * mm)
        canvas.drawString(12 * mm, 9 * mm, "逐句对齐稿 · 非官方文本 · 请勿作为逐字听写引用")
        canvas.drawRightString(A4[0] - 12 * mm, 9 * mm, f"第 {doc.page} 页")
        canvas.restoreState()

    doc = BaseDocTemplate(str(out), pagesize=A4, leftMargin=12 * mm, rightMargin=12 * mm,
                          topMargin=16 * mm, bottomMargin=15 * mm,
                          title=f"{title_en} — 中英文讲稿", author="sentence-first-agent",
                          subject="Bilingual speaker-labeled transcript")
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="body")
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=header_footer)])

    story = []
    story += [Spacer(1, 18 * mm),
              Paragraph("SENTENCE-FIRST PODCAST TRANSCRIPT", cover_small),
              Spacer(1, 6 * mm),
              Paragraph(escape(title_en), cover_title),
              Spacer(1, 2 * mm),
              Paragraph(escape(title_zh), cover_zh),
              Spacer(1, 5 * mm),
              Table([[""]], colWidths=[90 * mm], rowHeights=[0.8 * mm],
                    style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#111827"))])),
              Spacer(1, 14 * mm),
              Paragraph("中英文讲稿 · 按说话人逐句分句", ParagraphStyle("sub", fontName="Body", fontSize=12, leading=18, textColor=ink)),
              Spacer(1, 8 * mm),
              Paragraph(f"<b>Speakers:</b> Eric Geiger · Steve Bang Lee<br/>"
                        f"<b>Date:</b> {escape(date)}　　<b>Duration:</b> {escape(duration)}<br/>"
                        f"<b>Source:</b> {escape(source_url)}<br/>"
                        f"<b>Sentences:</b> {len(rows)}　（Eric {counts.get('Eric', 0)} / Steve {counts.get('Steve', 0)}）", cover_meta),
              Spacer(1, 12 * mm),
              Paragraph("阅读说明", ParagraphStyle("h", fontName="Body", fontSize=9.5, leading=14, textColor=ink)),
              Spacer(1, 2 * mm),
              Paragraph("每句先英文、后中文；左侧为 diarization 得到的说话人。"
                        "英文来自节目 SRT；中文为 Opus 译文经独立审计修订。"
                        "讲稿保留书面“撒但”，配音口播使用“魔鬼”。"
                        "英文仅校正两处明显专名：Gager→Geiger、So Bang→Steve Bang。", cover_note),
              Spacer(1, 5 * mm),
              Paragraph("本讲稿为机器翻译与机器说话人分配，不是逐字听写，也不是 Mariners Church 官方文本。"
                        "本项目与 Mariners Church 无隶属关系。", cover_note),
              PageBreak(),
              Paragraph("正文", ParagraphStyle("bodyh", fontName="Body", fontSize=13, leading=18, textColor=ink)),
              Spacer(1, 2 * mm),
              Paragraph(f"共 {len(rows)} 句；按节目顺序排列。English / 中文。", ParagraphStyle("bodysub", fontName="Body", fontSize=8.5, leading=12, textColor=muted)),
              Spacer(1, 4 * mm)]

    data = [[Paragraph("#", header_style), Paragraph("说话人 / Speaker", header_style),
             Paragraph("English", header_style), Paragraph("中文", header_style)]]
    for index, row in enumerate(rows, 1):
        data.append([Paragraph(str(index), ParagraphStyle("num", fontName="Body", fontSize=7.5, leading=9, textColor=muted)),
                     Paragraph(f"{row['speaker']}:", sp_steve if row["speaker"] == "Steve" else sp_eric),
                     Paragraph(escape(row["english"]), en_style),
                     Paragraph(row["chinese_html"], zh_style)])
    table = LongTable(data, colWidths=COL, repeatRows=1)
    style = [("BACKGROUND", (0, 0), (-1, 0), dark), ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
             ("TOPPADDING", (0, 0), (-1, -1), 2.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.6),
             ("LINEBELOW", (0, 0), (-1, -1), 0.25, faint)]
    for index, row in enumerate(rows, 1):
        style.append(("BACKGROUND", (0, index), (-1, index),
                      colors.HexColor("#F3F6FB") if row["speaker"] == "Steve" else colors.HexColor("#FFFBF3")))
    table.setStyle(TableStyle(style))
    story.append(table)
    story += [Spacer(1, 8 * mm),
              Paragraph("— 讲稿完 —", ParagraphStyle("end", fontName="Song", fontSize=9, leading=13, textColor=muted, alignment=1))]
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.build(story)
    return {"pdf": str(out), "sentences": len(rows), "pages": None}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--title-en", default="If I Had More Time · Jesus wins")
    p.add_argument("--title-zh", default="如果我有更多时间 · 耶稣得胜")
    p.add_argument("--date", default="2026-10-25")
    p.add_argument("--source-url", default="https://www.youtube.com/watch?v=7KRsow9aqBo")
    p.add_argument("--duration", default="54:57")
    a = p.parse_args()
    print(json.dumps(build(a.run, a.out, a.title_en, a.title_zh, a.date, a.source_url, a.duration), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
