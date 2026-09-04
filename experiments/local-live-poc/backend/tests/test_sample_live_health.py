from __future__ import annotations

import importlib.util
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).parents[2] / "scripts" / "sample-live-health.py"
SPEC = importlib.util.spec_from_file_location("sample_live_health", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class SampleLiveHealthTest(unittest.TestCase):
    def test_reads_live_stream_field_and_preserves_unknown_as_unknown(self) -> None:
        self.assertEqual(MODULE.health_fields({"status": "ready", "asr": {"available": True}, "liveStream": {"available": True}}), {
            "status": "ready", "asr_available": True, "live_available": True,
        })
        self.assertIsNone(MODULE.health_fields({"status": "ready", "live": {"available": True}})["live_available"])
        self.assertIsNone(MODULE.health_fields({"liveStream": {"available": "false"}})["live_available"])
        self.assertFalse(MODULE.health_fields({"liveStream": {"available": False}})["live_available"])

    def test_parses_swap_value_not_adjacent_free_field(self) -> None:
        output = "total = 1024.00M  used = 12.50M  free = 1011.50M  (encrypted)"
        self.assertEqual(MODULE.parse_swap_used_mb(output), 12.5)
        self.assertEqual(MODULE.parse_swap_used_mb("total = 2.00G used = 1.25G free = 0.75G"), 1280)
        self.assertEqual(MODULE.parse_swap_used_mb("used = 0.00M"), 0)
        self.assertIsNone(MODULE.parse_swap_used_mb("free"))

    def test_process_exit_and_missing_measurement_are_distinct(self) -> None:
        self.assertIsNone(MODULE.process_rss_kb(None))
        with patch.object(MODULE.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "")):
            self.assertEqual(MODULE.process_rss_kb(123), 0)
        with patch.object(MODULE.subprocess, "run", side_effect=OSError("unavailable")):
            self.assertIsNone(MODULE.process_rss_kb(123))
        with patch.object(MODULE.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, " 456\n", "")):
            self.assertEqual(MODULE.process_rss_kb(123), 456)


if __name__ == "__main__":
    unittest.main()
