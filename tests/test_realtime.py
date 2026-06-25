import unittest
import tempfile
import json
from pathlib import Path

import backend.realtime as realtime
from backend.realtime import (
    OPENAI_TRANSLATION_CALLS_URL,
    OPENAI_TRANSLATION_CLIENT_SECRET_URL,
    GCS_UPLOAD_BASE_URL,
    METADATA_TOKEN_URL,
    SECRET_MANAGER_ACCESS_BASE_URL,
    GcsJsonApiUploader,
    RealtimeEventArchive,
    RealtimeSessionStore,
    access_secret_with_secret_manager_api,
    create_openai_translation_session,
    normalize_gcs_prefix,
    realtime_translation_policy_error,
    sanitize_event,
)


class RealtimeSessionStoreTest(unittest.TestCase):
    def test_create_session_sets_current_and_validates_event_token(self):
        store = RealtimeSessionStore()
        session = store.create(sunday="2026-06-28")

        self.assertEqual(store.current_session_id(), session.session_id)
        self.assertTrue(store.validate_event_token(session.session_id, session.event_token))
        self.assertFalse(store.validate_event_token(session.session_id, "wrong-token"))
        self.assertFalse(store.validate_event_token(session.session_id, None))

    def test_appends_and_reads_caption_events_after_cursor(self):
        store = RealtimeSessionStore()
        session = store.create(sunday="2026-06-28")
        first = store.append_event(
            session.session_id,
            {"type": "caption_delta", "text": "神爱世人", "segmentId": "seg_1"},
        )
        second = store.append_event(
            session.session_id,
            {"type": "caption_final", "text": "神爱世人。", "final": True, "segmentId": "seg_1"},
        )

        events = store.wait_for_events(session.session_id, after_id=first["id"], timeout=0)
        self.assertEqual([event["id"] for event in events], [second["id"], second["id"] + 1])
        self.assertEqual(events[0]["text"], "神爱世人。")
        self.assertTrue(events[0]["final"])
        self.assertEqual(events[1]["type"], "caption_stable")
        self.assertEqual(events[1]["segmentId"], "seg_1")

    def test_derives_caption_stable_for_semantic_realtime_boundary(self):
        store = RealtimeSessionStore()
        session = store.create(sunday="2026-06-28")
        store.append_event(
            session.session_id,
            {
                "type": "input_transcript_delta",
                "text": "God loved the world.",
                "segmentId": "seg_1",
                "source": "openai_realtime_translation_ws",
            },
        )
        draft = store.append_event(
            session.session_id,
            {
                "type": "caption_delta",
                "text": "神爱世人。",
                "segmentId": "seg_1",
                "source": "openai_realtime_translation_ws",
                "latencyMs": 980,
            },
        )

        events = store.wait_for_events(session.session_id, after_id=draft["id"], timeout=0)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "caption_stable")
        self.assertEqual(events[0]["zh"], "神爱世人。")
        self.assertEqual(events[0]["en"], "God loved the world.")
        self.assertEqual(events[0]["source"], "realtime-caption-stabilizer")
        self.assertEqual(events[0]["stability"], "stable")
        self.assertEqual(events[0]["stabilizerWindowMs"], 8000)
        self.assertEqual(events[0]["stabilizerWindow"]["windowMs"], 8000)
        self.assertEqual(events[0]["stabilizerWindow"]["segmentId"], "seg_1")
        self.assertEqual(events[0]["stabilizerWindow"]["inputTextEn"], "God loved the world.")
        self.assertEqual(events[0]["stabilizerWindow"]["draftZh"], "神爱世人。")
        self.assertEqual(events[0]["stabilizerWindow"]["sourceEventIds"], [2, 3])
        self.assertEqual(events[0]["latencyMs"], 980)

    def test_does_not_stabilize_connector_ending_delta(self):
        store = RealtimeSessionStore()
        session = store.create(sunday="2026-06-28")
        draft = store.append_event(
            session.session_id,
            {
                "type": "caption_delta",
                "text": "这很重要，因为",
                "segmentId": "seg_1",
                "source": "openai_realtime_translation_ws",
            },
        )

        events = store.wait_for_events(session.session_id, after_id=draft["id"], timeout=0)

        self.assertEqual(events, [])

    def test_sanitize_event_drops_untrusted_fields(self):
        event = sanitize_event(
            {
                "type": "caption_delta",
                "text": "hello",
                "apiKey": "sk-secret",
                "Authorization": "Bearer secret",
                "latencyMs": "1200",
            }
        )

        self.assertEqual(event["text"], "hello")
        self.assertEqual(event["latencyMs"], 1200)
        self.assertNotIn("apiKey", event)
        self.assertNotIn("Authorization", event)

    def test_sanitize_event_keeps_only_safe_stabilizer_window_fields(self):
        event = sanitize_event(
            {
                "type": "caption_stable",
                "text": "神爱世人。",
                "segmentId": "seg_1",
                "stabilizerWindow": {
                    "windowMs": "8000",
                    "segmentId": "seg_1",
                    "inputTextEn": "God loved the world.",
                    "draftZh": "神爱世人。",
                    "sourceEventIds": ["2", 3, "bad"],
                    "apiKey": "sk-secret",
                },
            }
        )

        self.assertEqual(event["stabilizerWindow"]["windowMs"], 8000)
        self.assertEqual(event["stabilizerWindow"]["sourceEventIds"], [2, 3])
        self.assertNotIn("apiKey", event["stabilizerWindow"])

    def test_archive_writes_sanitized_jsonl_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = RealtimeEventArchive(Path(tmp))
            store = RealtimeSessionStore(archive)
            session = store.create(sunday="2026-06-28")
            store.append_event(
                session.session_id,
                {
                    "type": "caption_delta",
                    "text": "神爱世人",
                    "Authorization": "Bearer secret",
                    "apiKey": "sk-secret",
                },
            )

            path = archive.path_for(session.session_id)
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            self.assertIn('"type": "session_started"', lines[0])
            self.assertIn('"text": "神爱世人"', lines[1])
            self.assertNotIn("Authorization", path.read_text(encoding="utf-8"))
            self.assertNotIn("sk-secret", path.read_text(encoding="utf-8"))

    def test_archive_status_reports_directory(self):
        store = RealtimeSessionStore(RealtimeEventArchive("/tmp/realtime-test"))

        self.assertTrue(store.archive_status()["enabled"])
        self.assertEqual(store.archive_status()["directory"], "/tmp/realtime-test")
        self.assertFalse(store.archive_status()["gcsMirrorEnabled"])

    def test_archive_can_mirror_jsonl_to_gcs_prefix(self):
        class FakeUploader:
            def __init__(self):
                self.uploads = []

            def upload(self, local_path, gcs_uri):
                self.uploads.append((Path(local_path), gcs_uri))

        with tempfile.TemporaryDirectory() as tmp:
            uploader = FakeUploader()
            archive = RealtimeEventArchive(
                Path(tmp),
                gcs_prefix="gs://sermon-zh-artifacts/realtime-events",
                uploader=uploader,
            )
            store = RealtimeSessionStore(archive)
            session = store.create(sunday="2026-06-28")
            store.append_event(session.session_id, {"type": "caption_final", "text": "神爱世人。"})
            archive.wait_for_pending_mirrors(timeout=2)

            self.assertEqual(len(uploader.uploads), 2)
            self.assertEqual(
                uploader.uploads[-1][1],
                f"gs://sermon-zh-artifacts/realtime-events/2026-06-28/{archive.path_for(session.session_id).name}",
            )
            self.assertTrue(uploader.uploads[-1][0].read_text(encoding="utf-8").endswith("\n"))
            self.assertTrue(archive.status()["gcsMirrorEnabled"])
            self.assertEqual(archive.status()["gcsPrefix"], "gs://sermon-zh-artifacts/realtime-events")
            self.assertTrue(archive.status()["gcsMirrorHealthy"])
            self.assertEqual(archive.status()["gcsMirrorPending"], 0)

    def test_gcs_json_api_uploader_uses_metadata_token_and_upload_endpoint(self):
        requests = []

        class FakeResponse:
            def __init__(self, body):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return self.body

        original_urlopen = realtime.urlopen
        try:
            def fake_urlopen(request, timeout):
                requests.append(
                    {
                        "url": request.full_url,
                        "headers": dict(request.header_items()),
                        "data": request.data,
                        "method": request.get_method(),
                        "timeout": timeout,
                    }
                )
                if request.full_url == METADATA_TOKEN_URL:
                    return FakeResponse(b'{"access_token":"metadata-token"}')
                return FakeResponse(b'{"name":"realtime-events/2026-06-28/rt.jsonl"}')

            realtime.urlopen = fake_urlopen
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "rt.jsonl"
                path.write_text('{"type":"caption_delta","zh":"神爱世人"}\n', encoding="utf-8")
                GcsJsonApiUploader().upload(
                    path,
                    "gs://sermon-zh-artifacts/realtime-events/2026-06-28/rt.jsonl",
                )
        finally:
            realtime.urlopen = original_urlopen

        self.assertEqual(requests[0]["url"], METADATA_TOKEN_URL)
        self.assertEqual(requests[0]["headers"]["Metadata-flavor"], "Google")
        self.assertEqual(requests[1]["method"], "POST")
        self.assertTrue(requests[1]["url"].startswith(f"{GCS_UPLOAD_BASE_URL}/sermon-zh-artifacts/o?"))
        self.assertIn("name=realtime-events%2F2026-06-28%2Frt.jsonl", requests[1]["url"])
        self.assertEqual(requests[1]["headers"]["Authorization"], "Bearer metadata-token")
        self.assertEqual(requests[1]["data"], b'{"type":"caption_delta","zh":"\xe7\xa5\x9e\xe7\x88\xb1\xe4\xb8\x96\xe4\xba\xba"}\n')

    def test_gcs_mirror_failure_does_not_block_realtime_event_storage(self):
        class FailingUploader:
            def upload(self, local_path, gcs_uri):
                raise RuntimeError("gcloud storage upload failed")

        with tempfile.TemporaryDirectory() as tmp:
            archive = RealtimeEventArchive(
                Path(tmp),
                gcs_prefix="gs://sermon-zh-artifacts/realtime-events",
                uploader=FailingUploader(),
            )
            store = RealtimeSessionStore(archive)
            session = store.create(sunday="2026-06-28")
            event = store.append_event(session.session_id, {"type": "caption_delta", "zh": "神爱世人"})
            archive.wait_for_pending_mirrors(timeout=2)

            events = store.wait_for_events(session.session_id, after_id=0, timeout=0)
            path = archive.path_for(session.session_id)
            status = archive.status()

            self.assertEqual(events[-1]["id"], event["id"])
            self.assertIn('"zh": "神爱世人"', path.read_text(encoding="utf-8"))
            self.assertTrue(status["gcsMirrorEnabled"])
            self.assertFalse(status["gcsMirrorHealthy"])
            self.assertEqual(status["gcsMirrorFailureCount"], 2)
            self.assertIn("upload failed", status["gcsMirrorLastError"]["error"])

    def test_rejects_unsafe_realtime_gcs_prefix(self):
        with self.assertRaises(ValueError):
            normalize_gcs_prefix("gs://bucket/../events")
        with self.assertRaises(ValueError):
            normalize_gcs_prefix("https://storage.googleapis.com/bucket/events")

    def test_create_openai_translation_session_uses_client_secret_endpoint(self):
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"value":"ek_test","expires_at":123,"session":{"model":"gpt-realtime-translate"}}'

        original_urlopen = realtime.urlopen
        try:
            def fake_urlopen(request, timeout):
                captured["url"] = request.full_url
                captured["headers"] = dict(request.header_items())
                captured["payload"] = json.loads(request.data.decode("utf-8"))
                captured["timeout"] = timeout
                return FakeResponse()

            realtime.urlopen = fake_urlopen
            data = create_openai_translation_session(
                api_key="sk-test",
                model="gpt-realtime-translate",
                target_language="zh",
            )
        finally:
            realtime.urlopen = original_urlopen

        self.assertEqual(captured["url"], OPENAI_TRANSLATION_CLIENT_SECRET_URL)
        self.assertEqual(captured["payload"]["session"]["type"], "realtime")
        self.assertEqual(captured["payload"]["session"]["model"], "gpt-realtime-translate")
        self.assertEqual(captured["payload"]["session"]["output_modalities"], ["text"])
        self.assertEqual(captured["payload"]["session"]["audio"]["input"]["transcription"]["model"], "gpt-4o-transcribe")
        self.assertEqual(captured["payload"]["session"]["audio"]["input"]["transcription"]["language"], "en")
        self.assertEqual(data["client_secret"]["value"], "ek_test")

    def test_secret_manager_api_access_uses_metadata_token_without_gcloud(self):
        requests = []

        class FakeResponse:
            def __init__(self, body):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return self.body

        original_urlopen = realtime.urlopen
        try:
            def fake_urlopen(request, timeout):
                requests.append(
                    {
                        "url": request.full_url,
                        "headers": dict(request.header_items()),
                        "timeout": timeout,
                    }
                )
                if request.full_url == METADATA_TOKEN_URL:
                    return FakeResponse(b'{"access_token":"metadata-token"}')
                return FakeResponse(b'{"payload":{"data":"c2stdGVzdAo="}}')

            realtime.urlopen = fake_urlopen
            value = access_secret_with_secret_manager_api(
                "projects/ai-for-god/secrets/openai-api-key/versions/latest"
            )
        finally:
            realtime.urlopen = original_urlopen

        self.assertEqual(value, "sk-test")
        self.assertEqual(requests[0]["url"], METADATA_TOKEN_URL)
        self.assertEqual(
            requests[1]["url"],
            f"{SECRET_MANAGER_ACCESS_BASE_URL}/projects/ai-for-god/secrets/openai-api-key/versions/latest:access",
        )
        self.assertEqual(requests[1]["headers"]["Authorization"], "Bearer metadata-token")

    def test_create_openai_translation_session_rejects_wrong_model_before_http(self):
        calls = []
        original_urlopen = realtime.urlopen
        try:
            def fake_urlopen(request, timeout):
                calls.append(request)
                raise AssertionError("urlopen should not be called for unsupported realtime model")

            realtime.urlopen = fake_urlopen
            with self.assertRaises(ValueError) as context:
                create_openai_translation_session(
                    api_key="sk-test",
                    model="gpt-realtime-2",
                    target_language="zh",
                )
        finally:
            realtime.urlopen = original_urlopen

        self.assertEqual(calls, [])
        self.assertIn("gpt-realtime-translate", str(context.exception))

    def test_realtime_translation_policy_rejects_non_chinese_target(self):
        error = realtime_translation_policy_error("gpt-realtime-translate", "es")

        self.assertEqual(error["error"], "unsupported_realtime_target_language")
        self.assertEqual(error["expectedTargetLanguage"], "zh")

    def test_translation_calls_endpoint_is_dedicated_webrtc_url(self):
        self.assertEqual(
            OPENAI_TRANSLATION_CALLS_URL,
            "https://api.openai.com/v1/realtime/calls",
        )


if __name__ == "__main__":
    unittest.main()
