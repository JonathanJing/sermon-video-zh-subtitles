import unittest

from schema import extract_json, validate, validate_expected_audio, validate_expected_modalities
from prepare import transcript_for_range


class SchemaTest(unittest.TestCase):
    def valid(self):
        return {
            "audio_status": "matched", "video_status": "matched", "transcript_status": "partial",
            "events": [{"start_seconds": 1, "end_seconds": 2, "type": "scripture_reading",
                        "scripture_ref": "Revelation 2:1", "on_screen_text": None,
                        "evidence": {"audio": True, "video": True, "transcript": True},
                        "confidence": 0.9, "note": "quoted verse"}],
            "pause_candidates": [{"at_seconds": 2, "duration_seconds": 0.3,
                                  "kind": "sentence_boundary",
                                  "evidence": {"audio": True, "video": False, "transcript": False},
                                  "confidence": 0.8, "note": "audible silence"}],
            "limitations": ["candidate"],
        }

    def test_valid(self):
        self.assertEqual(validate(self.valid(), 10), [])

    def test_silence_cannot_claim_audio_evidence(self):
        data = self.valid()
        data["audio_status"] = "no_speech"
        errors = validate(data, 10)
        self.assertIn("event_0_unsupported_audio_scripture", errors)
        self.assertIn("pause_0_unsupported_audio_pause", errors)

    def test_harness_catches_claimed_speech_on_silence(self):
        errors = validate_expected_audio(self.valid(), "no_speech")
        self.assertIn("unexpected_audio_status_expected_no_speech", errors)
        self.assertIn("event_0_forbidden_without_matched_audio", errors)
        self.assertIn("event_0_false_audio_evidence", errors)
        self.assertIn("pause_0_forbidden_without_matched_audio", errors)

    def test_visible_text_requires_video_evidence(self):
        data = self.valid()
        data["events"][0]["on_screen_text"] = "REVELATION 2:1"
        data["events"][0]["evidence"]["video"] = False
        self.assertIn("event_0_unsupported_visual_text", validate(data, 10))

    def test_no_visual_condition_rejects_visual_claims(self):
        data = self.valid()
        data["events"][0]["on_screen_text"] = "REVELATION 2:1"
        errors = validate_expected_modalities(data, expected_video_status="no_visual")
        self.assertIn("unexpected_video_status_expected_no_visual", errors)
        self.assertIn("event_0_false_visual_text", errors)
        self.assertIn("event_0_false_video_evidence", errors)

    def test_no_transcript_condition_rejects_transcript_evidence(self):
        data = self.valid()
        errors = validate_expected_modalities(data, expected_transcript_status="not_provided")
        self.assertIn("unexpected_transcript_status_expected_not_provided", errors)
        self.assertIn("event_0_false_transcript_evidence", errors)

    def test_not_provided_transcript_status_is_valid(self):
        data = self.valid()
        data["transcript_status"] = "not_provided"
        data["events"][0]["evidence"]["transcript"] = False
        self.assertEqual(validate(data, 10), [])

    def test_placeholder_limitation_is_rejected(self):
        data = self.valid()
        data["limitations"] = ["string"]
        self.assertIn("placeholder_limitation", validate(data, 10))

    def test_extract_fenced_json(self):
        parsed = extract_json("```json\n{\"ok\": true}\n```")
        self.assertTrue(parsed["ok"])

    def test_extract_json_after_live_filler(self):
        parsed = extract_json('Analyzing now. {"ok": true} Finished.')
        self.assertTrue(parsed["ok"])

    def test_extract_json_skips_malformed_preface_and_uses_complete_fence(self):
        text = '''```json
{"audio_status":"matched",
```
thinking
```json
{"audio_status":"matched","video_status":"matched","transcript_status":"matched",
 "events":[],"pause_candidates":[],"limitations":["review"]}
```'''
        self.assertEqual(extract_json(text)["limitations"], ["review"])

    def test_incomplete_outer_json_does_not_become_nested_object(self):
        with self.assertRaises(Exception):
            extract_json('{"events": [{"evidence": {"audio": true}}')

    def test_timestamped_transcript_is_cropped_to_source_range(self):
        report = {"wordSequenceText": "one two three", "words": [
            {"text": "one", "timelineStart": 10.0, "timelineEnd": 10.5},
            {"text": "two", "timelineStart": 11.0, "timelineEnd": 11.5},
            {"text": "three", "timelineStart": 12.0, "timelineEnd": 12.5},
        ]}
        self.assertEqual(transcript_for_range(report, 10.9, 1.0), ("two", 1))


if __name__ == "__main__":
    unittest.main()
