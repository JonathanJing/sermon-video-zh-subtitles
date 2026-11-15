"""End-to-end dry run: stage events -> snapshot -> notification decisions.

Uses a fake notifier, so it never sends a real Bark push. It exercises the
whole weekly stage sequence including human handoffs, a stall, a failure with
retry, and run completion.
"""
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
    def __init__(self):
        self.messages = []

    def send(self, message):
        self.messages.append(message)
        return {"bark-iphone": True, "bark-mac": True}


class NotifyDryRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / "20261101-synthetic-zh"
        self.run.mkdir()
        self.index = self.root / ".status-index.json"
        self.clock = Clock()
        self.notifier = FakeNotifier()
        (self.run / "decisions.json").write_text(json.dumps({
            "schemaVersion": "sentence-first-frozen-decisions-v1",
            "form": "full", "sync": True, "publish": True,
            "locales": ["zh-Hans"], "title": "Synthetic run",
        }), encoding="utf-8")
        run_status.register_run(self.run, production="synthetic", locale="zh-Hans",
                                index=self.index, now=self.clock)

    def mark(self, stage, event, **kwargs):
        kwargs.setdefault("now", self.clock)
        return run_status.mark_event(self.run, stage, event, **kwargs)

    def handoff(self, stage, waiting_on, **kwargs):
        self.mark(stage, "waiting", waiting_on=waiting_on, kind="human", **kwargs)

    def notify(self):
        return run_status.notify_run(self.run, notifier=self.notifier, execute=True,
                                     index=self.index, now=self.clock)

    def titles(self):
        return [message.title for message in self.notifier.messages]

    def test_full_weekly_sequence_generates_and_sends_expected_notifications(self):
        # 1. start
        self.notify()
        self.assertEqual(self.titles(), ["[同行] 开工 · Synthetic run"])
        self.assertEqual(self.notifier.messages[0].level, "passive")
        self.notify()  # dedupe
        self.assertEqual(len(self.titles()), 1)

        # 2. source + preflight, English table human approval
        self.mark("l1.start", "started")
        self.mark("l1.start", "finished", evidence_level="E1")
        self.mark("l1.preflight", "started")
        self.mark("l1.preflight", "finished", evidence_level="E2")
        self.handoff("l1.english-review", "user English review", expected_minutes="10-20")
        self.notify()
        self.assertIn("[同行] 待批准 · 英文来源", self.titles())
        self.notify()  # dedupe while waiting
        self.assertEqual(self.titles().count("[同行] 待批准 · 英文来源"), 1)
        self.mark("l1.english-review", "resumed")
        self.mark("l1.english-review", "finished", evidence_level="E3")

        # 3. speaker mapping human confirmation, then translation
        self.mark("l2.translate.zh-Hans", "started")
        self.handoff("l1.speakers", "user speaker mapping")
        self.notify()
        self.assertIn("[同行] 待确认 · 讲员映射", self.titles())
        self.mark("l1.speakers", "resumed")
        self.mark("l1.speakers", "finished", evidence_level="E3")
        self.mark("l2.translate.zh-Hans", "progress", unit="rows", done=40, total=100)
        self.mark("l2.translate.zh-Hans", "finished", evidence_level="E1")

        # 4. a just-finished predecessor gets a 10-minute grace before "missing" is pushed
        self.notify()
        self.assertNotIn("[同行] 缺步骤 · l2.audit.zh-Hans", self.titles())
        self.clock.bump(run_status.MISSING_GRACE_SECONDS + 60)
        self.notify()
        self.assertIn("[同行] 缺步骤 · l2.audit.zh-Hans", self.titles())
        self.assertIn("[同行] 缺步骤 · l2.consistency", self.titles())
        self.mark("l2.audit.zh-Hans", "finished", evidence_level="E1")
        self.mark("l2.consistency", "started")
        self.mark("l2.consistency", "finished", evidence_level="E2")
        self.mark("l3.speech.zh-Hans", "started")
        self.mark("l3.speech.zh-Hans", "finished", evidence_level="E1")

        # 5. TTS stalls, then recovers
        self.mark("l3.tts.zh-Hans", "started", heartbeat_expected_seconds=30)
        self.clock.bump(200)
        self.notify()
        self.assertIn("[同行] 可能卡住 · l3.tts.zh-Hans", self.titles())
        self.mark("l3.tts.zh-Hans", "progress", unit="sentences", done=10, total=20)
        self.mark("l3.tts.zh-Hans", "finished", evidence_level="E1")

        # 6. finish fails, is retried and succeeds
        self.mark("l3.finish", "started")
        self.mark("l3.finish", "failed", error_class="infra", message="ssh timeout",
                  resume="retry finish_run")
        self.notify()
        failed = [message for message in self.notifier.messages if message.title == "[同行] 失败 · l3.finish"]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0].level, "timeSensitive")
        self.mark("l3.finish", "started")
        self.mark("l3.finish", "finished", evidence_level="E1")
        self.notify()  # no duplicate failure; finish is now complete
        self.assertEqual(self.titles().count("[同行] 失败 · l3.finish"), 1)

        # 7. lag gate, then track review
        self.mark("l3.lag-loop.zh-Hans", "started")
        self.mark("l3.lag-loop.zh-Hans", "finished", evidence_level="E2")
        self.handoff("l3.review.zh-Hans", "user track review",
                     action_url="http://127.0.0.1:8765/review-player.html", expected_minutes="20-80")
        self.notify()
        review = next(message for message in self.notifier.messages if message.title == "[同行] 可审 · zh-Hans 轨")
        self.assertEqual(review.level, "active")
        self.assertIsNone(review.url)  # localhost is never forwarded
        self.mark("l3.review.zh-Hans", "resumed")
        self.mark("l3.review.zh-Hans", "finished", evidence_level="E3")

        # 8. publish authorization + study approval
        self.handoff("l4.publish.authorization", "user publish authorization")
        self.notify()
        self.assertIn("[同行] 待授权 · 页面发布", self.titles())
        self.mark("l4.publish.authorization", "resumed")
        self.mark("l4.publish.authorization", "finished", evidence_level="E3")
        self.handoff("l4.study", "user study approval")
        self.notify()
        self.assertIn("[同行] 待批准 · 学习内容", self.titles())
        self.mark("l4.study", "resumed")
        self.mark("l4.study", "finished", evidence_level="E3")

        # 9. publish stages are observable but do not notify by themselves
        count_before_publish = len(self.notifier.messages)
        for stage, level in (("l4.assets", "E1"), ("l4.publish", "E4"), ("l4.verify", "E5")):
            self.mark(stage, "started")
            self.mark(stage, "finished", evidence_level=level)
        self.assertEqual(len(self.notifier.messages), count_before_publish)

        # 10. completion
        self.notify()
        self.assertIn(f"[同行] 完成 · {self.run.name}", self.titles())
        self.assertEqual(self.notifier.messages[-1].level, "active")
        snapshot = run_status.derive_snapshot(self.run, index=self.index, now=self.clock)
        self.assertEqual(snapshot["runState"], "completed")
        self.assertFalse(any(item["stage"].startswith("l3.review") for item in snapshot["attention"]))

        # all expected human fields made it into the messages; no secret/local path leaked
        joined = "\n".join(f"{m.title}\n{m.body}" for m in self.notifier.messages)
        self.assertIn("user English review", joined)
        self.assertIn("user track review", joined)
        self.assertIn("user publish authorization", joined)
        self.assertIn("user study approval", joined)
        self.assertNotIn("/Users/", joined)
        self.assertNotIn("127.0.0.1", joined)


if __name__ == "__main__":
    unittest.main()
