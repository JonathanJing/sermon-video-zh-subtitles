from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import patch

from backend.firebase_publisher import (
    AccessTokenProvider,
    CaptionProjector,
    FirebaseCaptionPublisher,
    FirebasePublisherConfig,
    LatestSnapshotQueue,
)


class AccessTokenProviderTest(unittest.TestCase):
    @patch("backend.firebase_publisher.subprocess.run")
    def test_uses_keyless_service_account_impersonation_when_configured(self, run) -> None:
        run.return_value.stdout = "short-lived-token\n"
        with patch.dict("os.environ", {
            "LOCAL_LIVE_FIREBASE_IMPERSONATE_SERVICE_ACCOUNT":
                "caption-publisher@example.iam.gserviceaccount.com",
        }, clear=True):
            provider = AccessTokenProvider()
            self.assertEqual(provider(), "short-lived-token")

        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], (
            "gcloud",
            "auth",
            "print-access-token",
            "--impersonate-service-account=caption-publisher@example.iam.gserviceaccount.com",
        ))

    @patch("backend.firebase_publisher.subprocess.run")
    def test_static_token_takes_precedence_without_invoking_gcloud(self, run) -> None:
        with patch.dict("os.environ", {
            "LOCAL_LIVE_FIREBASE_ACCESS_TOKEN": "injected-token",
            "LOCAL_LIVE_FIREBASE_IMPERSONATE_SERVICE_ACCOUNT":
                "caption-publisher@example.iam.gserviceaccount.com",
        }, clear=True):
            self.assertEqual(AccessTokenProvider()(), "injected-token")
        run.assert_not_called()


class CaptionProjectorTest(unittest.TestCase):
    def test_previous_caption_moves_only_after_completed_final(self) -> None:
        projector = CaptionProjector(expires_at_ms=999_999)
        projector.apply({
            "type": "asr.final",
            "segmentId": "seg-1",
            "sourceTextEn": "We walk by faith.",
        }, 100)
        projector.apply({
            "type": "translation.final",
            "segmentId": "seg-1",
            "sourceTextEn": "We walk by faith.",
            "targetTextZh": "我们凭信心而行。",
        }, 200)
        snapshot = projector.apply({
            "type": "asr.final",
            "segmentId": "seg-2",
            "sourceTextEn": "That changes tomorrow.",
        }, 300)

        self.assertEqual(snapshot["previousFinal"]["segmentId"], "seg-1")
        self.assertEqual(snapshot["active"]["segmentId"], "seg-2")
        self.assertEqual(snapshot["active"]["targetTextZh"], "")
        self.assertNotIn("metrics", snapshot)

    def test_stale_translation_is_not_published(self) -> None:
        projector = CaptionProjector(expires_at_ms=999_999)
        projector.apply({
            "type": "asr.final",
            "segmentId": "seg-2",
            "sourceTextEn": "Current.",
        }, 100)
        self.assertIsNone(projector.apply({
            "type": "translation.final",
            "segmentId": "seg-1",
            "sourceTextEn": "Old.",
            "targetTextZh": "旧句。",
        }, 200))

    def test_readable_display_ignores_raw_events_and_swaps_as_one_block(self) -> None:
        projector = CaptionProjector(expires_at_ms=999_999)
        first = projector.apply({
            "type": "caption.display",
            "segmentId": "seg-1",
            "sourceTextEn": "We walk by faith.",
            "targetTextZh": "我们凭信心而行。",
            "displayKind": "final",
        }, 100)
        self.assertIsNone(projector.apply({
            "type": "asr.final",
            "segmentId": "seg-2",
            "sourceTextEn": "That changes tomorrow.",
            "displayEligible": False,
        }, 200))
        self.assertEqual(projector.active, first["active"])

        snapshot = projector.apply({
            "type": "caption.display",
            "segmentId": "seg-2",
            "sourceTextEn": "That changes tomorrow.",
            "targetTextZh": "这改变了我们面对明天的方式。",
            "displayKind": "partial",
        }, 300)
        self.assertEqual(snapshot["previousFinal"]["segmentId"], "seg-1")
        self.assertEqual(snapshot["active"]["segmentId"], "seg-2")


class FirebaseCaptionPublisherTest(unittest.TestCase):
    def publisher(self, transport, **kwargs):
        return FirebaseCaptionPublisher(
            FirebasePublisherConfig(
                database_url="https://example.firebaseio.com",
                viewer_base_url="https://captions.example.org",
                session_ttl_seconds=60,
            ),
            transport=transport,
            **kwargs,
        )

    def test_slow_cloud_coalesces_1000_finals_and_preserves_session_end(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        writes = []

        def transport(_token, snapshot):
            entered.set()
            release.wait(timeout=5)
            writes.append(snapshot)

        publisher = self.publisher(transport)
        try:
            publisher.start_session("s1", "safe_token_1234567890123456")
            self.assertTrue(entered.wait(timeout=1))
            started = time.perf_counter()
            for index in range(1000):
                publisher.publish("s1", {
                    "type": "caption.display", "displayKind": "final",
                    "segmentId": f"seg-{index}", "sourceTextEn": f"Line {index}",
                    "targetTextZh": f"字幕 {index}",
                })
            publisher.end_session("s1")
            self.assertLess(time.perf_counter() - started, 1.0)
            self.assertEqual(publisher.work.qsize(), 1)
            self.assertEqual(publisher.coalesced_snapshot_count, 1000)
            self.assertEqual(publisher.dropped_final_count, 0)
            publisher.publish("s1", {
                "type": "asr.final", "segmentId": "late", "sourceTextEn": "Late",
            })
            release.set()
            publisher.work.join()
            self.assertEqual(len(writes), 2)
            self.assertEqual(writes[-1]["status"], "ended")
            self.assertEqual(writes[-1]["active"]["segmentId"], "seg-999")
            self.assertEqual(writes[-1]["previousFinal"]["segmentId"], "seg-998")
        finally:
            release.set()
            publisher.stop()

    def test_terminal_snapshot_retries_after_failure_without_new_caption(self) -> None:
        failed = threading.Event()
        recovered = threading.Event()
        writes = []

        def transport(_token, snapshot):
            if snapshot["status"] == "ended" and not failed.is_set():
                failed.set()
                raise OSError("temporary outage")
            writes.append(snapshot)
            if snapshot["status"] == "ended":
                recovered.set()

        publisher = self.publisher(transport)
        try:
            publisher.start_session("s1", "safe_token_1234567890123456")
            publisher.end_session("s1")
            self.assertTrue(failed.wait(timeout=1))
            self.assertTrue(recovered.wait(timeout=2))
            publisher.work.join()
            self.assertEqual(writes[-1]["status"], "ended")
            self.assertEqual(publisher.publish_failure_count, 1)
            self.assertIsNone(publisher.status()["lastError"])
        finally:
            publisher.stop()

    def test_resuming_same_token_uses_new_live_projector_and_sequence_base(self) -> None:
        writes = []
        publisher = self.publisher(lambda token, snapshot: writes.append((token, snapshot)))
        token = "safe_token_1234567890123456"
        try:
            publisher.start_session("s1", token, sequence_base=20)
            publisher.end_session("s1")
            publisher.work.join()
            self.assertEqual(writes[-1][1]["status"], "ended")
            publisher.start_session("s1", token, sequence_base=50)
            publisher.publish("s1", {
                "type": "caption.display", "segmentId": "resumed", "displayKind": "final",
                "sourceTextEn": "Resumed.", "targetTextZh": "已恢复。",
            })
            publisher.work.join()
            self.assertEqual(writes[-1][0], token)
            self.assertEqual(writes[-1][1]["status"], "live")
            self.assertEqual(writes[-1][1]["sequence"], 51)
            self.assertEqual(writes[-1][1]["active"]["segmentId"], "resumed")
            self.assertIsNone(writes[-1][1]["previousFinal"])
        finally:
            publisher.stop()

    def test_expired_pending_state_is_never_sent_after_cloud_recovers(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        now = [1000.0]
        writes = []

        def transport(_token, snapshot):
            writes.append(snapshot)
            entered.set()
            release.wait(timeout=5)

        publisher = self.publisher(transport, clock=lambda: now[0])
        try:
            publisher.start_session("s1", "safe_token_1234567890123456")
            self.assertTrue(entered.wait(timeout=1))
            publisher.end_session("s1")
            now[0] = 1061.0
            release.set()
            publisher.work.join()
            self.assertEqual(len(writes), 1)
            self.assertEqual(publisher.expired_snapshot_count, 1)
        finally:
            release.set()
            publisher.stop()

    def test_same_process_restart_supersedes_pending_end_with_default_sequence(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        writes = []

        def transport(_token, snapshot):
            entered.set()
            release.wait(timeout=5)
            writes.append(snapshot)

        publisher = self.publisher(transport)
        try:
            publisher.start_session("s1", "safe_token_1234567890123456")
            self.assertTrue(entered.wait(timeout=1))
            publisher.end_session("s1")
            publisher.start_session("s1", "safe_token_1234567890123456")
            release.set()
            publisher.work.join()
            self.assertEqual(writes[-1]["status"], "live")
            self.assertEqual(writes[-1]["sequence"], 2)
        finally:
            release.set()
            publisher.stop()

    def test_publisher_is_best_effort_and_throttles_partials(self) -> None:
        writes = []
        wrote = threading.Event()
        now = [1000.0]

        def transport(token, snapshot):
            writes.append((token, snapshot))
            wrote.set()

        publisher = FirebaseCaptionPublisher(
            FirebasePublisherConfig(
                database_url="https://example.firebaseio.com",
                viewer_base_url="https://captions.example.org",
                partial_interval_ms=500,
            ),
            transport=transport,
            clock=lambda: now[0],
        )
        try:
            url = publisher.start_session("session-1", "safe_token_1234567890123456")
            self.assertEqual(url, "https://captions.example.org/s/safe_token_1234567890123456")
            self.assertTrue(wrote.wait(timeout=1))
            wrote.clear()
            publisher.publish("session-1", {
                "type": "asr.final",
                "segmentId": "seg-1",
                "sourceTextEn": "Grace leads us.",
            })
            now[0] += 0.1
            publisher.publish("session-1", {
                "type": "translation.partial",
                "segmentId": "seg-1",
                "sourceTextEn": "Grace leads us.",
                "targetTextZh": "恩典",
            })
            now[0] += 0.1
            publisher.publish("session-1", {
                "type": "translation.partial",
                "segmentId": "seg-1",
                "sourceTextEn": "Grace leads us.",
                "targetTextZh": "恩典引领",
            })
            publisher.end_session("session-1")
            publisher.work.join()

            self.assertEqual(publisher.dropped_partial_count, 1)
            self.assertEqual(writes[-1][1]["status"], "ended")
            self.assertGreaterEqual(writes[-1][1]["sequence"], 3)
        finally:
            publisher.stop()

    def test_transport_failure_does_not_escape_to_live_path(self) -> None:
        failed = threading.Event()

        def transport(_token, _snapshot):
            failed.set()
            raise OSError("offline")

        publisher = FirebaseCaptionPublisher(
            FirebasePublisherConfig(
                database_url="https://example.firebaseio.com",
                viewer_base_url="https://captions.example.org",
            ),
            transport=transport,
        )
        try:
            publisher.start_session("session-1", "safe_token_1234567890123456")
            self.assertTrue(failed.wait(timeout=1))
            publisher.stop()
            self.assertEqual(publisher.status()["lastError"], "offline")
            self.assertGreaterEqual(publisher.publish_failure_count, 1)
            self.assertFalse(publisher.worker.is_alive())
        finally:
            publisher.stop()


class LatestSnapshotQueueTest(unittest.TestCase):
    @staticmethod
    def item(session, sequence=1, status="live"):
        return session, {"sequence": sequence, "status": status}, "final"

    def test_full_queue_replaces_latest_state_without_waiting(self) -> None:
        work = LatestSnapshotQueue(maxsize=32)
        for index in range(32):
            work.put_latest(self.item(str(index)))
        removed, reason = work.put_latest(self.item("31", 2, "ended"))
        self.assertEqual(reason, "coalesced")
        self.assertEqual(removed[1]["sequence"], 1)
        self.assertEqual(work.qsize(), 32)
        work.put_latest(self.item("new"))
        pending = []
        while not work.empty():
            pending.append(work.get_nowait())
            work.task_done()
        work.join()
        self.assertTrue(any(item[0] == "31" and item[1]["status"] == "ended" for item in pending))
        self.assertEqual(len(pending), 32)

    def test_late_retry_cannot_replace_newer_end_and_terminal_capacity_is_explicit(self) -> None:
        work = LatestSnapshotQueue(maxsize=2)
        work.put_latest(self.item("s1", 4, "ended"))
        removed, reason = work.put_latest(self.item("s1", 3))
        self.assertEqual(reason, "superseded")
        work.put_latest(self.item("s2", 1, "ended"))
        removed, reason = work.put_latest(self.item("s3"))
        self.assertEqual((removed[0], reason), ("s3", "overflow"))
        removed, reason = work.put_latest(self.item("s3", 2, "ended"))
        self.assertEqual((removed[0], reason), ("s1", "overflow"))
        self.assertEqual(work.qsize(), 2)


if __name__ == "__main__":
    unittest.main()
