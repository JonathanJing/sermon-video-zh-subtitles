import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import wave


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("english_word_timeline_poc", HERE / "run.py")
poc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(poc)


class EnglishWordTimelinePocTest(unittest.TestCase):
    def test_overlapping_windows_partition_kept_timeline(self):
        windows = poc.plan_windows(100, 130, 60, 10)
        self.assertEqual([(w["audioStart"], w["duration"]) for w in windows], [(100, 60), (150, 60), (200, 30)])
        self.assertEqual([(w["keepStart"], w["keepEnd"]) for w in windows], [(100, 155), (155, 205), (205, 230)])
        exact = poc.plan_windows(300, 60, 60, 10)
        self.assertEqual([(w["audioStart"], w["duration"]) for w in exact], [(300, 60)])

    def test_alignment_requires_same_token_sequence_and_valid_word_intervals(self):
        window = {"id": "w", "audioStart": 10, "duration": 10, "keepStart": 10, "keepEnd": 20}
        words, issues = poc.aligned_words("We can't stop.", [
            {"text": "We", "start": 0.1, "end": 0.3},
            {"text": "can't", "start": 0.4, "end": 0.7},
            {"text": "stop", "start": 0.8, "end": 1.1},
        ], window, 1000)
        self.assertEqual([word["normalized"] for word in words], ["we", "can't", "stop"])
        self.assertEqual(words[0]["timelineStart"], 1010.1)
        self.assertEqual(issues, [])
        _, issues = poc.aligned_words("We cannot stop.", [
            {"text": "We", "start": 0.1, "end": 0.3},
            {"text": "stop", "start": 0.8, "end": 1.1},
        ], window, 0)
        self.assertIn("aligner_token_sequence_differs_from_asr", [issue["type"] for issue in issues])
        _, issues = poc.aligned_words("to", [{"text": "to", "start": 0.5, "end": 0.5}], window, 0)
        invalid = [issue for issue in issues if issue["type"] == "invalid_aligned_word"][0]
        self.assertEqual(invalid["reasons"], ["zero_or_negative_duration"])

    def test_pcm_gate_recognizes_exact_silence(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "silence.wav"
            with wave.open(str(path), "wb") as stream:
                stream.setnchannels(1)
                stream.setsampwidth(2)
                stream.setframerate(16000)
                stream.writeframes(b"\0\0" * 16000)
            stats = poc.pcm_stats(path)
        self.assertTrue(stats["exactlyZeroPcm"])
        self.assertEqual(stats["peakPcm"], 0)

    def test_report_never_claims_transcript_completeness(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.wav"
            source.write_bytes(b"source")
            window_dir = root / "window"
            window_dir.mkdir()
            (window_dir / "asr.json").write_text(json.dumps({
                "status": "asr_candidate", "audioSha256": "a", "pcm": {"exactlyZeroPcm": False},
                "model": list(poc.ASR), "text": "One two.",
            }))
            (window_dir / "alignment.json").write_text(json.dumps({
                "model": list(poc.ALIGNER), "words": [
                    {"text": "One", "start": 0.1, "end": 0.3},
                    {"text": "two", "start": 0.5, "end": 0.8},
                ],
            }))
            window = {"id": "w", "audioStart": 0, "duration": 1, "keepStart": 0, "keepEnd": 1,
                      "directory": str(window_dir)}
            report = poc.build_report(source=source, source_id="fixture", source_duration=1,
                                      requested_start=0, requested_duration=1, timeline_offset=20,
                                      windows=[window], gap_seconds=2)
        self.assertEqual(report["status"], "machine_candidate_requires_review")
        self.assertFalse(report["transcriptCompletenessProven"])
        self.assertIn("transcript_completeness_unproven", [item["type"] for item in report["reviewItems"]])
        self.assertEqual(report["words"][1]["timelineEnd"], 20.8)


if __name__ == "__main__":
    unittest.main()
