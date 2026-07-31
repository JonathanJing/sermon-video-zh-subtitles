import argparse
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_post_live_timeline.py"
SPEC = importlib.util.spec_from_file_location("build_post_live_timeline", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class BuildPostLiveTimelineTest(unittest.TestCase):
    def test_timeline_transcription_uses_gpt_transcribe_context_and_provenance_cache(self):
        calls = []

        def fake_cut(_source, destination, _start, _duration):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"audio")

        def fake_transcribe(api_key, model, prompt, audio_path, **kwargs):
            calls.append(
                {
                    "apiKey": api_key,
                    "model": model,
                    "prompt": prompt,
                    "audio": audio_path,
                    **kwargs,
                }
            )
            return {"text": "Welcome to Mariners Online. My name is Steve.", "languages": ["en"]}

        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            source = root / "source.m4a"
            source.write_bytes(b"source")
            outdir = root / "timeline"
            with mock.patch.object(mod.sermon_pipeline, "ffprobe_duration", return_value=60.0), mock.patch.object(
                mod.sermon_pipeline, "cut_chunk", side_effect=fake_cut
            ), mock.patch.object(mod.sermon_pipeline, "transcribe_openai_audio", side_effect=fake_transcribe):
                first = mod.transcribe_full_audio_chunks(
                    api_key="key",
                    source=source,
                    outdir=outdir,
                    chunk_seconds=60.0,
                    model="gpt-transcribe",
                )
                second = mod.transcribe_full_audio_chunks(
                    api_key="key",
                    source=source,
                    outdir=outdir,
                    chunk_seconds=60.0,
                    model="gpt-transcribe",
                )
                cache_metadata_exists = (
                    outdir / "chunks" / "timeline_chunk_0000.request.json"
                ).exists()

        self.assertEqual(first, second)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["model"], "gpt-transcribe")
        self.assertEqual(calls[0]["languages"], ["en"])
        self.assertIn("Mariners Church", calls[0]["keywords"])
        self.assertTrue(cache_metadata_exists)

    def test_analyze_timeline_suggests_reviewable_window(self):
        chunks = [
            {
                "id": 0,
                "start": 0.0,
                "end": 120.0,
                "text": "Welcome to church. We are so glad you're here. Let's sing together.",
            },
            {
                "id": 1,
                "start": 120.0,
                "end": 240.0,
                "text": "My name is Steve Bang Lee. If you have your Bible, turn to Numbers chapter 21.",
            },
            {
                "id": 2,
                "start": 720.0,
                "end": 840.0,
                "text": "The bronze snake points us to God's love and to Jesus lifted up for us.",
            },
            {
                "id": 3,
                "start": 900.0,
                "end": 1020.0,
                "text": "Would you pray with me? Let's respond and sing together.",
            },
        ]

        analysis = mod.analyze_timeline(chunks, start_buffer_seconds=30.0, end_buffer_seconds=45.0)

        self.assertEqual(analysis["suggestedWindow"]["startTimecode"], "00:01:30.000")
        self.assertEqual(analysis["suggestedWindow"]["endTimecode"], "00:17:45.000")
        self.assertEqual(analysis["suggestedWindow"]["confidence"], "candidate_requires_review")
        self.assertEqual(analysis["suggestedWindow"]["endMarkerKind"], "explicit_transition")
        self.assertGreaterEqual(analysis["startCandidates"][0]["startScore"], 2)
        self.assertGreaterEqual(analysis["endCandidates"][-1]["endScore"], 2)
        self.assertEqual(analysis["nonSermonEvidence"][0]["id"], 0)

    def test_analyze_timeline_prefers_sermon_speaker_over_host_intro(self):
        chunks = [
            {
                "id": 13,
                "start": 1560.0,
                "end": 1680.0,
                "text": (
                    "Amen. My name is Jeremy Robertson and I serve as the lead pastor "
                    "of Mariners Yerba Linda. If you're watching from Southern California, "
                    "I'd love to invite you to join us."
                ),
            },
            {
                "id": 14,
                "start": 1680.0,
                "end": 1800.0,
                "text": (
                    "My name is Steve Bang Lee. I'm one of the pastors. "
                    "It is an absolute joy to be with you today."
                ),
            },
            {
                "id": 27,
                "start": 3240.0,
                "end": 3360.0,
                "text": "So let's sing, let's respond, and remember God's love.",
            },
        ]

        analysis = mod.analyze_timeline(chunks, start_buffer_seconds=30.0, end_buffer_seconds=45.0)

        self.assertEqual(analysis["suggestedWindow"]["startTimecode"], "00:27:30.000")
        self.assertEqual(analysis["startCandidates"][0]["id"], 14)
        self.assertGreater(analysis["startCandidates"][0]["startScore"], 1)

    def test_analyze_timeline_penalizes_host_course_announcement(self):
        chunks = [
            {
                "id": 9,
                "start": 1080.0,
                "end": 1200.0,
                "text": (
                    "My name is Aaron Kerr. Join me at Mariners Huntington Beach. "
                    "You can learn more through the link below. A course created by Steve Bang Lee "
                    "from our Deep Dive series begins soon."
                ),
            },
            {
                "id": 10,
                "start": 1200.0,
                "end": 1320.0,
                "text": "We are going to be in Ecclesiastes today as we look for God's wisdom.",
            },
            {
                "id": 24,
                "start": 2880.0,
                "end": 3000.0,
                "text": "Would you pray with me as we respond to God's word?",
            },
        ]

        analysis = mod.analyze_timeline(chunks, start_buffer_seconds=30.0, end_buffer_seconds=45.0)

        self.assertEqual(analysis["startCandidates"][0]["id"], 10)
        self.assertEqual(analysis["suggestedWindow"]["startTimecode"], "00:19:30.000")

    def test_analyze_timeline_penalizes_prayer_amen_as_start(self):
        chunks = [
            {
                "id": 8,
                "start": 960.0,
                "end": 1080.0,
                "text": (
                    "My name is Esther Chung. Father, give your special heaping of blessings unto moms. "
                    "We pray this in Jesus name. Amen."
                ),
            },
            {
                "id": 11,
                "start": 1320.0,
                "end": 1440.0,
                "text": "Today we are in Ecclesiastes as we study wisdom when life is complex.",
            },
            {
                "id": 24,
                "start": 2880.0,
                "end": 3000.0,
                "text": "The one who will never fail. He will never fail. Amen.",
            },
        ]

        analysis = mod.analyze_timeline(chunks, start_buffer_seconds=30.0, end_buffer_seconds=45.0)

        self.assertEqual(analysis["startCandidates"][0]["id"], 11)
        self.assertEqual(analysis["suggestedWindow"]["startTimecode"], "00:21:30.000")

    def test_analyze_timeline_uses_response_song_as_end_fallback(self):
        chunks = [
            {
                "id": 10,
                "start": 1200.0,
                "end": 1320.0,
                "text": "If you have your Bible, turn to Numbers chapter 21 as we continue our series.",
            },
            {
                "id": 20,
                "start": 2400.0,
                "end": 2520.0,
                "text": "Jesus is faithful in the wilderness and he is enough for us.",
            },
            {
                "id": 26,
                "start": 3120.0,
                "end": 3240.0,
                "text": "Isn't he glorious? Isn't he powerful? You are worthy of it all.",
            },
        ]

        analysis = mod.analyze_timeline(chunks, start_buffer_seconds=30.0, end_buffer_seconds=45.0)

        self.assertEqual(analysis["suggestedWindow"]["startTimecode"], "00:19:30.000")
        self.assertEqual(analysis["suggestedWindow"]["endTimecode"], "00:52:45.000")
        self.assertEqual(analysis["suggestedWindow"]["endMarkerKind"], "response_song")
        self.assertEqual(analysis["responseSongCandidates"][0]["id"], 26)

    def test_build_report_from_saved_transcript_never_marks_ready(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            transcript = root / "chunks.json"
            transcript.write_text(
                json.dumps(
                    [
                        {"id": 0, "start": 0, "end": 60, "text": "Welcome to Mariners Online. My name is Steve."},
                        {"id": 1, "start": 60, "end": 120, "text": "Let's pray and respond."},
                    ]
                ),
                encoding="utf-8",
            )
            audio = root / "source_audio.m4a"
            audio.write_text("fake audio", encoding="utf-8")
            args = argparse.Namespace(
                input=audio,
                out=root / "report.json",
                outdir=root / "timeline",
                chunk_seconds=60.0,
                model="gpt-4o-transcribe",
                api_key_secret=None,
                transcript_json=transcript,
                start_buffer_seconds=15.0,
                end_buffer_seconds=15.0,
            )

            report = mod.build_post_live_timeline(args)

        self.assertEqual(report["status"], "requires_operator_review")
        self.assertEqual(report["stage"], "timeline_probed")
        self.assertFalse(report["apiKeyMaterialIncluded"])
        self.assertIn("Review suggestedWindow", report["nextAction"])


if __name__ == "__main__":
    unittest.main()
