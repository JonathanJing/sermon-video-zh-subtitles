import json
from pathlib import Path
import tempfile
import unittest

from jsonschema import Draft202012Validator

from scripts import prepare_sentence_interpretation_shadow as subject


def write_segments(path: Path, *, long_without_boundary: bool = False) -> None:
    words = ["Do", "not", "be", "afraid."]
    if long_without_boundary:
        words = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
    timed = []
    cursor = 0.0
    for word in words:
        timed.append({"text": word, "start": cursor, "end": cursor + 0.8})
        cursor += 0.9
    payload = [{
        "id": 0,
        "referenceChunkId": "block-00",
        "text": " ".join(words),
        "start": timed[0]["start"],
        "end": timed[-1]["end"],
        "sentenceBoundarySource": "frozen_reference_punctuation",
        "wordTimes": timed,
    }]
    path.write_text(json.dumps(payload), encoding="utf-8")


class SentenceInterpretationShadowTests(unittest.TestCase):
    def test_clean_anchor_is_immutable_and_waits_for_machine_judge(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "segments.json"
            write_segments(source)
            first = subject.prepare_shadow(source, root / "shadow")
            second = subject.prepare_shadow(source, root / "shadow")
            self.assertEqual(first, second)
            self.assertEqual(first["status"], "waiting_machine_judge")
            self.assertEqual(first["layer"], "shared_english_source_and_anchors")
            self.assertEqual(first["interface"], "sermon-english-source-package-v1")
            self.assertFalse(first["productionTranslationEligible"])
            self.assertFalse(first["releaseEligible"])
            self.assertFalse(first["productionOutputChanged"])
            self.assertEqual(first["humanReview"], "pending")
            manifest = json.loads(Path(first["artifacts"]["anchorManifest"]["path"]).read_text())
            self.assertEqual(manifest["schemaVersion"], "sermon-sentence-anchor-manifest-v2")
            self.assertEqual(manifest["policy"]["maxUnitSeconds"], 8.0)
            self.assertEqual(first["nextStage"], "run_english_source_machine_judge")
            self.assertNotIn("translationRequest", first["artifacts"])
            source_package = json.loads(Path(
                first["artifacts"]["englishSourcePackage"]["path"]
            ).read_text())
            self.assertEqual(source_package["status"], "blocked")
            self.assertFalse(source_package["candidateTranslationEligible"])
            package_schema = json.loads((
                Path(__file__).parents[1] / "schemas/sermon-english-source-package-v1.schema.json"
            ).read_text())
            self.assertEqual(list(Draft202012Validator(package_schema).iter_errors(source_package)), [])
            schema = json.loads((Path(__file__).parents[1] / "schemas/sermon-sentence-interpretation-shadow-v1.schema.json").read_text())
            self.assertEqual(list(Draft202012Validator(schema).iter_errors(first)), [])

    def test_unsafe_long_sentence_stops_before_model_stage(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "segments.json"
            write_segments(source, long_without_boundary=True)
            receipt = subject.prepare_shadow(source, root / "shadow", max_unit_seconds=6.0)
            self.assertEqual(receipt["status"], "waiting_anchor_review")
            self.assertEqual(receipt["nextStage"], "operator_anchor_review")
            self.assertIn("clause_unit_exceeds_target_without_safe_boundary", receipt["anchorIssueTypes"])

    def test_changed_source_uses_new_identity_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "segments.json"
            write_segments(source)
            first = subject.prepare_shadow(source, root / "shadow")
            payload = json.loads(source.read_text())
            payload[0]["wordTimes"][-1]["end"] += 0.1
            payload[0]["end"] += 0.1
            source.write_text(json.dumps(payload), encoding="utf-8")
            second = subject.prepare_shadow(source, root / "shadow")
            self.assertNotEqual(
                Path(first["artifacts"]["receipt"]["path"]).parent,
                Path(second["artifacts"]["receipt"]["path"]).parent,
            )


if __name__ == "__main__":
    unittest.main()
