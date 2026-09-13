import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import series_terminology as names
from scripts import sermon_pipeline as pipeline
from scripts import build_sermon_reading_edition_with_openai as reading
from scripts import generate_notes_with_openai as notes


class SeriesTerminologyTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {}, clear=False)
        self.environment.start()
        os.environ.pop(names.ENV, None)

    def tearDown(self):
        self.environment.stop()

    def test_registry_contains_all_three_names_and_normalizes_title_aliases(self):
        self.assertEqual(len(names.context()["entries"]), 3)
        self.assertEqual(names.canonical_series("  WHEN LIFE DOESN'T MAKE SENSE "), "当生活令人费解")
        self.assertEqual(names.canonical_series("a-study-of-the-book-of-numbers"), "民数记研读")
        self.assertEqual(names.canonical_series("启示录系列"), "启示录：耶稣带来的安慰与盼望")
        self.assertEqual(names.canonical_series("Revelation"), "Revelation")
        self.assertEqual(names.canonical_series("历史系列"), "历史系列")

    def test_new_row_is_consumed_without_code_change(self):
        text = names.REGISTRY.read_text().replace("\n\n## 使用阶段", "\n| new-series | A New Series | 新系列 | 新系列 | user-provided | 2026-09-12 |\n\n## 使用阶段", 1)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "table.md"
            path.write_text(text)
            catalog = names.context(path)
        self.assertEqual(names.canonical_series("A New Series", catalog), "新系列")
        self.assertNotEqual(catalog["sha256"], names.context()["sha256"])

    def test_duplicate_and_conflicting_rows_fail(self):
        text = names.REGISTRY.read_text()
        row = next(line for line in text.splitlines() if line.startswith("| revelation-comfort"))
        with self.assertRaises(ValueError):
            names.parse_table(text.replace("\n\n## 使用阶段", "\n" + row + "\n\n## 使用阶段", 1))
        with self.assertRaises(ValueError):
            names.parse_table(text.replace("\n\n## 使用阶段", "\n" + row.replace("revelation-comfort-and-hope", "other-id") + "\n\n## 使用阶段", 1))

    def test_snapshot_reuses_original_version_and_restores_environment(self):
        original = names.context()
        changed = copy.deepcopy(original)
        changed["entries"][0]["chinese"] = "另一个译名"
        changed["sha256"] = names.digest({k: changed[k] for k in ("schemaVersion", "rules", "entries")})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frozen.json"
            with names.pinned_catalog(path):
                self.assertEqual(names.context(), original)
            alternate = Path(tmp) / "alternate.json"
            alternate.write_text(json.dumps(changed))
            os.environ[names.ENV] = str(alternate)
            with names.pinned_catalog(path):
                self.assertEqual(names.context(), original)
            self.assertEqual(os.environ[names.ENV], str(alternate))
            self.assertEqual(names.context(), changed)
            original["entries"][0]["chinese"] = "tampered"
            path.write_text(json.dumps(original))
            with self.assertRaises(ValueError):
                with names.pinned_catalog(path):
                    self.fail("corrupt snapshot was accepted")

    def test_glossary_keeps_custom_terms_and_context_separate_from_replacements(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "custom.json"
            path.write_text(json.dumps({"terms": ["Eric"], "zh_term_map": {"God": "神"}}))
            glossary = pipeline.load_glossary(path)
        self.assertEqual(glossary["terms"], ["Eric"])
        self.assertEqual(glossary["seriesTerminology"], names.context())
        self.assertIn("民数记研读", pipeline.glossary_lines(glossary))
        self.assertNotIn("When Life Doesn’t Make Sense", glossary["zh_term_map"])
        self.assertEqual(pipeline.normalize_zh_terms("有时生活令人费解。", glossary), "有时生活令人费解。")

    def test_editorial_passes_and_notes_receive_identical_policy(self):
        block = {"id": 1, "start": 0, "end": 5, "en": "A sermon.", "zh": "一篇证道。"}
        for qa in (False, True):
            payload = reading.request_payload([block], [block], 0, model="test", reasoning_effort="medium", qa_pass=qa)
            supplied = json.loads(payload["messages"][1]["content"])["seriesTerminology"]
            self.assertEqual(supplied, pipeline.load_glossary(None)["seriesTerminology"])
            self.assertIn(names.PROMPT_INSTRUCTION, payload["messages"][0]["content"])
        request = notes.build_openai_request([], {}, "test", "medium")
        self.assertIn(json.dumps(names.context(), ensure_ascii=False), request["input"][1]["content"][0]["text"])

    def test_explicit_titles_are_checked_without_rewriting_source(self):
        blocks = [{"id": 3, "en": 'Our series is over. Sometimes life doesn’t make sense.', "zh": "这个系列结束了。有时生活中的遭遇令人难以理解。"},
                  {"id": 4, "en": 'Read the Book of Numbers and Revelation.', "zh": "请阅读《民数记》和《启示录》。"}]
        original = copy.deepcopy(blocks)
        self.assertEqual(names.translation_issues(blocks), [])
        blocks.append({"id": 5, "en": 'Our series called "When Life Doesn’t Make Sense" starts today.', "zh": "今天开始新系列《当生活没有意义》。"})
        self.assertEqual(names.translation_issues(blocks)[0]["blockId"], 5)
        with self.assertRaises(ValueError):
            names.require_consistent(blocks)
        self.assertEqual(blocks[:2], original)
        blocks[2]["zh"] = "今天开始新系列《当生活令人费解》。"
        names.require_consistent(blocks)

    def test_reading_quality_reports_series_mismatch(self):
        blocks = [{"id": 7, "start": 0, "end": 6, "en": 'A series titled "A Study of the Book of Numbers".', "zh": "一个名为《民数记学习》的系列。"}]
        report = reading.reading_quality_report(blocks)
        self.assertIn("series_terminology", report["failures"])
        self.assertEqual(report["seriesTerminologyIssues"][0]["expectedChinese"], "民数记研读")

    def test_translation_cache_changes_with_registry_and_preserves_old_cache(self):
        glossary = pipeline.load_glossary(None)
        changed = copy.deepcopy(glossary)
        changed["seriesTerminology"]["entries"][0]["chinese"] = "修订后的标题"
        payload = {"choices": [{"message": {"content": '{"id": 1, "zh": "耶稣与你同在。"}'}}], "model": "test"}
        segments = [{"id": 1, "start": 0, "end": 5, "text": "Jesus is with you."}]
        with tempfile.TemporaryDirectory() as tmp, patch.object(pipeline, "chat_json", return_value=payload) as request:
            out = Path(tmp)
            for terms in (glossary, glossary, changed):
                pipeline.translate_chinese("unused-test-key", segments, out, "test", terms)
            self.assertEqual(request.call_count, 2)
            self.assertEqual(len(list((out / "translation_segments").glob("*.json"))), 2)
            self.assertIn(names.PROMPT_INSTRUCTION, request.call_args.args[1]["messages"][0]["content"])


if __name__ == "__main__":
    unittest.main()
