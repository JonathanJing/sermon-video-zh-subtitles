import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "sermon_pipeline.py"
SPEC = importlib.util.spec_from_file_location("sermon_pipeline", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class SermonPipelineTest(unittest.TestCase):
    def test_load_glossary_accepts_zh_terms_alias(self):
        with tempfile.TemporaryDirectory() as tempdir:
            glossary_path = Path(tempdir) / "glossary.json"
            glossary_path.write_text(
                '{"terms":["Numbers","Moses"],"zhTerms":{"Numbers":"民数记","Moses":"摩西"}}',
                encoding="utf-8",
            )

            glossary = mod.load_glossary(glossary_path)

        self.assertEqual(glossary["terms"], ["Numbers", "Moses"])
        self.assertEqual(glossary["zh_term_map"]["Numbers"], "民数记")
        self.assertEqual(glossary["zh_term_map"]["Moses"], "摩西")

    def test_normalize_zh_terms_replaces_bible_terms(self):
        glossary = {"terms": ["Numbers", "Moses"], "zh_term_map": {"Numbers": "民数记", "Moses": "摩西"}}

        result = mod.normalize_zh_terms("Numbers 里 Moses 的故事", glossary)

        self.assertEqual(result, "民数记 里 摩西 的故事")

    def test_shape_durations_clamps_overlaps_and_short_segments(self):
        shaped = mod.shape_durations(
            [
                {"id": 7, "start": 0.0, "end": 0.4, "text": "A"},
                {"id": 8, "start": 0.8, "end": 2.0, "text": "B"},
            ]
        )

        self.assertEqual([item["id"] for item in shaped], [0, 1])
        self.assertLessEqual(shaped[0]["end"], shaped[1]["start"])
        self.assertGreaterEqual(shaped[1]["end"] - shaped[1]["start"], 1.0)

    def test_qa_report_counts_hard_failures(self):
        en_segments = [
            {"id": 0, "start": 0.0, "end": 2.0, "text": "Moses speaks."},
            {"id": 1, "start": 1.5, "end": 3.0, "text": ""},
        ]
        zh_segments = [
            {"id": 0, "start": 0.0, "end": 2.0, "text": "Moses speaks.", "zh": "Moses 说话。"},
            {"id": 2, "start": 1.5, "end": 3.0, "text": "", "zh": ""},
        ]
        glossary = {"terms": ["Moses"], "zh_term_map": {"Moses": "摩西"}}

        report = mod.qa_report(en_segments, zh_segments, glossary)

        self.assertEqual(report["hardFailures"]["emptyEnglish"], 1)
        self.assertEqual(report["hardFailures"]["emptyChinese"], 1)
        self.assertEqual(report["hardFailures"]["overlaps"], 1)
        self.assertEqual(report["hardFailures"]["translationIdMismatchCount"], 1)
        self.assertEqual(report["latinBibleTermWarnings"][0]["term"], "Moses")


if __name__ == "__main__":
    unittest.main()
