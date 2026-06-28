import json
import tempfile
import unittest
from pathlib import Path

import scripts.build_local_sunday_manifest_evidence as mod
from scripts.build_playback_simulation import refresh_polished_layers


class BuildLocalSundayManifestEvidenceTest(unittest.TestCase):
    def test_builds_promoted_manifest_and_validation_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            out = root / "out"
            validation_out = root / "sunday-manifest-validation.json"
            write_source_run(source)

            report = mod.build_local_sunday_manifest_evidence(
                sunday="2026-06-28",
                source_run_root=source,
                source_manifest=None,
                out_root=out,
                validation_out=validation_out,
            )

            promoted = json.loads((out / "cloud-manifest.json").read_text(encoding="utf-8"))
            validation = json.loads(validation_out.read_text(encoding="utf-8"))
            copied_report_exists = (out / "artifacts" / "report.json").is_file()

        self.assertEqual(report["status"], "ok")
        self.assertEqual(promoted["sunday"], "2026-06-28")
        self.assertEqual(promoted["readiness"]["state"], "published")
        self.assertEqual(promoted["generationMode"], "youtube-live-archive")
        self.assertEqual(promoted["translationStatus"], "ready")
        self.assertEqual(promoted["models"]["realtimeDraft"], "gpt-realtime-translate")
        self.assertEqual(promoted["models"]["offlineAsr"], "gpt-4o-transcribe")
        self.assertEqual(promoted["models"]["offlineTranslation"], "gpt-5.4-mini")
        self.assertEqual(promoted["models"]["stableCorrection"], "gpt-5.4-mini")
        self.assertEqual(validation["status"], "ok")
        self.assertEqual(validation["failedChecks"], [])
        self.assertEqual(validation["playback"]["translatedSegments"], 1)
        self.assertEqual(report["offlineChainValidation"]["status"], "ok")
        self.assertEqual(report["offlineChainValidation"]["offlineRoute"]["decision"], "use_caption_track")
        self.assertEqual(report["offlineChainValidation"]["translation"]["model"], "gpt-5.4-mini")
        self.assertTrue(copied_report_exists)
        self.assertFalse(report["apiKeyMaterialIncluded"])
        self.assertFalse(report["secretResourceNamesIncluded"])

    def test_fails_when_manifest_output_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            write_source_run(source)
            (source / "artifacts" / "sermon.zh.live-aligned.srt").unlink()

            with self.assertRaises(SystemExit):
                mod.build_local_sunday_manifest_evidence(
                    sunday="2026-06-28",
                    source_run_root=source,
                    source_manifest=None,
                    out_root=Path(tmp) / "out",
                    validation_out=None,
                )


def write_source_run(root: Path) -> None:
    (root / "web").mkdir(parents=True)
    (root / "artifacts").mkdir(parents=True)
    playback = refresh_polished_layers(
        {
            "generatedFrom": "openai-translation-e2e",
            "translationStatus": "ready",
            "offlineSourceKind": "live_archive",
            "translationProvider": {"model": "gpt-5.4-mini"},
            "segments": [
                {
                    "id": "seg_1",
                    "startMs": 1000,
                    "endMs": 2500,
                    "en": "Grace and peace.",
                    "zh": "愿恩典与平安归给你们。",
                    "translationStatus": "ready",
                }
            ],
        }
    )
    (root / "web" / "playback-simulation.generated.js").write_text(
        "window.SERMON_PLAYBACK_SIMULATION = " + json.dumps(playback, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )
    (root / "artifacts" / "report.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "status": "ok",
                "caption_source": {"kind": "live_archive"},
                "offline_route": {
                    "strategy": "captions_first_then_asr",
                    "requestedLangs": ["en-orig", "en"],
                    "liveCaptionLangs": ["en"],
                    "sermonVodCaptionLangs": [],
                    "selectedSourceKind": "live_archive",
                    "decision": "use_caption_track",
                    "asrFallbackRequired": False,
                    "audioExtractionAttempted": False,
                    "fallbackReason": None,
                    "status": "caption_track_selected",
                },
                "asr": {"provider": "openai", "model": "gpt-4o-transcribe"},
                "outputs": [
                    {
                        "source_file": "raw/live.en.vtt",
                        "live_aligned_vtt": "artifacts/live.sermon.en.live-aligned.vtt",
                    }
                ],
                "apiKeyMaterialIncluded": False,
                "secretResourceNamesIncluded": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (root / "artifacts" / "sermon.zh.live-aligned.vtt").write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:02.500\n愿恩典与平安归给你们。\n",
        encoding="utf-8",
    )
    (root / "artifacts" / "sermon.zh.live-aligned.srt").write_text(
        "1\n00:00:01,000 --> 00:00:02,500\n愿恩典与平安归给你们。\n",
        encoding="utf-8",
    )
    (root / "artifacts" / "cloud-manifest.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "status": "ready",
                "translationStatus": "ready",
                "apiKeyMaterialIncluded": False,
                "secretResourceNamesIncluded": False,
                "outputs": [
                    {"localPath": "web/playback-simulation.generated.js", "gcsUri": ""},
                    {"localPath": "artifacts/sermon.zh.live-aligned.vtt", "gcsUri": ""},
                    {"localPath": "artifacts/sermon.zh.live-aligned.srt", "gcsUri": ""},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
