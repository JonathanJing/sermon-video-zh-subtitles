"""Tiny generated WAVs exercise the decoder gates; real job checks run separately."""
import hashlib
from pathlib import Path
import shutil
import tempfile
import unittest
import wave

from media_check import decode


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg tools are required")
class MediaCheckTests(unittest.TestCase):
    def test_decodes_audio_and_rejects_changed_hash_or_wrong_duration(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "synthetic.wav"
            with wave.open(str(path), "wb") as stream:
                stream.setnchannels(1)
                stream.setsampwidth(2)
                stream.setframerate(16000)
                stream.writeframes(b"\0\0" * 16000)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            report = decode(path, digest, 1)
            self.assertEqual(report["fullDecode"], "pass")
            self.assertEqual(report["durationSeconds"], 1)
            with self.assertRaisesRegex(ValueError, "duration_differs"):
                decode(path, digest, 2)
            with self.assertRaisesRegex(ValueError, "hash_mismatch"):
                decode(path, "0" * 64, 1)


if __name__ == "__main__":
    unittest.main()
