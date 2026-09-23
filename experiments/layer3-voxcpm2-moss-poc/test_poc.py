import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import wave


ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("layer3_multimodel_poc", ROOT / "poc.py")
POC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POC)


class Layer3MultimodelPocTests(unittest.TestCase):
    @staticmethod
    def write_silence(path, seconds=0.5, rate=16000):
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(rate)
            stream.writeframes(b"\0" * round(rate * seconds) * 2)

    def test_frozen_plan_is_valid(self):
        plan = POC.load_plan(ROOT / "plan.json")
        self.assertEqual([row["targetLocale"] for row in plan["multilingualSmoke"]], ["zh-Hans", "ko", "es", "vi"])
        self.assertEqual(plan["pauseProbe"]["pauseSeconds"], 1.450001)

    def test_candidate_matrix_has_nineteen_outputs(self):
        plan = POC.load_plan(ROOT / "plan.json")
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            for unit in plan["primaryUnits"]:
                sample = unit["sourceUnitId"]
                for path in [
                    run / "baseline" / "qwen" / f"{sample}.wav",
                    run / "voxcpm2" / sample / "clone.wav",
                    run / "voxcpm2" / sample / "style_guided.wav",
                    run / "moss" / sample / "clone.wav",
                    run / "moss" / sample / "duration_control.wav",
                ]:
                    self.write_silence(path)
            self.write_silence(run / "moss" / plan["pauseProbe"]["sampleId"] / "explicit_pause.wav", 2.0)
            for smoke in plan["multilingualSmoke"]:
                self.write_silence(run / "voxcpm2" / "smoke" / f'{smoke["targetLocale"]}.wav')
                self.write_silence(run / "moss" / "smoke" / f'{smoke["targetLocale"]}.wav')
            specs = list(POC.candidate_specs(plan, run))
            self.assertEqual(len(specs), 19)
            screens = [{"sampleId": row["sampleId"], "variant": row["variant"], "status": "screened"} for row in specs]
            (run / "asr-screening.json").write_text(json.dumps({"results": screens}), encoding="utf-8")
            (run / "speaker-similarity.json").write_text(json.dumps({"results": screens}), encoding="utf-8")
            report = POC.evaluate(plan, run)
            self.assertEqual(report["candidateCount"], 19)
            self.assertEqual(report["status"], "machine_checks_complete_human_listening_pending")
            self.assertFalse(report["productionEligible"])


if __name__ == "__main__":
    unittest.main()
