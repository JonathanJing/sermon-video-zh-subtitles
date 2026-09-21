import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("sentence_translation_map", HERE / "sentence_translation_map.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def segment(text, start, end):
    words = text.split()
    step = (end - start) / len(words)
    return {
        "text": text,
        "timingQuality": "mfa_word_aligned",
        "requires_operator_review": True,
        "wordTimes": [
            {"text": word, "start": start + index * step, "end": start + (index + 1) * step}
            for index, word in enumerate(words)
        ],
    }


class SentenceTranslationMapTests(unittest.TestCase):
    def paths(self):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        segments = root / "segments.json"
        spec = root / "spec.json"
        segments.write_text("[]\n", encoding="utf-8")
        spec.write_text("{}\n", encoding="utf-8")
        return temporary, segments, spec

    def base_spec(self):
        return {
            "sampleId": "sample",
            "sourceId": "source",
            "sourceSha256": "a" * 64,
            "sermonSourceStartSeconds": 100.0,
            "clipSourceStartSeconds": 110.0,
            "translationGroups": [{
                "translationGroupId": "g1",
                "sourceSentenceIndexes": [0, 1],
                "chinese": "第一句。第二句。",
                "coverage": [
                    {"sourceSentenceIndex": 0, "targetText": "第一句。"},
                    {"sourceSentenceIndex": 1, "targetText": "第二句。"},
                ],
                "measuredChineseAudio": {
                    "cueId": 1,
                    "currentCueStart": 2.0,
                    "currentCueEnd": 5.0,
                    "text": "第一句。第二句。",
                },
            }],
        }

    def test_structural_pass_and_reanchored_fit(self):
        temporary, segments_path, spec_path = self.paths()
        self.addCleanup(temporary.cleanup)
        segments = [segment("One sentence.", 0.5, 2.5), segment("Second sentence.", 3.0, 5.0)]
        spec = self.base_spec()
        segments_path.write_text(json.dumps(segments), encoding="utf-8")
        spec_path.write_text(json.dumps(spec), encoding="utf-8")
        report = MODULE.build_report(segments, spec, segments_path=segments_path, spec_path=spec_path)
        self.assertTrue(report["structuralPass"])
        self.assertFalse(report["semanticCoverageProven"])
        group = report["translationGroups"][0]
        self.assertEqual(group["sourceWindow"]["availableSeconds"], 4.5)
        self.assertEqual(group["measuredChineseAudio"]["durationSeconds"], 3.0)
        self.assertTrue(group["sentenceAnchoredPlan"]["fitsAtMeasuredNaturalRate"])

    def test_missing_source_assignment_fails_closed(self):
        temporary, segments_path, spec_path = self.paths()
        self.addCleanup(temporary.cleanup)
        segments = [segment("One sentence.", 0.5, 2.5), segment("Second sentence.", 3.0, 5.0)]
        spec = self.base_spec()
        spec["translationGroups"][0]["sourceSentenceIndexes"] = [0]
        spec["translationGroups"][0]["coverage"] = [{"sourceSentenceIndex": 0, "targetText": "第一句。"}]
        segments_path.write_text(json.dumps(segments), encoding="utf-8")
        spec_path.write_text(json.dumps(spec), encoding="utf-8")
        report = MODULE.build_report(segments, spec, segments_path=segments_path, spec_path=spec_path)
        self.assertFalse(report["structuralPass"])
        self.assertIn("target_sentence_assignment_not_exact", {issue["type"] for issue in report["issues"]})

    def test_audio_overflow_fails_closed(self):
        temporary, segments_path, spec_path = self.paths()
        self.addCleanup(temporary.cleanup)
        segments = [segment("One sentence.", 0.5, 1.5), segment("Second sentence.", 2.0, 3.0)]
        spec = self.base_spec()
        spec["translationGroups"][0]["measuredChineseAudio"]["currentCueEnd"] = 7.0
        segments_path.write_text(json.dumps(segments), encoding="utf-8")
        spec_path.write_text(json.dumps(spec), encoding="utf-8")
        report = MODULE.build_report(segments, spec, segments_path=segments_path, spec_path=spec_path)
        self.assertFalse(report["structuralPass"])
        self.assertIn("measured_chinese_audio_exceeds_source_window", {issue["type"] for issue in report["issues"]})


if __name__ == "__main__":
    unittest.main()
