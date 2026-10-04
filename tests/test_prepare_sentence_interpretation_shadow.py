import json
import hashlib
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

    def test_override_evidence_must_bind_exact_aligned_segments(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "segments.json"
            words = ["Alpha", "bravo", "charlie", "delta,", "echo", "foxtrot,",
                     "golf", "hotel", "india", "juliet."]
            timed = []
            cursor = 0.0
            for word in words:
                timed.append({"text": word, "start": cursor, "end": cursor + 0.4})
                cursor += 0.5
            source.write_text(json.dumps([{
                "id": 0, "referenceChunkId": "block-00", "text": " ".join(words),
                "start": 0.0, "end": timed[-1]["end"],
                "sentenceBoundarySource": "frozen_reference_punctuation", "wordTimes": timed,
            }]), encoding="utf-8")
            evidence = root / "boundary-overrides.json"
            payload = {"schemaVersion": "sermon-anchor-boundary-overrides-v1",
                       "alignedSegmentsSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                       "overrides": {"block-00-s001": "block-00-w0004"}}
            evidence.write_text(json.dumps(payload), encoding="utf-8")
            receipt = subject.prepare_shadow(
                source, root / "shadow", max_unit_seconds=3.0,
                boundary_overrides_path=evidence,
            )
            manifest = json.loads(Path(receipt["artifacts"]["anchorManifest"]["path"]).read_text())
            self.assertEqual(manifest["policy"]["boundaryOverrides"], payload["overrides"])
            self.assertEqual(receipt["anchorIssueCount"], 0)
            self.assertEqual(receipt["identity"]["sourceContext"]["boundaryOverridesEvidenceSha256"],
                             hashlib.sha256(evidence.read_bytes()).hexdigest())
            schema = json.loads((Path(__file__).parents[1] / "schemas/sermon-sentence-interpretation-shadow-v1.schema.json").read_text())
            self.assertEqual(list(Draft202012Validator(schema).iter_errors(receipt)), [])
            payload["alignedSegmentsSha256"] = "0" * 64
            evidence.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(ValueError):
                subject.prepare_shadow(source, root / "other", boundary_overrides_path=evidence)

    def test_v2_retain_is_source_bound_immutable_and_schema_valid(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "segments.json"
            write_segments(source, long_without_boundary=True)
            original = source.read_bytes()
            first = subject.prepare_shadow(source, root / "shadow", max_unit_seconds=4.0)
            manifest = json.loads(Path(first["artifacts"]["anchorManifest"]["path"]).read_text())
            ids = [word for u in manifest["sourceUnits"] for word in u["sourceWordIds"]]
            decision = {"action": "retain_sentence", "sourceWordIds": ids,
                        "reason": "Keep dependency intact", "evidenceRef": "judge.json#sentence-1"}
            payload = {"schemaVersion": "sermon-anchor-boundary-overrides-v2",
                       "alignedSegmentsSha256": hashlib.sha256(original).hexdigest(),
                       "overrides": {"block-00-s001": decision}}
            evidence = root / "overrides.json"
            evidence.write_text(json.dumps(payload))
            kwargs = dict(max_unit_seconds=4.0, boundary_overrides_path=evidence)
            second = subject.prepare_shadow(source, root / "shadow", **kwargs)
            self.assertEqual(second, subject.prepare_shadow(source, root / "shadow", **kwargs))
            self.assertNotEqual(first["artifacts"]["receipt"]["path"], second["artifacts"]["receipt"]["path"])
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(second["status"], "waiting_anchor_review")
            self.assertFalse(second["productionTranslationEligible"])
            self.assertEqual(second["anchorIssueCount"], 1)
            manifest = json.loads(Path(second["artifacts"]["anchorManifest"]["path"]).read_text())
            for value, name in ((payload, "sermon-anchor-boundary-overrides-v2"),
                                (manifest, "sermon-sentence-anchor-manifest-v2"),
                                (second, "sermon-sentence-interpretation-shadow-v1")):
                schema = json.loads((Path(__file__).parents[1] / "schemas" / f"{name}.schema.json").read_text())
                self.assertEqual(list(Draft202012Validator(schema).iter_errors(value)), [])
            decision["reason"] = "Revised machine evidence"
            evidence.write_text(json.dumps(payload))
            third = subject.prepare_shadow(source, root / "shadow", **kwargs)
            self.assertNotEqual(second["artifacts"]["receipt"]["path"], third["artifacts"]["receipt"]["path"])
            for invalid in ({**payload, "humanApproval": True},
                            {**payload, "alignedSegmentsSha256": "0" * 64},
                            {**payload, "overrides": {"block-00-s001": ids[0]}},
                            {**payload, "schemaVersion": "sermon-anchor-boundary-overrides-v1"}):
                evidence.write_text(json.dumps(invalid))
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    subject.prepare_shadow(source, root / "invalid", **kwargs)

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
