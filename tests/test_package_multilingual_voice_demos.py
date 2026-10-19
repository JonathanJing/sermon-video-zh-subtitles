import importlib.util
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import wave


ROOT = Path(__file__).parents[1]
IMPLEMENTATION = ROOT / "experiments/sermon-dubbing-poc/package_multilingual_voice_demos.py"
SPEC = importlib.util.spec_from_file_location("package_multilingual_voice_demos", IMPLEMENTATION)
subject = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(subject)


class MultilingualVoiceDemoPackageTest(unittest.TestCase):
    def test_cli_from_external_cwd(self):
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            self.skipTest("ffmpeg and ffprobe are required for the synthetic audio fixture")
        with tempfile.TemporaryDirectory() as folder:
            outside = Path(folder)
            registry = outside / "registry.json"
            registry.write_text(json.dumps({"speakers": [{"speakerId": "speaker", "localeCapabilities": [
                {"targetLocale": "ko", "status": "unverified_poc"},
            ]}]}))
            outputs = []
            for label, cli in (("experiment", IMPLEMENTATION),):
                root = outside / label
                wav = root / "speaker/ko.wav"
                wav.parent.mkdir(parents=True)
                with wave.open(str(wav), "wb") as stream:
                    stream.setnchannels(1)
                    stream.setsampwidth(2)
                    stream.setframerate(16000)
                    stream.writeframes(struct.pack("<" + "h" * 1600, *([1000] * 1600)))
                track = {
                    "speakerId": "speaker", "displayName": "Synthetic Speaker", "targetLocale": "ko",
                    "file": "speaker/ko.wav", "audioSha256": hashlib.sha256(wav.read_bytes()).hexdigest(),
                    "fullDecode": "pass", "capabilityStatus": "unverified_poc",
                    "machineScreening": "not_run", "humanListeningStatus": "pending",
                }
                for name, tracks in (("manifest.json", [track]), ("vietnamese-manifest.json", [])):
                    (root / name).write_text(json.dumps({
                        "schemaVersion": "sermon-multilingual-voice-demo-manifest-v1",
                        "trackCount": len(tracks), "fullDecodeCoverage": 1,
                        "humanListeningStatus": "pending", "tracks": tracks,
                    }))
                result = subprocess.run(
                    [sys.executable, str(cli), "--root", str(root), "--registry", str(registry)],
                    cwd=outside, capture_output=True, text=True, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)["trackCount"], 1)
                outputs.append(json.loads((root / "delivery-manifest.json").read_text()))
            self.assertEqual(outputs[0]["humanListeningStatus"], "pending")

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
