import importlib.util
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "publish_post_live_sunday_manifest.py"
SPEC = importlib.util.spec_from_file_location("publish_post_live_sunday_manifest", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class PublishPostLiveSundayManifestTest(unittest.TestCase):
    def test_builds_reviewed_sunday_manifest_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pipeline = root / "pipeline"
            pipeline.mkdir()
            (pipeline / "sermon_zh_relative.reviewed.srt").write_text(
                "1\n00:00:01,000 --> 00:00:02,500\n神爱世人。\n",
                encoding="utf-8",
            )
            (pipeline / "sermon_zh_relative.reviewed.vtt").write_text(
                "WEBVTT\n\n00:00:01.000 --> 00:00:02.500\n神爱世人。\n",
                encoding="utf-8",
            )
            (pipeline / "sermon_en_relative.srt").write_text(
                "1\n00:00:01,000 --> 00:00:02,500\nGod loved the world.\n",
                encoding="utf-8",
            )
            (pipeline / "summary.json").write_text(
                json.dumps(
                    {
                        "sourceDurationSeconds": 3600,
                        "clipDurationSeconds": 90,
                        "sermonStartSeconds": 1630,
                        "sermonStartTimecode": "00:27:10.000",
                        "sermonEndSeconds": 1720,
                        "sermonEndTimecode": "00:28:40.000",
                    }
                ),
                encoding="utf-8",
            )
            out_root = root / "sunday-package"

            report = mod.publish_post_live_sunday_manifest(
                Namespace(
                    sunday="2026-07-05",
                    slug="abc123",
                    pipeline_outdir=pipeline,
                    out_root=out_root,
                    live_url="https://www.youtube.com/watch?v=abc123",
                    title="Reviewed Sermon",
                    translation_model="gpt-5.5",
                    asr_model="gpt-4o-transcribe",
                    stable_correction_model="gpt-5.4-mini",
                    realtime_draft_model="gpt-realtime-translate",
                    gcs_bucket=None,
                    gcs_prefix="sundays",
                    session_id=None,
                    apply=False,
                    out=None,
                )
            )

            manifest = json.loads((out_root / "cloud-manifest.json").read_text(encoding="utf-8"))
            playback_text = (out_root / "web" / "playback-simulation.generated.js").read_text(encoding="utf-8")
            playback = json.loads(playback_text.removeprefix(mod.JS_PREFIX).rstrip(";\n"))

        self.assertEqual(report["status"], "planned")
        self.assertEqual(report["segmentCount"], 1)
        self.assertEqual(manifest["sunday"], "2026-07-05")
        self.assertEqual(manifest["readiness"]["state"], "published")
        self.assertEqual(manifest["models"]["offlineTranslation"], "gpt-5.5")
        self.assertEqual(playback["segments"][0]["zh"], "神爱世人。")
        self.assertEqual(playback["segments"][0]["en"], "God loved the world.")
        self.assertEqual(playback["translationProvider"]["model"], "gpt-5.5")


if __name__ == "__main__":
    unittest.main()
