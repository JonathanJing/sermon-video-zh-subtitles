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


class AccountsTests(unittest.TestCase):
    def test_the_second_mac_is_a_bark_account_and_a_missing_key_is_simply_left_out(self):
        self.assertEqual(notify.ACCOUNTS, ("bark-iphone", "bark-mac", "bark-mbp14"))
        stored = {"bark-iphone": "A", "bark-mbp14": "C"}

        def keychain(command, **kwargs):
            account = command[command.index("-a") + 1]
            return completed(0, stored[account] + "\n") if account in stored else completed(44)
        self.assertEqual(notify.keychain_keys(run=keychain), {"bark-iphone": "A", "bark-mbp14": "C"})


class EmailChannelTests(unittest.TestCase):
    """The backup channel: everything that is not passive, never a reason to fail production."""

    def _notifier(self, mail):
        return notify.Notifier({"bark-iphone": "key", "bark-mac": "mac"}, post=lambda url, payload: {"code": 200},
                               local=lambda message: True, sleep=lambda seconds: None, mail=mail)

    def test_email_goes_out_for_everything_but_passive(self):
        sent = []
        notifier = self._notifier(lambda message: sent.append(message.title) or True)
        self.assertNotIn("email", notifier.send(notify.Message("开工", "b", "passive")))
        for level in ("active", "timeSensitive", "critical"):
            self.assertIs(notifier.send(notify.Message(level, "b", level))["email"], True)
        self.assertEqual(sent, ["active", "timeSensitive", "critical"])

    def test_no_mail_callable_means_no_email_key(self):
        results = self._notifier(None).send(notify.Message("t", "b", "active"))
        self.assertEqual(results, {"bark-iphone": True, "bark-mac": True})

    def test_a_mail_bug_does_not_raise_and_bark_still_counts(self):
        def boom(message):
            raise RuntimeError("smtp exploded")
        results = self._notifier(boom).send(notify.Message("t", "b", "timeSensitive"))
        self.assertIs(results["email"], False)
        self.assertTrue(notify.delivered(results))

    def test_email_alone_counts_as_delivered(self):
        notifier = notify.Notifier({}, post=lambda url, payload: {"code": 500}, local=lambda message: False,
                                   sleep=lambda seconds: None, mail=lambda message: True)
        self.assertTrue(notify.delivered(notifier.send(notify.Message("t", "b", "active"))))

    def test_send_email_builds_the_message_and_marks_urgent_ones(self):
        seen = {}

        class FakeSMTP:
            def __init__(self, host, port, timeout):
                seen["server"] = (host, port)
            def __enter__(self):
                return self
            def __exit__(self, *exc):
                return False
            def login(self, user, password):
                seen["login"] = (user, password)
            def send_message(self, mail):
                seen["mail"] = mail

        ok = notify.send_email(notify.Message("[同行] 待批准 · 英文表", "457 句", "timeSensitive", "https://mac.example.ts.net/english.html"),
                               credentials=("sender@example.com", "app-password", "to@example.com"), smtp_factory=FakeSMTP)
        self.assertTrue(ok)
        mail = seen["mail"]
        self.assertEqual((seen["server"], seen["login"]), (("smtp.gmail.com", 465), ("sender@example.com", "app-password")))
        self.assertEqual((mail["To"], mail["Subject"], mail["Importance"]), ("to@example.com", "[同行] 待批准 · 英文表", "high"))
        body = mail.get_content()
        self.assertIn("457 句", body)
        self.assertIn("https://mac.example.ts.net/english.html", body)
        self.assertNotIn("app-password", body)

    def test_send_email_without_credentials_or_on_smtp_error_returns_false(self):
        def no_keychain(command, **kwargs):
            return completed(44)
        self.assertIsNone(notify.email_credentials(run=no_keychain))

        class Refusing:
            def __init__(self, *args, **kwargs):
                raise OSError("network down")
        self.assertFalse(notify.send_email(notify.Message("t", "b", "active"),
                                           credentials=("a@example.com", "pw", "a@example.com"), smtp_factory=Refusing))

    def test_email_credentials_default_recipient_is_the_sender(self):
        stored = {"gmail-user": "sender@example.com", "gmail-app": "pw"}
        def keychain(command, **kwargs):
            account = command[command.index("-a") + 1]
            return completed(0, stored[account] + "\n") if account in stored else completed(44)
        self.assertEqual(notify.email_credentials(run=keychain), ("sender@example.com", "pw", "sender@example.com"))


if __name__ == "__main__":
    unittest.main()
