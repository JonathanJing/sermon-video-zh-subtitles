#!/usr/bin/env python3
"""Render a mobile-friendly Chinese sermon companion PDF from reviewed insight JSON."""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.render_mobile_pdf_from_srt import (  # noqa: E402
    COMPACT_DISCLAIMER,
    MOBILE_PAGE_SIZE,
    register_cjk_font,
)


PAGE_WIDTH, PAGE_HEIGHT = MOBILE_PAGE_SIZE
MARGIN_X = 23
MARGIN_TOP = 28
MARGIN_BOTTOM = 31
SPARSE_PAGE_USED_HEIGHT = 90


class TrackingDocTemplate(SimpleDocTemplate):
    """Capture used vertical space so QA can reject nearly empty continuation pages."""

    page_used_heights: dict[int, float]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.page_used_heights = {}

    def afterPage(self) -> None:
        frame = getattr(self, "frame", None)
        if frame is None:
            return
        used_height = max(0.0, float(frame._y2) - float(frame._y))
        self.page_used_heights[int(self.page)] = round(used_height, 2)


def main() -> int:
    args = parse_args()
    insights = json.loads(args.input.read_text(encoding="utf-8"))
    qa = render_companion_pdf(insights, args.out, font_path=args.font_path)
    qa_path = args.qa_out or args.out.with_suffix(".qa.json")
    qa_path.parent.mkdir(parents=True, exist_ok=True)
    qa_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "ok" if qa["status"] == "pass" else "needs_review",
                "out": str(args.out),
                "qa": str(qa_path),
                "qaStatus": qa["status"],
                "pageCount": qa["pageCount"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if qa["status"] == "pass" else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--qa-out", type=Path)
    parser.add_argument("--font-path", type=Path)
    return parser.parse_args()


def render_companion_pdf(
    insights: dict[str, Any],
    out: Path,
    *,
    font_path: Path | None = None,
) -> dict[str, Any]:
    out.parent.mkdir(parents=True, exist_ok=True)
    font_name = register_cjk_font(font_path)
    styles = companion_styles(font_name)
    story: list[Any] = []

    title = clean_text(insights.get("sermonTitle")) or "主日证道"
    speaker = clean_text(insights.get("speaker"))
    sermon_date = clean_text(insights.get("sermonDate"))
    source_label = clean_text(insights.get("sourceLabel"))
    summary = clean_text(insights.get("summaryZh"))
    outline = normalize_outline(insights.get("outlineZh"))
    scripture_refs = clean_string_list(insights.get("scriptureRefs"))
    quotes = normalize_quotes(insights.get("quotes"))

    story.append(Paragraph(escape(title), styles["title"]))
    story.append(Paragraph("证道同行", styles["document_type"]))
    metadata = " · ".join(part for part in (sermon_date, f"讲员：{speaker}" if speaker else "") if part)
    if metadata:
        story.append(Paragraph(escape(metadata), styles["metadata"]))
    story.append(Spacer(1, 10))
    if source_label:
        source_table = Table(
            [
                [Paragraph(escape(source_label), styles["source_note"])],
                [Paragraph(escape(COMPACT_DISCLAIMER), styles["source_disclaimer"])],
            ],
            colWidths=[PAGE_WIDTH - MARGIN_X * 2],
        )
        source_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EEF5FB")),
                    ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#C6D9EA")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 1), (0, 1), 0),
                ]
            )
        )
        story.extend([source_table, Spacer(1, 13)])

    if summary:
        story.extend(section("证道摘要", [Paragraph(escape(summary), styles["body"])], styles))

    if outline:
        outline_flowables: list[Any] = []
        for index, item in enumerate(outline, start=1):
            item_flowables: list[Any] = [
                Paragraph(f"{index}. {escape(item['title'])}", styles["outline_title"])
            ]
            if item["points"]:
                bullet_lines = "<br/>".join(f"• {escape(point)}" for point in item["points"])
                item_flowables.append(Paragraph(bullet_lines, styles["bullet"]))
            item_flowables.append(Spacer(1, 5))
            outline_flowables.append(KeepTogether(item_flowables))
        story.extend(section("证道脉络", outline_flowables, styles))

    if scripture_refs:
        scripture_flowables = [Paragraph(f"• {escape(ref)}", styles["bullet"]) for ref in scripture_refs]
        story.extend(section("重点经文", scripture_flowables, styles))

    if quotes:
        quote_flowables: list[Any] = []
        for quote in quotes:
            quote_block: list[Any] = [Paragraph(f"“{escape(quote['textZh'])}”", styles["quote"])]
            evidence = quote_evidence_label(quote)
            if evidence:
                quote_block.append(Paragraph(escape(evidence), styles["evidence"]))
            quote_block.append(Spacer(1, 7))
            quote_flowables.append(KeepTogether(quote_block))
        story.extend(section("讲道摘录（中文译文）", quote_flowables, styles))

    doc = TrackingDocTemplate(
        str(out),
        pagesize=MOBILE_PAGE_SIZE,
        leftMargin=MARGIN_X,
        rightMargin=MARGIN_X,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM,
        title=f"{title} - 证道同行",
        author="sermon-video-zh-subtitles",
    )
    doc.build(
        story,
        onFirstPage=lambda canvas_obj, _doc: draw_page_footer(canvas_obj, font_name),
        onLaterPages=lambda canvas_obj, _doc: draw_page_footer(canvas_obj, font_name),
    )

    forbidden_fields = find_forbidden_fields(insights)
    sparse_pages = [
        page
        for page, used_height in sorted(doc.page_used_heights.items())
        if page > 1 and used_height < SPARSE_PAGE_USED_HEIGHT
    ]
    failures: list[str] = []
    if not summary:
        failures.append("missing_summary")
    if not outline:
        failures.append("missing_outline")
    if forbidden_fields:
        failures.append("discussion_or_application_fields_present")
    if not out.exists() or out.stat().st_size < 500:
        failures.append("pdf_missing_or_too_small")
    if sparse_pages:
        failures.append("sparse_continuation_page")
    if quotes and not all(quote.get("sourceSegmentId") and quote.get("sourceTextZh") for quote in quotes):
        failures.append("quote_traceability_incomplete")

    return {
        "schemaVersion": 1,
        "status": "pass" if not failures else "needs_review",
        "artifactType": "sermon_companion_pdf",
        "pdf": str(out),
        "pageCount": int(getattr(doc, "page", 0) or 0),
        "pageUsedHeights": doc.page_used_heights,
        "sparsePages": sparse_pages,
        "font": font_name,
        "summaryPresent": bool(summary),
        "outlineSectionCount": len(outline),
        "scriptureRefCount": len(scripture_refs),
        "quoteCount": len(quotes),
        "discussionQuestionsIncluded": False,
        "forbiddenFieldPaths": forbidden_fields,
        "failures": failures,
    }


def companion_styles(font_name: str) -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "CompanionTitle",
            parent=base["Title"],
            fontName=font_name,
            fontSize=18,
            leading=24,
            textColor=colors.HexColor("#111827"),
            alignment=TA_CENTER,
            wordWrap="CJK",
            spaceAfter=4,
        ),
        "document_type": ParagraphStyle(
            "DocumentType",
            parent=base["Normal"],
            fontName=font_name,
            fontSize=11,
            leading=15,
            textColor=colors.HexColor("#315D7D"),
            alignment=TA_CENTER,
            wordWrap="CJK",
        ),
        "metadata": ParagraphStyle(
            "Metadata",
            parent=base["Normal"],
            fontName=font_name,
            fontSize=8.5,
            leading=12,
            textColor=colors.HexColor("#667085"),
            alignment=TA_CENTER,
            wordWrap="CJK",
            spaceBefore=5,
        ),
        "source_note": ParagraphStyle(
            "SourceNote",
            parent=base["Normal"],
            fontName=font_name,
            fontSize=9,
            leading=14,
            textColor=colors.HexColor("#35566F"),
            wordWrap="CJK",
        ),
        "source_disclaimer": ParagraphStyle(
            "SourceDisclaimer",
            parent=base["Normal"],
            fontName=font_name,
            fontSize=7.4,
            leading=11,
            textColor=colors.HexColor("#66788A"),
            wordWrap="CJK",
        ),
        "section_heading": ParagraphStyle(
            "SectionHeading",
            parent=base["Heading2"],
            fontName=font_name,
            fontSize=12.5,
            leading=17,
            textColor=colors.HexColor("#1F4E6B"),
            wordWrap="CJK",
            spaceBefore=5,
            spaceAfter=7,
            keepWithNext=1,
        ),
        "body": ParagraphStyle(
            "CompanionBody",
            parent=base["BodyText"],
            fontName=font_name,
            fontSize=11.2,
            leading=18,
            textColor=colors.HexColor("#202B38"),
            wordWrap="CJK",
        ),
        "outline_title": ParagraphStyle(
            "OutlineTitle",
            parent=base["BodyText"],
            fontName=font_name,
            fontSize=11.2,
            leading=17,
            textColor=colors.HexColor("#172B3A"),
            wordWrap="CJK",
            spaceAfter=3,
        ),
        "bullet": ParagraphStyle(
            "CompanionBullet",
            parent=base["BodyText"],
            fontName=font_name,
            fontSize=10.5,
            leading=16.5,
            leftIndent=10,
            firstLineIndent=-7,
            textColor=colors.HexColor("#344054"),
            wordWrap="CJK",
            spaceAfter=2,
        ),
        "quote": ParagraphStyle(
            "CompanionQuote",
            parent=base["BodyText"],
            fontName=font_name,
            fontSize=11.2,
            leading=18,
            leftIndent=10,
            rightIndent=8,
            textColor=colors.HexColor("#243B53"),
            wordWrap="CJK",
        ),
        "evidence": ParagraphStyle(
            "QuoteEvidence",
            parent=base["BodyText"],
            fontName=font_name,
            fontSize=7.8,
            leading=11,
            leftIndent=10,
            textColor=colors.HexColor("#768596"),
            wordWrap="CJK",
        ),
    }


def section(title: str, body: list[Any], styles: dict[str, ParagraphStyle]) -> list[Any]:
    if not body:
        return []
    heading = Paragraph(escape(title), styles["section_heading"])
    return [heading, *body, Spacer(1, 10)]


def draw_page_footer(canvas_obj: Any, font_name: str) -> None:
    canvas_obj.saveState()
    canvas_obj.setStrokeColor(colors.HexColor("#D9E1E8"))
    canvas_obj.line(MARGIN_X, 22, PAGE_WIDTH - MARGIN_X, 22)
    canvas_obj.setFillColor(colors.HexColor("#7A8795"))
    canvas_obj.setFont(font_name, 7.5)
    canvas_obj.drawString(MARGIN_X, 11, "证道同行 · AI 辅助整理")
    canvas_obj.drawRightString(PAGE_WIDTH - MARGIN_X, 11, str(canvas_obj.getPageNumber()))
    canvas_obj.restoreState()


def normalize_outline(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        title = clean_text(item.get("title"))
        points = clean_string_list(item.get("points"))
        if title or points:
            result.append({"title": title or "要点", "points": points})
    return result


def normalize_quotes(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict) and clean_text(item.get("textZh"))]


def quote_evidence_label(quote: dict[str, Any]) -> str:
    parts: list[str] = []
    start_ms = int(quote.get("startMs") or 0)
    if start_ms:
        parts.append(format_timestamp(start_ms))
    segment_id = clean_text(quote.get("sourceSegmentId"))
    if segment_id:
        parts.append(segment_id)
    return "来源：" + " · ".join(parts) if parts else ""


def format_timestamp(milliseconds: int) -> str:
    total_seconds = max(0, milliseconds // 1000)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


def find_forbidden_fields(value: Any, prefix: str = "") -> list[str]:
    forbidden = ("question", "application")
    found: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if any(token in str(key).lower() for token in forbidden):
                found.append(path)
            found.extend(find_forbidden_fields(nested, path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found.extend(find_forbidden_fields(nested, f"{prefix}[{index}]"))
    return found


def clean_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [clean_text(item) for item in value if clean_text(item)]


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def escape(value: str) -> str:
    return html.escape(value, quote=False)


if __name__ == "__main__":
    raise SystemExit(main())
