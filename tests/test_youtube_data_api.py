import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "youtube_data_api.py"
SPEC = importlib.util.spec_from_file_location("youtube_data_api", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class YouTubeDataApiTest(unittest.TestCase):
    def test_completed_live_video_normalizes_to_existing_post_live_contract(self):
        resource = {
            "id": "5GuhLMPflds",
            "snippet": {
                "title": "Test Sermon",
                "channelId": "channel",
                "channelTitle": "Mariners Church",
                "liveBroadcastContent": "none",
            },
            "contentDetails": {"duration": "PT1H14M38.5S"},
            "liveStreamingDetails": {
                "actualStartTime": "2026-07-11T23:00:00Z",
                "actualEndTime": "2026-07-12T00:14:38Z",
            },
            "status": {"privacyStatus": "public"},
        }
        metadata = mod.normalize_video_resource(resource)
        self.assertEqual(metadata["live_status"], "was_live")
        self.assertTrue(metadata["was_live"])
        self.assertEqual(metadata["duration"], 4478.5)
        self.assertEqual(metadata["metadata_provider"], "youtube-data-api-v3")

    def test_active_and_upcoming_states(self):
        active = mod.normalize_video_resource({
            "id": "active12345",
            "snippet": {"liveBroadcastContent": "live"},
            "liveStreamingDetails": {"actualStartTime": "2026-07-12T00:00:00Z"},
        })
        upcoming = mod.normalize_video_resource({
            "id": "future12345",
            "snippet": {"liveBroadcastContent": "upcoming"},
            "liveStreamingDetails": {"scheduledStartTime": "2026-07-19T15:30:00Z"},
        })
        self.assertEqual(active["live_status"], "is_live")
        self.assertEqual(upcoming["live_status"], "is_upcoming")

    def test_request_never_returns_api_key_in_metadata(self):
        captured = {}

        def requester(url, params, timeout):
            captured.update({"url": url, "params": params, "timeout": timeout})
            return FakeResponse(200, {"items": [{"id": "abc12345678", "snippet": {}}]})

        metadata = mod.video_metadata("abc12345678", api_key="secret-key", requester=requester)
        self.assertEqual(captured["params"]["key"], "secret-key")
        self.assertNotIn("secret-key", str(metadata))

    def test_api_error_is_sanitized_to_message(self):
        with self.assertRaises(mod.YouTubeDataApiError) as caught:
            mod.video_metadata(
                "abc12345678",
                api_key="secret-key",
                requester=lambda *_args, **_kwargs: FakeResponse(403, {"error": {"message": "API disabled"}}),
            )
        self.assertIn("HTTP 403", str(caught.exception))
        self.assertNotIn("secret-key", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
