import importlib.util
import json
import sys
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "stabilize_realtime_deltas_with_openai.py"
SPEC = importlib.util.spec_from_file_location("stabilize_realtime_deltas_with_openai", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class StabilizeRealtimeDeltasWithOpenAITest(unittest.TestCase):
    def test_builds_candidates_from_final_input_transcripts_and_draft_zh(self):
        events = [
            {
                "id": 1,
                "type": "caption_delta",
                "segmentId": "seg_1",
                "delta": "耶稣是",
            },
            {
                "id": 2,
                "type": "caption_final",
                "segmentId": "seg_1",
                "text": "耶稣是我们的中保。",
                "final": True,
            },
            {
                "id": 3,
                "type": "input_transcript_final",
                "segmentId": "seg_1",
                "text": "Jesus is our mediator.",
                "createdAt": "2026-06-25T00:00:00Z",
            },
        ]

        candidates = mod.stable_correction_candidates(events, max_windows=None)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["id"], "seg_1")
        self.assertEqual(candidates[0]["en"], "Jesus is our mediator.")
        self.assertEqual(candidates[0]["draftZh"], "耶稣是我们的中保。")
        self.assertEqual(candidates[0]["sourceEventId"], 3)

    def test_builds_candidate_from_input_deltas_when_final_is_missing(self):
        events = [
            {"id": 1, "type": "input_transcript_delta", "delta": "Jesus is "},
            {"id": 2, "type": "input_transcript_delta", "delta": "our mediator."},
        ]

        candidates = mod.stable_correction_candidates(events, max_windows=None)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["id"], "rt_stable_0001")
        self.assertEqual(candidates[0]["en"], "Jesus is our mediator.")

    def test_uses_caption_stable_as_correction_draft(self):
        events = [
            {"id": 1, "type": "caption_delta", "segmentId": "seg_1", "delta": "耶稣是"},
            {
                "id": 2,
                "type": "caption_stable",
                "segmentId": "seg_1",
                "zh": "耶稣是中保。",
                "stability": "stable",
            },
            {
                "id": 3,
                "type": "input_transcript_final",
                "segmentId": "seg_1",
                "text": "Jesus is our mediator.",
            },
        ]

        candidates = mod.stable_correction_candidates(events, max_windows=None)

        self.assertEqual(candidates[0]["draftZh"], "耶稣是中保。")

    def test_build_output_omits_secret_resource_name(self):
        output = mod.build_output(
            input_jsonl=Path("artifacts/realtime.jsonl"),
            model="gpt-5.4-mini",
            candidates=[{"id": "seg_1", "en": "Jesus is our mediator.", "draftZh": "耶稣是中保。"}],
            corrections=[{"id": "seg_1", "zh": "耶稣是我们的中保。", "note": "术语修正。"}],
            api_key_secret="projects/p/secrets/openai-api-key/versions/latest",
        )
        rendered = json.dumps(output, ensure_ascii=False)

        self.assertEqual(output["status"], "ready")
        self.assertEqual(output["segments"][0]["stableZh"], "耶稣是我们的中保。")
        self.assertFalse(output["apiKeyMaterialIncluded"])
        self.assertFalse(output["secretResourceNamesIncluded"])
        self.assertNotIn("projects/p/secrets", rendered)
        self.assertNotIn("openai-api-key", rendered)

    def test_rejects_raw_api_key_material_for_secret_reference(self):
        with self.assertRaises(SystemExit):
            mod.validate_secret_resource_name("sk-this-looks-like-raw-key-material")

    def test_rejects_realtime_model_for_stable_correction(self):
        with self.assertRaises(SystemExit):
            mod.validate_stable_correction_model("gpt-realtime-translate")

    def test_rejects_non_required_model_for_stable_correction(self):
        with self.assertRaises(SystemExit):
            mod.validate_stable_correction_model("gpt-5.5")

    def test_normalize_correction_accepts_translation_alias(self):
        normalized = mod.normalize_correction({"segment_id": "seg_1", "translation": "耶稣是我们的中保。"})

        self.assertEqual(normalized["id"], "seg_1")
        self.assertEqual(normalized["zh"], "耶稣是我们的中保。")

    def test_stable_correction_events_are_caption_finals(self):
        events = mod.stable_correction_events(
            {
                "segments": [
                    {
                        "id": "seg_1",
                        "en": "Jesus is our mediator.",
                        "draftZh": "耶稣是中保。",
                        "stableZh": "耶稣是我们的中保。",
                    },
                    {"id": "seg_2", "en": "No correction.", "stableZh": ""},
                ]
            },
            model="gpt-5.4-mini",
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "caption_final")
        self.assertEqual(events[0]["segmentId"], "seg_1")
        self.assertEqual(events[0]["zh"], "耶稣是我们的中保。")
        self.assertEqual(events[0]["en"], "Jesus is our mediator.")
        self.assertEqual(events[0]["source"], "gpt-5.4-mini-stable-correction")

    def test_post_stable_corrections_sends_event_token_header_without_returning_it(self):
        calls = []

        class FakeResponse:
            status_code = 202
            text = '{"status":"accepted"}'

            def json(self):
                return {"status": "accepted"}

        original_post = mod.requests.post
        try:
            def fake_post(url, headers, json, timeout):
                calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
                return FakeResponse()

            mod.requests.post = fake_post
            posted = mod.post_stable_corrections(
                output={
                    "segments": [
                        {
                            "id": "seg_1",
                            "en": "Jesus is our mediator.",
                            "stableZh": "耶稣是我们的中保。",
                        }
                    ]
                },
                backend_url="http://127.0.0.1:8080/",
                session_id="rt_test",
                event_token="secret-event-token",
                model="gpt-5.4-mini",
            )
        finally:
            mod.requests.post = original_post

        self.assertEqual(posted, 1)
        self.assertEqual(calls[0]["url"], "http://127.0.0.1:8080/api/realtime/sessions/rt_test/events")
        self.assertEqual(calls[0]["headers"]["X-Realtime-Event-Token"], "secret-event-token")
        self.assertEqual(calls[0]["json"]["type"], "caption_final")
        self.assertEqual(calls[0]["json"]["model"], "gpt-5.4-mini")

    def test_post_stable_corrections_can_use_admin_token_for_browser_session(self):
        calls = []

        class FakeResponse:
            status_code = 202
            text = '{"status":"accepted"}'

            def json(self):
                return {"status": "accepted"}

        original_post = mod.requests.post
        try:
            def fake_post(url, headers, json, timeout):
                calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
                return FakeResponse()

            mod.requests.post = fake_post
            posted = mod.post_stable_corrections(
                output={
                    "segments": [
                        {
                            "id": "seg_1",
                            "en": "Jesus is our mediator.",
                            "stableZh": "耶稣是我们的中保。",
                        }
                    ]
                },
                backend_url="http://127.0.0.1:8080/",
                session_id="rt_test",
                admin_token="operator-token",
                model="gpt-5.4-mini",
            )
        finally:
            mod.requests.post = original_post

        self.assertEqual(posted, 1)
        self.assertEqual(calls[0]["headers"]["Authorization"], "Bearer operator-token")
        self.assertNotIn("X-Realtime-Event-Token", calls[0]["headers"])
        self.assertEqual(calls[0]["json"]["source"], "gpt-5.4-mini-stable-correction")

    def test_post_backend_args_must_be_supplied_together(self):
        original_argv = sys.argv
        try:
            sys.argv = [
                "stabilize",
                "--input-jsonl",
                "events.jsonl",
                "--api-key-secret",
                "projects/p/secrets/openai-api-key/versions/latest",
                "--post-backend-url",
                "http://127.0.0.1:8080",
            ]
            with self.assertRaises(SystemExit):
                mod.parse_args()
        finally:
            sys.argv = original_argv

    def test_stabilize_batch_uses_responses_api_and_typed_output(self):
        calls = []

        class FakeResponse:
            status_code = 200
            text = ""

            def json(self):
                return {
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": (
                                        "{\"segments\":[{\"id\":\"seg_1\","
                                        "\"zh\":\"耶稣是我们的中保。\",\"note\":\"术语修正。\"}]}"
                                    ),
                                }
                            ],
                        }
                    ]
                }

        original_post = mod.requests.post
        try:
            def fake_post(url, headers, json, timeout):
                calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
                return FakeResponse()

            mod.requests.post = fake_post
            corrections = mod.stabilize_batch(
                [{"id": "seg_1", "en": "Jesus is our mediator.", "draftZh": "耶稣是中保。"}],
                api_key="sk-test",
                model="gpt-5.4-mini",
            )
        finally:
            mod.requests.post = original_post

        self.assertEqual(corrections[0]["zh"], "耶稣是我们的中保。")
        self.assertEqual(calls[0]["url"], mod.OPENAI_RESPONSES_URL)
        self.assertEqual(calls[0]["json"]["model"], "gpt-5.4-mini")
        self.assertIn("input", calls[0]["json"])
        self.assertNotIn("messages", calls[0]["json"])
        self.assertEqual(calls[0]["json"]["text"]["format"]["type"], "json_object")


if __name__ == "__main__":
    unittest.main()
