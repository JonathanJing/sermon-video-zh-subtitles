#!/usr/bin/env python3
"""Render a mobile-friendly Chinese sermon interpretation PDF from reviewed insight JSON."""

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
    qa = render_interpretation_pdf(insights, args.out, font_path=args.font_path)
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


def render_interpretation_pdf(
    insights: dict[str, Any],
    out: Path,
    *,
    font_path: Path | None = None,
    _allow_outline_split: bool = True,
) -> dict[str, Any]:
    out.parent.mkdir(parents=True, exist_ok=True)
    font_name = register_cjk_font(font_path)
    styles = interpretation_styles(font_name)
    story: list[Any] = []

    title = clean_text(insights.get("sermonTitle")) or "主日证道"
    speaker = clean_text(insights.get("speaker"))
    sermon_date = clean_text(insights.get("sermonDate"))
    source_label = clean_text(insights.get("sourceLabel"))
    central_message = clean_text(insights.get("centralMessageZh"))
    central_message_sources = normalize_source_indexes(insights.get("centralMessageSourceSliceIndexes"))
    summary = clean_text(insights.get("summaryZh"))
    summary_sources = normalize_source_indexes(insights.get("summarySourceSliceIndexes"))
    outline = normalize_outline(insights.get("outlineZh"))
    scripture_refs = clean_string_list(insights.get("scriptureRefs"))
    scripture_context = normalize_sourced_items(
        insights.get("scriptureContextZh"),
        title_key="reference",
        body_key="explanation",
    )
    theological_insights = normalize_sourced_items(
        insights.get("theologicalInsightsZh"),
        title_key="title",
        body_key="explanation",
    )
    illustrations = normalize_sourced_items(
        insights.get("illustrationsZh"),
        title_key="title",
        body_key="function",
    )
    pastoral_distinctions = normalize_sourced_items(
        insights.get("pastoralDistinctionsZh"),
        title_key="title",
        body_key="explanation",
    )
    reflection_questions = normalize_reflection_questions(insights.get("reflectionQuestionsZh"))
    small_group_guide = normalize_sourced_items(
        insights.get("smallGroupGuideZh"),
        title_key="section",
        body_key="guidance",
    )
    response_prayer = clean_text(insights.get("responsePrayerZh"))
    response_prayer_sources = normalize_source_indexes(insights.get("responsePrayerSourceSliceIndexes"))
    quotes = normalize_quotes(insights.get("quotes"))
    slices_by_index = {
        int(item.get("index") or 0): item
        for item in (insights.get("slices") or [])
        if isinstance(item, dict) and int(item.get("index") or 0) > 0
    }

    story.append(Paragraph(escape(title), styles["title"]))
    story.append(Paragraph("证道解读", styles["document_type"]))
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

    if central_message:
        central_table = Table(
            [
                [Paragraph("核心信息", styles["callout_title"])],
                [Paragraph(escape(central_message), styles["central_message"])],
                [Paragraph(escape(source_indexes_label(central_message_sources, slices_by_index)), styles["evidence"])],
            ],
            colWidths=[PAGE_WIDTH - MARGIN_X * 2],
        )
        central_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#E9F3F8")),
                    ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#2E6F95")),
                    ("LINEBEFORE", (0, 0), (0, -1), 3.5, colors.HexColor("#2E6F95")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ]
            )
        )
        story.extend([central_table, Spacer(1, 12)])

    if summary:
        story.extend(
            section(
                "证道摘要",
                [
                    Paragraph(escape(summary), styles["body"]),
                    Paragraph(escape(source_indexes_label(summary_sources, slices_by_index)), styles["evidence"]),
                ],
                styles,
            )
        )

    if outline:
        outline_flowables: list[Any] = []
        for index, item in enumerate(outline, start=1):
            item_flowables: list[Any] = [
                Paragraph(f"{index}. {escape(item['title'])}", styles["outline_title"])
            ]
            if _allow_outline_split:
                if item["points"]:
                    item_flowables.extend(
                        Paragraph(f"• {escape(point)}", styles["bullet"])
                        for point in item["points"][:-1]
                    )
                item_tail: list[Any] = []
                if item["points"]:
                    item_tail.append(
                        Paragraph(f"• {escape(item['points'][-1])}", styles["bullet"])
                    )
                item_tail.append(
                    Paragraph(
                        escape(source_indexes_label(item["sourceSliceIndexes"], slices_by_index)),
                        styles["evidence"],
                    )
                )
                item_tail.append(Spacer(1, 5))
                # Let long outline entries cross a page boundary while keeping
                # the final point attached to its traceability evidence.
                item_flowables.append(KeepTogether(item_tail))
                outline_flowables.extend(item_flowables)
            else:
                if item["points"]:
                    bullet_lines = "<br/>".join(
                        f"• {escape(point)}" for point in item["points"]
                    )
                    item_flowables.append(Paragraph(bullet_lines, styles["bullet"]))
                item_flowables.append(
                    Paragraph(
                        escape(source_indexes_label(item["sourceSliceIndexes"], slices_by_index)),
                        styles["evidence"],
                    )
                )
                item_flowables.append(Spacer(1, 5))
                outline_flowables.append(KeepTogether(item_flowables))
        story.extend(section("证道脉络", outline_flowables, styles))

    if scripture_refs or scripture_context:
        scripture_flowables = [
            Paragraph(f"• {escape(ref)}", styles["bullet"])
            for ref in scripture_refs
        ]
        scripture_flowables.extend(
            sourced_item_flowables(scripture_context, slices_by_index, styles)
        )
        story.extend(section("经文脉络", scripture_flowables, styles))

    if theological_insights:
        story.extend(
            section(
                "神学重点",
                sourced_item_flowables(theological_insights, slices_by_index, styles),
                styles,
            )
        )

    if illustrations:
        story.extend(
            section(
                "例证与作用",
                sourced_item_flowables(illustrations, slices_by_index, styles),
                styles,
            )
        )

    if pastoral_distinctions:
        story.extend(
            section(
                "牧养辨析",
                sourced_item_flowables(pastoral_distinctions, slices_by_index, styles),
                styles,
            )
        )

    story.extend(
        section(
            "编辑性牧养提醒",
            [
                Table(
                    [
                        [
                            Paragraph(
                                "本解读主要跟随证道处理因自己行为产生的罪疚与羞耻。"
                                "如果羞耻来自他人施加的虐待、暴力或操控，责任不在受害者；"
                                "寻求安全、教会保护、专业帮助或法律介入，并不违背恩典。",
                                styles["caution"],
                            )
                        ]
                    ],
                    colWidths=[PAGE_WIDTH - MARGIN_X * 2],
                    style=TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FBEDEE")),
                            ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#A7484F")),
                            ("LINEBEFORE", (0, 0), (0, -1), 3.5, colors.HexColor("#A7484F")),
                            ("LEFTPADDING", (0, 0), (-1, -1), 10),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                            ("TOPPADDING", (0, 0), (-1, -1), 9),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                        ]
                    ),
                )
            ],
            styles,
        )
    )

    if reflection_questions:
        reflection_flowables: list[Any] = [
            Paragraph("以下问题为 AI 辅助整理，不是讲员原话。", styles["ai_label"])
        ]
        for index, item in enumerate(reflection_questions, start=1):
            reflection_flowables.extend(
                [
                    Paragraph(f"{index}. {escape(item['question'])}", styles["body"]),
                    Paragraph(
                        escape(source_indexes_label(item["sourceSliceIndexes"], slices_by_index)),
                        styles["evidence"],
                    ),
                    Spacer(1, 4),
                ]
            )
        story.extend(section("个人反思", reflection_flowables, styles))

    if small_group_guide:
        group_flowables: list[Any] = [
            Paragraph("以下带领建议为 AI 辅助整理，应由小组带领者按实际情况审阅。", styles["ai_label"])
        ]
        group_flowables.extend(
            sourced_item_flowables(small_group_guide, slices_by_index, styles)
        )
        story.extend(section("小组讨论指南", group_flowables, styles))

    if response_prayer:
        prayer_table = Table(
            [
                [Paragraph("AI 辅助回应祷告，非讲员原祷告", styles["ai_label"])],
                [Paragraph(escape(response_prayer), styles["body"])],
                [
                    Paragraph(
                        escape(source_indexes_label(response_prayer_sources, slices_by_index)),
                        styles["evidence"],
                    )
                ],
            ],
            colWidths=[PAGE_WIDTH - MARGIN_X * 2],
        )
        prayer_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EEF5FB")),
                    ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#7FA7C2")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        story.extend(section("回应祷告", [prayer_table], styles))

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
        title=f"{title} - 证道解读",
        author="sermon-video-zh-subtitles",
    )
    doc.build(
        story,
        onFirstPage=lambda canvas_obj, _doc: draw_page_footer(canvas_obj, font_name),
        onLaterPages=lambda canvas_obj, _doc: draw_page_footer(canvas_obj, font_name),
    )

    sparse_pages = [
        page
        for page, used_height in sorted(doc.page_used_heights.items())
        if page > 1 and used_height < SPARSE_PAGE_USED_HEIGHT
    ]
    if _allow_outline_split and sparse_pages:
        fallback_qa = render_interpretation_pdf(
            insights,
            out,
            font_path=font_path,
            _allow_outline_split=False,
        )
        fallback_qa["outlineSplitFallbackApplied"] = True
        return fallback_qa
    failures: list[str] = []
    traceability = insights.get("traceability") if isinstance(insights.get("traceability"), dict) else {}
    declared_missing_source_paths = clean_string_list(traceability.get("missingSourcePaths"))
    derived_missing_source_paths = find_missing_or_invalid_source_paths(
        central_message=central_message,
        central_message_sources=central_message_sources,
        summary=summary,
        summary_sources=summary_sources,
        outline=outline,
        scripture_context=scripture_context,
        theological_insights=theological_insights,
        illustrations=illustrations,
        pastoral_distinctions=pastoral_distinctions,
        reflection_questions=reflection_questions,
        small_group_guide=small_group_guide,
        response_prayer=response_prayer,
        response_prayer_sources=response_prayer_sources,
        valid_slice_indexes=set(slices_by_index),
    )
    missing_source_paths = list(
        dict.fromkeys([*declared_missing_source_paths, *derived_missing_source_paths])
    )
    interpretation_traceability_complete = bool(
        traceability.get("allInterpretationItemsHaveSource")
    ) and not missing_source_paths
    quote_traceability_complete = all(
        quote_has_exact_source(quote, slices_by_index=slices_by_index)
        for quote in quotes
    )
    page_count = int(getattr(doc, "page", 0) or 0)
    blank_pages = [
        page
        for page, used_height in sorted(doc.page_used_heights.items())
        if used_height <= 0
    ]
    if not summary:
        failures.append("missing_summary")
    if not central_message:
        failures.append("missing_central_message")
    if len(outline) < 3:
        failures.append("missing_outline")
    if not scripture_refs:
        failures.append("missing_scripture_references")
    if not scripture_context:
        failures.append("missing_scripture_context")
    if len(theological_insights) < 2:
        failures.append("insufficient_theological_insights")
    if not pastoral_distinctions:
        failures.append("missing_pastoral_distinctions")
    if len(reflection_questions) < 3:
        failures.append("insufficient_reflection_questions")
    if len(small_group_guide) < 3:
        failures.append("insufficient_small_group_guide")
    if not response_prayer:
        failures.append("missing_response_prayer")
    if not interpretation_traceability_complete:
        failures.append("interpretation_traceability_incomplete")
    if not out.exists() or out.stat().st_size < 500:
        failures.append("pdf_missing_or_too_small")
    if blank_pages:
        failures.append("blank_pages")
    if sparse_pages:
        failures.append("sparse_continuation_page")
    if page_count > 20:
        failures.append("page_count_exceeds_limit")
    if quotes and not quote_traceability_complete:
        failures.append("quote_traceability_incomplete")
    missing_glyph_markers = [
        marker
        for marker in ("\ufffd", "□")
        if marker in json.dumps(insights, ensure_ascii=False)
    ]
    if missing_glyph_markers:
        failures.append("missing_glyph_markers")

    return {
        "schemaVersion": 2,
        "status": "pass" if not failures else "needs_review",
        "artifactType": "sermon_interpretation_pdf",
        "pdf": str(out),
        "pageCount": page_count,
        "pageUsedHeights": doc.page_used_heights,
        "allPagesChecked": True,
        "blankPages": blank_pages,
        "sparsePages": sparse_pages,
        "outlineSplitFallbackApplied": False,
        "font": font_name,
        "centralMessagePresent": bool(central_message),
        "summaryPresent": bool(summary),
        "outlineSectionCount": len(outline),
        "scriptureRefCount": len(scripture_refs),
        "scriptureContextCount": len(scripture_context),
        "theologicalInsightCount": len(theological_insights),
        "illustrationCount": len(illustrations),
        "pastoralDistinctionCount": len(pastoral_distinctions),
        "reflectionQuestionCount": len(reflection_questions),
        "smallGroupGuideCount": len(small_group_guide),
        "responsePrayerPresent": bool(response_prayer),
        "quoteCount": len(quotes),
        "aiAssistedSectionsLabeled": True,
        "interpretationTraceabilityComplete": interpretation_traceability_complete,
        "quoteTraceabilityComplete": quote_traceability_complete,
        "missingSourcePaths": missing_source_paths,
        "missingGlyphMarkers": missing_glyph_markers,
        "failures": failures,
    }


def interpretation_styles(font_name: str) -> dict[str, ParagraphStyle]:
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
        "callout_title": ParagraphStyle(
            "CalloutTitle",
            parent=base["Heading3"],
            fontName=font_name,
            fontSize=10.5,
            leading=15,
            textColor=colors.HexColor("#1F4E6B"),
            wordWrap="CJK",
        ),
        "central_message": ParagraphStyle(
            "CentralMessage",
            parent=base["BodyText"],
            fontName=font_name,
            fontSize=12,
            leading=19,
            textColor=colors.HexColor("#17324A"),
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
        "item_title": ParagraphStyle(
            "InterpretationItemTitle",
            parent=base["BodyText"],
            fontName=font_name,
            fontSize=11,
            leading=16.5,
            textColor=colors.HexColor("#17324A"),
            wordWrap="CJK",
            spaceAfter=2,
        ),
        "ai_label": ParagraphStyle(
            "AiAssistedLabel",
            parent=base["BodyText"],
            fontName=font_name,
            fontSize=8.2,
            leading=12,
            textColor=colors.HexColor("#66788A"),
            wordWrap="CJK",
            spaceAfter=5,
        ),
        "caution": ParagraphStyle(
            "PastoralCaution",
            parent=base["BodyText"],
            fontName=font_name,
            fontSize=9.6,
            leading=15.5,
            textColor=colors.HexColor("#65373B"),
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
    canvas_obj.drawString(MARGIN_X, 11, "证道解读 · AI 辅助整理")
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
            result.append(
                {
                    "title": title or "要点",
                    "points": points,
                    "sourceSliceIndexes": normalize_source_indexes(
                        item.get("sourceSliceIndexes")
                    ),
                }
            )
    return result


def normalize_source_indexes(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    result: list[int] = []
    for item in value:
        try:
            index = int(item)
        except (TypeError, ValueError):
            continue
        if index > 0 and index not in result:
            result.append(index)
    return result


def find_missing_or_invalid_source_paths(
    *,
    central_message: str,
    central_message_sources: list[int],
    summary: str,
    summary_sources: list[int],
    outline: list[dict[str, Any]],
    scripture_context: list[dict[str, Any]],
    theological_insights: list[dict[str, Any]],
    illustrations: list[dict[str, Any]],
    pastoral_distinctions: list[dict[str, Any]],
    reflection_questions: list[dict[str, Any]],
    small_group_guide: list[dict[str, Any]],
    response_prayer: str,
    response_prayer_sources: list[int],
    valid_slice_indexes: set[int],
) -> list[str]:
    missing: list[str] = []

    def source_is_invalid(indexes: list[int]) -> bool:
        return not indexes or any(index not in valid_slice_indexes for index in indexes)

    if central_message and source_is_invalid(central_message_sources):
        missing.append("centralMessageSourceSliceIndexes")
    if summary and source_is_invalid(summary_sources):
        missing.append("summarySourceSliceIndexes")
    for field, items in (
        ("outlineZh", outline),
        ("scriptureContextZh", scripture_context),
        ("theologicalInsightsZh", theological_insights),
        ("illustrationsZh", illustrations),
        ("pastoralDistinctionsZh", pastoral_distinctions),
        ("reflectionQuestionsZh", reflection_questions),
        ("smallGroupGuideZh", small_group_guide),
    ):
        for index, item in enumerate(items):
            if source_is_invalid(item.get("sourceSliceIndexes") or []):
                missing.append(f"{field}[{index}].sourceSliceIndexes")
    if response_prayer and source_is_invalid(response_prayer_sources):
        missing.append("responsePrayerSourceSliceIndexes")
    return missing


def normalize_sourced_items(
    value: Any,
    *,
    title_key: str,
    body_key: str,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        title = clean_text(item.get(title_key))
        body = clean_text(item.get(body_key))
        if title or body:
            result.append(
                {
                    "title": title or "要点",
                    "body": body,
                    "sourceSliceIndexes": normalize_source_indexes(
                        item.get("sourceSliceIndexes")
                    ),
                }
            )
    return result


def normalize_reflection_questions(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            question = clean_text(item.get("question") or item.get("text"))
            sources = normalize_source_indexes(item.get("sourceSliceIndexes"))
        else:
            question = clean_text(item)
            sources = []
        if question:
            result.append({"question": question, "sourceSliceIndexes": sources})
    return result


def sourced_item_flowables(
    items: list[dict[str, Any]],
    slices_by_index: dict[int, dict[str, Any]],
    styles: dict[str, ParagraphStyle],
) -> list[Any]:
    flowables: list[Any] = []
    for item in items:
        block = [
            Paragraph(escape(item["title"]), styles["item_title"]),
        ]
        if item.get("body"):
            block.append(Paragraph(escape(item["body"]), styles["body"]))
        block.extend(
            [
                Paragraph(
                    escape(source_indexes_label(item["sourceSliceIndexes"], slices_by_index)),
                    styles["evidence"],
                ),
                Spacer(1, 6),
            ]
        )
        flowables.append(KeepTogether(block))
    return flowables


def source_indexes_label(
    indexes: list[int],
    slices_by_index: dict[int, dict[str, Any]],
) -> str:
    if not indexes:
        return "证据：未提供转录切片"
    ranges: list[str] = []
    for index in indexes:
        item = slices_by_index.get(index)
        if not item:
            continue
        start = format_timestamp(int(item.get("startMs") or 0))
        end = format_timestamp(int(item.get("endMs") or 0))
        ranges.append(f"{start}-{end}")
    label = "、".join(str(index) for index in indexes)
    suffix = f" · {' / '.join(ranges)}" if ranges else ""
    return f"证据：转录切片 {label}{suffix}"


def normalize_quotes(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict) and clean_text(item.get("textZh"))]


def quote_has_exact_source(
    quote: dict[str, Any],
    *,
    slices_by_index: dict[int, dict[str, Any]],
) -> bool:
    text = clean_text(quote.get("textZh"))
    source_segment_id = clean_text(quote.get("sourceSegmentId"))
    try:
        source_slice_index = int(quote.get("sourceSliceIndex") or 0)
    except (TypeError, ValueError):
        return False
    source_slice = slices_by_index.get(source_slice_index)
    evidence_by_id = {
        clean_text(item.get("id")): item
        for item in (source_slice or {}).get("segmentEvidence") or []
        if isinstance(item, dict)
    }
    evidence = evidence_by_id.get(source_segment_id)
    evidence_text = clean_text((evidence or {}).get("textZh"))
    return bool(
        text
        and evidence_text
        and text in evidence_text
        and clean_text(quote.get("sourceTextZh")) == evidence_text
        and source_segment_id
        and quote.get("exactSourceMatch") is True
    )


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
