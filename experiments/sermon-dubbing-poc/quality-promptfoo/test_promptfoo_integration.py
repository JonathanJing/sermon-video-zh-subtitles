"""Opt-in installed-tool integration; providers are local and OS network-denied."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
FIXTURES = HERE.parent / "quality-fixtures"
BASELINE = HERE.parent / "quality-baselines/2026-09-06-l8ucqF9uA9A"


@unittest.skipUnless(sys.platform == "darwin" and (HERE / "node_modules/promptfoo/package.json").is_file(),
                     "Install the pinned local Promptfoo package on macOS first")
class LocalPromptfooIntegrationTests(unittest.TestCase):
    def test_real_provider_and_assertion_execute_for_positive_and_negative(self):
        with tempfile.TemporaryDirectory() as temporary:
            for candidate, expected_code, expected_stats in (("baseline.json", 0, (1, 0)), ("candidate-regression.json", 1, (0, 1))):
                with self.subTest(candidate=candidate):
                    out = Path(temporary) / candidate
                    run = subprocess.run([sys.executable, str(HERE / "run_eval.py"), "--suite", str(FIXTURES / "suite.json"),
                                          "--baseline", str(FIXTURES / "baseline.json"), "--candidate", str(FIXTURES / candidate),
                                          "--out-dir", str(out)], capture_output=True, text=True, timeout=120)
                    self.assertEqual(run.returncode, expected_code, run.stdout + run.stderr)
                    results = json.loads((out / "promptfoo-results.json").read_text())
                    stats = results["results"]["stats"]
                    self.assertEqual((stats["successes"], stats["failures"]), expected_stats)
                    self.assertEqual(stats["errors"], 0)
                    self.assertEqual(stats["tokenUsage"]["total"], 0)
                    row = results["results"]["results"][0]
                    self.assertEqual(row["provider"]["id"], "sermon-local-saved-report-v1")
                    self.assertIs(row["response"]["metadata"]["localProviderExecuted"], True)
                    self.assertEqual(row["gradingResult"]["componentResults"][0]["assertion"]["type"], "javascript")
                    self.assertIsNone(results.get("shareableUrl"))
                    receipt = json.loads((out / "run-receipt.json").read_text())
                    self.assertEqual(receipt["networkPolicy"], "macos_sandbox_deny_network")
                    self.assertIs(receipt["telemetryEnabled"], False)

    def test_os_sandbox_denies_even_loopback_network(self):
        node = shutil.which("node")
        run = subprocess.run(["/usr/bin/sandbox-exec", "-p", "(version 1) (allow default) (deny network*)", node, "-e",
                              "const s=require('node:net').connect({host:'127.0.0.1',port:9}); s.on('error',e=>{console.log(e.code);process.exit(e.code==='EPERM'?0:1)}); s.on('connect',()=>process.exit(2));"],
                             capture_output=True, text=True, timeout=10)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("EPERM", run.stdout)


class ExistingSermonRegressionTests(unittest.TestCase):
    def test_existing_v2_audio_receipts_do_not_hide_canonical_number_errors(self):
        sys.path.insert(0, str(HERE.parent))
        from quality_harness import compare
        if not BASELINE.is_dir():
            self.skipTest("Frozen real baseline is unavailable")
        suite = json.loads((BASELINE / "suite.json").read_text())
        if not (BASELINE / suite["modelReviewEvidence"]["path"]).exists():
            self.skipTest("Original local review and audio receipts are unavailable")
        result = compare(BASELINE / "suite.json", BASELINE / "baseline-v3.json", BASELINE / "known-issue-v2.json")
        self.assertTrue(result["baseline"]["passed"])
        self.assertFalse(result["candidate"]["passed"])
        self.assertEqual({row["rule"] for row in result["regressions"]}, {
            "canonical_number_spoken:5300", "canonical_number_recognized:5300",
            "canonical_number_spoken:3000", "canonical_number_recognized:3000"})
        bad = [m for m in result["candidate"]["recordedAudioMeasurements"] if m["sampleId"].endswith("block-2")]
        self.assertEqual([m["unitId"] for m in bad], [5, 6])
        self.assertTrue(all(m["asrSimilarity"] == 1.0 and m["reportedDifferences"] == 0 for m in bad))
        self.assertEqual(result["humanAcceptance"], "not_evaluated")


if __name__ == "__main__":
    unittest.main()
