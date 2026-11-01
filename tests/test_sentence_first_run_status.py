"""Tests for the sentence-first observable run status sidecar (P0)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "experiments" / "sentence-first-agent"
if str(EXPERIMENT) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT))
import run_status  # noqa: E402
import spark_queue  # noqa: E402


class Clock:
    def __init__(self, at: str = "2026-11-01T12:00:00+00:00"):
        self.at = at

    def __call__(self) -> str:
        return self.at

    def bump(self, seconds: float) -> str:
        value = datetime.fromisoformat(self.at) + timedelta(seconds=seconds)
        self.at = value.isoformat(timespec="seconds")
        return self.at


class RunStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / "run"
        self.run.mkdir()
        self.index = self.root / ".status-index.json"
        self.clock = Clock()
        self.write_json(self.run / "decisions.json", {
            "schemaVersion": "sentence-first-frozen-decisions-v1",
            "form": "full", "sync": True, "publish": True,
            "locales": ["zh-Hans"], "title": "Test run",
        })

    @staticmethod
    def write_json(path: Path, value) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    def register(self, **overrides):
        kwargs = dict(production="p", page_id="page-1", locale="zh-Hans", index=self.index, now=self.clock)
        kwargs.update(overrides)
        return run_status.register_run(self.run, **kwargs)

    def mark(self, stage, event, **overrides):
        kwargs = dict(now=self.clock)
        kwargs.update(overrides)
        return run_status.mark_event(self.run, stage, event, **kwargs)

    def snapshot(self, **overrides):
        kwargs = dict(index=self.index, now=self.clock)
        kwargs.update(overrides)
        return run_status.derive_snapshot(self.run, **kwargs)

    def test_register_writes_index_and_planned_event_without_a_fake_stage(self):
        entry = self.register()
        self.assertEqual(entry["runs"]["zh-Hans"], "run")
        data = json.loads(self.index.read_text(encoding="utf-8"))
        self.assertEqual(data["productions"]["p"]["pageId"], "page-1")
        snapshot = self.snapshot()
        self.assertEqual(snapshot["runState"], "planned")
        self.assertEqual(snapshot["stages"], [])
        self.assertEqual(snapshot["source"]["statusEvents"], 1)

    def test_started_progress_finished_and_evidence(self):
        self.register()
        self.mark("l1.start", "started")
        self.clock.bump(5)
        self.mark("l1.start", "finished", evidence_level="E1")
        self.clock.bump(5)
        self.mark("l2.translate.zh-Hans", "started")
        self.clock.bump(10)
        self.mark("l2.translate.zh-Hans", "progress", unit="sentences", done=10, total=100)
        self.clock.bump(10)
        self.mark("l2.translate.zh-Hans", "progress", unit="sentences", done=30, total=100)
        self.clock.bump(5)
        self.mark("l2.translate.zh-Hans", "finished", evidence_level="E1")
        snapshot = self.snapshot()
        stages = {stage["id"]: stage for stage in snapshot["stages"]}
        self.assertEqual(stages["l1.start"]["state"], "succeeded")
        self.assertEqual(stages["l1.start"]["evidenceLevel"], "E1")
        self.assertEqual(stages["l2.translate.zh-Hans"]["state"], "succeeded")
        self.assertEqual(stages["l2.translate.zh-Hans"]["progress"]["done"], 30)

    def test_eta_from_two_progress_samples_only_while_running(self):
        self.register()
        self.mark("l2.translate.zh-Hans", "started")
        self.clock.bump(10)
        self.mark("l2.translate.zh-Hans", "progress", unit="sentences", done=10, total=100)
        self.clock.bump(10)
        self.mark("l2.translate.zh-Hans", "progress", unit="sentences", done=30, total=100)
        snapshot = self.snapshot()
        stage = next(stage for stage in snapshot["stages"] if stage["id"] == "l2.translate.zh-Hans")
        # 20 units in 10 s -> 2/s; 70 remaining -> 35 s.
        self.assertEqual(stage["etaSeconds"], 35)
        self.assertEqual(stage["etaSource"], "observed")

    def test_waiting_creates_attention_and_resume_closes_it(self):
        self.register()
        self.mark("l3.finish", "started")
        self.clock.bump(30)
        self.mark("l3.finish", "finished", evidence_level="E1")
        self.clock.bump(10)
        self.mark("l3.review.zh-Hans", "waiting", waiting_on="user track review",
                  kind="human", action_url="http://127.0.0.1:8765/review-player.html",
                  expected_minutes="20-80")
        snapshot = self.snapshot()
        attention = [item for item in snapshot["attention"] if item["stage"] == "l3.review.zh-Hans"]
        self.assertEqual(len(attention), 1)
        self.assertEqual(attention[0]["kind"], "human_review")
        self.assertEqual(attention[0]["waitingOn"], "user track review")
        self.assertEqual(attention[0]["severity"], "attention")
        self.clock.bump(60)
        self.mark("l3.review.zh-Hans", "resumed")
        snapshot = self.snapshot()
        self.assertEqual([item for item in snapshot["attention"]
                          if item["stage"] == "l3.review.zh-Hans"], [])

    def test_stall_is_derived_and_does_not_become_failed(self):
        self.register()
        self.mark("l3.tts.john_thomas.zh-Hans", "started")
        self.clock.bump(600)
        snapshot = self.snapshot()
        stage = next(stage for stage in snapshot["stages"] if stage["id"] == "l3.tts.john_thomas.zh-Hans")
        self.assertEqual(stage["state"], "running")
        self.assertTrue(stage["stalled"])
        self.assertTrue(snapshot["stalled"])
        stalled = [item for item in snapshot["attention"] if item["kind"] == "stalled"]
        self.assertEqual(len(stalled), 1)
        self.assertEqual(stalled[0]["severity"], "timeSensitive")
        self.assertFalse(any(stage["state"] == "failed" for stage in snapshot["stages"]))

    def test_mark_refreshes_the_snapshot_for_the_dock(self):
        self.register()
        self.mark("l1.start", "started")
        snapshot = run_status._read_json(run_status.status_path(self.run))
        self.assertIsNotNone(snapshot.get("generatedAt"))
        self.assertEqual(snapshot["stages"][0]["id"], "l1.start")
        self.assertEqual(snapshot["stages"][0]["state"], "running")

    def test_missing_required_after_translation_includes_audit_and_consistency(self):
        self.register()
        self.mark("l1.start", "started")
        self.clock.bump(5)
        self.mark("l1.start", "finished", evidence_level="E1")
        self.clock.bump(5)
        self.mark("l1.preflight", "started")
        self.clock.bump(5)
        self.mark("l1.preflight", "finished", evidence_level="E2")
        self.clock.bump(5)
        self.mark("l2.translate.zh-Hans", "started")
        self.clock.bump(10)
        self.mark("l2.translate.zh-Hans", "finished", evidence_level="E1")
        self.clock.bump(run_status.MISSING_GRACE_SECONDS + 60)
        snapshot = self.snapshot()
        self.assertIn("l2.audit.zh-Hans", snapshot["required"]["missing"])
        self.assertIn("l2.consistency", snapshot["required"]["missing"])
        self.assertNotIn("l3.speech.zh-Hans", snapshot["required"]["missing"])
        self.assertEqual(snapshot["runState"], "attention_required")

    def test_deepseek_state_is_derived_without_explicit_events(self):
        self.register()
        self.write_json(self.run / "state-translate.json", {
            "label": "translate", "status": "running", "windowsDone": 3, "total": 10,
            "unitsDone": 30, "startedAt": "2026-11-01T12:01:00+00:00",
            "updatedAt": "2026-11-01T12:02:00+00:00",
        })
        self.clock.at = "2026-11-01T12:02:10+00:00"
        snapshot = self.snapshot()
        stage = next(stage for stage in snapshot["stages"] if stage["id"] == "l2.translate.zh-Hans")
        self.assertEqual(stage["state"], "running")
        self.assertEqual(stage["progress"], {"unit": "windows", "done": 3, "total": 10})
        self.assertEqual(stage["source"], "derived:state-translate.json")
        self.assertEqual(stage["heartbeatAgeSeconds"], 10.0)
        self.assertIn("state-translate.json", snapshot["source"]["derived"])

    def test_artifact_fallbacks_fill_stages_that_old_runs_never_journaled(self):
        self.register()
        (self.run / "translations.jsonl").write_text('{"id":"s1"}\n{"id":"s2"}\n', encoding="utf-8")
        (self.run / "sentences.jsonl").write_text('{"id":"s1"}\n{"id":"s2"}\n', encoding="utf-8")
        (self.run / "speech.jsonl").write_text(
            '{"id":"s1","speaker":"john_thomas"}\n{"id":"s2","speaker":"john_thomas"}\n', encoding="utf-8")
        (self.run / "audit").mkdir()
        (self.run / "audit" / "revisions-zh-Hans.jsonl").write_text('{"id":"s1"}\n', encoding="utf-8")
        (self.run / "track.wav").write_bytes(b"")
        snapshot = self.snapshot()
        stages = {stage["id"]: stage for stage in snapshot["stages"]}
        for stage_id in ("l2.translate.zh-Hans", "l2.audit.zh-Hans", "l3.speech.zh-Hans",
                         "l3.tts.john_thomas.zh-Hans", "l3.finish"):
            self.assertEqual(stages[stage_id]["state"], "succeeded", stage_id)
            self.assertEqual(stages[stage_id]["evidenceLevel"], "E1", stage_id)
        self.assertEqual(stages["l3.tts.john_thomas.zh-Hans"]["source"], "derived:track.wav")

    def test_locale_is_inferred_from_a_short_run_name_suffix(self):
        short = self.root / "run-zh"
        short.mkdir()
        self.write_json(short / "decisions.json", {"form": "clip", "sync": False, "publish": False})
        run_status.mark_event(short, "l1.start", "started", now=self.clock)
        snapshot = run_status.derive_snapshot(short, index=self.index, now=self.clock)
        self.assertEqual(snapshot["locale"], "zh-Hans")

    def test_state_total_zero_does_not_invent_a_percentage_or_eta(self):
        self.register()
        self.write_json(self.run / "state-trim.json", {
            "label": "trim", "status": "running", "windowsDone": 2, "total": 0,
            "updatedAt": "2026-11-01T12:02:00+00:00",
        })
        self.clock.at = "2026-11-01T12:02:10+00:00"
        snapshot = self.snapshot()
        stage = next(stage for stage in snapshot["stages"] if stage["id"] == "l3.lag-loop.zh-Hans")
        self.assertEqual(stage["progress"], {"unit": "windows", "done": 2, "total": None})
        self.assertIsNone(stage["etaSeconds"])

    def test_production_aggregates_runs_and_attention(self):
        self.register()
        ko_run = self.root / "run-ko"
        ko_run.mkdir()
        self.write_json(ko_run / "decisions.json", {
            "form": "full", "sync": True, "publish": True, "locales": ["ko"], "title": "Test run",
        })
        run_status.register_run(ko_run, production="p", page_id="page-1", locale="ko",
                                index=self.index, now=self.clock)
        self.mark("l1.start", "started")
        self.clock.bump(60)
        self.mark("l1.start", "failed", error_class="infra", message="ssh timeout",
                  resume="retry spark begin")
        snapshot = run_status.build_production("p", index=self.index, now=self.clock)
        self.assertEqual(snapshot["runState"], "attention_required")
        self.assertEqual({run["locale"] for run in snapshot["runs"]}, {"zh-Hans", "ko"})
        self.assertTrue(any(item["kind"] == "failed" and item["runId"] == "run"
                            for item in snapshot["attention"]))
        self.assertEqual(snapshot["required"]["missing"], ["run-ko:l1.start"])

    def test_check_detects_a_snapshot_that_no_longer_matches_events(self):
        self.register()
        self.mark("l1.start", "started")
        run_status.rebuild_run(self.run, index=self.index, now=self.clock)
        self.assertTrue(run_status.check_snapshot(self.run, index=self.index, now=self.clock)["consistent"])
        self.clock.bump(10)
        self.mark("l1.start", "finished", evidence_level="E1")
        # Producers now refresh the snapshot on write; simulate an external edit
        # that left it stale so the checker still has something to detect.
        stale = run_status._read_json(run_status.status_path(self.run))
        stale["stages"] = []
        run_status._write_json(run_status.status_path(self.run), stale)
        report = run_status.check_snapshot(self.run, index=self.index, now=self.clock)
        self.assertFalse(report["consistent"])
        self.assertIn("stages", report["mismatches"])

    def test_heartbeat_expectation_can_tighten_the_stall_threshold(self):
        self.register()
        self.mark("l3.tts.john_thomas.zh-Hans", "started", heartbeat_expected_seconds=30)
        self.clock.bump(200)
        stage = next(stage for stage in self.snapshot()["stages"]
                     if stage["id"] == "l3.tts.john_thomas.zh-Hans")
        self.assertTrue(stage["stalled"])

    def test_finished_without_evidence_stays_unknown(self):
        self.register()
        self.mark("l1.start", "started")
        self.mark("l1.start", "finished")
        stage = next(stage for stage in self.snapshot()["stages"] if stage["id"] == "l1.start")
        self.assertEqual(stage["state"], "succeeded")
        self.assertIsNone(stage["evidenceLevel"])

    def test_status_rebuilds_when_a_snapshot_ages_without_new_events(self):
        self.register()
        self.mark("l3.tts.john_thomas.zh-Hans", "started")
        run_status.rebuild_run(self.run, index=self.index, now=self.clock)
        self.clock.bump(60)
        snapshot = run_status._snapshot_or_build(self.run, self.index, now=self.clock)
        stage = next(stage for stage in snapshot["stages"]
                     if stage["id"] == "l3.tts.john_thomas.zh-Hans")
        self.assertGreaterEqual(stage["heartbeatAgeSeconds"], 60)

    def test_check_is_stable_when_only_time_passes(self):
        self.register()
        self.mark("l1.start", "started")
        self.mark("l3.review.zh-Hans", "waiting", waiting_on="user track review", kind="human")
        run_status.rebuild_run(self.run, index=self.index, now=self.clock)
        self.clock.bump(3600)
        report = run_status.check_snapshot(self.run, index=self.index, now=self.clock)
        self.assertTrue(report["consistent"])

    def test_wrap_marks_success_and_failure(self):
        self.register()
        code = run_status.wrap_command(
            self.run, "l1.srt", [sys.executable, "-c", "pass"], heartbeat_seconds=60)
        self.assertEqual(code, 0)
        snapshot = self.snapshot()
        stage = next(stage for stage in snapshot["stages"] if stage["id"] == "l1.srt")
        self.assertEqual(stage["state"], "succeeded")
        code = run_status.wrap_command(
            self.run, "l1.srt", [sys.executable, "-c", "raise SystemExit(3)"], heartbeat_seconds=60)
        self.assertEqual(code, 3)
        snapshot = self.snapshot()
        stage = next(stage for stage in snapshot["stages"] if stage["id"] == "l1.srt")
        self.assertEqual(stage["state"], "failed")
        self.assertEqual(stage["errorClass"], "process")
        self.assertTrue(any(item["kind"] == "failed" for item in snapshot["attention"]))

    def test_spark_queue_run_job_emits_started_progress_finished(self):
        self.register()
        code = spark_queue.run_job(
            [sys.executable, "-c", "pass"], run=self.run,
            stages=["l3.tts.john_thomas.zh-Hans"], purpose="sentence-tts-john_thomas-zh-Hans",
            done=1, total=1)
        self.assertEqual(code, 0)
        snapshot = self.snapshot()
        stage = next(stage for stage in snapshot["stages"] if stage["id"] == "l3.tts.john_thomas.zh-Hans")
        self.assertEqual(stage["state"], "succeeded")
        self.assertEqual(stage["evidenceLevel"], "E1")
        self.assertEqual(stage["progress"]["done"], 1)
        self.assertEqual(stage["source"], "spark_queue")

    def test_spark_queue_run_job_marks_failure(self):
        self.register()
        code = spark_queue.run_job(
            [sys.executable, "-c", "raise SystemExit(3)"], run=self.run,
            stages=["l3.tts.john_thomas.zh-Hans"], purpose="sentence-tts-john_thomas-zh-Hans",
            done=1, total=1)
        self.assertEqual(code, 3)
        snapshot = self.snapshot()
        stage = next(stage for stage in snapshot["stages"] if stage["id"] == "l3.tts.john_thomas.zh-Hans")
        self.assertEqual(stage["state"], "failed")
        self.assertEqual(stage["errorClass"], "process")

    def test_wrap_cli_recognizes_wrap_subcommand(self):
        code = run_status.main([
            "wrap", "--run", str(self.run), "--stage", "l1.srt", "--",
            sys.executable, "-c", "pass",
        ])
        self.assertEqual(code, 0)
        snapshot = self.snapshot()
        stage = next(stage for stage in snapshot["stages"] if stage["id"] == "l1.srt")
        self.assertEqual(stage["state"], "succeeded")

    def test_invalid_stage_and_waiting_without_owner_are_refused(self):
        self.register()
        with self.assertRaisesRegex(ValueError, "stage must be"):
            self.mark("bad stage", "started")
        with self.assertRaisesRegex(ValueError, "waiting requires"):
            self.mark("l3.review.zh-Hans", "waiting")


if __name__ == "__main__":
    unittest.main()
