"""Retired discovery entry points must fail before any paid processing."""
import subprocess
import sys
import unittest
from pathlib import Path

from scripts import build_post_live_timeline as mod


class RetiredTimelineTest(unittest.TestCase):
    def test_imported_entry_point_rejects_without_inspecting_inputs(self):
        with self.assertRaisesRegex(SystemExit, "retired.*operator-confirmed"):
            mod.build_post_live_timeline(object())

    def test_old_cli_fails_with_manual_workflow_guidance(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "build_post_live_timeline.py"
        result = subprocess.run(
            [sys.executable, str(script), "--input", "/missing/audio.m4a"],
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("retired", result.stderr)
        self.assertIn("operator-confirmed", result.stderr)
        self.assertIn("codex-local-production-runbook.zh.md", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
