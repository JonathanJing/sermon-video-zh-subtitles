import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_no_caption_asr_sample_chain.py"
SPEC = importlib.util.spec_from_file_location("build_no_caption_asr_sample_chain", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class BuildNoCaptionAsrSampleChainTest(unittest.TestCase):
    def test_builds_valid_sample_chain_from_asr_smoke(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            smoke = write_asr_smoke(root)
            args = args_for(root, smoke)

            report = mod.build_sample_chain(args)

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["sourceEvidence"], "authorized_extracted_audio_sample")
        self.assertEqual(report["validation"]["status"], "ok")
        self.assertEqual(report["validation"]["sourceEvidence"], "authorized_extracted_audio_sample")
        self.assertEqual(report["validation"]["offlineRoute"]["decision"], "use_asr_fallback")
        self.assertEqual(report["validation"]["asr"]["model"], "gpt-4o-transcribe")
        self.assertEqual(report["validation"]["translation"]["model"], "gpt-5.4-mini")
        self.assertFalse(report["apiKeyMaterialIncluded"])
        self.assertFalse(report["secretResourceNamesIncluded"])

    def test_fails_when_asr_smoke_is_not_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            smoke = root / "asr-smoke.json"
            smoke.write_text(json.dumps({"status": "failed"}), encoding="utf-8")

            report = mod.build_sample_chain(args_for(root, smoke))

        self.assertEqual(report["status"], "failed")
        self.assertIn("not ok", report["message"])


def write_asr_smoke(root: Path) -> Path:
    out_dir = root / "offline-asr-fallback-smoke"
    out_dir.mkdir()
    vtt = out_dir / "asr-smoke.en.vtt"
    vtt.write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:02.500\nGod loved the world.\n",
        encoding="utf-8",
    )
    report = out_dir / "report.json"
    report.write_text(
        json.dumps(
            {
                "status": "ok",
                "cueCount": 1,
                "asr": {"provider": "openai", "model": "gpt-4o-transcribe"},
                "source": {
                    "kind": "authorized_extracted_audio_sample",
                    "path": "artifacts/evidence/realtime-source/synthetic-authorized-speech.wav",
                    "bytes": 1000,
                },
                "outputs": {
                    "vtt": str(vtt),
                    "srt": str(out_dir / "asr-smoke.en.srt"),
                },
                "apiKeyMaterialIncluded": False,
                "secretResourceNamesIncluded": False,
            }
        ),
        encoding="utf-8",
    )
    return report


def args_for(root: Path, smoke: Path):
    class Args:
        pass

    args = Args()
    args.asr_smoke_report = smoke
    args.sunday = "2026-06-28"
    args.out_root = root / "sample-chain"
    args.validation_out = root / "validation.json"
    args.out = root / "sample-chain-report.json"
    return args


if __name__ == "__main__":
    unittest.main()
