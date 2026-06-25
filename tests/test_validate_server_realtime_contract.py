import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "validate_server_realtime_contract.py"
SPEC = importlib.util.spec_from_file_location("validate_server_realtime_contract", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class ValidateServerRealtimeContractTest(unittest.TestCase):
    def test_server_realtime_contract_passes(self):
        report = mod.validate_server_realtime_contract()

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["failedChecks"], [])
        self.assertIn("nested_output_transcript_delta_object_mapping", [check["name"] for check in report["checks"]])
        policy_check = next(check for check in report["checks"] if check["name"] == "backend_realtime_session_policy")
        self.assertTrue(policy_check["observed"]["allowedRealtimeTranslateZh"])
        self.assertTrue(policy_check["observed"]["rejectsWrongModel"])
        self.assertTrue(policy_check["observed"]["rejectsWrongTargetLanguage"])
        worker_policy = next(check for check in report["checks"] if check["name"] == "media_worker_model_policy")
        self.assertTrue(worker_policy["observed"]["allowsRealtimeTranslateZh"])
        self.assertTrue(worker_policy["observed"]["rejectsWrongRealtimeModel"])
        self.assertTrue(worker_policy["observed"]["rejectsWrongTargetLanguage"])
        self.assertTrue(worker_policy["observed"]["allowsGpt4oTranscribeFallback"])
        self.assertTrue(worker_policy["observed"]["rejectsWrongFallbackModel"])
        self.assertEqual(report["models"]["realtimeDraft"], "gpt-realtime-translate")
        self.assertEqual(report["models"]["inputTranscriptFallback"], "gpt-4o-transcribe")
        self.assertFalse(report["apiKeyMaterialIncluded"])
        self.assertFalse(report["secretResourceNamesIncluded"])
        self.assertNotIn("/secrets/", json.dumps(report))

    def test_main_writes_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "server-realtime-contract.json"
            argv = ["validate_server_realtime_contract.py", "--out", str(out)]
            stdout = io.StringIO()
            original_argv = mod.sys.argv
            original_stdout = mod.sys.stdout
            try:
                mod.sys.argv = argv
                mod.sys.stdout = stdout
                exit_code = mod.main()
            finally:
                mod.sys.argv = original_argv
                mod.sys.stdout = original_stdout

            payload = json.loads(out.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(json.loads(stdout.getvalue())["status"], "ok")


if __name__ == "__main__":
    unittest.main()
