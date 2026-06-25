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
                destination_manifest="gs://bucket/sundays/2026-06-28/cloud-manifest.json",
                operator_reviewed=True,
            )

        self.assertEqual(promoted["status"], "ready")
        self.assertEqual(promoted["sunday"], "2026-06-28")
        self.assertEqual(promoted["translationStatus"], "ready")
        self.assertEqual(promoted["generationMode"], "youtube-live-archive")
        self.assertEqual(promoted["publishedManifest"], "gs://bucket/sundays/2026-06-28/cloud-manifest.json")
        self.assertEqual(promoted["models"]["realtimeDraft"], "gpt-realtime-translate")
        self.assertEqual(promoted["models"]["offlineAsr"], "gpt-4o-transcribe")
        self.assertEqual(promoted["models"]["offlineTranslation"], "gpt-5.4-mini")
        self.assertEqual(promoted["models"]["stableCorrection"], "gpt-5.4-mini")
        self.assertEqual(promoted["readiness"]["state"], "published")
        self.assertEqual(promoted["readiness"]["sourceMode"], "youtube-live-archive")
        self.assertTrue(promoted["readiness"]["operatorReviewed"])
        self.assertTrue(promoted["readiness"]["publishedAt"])
        self.assertEqual(promoted["readiness"]["publishedManifest"], "gs://bucket/sundays/2026-06-28/cloud-manifest.json")
        self.assertFalse(promoted["apiKeyMaterialIncluded"])
        self.assertFalse(promoted["secretResourceNamesIncluded"])
        self.assertNotIn("apiKeySecret", json.dumps(promoted))
        self.assertNotIn("/secrets/", json.dumps(promoted))

    def test_fallback_readiness_requires_reason(self):
        with self.assertRaises(SystemExit):
            promote.promote_manifest(
                {
                    "apiKeyMaterialIncluded": False,
                    "secretResourceNamesIncluded": False,
                    "outputs": [
                        {"localPath": "web/playback-simulation.generated.js", "gcsUri": "gs://bucket/web/playback.js"},
                        {"localPath": "artifacts/sermon.zh.live-aligned.vtt", "gcsUri": "gs://bucket/sermon.vtt"},
                    ],
                },
                sunday="2026-06-28",
                source_manifest="gs://bucket/runs/x/artifacts/cloud-manifest.json",
                readiness_state="fallback",
            )

    def test_fallback_readiness_records_reason(self):
        promoted = promote.promote_manifest(
            {
                "apiKeyMaterialIncluded": False,
                "secretResourceNamesIncluded": False,
                "outputs": [
                    {"localPath": "web/playback-simulation.generated.js", "gcsUri": "gs://bucket/web/playback.js"},
                    {"localPath": "artifacts/sermon.zh.live-aligned.vtt", "gcsUri": "gs://bucket/sermon.vtt"},
                ],
            },
            sunday="2026-06-28",
            source_manifest="gs://bucket/runs/x/artifacts/cloud-manifest.json",
            readiness_state="fallback",
            fallback_reason="Realtime source failed; showing reviewed offline captions.",
        )

        self.assertEqual(promoted["status"], "fallback")
        self.assertEqual(promoted["readiness"]["state"], "fallback")
        self.assertTrue(promoted["readiness"]["fallback"])
        self.assertIn("Realtime source failed", promoted["readiness"]["fallbackReason"])

    def test_rejects_published_manifest_when_translation_status_is_unknown(self):
        with self.assertRaises(SystemExit):
            promote.promote_manifest(
                {
                    "apiKeyMaterialIncluded": False,
                    "secretResourceNamesIncluded": False,
                    "outputs": [
                        {"localPath": "web/playback-simulation.generated.js", "gcsUri": "gs://bucket/web/playback.js"},
                        {"localPath": "artifacts/sermon.zh.live-aligned.vtt", "gcsUri": "gs://bucket/sermon.zh.vtt"},
                    ],
                },
                sunday="2026-06-28",
                source_manifest="gs://bucket/runs/x/artifacts/cloud-manifest.json",
                readiness_state="published",
            )

    def test_rejects_ready_manifest_when_translation_status_needs_translation(self):
        with tempfile.TemporaryDirectory() as tmp:
            playback = Path(tmp) / "playback-simulation.generated.js"
            playback.write_text(
                'window.SERMON_PLAYBACK_SIMULATION = {"translationStatus":"needs_translation"};',
                encoding="utf-8",
            )
            with self.assertRaises(SystemExit):
                promote.promote_manifest(
                    {
                        "apiKeyMaterialIncluded": False,
                        "secretResourceNamesIncluded": False,
                        "outputs": [
                            {"localPath": "web/playback-simulation.generated.js", "gcsUri": str(playback)},
                            {"localPath": "artifacts/sermon.zh.live-aligned.vtt", "gcsUri": "gs://bucket/sermon.zh.vtt"},
                        ],
                    },
                    sunday="2026-06-28",
                    source_manifest="gs://bucket/runs/x/artifacts/cloud-manifest.json",
                    readiness_state="ready",
                )

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

    def test_rejects_manifest_without_chinese_caption_output(self):
        with self.assertRaises(SystemExit):
            promote.promote_manifest(
                {
                    "apiKeyMaterialIncluded": False,
                    "secretResourceNamesIncluded": False,
                    "outputs": [
                        {"localPath": "web/playback-simulation.generated.js", "gcsUri": "gs://bucket/web/playback.js"},
                        {"localPath": "artifacts/sermon.en.live-aligned.vtt", "gcsUri": "gs://bucket/sermon.en.vtt"},
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

    def test_read_json_accepts_relative_nested_local_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path.cwd()
            try:
                root = Path(tmp)
                nested = root / "artifacts" / "cloud-manifest.json"
                nested.parent.mkdir(parents=True)
                nested.write_text('{"status":"ok"}', encoding="utf-8")
                import os

                os.chdir(root)
                loaded = promote.read_json("artifacts/cloud-manifest.json")
            finally:
                os.chdir(cwd)

        self.assertEqual(loaded["status"], "ok")


if __name__ == "__main__":
    unittest.main()
