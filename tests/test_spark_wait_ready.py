import unittest

from tools.ops import spark_wait_ready as subject
from scripts.spark_exclusive_session import SessionError


class FakeClient:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def require_ready(self):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.slept = []

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds

    def monotonic(self):
        return self.now


class WaitReadyTests(unittest.TestCase):
    def test_retries_competing_units_and_memory_until_ready(self):
        client = FakeClient([SessionError("competing_service_active:llama-server.service"),
                             SessionError("insufficient_available_memory"),
                             SessionError("competing_launcher_active"), {"status": "exclusive_ready"}])
        clock = FakeClock()
        report = subject.wait(client, poll_seconds=30, max_minutes=30, sleep=clock.sleep, clock=clock.monotonic,
                              now=lambda: "t")
        self.assertEqual(report["status"], "ready")
        self.assertEqual(client.calls, 4)
        self.assertEqual(clock.slept, [30, 30, 30])
        self.assertEqual([row["error"] for row in report["attempts"]],
                         ["competing_service_active:llama-server.service", "insufficient_available_memory",
                          "competing_launcher_active"])

    def test_unknown_or_closed_session_is_not_retried(self):
        for code in ("session_not_ready", "ssh_outcome_unknown_reconcile_before_retry", "unit_identity_changed",
                     "snapshot_lacks_unit:job-reasoning-review.timer"):
            with self.subTest(code=code):
                client = FakeClient([SessionError(code), {"status": "exclusive_ready"}])
                clock = FakeClock()
                report = subject.wait(client, sleep=clock.sleep, clock=clock.monotonic, now=lambda: "t")
                self.assertEqual((report["status"], report["reason"], client.calls), ("not_ready", code, 1))
                self.assertEqual(clock.slept, [])

    def test_gives_up_after_the_deadline(self):
        client = FakeClient([SessionError("competing_service_active:job-reasoning-review.timer")] * 100)
        clock = FakeClock()
        report = subject.wait(client, poll_seconds=60, max_minutes=5, sleep=clock.sleep, clock=clock.monotonic,
                              now=lambda: "t")
        self.assertEqual(report["status"], "timeout")
        self.assertEqual(report["reason"], "competing_service_active:job-reasoning-review.timer")
        # Polls at 0, 60, …, 300 s; the next poll would pass the 5-minute deadline.
        self.assertEqual(client.calls, 6)
        self.assertEqual(sum(clock.slept), 300)

    def test_bounds_are_explicit(self):
        with self.assertRaises(ValueError):
            subject.wait(FakeClient([]), poll_seconds=0.5)
        with self.assertRaises(ValueError):
            subject.wait(FakeClient([]), max_minutes=0)


if __name__ == "__main__":
    unittest.main()
