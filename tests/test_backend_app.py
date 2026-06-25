import json
import io
import unittest
from pathlib import Path

from backend.app import ApiHandler, WEB_ROOT
from backend.config import AppConfig
from backend.realtime import RealtimeSessionStore


class BackendAppTest(unittest.TestCase):
    def test_static_root_serves_web_index(self):
        self.assertEqual(ApiHandler.static_path_for(ApiHandler, "/"), WEB_ROOT / "index.html")

    def test_static_pwa_route_falls_back_to_index(self):
        self.assertEqual(
            ApiHandler.static_path_for(ApiHandler, "/sundays/2026-06-21"),
            WEB_ROOT / "index.html",
        )

    def test_static_admin_route_serves_admin_page(self):
        self.assertEqual(ApiHandler.static_path_for(ApiHandler, "/admin"), WEB_ROOT / "admin.html")
        self.assertEqual(ApiHandler.static_path_for(ApiHandler, "/admin/"), WEB_ROOT / "admin.html")

    def test_static_path_rejects_escape(self):
        with self.assertRaises(FileNotFoundError):
            ApiHandler.static_path_for(ApiHandler, "/../README.md")

    def test_admin_status_sanitizes_secret_resource_names(self):
        test_case = self

        class FakeService:
            def _resolve_sunday(self, sunday):
                test_case.assertEqual(sunday, "current")
                return "2026-06-28"

            def get_public_slice(self, sunday):
                test_case.assertEqual(sunday, "current")
                return {
                    "status": "ready",
                    "generationMode": "youtube-live-archive",
                    "artifactCount": 2,
                    "sermonTitle": "Test Sermon",
                    "translationStatus": "ready",
                    "publishedAt": "2026-06-28T18:20:00+00:00",
                    "readiness": {
                        "state": "published",
                        "publicArtifactsReady": True,
                        "fallback": False,
                        "sourceMode": "youtube-live-archive",
                        "publishedAt": "2026-06-28T18:20:00+00:00",
                    },
                }

        handler = object.__new__(ApiHandler)
        handler.config = AppConfig(
            artifact_bucket="sermon-zh-artifacts-ai-for-god",
            artifact_prefix="sundays",
            current_manifest_uri=None,
            sunday_manifest_uri_template=None,
            timezone="America/Los_Angeles",
            openai_api_key_secret="projects/123/secrets/openai-api-key/versions/latest",
            operator_admin_token="secret-token",
            internal_task_token=None,
            enable_inline_worker=False,
        )
        handler.service = FakeService()
        handler.realtime_store = RealtimeSessionStore()
        status = ApiHandler.admin_status(handler)
        text = str(status)
        self.assertEqual(status["secrets"]["openaiApiKey"], "configured")
        self.assertEqual(status["secrets"]["operatorAdminToken"], "configured")
        self.assertEqual(status["artifact"]["generationMode"], "youtube-live-archive")
        self.assertEqual(status["captions"]["publishedAt"], "2026-06-28T18:20:00+00:00")
        self.assertEqual(status["readiness"]["state"], "published")
        self.assertFalse(status["readiness"]["fallback"])
        self.assertEqual(status["settings"]["sourceDiscoveryEndpoint"], "/api/admin/sundays/{sunday}/discover-source")
        self.assertFalse(status["realtime"]["eventArchive"]["enabled"])
        self.assertNotIn("projects/123/secrets", text)
        self.assertNotIn("secret-token", text)

    def test_local_realtime_session_create_returns_event_token_without_client_secret(self):
        handler = object.__new__(ApiHandler)
        handler.config = AppConfig(
            artifact_bucket=None,
            artifact_prefix="sundays",
            current_manifest_uri=None,
            sunday_manifest_uri_template=None,
            timezone="America/Los_Angeles",
            openai_api_key_secret=None,
            operator_admin_token=None,
            internal_task_token=None,
            enable_inline_worker=False,
        )
        handler.headers = {}
        handler.realtime_store = RealtimeSessionStore()
        handler.read_json_body = lambda: {
            "sunday": "2026-06-28",
            "model": "gpt-realtime-translate",
            "targetLanguage": "zh",
            "source": "ipad-mic",
        }
        captured = {}
        handler.write_json = lambda payload, status=200: captured.update(
            {"payload": payload, "status": status}
        )

        ApiHandler.handle_realtime_local_session_create(handler)

        self.assertEqual(captured["status"], 201)
        self.assertEqual(captured["payload"]["status"], "ready")
        self.assertIn("sessionId", captured["payload"])
        self.assertIn("eventToken", captured["payload"])
        self.assertIsNone(captured["payload"]["webrtc"])
        self.assertEqual(captured["payload"]["audioSourceKind"], "ipad_mic")
        self.assertNotIn("clientSecret", captured["payload"])

    def test_local_realtime_session_rejects_non_translate_model(self):
        handler = object.__new__(ApiHandler)
        handler.config = AppConfig(
            artifact_bucket=None,
            artifact_prefix="sundays",
            current_manifest_uri=None,
            sunday_manifest_uri_template=None,
            timezone="America/Los_Angeles",
            openai_api_key_secret=None,
            operator_admin_token=None,
            internal_task_token=None,
            enable_inline_worker=False,
        )
        handler.headers = {}
        handler.realtime_store = RealtimeSessionStore()
        handler.read_json_body = lambda: {
            "sunday": "2026-06-28",
            "model": "gpt-realtime-2",
            "targetLanguage": "zh",
            "source": "ipad-mic",
        }
        captured = {}
        handler.write_json = lambda payload, status=200: captured.update(
            {"payload": payload, "status": status}
        )

        ApiHandler.handle_realtime_local_session_create(handler)

        self.assertEqual(captured["status"], 400)
        self.assertEqual(captured["payload"]["error"], "unsupported_realtime_model")
        self.assertEqual(captured["payload"]["expectedModel"], "gpt-realtime-translate")
        self.assertIsNone(handler.realtime_store.current_session_id())

    def test_realtime_webrtc_session_rejects_non_chinese_target_before_openai_call(self):
        handler = object.__new__(ApiHandler)
        handler.config = AppConfig(
            artifact_bucket=None,
            artifact_prefix="sundays",
            current_manifest_uri=None,
            sunday_manifest_uri_template=None,
            timezone="America/Los_Angeles",
            openai_api_key_secret=None,
            operator_admin_token=None,
            internal_task_token=None,
            enable_inline_worker=False,
        )
        handler.headers = {}
        handler.realtime_store = RealtimeSessionStore()
        handler.read_json_body = lambda: {
            "sunday": "2026-06-28",
            "model": "gpt-realtime-translate",
            "targetLanguage": "es",
            "source": "ipad-mic",
        }
        captured = {}
        handler.write_json = lambda payload, status=200: captured.update(
            {"payload": payload, "status": status}
        )

        ApiHandler.handle_realtime_session_create(handler)

        self.assertEqual(captured["status"], 400)
        self.assertEqual(captured["payload"]["error"], "unsupported_realtime_target_language")
        self.assertEqual(captured["payload"]["expectedTargetLanguage"], "zh")
        self.assertIsNone(handler.realtime_store.current_session_id())

    def test_admin_token_can_post_only_stable_realtime_correction_without_event_token(self):
        handler = object.__new__(ApiHandler)
        handler.config = AppConfig(
            artifact_bucket=None,
            artifact_prefix="sundays",
            current_manifest_uri=None,
            sunday_manifest_uri_template=None,
            timezone="America/Los_Angeles",
            openai_api_key_secret=None,
            operator_admin_token=None,
            internal_task_token="task-token",
            enable_inline_worker=False,
        )
        handler.headers = {"X-Internal-Task-Token": "task-token"}
        handler.realtime_store = RealtimeSessionStore()
        session = handler.realtime_store.create(sunday="2026-06-28")
        event_count = len(handler.realtime_store.get(session.session_id).events)
        handler.read_json_body = lambda: {
            "type": "caption_final",
            "source": "gpt-5.4-mini-stable-correction",
            "model": "gpt-5.4-mini",
            "segmentId": "seg_1",
            "text": "耶稣是我们的中保。",
            "zh": "耶稣是我们的中保。",
            "final": True,
        }
        captured = {}
        handler.write_json = lambda payload, status=200: captured.update(
            {"payload": payload, "status": status}
        )

        ApiHandler.handle_realtime_event_post(handler, session.session_id)

        self.assertEqual(captured["status"], 202)
        event = handler.realtime_store.get(session.session_id).events[-1]
        self.assertEqual(event["source"], "gpt-5.4-mini-stable-correction")
        self.assertEqual(event["model"], "gpt-5.4-mini")

    def test_admin_token_can_post_stable_realtime_correction_with_zh_only(self):
        handler = object.__new__(ApiHandler)
        handler.config = AppConfig(
            artifact_bucket=None,
            artifact_prefix="sundays",
            current_manifest_uri=None,
            sunday_manifest_uri_template=None,
            timezone="America/Los_Angeles",
            openai_api_key_secret=None,
            operator_admin_token=None,
            internal_task_token="task-token",
            enable_inline_worker=False,
        )
        handler.headers = {"X-Internal-Task-Token": "task-token"}
        handler.realtime_store = RealtimeSessionStore()
        session = handler.realtime_store.create(sunday="2026-06-28")
        event_count = len(handler.realtime_store.get(session.session_id).events)
        handler.read_json_body = lambda: {
            "type": "caption_final",
            "source": "gpt-5.4-mini-stable-correction",
            "model": "gpt-5.4-mini",
            "segmentId": "seg_1",
            "zh": "神爱世人。",
            "final": True,
        }
        captured = {}
        handler.write_json = lambda payload, status=200: captured.update(
            {"payload": payload, "status": status}
        )

        ApiHandler.handle_realtime_event_post(handler, session.session_id)

        self.assertEqual(captured["status"], 202)
        event = handler.realtime_store.get(session.session_id).events[-1]
        self.assertEqual(event["zh"], "神爱世人。")

    def test_admin_token_cannot_post_nonfinal_stable_realtime_correction_without_event_token(self):
        handler = object.__new__(ApiHandler)
        handler.config = AppConfig(
            artifact_bucket=None,
            artifact_prefix="sundays",
            current_manifest_uri=None,
            sunday_manifest_uri_template=None,
            timezone="America/Los_Angeles",
            openai_api_key_secret=None,
            operator_admin_token=None,
            internal_task_token="task-token",
            enable_inline_worker=False,
        )
        handler.headers = {"X-Internal-Task-Token": "task-token"}
        handler.realtime_store = RealtimeSessionStore()
        session = handler.realtime_store.create(sunday="2026-06-28")
        event_count = len(handler.realtime_store.get(session.session_id).events)
        handler.read_json_body = lambda: {
            "type": "caption_final",
            "source": "gpt-5.4-mini-stable-correction",
            "model": "gpt-5.4-mini",
            "segmentId": "seg_1",
            "zh": "神爱世人。",
            "final": False,
        }
        captured = {}
        handler.write_json = lambda payload, status=200: captured.update(
            {"payload": payload, "status": status}
        )

        ApiHandler.handle_realtime_event_post(handler, session.session_id)

        self.assertEqual(captured["status"], 401)
        self.assertEqual(captured["payload"]["error"], "unauthorized")
        self.assertEqual(len(handler.realtime_store.get(session.session_id).events), event_count)

    def test_admin_token_cannot_post_unsegmented_stable_realtime_correction_without_event_token(self):
        handler = object.__new__(ApiHandler)
        handler.config = AppConfig(
            artifact_bucket=None,
            artifact_prefix="sundays",
            current_manifest_uri=None,
            sunday_manifest_uri_template=None,
            timezone="America/Los_Angeles",
            openai_api_key_secret=None,
            operator_admin_token=None,
            internal_task_token="task-token",
            enable_inline_worker=False,
        )
        handler.headers = {"X-Internal-Task-Token": "task-token"}
        handler.realtime_store = RealtimeSessionStore()
        session = handler.realtime_store.create(sunday="2026-06-28")
        event_count = len(handler.realtime_store.get(session.session_id).events)
        handler.read_json_body = lambda: {
            "type": "caption_final",
            "source": "gpt-5.4-mini-stable-correction",
            "model": "gpt-5.4-mini",
            "zh": "神爱世人。",
            "final": True,
        }
        captured = {}
        handler.write_json = lambda payload, status=200: captured.update(
            {"payload": payload, "status": status}
        )

        ApiHandler.handle_realtime_event_post(handler, session.session_id)

        self.assertEqual(captured["status"], 401)
        self.assertEqual(captured["payload"]["error"], "unauthorized")
        self.assertEqual(len(handler.realtime_store.get(session.session_id).events), event_count)

    def test_admin_token_cannot_post_realtime_draft_event_without_event_token(self):
        handler = object.__new__(ApiHandler)
        handler.config = AppConfig(
            artifact_bucket=None,
            artifact_prefix="sundays",
            current_manifest_uri=None,
            sunday_manifest_uri_template=None,
            timezone="America/Los_Angeles",
            openai_api_key_secret=None,
            operator_admin_token="operator-token",
            internal_task_token=None,
            enable_inline_worker=False,
        )
        handler.headers = {"Authorization": "Bearer operator-token"}
        handler.realtime_store = RealtimeSessionStore()
        session = handler.realtime_store.create(sunday="2026-06-28")
        handler.read_json_body = lambda: {
            "type": "caption_delta",
            "source": "openai-realtime-webrtc",
            "text": "神爱世人",
            "zh": "神爱世人",
        }
        captured = {}
        handler.write_json = lambda payload, status=200: captured.update(
            {"payload": payload, "status": status}
        )

        ApiHandler.handle_realtime_event_post(handler, session.session_id)

        self.assertEqual(captured["status"], 401)
        self.assertEqual(captured["payload"]["error"], "unauthorized")

    def test_realtime_output_transcript_delta_is_saved_and_rendered_as_sse(self):
        handler = object.__new__(ApiHandler)
        handler.config = AppConfig(
            artifact_bucket=None,
            artifact_prefix="sundays",
            current_manifest_uri=None,
            sunday_manifest_uri_template=None,
            timezone="America/Los_Angeles",
            openai_api_key_secret=None,
            operator_admin_token=None,
            internal_task_token=None,
            enable_inline_worker=False,
        )
        handler.realtime_store = RealtimeSessionStore()
        session = handler.realtime_store.create(sunday="2026-06-28")
        handler.headers = {"X-Realtime-Event-Token": session.event_token}
        handler.read_json_body = lambda: {
            "type": "caption_delta",
            "source": "openai-realtime-webrtc",
            "segmentId": "resp_delta_1",
            "delta": "神爱世人",
            "zh": "神爱世人",
            "openaiEventType": "session.output_transcript.delta",
        }
        captured = {}
        handler.write_json = lambda payload, status=200: captured.update(
            {"payload": payload, "status": status}
        )

        ApiHandler.handle_realtime_event_post(handler, session.session_id)

        self.assertEqual(captured["status"], 202)
        event = handler.realtime_store.get(session.session_id).events[-1]
        self.assertEqual(event["type"], "caption_delta")
        self.assertEqual(event["zh"], "神爱世人")
        self.assertEqual(event["delta"], "神爱世人")
        self.assertEqual(event["openaiEventType"], "session.output_transcript.delta")

        sse_handler = object.__new__(ApiHandler)
        sse_handler.wfile = io.BytesIO()
        ApiHandler.write_sse_event(sse_handler, event)

        sse_text = sse_handler.wfile.getvalue().decode("utf-8")
        self.assertIn("event: caption_delta", sse_text)
        self.assertIn('"zh": "神爱世人"', sse_text)
        self.assertIn('"openaiEventType": "session.output_transcript.delta"', sse_text)

    def test_realtime_input_transcript_delta_is_saved_and_rendered_as_sse(self):
        handler = object.__new__(ApiHandler)
        handler.config = AppConfig(
            artifact_bucket=None,
            artifact_prefix="sundays",
            current_manifest_uri=None,
            sunday_manifest_uri_template=None,
            timezone="America/Los_Angeles",
            openai_api_key_secret=None,
            operator_admin_token=None,
            internal_task_token=None,
            enable_inline_worker=False,
        )
        handler.realtime_store = RealtimeSessionStore()
        session = handler.realtime_store.create(sunday="2026-06-28")
        handler.headers = {"X-Realtime-Event-Token": session.event_token}
        handler.read_json_body = lambda: {
            "type": "input_transcript_delta",
            "source": "openai-realtime-webrtc",
            "segmentId": "resp_delta_1",
            "delta": "God loved the world",
            "en": "God loved the world",
            "openaiEventType": "session.input_transcript.delta",
        }
        captured = {}
        handler.write_json = lambda payload, status=200: captured.update(
            {"payload": payload, "status": status}
        )

        ApiHandler.handle_realtime_event_post(handler, session.session_id)

        self.assertEqual(captured["status"], 202)
        event = handler.realtime_store.get(session.session_id).events[-1]
        self.assertEqual(event["type"], "input_transcript_delta")
        self.assertEqual(event["en"], "God loved the world")
        self.assertEqual(event["delta"], "God loved the world")
        self.assertEqual(event["openaiEventType"], "session.input_transcript.delta")

        sse_handler = object.__new__(ApiHandler)
        sse_handler.wfile = io.BytesIO()
        ApiHandler.write_sse_event(sse_handler, event)

        sse_text = sse_handler.wfile.getvalue().decode("utf-8")
        self.assertIn("event: input_transcript_delta", sse_text)
        self.assertIn('"en": "God loved the world"', sse_text)
        self.assertIn('"openaiEventType": "session.input_transcript.delta"', sse_text)

    def test_live_source_discovery_requires_authorization(self):
        handler = object.__new__(ApiHandler)
        handler.config = AppConfig(
            artifact_bucket=None,
            artifact_prefix="sundays",
            current_manifest_uri=None,
            sunday_manifest_uri_template=None,
            timezone="America/Los_Angeles",
            openai_api_key_secret=None,
            operator_admin_token="operator-token",
            internal_task_token=None,
            enable_inline_worker=False,
        )
        handler.headers = {}
        captured = {}
        handler.write_json = lambda payload, status=200: captured.update(
            {"payload": payload, "status": status}
        )

        ApiHandler.handle_live_source_discovery(handler, "2026-06-28")

        self.assertEqual(captured["status"], 401)
        self.assertEqual(captured["payload"]["error"], "unauthorized")

    def test_live_source_discovery_returns_sanitized_generation_request(self):
        handler = object.__new__(ApiHandler)
        handler.config = AppConfig(
            artifact_bucket=None,
            artifact_prefix="sundays",
            current_manifest_uri=None,
            sunday_manifest_uri_template=None,
            timezone="America/Los_Angeles",
            openai_api_key_secret=None,
            operator_admin_token=None,
            internal_task_token="task-token",
            enable_inline_worker=False,
        )
        handler.headers = {"X-Internal-Task-Token": "task-token"}
        handler.read_json_body = lambda: {
            "expectedTitle": "The Cure for Our Rebellion - Eric Geiger | Mariners Church",
            "now": "2026-06-28T08:24:00-07:00",
            "sources": [
                {
                    "kind": "youtube-streams",
                    "service": "830",
                    "url": "https://www.youtube.com/watch?v=early",
                    "state": "live",
                    "sameSermonConfidence": 0.91,
                }
            ],
        }
        captured = {}
        handler.write_json = lambda payload, status=200: captured.update(
            {"payload": payload, "status": status}
        )

        ApiHandler.handle_live_source_discovery(handler, "2026-06-28")

        payload = captured["payload"]
        self.assertEqual(captured["status"], 202)
        self.assertEqual(payload["status"], "source_detected")
        self.assertEqual(payload["selectedSource"]["service"], "830")
        self.assertEqual(payload["generationRequest"]["liveUrl"], "https://www.youtube.com/watch?v=early")
        self.assertFalse(payload["apiKeyMaterialIncluded"])
        self.assertFalse(payload["secretResourceNamesIncluded"])
        self.assertNotIn("/secrets/", json.dumps(payload))

    def test_live_source_discovery_auto_generate_returns_plan_summary_without_secret_reference(self):
        class FakeService:
            def _resolve_sunday(self, sunday):
                return "2026-06-28" if sunday == "current" else sunday

        handler = object.__new__(ApiHandler)
        handler.config = AppConfig(
            artifact_bucket="sermon-zh-artifacts-ai-for-god",
            artifact_prefix="sundays",
            current_manifest_uri=None,
            sunday_manifest_uri_template=None,
            timezone="America/Los_Angeles",
            openai_api_key_secret="projects/p/secrets/openai-api-key/versions/latest",
            operator_admin_token=None,
            internal_task_token="task-token",
            enable_inline_worker=False,
        )
        handler.service = FakeService()
        handler.headers = {"X-Internal-Task-Token": "task-token"}
        handler.read_json_body = lambda: {
            "autoGenerate": True,
            "sources": [
                {
                    "kind": "youtube-streams",
                    "service": "1000",
                    "url": "https://www.youtube.com/watch?v=ten",
                    "state": "upcoming",
                    "sameSermonConfidence": 0.92,
                }
            ],
        }
        captured = {}
        handler.write_json = lambda payload, status=200: captured.update(
            {"payload": payload, "status": status}
        )

        ApiHandler.handle_live_source_discovery(handler, "current")

        payload = captured["payload"]
        self.assertEqual(captured["status"], 202)
        self.assertEqual(payload["sunday"], "2026-06-28")
        self.assertEqual(payload["generationRequest"]["sunday"], "2026-06-28")
        self.assertEqual(payload["generationPlan"]["status"], "planned")
        self.assertEqual(payload["generationPlan"]["commandCount"], 8)
        self.assertIn("sundays/2026-06-28/runs/", payload["generationPlan"]["prefix"])
        self.assertNotIn("sundays/current", json.dumps(payload))
        self.assertNotIn("commands", payload["generationPlan"])
        self.assertFalse(payload["secretResourceNamesIncluded"])
        self.assertNotIn("projects/p/secrets", json.dumps(payload))

    def test_dockerfile_starts_backend_app(self):
        dockerfile = Path(__file__).resolve().parents[1] / "Dockerfile"
        text = dockerfile.read_text(encoding="utf-8")
        self.assertIn("COPY requirements.txt", text)
        self.assertIn("pip install", text)
        self.assertIn("COPY backend/", text)
        self.assertIn('CMD ["python", "-m", "backend.app"]', text)


if __name__ == "__main__":
    unittest.main()
