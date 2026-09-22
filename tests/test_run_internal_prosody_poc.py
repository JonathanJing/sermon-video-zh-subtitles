import json
from pathlib import Path
import tempfile
import unittest

from scripts import run_internal_prosody_poc as subject
from scripts.run_multilingual_prosody_poc import PLAN_SCHEMA, canonical_sha


class InternalProsodyPocTest(unittest.TestCase):
    def fixtures(self):
        anchor = {
            "schemaVersion": "sermon-sentence-anchor-manifest-v2",
            "sourceUnits": [{
                "sourceUnitId": "u1", "start": 10.0, "end": 11.7,
                "words": [
                    {"wordId": "w1", "text": "His", "start": 10.0, "end": 10.3},
                    {"wordId": "w2", "text": "roar", "start": 10.3, "end": 10.6},
                    {"wordId": "w3", "text": "wins", "start": 11.1, "end": 11.7},
                ],
            }],
        }
        base = {
            "schemaVersion": PLAN_SCHEMA,
            "targetLocale": "zh-Hans",
            "sourceWindow": {"startSeconds": 10.0, "endSeconds": 11.7, "durationSeconds": 1.7},
            "renderContract": {},
            "limitations": ["no_time_stretch"],
            "units": [{
                "unitIndex": 0, "sourceUnitId": "u1", "sourceStartSeconds": 10.0,
                "sourceEndSeconds": 11.7, "sourceSpeechDurationSeconds": 1.7,
                "sourcePauseAfterSeconds": 0.0, "assemblyPauseAfterSeconds": 0.0,
                "targetText": "他的吼声得胜。", "targetTextSha256": "unused",
                "targetDurationBudgetSeconds": 1.7, "outputRelativePath": "units/unit-0000.wav",
            }],
        }
        spec = {
            "schemaVersion": subject.SPEC_SCHEMA,
            "sourceUnitId": "u1",
            "basePlanJsonSha256": canonical_sha(base),
            "anchorManifestJsonSha256": canonical_sha(anchor),
            "wholeUnitInstruct": "重读吼声并在之后停顿。",
            "phrases": [
                {"phraseId": "p01", "targetText": "他的吼声", "sourceWordIds": ["w1", "w2"], "instruct": "重读吼声。"},
                {"phraseId": "p02", "targetText": "得胜。", "sourceWordIds": ["w3"], "instruct": "坚定收束。"},
            ],
        }
        return anchor, base, spec

    def test_prepare_derives_internal_pause_and_preserves_text(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            anchor, base, spec = self.fixtures()
            for name, value in (("anchor.json", anchor), ("base.json", base), ("spec.json", spec)):
                (root / name).write_text(json.dumps(value), encoding="utf-8")
            manifest = subject.prepare(root / "base.json", root / "anchor.json", root / "spec.json", root / "out")
            phrase = json.loads((root / "out/phrase-plan.json").read_text())
            whole = json.loads((root / "out/whole-unit-plan.json").read_text())
            self.assertAlmostEqual(manifest["derivedInternalPausesSeconds"][0], 0.5)
            self.assertEqual("".join(unit["targetText"] for unit in phrase["units"]), "他的吼声得胜。")
            self.assertEqual(whole["units"][0]["instruct"], spec["wholeUnitInstruct"])
            self.assertEqual(phrase["renderContract"]["pausePolicy"], "deterministic_copy_of_layer1_intra_unit_word_gaps")
            self.assertFalse(manifest["productionEligible"])

    def test_prepare_rejects_phrase_text_drift(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            anchor, base, spec = self.fixtures()
            spec["phrases"][1]["targetText"] = "失败。"
            for name, value in (("anchor.json", anchor), ("base.json", base), ("spec.json", spec)):
                (root / name).write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unchanged target sentence"):
                subject.prepare(root / "base.json", root / "anchor.json", root / "spec.json", root / "out")

    def test_prepare_rejects_source_word_gap(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            anchor, base, spec = self.fixtures()
            spec["phrases"][0]["sourceWordIds"] = ["w1"]
            for name, value in (("anchor.json", anchor), ("base.json", base), ("spec.json", spec)):
                (root / name).write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "cover the selected Layer 1 unit"):
                subject.prepare(root / "base.json", root / "anchor.json", root / "spec.json", root / "out")


if __name__ == "__main__":
    unittest.main()
