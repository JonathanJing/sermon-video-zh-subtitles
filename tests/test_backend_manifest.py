import json
import tempfile
import unittest
from pathlib import Path

from backend.config import AppConfig
from backend.manifest import SundaySliceService
from backend.storage import LocalArtifactReader


class SundaySliceServiceTest(unittest.TestCase):
    def test_public_slice_filters_secret_and_non_caption_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json(
                root / "manifest.json",
                {
                    "schemaVersion": 1,
                    "status": "ready",
                    "translationStatus": "ready",
                    "apiKeySecret": "projects/p/secrets/openai-api-key/versions/latest",
                    "apiKeyMaterialIncluded": False,
                    "outputs": [
                        {
                            "localPath": "artifacts/report.json",
                            "gcsUri": str(root / "report.json"),
                        },
                        {
                            "localPath": "web/playback-simulation.generated.js",
                            "gcsUri": str(root / "playback.js"),
                        },
                        {
                            "localPath": "model-output/raw.jsonl",
                            "gcsUri": str(root / "raw.jsonl"),
                        },
                        {
                            "localPath": "artifacts/sermon.zh.live-aligned.vtt",
                            "gcsUri": str(root / "sermon.vtt"),
                        },
                    ],
                },
            )
            write_json(
                root / "report.json",
                {
                    "sermon_candidate": {
                        "title": "The Cure for Our Rebellion - Eric Geiger | Mariners Church"
                    }
                },
            )
            (root / "playback.js").write_text("window.SERMON_PLAYBACK_SIMULATION = {}", encoding="utf-8")
            (root / "sermon.vtt").write_text("WEBVTT\n\n", encoding="utf-8")

            service = SundaySliceService(
                AppConfig(
                    artifact_bucket=None,
                    artifact_prefix="sundays",
                    current_manifest_uri=str(root / "manifest.json"),
                    sunday_manifest_uri_template=None,
                    timezone="America/Los_Angeles",
                    openai_api_key_secret=None,
                    operator_admin_token=None,
                    internal_task_token=None,
                    enable_inline_worker=False,
                ),
                LocalArtifactReader(root),
            )

            public_slice = service.get_public_slice("current")

            self.assertEqual(public_slice["artifactCount"], 2)
            self.assertEqual(public_slice["status"], "ready")
            self.assertEqual(public_slice["translationStatus"], "ready")
            self.assertEqual(
                public_slice["sermonTitle"],
                "The Cure for Our Rebellion - Eric Geiger | Mariners Church",
            )
            self.assertNotIn("apiKeySecret", json.dumps(public_slice))
            self.assertNotIn("/secrets/", json.dumps(public_slice))
            self.assertEqual(
                [artifact["key"] for artifact in public_slice["artifacts"]],
                ["playback-js", "sermon-zh-live-aligned-vtt"],
            )
            self.assertEqual(
                public_slice["artifacts"][0]["apiPath"],
                "/api/sundays/current/artifacts/playback-js",
            )

    def test_rejects_non_sunday_slice_date(self):
        service = SundaySliceService(
            AppConfig(
                artifact_bucket="bucket",
                artifact_prefix="sundays",
                current_manifest_uri=None,
                sunday_manifest_uri_template=None,
                timezone="America/Los_Angeles",
                openai_api_key_secret=None,
                operator_admin_token=None,
                internal_task_token=None,
                enable_inline_worker=False,
            ),
            LocalArtifactReader(Path(tempfile.gettempdir())),
        )

        with self.assertRaises(ValueError):
            service.manifest_uri_for("2026-06-23")


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
