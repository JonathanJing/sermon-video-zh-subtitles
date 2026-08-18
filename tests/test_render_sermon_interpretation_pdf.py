import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "render_sermon_interpretation_pdf.py"
SPEC = importlib.util.spec_from_file_location("render_sermon_interpretation_pdf", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class RenderSermonInterpretationPdfTest(unittest.TestCase):
    def complete_insights(self):
        slices = [
            {
                "index": 1,
                "startMs": 0,
                "endMs": 300_000,
                "segmentEvidence": [
                    {
                        "id": "srt-0007",
                        "startMs": 133_000,
                        "endMs": 140_000,
                        "textZh": "环境改变时，我们最容易感到焦虑。",
                    }
                ],
            },
            {"index": 2, "startMs": 300_000, "endMs": 600_000},
            {"index": 3, "startMs": 600_000, "endMs": 900_000},
        ]
        return {
            "schemaVersion": 2,
            "artifactType": "sermon_interpretation",
            "sermonTitle": "在改变中信靠神",
            "speaker": "Eric Geiger",
            "sermonDate": "2026-08-09",
            "sourceLabel": "本材料基于所选直播版本；其他场次的具体措辞可能不同。",
            "slices": slices,
            "centralMessageZh": "环境会改变，但神的信实不会改变。",
            "centralMessageSourceSliceIndexes": [1, 2],
            "summaryZh": "证道说明环境变化会引发焦虑，但神借着稳定的属灵节奏提醒我们继续信靠祂。",
            "summarySourceSliceIndexes": [1, 2],
            "outlineZh": [
                {
                    "title": "变化带来的压力",
                    "points": ["生活环境变化会放大人的焦虑。"],
                    "sourceSliceIndexes": [1],
                },
                {
                    "title": "重新建立节奏",
                    "points": ["经文帮助人重新定向。"],
                    "sourceSliceIndexes": [2],
                },
                {
                    "title": "在群体中坚持",
                    "points": ["属灵群体帮助人持续信靠。"],
                    "sourceSliceIndexes": [3],
                },
            ],
            "scriptureRefs": ["腓立比书 4:6-7"],
            "scriptureContextZh": [
                {
                    "reference": "腓立比书 4:6-7",
                    "explanation": "保罗把忧虑转向祷告与神所赐的平安。",
                    "sourceSliceIndexes": [2],
                }
            ],
            "theologicalInsightsZh": [
                {
                    "title": "神的信实",
                    "explanation": "人的环境变化不改变神的性情。",
                    "sourceSliceIndexes": [1],
                },
                {
                    "title": "祷告与平安",
                    "explanation": "祷告把焦虑带到神面前。",
                    "sourceSliceIndexes": [2],
                },
            ],
            "illustrationsZh": [
                {
                    "title": "生活节奏",
                    "function": "帮助听众看见稳定操练如何承载信心。",
                    "sourceSliceIndexes": [2],
                }
            ],
            "pastoralDistinctionsZh": [
                {
                    "title": "信靠不等于否认压力",
                    "explanation": "证道承认焦虑真实存在，同时邀请听众转向神。",
                    "sourceSliceIndexes": [1, 2],
                }
            ],
            "reflectionQuestionsZh": [
                {"question": "什么变化最容易放大我的焦虑？", "sourceSliceIndexes": [1]},
                {"question": "我如何把忧虑带进祷告？", "sourceSliceIndexes": [2]},
                {"question": "谁能陪伴我建立稳定节奏？", "sourceSliceIndexes": [3]},
            ],
            "smallGroupGuideZh": [
                {"section": "读经", "guidance": "阅读重点经文。", "sourceSliceIndexes": [2]},
                {"section": "讨论", "guidance": "分享环境变化带来的压力。", "sourceSliceIndexes": [1]},
                {"section": "回应", "guidance": "彼此代祷并建立支持。", "sourceSliceIndexes": [3]},
            ],
            "responsePrayerZh": "信实的神，求你帮助我们在变化中把忧虑交托给你，并在你的平安中继续信靠。",
            "responsePrayerSourceSliceIndexes": [1, 2],
            "quotes": [
                {
                    "textZh": "环境改变时，我们最容易感到焦虑。",
                    "sourceSliceIndex": 1,
                    "sourceSegmentId": "srt-0007",
                    "sourceTextZh": "环境改变时，我们最容易感到焦虑。",
                    "sourceTextEn": "We are most anxious when our context changes.",
                    "startMs": 133_000,
                    "endMs": 140_000,
                    "exactSourceMatch": True,
                }
            ],
            "traceability": {
                "allInterpretationItemsHaveSource": True,
                "missingSourcePaths": [],
                "allQuotesHaveSource": True,
                "allQuotesAreExactExcerpts": True,
            },
        }

    def test_renders_traceable_sermon_interpretation(self):
        insights = self.complete_insights()
        with tempfile.TemporaryDirectory() as tempdir:
            out = Path(tempdir) / "sermon_interpretation_zh.pdf"
            qa = mod.render_interpretation_pdf(insights, out)

            self.assertTrue(out.read_bytes().startswith(b"%PDF"))
            self.assertGreater(out.stat().st_size, 500)
            self.assertEqual(qa["status"], "pass")
            self.assertTrue(qa["allPagesChecked"])
            self.assertTrue(qa["aiAssistedSectionsLabeled"])
            self.assertTrue(qa["interpretationTraceabilityComplete"])
            self.assertEqual(3, qa["reflectionQuestionCount"])
            self.assertEqual(3, qa["smallGroupGuideCount"])
            self.assertTrue(qa["responsePrayerPresent"])
            self.assertGreaterEqual(qa["pageCount"], 1)

    def test_qa_rejects_missing_interpretation_traceability(self):
        insights = self.complete_insights()
        insights["traceability"] = {
            "allInterpretationItemsHaveSource": False,
            "missingSourcePaths": ["reflectionQuestionsZh[0].sourceSliceIndexes"],
        }
        with tempfile.TemporaryDirectory() as tempdir:
            qa = mod.render_interpretation_pdf(insights, Path(tempdir) / "interpretation.pdf")

        self.assertEqual(qa["status"], "needs_review")
        self.assertIn("interpretation_traceability_incomplete", qa["failures"])
        self.assertIn(
            "reflectionQuestionsZh[0].sourceSliceIndexes",
            qa["missingSourcePaths"],
        )

    def test_qa_recomputes_traceability_instead_of_trusting_declared_flags(self):
        insights = self.complete_insights()
        insights["reflectionQuestionsZh"][0]["sourceSliceIndexes"] = [999]
        insights["traceability"] = {
            "allInterpretationItemsHaveSource": True,
            "missingSourcePaths": [],
            "allQuotesHaveSource": True,
            "allQuotesAreExactExcerpts": True,
        }
        with tempfile.TemporaryDirectory() as tempdir:
            qa = mod.render_interpretation_pdf(insights, Path(tempdir) / "interpretation.pdf")

        self.assertEqual(qa["status"], "needs_review")
        self.assertFalse(qa["interpretationTraceabilityComplete"])
        self.assertIn("interpretation_traceability_incomplete", qa["failures"])
        self.assertIn(
            "reflectionQuestionsZh[0].sourceSliceIndexes",
            qa["missingSourcePaths"],
        )

    def test_qa_rejects_quote_without_exact_valid_source(self):
        insights = self.complete_insights()
        insights["quotes"][0]["sourceSliceIndex"] = 999
        insights["traceability"]["allQuotesHaveSource"] = True
        insights["traceability"]["allQuotesAreExactExcerpts"] = True
        with tempfile.TemporaryDirectory() as tempdir:
            qa = mod.render_interpretation_pdf(insights, Path(tempdir) / "interpretation.pdf")

        self.assertEqual(qa["status"], "needs_review")
        self.assertFalse(qa["quoteTraceabilityComplete"])
        self.assertIn("quote_traceability_incomplete", qa["failures"])

    def test_long_outline_can_cross_pages_without_wasting_a_page(self):
        insights = self.complete_insights()
        insights["outlineZh"][0]["points"] = [
            f"第{index}点：" + "这是用于验证跨页排版与证据同行关系的完整中文说明。" * 3
            for index in range(8)
        ]
        with tempfile.TemporaryDirectory() as tempdir:
            qa = mod.render_interpretation_pdf(
                insights,
                Path(tempdir) / "interpretation.pdf",
            )

        self.assertEqual(qa["status"], "pass")
        self.assertEqual(qa["pageCount"], 3)
        self.assertEqual(qa["sparsePages"], [])
        self.assertFalse(qa["outlineSplitFallbackApplied"])

    def test_long_outline_falls_back_when_split_layout_would_be_sparse(self):
        insights = self.complete_insights()
        insights["outlineZh"][0]["points"] = [
            f"第{index}点：" + "这是用于验证跨页排版与证据同行关系的完整中文说明。" * 3
            for index in range(10)
        ]
        with tempfile.TemporaryDirectory() as tempdir:
            qa = mod.render_interpretation_pdf(
                insights,
                Path(tempdir) / "interpretation.pdf",
            )

        self.assertEqual(qa["status"], "pass")
        self.assertEqual(qa["sparsePages"], [])
        self.assertTrue(qa["outlineSplitFallbackApplied"])

    def test_cli_writes_pdf_and_qa(self):
        insights = self.complete_insights()
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            source = root / "insights.json"
            out = root / "interpretation.pdf"
            qa_out = root / "interpretation.qa.json"
            source.write_text(json.dumps(insights, ensure_ascii=False), encoding="utf-8")
            old_argv = sys.argv
            try:
                sys.argv = [str(SCRIPT_PATH), "--input", str(source), "--out", str(out), "--qa-out", str(qa_out)]
                self.assertEqual(mod.main(), 0)
            finally:
                sys.argv = old_argv

            qa = json.loads(qa_out.read_text(encoding="utf-8"))

        self.assertEqual(qa["status"], "pass")


if __name__ == "__main__":
    unittest.main()
