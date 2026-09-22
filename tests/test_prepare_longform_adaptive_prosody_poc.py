import json
from pathlib import Path
import tempfile
import unittest

from scripts import prepare_longform_adaptive_prosody_poc as subject
from scripts.run_multilingual_prosody_poc import PLAN_SCHEMA, canonical_sha


class LongformAdaptivePreparationTest(unittest.TestCase):
    def test_prepares_multi_sentence_phrase_plan_without_changing_text(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base = {
                "schemaVersion": PLAN_SCHEMA, "targetLocale": "zh-Hans",
                "sourceWindow": {"startSeconds": 1.0, "endSeconds": 5.0, "durationSeconds": 4.0},
                "renderContract": {}, "limitations": [],
                "units": [
                    {"sourceUnitId": "u1", "sourceStartSeconds": 1.0, "sourceEndSeconds": 2.0, "targetText": "甲乙"},
                    {"sourceUnitId": "u2", "sourceStartSeconds": 3.0, "sourceEndSeconds": 5.0, "targetText": "丙丁"},
                ],
            }
            anchor = {
                "schemaVersion": "sermon-sentence-anchor-manifest-v2",
                "sourceUnits": [
                    {"sourceUnitId": "u1", "start": 1.0, "end": 2.0, "words": [
                        {"wordId": "w1", "start": 1.0, "end": 1.4}, {"wordId": "w2", "start": 1.5, "end": 2.0}]},
                    {"sourceUnitId": "u2", "start": 3.0, "end": 5.0, "words": [
                        {"wordId": "w3", "start": 3.0, "end": 3.5}, {"wordId": "w4", "start": 4.0, "end": 5.0}]},
                ],
            }
            spec = {
                "schemaVersion": subject.SPEC_SCHEMA,
                "basePlanJsonSha256": canonical_sha(base),
                "anchorManifestJsonSha256": canonical_sha(anchor),
                "sentences": [
                    {"sourceUnitId": "u1", "phrases": [
                        {"phraseId": "p1", "targetText": "甲", "sourceWordIds": ["w1"], "instruct": "a"},
                        {"phraseId": "p2", "targetText": "乙", "sourceWordIds": ["w2"], "instruct": "b"}]},
                    {"sourceUnitId": "u2", "phrases": [
                        {"phraseId": "p1", "targetText": "丙丁", "sourceWordIds": ["w3", "w4"], "instruct": "c"}]},
                ],
            }
            for name, value in (("base.json", base), ("anchor.json", anchor), ("spec.json", spec)):
                (root / name).write_text(json.dumps(value), encoding="utf-8")

            manifest = subject.prepare(root / "base.json", root / "anchor.json", root / "spec.json", root / "out")
            plan = json.loads((root / "out/phrase-plan.json").read_text())

            self.assertEqual(manifest["sentenceCount"], 2)
            self.assertEqual(manifest["phraseCount"], 3)
            self.assertEqual([unit["unitIndex"] for unit in plan["units"]], [0, 1, 2])
            self.assertEqual("".join(unit["targetText"] for unit in plan["units"]), "甲乙丙丁")
            self.assertEqual(plan["renderContract"]["pausePolicy"], "adaptive_source_start_anchor_fill_after_synthesis")
            self.assertFalse(plan["productionEligible"])


if __name__ == "__main__":
    unittest.main()
