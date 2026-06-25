import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_realtime_stable_reconnect_smoke.py"
REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("run_realtime_stable_reconnect_smoke", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class RunRealtimeStableReconnectSmokeTest(unittest.TestCase):
    def test_smoke_proves_stable_caption_reconnect_and_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = SimpleNamespace(
                sunday="2026-06-28",
                event_log_dir=root / "events",
                out=root / "report.json",
                session_validation_out=root / "session-validation.json",
                min_stable_p95_ms=3000,
                max_stable_p95_ms=6000,
            )

            report = mod.run_smoke(args)
            validation = json.loads(args.session_validation_out.read_text(encoding="utf-8"))
            events_path = Path(report["eventsJsonl"])
            if not events_path.is_absolute():
                events_path = REPO_ROOT / events_path

            self.assertEqual(report["status"], "ok")
            self.assertEqual(report["failedChecks"], [])
            self.assertIn("caption_stable", report["eventTypes"])
            self.assertEqual(report["stableSegmentId"], "seg_smoke_1")
            self.assertEqual(report["finalSegmentId"], "seg_smoke_1")
            self.assertEqual(report["stableLatency"]["p95Ms"], 3400)
            self.assertEqual(validation["status"], "ok")
            self.assertEqual(validation["stableLatency"]["p95Ms"], 3400)
            self.assertTrue(events_path.exists())
            archived = events_path.read_text(encoding="utf-8")
            self.assertIn('"type": "caption_stable"', archived)
            self.assertIn('"stabilizerWindow"', archived)
            self.assertFalse(report["apiKeyMaterialIncluded"])
            self.assertFalse(report["secretResourceNamesIncluded"])


if __name__ == "__main__":
    unittest.main()
