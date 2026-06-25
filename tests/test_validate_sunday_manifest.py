import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "validate_sunday_manifest.py"
SPEC = importlib.util.spec_from_file_location("validate_sunday_manifest", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class ValidateSundayManifestTest(unittest.TestCase):
    def write_ready_artifacts(self, root: Path) -> dict:
        playback = root / "playback-simulation.generated.js"
        playback.write_text(
            "window.SERMON_PLAYBACK_SIMULATION = "
            + json.dumps(
                {
                    "translationStatus": "ready",
                    "translationProvider": {"model": "gpt-5.4-mini"},
                    "offlineSourceKind": "live_archive",
                    "segments": [
                        {
                            "id": "seg_1",
                            "startMs": 1000,
                            "endMs": 2000,
                            "en": "God loved the world.",
                            "zh": "神爱世人。",
                            "translationStatus": "ready",
                        }
                    ],
                },
                ensure_ascii=False,
            )
            + ";\n",
            encoding="utf-8",
        )
        vtt = root / "sermon.zh.live-aligned.vtt"
        vtt.write_text("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n神爱世人。\n", encoding="utf-8")
        srt = root / "sermon.zh.live-aligned.srt"
        srt.write_text("1\n00:00:01,000 --> 00:00:02,000\n神爱世人。\n", encoding="utf-8")
        manifest = {
            "schemaVersion": 1,
            "status": "ready",
            "sunday": "2026-06-28",
            "generationMode": "youtube-live-archive",
            "translationStatus": "ready",
            "readiness": {
                "state": "published",
                "sourceMode": "youtube-live-archive",
                "publicArtifactsReady": True,
            },
            "models": {
                "realtimeDraft": "gpt-realtime-translate",
                "offlineAsr": "gpt-4o-transcribe",
                "offlineTranslation": "gpt-5.4-mini",
                "stableCorrection": "gpt-5.4-mini",
            },
            "offlineSourceKind": "live_archive",
            "offlineRoute": {
                "strategy": "captions_first_then_asr",
                "decision": "use_caption_track",
                "selectedSourceKind": "live_archive",
                "asrFallbackRequired": False,
                "audioExtractionAttempted": False,
                "fallbackReason": None,
            },
            "apiKeyMaterialIncluded": False,
            "secretResourceNamesIncluded": False,
            "outputs": [
                {"localPath": "web/playback-simulation.generated.js", "gcsUri": str(playback)},
                {"localPath": "artifacts/sermon.zh.live-aligned.vtt", "gcsUri": str(vtt)},
                {"localPath": "artifacts/sermon.zh.live-aligned.srt", "gcsUri": str(srt)},
            ],
        }
        return manifest

    def test_validates_ready_manifest_and_readable_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_ready_artifacts(root)

            report = mod.validate_manifest_contract(
                manifest=manifest,
                manifest_uri=str(root / "cloud-manifest.json"),
                sunday="2026-06-28",
                require_readable_artifacts=True,
            )

            self.assertEqual(report["status"], "ok")
            self.assertEqual(report["artifactLocation"], "local")
            self.assertFalse(report["publicGcsArtifacts"])
            self.assertTrue(report["readableArtifactsRequired"])
            self.assertEqual(report["failedChecks"], [])
            self.assertEqual(report["playback"]["translatedSegments"], 1)
            self.assertEqual(report["offlineRoute"]["decision"], "use_caption_track")
            self.assertEqual(report["offlineRoute"]["offlineSourceKind"], "live_archive")
            self.assertIn("artifacts/sermon.zh.live-aligned.vtt", report["outputs"]["chineseVtt"])
            self.assertIn("artifacts/sermon.zh.live-aligned.srt", report["outputs"]["chineseSrt"])
            self.assertFalse(report["apiKeyMaterialIncluded"])
            self.assertFalse(report["secretResourceNamesIncluded"])

    def test_fails_without_chinese_srt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_ready_artifacts(root)
            manifest["outputs"] = [
                item for item in manifest["outputs"] if not item["localPath"].endswith(".srt")
            ]

            report = mod.validate_manifest_contract(
                manifest=manifest,
                manifest_uri=str(root / "cloud-manifest.json"),
                require_readable_artifacts=True,
            )

            self.assertEqual(report["status"], "failed")
            self.assertIn("chinese_srt", report["failedChecks"])

    def test_fails_wrong_offline_translation_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_ready_artifacts(root)
            manifest["models"]["offlineTranslation"] = "gpt-realtime-translate"

            report = mod.validate_manifest_contract(
                manifest=manifest,
                manifest_uri=str(root / "cloud-manifest.json"),
            )

        self.assertEqual(report["status"], "failed")
        self.assertIn("model_offlineTranslation", report["failedChecks"])

    def test_fails_manifest_without_offline_route_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_ready_artifacts(root)
            manifest.pop("offlineSourceKind")
            manifest.pop("offlineRoute")

            report = mod.validate_manifest_contract(
                manifest=manifest,
                manifest_uri=str(root / "cloud-manifest.json"),
            )

        self.assertEqual(report["status"], "failed")
        self.assertIn("offline_source_kind", report["failedChecks"])
        self.assertIn("offline_route_strategy", report["failedChecks"])

    def test_fails_asr_route_that_does_not_mark_audio_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_ready_artifacts(root)
            manifest["offlineSourceKind"] = "openai_asr"
            manifest["offlineRoute"] = {
                "strategy": "captions_first_then_asr",
                "decision": "use_asr_fallback",
                "selectedSourceKind": "openai_asr",
                "asrFallbackRequired": True,
                "audioExtractionAttempted": False,
                "fallbackReason": "no_requested_caption_track",
            }

            report = mod.validate_manifest_contract(
                manifest=manifest,
                manifest_uri=str(root / "cloud-manifest.json"),
            )

        self.assertEqual(report["status"], "failed")
        self.assertIn("offline_route_asr_fallback", report["failedChecks"])

    def test_fails_placeholder_playback_when_artifacts_are_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_ready_artifacts(root)
            playback = Path(manifest["outputs"][0]["gcsUri"])
            playback.write_text(
                "window.SERMON_PLAYBACK_SIMULATION = "
                + json.dumps(
                    {
                        "translationStatus": "ready",
                        "segments": [
                            {
                                "zh": "AI 中文待生成：God loved the world.",
                                "translationStatus": "needs_translation",
                            }
                        ],
                    },
                    ensure_ascii=False,
                )
                + ";\n",
                encoding="utf-8",
            )

            report = mod.validate_manifest_contract(
                manifest=manifest,
                manifest_uri=str(root / "cloud-manifest.json"),
                require_readable_artifacts=True,
            )

            self.assertEqual(report["status"], "failed")
            self.assertIn("playback_translated_segments", report["failedChecks"])

    def test_fails_secret_material_in_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_ready_artifacts(root)
            manifest["apiKeySecret"] = "projects/p/secrets/openai-api-key/versions/latest"

            report = mod.validate_manifest_contract(
                manifest=manifest,
                manifest_uri=str(root / "cloud-manifest.json"),
            )

            self.assertEqual(report["status"], "failed")
            self.assertIn("secret_strings", report["failedChecks"])

    def test_main_writes_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.write_ready_artifacts(root)
            manifest_path = root / "cloud-manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            out = root / "manifest-validation.json"
            argv = [
                "validate_sunday_manifest.py",
                "--manifest",
                str(manifest_path),
                "--sunday",
                "2026-06-28",
                "--require-readable-artifacts",
                "--out",
                str(out),
            ]
            stdout = io.StringIO()
            original_argv = mod.sys.argv
            original_stdout = mod.sys.stdout
            try:
                mod.sys.argv = argv
                mod.sys.stdout = stdout
                exit_code = mod.main()
            finally:
                mod.sys.argv = original_argv
                mod.sys.stdout = original_stdout

            payload = json.loads(out.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(json.loads(stdout.getvalue())["status"], "ok")

    def test_main_writes_failed_report_when_manifest_cannot_be_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing = root / "missing-cloud-manifest.json"
            out = root / "manifest-validation.json"
            argv = [
                "validate_sunday_manifest.py",
                "--manifest",
                str(missing),
                "--sunday",
                "2026-06-28",
                "--require-readable-artifacts",
                "--out",
                str(out),
            ]
            stdout = io.StringIO()
            original_argv = mod.sys.argv
            original_stdout = mod.sys.stdout
            try:
                mod.sys.argv = argv
                mod.sys.stdout = stdout
                exit_code = mod.main()
            finally:
                mod.sys.argv = original_argv
                mod.sys.stdout = original_stdout

            payload = json.loads(out.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "failed")
        self.assertIn("manifest_readable", payload["failedChecks"])
        self.assertFalse(payload["apiKeyMaterialIncluded"])
        self.assertFalse(payload["secretResourceNamesIncluded"])

    def test_marks_gcs_manifest_and_outputs_as_public_gcs_artifacts(self):
        manifest = self.write_ready_artifacts(Path("/tmp"))
        for output in manifest["outputs"]:
            output["gcsUri"] = f"gs://bucket/sundays/2026-06-28/{output['localPath']}"

        report = mod.validate_manifest_contract(
            manifest=manifest,
            manifest_uri="gs://bucket/sundays/2026-06-28/cloud-manifest.json",
            sunday="2026-06-28",
            require_readable_artifacts=False,
        )

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["artifactLocation"], "gcs")
        self.assertTrue(report["publicGcsArtifacts"])
        self.assertFalse(report["readableArtifactsRequired"])
        self.assertIsNone(report["playback"]["readable"])


if __name__ == "__main__":
    unittest.main()
