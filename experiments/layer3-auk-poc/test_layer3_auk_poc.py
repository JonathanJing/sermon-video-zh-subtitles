import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import wave


ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("layer3_auk_poc", ROOT / "layer3_poc.py")
POC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POC)


class Layer3AukPocTests(unittest.TestCase):
    @staticmethod
    def write_silence(path, seconds, rate=24000):
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(rate)
            stream.writeframes(b"\0" * round(rate * seconds) * 2)

    def test_frozen_plan_is_valid(self):
        plan = POC.load_plan(ROOT / "plan.json")
        self.assertEqual(len(plan["units"]), 6)
        self.assertEqual([unit["sourceUnitId"] for unit in plan["units"] if unit["challenger"]],
                         ["block-59-u001", "block-59-u005"])

    def test_assembly_copies_pauses_without_stretching_units(self):
        plan = POC.load_plan(ROOT / "plan.json")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            qwen = root / "qwen"
            qwen.mkdir()
            rate = 24000
            unit_duration = 0.5
            for unit in plan["units"]:
                self.write_silence(qwen / f'{unit["sourceUnitId"]}.wav', unit_duration, rate)
            receipt = POC.assemble(plan, qwen, root / "assembled.wav")
            expected = 6 * unit_duration + sum(unit["pauseAfterSeconds"] for unit in plan["units"][:-1])
            self.assertAlmostEqual(receipt["track"]["durationSeconds"], expected, places=3)
            self.assertEqual([cue["pauseAfterSeconds"] for cue in receipt["cues"]],
                             [unit["pauseAfterSeconds"] if index < 5 else 0.0 for index, unit in enumerate(plan["units"])])
            self.assertEqual(receipt["ratePolicy"], "natural_no_time_stretch")

    def test_evaluation_requires_both_dimensions_and_keeps_human_pending(self):
        plan = POC.load_plan(ROOT / "plan.json")
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            rate = 24000
            keys = []
            for unit in plan["units"]:
                qwen = run / "qwen" / f'{unit["sourceUnitId"]}.wav'
                self.write_silence(qwen, unit["targetDurationSeconds"], rate)
                keys.append((unit["sourceUnitId"], "qwen_sft_unit"))
                if unit["challenger"]:
                    for variant in ("auk_zero_shot", "qwen_then_auk_speed_emphasis"):
                        path = run / "auk" / unit["sourceUnitId"] / f"{variant}.wav"
                        self.write_silence(path, unit["targetDurationSeconds"], rate)
                        keys.append((unit["sourceUnitId"], variant))
            screens = [
                {"sourceUnitId": unit, "variant": variant, "status": "screened", "audioSha256": POC.sha256(
                    (run / "qwen" / f"{unit}.wav") if variant == "qwen_sft_unit"
                    else (run / "auk" / unit / f"{variant}.wav")
                )}
                for unit, variant in keys
            ]
            (run / "asr-screening.json").write_text(json.dumps({"results": screens}), encoding="utf-8")
            (run / "speaker-similarity.json").write_text(json.dumps({"results": screens}), encoding="utf-8")
            report = POC.evaluate(plan, run)
            self.assertEqual(report["candidateCount"], 10)
            self.assertEqual(report["status"], "machine_checks_complete_human_listening_pending")
            self.assertFalse(report["productionEligible"])
            self.assertTrue(all(row["humanListening"] == "pending" for row in report["results"]))
            first = run / "qwen" / f'{plan["units"][0]["sourceUnitId"]}.wav'
            self.write_silence(first, plan["units"][0]["targetDurationSeconds"] + 0.1)
            stale = POC.evaluate(plan, run)
            self.assertEqual(stale["status"], "partial")
            self.assertEqual(stale["results"][0]["contentAsrScreen"]["status"], "pending")
            self.assertEqual(stale["results"][0]["speakerSimilarityScreen"]["status"], "pending")

    def test_optional_baselines_cannot_replace_missing_required_candidates(self):
        plan = POC.load_plan(ROOT / "plan.json")
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            for unit in plan["units"]:
                self.write_silence(run / "qwen" / f'{unit["sourceUnitId"]}.wav', 0.5)
                if unit["challenger"]:
                    self.write_silence(run / "baseline" / f'{unit["sourceUnitId"]}.wav', 0.5)
                    for variant in ("auk_zero_shot", "qwen_then_auk_speed_emphasis"):
                        if unit["sourceUnitId"] == "block-59-u001" and variant == "auk_zero_shot":
                            continue
                        self.write_silence(run / "auk" / unit["sourceUnitId"] / f"{variant}.wav", 0.5)
            screens = [
                {"sourceUnitId": unit["sourceUnitId"], "variant": variant, "status": "screened", "audioSha256": POC.sha256(path)}
                for unit, variant, path in POC.candidate_paths(plan, run)
            ]
            for filename in ("asr-screening.json", "speaker-similarity.json"):
                (run / filename).write_text(json.dumps({"results": screens}), encoding="utf-8")
            report = POC.evaluate(plan, run)
            self.assertGreaterEqual(report["candidateCount"], report["expectedMinimumCandidateCount"])
            self.assertEqual(report["status"], "partial")


if __name__ == "__main__":
    unittest.main()
