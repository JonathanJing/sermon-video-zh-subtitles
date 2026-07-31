import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.build_sermon_reading_edition_with_openai import (
    build_sentence_units,
    build_semantic_blocks,
    draft_comparison_report,
    edit_batch,
    parse_json_message,
    reading_quality_report,
    write_block_srt,
)


class ReadingEditionTest(unittest.TestCase):
    def test_sentence_units_split_multiple_sentences_inside_one_segment(self):
        units = build_sentence_units(
            [
                {
                    "id": 0,
                    "start": 0.0,
                    "end": 10.0,
                    "text": "First sentence. Second sentence.",
                }
            ]
        )
        self.assertEqual(2, len(units))
        self.assertEqual("First sentence.", units[0]["en"])
        self.assertEqual("Second sentence.", units[1]["en"])
        self.assertLess(units[0]["end"], units[1]["end"])

    def test_semantic_blocks_wait_for_sentence_end(self):
        english = [
            {"id": 0, "start": 0.0, "end": 30.0, "text": "This sentence"},
            {"id": 1, "start": 30.0, "end": 50.0, "text": "continues here."},
            {"id": 2, "start": 50.0, "end": 100.0, "text": "A second sentence ends."},
        ]
        chinese = [
            {"id": 0, "zh": "这句话"},
            {"id": 1, "zh": "在这里继续。"},
            {"id": 2, "zh": "第二句话结束。"},
        ]
        blocks = build_semantic_blocks(
            english,
            chinese,
            preferred_seconds=40,
            preferred_english_chars=900,
            hard_seconds=120,
            hard_english_chars=1900,
        )
        self.assertEqual(2, len(blocks))
        self.assertEqual([0, 1], blocks[0]["segmentIds"])
        self.assertTrue(blocks[0]["en"].endswith("."))

    def test_compact_semantic_blocks_support_two_pairs_per_mobile_page(self):
        sentence = "This sentence carries one complete sermon thought for bilingual reading. "
        english = [
            {
                "id": index,
                "start": index * 10.0,
                "end": (index + 1) * 10.0,
                "text": sentence.strip(),
            }
            for index in range(6)
        ]
        chinese = [{"id": index, "zh": "这是一个完整的证道意思。"} for index in range(6)]

        blocks = build_semantic_blocks(
            english,
            chinese,
            preferred_seconds=24,
            preferred_english_chars=420,
            hard_seconds=55,
            hard_english_chars=840,
        )

        self.assertEqual(2, len(blocks))
        self.assertTrue(all(len(block["en"]) < 420 for block in blocks))
        segment_ids = [segment_id for block in blocks for segment_id in block["segmentIds"]]
        self.assertEqual(list(range(6)), segment_ids)

    def test_quality_report_rejects_ellipsis_fillers_and_fragments(self):
        report = reading_quality_report(
            [
                {
                    "id": 0,
                    "en": "Complete English sentence.",
                    "zh": "你知道，这句话……",
                },
                {
                    "id": 1,
                    "en": "Another complete sentence.",
                    "zh": "另一句话，",
                },
            ]
        )
        self.assertEqual("needs_revision", report["status"])
        self.assertIn("ellipsis", report["failures"])
        self.assertIn("oral_fillers", report["failures"])
        self.assertIn("dangling_fragments", report["failures"])

    def test_quality_report_accepts_clean_reading_prose(self):
        report = reading_quality_report(
            [
                {
                    "id": 0,
                    "en": "Jesus shows us the self-giving love of God.",
                    "zh": "耶稣向我们显明神舍己的爱。",
                }
            ]
        )
        self.assertEqual("pass", report["status"])
        self.assertEqual(0, report["metrics"]["ellipsisCount"])

    def test_quality_report_allows_semantic_you_know_question(self):
        report = reading_quality_report(
            [
                {
                    "id": 0,
                    "en": "Do you know what this says? It says I had a good night's sleep.",
                    "zh": "你知道这说明什么吗？这说明我昨晚睡得很好。",
                }
            ]
        )
        self.assertEqual("pass", report["status"])
        self.assertEqual([], report["oralFillers"])
        self.assertEqual(
            "sermon-reading-edition-quality-v2",
            report["qualityRuleVersion"],
        )

    def test_quality_report_checks_terms_english_leaks_and_punctuation(self):
        report = reading_quality_report(
            [
                {
                    "id": 0,
                    "en": "Acts describes the Holy Spirit.",
                    "zh": "Acts 描述了神的工作。。",
                }
            ]
        )
        self.assertEqual("needs_revision", report["status"])
        self.assertIn("source_term_coverage", report["failures"])
        self.assertIn("unexpected_english_tokens", report["failures"])
        self.assertIn("repeated_punctuation", report["failures"])

    def test_quality_report_allows_approved_proper_nouns(self):
        report = reading_quality_report(
            [
                {
                    "id": 0,
                    "en": "Welcome to Mariners Online. Please check the sleep data on your Oura ring.",
                    "zh": "欢迎来到 Mariners Online，请查看你的 Oura 戒指。",
                }
            ]
        )
        self.assertEqual("pass", report["status"])

    def test_writes_reading_block_srt(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reading.srt"
            write_block_srt(
                path,
                [{"id": 0, "start": 0.64, "end": 5.44, "zh": "完整的一句话。"}],
                "zh",
            )
            text = path.read_text(encoding="utf-8")
            self.assertIn("00:00:00,640 --> 00:00:05,440", text)
            self.assertIn("完整的一句话。", text)

    def test_reports_improvement_from_subtitle_draft(self):
        report = draft_comparison_report(
            [{"id": 0, "zh": "你知道，这是一句……"}],
            [{"id": 0, "zh": "这是一句话。"}],
        )
        self.assertEqual(1, report["sourceSubtitleSegmentCount"])
        self.assertEqual(1, report["draftEllipsisCount"])
        self.assertEqual(0, report["finalEllipsisCount"])
        self.assertEqual(1, report["draftOralFillers"]["你知道"])
        self.assertEqual(0, report["finalOralFillers"]["你知道"])

    def test_parses_fenced_json_message(self):
        parsed = parse_json_message('```json\n{"blocks":[{"id":0,"zh":"完整。"}]}\n```')
        self.assertEqual("完整。", parsed["blocks"][0]["zh"])

    def test_reading_edit_cache_is_scoped_to_provider(self):
        blocks = [
            {
                "id": 0,
                "start": 0.0,
                "end": 5.0,
                "en": "Grace meets us here.",
                "draftZh": "恩典在这里与我们相遇。",
            }
        ]
        openai_result = {
            "model": "gpt-5.6-sol",
            "choices": [{"message": {"content": '{"blocks":[{"id":0,"zh":"恩典在此与我们相遇。"}]}'}}],
        }
        codex_result = {"blocks": [{"id": 0, "zh": "恩典就在这里与我们相遇。"}]}

        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            with mock.patch(
                "scripts.build_sermon_reading_edition_with_openai.chat_json",
                return_value=openai_result,
            ) as openai_call:
                edit_batch(
                    "key",
                    blocks,
                    blocks,
                    0,
                    root,
                    model="gpt-5.6-sol",
                    reasoning_effort="high",
                    qa_pass=False,
                    provider="openai",
                    codex_cli=root / "codex",
                    schema_path=root / "schema.json",
                )
            with mock.patch(
                "scripts.build_sermon_reading_edition_with_openai.codex_json",
                return_value=codex_result,
            ) as codex_call:
                edit_batch(
                    "key",
                    blocks,
                    blocks,
                    0,
                    root,
                    model="gpt-5.6-sol",
                    reasoning_effort="high",
                    qa_pass=False,
                    provider="codex",
                    codex_cli=root / "codex",
                    schema_path=root / "schema.json",
                )

        openai_call.assert_called_once()
        codex_call.assert_called_once()


if __name__ == "__main__":
    unittest.main()
