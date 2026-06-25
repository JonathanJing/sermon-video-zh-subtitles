import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "validate_production_readiness.py"
SPEC = importlib.util.spec_from_file_location("validate_production_readiness", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class ValidateProductionReadinessTest(unittest.TestCase):
    def write_fixture_set(self, root: Path) -> dict[str, Path]:
        report = root / "report.json"
        playback = root / "playback-simulation.generated.js"
        zh_vtt = root / "sermon.zh.live-aligned.vtt"
        zh_srt = root / "sermon.zh.live-aligned.srt"
        run_manifest = root / "run-cloud-manifest.json"
        sunday_manifest = root / "sunday-cloud-manifest.json"
        realtime = root / "rt_test.jsonl"

        report.write_text(
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
                            "lang": "en",
                            "source_file": "raw/live.en.vtt",
                            "cue_count": 1,
                            "local_vtt": "artifacts/live.sermon.en.local.vtt",
                            "live_aligned_vtt": "artifacts/live.sermon.en.live-aligned.vtt",
                            "local_srt": "artifacts/live.sermon.en.local.srt",
                            "live_aligned_srt": "artifacts/live.sermon.en.live-aligned.srt",
                        }
                    ],
                    "apiKeyMaterialIncluded": False,
                    "secretResourceNamesIncluded": False,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        playback_payload = {
            "schemaVersion": 1,
            "generatedFrom": "openai-translation-e2e",
            "translationStatus": "ready",
            "offlineSourceKind": "live_archive",
            "offlineRoute": {
                "strategy": "captions_first_then_asr",
                "decision": "use_caption_track",
                "selectedSourceKind": "live_archive",
                "asrFallbackRequired": False,
                "audioExtractionAttempted": False,
                "fallbackReason": None,
            },
            "translationProvider": {
                "provider": "openai",
                "model": "gpt-5.4-mini",
                "apiKeyMaterialIncluded": False,
                "secretResourceNamesIncluded": False,
            },
            "segments": [
                {
                    "id": "sim_0001",
                    "startMs": 1000,
                    "endMs": 2500,
                    "en": "God loved the world.",
                    "zh": "神爱世人。",
                    "translationStatus": "ready",
                }
            ],
        }
        playback.write_text(
            "window.SERMON_PLAYBACK_SIMULATION = "
            + json.dumps(playback_payload, ensure_ascii=False)
            + ";\n",
            encoding="utf-8",
        )
        zh_vtt.write_text("WEBVTT\n\n00:00:01.000 --> 00:00:02.500\n神爱世人。\n", encoding="utf-8")
        zh_srt.write_text("1\n00:00:01,000 --> 00:00:02,500\n神爱世人。\n", encoding="utf-8")
        manifest_payload = {
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
                {"localPath": "artifacts/sermon.zh.live-aligned.vtt", "gcsUri": str(zh_vtt)},
                {"localPath": "artifacts/sermon.zh.live-aligned.srt", "gcsUri": str(zh_srt)},
            ],
        }
        run_manifest.write_text(json.dumps(manifest_payload, ensure_ascii=False), encoding="utf-8")
        sunday_manifest.write_text(json.dumps(manifest_payload, ensure_ascii=False), encoding="utf-8")
        realtime.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "id": 1,
                            "sessionId": "rt_test",
                            "type": "session_started",
                            "model": "gpt-realtime-translate",
                            "targetLanguage": "zh",
                            "audioSourceKind": "ipad_mic",
                        }
                    ),
                    json.dumps(
                        {
                            "id": 2,
                            "sessionId": "rt_test",
                            "type": "input_transcript_delta",
                            "source": "openai_realtime_translation_ws",
                            "en": "God loved the world.",
                            "segmentId": "seg_1",
                        },
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        {
                            "id": 3,
                            "sessionId": "rt_test",
                            "type": "caption_delta",
                            "source": "openai_realtime_translation_ws",
                            "zh": "神爱世人。",
                            "segmentId": "seg_1",
                        },
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        {
                            "id": 4,
                            "sessionId": "rt_test",
                            "type": "caption_final",
                            "source": "gpt-5.4-mini-stable-correction",
                            "model": "gpt-5.4-mini",
                            "zh": "神爱世人。",
                            "en": "God loved the world.",
                            "final": True,
                            "segmentId": "seg_1",
                        },
                        ensure_ascii=False,
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        return {
            "report": report,
            "playback": playback,
            "zh_vtt": zh_vtt,
            "zh_srt": zh_srt,
            "run_manifest": run_manifest,
            "sunday_manifest": sunday_manifest,
            "realtime": realtime,
        }

    def args_for(self, paths: dict[str, Path], **overrides):
        values = {
            "offline_report": str(paths["report"]),
            "playback_js": str(paths["playback"]),
            "zh_vtt": str(paths["zh_vtt"]),
            "zh_srt": str(paths["zh_srt"]),
            "run_manifest": str(paths["run_manifest"]),
            "sunday_manifest": str(paths["sunday_manifest"]),
            "sunday": "2026-06-28",
            "expected_source_mode": "youtube-live-archive",
            "require_readable_sunday_artifacts": True,
            "realtime_events_jsonl": str(paths["realtime"]),
            "allow_missing_realtime": False,
            "allow_missing_stable_correction": False,
            "out": None,
        }
        values.update(overrides)
        return type("Args", (), values)()

    def test_validates_all_readiness_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = self.write_fixture_set(Path(tmp))
            report = mod.validate_production_readiness(self.args_for(paths))

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["failedChecks"], [])
        self.assertEqual(report["offline"]["offlineSourceKind"], "live_archive")
        self.assertEqual(report["offline"]["offlineRoute"]["decision"], "use_caption_track")
        self.assertEqual(report["realtime"]["counts"]["stableCorrectionEvents"], 1)

    def test_missing_realtime_fails_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = self.write_fixture_set(Path(tmp))
            report = mod.validate_production_readiness(self.args_for(paths, realtime_events_jsonl=None))

        self.assertEqual(report["status"], "failed")
        self.assertIn("realtime_session", report["failedChecks"])

    def test_missing_realtime_can_be_warning_for_offline_only_smoke(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = self.write_fixture_set(Path(tmp))
            report = mod.validate_production_readiness(
                self.args_for(paths, realtime_events_jsonl=None, allow_missing_realtime=True)
            )

        self.assertEqual(report["status"], "ok")
        self.assertIn("realtime_session", report["warnings"])

    def test_main_writes_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self.write_fixture_set(root)
            out = root / "readiness.json"
            argv = [
                "validate_production_readiness.py",
                "--offline-report",
                str(paths["report"]),
                "--playback-js",
                str(paths["playback"]),
                "--zh-vtt",
                str(paths["zh_vtt"]),
                "--zh-srt",
                str(paths["zh_srt"]),
                "--run-manifest",
                str(paths["run_manifest"]),
                "--sunday-manifest",
                str(paths["sunday_manifest"]),
                "--sunday",
                "2026-06-28",
                "--require-readable-sunday-artifacts",
                "--realtime-events-jsonl",
                str(paths["realtime"]),
                "--out",
                str(out),
            ]
            original_argv = mod.sys.argv
            original_stdout = mod.sys.stdout
            stdout = io.StringIO()
            try:
                mod.sys.argv = argv
                mod.sys.stdout = stdout
                exit_code = mod.main()
            finally:
                mod.sys.argv = original_argv
                mod.sys.stdout = original_stdout

            self.assertEqual(exit_code, 0)
            written = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(written["status"], "ok")
            self.assertEqual(written["offline"]["offlineRoute"]["strategy"], "captions_first_then_asr")
            self.assertIn('"status": "ok"', stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
