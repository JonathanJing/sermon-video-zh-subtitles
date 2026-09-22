import json
from pathlib import Path
import tempfile
import unittest
import wave

from scripts import assemble_adaptive_phrase_audio as subject
from scripts.run_multilingual_prosody_poc import PLAN_SCHEMA


def write_wav(path: Path, seconds: float, rate: int = 1000):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b"\x01\x00" * round(seconds * rate))


class AdaptivePhraseAssemblyTest(unittest.TestCase):
    def plan(self):
        return {
            "schemaVersion": PLAN_SCHEMA,
            "targetLocale": "zh-Hans",
            "sourceWindow": {"startSeconds": 10.0, "endSeconds": 15.0, "durationSeconds": 5.0},
            "units": [
                {"unitIndex": 0, "sourceUnitId": "u1-p1", "parentSourceUnitId": "u1", "sourceStartSeconds": 10.0, "targetText": "第一段", "outputRelativePath": "units/p1.wav"},
                {"unitIndex": 1, "sourceUnitId": "u1-p2", "parentSourceUnitId": "u1", "sourceStartSeconds": 12.0, "targetText": "第二段", "outputRelativePath": "units/p2.wav"},
                {"unitIndex": 2, "sourceUnitId": "u1-p3", "parentSourceUnitId": "u1", "sourceStartSeconds": 14.0, "targetText": "第三段。", "outputRelativePath": "units/p3.wav"},
            ],
        }

    def test_inserts_only_enough_silence_to_hit_phrase_start_anchors(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = self.plan()
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            write_wav(root / "render/units/p1.wav", 1.5)
            write_wav(root / "render/units/p2.wav", 1.0)
            write_wav(root / "render/units/p3.wav", 1.2)
            manifest = subject.assemble(plan_path, root / "render", root / "out")
            schedule = json.loads((root / "out/schedule.json").read_text())
            self.assertEqual([row["insertedPauseBeforeSeconds"] for row in schedule["units"]], [0.0, 0.5, 1.0])
            self.assertEqual([row["startSeconds"] for row in schedule["units"]], [0.0, 2.0, 4.0])
            self.assertAlmostEqual(schedule["trackDurationSeconds"], 5.2)
            self.assertAlmostEqual(schedule["sentenceEndLagSeconds"], 0.2)
            self.assertEqual(schedule["displayText"], "第一段第二段第三段。")
            self.assertEqual(manifest["fullDecode"], "pass")

    def test_records_overrun_instead_of_negative_pause(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = self.plan()
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            write_wav(root / "render/units/p1.wav", 2.5)
            write_wav(root / "render/units/p2.wav", 2.0)
            write_wav(root / "render/units/p3.wav", 1.0)
            manifest = subject.assemble(plan_path, root / "render", root / "out")
            schedule = json.loads((root / "out/schedule.json").read_text())
            self.assertEqual(schedule["units"][1]["pauseDecision"], "overrun_no_pause")
            self.assertAlmostEqual(schedule["units"][1]["overrunBeforeSeconds"], 0.5)
            self.assertEqual(manifest["metrics"]["overrunPhraseCount"], 2)

    def test_supports_multiple_sentences_but_keeps_whole_sentence_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = self.plan()
            plan["units"][2]["sourceUnitId"] = "u2-p1"
            plan["units"][2]["parentSourceUnitId"] = "u2"
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            write_wav(root / "render/units/p1.wav", 1.5)
            write_wav(root / "render/units/p2.wav", 1.0)
            write_wav(root / "render/units/p3.wav", 1.2)

            manifest = subject.assemble(plan_path, root / "render", root / "out")
            schedule = json.loads((root / "out/schedule.json").read_text())

            self.assertEqual(schedule["parentSourceUnitIds"], ["u1", "u2"])
            self.assertNotIn("parentSourceUnitId", schedule)
            self.assertEqual([row["text"] for row in schedule["sentences"]], ["第一段第二段", "第三段。"])
            self.assertEqual([row["startSeconds"] for row in schedule["sentences"]], [0.0, 4.0])
            self.assertEqual([row["endSeconds"] for row in schedule["sentences"]], [4.0, 5.2])
            self.assertEqual(manifest["metrics"]["sentenceCount"], 2)
            self.assertEqual(manifest["metrics"]["phraseCount"], 3)

    def test_acoustic_policy_caps_pause_and_rejects_unmeasured_internal_boundary(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = self.plan()
            plan["renderContract"] = {"pausePolicy": "measured_layer1_pause_only_capped_by_source_gap"}
            plan["pauseEvidenceJsonSha256"] = "a" * 64
            plan["sourceMediaSha256"] = "b" * 64
            for unit in plan["units"][1:]:
                unit["sourcePauseEvidence"] = {
                    "classification": "supported_pause_candidate", "measuredLowEnergyOverlapSeconds": 0.4,
                }
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            write_wav(root / "render/units/p1.wav", 1.0)
            write_wav(root / "render/units/p2.wav", 2.7)
            write_wav(root / "render/units/p3.wav", 0.8)
            subject.assemble(plan_path, root / "render", root / "out")
            schedule = json.loads((root / "out/schedule.json").read_text())
            self.assertEqual([row["insertedPauseBeforeSeconds"] for row in schedule["units"]], [0.0, 0.4, 0.2])
            self.assertEqual(schedule["units"][2]["pauseDecision"], "acoustic_pause_preserved_after_overrun")

            plan["units"][1].pop("sourcePauseEvidence")
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "lacks Layer 1 pause evidence"):
                subject.assemble(plan_path, root / "render", root / "failed")

    def test_acoustic_policy_does_not_fill_extra_sentence_silence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = self.plan()
            plan["renderContract"] = {"pausePolicy": "measured_layer1_pause_only_capped_by_source_gap"}
            plan["pauseEvidenceJsonSha256"] = "a" * 64
            plan["sourceMediaSha256"] = "b" * 64
            plan["units"][1]["parentSourceUnitId"] = "u2"
            plan["units"][2]["parentSourceUnitId"] = "u2"
            plan["units"][1]["sourcePauseEvidence"] = {
                "classification": "supported_pause_candidate", "measuredLowEnergyOverlapSeconds": 0.5,
            }
            plan["units"][2]["sourcePauseEvidence"] = {
                "classification": "supported_pause_candidate", "measuredLowEnergyOverlapSeconds": 0.3,
            }
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            write_wav(root / "render/units/p1.wav", 0.8)
            write_wav(root / "render/units/p2.wav", 1.0)
            write_wav(root / "render/units/p3.wav", 0.8)
            subject.assemble(plan_path, root / "render", root / "out")
            schedule = json.loads((root / "out/schedule.json").read_text())
            self.assertEqual(schedule["units"][1]["insertedPauseBeforeSeconds"], 0.5)
            self.assertEqual(schedule["units"][1]["startSeconds"], 1.3)
            self.assertEqual(schedule["units"][2]["insertedPauseBeforeSeconds"], 0.3)


if __name__ == "__main__":
    unittest.main()
