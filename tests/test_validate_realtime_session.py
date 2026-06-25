import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "validate_realtime_session.py"
SPEC = importlib.util.spec_from_file_location("validate_realtime_session", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class ValidateRealtimeSessionTest(unittest.TestCase):
    def ready_events(self):
        return [
            {
                "id": 1,
                "sessionId": "rt_test",
                "type": "session_started",
                "model": "gpt-realtime-translate",
                "targetLanguage": "zh",
                "audioSourceKind": "ipad_mic",
            },
            {
                "id": 2,
                "sessionId": "rt_test",
                "type": "input_transcript_delta",
                "source": "openai_realtime_translation_ws",
                "en": "God loved the world.",
                "delta": "God loved the world.",
                "segmentId": "seg_1",
            },
            {
                "id": 3,
                "sessionId": "rt_test",
                "type": "caption_delta",
                "source": "openai_realtime_translation_ws",
                "zh": "神爱世人。",
                "delta": "神爱世人。",
                "segmentId": "seg_1",
                "latencyMs": 420,
            },
            {
                "id": 4,
                "sessionId": "rt_test",
                "type": "caption_stable",
                "source": "realtime-caption-stabilizer",
                "stability": "stable",
                "zh": "神爱世人。",
                "en": "God loved the world.",
                "final": False,
                "segmentId": "seg_1",
                "stabilizerWindowMs": 8000,
                "stabilizerWindow": {
                    "windowMs": 8000,
                    "segmentId": "seg_1",
                    "sourceEventIds": [2, 3],
                    "inputTextEn": "God loved the world.",
                    "draftZh": "神爱世人。",
                },
                "latencyMs": 1200,
            },
            {
                "id": 5,
                "sessionId": "rt_test",
                "type": "caption_final",
                "source": "gpt-5.4-mini-stable-correction",
                "model": "gpt-5.4-mini",
                "zh": "神爱世人。",
                "en": "God loved the world.",
                "final": True,
                "segmentId": "seg_1",
            },
        ]

    def report_for(self, events, raw_text=None, **overrides):
        if raw_text is None:
            raw_text = "\n".join(json.dumps(event, ensure_ascii=False) for event in events)
        kwargs = {
            "events": events,
            "raw_text": raw_text,
            "events_uri": "/tmp/rt_test.jsonl",
            "require_caption_stable": True,
            "require_stable_correction": True,
        }
        kwargs.update(overrides)
        return mod.validate_realtime_session(**kwargs)

    def test_validates_realtime_input_caption_model_and_stable_correction(self):
        report = self.report_for(self.ready_events())

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["failedChecks"], [])
        self.assertEqual(report["counts"]["realtimeInputTranscriptEvents"], 1)
        self.assertEqual(report["counts"]["realtimeCaptionEvents"], 1)
        self.assertEqual(report["counts"]["stableCaptionEvents"], 1)
        self.assertEqual(report["counts"]["stableCorrectionEvents"], 1)
        self.assertEqual(report["stableLatency"]["p95Ms"], 1200)
        self.assertEqual(report["sessionIds"], ["rt_test"])
        self.assertEqual(report["targetLanguages"], ["zh"])
        self.assertEqual(report["audioSourceKinds"], ["ipad_mic"])
        self.assertNotIn("stable_correction_context", report["failedChecks"])
        self.assertEqual(report["latency"]["maxMs"], 1200)
        self.assertFalse(report["apiKeyMaterialIncluded"])
        self.assertFalse(report["secretResourceNamesIncluded"])

    def test_accepts_browser_webrtc_realtime_source(self):
        events = self.ready_events()
        for event in events:
            if event.get("source") == "openai_realtime_translation_ws":
                event["source"] = "openai-realtime-webrtc"

        report = self.report_for(events)

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["realtimeSources"], ["openai-realtime-webrtc"])

    def test_accepts_legacy_audio_source_kind_from_source_field(self):
        events = self.ready_events()
        events[0].pop("audioSourceKind")
        events.insert(
            1,
            {
                "id": 2,
                "sessionId": "rt_test",
                "type": "media_worker_started",
                "source": "authorized_audio_file",
                "model": "gpt-realtime-translate",
                "targetLanguage": "zh",
            },
        )
        for index, event in enumerate(events, start=1):
            event["id"] = index

        report = self.report_for(events)

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["audioSourceKinds"], ["authorized_audio_file"])

    def test_does_not_treat_processor_source_as_audio_source_kind(self):
        events = self.ready_events()
        events[0].pop("audioSourceKind")

        report = self.report_for(events)

        self.assertEqual(report["status"], "failed")
        self.assertIn("audio_source_kind", report["failedChecks"])

    def test_fails_without_realtime_input_transcript(self):
        events = [event for event in self.ready_events() if event.get("type") not in mod.INPUT_TYPES]

        report = self.report_for(events)

        self.assertEqual(report["status"], "failed")
        self.assertIn("input_transcript_events", report["failedChecks"])
        self.assertIn("input_transcript_english", report["failedChecks"])

    def test_accepts_gpt4o_transcribe_fallback_input_transcript(self):
        events = self.ready_events()
        for event in events:
            if event.get("type") in mod.INPUT_TYPES:
                event["source"] = "openai_audio_transcription_fallback"
                event["model"] = "gpt-4o-transcribe"

        report = self.report_for(events)

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["counts"]["inputTranscriptEvents"], 1)
        self.assertEqual(report["counts"]["realtimeInputTranscriptEvents"], 0)

    def test_fails_without_chinese_caption(self):
        events = self.ready_events()
        for event in events:
            if event.get("type") in mod.CAPTION_TYPES and event.get("source") == "openai_realtime_translation_ws":
                event["zh"] = "draft caption"
                event["delta"] = "draft caption"

        report = self.report_for(events)

        self.assertEqual(report["status"], "failed")
        self.assertIn("caption_chinese", report["failedChecks"])

    def test_fails_without_model_event_by_default(self):
        events = self.ready_events()
        events[0].pop("model")

        report = self.report_for(events)

        self.assertEqual(report["status"], "failed")
        self.assertIn("realtime_model", report["failedChecks"])

    def test_fails_without_target_language(self):
        events = self.ready_events()
        events[0].pop("targetLanguage")

        report = self.report_for(events)

        self.assertEqual(report["status"], "failed")
        self.assertIn("target_language", report["failedChecks"])

    def test_fails_without_allowed_audio_source_kind(self):
        events = self.ready_events()
        events[0]["audioSourceKind"] = "unknown"

        report = self.report_for(events)

        self.assertEqual(report["status"], "failed")
        self.assertIn("audio_source_kind", report["failedChecks"])

    def test_can_allow_missing_model_event_for_legacy_archives(self):
        events = self.ready_events()
        events[0].pop("model")

        report = self.report_for(events, require_model_event=False)

        self.assertEqual(report["status"], "ok")

    def test_fails_without_session_id_by_default(self):
        events = self.ready_events()
        for event in events:
            event.pop("sessionId", None)

        report = self.report_for(events)

        self.assertEqual(report["status"], "failed")
        self.assertIn("session_id_consistent", report["failedChecks"])

    def test_can_allow_missing_session_id_for_legacy_archives(self):
        events = self.ready_events()
        for event in events:
            event.pop("sessionId", None)

        report = self.report_for(events, require_session_id=False)

        self.assertEqual(report["status"], "ok")

    def test_fails_mixed_session_ids(self):
        events = self.ready_events()
        events[-1]["sessionId"] = "rt_other"

        report = self.report_for(events)

        self.assertEqual(report["status"], "failed")
        self.assertIn("session_id_consistent", report["failedChecks"])

    def test_fails_non_increasing_event_ids(self):
        events = self.ready_events()
        events[-1]["id"] = 2

        report = self.report_for(events)

        self.assertEqual(report["status"], "failed")
        self.assertIn("event_ids_strictly_increasing", report["failedChecks"])

    def test_fails_when_stable_correction_is_required_but_missing(self):
        events = [
            event
            for event in self.ready_events()
            if event.get("source") != "gpt-5.4-mini-stable-correction"
        ]

        report = self.report_for(events)

        self.assertEqual(report["status"], "failed")
        self.assertIn("stable_correction", report["failedChecks"])

    def test_fails_when_caption_stable_is_required_but_missing(self):
        events = [
            event
            for event in self.ready_events()
            if event.get("source") != "realtime-caption-stabilizer"
        ]

        report = self.report_for(events)

        self.assertEqual(report["status"], "failed")
        self.assertIn("caption_stable", report["failedChecks"])

    def test_fails_when_caption_stable_lacks_window_context(self):
        events = self.ready_events()
        for event in events:
            if event.get("type") == "caption_stable":
                event.pop("stabilizerWindow", None)

        report = self.report_for(events)

        self.assertEqual(report["status"], "failed")
        self.assertIn("caption_stable_window", report["failedChecks"])

    def test_fails_when_stable_correction_does_not_match_realtime_draft_segment(self):
        events = self.ready_events()
        events[-1]["segmentId"] = "seg_other"

        report = self.report_for(events)

        self.assertEqual(report["status"], "failed")
        self.assertIn("stable_correction_matches_realtime_draft_segment", report["failedChecks"])
        self.assertIn("stable_correction_context", report["failedChecks"])

    def test_fails_when_stable_correction_lacks_english_context(self):
        events = self.ready_events()
        events[-1]["en"] = ""

        report = self.report_for(events)

        self.assertEqual(report["status"], "failed")
        self.assertIn("stable_correction_context", report["failedChecks"])

    def test_fails_when_stable_correction_lacks_matching_input_transcript_segment(self):
        events = self.ready_events()
        for event in events:
            if event.get("type") in mod.INPUT_TYPES:
                event["segmentId"] = "seg_other"

        report = self.report_for(events)

        self.assertEqual(report["status"], "failed")
        self.assertIn("stable_correction_context", report["failedChecks"])

    def test_fails_secret_material_anywhere_in_jsonl(self):
        events = self.ready_events()
        raw_text = "\n".join(json.dumps(event, ensure_ascii=False) for event in events)
        raw_text += '\n{"type":"caption_delta","text":"sk-this-is-raw-key-material"}\n'

        report = self.report_for(events, raw_text=raw_text)

        self.assertEqual(report["status"], "failed")
        self.assertIn("secret_strings", report["failedChecks"])

    def test_parse_jsonl_rejects_non_object_rows(self):
        with self.assertRaises(SystemExit):
            mod.parse_jsonl('{"type":"session_started"}\n["not", "an", "object"]\n')

    def test_main_writes_report_and_returns_nonzero_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events_jsonl = root / "events.jsonl"
            out = root / "report.json"
            events_jsonl.write_text(
                json.dumps(
                    {
                        "id": 1,
                        "sessionId": "rt_test",
                        "type": "session_started",
                        "model": "gpt-realtime-translate",
                        "targetLanguage": "zh",
                        "audioSourceKind": "ipad_mic",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            argv = [
                "validate_realtime_session.py",
                "--events-jsonl",
                str(events_jsonl),
                "--require-stable-correction",
                "--out",
                str(out),
            ]
            original_argv = mod.sys.argv
            stdout = io.StringIO()
            original_stdout = mod.sys.stdout
            try:
                mod.sys.argv = argv
                mod.sys.stdout = stdout
                exit_code = mod.main()
            finally:
                mod.sys.argv = original_argv
                mod.sys.stdout = original_stdout

            self.assertEqual(exit_code, 2)
            written = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(written["status"], "failed")
            self.assertIn('"status": "failed"', stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
