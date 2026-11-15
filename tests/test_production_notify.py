"""Tests for the reusable Bark transport (no network, no keychain reads)."""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPS = ROOT / "tools" / "ops"
if str(OPS) not in sys.path:
    sys.path.insert(0, str(OPS))
import notify  # noqa: E402


class FakePost:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, url, payload):
        self.calls.append((url, payload))
        return self.replies.pop(0) if self.replies else {"code": 200}


def completed(returncode=0, stdout=""):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="")


class NotifyTransportTests(unittest.TestCase):
    def test_payload_carries_group_level_and_url(self):
        post = FakePost([{"code": 200}])
        notifier = notify.Notifier({"bark-iphone": "key"}, post=post,
                                   local=lambda message: True, sleep=lambda seconds: None)
        results = notifier.send(notify.Message("[同行] 可审", "body", "active",
                                               url="https://example.test/status"))
        self.assertTrue(results["bark-iphone"])
        payload = post.calls[0][1]
        self.assertEqual(payload["device_key"], "key")
        self.assertEqual(payload["group"], notify.GROUP)
        self.assertEqual(payload["level"], "active")
        self.assertEqual(payload["url"], "https://example.test/status")
        self.assertEqual(payload["isArchive"], "1")

    def test_retries_then_succeeds(self):
        post = FakePost([{"code": 500, "message": "down"}, {"code": 502}, {"code": 200}])
        sleeps = []
        notifier = notify.Notifier({"bark-iphone": "key"}, post=post,
                                   local=lambda message: True, sleep=sleeps.append, attempts=3)
        self.assertTrue(notifier.send(notify.Message("t", "b"))["bark-iphone"])
        self.assertEqual(len(post.calls), 3)
        self.assertEqual(sleeps, [2, 4])

    def test_mac_failure_falls_back_to_local_and_never_raises(self):
        local_calls = []
        notifier = notify.Notifier({"bark-mac": "key"},
                                   post=lambda url, payload: (_ for _ in ()).throw(OSError("offline")),
                                   local=lambda message: local_calls.append(message) or True,
                                   sleep=lambda seconds: None, attempts=1)
        results = notifier.send(notify.Message("t", "b", "timeSensitive"))
        self.assertFalse(results["bark-mac"])
        self.assertTrue(results["local"])
        self.assertEqual(len(local_calls), 1)

    def test_passive_does_not_fall_back_to_local(self):
        local_calls = []
        notifier = notify.Notifier({}, post=lambda url, payload: {"code": 200},
                                   local=lambda message: local_calls.append(message) or True,
                                   sleep=lambda seconds: None)
        results = notifier.send(notify.Message("t", "b", "passive"))
        self.assertEqual(results, {})
        self.assertEqual(local_calls, [])

    def test_no_push_prints_without_network(self):
        notifier = notify.Notifier({}, post=lambda url, payload: {"code": 200},
                                   local=lambda message: True, push=False)
        self.assertEqual(notifier.send(notify.Message("t", "b")), {"printed": True})

    def test_keychain_skips_missing_accounts(self):
        def run(command, **kwargs):
            account = command[command.index("-a") + 1]
            return completed(0, "secret\n") if account == "bark-iphone" else completed(1)

        keys = notify.keychain_keys(("bark-iphone", "bark-mac"), run=run)
        self.assertEqual(keys, {"bark-iphone": "secret"})

    def test_message_rejects_unknown_level(self):
        with self.assertRaisesRegex(ValueError, "Bark level"):
            notify.Message("t", "b", "loud")


if __name__ == "__main__":
    unittest.main()
