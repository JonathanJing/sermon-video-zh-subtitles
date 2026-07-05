import argparse
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_post_live_timeline.py"
SPEC = importlib.util.spec_from_file_location("build_post_live_timeline", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class BuildPostLiveTimelineTest(unittest.TestCase):
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
                "start": 240.0,
                "end": 360.0,
                "text": "The bronze snake points us to God's love and to Jesus lifted up for us.",
            },
            {
                "id": 3,
                "start": 360.0,
                "end": 480.0,
                "text": "Would you pray with me? Let's respond and sing together.",
            },
        ]

        analysis = mod.analyze_timeline(chunks, start_buffer_seconds=30.0, end_buffer_seconds=45.0)

        self.assertEqual(analysis["suggestedWindow"]["startTimecode"], "00:01:30.000")
        self.assertEqual(analysis["suggestedWindow"]["endTimecode"], "00:08:45.000")
        self.assertEqual(analysis["suggestedWindow"]["confidence"], "candidate_requires_review")
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
