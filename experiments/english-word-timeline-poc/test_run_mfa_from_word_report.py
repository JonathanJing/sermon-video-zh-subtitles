import importlib.util
import hashlib
from pathlib import Path
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("run_mfa_from_word_report", HERE / "run_mfa_from_word_report.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class MfaFromWordReportTests(unittest.TestCase):
    def test_frozen_input_accepts_matching_single_run(self):
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "audio.wav"
            audio.write_bytes(b"audio")
            digest = hashlib.sha256(b"audio").hexdigest()
            report = {"modelRuns": [{"rawTranscript": "Frozen words.", "audioSha256": digest}]}
            self.assertEqual(MODULE.frozen_input(report, audio), ("Frozen words.", digest))

    def test_frozen_input_rejects_changed_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "audio.wav"
            audio.write_bytes(b"changed")
            report = {"modelRuns": [{"rawTranscript": "Frozen words.", "audioSha256": "0" * 64}]}
            with self.assertRaisesRegex(ValueError, "Audio hash differs"):
                MODULE.frozen_input(report, audio)


if __name__ == "__main__":
    unittest.main()
