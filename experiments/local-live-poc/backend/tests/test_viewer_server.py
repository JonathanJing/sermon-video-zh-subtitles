from __future__ import annotations

import json
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from backend.viewer_server import CaptionHub, ViewerService


class CaptionHubTest(unittest.TestCase):
    def test_projects_only_caption_fields_and_keeps_latest_snapshot(self) -> None:
        hub = CaptionHub()
        token = hub.start_session("session-1")
        subscriber = hub.subscribe(token)
        self.assertIsNotNone(subscriber)
        subscriber.get(timeout=1)
        hub.publish("session-1", {
            "type": "translation.final",
            "sourceTextEn": "Grace leads us.",
            "targetTextZh": "恩典引领我们。",
            "contextHitIds": ["private-pack-entry"],
            "metrics": {"private": True},
        })
        projected = subscriber.get(timeout=1)
        self.assertEqual(projected["targetTextZh"], "恩典引领我们。")
        self.assertNotIn("contextHitIds", projected)
        self.assertNotIn("metrics", projected)
        self.assertEqual(hub.snapshot(token)["sourceTextEn"], "Grace leads us.")

    def test_control_and_storage_events_are_not_shared(self) -> None:
        hub = CaptionHub()
        token = hub.start_session("session-1")
        subscriber = hub.subscribe(token)
        subscriber.get(timeout=1)
        hub.publish("session-1", {"type": "runtime_restart_requested", "secret": "no"})
        self.assertTrue(subscriber.empty())


class ViewerHttpTest(unittest.TestCase):
    def setUp(self) -> None:
        self.hub = CaptionHub()
        self.token = self.hub.start_session("session-http")
        self.service = ViewerService(self.hub, "127.0.0.1", 0)
        self.service.start()
        self.base = f"http://127.0.0.1:{self.service.port}"

    def tearDown(self) -> None:
        self.service.stop()

    def test_viewer_page_and_snapshot_are_read_only(self) -> None:
        with urlopen(f"{self.base}/view/{self.token}", timeout=2) as response:
            html = response.read().decode("utf-8")
            self.assertIn("现场中文字幕", html)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
        with urlopen(f"{self.base}/api/view/{self.token}/snapshot", timeout=2) as response:
            self.assertEqual(json.loads(response.read())["active"], True)
        request = Request(f"{self.base}/api/view/{self.token}/snapshot", data=b"{}", method="POST")
        with self.assertRaises(HTTPError) as caught:
            urlopen(request, timeout=2)
        self.assertEqual(caught.exception.code, 405)

    def test_unknown_token_is_not_disclosed(self) -> None:
        with self.assertRaises(HTTPError) as caught:
            urlopen(f"{self.base}/view/not-a-token", timeout=2)
        self.assertEqual(caught.exception.code, 404)

    def test_sse_stream_delivers_caption_updates(self) -> None:
        with urlopen(f"{self.base}/api/view/{self.token}/events", timeout=2) as response:
            self.assertEqual(response.headers["Content-Type"], "text/event-stream; charset=utf-8")
            self.assertTrue(response.readline().decode().startswith("id: 1"))
            snapshot = json.loads(response.readline().decode().removeprefix("data: "))
            self.assertEqual(snapshot["type"], "caption.snapshot")
            response.readline()
            self.hub.publish("session-http", {
                "type": "translation.final",
                "sourceTextEn": "Grace.",
                "targetTextZh": "恩典。",
            })
            self.assertTrue(response.readline().decode().startswith("id: 2"))
            update = json.loads(response.readline().decode().removeprefix("data: "))
            self.assertEqual(update["targetTextZh"], "恩典。")


if __name__ == "__main__":
    unittest.main()
