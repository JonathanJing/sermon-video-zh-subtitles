import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "validate_offline_chain.py"
SPEC = importlib.util.spec_from_file_location("validate_offline_chain", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def write_playback(path: Path, *, source_kind: str = "live_archive", model: str = "gpt-5.4-mini", placeholder: bool = False) -> None:
    zh = "神爱世人。" if not placeholder else "AI 中文待生成：God loved the world."
    payload = {
        "schemaVersion": 1,
        "generatedFrom": "openai-translation-e2e",
        "translationStatus": "ready",
        "offlineSourceKind": source_kind,
        "offlineRoute": offline_route_for(source_kind),
        "translationProvider": {
            "provider": "openai",
            "model": model,
            "apiKeyMaterialIncluded": False,
            "secretResourceNamesIncluded": False,
        },
        "segments": [
            {
                "id": "sim_0001",
                "startMs": 1000,
                "endMs": 2500,
                "en": "God loved the world.",
                "zh": zh,
                "translationStatus": "ready",
            }
        ],
    }
    path.write_text(
        "window.SERMON_PLAYBACK_SIMULATION = " + json.dumps(payload, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )


def offline_route_for(source_kind: str = "live_archive") -> dict:
    if source_kind == "openai_asr":
        return {
            "strategy": "captions_first_then_asr",
            "decision": "use_asr_fallback",
            "selectedSourceKind": "openai_asr",
            "asrFallbackRequired": True,
            "audioExtractionAttempted": True,
            "fallbackReason": "no_requested_caption_track",
        }
    return {
        "strategy": "captions_first_then_asr",
        "decision": "use_caption_track",
        "selectedSourceKind": source_kind,
        "asrFallbackRequired": False,
        "audioExtractionAttempted": False,
        "fallbackReason": None,
    }


class ValidateOfflineChainTest(unittest.TestCase):
    def ready_report(self, *, source_kind: str = "live_archive") -> dict:
        output = {
            "lang": "en",
            "cue_count": 1,
            "local_vtt": "artifacts/live.sermon.en.local.vtt",
            "live_aligned_vtt": "artifacts/live.sermon.en.live-aligned.vtt",
            "local_srt": "artifacts/live.sermon.en.local.srt",
            "live_aligned_srt": "artifacts/live.sermon.en.live-aligned.srt",
        }
        if source_kind == "openai_asr":
            output["source_kind"] = "openai_asr"
            output["source_file"] = "raw/live.sermon-audio.m4a"
        else:
            output["source_file"] = "raw/live.en.vtt"
        if source_kind == "openai_asr":
            route = {
                "strategy": "captions_first_then_asr",
                "requestedLangs": ["en-orig", "en"],
                "liveCaptionLangs": [],
                "sermonVodCaptionLangs": [],
                "selectedSourceKind": "openai_asr",
                "decision": "use_asr_fallback",
                "asrFallbackRequired": True,
                "audioExtractionAttempted": True,
                "fallbackReason": "no_requested_caption_track",
                "status": "asr_completed",
            }
        else:
            route = {
                "strategy": "captions_first_then_asr",
                "requestedLangs": ["en-orig", "en"],
                "liveCaptionLangs": ["en"],
                "sermonVodCaptionLangs": [],
                "selectedSourceKind": source_kind,
                "decision": "use_caption_track",
                "asrFallbackRequired": False,
                "audioExtractionAttempted": False,
                "fallbackReason": None,
                "status": "caption_track_selected",
            }
        return {
            "schemaVersion": 1,
            "status": "ok",
            "caption_source": {"kind": source_kind},
            "offline_route": route,
            "asr": {"provider": "openai", "model": "gpt-4o-transcribe"},
            "outputs": [output],
            "apiKeyMaterialIncluded": False,
            "secretResourceNamesIncluded": False,
        }

    def ready_manifest(self, *, source_kind: str = "live_archive") -> dict:
        return {
            "schemaVersion": 1,
            "apiKeyMaterialIncluded": False,
            "secretResourceNamesIncluded": False,
            "offlineSourceKind": source_kind,
            "offlineRoute": offline_route_for(source_kind),
            "models": {
                "realtimeDraft": "gpt-realtime-translate",
                "offlineAsr": "gpt-4o-transcribe",
                "offlineTranslation": "gpt-5.4-mini",
                "stableCorrection": "gpt-5.4-mini",
            },
            "outputs": [
                {"localPath": "web/playback-simulation.generated.js", "gcsUri": ""},
                {"localPath": "artifacts/sermon.zh.live-aligned.vtt", "gcsUri": ""},
                {"localPath": "artifacts/sermon.zh.live-aligned.srt", "gcsUri": ""},
            ],
        }

    def report_for(self, root: Path, *, source_kind: str = "live_archive", model: str = "gpt-5.4-mini", placeholder: bool = False, report_overrides=None):
        report = self.ready_report(source_kind=source_kind)
        if report_overrides:
            report.update(report_overrides)
        playback = root / "playback.js"
        write_playback(playback, source_kind=source_kind, model=model, placeholder=placeholder)
        vtt_text = "WEBVTT\n\n00:00:01.000 --> 00:00:02.500\n神爱世人。\n"
        srt_text = "1\n00:00:01,000 --> 00:00:02,500\n神爱世人。\n"
        return mod.validate_offline_chain(
            report=report,
            report_text=json.dumps(report, ensure_ascii=False),
            report_uri=str(root / "report.json"),
            playback=mod.parse_playback_js(playback.read_text(encoding="utf-8")),
            playback_text=playback.read_text(encoding="utf-8"),
            playback_uri=str(playback),
            zh_vtt_text=vtt_text,
            zh_vtt_uri=str(root / "sermon.zh.live-aligned.vtt"),
            zh_srt_text=srt_text,
            zh_srt_uri=str(root / "sermon.zh.live-aligned.srt"),
            manifest=self.ready_manifest(source_kind=source_kind),
            manifest_text=json.dumps(self.ready_manifest(source_kind=source_kind), ensure_ascii=False),
            manifest_uri=str(root / "cloud-manifest.json"),
        )

    def test_validates_caption_priority_offline_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = self.report_for(Path(tmp), source_kind="live_archive")

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["offlineSourceKind"], "live_archive")
        self.assertEqual(report["offlineRoute"]["decision"], "use_caption_track")
        self.assertFalse(report["asr"]["used"])
        self.assertEqual(report["translation"]["model"], "gpt-5.4-mini")

    def test_validates_asr_fallback_offline_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = self.report_for(Path(tmp), source_kind="openai_asr")

        self.assertEqual(report["status"], "ok")
        self.assertTrue(report["asr"]["used"])
        self.assertTrue(report["offlineRoute"]["audioExtractionAttempted"])
        self.assertEqual(report["asr"]["model"], "gpt-4o-transcribe")

    def test_fails_caption_route_that_attempted_audio_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = self.ready_report(source_kind="live_archive")
            report["offline_route"]["audioExtractionAttempted"] = True
            validation = self.report_for(Path(tmp), source_kind="live_archive", report_overrides=report)

        self.assertEqual(validation["status"], "failed")
        self.assertIn("caption_route_did_not_extract_audio", validation["failedChecks"])

    def test_fails_caption_route_with_asr_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = self.ready_report(source_kind="live_archive")
            report["outputs"].append(
                {
                    "source_kind": "openai_asr",
                    "source_file": "raw/live.sermon-audio.m4a",
                    "live_aligned_vtt": "artifacts/live.sermon.en.live-aligned.vtt",
                }
            )
            validation = self.report_for(Path(tmp), source_kind="live_archive", report_overrides=report)

        self.assertEqual(validation["status"], "failed")
        self.assertIn("caption_route_no_asr_outputs", validation["failedChecks"])

    def test_fails_wrong_translation_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = self.report_for(Path(tmp), model="gpt-realtime-translate")

        self.assertEqual(report["status"], "failed")
        self.assertIn("offline_translation_model", report["failedChecks"])
        self.assertIn("not_realtime_chain", report["failedChecks"])

    def test_fails_placeholder_chinese_playback(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = self.report_for(Path(tmp), placeholder=True)

        self.assertEqual(report["status"], "failed")
        self.assertIn("playback_translated_segments", report["failedChecks"])

    def test_fails_when_chinese_captions_are_not_aligned_to_playback_segments(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = self.ready_report()
            playback = root / "playback.js"
            write_playback(playback)

            validation = mod.validate_offline_chain(
                report=report,
                report_text=json.dumps(report),
                report_uri=str(root / "report.json"),
                playback=mod.parse_playback_js(playback.read_text(encoding="utf-8")),
                playback_text=playback.read_text(encoding="utf-8"),
                playback_uri=str(playback),
                zh_vtt_text="WEBVTT\n\n00:00:02.000 --> 00:00:03.500\n神爱世人。\n",
                zh_vtt_uri=str(root / "sermon.zh.live-aligned.vtt"),
                zh_srt_text="1\n00:00:02,000 --> 00:00:03,500\n神爱世人。\n",
                zh_srt_uri=str(root / "sermon.zh.live-aligned.srt"),
                manifest=self.ready_manifest(),
                manifest_text=json.dumps(self.ready_manifest()),
                manifest_uri=str(root / "cloud-manifest.json"),
            )

        self.assertEqual(validation["status"], "failed")
        self.assertIn("zh_vtt_timeline_alignment", validation["failedChecks"])
        self.assertIn("zh_srt_timeline_alignment", validation["failedChecks"])

    def test_fails_asr_fallback_with_wrong_asr_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = self.ready_report(source_kind="openai_asr")
            report["asr"]["model"] = "gpt-4o-mini-transcribe"
            validation = self.report_for(Path(tmp), source_kind="openai_asr", report_overrides=report)

        self.assertEqual(validation["status"], "failed")
        self.assertIn("asr_model", validation["failedChecks"])

    def test_fails_asr_fallback_when_requested_caption_track_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = self.ready_report(source_kind="openai_asr")
            report["offline_route"]["liveCaptionLangs"] = ["en"]
            validation = self.report_for(Path(tmp), source_kind="openai_asr", report_overrides=report)

        self.assertEqual(validation["status"], "failed")
        self.assertIn("asr_no_requested_caption_tracks", validation["failedChecks"])

    def test_fails_asr_fallback_without_audio_source_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = self.ready_report(source_kind="openai_asr")
            report["outputs"][0]["source_file"] = "raw/live.en.vtt"
            validation = self.report_for(Path(tmp), source_kind="openai_asr", report_overrides=report)

        self.assertEqual(validation["status"], "failed")
        self.assertIn("asr_audio_source_artifact", validation["failedChecks"])

    def test_fails_manifest_without_chinese_srt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = self.ready_report()
            playback = root / "playback.js"
            write_playback(playback)
            manifest = self.ready_manifest()
            manifest["outputs"] = [item for item in manifest["outputs"] if not item["localPath"].endswith(".srt")]

            validation = mod.validate_offline_chain(
                report=report,
                report_text=json.dumps(report),
                report_uri=str(root / "report.json"),
                playback=mod.parse_playback_js(playback.read_text(encoding="utf-8")),
                playback_text=playback.read_text(encoding="utf-8"),
                playback_uri=str(playback),
                zh_vtt_text="WEBVTT\n\n00:00:01.000 --> 00:00:02.500\n神爱世人。\n",
                zh_vtt_uri=str(root / "sermon.zh.live-aligned.vtt"),
                zh_srt_text="1\n00:00:01,000 --> 00:00:02,500\n神爱世人。\n",
                zh_srt_uri=str(root / "sermon.zh.live-aligned.srt"),
                manifest=manifest,
                manifest_text=json.dumps(manifest),
                manifest_uri=str(root / "cloud-manifest.json"),
            )

        self.assertEqual(validation["status"], "failed")
        self.assertIn("manifest_zh_srt", validation["failedChecks"])

    def test_fails_when_manifest_offline_route_does_not_match_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = self.ready_report(source_kind="live_archive")
            playback = root / "playback.js"
            write_playback(playback, source_kind="live_archive")
            manifest = self.ready_manifest(source_kind="openai_asr")

            validation = mod.validate_offline_chain(
                report=report,
                report_text=json.dumps(report),
                report_uri=str(root / "report.json"),
                playback=mod.parse_playback_js(playback.read_text(encoding="utf-8")),
                playback_text=playback.read_text(encoding="utf-8"),
                playback_uri=str(playback),
                zh_vtt_text="WEBVTT\n\n00:00:01.000 --> 00:00:02.500\n神爱世人。\n",
                zh_vtt_uri=str(root / "sermon.zh.live-aligned.vtt"),
                zh_srt_text="1\n00:00:01,000 --> 00:00:02,500\n神爱世人。\n",
                zh_srt_uri=str(root / "sermon.zh.live-aligned.srt"),
                manifest=manifest,
                manifest_text=json.dumps(manifest),
                manifest_uri=str(root / "cloud-manifest.json"),
            )

        self.assertEqual(validation["status"], "failed")
        self.assertIn("manifest_offline_source_kind", validation["failedChecks"])
        self.assertIn("manifest_offline_route_decision", validation["failedChecks"])
        self.assertIn("manifest_offline_route_asr_policy", validation["failedChecks"])

    def test_fails_when_manifest_offline_translation_uses_realtime_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = self.ready_report()
            playback = root / "playback.js"
            write_playback(playback)
            manifest = self.ready_manifest()
            manifest["models"] = {
                "realtimeDraft": "gpt-realtime-translate",
                "offlineTranslation": "gpt-realtime-translate",
            }

            validation = mod.validate_offline_chain(
                report=report,
                report_text=json.dumps(report),
                report_uri=str(root / "report.json"),
                playback=mod.parse_playback_js(playback.read_text(encoding="utf-8")),
                playback_text=playback.read_text(encoding="utf-8"),
                playback_uri=str(playback),
                zh_vtt_text="WEBVTT\n\n00:00:01.000 --> 00:00:02.500\n神爱世人。\n",
                zh_vtt_uri=str(root / "sermon.zh.live-aligned.vtt"),
                zh_srt_text="1\n00:00:01,000 --> 00:00:02,500\n神爱世人。\n",
                zh_srt_uri=str(root / "sermon.zh.live-aligned.srt"),
                manifest=manifest,
                manifest_text=json.dumps(manifest),
                manifest_uri=str(root / "cloud-manifest.json"),
            )

        self.assertEqual(validation["status"], "failed")
        self.assertIn("manifest_offline_translation_model", validation["failedChecks"])

    def test_fails_when_manifest_models_are_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = self.ready_report()
            playback = root / "playback.js"
            write_playback(playback)
            manifest = self.ready_manifest()
            manifest.pop("models")

            validation = mod.validate_offline_chain(
                report=report,
                report_text=json.dumps(report),
                report_uri=str(root / "report.json"),
                playback=mod.parse_playback_js(playback.read_text(encoding="utf-8")),
                playback_text=playback.read_text(encoding="utf-8"),
                playback_uri=str(playback),
                zh_vtt_text="WEBVTT\n\n00:00:01.000 --> 00:00:02.500\n神爱世人。\n",
                zh_vtt_uri=str(root / "sermon.zh.live-aligned.vtt"),
                zh_srt_text="1\n00:00:01,000 --> 00:00:02,500\n神爱世人。\n",
                zh_srt_uri=str(root / "sermon.zh.live-aligned.srt"),
                manifest=manifest,
                manifest_text=json.dumps(manifest),
                manifest_uri=str(root / "cloud-manifest.json"),
            )

        self.assertEqual(validation["status"], "failed")
        self.assertIn("manifest_models_present", validation["failedChecks"])
        self.assertIn("manifest_realtime_draft_model", validation["failedChecks"])
        self.assertIn("manifest_offline_asr_model", validation["failedChecks"])
        self.assertIn("manifest_offline_translation_model", validation["failedChecks"])
        self.assertIn("manifest_stable_correction_model", validation["failedChecks"])

    def test_fails_when_manifest_offline_asr_or_stable_models_are_wrong(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = self.ready_report()
            playback = root / "playback.js"
            write_playback(playback)
            manifest = self.ready_manifest()
            manifest["models"]["offlineAsr"] = "gpt-realtime-translate"
            manifest["models"]["stableCorrection"] = "gpt-realtime-translate"

            validation = mod.validate_offline_chain(
                report=report,
                report_text=json.dumps(report),
                report_uri=str(root / "report.json"),
                playback=mod.parse_playback_js(playback.read_text(encoding="utf-8")),
                playback_text=playback.read_text(encoding="utf-8"),
                playback_uri=str(playback),
                zh_vtt_text="WEBVTT\n\n00:00:01.000 --> 00:00:02.500\n神爱世人。\n",
                zh_vtt_uri=str(root / "sermon.zh.live-aligned.vtt"),
                zh_srt_text="1\n00:00:01,000 --> 00:00:02,500\n神爱世人。\n",
                zh_srt_uri=str(root / "sermon.zh.live-aligned.srt"),
                manifest=manifest,
                manifest_text=json.dumps(manifest),
                manifest_uri=str(root / "cloud-manifest.json"),
            )

        self.assertEqual(validation["status"], "failed")
        self.assertIn("manifest_offline_asr_model", validation["failedChecks"])
        self.assertIn("manifest_stable_correction_model", validation["failedChecks"])

    def test_main_writes_report_and_returns_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "report.json"
            playback_path = root / "playback.js"
            vtt_path = root / "sermon.zh.live-aligned.vtt"
            srt_path = root / "sermon.zh.live-aligned.srt"
            out_path = root / "validation.json"
            report_path.write_text(json.dumps(self.ready_report()), encoding="utf-8")
            write_playback(playback_path)
            vtt_path.write_text("WEBVTT\n\n00:00:01.000 --> 00:00:02.500\n神爱世人。\n", encoding="utf-8")
            srt_path.write_text("1\n00:00:01,000 --> 00:00:02,500\n神爱世人。\n", encoding="utf-8")
            argv = [
                "validate_offline_chain.py",
                "--report",
                str(report_path),
                "--playback-js",
                str(playback_path),
                "--zh-vtt",
                str(vtt_path),
                "--zh-srt",
                str(srt_path),
                "--out",
                str(out_path),
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
            self.assertEqual(json.loads(out_path.read_text(encoding="utf-8"))["status"], "ok")
            self.assertIn('"status": "ok"', stdout.getvalue())

    def test_main_writes_structured_failure_when_outputs_are_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "report.json"
            playback_path = root / "playback.js"
            missing_vtt = root / "missing.zh.vtt"
            missing_srt = root / "missing.zh.srt"
            out_path = root / "validation.json"
            report_path.write_text(json.dumps(self.ready_report()), encoding="utf-8")
            write_playback(playback_path)
            argv = [
                "validate_offline_chain.py",
                "--report",
                str(report_path),
                "--playback-js",
                str(playback_path),
                "--zh-vtt",
                str(missing_vtt),
                "--zh-srt",
                str(missing_srt),
                "--out",
                str(out_path),
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

            self.assertEqual(exit_code, 2)
            written = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(written["status"], "failed")
            self.assertIn("input_readable_zh_vtt", written["failedChecks"])
            self.assertIn("input_readable_zh_srt", written["failedChecks"])
            self.assertFalse(written["apiKeyMaterialIncluded"])
            self.assertIn('"status": "failed"', stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
