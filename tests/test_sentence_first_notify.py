"""Tests for the run_status notification policy (P2)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "experiments" / "sentence-first-agent"
if str(EXPERIMENT) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT))
import run_status  # noqa: E402


class Clock:
    def __init__(self, at="2026-11-01T12:00:00+00:00"):
        self.at = at

    def __call__(self):
        return self.at

    def bump(self, seconds):
        self.at = (datetime.fromisoformat(self.at) + timedelta(seconds=seconds)).isoformat(timespec="seconds")


class FakeNotifier:
    def __init__(self, delivered=True):
        self.messages = []
        self.delivered = delivered

    def send(self, message):
        self.messages.append(message)
        return {"bark-iphone": self.delivered}


class NotifyPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / "run"
        self.run.mkdir()
        self.index = self.root / ".status-index.json"
        self.clock = Clock()
        (self.run / "decisions.json").write_text(json.dumps({
            "schemaVersion": "sentence-first-frozen-decisions-v1",
            "form": "full", "sync": True, "publish": True,
            "locales": ["zh-Hans"], "title": "Test run",
        }), encoding="utf-8")
        run_status.register_run(self.run, production="p", page_id="page-1", locale="zh-Hans",
                                index=self.index, now=self.clock)

    def mark(self, stage, event, **kwargs):
        kwargs.setdefault("now", self.clock)
        return run_status.mark_event(self.run, stage, event, **kwargs)

    def notify(self, notifier, execute=True, **kwargs):
        return run_status.notify_run(self.run, notifier=notifier, execute=execute,
                                     index=self.index, now=self.clock, **kwargs)

    def test_dry_run_plans_start_without_writing_a_ledger(self):
        self.mark("l1.start", "started")
        notifier = FakeNotifier()
        result = self.notify(notifier, execute=False)
        self.assertEqual([item["kind"] for item in result["plan"]], ["started"])
        self.assertEqual(notifier.messages, [])
        self.assertFalse((self.run / "status" / "notify-sent.ndjson").exists())

    def test_execute_sends_start_once_and_records_the_ledger(self):
        self.mark("l1.start", "started")
        notifier = FakeNotifier()
        first = self.notify(notifier)
        self.assertEqual(len(first["sent"]), 1)
        self.assertEqual(len(notifier.messages), 1)
        ledger = self.run / "status" / "notify-sent.ndjson"
        self.assertTrue(ledger.is_file())
        second = self.notify(notifier)
        self.assertEqual(second["sent"], [])
        self.assertTrue(any(item["reason"] == "already-sent" for item in second["skipped"]))
        self.assertEqual(len(notifier.messages), 1)

    def test_handoff_notification_does_not_forward_a_local_player_url(self):
        self.mark("l3.review.zh-Hans", "waiting", waiting_on="user track review", kind="human",
                  action_url="http://127.0.0.1:8765/review-player.html", expected_minutes="20-80")
        candidates = run_status.notification_candidates(
            run_status.derive_snapshot(self.run, index=self.index, now=self.clock))
        review = next(item for item in candidates if item["kind"] == "human_review")
        self.assertEqual(review["level"], "active")
        self.assertIsNone(review["url"])
        self.assertIn("user track review", review["body"])

    def test_human_review_copy_is_stage_specific(self):
        for stage, expected_title in (
            ("l1.english-review", "待批准 · 英文来源"),
            ("l1.speakers", "待确认 · 讲员映射"),
            ("l4.publish.authorization", "待授权 · 页面发布"),
            ("l4.study", "待批准 · 学习内容"),
            ("l3.review.ko", "可审 · ko 轨"),
        ):
            title, body = run_status._human_review_copy(stage, "user review", "5-10", 600)
            self.assertIn(expected_title, title)
            self.assertIn("已等 10m00s", body)
            if stage.startswith("l3.review"):
                self.assertIn("播放器", body)
            else:
                self.assertNotIn("播放器", body)

    def test_failed_and_unknown_outcome_levels(self):
        self.mark("l1.start", "started")
        self.mark("l1.start", "failed", error_class="infra", message="ssh down", resume="retry")
        snapshot = run_status.derive_snapshot(self.run, index=self.index, now=self.clock)
        failed = next(item for item in run_status.notification_candidates(snapshot)
                      if item["kind"] == "failed")
        self.assertEqual(failed["level"], "timeSensitive")
        self.assertIn("retry", failed["body"])

        snapshot["attention"] = [{
            "kind": "failed", "severity": "timeSensitive", "stage": "l3.tts.zh-Hans",
            "since": "2026-11-01T12:00:00+00:00", "errorClass": "unknown_outcome",
        }]
        unknown = next(item for item in run_status.notification_candidates(snapshot)
                       if item["kind"] == "failed")
        self.assertEqual(unknown["level"], "critical")

    def test_stalled_notification_has_a_cooldown(self):
        self.mark("l3.tts.john_thomas.zh-Hans", "started", heartbeat_expected_seconds=30)
        self.clock.bump(200)
        notifier = FakeNotifier()
        first = self.notify(notifier)
        self.assertTrue(any(item["kind"] == "stalled" for item in first["sent"]))
        self.clock.bump(60)
        second = self.notify(notifier)
        self.assertTrue(any(item["kind"] == "stalled" and item["reason"] == "cooldown"
                            for item in second["skipped"]))
        self.clock.bump(1000)
        third = self.notify(notifier)
        self.assertTrue(any(item["kind"] == "stalled" for item in third["sent"]))

    def test_completed_candidate_and_text_redaction(self):
        snapshot = {
            "runId": "run", "productionId": "p", "startedAt": "2026-11-01T12:00:00+00:00",
            "generatedAt": "2026-11-01T13:00:00+00:00", "runState": "completed",
            "decisions": {"locales": ["zh-Hans"], "form": "full"},
            "attention": [],
            "deliverables": [{"id": "track", "evidenceLevel": "E1"}],
        }
        complete = next(item for item in run_status.notification_candidates(snapshot)
                        if item["kind"] == "completed")
        self.assertEqual(complete["level"], "active")
        self.assertIn("track=E1", complete["body"])
        self.assertEqual(run_status._safe_text("/Users/x/private/file.wav sk-abcdef1234"),
                         "<path> <key>")

    def test_production_notifies_each_run(self):
        ko_run = self.root / "run-ko"
        ko_run.mkdir()
        (ko_run / "decisions.json").write_text(json.dumps({
            "form": "full", "sync": True, "publish": True, "locales": ["ko"], "title": "Test run",
        }), encoding="utf-8")
        run_status.register_run(ko_run, production="p", page_id="page-1", locale="ko",
                                index=self.index, now=self.clock)
        notifier = FakeNotifier()
        result = run_status.notify_production("p", notifier=notifier, execute=True,
                                              index=self.index, now=self.clock)
        self.assertEqual(len(result["runs"]), 2)
        self.assertEqual(len(notifier.messages), 2)


if __name__ == "__main__":
    unittest.main()
