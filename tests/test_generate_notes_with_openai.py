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

    def test_normalizes_insights_without_secret_material(self):
        insights = mod.normalize_insights(
            {
                "summaryZh": "证道强调基督的怜悯。",
                "outlineZh": [{"title": "中保", "points": ["亚伦代求", "基督成全"]}],
                "scriptureRefs": ["民数记 16"],
                "applicationQuestionsZh": ["我如何回应神的怜悯？"],
                "quotes": [
                    {
                        "textZh": "我们需要一位站在死亡和生命之间的中保。",
                        "sourceSliceIndex": 1,
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
        self.assertEqual(insights["quotes"][0]["sourceSegmentId"], "seg_1")
        self.assertNotIn("apiKeySecret", rendered)
        self.assertNotIn("projects/p/secrets", rendered)
        self.assertFalse(insights["apiKeyMaterialIncluded"])
        self.assertFalse(insights["secretResourceNamesIncluded"])

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
