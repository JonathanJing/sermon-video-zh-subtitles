"""Tests that the P1 script hooks really write observable status (no real runs)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "experiments" / "sentence-first-agent"
if str(EXPERIMENT) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT))
import finish_run  # noqa: E402
import lag_loop  # noqa: E402
import run_status  # noqa: E402

try:  # sfa_publish imports the production package (jsonschema); skip only its tests if absent
    import sfa_publish  # noqa: E402
except ModuleNotFoundError as exc:  # pragma: no cover - environment dependent
    sfa_publish = None
    SFA_IMPORT_ERROR = exc
else:
    SFA_IMPORT_ERROR = None


class FakeCfg:
    locales = ("zh-Hans",)

    def __init__(self, run: Path):
        self.run = run

    def run_dir(self, locale):
        return self.run


class P1StatusHookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / "run"
        self.run.mkdir()
        self.index = self.root / ".status-index.json"
        (self.run / "decisions.json").write_text(json.dumps({
            "form": "full", "sync": True, "publish": True, "locales": ["zh-Hans"],
        }), encoding="utf-8")
        run_status.register_run(self.run, production="p", locale="zh-Hans", index=self.index)

    def events(self):
        path = self.run / "status" / "events.ndjson"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_finish_run_writes_five_step_progress(self):
        finish_run.status_progress(self.run, 2, "merged track")
        event = self.events()[-1]
        self.assertEqual(event["type"], "stage.progress")
        self.assertEqual(event["stage"], "l3.finish")
        self.assertEqual(event["progress"], {"unit": "steps", "done": 2, "total": finish_run.FINISH_STEPS})
        self.assertEqual(event["source"], "finish_run")

    def test_lag_loop_writes_progress_and_terminal_evidence(self):
        lag_loop.status_progress(self.run, "zh-Hans", 1, 2, "iteration 1")
        event = self.events()[-1]
        self.assertEqual(event["stage"], "l3.lag-loop.zh-Hans")
        self.assertEqual(event["progress"]["done"], 1)
        url = lag_loop.status_finished(self.run, "zh-Hans", evidence_level="E2")
        self.assertIsNone(url)
        snapshot = run_status.derive_snapshot(self.run, index=self.index)
        stage = next(stage for stage in snapshot["stages"] if stage["id"] == "l3.lag-loop.zh-Hans")
        self.assertEqual(stage["state"], "succeeded")
        self.assertEqual(stage["evidenceLevel"], "E2")

    def test_translate_subagent_output_is_visible_as_rows_progress(self):
        translate = self.run / "translate"
        translate.mkdir()
        (translate / "input-0.jsonl").write_text('{"id":"s1"}\n{"id":"s2"}\n', encoding="utf-8")
        (translate / "output-0.jsonl").write_text('{"id":"s1"}\n', encoding="utf-8")
        snapshot = run_status.derive_snapshot(self.run, index=self.index)
        stage = next(stage for stage in snapshot["stages"] if stage["id"] == "l2.translate.zh-Hans")
        self.assertEqual(stage["state"], "running")
        self.assertEqual(stage["progress"], {"unit": "rows", "done": 1, "total": 2})
        self.assertEqual(stage["source"], "derived:translate/")

    @unittest.skipIf(sfa_publish is None, f"sfa_publish production deps unavailable: {SFA_IMPORT_ERROR}")
    def test_publish_commands_write_l4_stages(self):
        cfg = FakeCfg(self.run)
        sfa_publish._mark_publish(cfg, "assets", "started")
        sfa_publish._mark_publish(cfg, "assets", "finished", evidence_level="E1")
        snapshot = run_status.derive_snapshot(self.run, index=self.index)
        stage = next(stage for stage in snapshot["stages"] if stage["id"] == "l4.assets")
        self.assertEqual(stage["state"], "succeeded")
        self.assertEqual(stage["evidenceLevel"], "E1")

    @unittest.skipIf(sfa_publish is None, f"sfa_publish production deps unavailable: {SFA_IMPORT_ERROR}")
    def test_publish_failure_is_visible(self):
        cfg = FakeCfg(self.run)
        sfa_publish._mark_publish(cfg, "preflight", "started")
        sfa_publish._mark_publish(cfg, "preflight", "failed", error_class="gate",
                                  message="english receipt missing", resume="rerun preflight")
        snapshot = run_status.derive_snapshot(self.run, index=self.index)
        stage = next(stage for stage in snapshot["stages"] if stage["id"] == "l4.preflight")
        self.assertEqual(stage["state"], "failed")
        self.assertTrue(any(item["stage"] == "l4.preflight" for item in snapshot["attention"]))


if __name__ == "__main__":
    unittest.main()
