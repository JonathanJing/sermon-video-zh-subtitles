import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_multistage_post_live_timeline.py"
SPEC = importlib.util.spec_from_file_location("build_multistage_post_live_timeline", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class MultistageTimelineTest(unittest.TestCase):
    def test_transition_selection_requires_known_ordered_chunks(self):
        chunks = [
            {"id": 4, "start": 1200.0, "end": 1230.0, "text": "host"},
            {"id": 5, "start": 1230.0, "end": 1260.0, "text": "sermon"},
            {"id": 60, "start": 2880.0, "end": 2910.0, "text": "response"},
        ]
        result = mod.validate_transition_selection(
            {"startChunkId": 5, "endChunkId": 60, "confidence": 0.9}, chunks
        )
        self.assertEqual(result["startChunkId"], 5)
        with self.assertRaises(RuntimeError):
            mod.validate_transition_selection({"startChunkId": 60, "endChunkId": 5}, chunks)

    def test_exact_selection_accepts_manual_quality_boundary(self):
        start = [
            {"id": 10, "start": 1760.0, "end": 1765.0, "text": "Take a look."},
            {"id": 11, "start": 1765.0, "end": 1770.0, "text": "God's people had seen his power."},
        ]
        end = [
            {"id": 12, "start": 3510.0, "end": 3515.0, "text": "final sermon words"},
            {"id": 13, "start": 3515.0, "end": 3520.0, "text": "Let's pray."},
            {"id": 14, "start": 3520.0, "end": 3525.0, "text": "transition"},
        ]
        result = mod.validate_exact_selection(
            {"startChunkId": 11, "endBoundarySeconds": 3525, "confidence": 0.96}, start, end
        )
        self.assertEqual(result["endBoundarySeconds"], 3525.0)

    def test_classifier_uses_requested_model_and_high_reasoning(self):
        captured = []
        original = mod.sermon_pipeline.chat_json

        def fake_chat(_api_key, payload):
            captured.append(payload)
            return {
                "model": "gpt-5.6",
                "choices": [{"message": {"content": json.dumps({"startChunkId": 1, "endChunkId": 2})}}],
            }

        try:
            mod.sermon_pipeline.chat_json = fake_chat
            with tempfile.TemporaryDirectory() as tempdir:
                classify = mod.make_openai_classifier(
                    "test-key", model="gpt-5.6", reasoning_effort="high", cache_dir=Path(tempdir)
                )
                classify("transition", [{"id": 1}, {"id": 2}])
        finally:
            mod.sermon_pipeline.chat_json = original

        self.assertEqual(captured[0]["model"], "gpt-5.6")
        self.assertEqual(captured[0]["reasoning_effort"], "high")
        self.assertEqual(captured[0]["response_format"], {"type": "json_object"})
        self.assertIn("candidate for human review", captured[0]["messages"][0]["content"])
        self.assertIn("Required JSON schema", captured[0]["messages"][1]["content"])

    def test_classifier_cache_changes_when_prompt_version_changes(self):
        calls = []

        def fake_chat(_api_key, _payload):
            calls.append(1)
            return {
                "model": "gpt-5.6-sol",
                "choices": [{"message": {"content": '{"startChunkId":1,"endChunkId":2,"confidence":0.8,"startReason":"x","endReason":"y"}'}}],
            }

        original = mod.sermon_pipeline.chat_json
        try:
            mod.sermon_pipeline.chat_json = fake_chat
            with tempfile.TemporaryDirectory() as tempdir:
                classify = mod.make_openai_classifier("key", model="gpt-5.6", reasoning_effort="high", cache_dir=Path(tempdir))
                first = classify("transition", [{"id": 1}, {"id": 2}])
                second = classify("transition", [{"id": 1}, {"id": 2}])
        finally:
            mod.sermon_pipeline.chat_json = original

        self.assertEqual(len(calls), 1)
        self.assertEqual(first["promptVersion"], mod.review_prompts.BOUNDARY_PROMPT_VERSION)
        self.assertEqual(second["inputSha256Prefix"], first["inputSha256Prefix"])

    def test_fine_zone_cache_path_is_bound_to_window(self):
        audio_paths = []
        original_cut = mod.sermon_pipeline.cut_chunk
        original_transcribe = mod.transcribe_absolute_chunks

        def fake_cut(_source, dest, _start, _duration):
            audio_paths.append(dest)

        def fake_transcribe(**kwargs):
            return [{"id": 0, "start": kwargs["absolute_offset"], "end": kwargs["absolute_offset"] + 5, "text": "x"}]

        try:
            mod.sermon_pipeline.cut_chunk = fake_cut
            mod.transcribe_absolute_chunks = fake_transcribe
            with tempfile.TemporaryDirectory() as tempdir:
                root = Path(tempdir)
                mod.transcribe_zone(
                    api_key="x", source=root / "source.m4a", outdir=root / "fine",
                    zone={"startSeconds": 100.0, "endSeconds": 200.0}, chunk_seconds=5.0, model="asr",
                )
                mod.transcribe_zone(
                    api_key="x", source=root / "source.m4a", outdir=root / "fine",
                    zone={"startSeconds": 160.0, "endSeconds": 260.0}, chunk_seconds=5.0, model="asr",
                )
        finally:
            mod.sermon_pipeline.cut_chunk = original_cut
            mod.transcribe_absolute_chunks = original_transcribe

        self.assertNotEqual(audio_paths[0].parent, audio_paths[1].parent)
        self.assertIn("zone_100000_200000", str(audio_paths[0]))
        self.assertIn("zone_160000_260000", str(audio_paths[1]))


if __name__ == "__main__":
    unittest.main()
