import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
SCRIPT_PATH = SCRIPT_DIR / "run_offline_asr_fallback_smoke.py"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
SPEC = importlib.util.spec_from_file_location("run_offline_asr_fallback_smoke", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class RunOfflineAsrFallbackSmokeTest(unittest.TestCase):
    def test_run_smoke_writes_asr_outputs_without_secret_material(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "audio.wav"
            audio.write_bytes(b"fake wav")
            args = SimpleNamespace(
                audio_file=audio,
                api_key_secret="projects/p/secrets/openai-api-key/versions/latest",
                model="gpt-4o-transcribe",
                fallback_duration_ms=None,
                out_dir=root / "out",
            )
            original_transcribe = mod.offline.transcribe_audio_to_cues
            try:
                mod.offline.transcribe_audio_to_cues = lambda **_kwargs: [
                    mod.offline.Cue(start_ms=0, end_ms=1500, text="God loved the world.", identifier="asr_0001")
                ]

                report = mod.run_smoke(args)
            finally:
                mod.offline.transcribe_audio_to_cues = original_transcribe

            rendered = json.dumps(report)
            self.assertEqual(report["status"], "ok")
            self.assertEqual(report["asr"]["model"], "gpt-4o-transcribe")
            self.assertEqual(report["cueCount"], 1)
            self.assertTrue((root / "out" / "asr-smoke.en.vtt").is_file())
            self.assertTrue((root / "out" / "asr-smoke.en.srt").is_file())
            self.assertNotIn("openai-api-key", rendered)
            self.assertNotIn("projects/p/secrets", rendered)

    def test_run_smoke_failure_is_sanitized(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "audio.wav"
            audio.write_bytes(b"fake wav")
            args = SimpleNamespace(
                audio_file=audio,
                api_key_secret="projects/p/secrets/openai-api-key/versions/latest",
                model="gpt-4o-transcribe",
                fallback_duration_ms=None,
                out_dir=root / "out",
            )
            original_transcribe = mod.offline.transcribe_audio_to_cues
            try:
                def fail(**_kwargs):
                    raise RuntimeError("bad sk-secret123 from projects/p/secrets/openai-api-key/versions/latest")

                mod.offline.transcribe_audio_to_cues = fail
                report = mod.run_smoke(args)
            finally:
                mod.offline.transcribe_audio_to_cues = original_transcribe

            rendered = json.dumps(report)
            self.assertEqual(report["status"], "failed")
            self.assertIn("sk-REDACTED", report["error"])
            self.assertNotIn("sk-secret123", rendered)
            self.assertNotIn("openai-api-key", rendered)


if __name__ == "__main__":
    unittest.main()
