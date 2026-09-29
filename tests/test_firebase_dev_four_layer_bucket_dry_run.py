from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts import firebase_dev_four_layer_bucket_dry_run as dry


class FirebaseDevFourLayerBucketDryRunTests(unittest.TestCase):
    def test_rebase_keeps_complete_cue_and_rejects_cross_boundary(self) -> None:
        cue = {"start": 213.44, "end": 216.35, "text": "approved parent text"}
        shifted = dry.rebase(cue)
        self.assertEqual((shifted["start"], shifted["end"]), (0.0, 2.91))
        self.assertEqual(cue["start"], 213.44)
        with self.assertRaisesRegex(ValueError, "crosses clip boundary"):
            dry.rebase({"start": 213.0, "end": 214.0})

    def test_intake_rejects_wrong_hash_and_embedded_credentials(self) -> None:
        with TemporaryDirectory() as directory:
            source = Path(directory) / "clip.mp4"
            source.write_bytes(b"wrong fixture")
            with self.assertRaisesRegex(ValueError, "SHA differs"):
                dry.fetch_clip(source.as_uri(), Path(directory) / "download.mp4", "a" * 64)
            with self.assertRaisesRegex(ValueError, "credential-free"):
                dry.fetch_clip("https://user:password@example.test/clip.mp4",
                               Path(directory) / "download.mp4", "a" * 64)
            with self.assertRaisesRegex(ValueError, "credential-free"):
                dry.fetch_clip("https://example.test/clip.mp4?token=secret",
                               Path(directory) / "download.mp4", "a" * 64)


if __name__ == "__main__":
    unittest.main()
