import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "promote_sunday_manifest.py"
SPEC = importlib.util.spec_from_file_location("promote_sunday_manifest", SCRIPT_PATH)
promote = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(promote)


class PromoteSundayManifestTest(unittest.TestCase):
    def test_promote_manifest_adds_ready_state_without_secret_references(self):
        with tempfile.TemporaryDirectory() as tmp:
            playback = Path(tmp) / "playback-simulation.generated.js"
            playback.write_text(
                'window.SERMON_PLAYBACK_SIMULATION = {"translationStatus":"ready"};',
                encoding="utf-8",
            )
            manifest = {
                "schemaVersion": 1,
                "apiKeyMaterialIncluded": False,
                "secretResourceNamesIncluded": False,
                "outputs": [
                    {
                        "localPath": "web/playback-simulation.generated.js",
                        "gcsUri": str(playback),
                    },
                    {
                        "localPath": "artifacts/sermon.zh.live-aligned.vtt",
                        "gcsUri": "gs://bucket/runs/x/artifacts/sermon.zh.live-aligned.vtt",
                    },
                ],
            }

            promoted = promote.promote_manifest(
                manifest,
                sunday="2026-06-28",
                source_manifest="gs://bucket/runs/x/artifacts/cloud-manifest.json",
            )

        self.assertEqual(promoted["status"], "ready")
        self.assertEqual(promoted["sunday"], "2026-06-28")
        self.assertEqual(promoted["translationStatus"], "ready")
        self.assertEqual(promoted["readiness"]["state"], "published")
        self.assertFalse(promoted["apiKeyMaterialIncluded"])
        self.assertFalse(promoted["secretResourceNamesIncluded"])
        self.assertNotIn("apiKeySecret", json.dumps(promoted))
        self.assertNotIn("/secrets/", json.dumps(promoted))

    def test_rejects_manifest_without_public_playback(self):
        with self.assertRaises(SystemExit):
            promote.promote_manifest(
                {
                    "apiKeyMaterialIncluded": False,
                    "secretResourceNamesIncluded": False,
                    "outputs": [
                        {
                            "localPath": "artifacts/sermon.zh.live-aligned.vtt",
                            "gcsUri": "gs://bucket/runs/x/artifacts/sermon.zh.live-aligned.vtt",
                        }
                    ],
                },
                sunday="2026-06-28",
                source_manifest="gs://bucket/runs/x/artifacts/cloud-manifest.json",
            )

    def test_writes_local_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "sundays" / "2026-06-28" / "cloud-manifest.json"
            promote.write_json(
                str(destination),
                {
                    "status": "ready",
                    "outputs": [],
                    "apiKeyMaterialIncluded": False,
                    "secretResourceNamesIncluded": False,
                },
                dry_run=False,
            )
            self.assertTrue(destination.exists())
            self.assertEqual(json.loads(destination.read_text(encoding="utf-8"))["status"], "ready")


if __name__ == "__main__":
    unittest.main()
