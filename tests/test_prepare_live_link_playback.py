import importlib.util
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
            manifest = mod.write_cloud_manifest(
                out_dir=out_dir,
                web_out=web_out,
                gcs_outputs=[{"localPath": "x", "gcsUri": "gs://bucket/x"}],
                api_key_secret="projects/p/secrets/openai-api-key/versions/latest",
            )

            text = manifest.read_text(encoding="utf-8")
            self.assertNotIn("apiKeySecret", text)
            self.assertNotIn("projects/p/secrets", text)
            self.assertNotIn("openai-api-key", text)
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
