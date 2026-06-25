import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import scripts.run_realtime_public_sse_smoke as mod


class RealtimePublicSseSmokeTest(unittest.TestCase):
    def test_smoke_posts_events_and_reads_public_sse_without_reporting_token(self):
        calls = []

        with patch.object(mod, "urlopen", side_effect=fake_urlopen(calls)):
            report = mod.run_smoke(args_for(internal_task_token="task-token"))

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["sessionId"], "rt_test")
        self.assertEqual(report["sse"]["eventsRead"], 5)
        self.assertEqual(report["sse"]["sessionStarted"]["targetLanguage"], "zh")
        self.assertEqual(report["sse"]["sessionStarted"]["audioSourceKind"], "ipad_mic")
        self.assertEqual(report["sse"]["stableCaption"]["segments"], ["smoke_1"])
        self.assertEqual(report["sse"]["stableCaption"]["latencyP95Ms"], 3400)
        self.assertTrue(report["sse"]["stableCaption"]["windowed"])
        self.assertEqual(report["sse"]["stableCorrection"]["matchedSegments"], ["smoke_1"])
        self.assertEqual(report["sessionValidation"]["status"], "skipped")
        self.assertIn("caption_final", report["sse"]["types"])
        self.assertIn("caption_stable", report["sse"]["types"])
        rendered = json.dumps(report)
        self.assertNotIn("event-token-secret", rendered)
        self.assertFalse(report["eventTokenIncluded"])
        self.assertEqual(calls[0]["headers"]["X-internal-task-token"], "task-token")
        event_posts = [call for call in calls if "/api/realtime/sessions/rt_test/events" in call["url"]]
        self.assertEqual(len(event_posts), 3)
        self.assertTrue(all(call["headers"]["X-realtime-event-token"] == "event-token-secret" for call in event_posts))
        self.assertEqual(event_posts[-1]["json"]["en"], "God loved the world")
        self.assertEqual(report["eventPayloadSource"]["kind"], "inline_smoke_fixture")

    def test_smoke_posts_browser_normalized_events_when_web_contract_report_is_provided(self):
        calls = []

        with tempfile.TemporaryDirectory() as tmp:
            web_report = Path(tmp) / "web-realtime-contract.json"
            web_report.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "normalizationProbe": {
                            "status": "ok",
                            "results": [
                                {
                                    "name": "output_delta",
                                    "actual": {
                                        "type": "caption_delta",
                                        "source": "openai-realtime-webrtc",
                                        "zh": "神爱世人",
                                        "text": "神爱世人",
                                        "delta": "神爱世人",
                                        "segmentId": "seg_browser",
                                        "openaiEventType": "session.output_transcript.delta",
                                    },
                                },
                                {
                                    "name": "paired_input_delta",
                                    "actual": {
                                        "type": "input_transcript_delta",
                                        "source": "openai-realtime-webrtc",
                                        "en": "God loved the world",
                                        "text": "God loved the world",
                                        "delta": "God loved the world",
                                        "segmentId": "seg_browser",
                                        "openaiEventType": "session.input_transcript.delta",
                                    },
                                },
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(mod, "urlopen", side_effect=fake_urlopen(calls, stable_segment_id="seg_browser", draft_segment_id="seg_browser")):
                report = mod.run_smoke(args_for(web_realtime_contract_report=web_report))

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["eventPayloadSource"]["kind"], "web_realtime_contract_normalization_probe")
        payloads = [call["json"] for call in calls if "/api/realtime/sessions/rt_test/events" in call["url"]]
        self.assertEqual([payload["type"] for payload in payloads], ["input_transcript_delta", "caption_delta", "caption_final"])
        self.assertEqual(payloads[0]["openaiEventType"], "session.input_transcript.delta")
        self.assertEqual(payloads[1]["openaiEventType"], "session.output_transcript.delta")
        self.assertEqual(payloads[2]["segmentId"], "seg_browser")
        self.assertEqual(payloads[2]["en"], "God loved the world")
        browser_check = next(check for check in report["checks"] if check["name"] == "browser_normalized_event_payloads")
        self.assertEqual(browser_check["state"], "pass")

    def test_create_session_failure_fails_cleanly(self):
        with patch.object(mod, "urlopen", side_effect=fake_urlopen([], create_status=401)):
            report = mod.run_smoke(args_for())

        self.assertEqual(report["status"], "failed")
        self.assertIn("create_local_session", report["failedChecks"])

    def test_smoke_fails_when_public_sse_session_metadata_is_missing(self):
        with patch.object(mod, "urlopen", side_effect=fake_urlopen([], sse_session_metadata=False)):
            report = mod.run_smoke(args_for())

        self.assertEqual(report["status"], "failed")
        self.assertIn("sse_session_metadata", report["failedChecks"])
        self.assertIsNone(report["sse"]["sessionStarted"].get("audioSourceKind"))

    def test_smoke_fails_when_stable_correction_uses_different_segment(self):
        with patch.object(mod, "urlopen", side_effect=fake_urlopen([], stable_segment_id="smoke_other")):
            report = mod.run_smoke(args_for())

        self.assertEqual(report["status"], "failed")
        self.assertIn("sse_stable_correction_matches_draft_segment", report["failedChecks"])
        self.assertEqual(report["sse"]["stableCorrection"]["draftSegments"], ["smoke_1"])
        self.assertEqual(report["sse"]["stableCorrection"]["stableCorrectionSegments"], ["smoke_other"])

    def test_smoke_validates_session_jsonl_when_configured(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events_jsonl = root / "rt_test.jsonl"
            validation_out = root / "validation.json"
            events_jsonl.write_text(
                "\n".join(
                    json.dumps(row, ensure_ascii=False)
                    for row in [
                        {
                            "id": 1,
                            "type": "session_started",
                            "sessionId": "rt_test",
                            "model": "gpt-realtime-translate",
                            "targetLanguage": "zh",
                            "audioSourceKind": "ipad_mic",
                        },
                        {
                            "id": 2,
                            "type": "input_transcript_delta",
                            "sessionId": "rt_test",
                            "source": "openai-realtime-webrtc",
                            "en": "God loved the world",
                            "segmentId": "smoke_1",
                        },
                        {
                            "id": 3,
                            "type": "caption_delta",
                            "sessionId": "rt_test",
                            "source": "openai-realtime-webrtc",
                            "model": "gpt-realtime-translate",
                            "zh": "神爱世人",
                            "segmentId": "smoke_1",
                        },
                        {
                            "id": 4,
                            "type": "caption_stable",
                            "sessionId": "rt_test",
                            "source": "realtime-caption-stabilizer",
                            "stability": "stable",
                            "zh": "神爱世人。",
                            "en": "God loved the world",
                            "segmentId": "smoke_1",
                            "latencyMs": 3400,
                            "stabilizerWindow": {
                                "windowMs": 8000,
                                "segmentId": "smoke_1",
                                "sourceEventIds": [2, 3],
                                "inputTextEn": "God loved the world",
                                "draftZh": "神爱世人。",
                            },
                        },
                        {
                            "id": 5,
                            "type": "caption_final",
                            "sessionId": "rt_test",
                            "source": "gpt-5.4-mini-stable-correction",
                            "model": "gpt-5.4-mini",
                            "zh": "神爱世人。",
                            "en": "God loved the world",
                            "segmentId": "smoke_1",
                        },
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            with patch.object(mod, "urlopen", side_effect=fake_urlopen([])):
                report = mod.run_smoke(
                    args_for(
                        session_events_jsonl=str(events_jsonl),
                        session_validation_out=validation_out,
                    )
                )

            self.assertEqual(report["status"], "ok")
            self.assertEqual(report["sessionValidation"]["status"], "ok")
            self.assertEqual(report["sessionValidation"]["counts"]["stableCaptionEvents"], 1)
            self.assertEqual(report["sessionValidation"]["counts"]["stableCorrectionEvents"], 1)
            self.assertIn("session_jsonl_validation", [check["name"] for check in report["checks"]])
            written = json.loads(validation_out.read_text(encoding="utf-8"))
            self.assertEqual(written["status"], "ok")

    def test_smoke_validates_session_jsonl_from_event_log_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events_jsonl = root / "rt_test.jsonl"
            events_jsonl.write_text(
                "\n".join(
                    json.dumps(row, ensure_ascii=False)
                    for row in [
                        {
                            "id": 1,
                            "type": "session_started",
                            "sessionId": "rt_test",
                            "model": "gpt-realtime-translate",
                            "targetLanguage": "zh",
                            "audioSourceKind": "ipad_mic",
                        },
                        {
                            "id": 2,
                            "type": "input_transcript_delta",
                            "sessionId": "rt_test",
                            "source": "openai-realtime-webrtc",
                            "en": "God loved the world",
                            "segmentId": "smoke_1",
                        },
                        {
                            "id": 3,
                            "type": "caption_delta",
                            "sessionId": "rt_test",
                            "source": "openai-realtime-webrtc",
                            "model": "gpt-realtime-translate",
                            "zh": "神爱世人",
                            "segmentId": "smoke_1",
                        },
                        {
                            "id": 4,
                            "type": "caption_stable",
                            "sessionId": "rt_test",
                            "source": "realtime-caption-stabilizer",
                            "stability": "stable",
                            "zh": "神爱世人。",
                            "en": "God loved the world",
                            "segmentId": "smoke_1",
                            "latencyMs": 3400,
                            "stabilizerWindow": {
                                "windowMs": 8000,
                                "segmentId": "smoke_1",
                                "sourceEventIds": [2, 3],
                                "inputTextEn": "God loved the world",
                                "draftZh": "神爱世人。",
                            },
                        },
                        {
                            "id": 5,
                            "type": "caption_final",
                            "sessionId": "rt_test",
                            "source": "gpt-5.4-mini-stable-correction",
                            "model": "gpt-5.4-mini",
                            "zh": "神爱世人。",
                            "en": "God loved the world",
                            "segmentId": "smoke_1",
                        },
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            with patch.object(mod, "urlopen", side_effect=fake_urlopen([])):
                report = mod.run_smoke(args_for(event_log_dir=root))

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["sessionValidation"]["eventsJsonl"], "rt_test.jsonl")
        self.assertEqual(report["sessionValidation"]["counts"]["events"], 5)

    def test_smoke_fails_when_configured_session_jsonl_validation_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            events_jsonl = Path(tmp) / "rt_test.jsonl"
            events_jsonl.write_text(
                '{"id":1,"type":"session_started","sessionId":"rt_test","model":"gpt-realtime-translate","targetLanguage":"zh","audioSourceKind":"ipad_mic"}\n',
                encoding="utf-8",
            )

            with patch.object(mod, "urlopen", side_effect=fake_urlopen([])):
                report = mod.run_smoke(args_for(session_events_jsonl=str(events_jsonl)))

        self.assertEqual(report["status"], "failed")
        self.assertIn("session_jsonl_validation", report["failedChecks"])
        self.assertIn("stable_correction", report["sessionValidation"]["failedChecks"])

    def test_session_events_jsonl_uri_can_be_derived_from_gcs_prefix(self):
        uri = mod.session_events_jsonl_uri(
            args=args_for(
                sunday="2026-06-28",
                realtime_event_gcs_prefix="gs://sermon-zh-artifacts/realtime-events/",
            ),
            session_id="rt bad/id",
        )

        self.assertEqual(uri, "gs://sermon-zh-artifacts/realtime-events/2026-06-28/rt_bad_id.jsonl")

    def test_session_events_jsonl_uri_can_be_derived_from_local_event_log_dir(self):
        uri = mod.session_events_jsonl_uri(
            args=args_for(event_log_dir=Path("/tmp/sermon-events")),
            session_id="rt bad/id",
        )

        self.assertEqual(uri, "/tmp/sermon-events/rt_bad_id.jsonl")


def args_for(
    internal_task_token=None,
    sunday="2026-06-28",
    session_events_jsonl=None,
    event_log_dir=None,
    realtime_event_gcs_prefix=None,
    web_realtime_contract_report=None,
    session_validation_out=None,
):
    return Namespace(
        base_url="https://example.run.app",
        sunday=sunday,
        admin_token=None,
        internal_task_token=internal_task_token,
        timeout_seconds=20,
        session_events_jsonl=session_events_jsonl,
        event_log_dir=event_log_dir,
        realtime_event_gcs_prefix=realtime_event_gcs_prefix,
        web_realtime_contract_report=str(web_realtime_contract_report) if web_realtime_contract_report else None,
        session_validation_out=session_validation_out,
        out=None,
    )


class FakeResponse:
    def __init__(self, *, body="", status=200, content_type="application/json", lines=None):
        self.body = body.encode("utf-8")
        self.status = status
        self.headers = {"Content-Type": content_type}
        self.lines = [line.encode("utf-8") for line in (lines or [])]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.body

    def readline(self):
        return self.lines.pop(0) if self.lines else b""


def fake_urlopen(calls, create_status=201, sse_session_metadata=True, stable_segment_id="smoke_1", draft_segment_id="smoke_1"):
    def _fake_urlopen(request, timeout):
        headers = dict(request.header_items())
        body = request.data.decode("utf-8") if getattr(request, "data", None) else ""
        try:
            payload = json.loads(body) if body else None
        except json.JSONDecodeError:
            payload = None
        calls.append({"url": request.full_url, "method": request.get_method(), "headers": headers, "json": payload})
        if request.full_url.endswith("/api/admin/realtime/local-sessions"):
            return FakeResponse(
                status=create_status,
                body=json.dumps(
                    {
                        "status": "ready",
                        "sessionId": "rt_test",
                        "eventToken": "event-token-secret",
                        "model": "gpt-realtime-translate",
                        "targetLanguage": "zh",
                        "audioSourceKind": "ipad_mic",
                    }
                    if create_status == 201
                    else {"error": "unauthorized"}
                ),
            )
        if "/api/realtime/sessions/rt_test/events" in request.full_url:
            return FakeResponse(status=202, body=json.dumps({"status": "accepted", "id": 2}))
        if request.full_url.startswith("https://example.run.app/api/realtime/sessions/current/events"):
            session_started = (
                '{"id":1,"type":"session_started","model":"gpt-realtime-translate","targetLanguage":"zh","audioSourceKind":"ipad_mic"}'
                if sse_session_metadata
                else '{"id":1,"type":"session_started","model":"gpt-realtime-translate","targetLanguage":"zh"}'
            )
            lines = [
                'id: 1\n',
                'event: session_started\n',
                f"data: {session_started}\n",
                '\n',
                sse_data(
                    {
                        "id": 2,
                        "type": "input_transcript_delta",
                        "source": "openai-realtime-webrtc",
                        "en": "God loved the world",
                        "segmentId": draft_segment_id,
                    }
                ),
                '\n',
                sse_data(
                    {
                        "id": 3,
                        "type": "caption_delta",
                        "source": "openai-realtime-webrtc",
                        "zh": "神爱世人",
                        "segmentId": draft_segment_id,
                    }
                ),
                '\n',
                sse_data(
                    {
                        "id": 4,
                        "type": "caption_stable",
                        "source": "realtime-caption-stabilizer",
                        "stability": "stable",
                        "zh": "神爱世人。",
                        "en": "God loved the world",
                        "segmentId": draft_segment_id,
                        "latencyMs": 3400,
                        "stabilizerWindow": {
                            "windowMs": 8000,
                            "segmentId": draft_segment_id,
                            "sourceEventIds": [2, 3],
                            "inputTextEn": "God loved the world",
                            "draftZh": "神爱世人。",
                        },
                    }
                ),
                '\n',
                sse_data(
                    {
                        "id": 5,
                        "type": "caption_final",
                        "source": "gpt-5.4-mini-stable-correction",
                        "model": "gpt-5.4-mini",
                        "zh": "神爱世人。",
                        "segmentId": stable_segment_id,
                    }
                ),
                '\n',
            ]
            return FakeResponse(status=200, content_type="text/event-stream", lines=lines)
        raise AssertionError(f"unexpected URL: {request.full_url}")

    return _fake_urlopen


def sse_data(payload):
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    unittest.main()
