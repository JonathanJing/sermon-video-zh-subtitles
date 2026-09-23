import importlib.util
import json
import subprocess
import sys
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
            screens = [
                {"sampleId": row["sampleId"], "variant": row["variant"], "status": "screened", "audioSha256": POC.sha256(row["path"])}
                for row in specs
            ]
            (run / "asr-screening.json").write_text(json.dumps({"results": screens}), encoding="utf-8")
            (run / "speaker-similarity.json").write_text(json.dumps({"results": screens}), encoding="utf-8")
            report = POC.evaluate(plan, run)
            self.assertEqual(report["candidateCount"], 19)
            self.assertEqual(report["status"], "machine_checks_complete_human_listening_pending")
            self.assertFalse(report["productionEligible"])
            first = specs[0]["path"]
            self.write_silence(first, 0.6)
            stale = POC.evaluate(plan, run)
            self.assertEqual(stale["status"], "partial")
            self.assertEqual(stale["results"][0]["contentAsrScreen"]["status"], "pending")
            self.assertEqual(stale["results"][0]["speakerSimilarityScreen"]["status"], "pending")


    def test_long_ab_builder_requires_current_render_manifests(self):
        plan = json.loads((ROOT / "long-ab-plan.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            for engine in ("qwen", "voxcpm2"):
                audio = run / f"{engine}.wav"
                self.write_silence(audio)
                manifest = {
                    "schemaVersion": "sermon-layer3-qwen-voxcpm2-long-ab-render-v1",
                    "sampleId": plan["passage"]["sampleId"],
                    "engine": engine,
                    "textSha256": plan["passage"]["textSha256"],
                    "audio": str(audio),
                    "audioSha256": POC.sha256(audio),
                    "productionEligible": False,
                    "humanApproval": False,
                }
                (run / f"{engine}-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            command = [sys.executable, str(ROOT / "build_long_ab.py"), "--plan", str(ROOT / "long-ab-plan.json"), "--run-dir", str(run)]
            subprocess.run(command, check=True, capture_output=True, text=True)
            self.assertTrue((run / "blind-map.json").exists())
            self.assertTrue((run / "listening.html").exists())
            (run / "blind-map.json").unlink()
            (run / "listening.html").unlink()
            self.write_silence(run / "qwen.wav", 0.6)
            stale = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(stale.returncode, 0)
            self.assertIn("render manifest does not match", stale.stderr)
            self.assertFalse((run / "blind-map.json").exists())
            manifest_path = run / "qwen-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["audioSha256"] = POC.sha256(run / "qwen.wav")
            manifest["textSha256"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            stale = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(stale.returncode, 0)
            self.assertFalse((run / "blind-map.json").exists())


if __name__ == "__main__":
    unittest.main()
