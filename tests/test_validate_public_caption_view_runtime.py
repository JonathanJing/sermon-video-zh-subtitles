import importlib.util
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "validate_public_caption_view_runtime.py"
SPEC = importlib.util.spec_from_file_location("validate_public_caption_view_runtime", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


class ValidatePublicCaptionViewRuntimeTest(unittest.TestCase):
    def test_runtime_probe_proves_public_view_updates_draft_and_stable_caption(self):
        report = mod.validate_public_caption_view_runtime(mod.DEFAULT_APP_JS)

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["probe"]["eventSourceUrl"], "/api/realtime/sessions/current/events")
        self.assertIn("caption_delta", report["probe"]["eventSourceListeners"])
        self.assertEqual(report["probe"]["draftCaption"], "神爱世人")
        self.assertEqual(report["probe"]["stableCaption"], "神爱世人。")
        self.assertEqual(report["probe"]["segmentEn"], "God loved the world")
        self.assertTrue(report["probe"]["segmentStable"])
        self.assertFalse(report["apiKeyMaterialIncluded"])
        self.assertFalse(report["eventTokenIncluded"])

    def test_failed_node_probe_is_reported_without_leaking_secret_fields(self):
        report = mod.validate_public_caption_view_runtime(mod.DEFAULT_APP_JS, node_bin="/missing/node")

        self.assertEqual(report["status"], "failed")
        self.assertIn("node_runtime_probe", report["failedChecks"])
        self.assertFalse(report["apiKeyMaterialIncluded"])
        self.assertFalse(report["secretResourceNamesIncluded"])
        self.assertFalse(report["eventTokenIncluded"])


if __name__ == "__main__":
    unittest.main()
