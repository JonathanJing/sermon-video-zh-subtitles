import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import wave

from scripts import run_multilingual_prosody_poc as subject


def canonical(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def write_wav(path: Path, seconds: float, rate: int = 8000):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b"\x01\x00" * round(seconds * rate))


class ProsodyPocTest(unittest.TestCase):
    def fixtures(self):
        anchor = {
            "schemaVersion": "sermon-sentence-anchor-manifest-v2",
            "sourceUnits": [
                {"sourceUnitId": "u1", "start": 10.0, "end": 10.5, "boundary": {"pauseAfterSeconds": 0.2}},
                {"sourceUnitId": "u2", "start": 10.7, "end": 10.95, "boundary": {"pauseAfterSeconds": 4.0}},
            ],
        }
        candidate = {
            "schemaVersion": "sermon-target-language-candidate-v2",
            "targetLocale": "ko",
            "anchorManifestSha256": canonical(anchor),
            "groups": [{
                "sourceUnitIds": ["u1", "u2"],
                "targetUtterances": ["첫째.", "둘째."],
                "coverage": [
                    {"sourceUnitId": "u1", "targetText": "첫째."},
                    {"sourceUnitId": "u2", "targetText": "둘째."},
                ],
            }],
        }
        return anchor, candidate

    def test_prepare_preserves_source_pause_but_drops_trailing_pause(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            anchor, candidate = self.fixtures()
            anchor_path, candidate_path, plan_path = root / "anchor.json", root / "candidate.json", root / "plan.json"
            anchor_path.write_text(json.dumps(anchor))
            candidate_path.write_text(json.dumps(candidate))
            plan = subject.prepare(anchor_path, candidate_path, plan_path)
            self.assertEqual([row["assemblyPauseAfterSeconds"] for row in plan["units"]], [0.2, 0.0])
            self.assertEqual(plan["renderContract"]["emphasisPolicy"], "out_of_scope_for_minimal_poc")
            self.assertNotIn("instruct", plan["units"][0])
            self.assertFalse(plan["productionEligible"])

    def test_assemble_uses_measured_units_and_deterministic_silence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            anchor, candidate = self.fixtures()
            anchor_path, candidate_path, plan_path = root / "anchor.json", root / "candidate.json", root / "plan.json"
            anchor_path.write_text(json.dumps(anchor))
            candidate_path.write_text(json.dumps(candidate))
            subject.prepare(anchor_path, candidate_path, plan_path)
            units = root / "render"
            write_wav(units / "units/unit-0000.wav", 0.4)
            write_wav(units / "units/unit-0001.wav", 0.3)
            manifest = subject.assemble(plan_path, units, root / "assembled")
            schedule = json.loads((root / "assembled/schedule.json").read_text())
            self.assertAlmostEqual(schedule["trackDurationSeconds"], 0.9, places=3)
            self.assertAlmostEqual(schedule["units"][0]["insertedPauseSeconds"], 0.2, places=3)
            self.assertAlmostEqual(schedule["units"][1]["speechEndLagSeconds"], -0.05, places=3)
            self.assertEqual(manifest["status"], "assembled_and_fully_decoded_human_review_pending")
            self.assertEqual(manifest["fullDecode"], "pass")

    def test_prepare_rejects_candidate_bound_to_other_anchor(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            anchor, candidate = self.fixtures()
            candidate["anchorManifestSha256"] = "0" * 64
            anchor_path, candidate_path = root / "anchor.json", root / "candidate.json"
            anchor_path.write_text(json.dumps(anchor))
            candidate_path.write_text(json.dumps(candidate))
            with self.assertRaisesRegex(ValueError, "another anchor"):
                subject.prepare(anchor_path, candidate_path, root / "plan.json")

    def test_tune_uses_same_model_pace_instructions_only_outside_tolerance(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            anchor, candidate = self.fixtures()
            anchor_path, candidate_path, plan_path = root / "anchor.json", root / "candidate.json", root / "plan.json"
            anchor_path.write_text(json.dumps(anchor))
            candidate_path.write_text(json.dumps(candidate))
            subject.prepare(anchor_path, candidate_path, plan_path)
            schedule = {
                "schemaVersion": "sermon-target-language-prosody-poc-schedule-v1",
                "units": [
                    {"sourceUnitId": "u1", "speechDurationDeltaSeconds": 0.7},
                    {"sourceUnitId": "u2", "speechDurationDeltaSeconds": -0.2},
                ],
            }
            schedule_path = root / "schedule.json"
            schedule_path.write_text(json.dumps(schedule))
            tuned = subject.tune(plan_path, schedule_path, root / "tuned.json")
            self.assertIn("slightly faster", tuned["units"][0]["instruct"])
            self.assertNotIn("instruct", tuned["units"][1])
            self.assertEqual(tuned["renderContract"]["pacePolicy"], "same_model_duration_feedback_instruction_v1")


if __name__ == "__main__":
    unittest.main()
