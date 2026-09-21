import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "package_multilingual_voice_demos", ROOT / "scripts/package_multilingual_voice_demos.py"
)
subject = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(subject)


class MultilingualVoiceDemoPackageTest(unittest.TestCase):
    def test_duplicate_track_is_rejected_before_encoding(self):
        registry = {"speakers": [{"speakerId": "speaker", "localeCapabilities": [{"targetLocale": "ko", "status": "unverified_poc"}]}]}
        track = {
            "speakerId": "speaker", "targetLocale": "ko", "file": "speaker/ko.wav",
            "audioSha256": "unused", "fullDecode": "pass",
        }
        qwen = {"schemaVersion": "sermon-multilingual-voice-demo-manifest-v1", "trackCount": 2, "fullDecodeCoverage": 1, "humanListeningStatus": "pending", "tracks": [track, track]}
        vi = {"schemaVersion": "sermon-multilingual-voice-demo-manifest-v1", "trackCount": 0, "fullDecodeCoverage": 1, "humanListeningStatus": "pending", "tracks": []}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "manifest.json").write_text(json.dumps(qwen))
            (root / "vietnamese-manifest.json").write_text(json.dumps(vi))
            with self.assertRaisesRegex(ValueError, "duplicate"):
                subject.collect_tracks(root, registry)

    def test_missing_matrix_member_is_rejected(self):
        registry = {"speakers": [{"speakerId": "speaker", "localeCapabilities": [
            {"targetLocale": "ko", "status": "unverified_poc"},
            {"targetLocale": "vi", "status": "unverified_poc"},
        ]}]}
        qwen = {"schemaVersion": "sermon-multilingual-voice-demo-manifest-v1", "trackCount": 0, "fullDecodeCoverage": 1, "humanListeningStatus": "pending", "tracks": []}
        vi = dict(qwen)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "manifest.json").write_text(json.dumps(qwen))
            (root / "vietnamese-manifest.json").write_text(json.dumps(vi))
            with self.assertRaisesRegex(ValueError, "matrix differs"):
                subject.collect_tracks(root, registry)


if __name__ == "__main__":
    unittest.main()
