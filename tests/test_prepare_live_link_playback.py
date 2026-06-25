import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "prepare_live_link_playback.py"
SPEC = importlib.util.spec_from_file_location("prepare_live_link_playback", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class PrepareLiveLinkPlaybackTest(unittest.TestCase):
    def test_default_asr_model_uses_gpt_4o_transcribe(self):
        self.assertEqual(mod.DEFAULT_ASR_MODEL, "gpt-4o-transcribe")

    def test_prepare_command_passes_api_key_secret_to_asr_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            commands = []
            original_parse_args = mod.parse_args
            original_run = mod.run
            try:
                mod.parse_args = lambda: type(
                    "Args",
                    (),
                    {
                        "live_url": "https://youtube.test/watch?v=abc123",
                        "sermon_url": None,
                        "sermon_start": None,
                        "lang": [],
                        "playback_lang": None,
                        "out_dir": root / "artifacts",
                        "web_out": root / "web" / "test-asr.generated.js",
                        "playlist_end": 1,
                        "max_segments": 8,
                        "playback_speed": 18.0,
                        "asr_model": "gpt-4o-transcribe",
                        "gcs_bucket": None,
                        "gcs_prefix": "poc/live-link",
                        "gcs_dry_run": True,
                        "api_key_secret": "projects/p/secrets/openai-api-key/versions/latest",
                    },
                )()
                mod.run = lambda command, cwd: commands.append(command)
                rc = mod.main()
            finally:
                mod.parse_args = original_parse_args
                mod.run = original_run

        self.assertEqual(rc, 0)
        self.assertIn("--api-key-secret", commands[0])
        self.assertIn("projects/p/secrets/openai-api-key/versions/latest", commands[0])
        self.assertIn("--asr-model", commands[0])

    def test_rejects_realtime_model_for_offline_asr(self):
        with self.assertRaises(SystemExit):
            mod.validate_asr_model("gpt-realtime-translate")

    def test_rejects_non_required_model_for_offline_asr(self):
        with self.assertRaises(SystemExit):
            mod.validate_asr_model("gpt-4o-mini-transcribe")

    def test_generated_content_files_and_dry_run_gcs_uris(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out_dir = root / "artifacts"
            out_dir.mkdir()
            web_out = root / "web" / "playback-simulation.generated.js"
            web_out.parent.mkdir()

            expected = [
                out_dir / "report.json",
                out_dir / "report.md",
                out_dir / "sermon.en.live-aligned.vtt",
                out_dir / "sermon.en.live-aligned.srt",
                web_out,
            ]
            for path in expected:
                path.write_text("x", encoding="utf-8")
            (out_dir / "ignore.txt").write_text("x", encoding="utf-8")

            files = mod.generated_content_files(out_dir, web_out)
            uploads = mod.publish_files_to_gcs(
                files=files,
                bucket="sermon-zh-poc",
                prefix="runs/2026-06-22",
                out_dir=out_dir,
                web_out=web_out,
                dry_run=True,
            )

            self.assertEqual(len(files), 5)
            self.assertIn(
                "gs://sermon-zh-poc/runs/2026-06-22/artifacts/report.json",
                [item["gcsUri"] for item in uploads],
            )
            self.assertIn(
                "gs://sermon-zh-poc/runs/2026-06-22/web/playback-simulation.generated.js",
                [item["gcsUri"] for item in uploads],
            )
            self.assertIn(
                {"localPath": "artifacts/report.json", "gcsUri": "gs://sermon-zh-poc/runs/2026-06-22/artifacts/report.json"},
                uploads,
            )

    def test_cloud_manifest_never_contains_secret_reference_or_api_key_material(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            web_out = out_dir / "playback.js"
            (out_dir / "report.json").write_text(
                '{"caption_source":{"kind":"live_archive"},"offline_route":{"strategy":"captions_first_then_asr","decision":"use_caption_track","selectedSourceKind":"live_archive","asrFallbackRequired":false,"audioExtractionAttempted":false,"fallbackReason":null}}',
                encoding="utf-8",
            )
            web_out.write_text(
                'window.SERMON_PLAYBACK_SIMULATION = {"offlineSourceKind":"live_archive"};\n',
                encoding="utf-8",
            )
            manifest = mod.write_cloud_manifest(
                out_dir=out_dir,
                web_out=web_out,
                gcs_outputs=[{"localPath": "x", "gcsUri": "gs://bucket/x"}],
                api_key_secret="projects/p/secrets/openai-api-key/versions/latest",
                report_path=out_dir / "report.json",
                playback_path=web_out,
            )

            text = manifest.read_text(encoding="utf-8")
            payload = json.loads(text)
            self.assertNotIn("apiKeySecret", text)
            self.assertNotIn("projects/p/secrets", text)
            self.assertNotIn("openai-api-key", text)
            self.assertEqual(payload["offlineSourceKind"], "live_archive")
            self.assertEqual(payload["offlineRoute"]["decision"], "use_caption_track")
            self.assertIn('"apiKeyMaterialIncluded": false', text)
            self.assertIn('"secretResourceNamesIncluded": false', text)
            self.assertIn('"serverSideSecretConfigured": true', text)
            self.assertNotIn(str(out_dir), text)

    def test_gcs_bucket_and_prefix_are_normalized(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out_dir = root / "artifacts"
            out_dir.mkdir()
            report = out_dir / "report.json"
            report.write_text("{}", encoding="utf-8")

            uploads = mod.publish_files_to_gcs(
                files=[report],
                bucket="gs://sermon-zh-poc/",
                prefix="/runs/2026-06-22/",
                out_dir=out_dir,
                web_out=root / "web" / "playback-simulation.generated.js",
                dry_run=True,
            )

            self.assertEqual(
                uploads[0]["gcsUri"],
                "gs://sermon-zh-poc/runs/2026-06-22/artifacts/report.json",
            )

    def test_rejects_raw_api_key_material_for_secret_reference(self):
        with self.assertRaises(SystemExit):
            mod.validate_secret_resource_name("sk-this-looks-like-raw-key-material")

    def test_rejects_unsafe_gcs_prefix(self):
        with self.assertRaises(SystemExit):
            mod.normalize_gcs_prefix("../runs")


if __name__ == "__main__":
    unittest.main()
