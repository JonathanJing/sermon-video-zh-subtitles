"""Behavioral DAG tests: overlap, dependency join, cancellation and provenance."""
from contextlib import nullcontext
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import run_weekly_dubbing as runner
import test_weekly_accounting as accounting_tests


class ParallelDubbingTests(unittest.TestCase):
    setUp = accounting_tests.WeeklyAccountingTests.setUp
    fixture = accounting_tests.WeeklyAccountingTests.fixture
    read_accounting = accounting_tests.WeeklyAccountingTests.read_accounting

    def enable_parallel(self):
        sys.argv.remove("--serial-stages")

    def test_alignment_overlaps_render_and_screening_then_timing_joins(self):
        started, screened, finished = (threading.Event() for _ in range(3))
        with tempfile.TemporaryDirectory() as tmp, self.fixture(tmp) as f, patch.object(runner, "local_model_slot", return_value=nullcontext()):
            self.enable_parallel()
            original = f.command
            def command(argv, **kwargs):
                name = Path(argv[1]).name if len(argv) > 1 else ""
                if name == "align_weekly_source.py":
                    started.set()
                    self.assertTrue(screened.wait(3), "screening must start before alignment finishes")
                    finished.set()
                elif name == "screen_weekly_audio.py":
                    self.assertTrue(started.wait(3))
                    self.assertFalse(finished.is_set())
                    screened.set()
                elif name == "check_weekly_timing.py":
                    self.assertTrue(finished.is_set(), "timing must wait for alignment")
                elif "/work/render_weekly_audio.py" in argv[-1]:
                    self.assertTrue(started.wait(3), "render overlaps a running alignment")
                    self.assertFalse(finished.is_set())
                return original(argv, **kwargs)
            f.process.side_effect = command
            runner.main()
            self.assertTrue((f.work / "workflow-receipt.json").exists())
            alignment = [row for row in f.commands if "align_weekly_source.py" in " ".join(row["argv"])][0]
            self.assertEqual(alignment["stage"], "source_alignment")
            _, _, finished_stages = self.read_accounting(f.work / "accounting")
            parent = next(row for row in finished_stages if row["stage"] == "weekly_dubbing")
            child = next(row for row in finished_stages if row["stage"] == "source_alignment")
            self.assertEqual(child["parentSpanId"], parent["spanId"])
            self.assertEqual(alignment["runId"], child["runId"])

    def test_render_failure_cancels_worker_preserves_partial_evidence(self):
        started, stopped = threading.Event(), threading.Event()
        with tempfile.TemporaryDirectory() as tmp, self.fixture(tmp) as f, patch.object(runner, "local_model_slot", return_value=nullcontext()):
            self.enable_parallel()
            original = f.command
            def command(argv, **kwargs):
                if len(argv) > 1 and Path(argv[1]).name == "align_weekly_source.py":
                    evidence = f.work / "source-alignment/partial.json"
                    evidence.parent.mkdir(exist_ok=True)
                    evidence.write_text('{"preserved": true}')
                    started.set()
                    self.assertTrue(kwargs["cancel_event"].wait(3), "sibling failure must cancel worker")
                    stopped.set()
                    raise InterruptedError("cancelled source alignment")
                if "docker ps" in argv[-1]:
                    self.assertTrue(started.wait(3))
                    raise ValueError("render branch failure")
                return original(argv, **kwargs)
            f.process.side_effect = command
            with self.assertRaisesRegex(ValueError, "render branch failure"):
                runner.main()
            self.assertTrue(stopped.is_set())
            self.assertTrue((f.work / "source-alignment/partial.json").exists())
            self.assertFalse((f.work / "workflow-receipt.json").exists())
            f.mocks["validate_candidate"].assert_not_called()

    def test_alignment_failure_prevents_timing_or_candidate(self):
        with tempfile.TemporaryDirectory() as tmp, self.fixture(tmp) as f, patch.object(runner, "local_model_slot", return_value=nullcontext()):
            self.enable_parallel()
            original = f.command
            def command(argv, **kwargs):
                if len(argv) > 1 and Path(argv[1]).name == "align_weekly_source.py":
                    raise ValueError("alignment receipt invalid")
                return original(argv, **kwargs)
            f.process.side_effect = command
            with self.assertRaisesRegex(ValueError, "alignment receipt invalid"):
                runner.main()
            self.assertFalse((f.work / "workflow-receipt.json").exists())
            f.mocks["validate_timing"].assert_not_called()
            f.mocks["validate_candidate"].assert_not_called()


if __name__ == "__main__":
    unittest.main()
