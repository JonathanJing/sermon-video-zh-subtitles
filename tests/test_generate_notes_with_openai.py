import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "generate_notes_with_openai.py"
SPEC = importlib.util.spec_from_file_location("generate_notes_with_openai", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class GenerateNotesWithOpenAITest(unittest.TestCase):
    def test_parses_chinese_srt_as_note_segments(self):
        srt = """1
00:00:01,000 --> 00:00:04,500
今天我们看见神的怜悯。

2
00:05:02.250 --> 00:05:08.000
<i>基督站在我们中间</i>
成为我们的中保。
"""

        segments = mod.segments_from_srt(srt, lang="zh")
        slices = mod.build_note_slices(segments)

        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0]["id"], "srt-0001")
        self.assertEqual(segments[0]["startMs"], 1000)
        self.assertEqual(segments[1]["startMs"], 302_250)
        self.assertEqual(segments[1]["endMs"], 308_000)
        self.assertEqual(segments[1]["zh"], "基督站在我们中间 成为我们的中保。")
        self.assertEqual(slices[0]["segmentIds"], ["srt-0001", "srt-0002"])
        self.assertIn("今天我们看见神的怜悯", slices[0]["text"])

    def test_parses_english_srt_as_source_text_for_chinese_notes(self):
        srt = """1
00:00:10,000 --> 00:00:14,000
Jesus is our mediator.
"""

        segments = mod.segments_from_srt(srt, lang="en")
        slices = mod.build_note_slices(segments)

        self.assertEqual(segments[0]["en"], "Jesus is our mediator.")
        self.assertNotIn("zh", segments[0])
        self.assertEqual(slices[0]["text"], "Jesus is our mediator.")

    def test_builds_time_and_char_bounded_note_slices(self):
        long_text = "这是一段很长的证道字幕，用来测试字数兜底。" * 90
        segments = [
            {"id": "seg_1", "startMs": 0, "endMs": 10_000, "zh": "开场提出今天的主题。"},
            {"id": "seg_2", "startMs": 310_000, "endMs": 320_000, "zh": "五分钟后进入第二段。"},
            {"id": "seg_3", "startMs": 321_000, "endMs": 330_000, "zh": long_text},
        ]

        slices = mod.build_note_slices(segments)

        self.assertGreaterEqual(len(slices), 2)
        self.assertEqual(slices[0]["segmentIds"], ["seg_1", "seg_2"])
        self.assertLessEqual(max(item["charCount"] for item in slices), mod.NOTE_SLICE_MAX_CHARS)

    def test_openai_request_uses_configured_model_and_reasoning(self):
        slices = [
            {
                "index": 1,
                "startMs": 0,
                "endMs": 10_000,
                "text": "耶稣是我们的中保。",
                "charCount": 9,
                "segmentIds": ["seg_1"],
                "refs": ["Numbers 16"],
            }
        ]

        payload = mod.build_openai_request(
            slices=slices,
            simulation={"sermonTitle": "Test Sermon"},
            model="gpt-5.4-mini",
            reasoning_effort="medium",
        )

        self.assertEqual(payload["model"], "gpt-5.4-mini")
        self.assertEqual(payload["reasoning"], {"effort": "medium"})
        self.assertEqual(payload["text"]["format"]["type"], "json_object")
        self.assertIn("human church review", payload["input"][0]["content"][0]["text"])
        self.assertIn("empty arrays", payload["input"][1]["content"][0]["text"])
        rendered = json.dumps(payload, ensure_ascii=False)
        self.assertIn("reflectionQuestionsZh", rendered)
        self.assertIn("smallGroupGuideZh", rendered)
        self.assertIn("responsePrayerZh", rendered)
        self.assertIn("sourceSliceIndexes", rendered)

    def test_normalizes_insights_without_secret_material(self):
        insights = mod.normalize_insights(
            {
                "centralMessageZh": "基督担当我们的罪，使相信的人得赦免。",
                "centralMessageSourceSliceIndexes": [1],
                "summaryZh": "证道强调基督的怜悯。",
                "summarySourceSliceIndexes": [1],
                "outlineZh": [
                    {
                        "title": "中保",
                        "points": ["亚伦代求", "基督成全"],
                        "sourceSliceIndexes": [1],
                    }
                ],
                "scriptureRefs": ["民数记 16"],
                "scriptureContextZh": [
                    {
                        "reference": "民数记 16",
                        "explanation": "中保站在死亡与生命之间。",
                        "sourceSliceIndexes": [1],
                    }
                ],
                "theologicalInsightsZh": [
                    {
                        "title": "基督是中保",
                        "explanation": "基督成全人无法完成的救赎。",
                        "sourceSliceIndexes": [1],
                    }
                ],
                "illustrationsZh": [],
                "pastoralDistinctionsZh": [
                    {
                        "title": "赦免与责任",
                        "explanation": "领受恩典不等于否认责任。",
                        "sourceSliceIndexes": [1],
                    }
                ],
                "reflectionQuestionsZh": [
                    {
                        "question": "我是否仍在靠自己的表现换取接纳？",
                        "sourceSliceIndexes": [1],
                    }
                ],
                "smallGroupGuideZh": [
                    {
                        "section": "读经",
                        "guidance": "阅读本段经文并观察中保的角色。",
                        "sourceSliceIndexes": [1],
                    }
                ],
                "responsePrayerZh": "神啊，求你帮助我信靠基督已经完成的工作。",
                "responsePrayerSourceSliceIndexes": [1],
                "quotes": [
                    {
                        "textZh": "我们需要一位站在死亡和生命之间的中保。",
                        "sourceSliceIndex": 1,
                        "sourceSegmentId": "seg_1",
                    }
                ],
            },
            slices=[
                {
                    "index": 1,
                    "startMs": 0,
                    "endMs": 10_000,
                    "text": "我们需要一位站在死亡和生命之间的中保。",
                    "charCount": 20,
                    "segmentIds": ["seg_1"],
                    "segmentEvidence": [
                        {
                            "id": "seg_1",
                            "startMs": 0,
                            "endMs": 10_000,
                            "textZh": "我们需要一位站在死亡和生命之间的中保。",
                            "textEn": "We need a mediator who stands between death and life.",
                        }
                    ],
                    "refs": [],
                }
            ],
            simulation={"translationStatus": "ready", "segments": [{"id": "seg_1"}]},
            model="gpt-5.4-mini",
            reasoning_effort="medium",
            api_key_secret="projects/p/secrets/openai-api-key/versions/latest",
        )
        rendered = json.dumps(insights, ensure_ascii=False)

        self.assertEqual(insights["model"], "gpt-5.4-mini")
        self.assertEqual(insights["reasoningEffort"], "medium")
        self.assertTrue(insights["traceability"]["allQuotesHaveSource"])
        self.assertTrue(insights["traceability"]["allQuotesAreExactExcerpts"])
        self.assertTrue(insights["traceability"]["allInterpretationItemsHaveSource"])
        self.assertEqual([], insights["traceability"]["missingSourcePaths"])
        self.assertEqual(insights["quotes"][0]["sourceSegmentId"], "seg_1")
        self.assertEqual(insights["quotes"][0]["sourceTextEn"], "We need a mediator who stands between death and life.")
        self.assertEqual(
            "我是否仍在靠自己的表现换取接纳？",
            insights["reflectionQuestionsZh"][0]["question"],
        )
        self.assertEqual([1], insights["responsePrayerSourceSliceIndexes"])
        self.assertNotIn("apiKeySecret", rendered)
        self.assertNotIn("projects/p/secrets", rendered)
        self.assertFalse(insights["apiKeyMaterialIncluded"])
        self.assertFalse(insights["secretResourceNamesIncluded"])

    def test_normalization_flags_interpretation_items_without_valid_sources(self):
        insights = mod.normalize_insights(
            {
                "centralMessageZh": "核心信息。",
                "centralMessageSourceSliceIndexes": [999],
                "summaryZh": "摘要。",
                "summarySourceSliceIndexes": [1],
                "outlineZh": [
                    {
                        "title": "要点",
                        "points": ["内容"],
                        "sourceSliceIndexes": [],
                    }
                ],
                "responsePrayerZh": "回应祷告。",
                "responsePrayerSourceSliceIndexes": [],
            },
            slices=[
                {
                    "index": 1,
                    "startMs": 0,
                    "endMs": 10_000,
                    "text": "证道内容。",
                    "charCount": 5,
                    "segmentIds": ["seg_1"],
                    "segmentEvidence": [],
                    "refs": [],
                }
            ],
            simulation={"segments": [{"id": "seg_1"}]},
            model="gpt-5.6",
            reasoning_effort="high",
            api_key_secret="",
        )

        self.assertFalse(insights["traceability"]["allInterpretationItemsHaveSource"])
        self.assertIn(
            "centralMessageSourceSliceIndexes",
            insights["traceability"]["missingSourcePaths"],
        )
        self.assertIn(
            "outlineZh[0].sourceSliceIndexes",
            insights["traceability"]["missingSourcePaths"],
        )
        self.assertIn(
            "responsePrayerSourceSliceIndexes",
            insights["traceability"]["missingSourcePaths"],
        )

    def test_drops_paraphrased_or_misattributed_quote(self):
        slices = [
            {
                "index": 1,
                "startMs": 0,
                "endMs": 10_000,
                "text": "神爱世人。",
                "charCount": 5,
                "segmentIds": ["seg_1"],
                "segmentEvidence": [
                    {
                        "id": "seg_1",
                        "startMs": 0,
                        "endMs": 10_000,
                        "textZh": "神爱世人。",
                        "textEn": "God loved the world.",
                    }
                ],
                "refs": [],
            }
        ]

        quotes = mod.normalize_quotes(
            [
                {"textZh": "神非常爱全世界。", "sourceSliceIndex": 1, "sourceSegmentId": "seg_1"},
                {"textZh": "神爱世人。", "sourceSliceIndex": 1, "sourceSegmentId": "wrong"},
            ],
            slices,
        )

        self.assertEqual(quotes, [])

    def test_drops_quote_with_malformed_source_slice_index(self):
        quotes = mod.normalize_quotes(
            [
                {
                    "textZh": "神爱世人。",
                    "sourceSliceIndex": "slice-one",
                    "sourceSegmentId": "seg_1",
                }
            ],
            [
                {
                    "index": 1,
                    "segmentEvidence": [
                        {
                            "id": "seg_1",
                            "startMs": 0,
                            "endMs": 10_000,
                            "textZh": "神爱世人。",
                        }
                    ],
                }
            ],
        )

        self.assertEqual(quotes, [])

    def test_merges_aligned_bilingual_srt_segments(self):
        primary = [{"id": "srt-0001", "startMs": 1000, "endMs": 3000, "zh": "神爱世人。"}]
        secondary = [{"id": "srt-0001", "startMs": 1000, "endMs": 3000, "en": "God loved the world."}]

        merged = mod.merge_aligned_segments(primary, secondary)
        slices = mod.build_note_slices(merged)

        self.assertEqual(merged[0]["zh"], "神爱世人。")
        self.assertEqual(merged[0]["en"], "God loved the world.")
        self.assertEqual(slices[0]["segmentEvidence"][0]["textEn"], "God loved the world.")

    def test_updates_manifest_with_insight_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "cloud-manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "apiKeyMaterialIncluded": False,
                        "secretResourceNamesIncluded": False,
                        "outputs": [{"localPath": "web/playback-simulation.generated.js", "gcsUri": "gs://b/p/web/playback-simulation.generated.js"}],
                    }
                ),
                encoding="utf-8",
            )
            mod.update_run_manifest(
                manifest_path=manifest,
                uploads=[
                    {"localPath": "insights/openai-notes.json", "gcsUri": "gs://b/p/insights/openai-notes.json"},
                    {"localPath": "model-output/openai-notes-output.jsonl", "gcsUri": "gs://b/p/model-output/openai-notes-output.jsonl"},
                ],
                insights={"status": "ready", "model": "gpt-5.4-mini", "reasoningEffort": "medium"},
                gcs_bucket=None,
                gcs_prefix="p",
            )
            updated = json.loads(manifest.read_text(encoding="utf-8"))

        local_paths = {item["localPath"] for item in updated["outputs"]}
        self.assertIn("insights/openai-notes.json", local_paths)
        self.assertEqual(updated["insightsProvider"]["model"], "gpt-5.4-mini")
        self.assertEqual(updated["insightsProvider"]["reasoningEffort"], "medium")
        self.assertFalse(updated["secretResourceNamesIncluded"])


if __name__ == "__main__":
    unittest.main()
