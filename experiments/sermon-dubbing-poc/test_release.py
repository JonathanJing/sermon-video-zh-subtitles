import json
from pathlib import Path
import tempfile
import unittest

from deploy_firebase import verify_release
from poc import sha256


class ReleaseTests(unittest.TestCase):
    def test_upload_directory_rejects_unlisted_training_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "public").mkdir()
            index = root / "public/index.html"
            index.write_text("<html></html>")
            (root / "build-report.json").write_text(json.dumps({"files": [{"path": "index.html", "sha256": sha256(index)}]}))
            verify_release(root)
            (root / "public/private-reference.wav").write_bytes(b"private")
            with self.assertRaises(ValueError):
                verify_release(root)

    def test_changed_release_bytes_are_not_deployed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "public").mkdir()
            index = root / "public/index.html"
            index.write_text("original")
            (root / "build-report.json").write_text(json.dumps({"files": [{"path": "index.html", "sha256": sha256(index)}]}))
            index.write_text("modified after verification")
            with self.assertRaises(ValueError):
                verify_release(root)


if __name__ == '__main__':
    unittest.main()
