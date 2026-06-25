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

    def test_build_output_omits_secret_resource_name(self):
        output = mod.build_output(
            input_jsonl=Path("artifacts/realtime.jsonl"),
            model="gpt-5.5-mini",
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

    def test_normalize_correction_accepts_translation_alias(self):
        normalized = mod.normalize_correction({"segment_id": "seg_1", "translation": "耶稣是我们的中保。"})

        self.assertEqual(normalized["id"], "seg_1")
        self.assertEqual(normalized["zh"], "耶稣是我们的中保。")


if __name__ == "__main__":
    unittest.main()
