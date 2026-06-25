import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "validate_stable_correction_contract.py"
SPEC = importlib.util.spec_from_file_location("validate_stable_correction_contract", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class ValidateStableCorrectionContractTest(unittest.TestCase):
    def test_stable_correction_contract_passes(self):
        report = mod.validate_stable_correction_contract()

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["failedChecks"], [])
        self.assertEqual(report["models"]["stableCorrection"], "gpt-5.4-mini")
        event_check = next(
            check for check in report["checks"] if check["name"] == "stable_corrections_are_caption_final_events"
        )
        self.assertTrue(event_check["observed"]["hasSegmentId"])
        self.assertEqual(event_check["observed"]["segmentId"], "seg_1")
        self.assertTrue(event_check["observed"]["final"])
        model_policy = next(check for check in report["checks"] if check["name"] == "stable_correction_model_policy")
        self.assertTrue(model_policy["observed"]["allowsRequiredMini"])
        self.assertTrue(model_policy["observed"]["rejectsRealtimeTranslate"])
        self.assertTrue(model_policy["observed"]["rejectsAlternativeSubstitute"])
        self.assertFalse(report["apiKeyMaterialIncluded"])
        self.assertFalse(report["secretResourceNamesIncluded"])
        self.assertFalse(report["eventTokenIncluded"])
        rendered = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("projects/", rendered)
        self.assertNotIn("/secrets/", rendered)
        self.assertNotIn("sk-", rendered)

    def test_main_writes_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "stable-correction-contract.json"
            argv = ["validate_stable_correction_contract.py", "--out", str(out)]
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
