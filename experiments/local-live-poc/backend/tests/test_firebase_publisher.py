from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

from backend.firebase_publisher import (
    AccessTokenProvider,
    CaptionProjector,
    FirebaseCaptionPublisher,
    FirebasePublisherConfig,
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
            publisher.work.join()
            self.assertEqual(publisher.status()["lastError"], "offline")
        finally:
            publisher.stop()


if __name__ == "__main__":
    unittest.main()
