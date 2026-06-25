import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_no_caption_archive_asr_route.py"
SPEC = importlib.util.spec_from_file_location("run_no_caption_archive_asr_route", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class RunNoCaptionArchiveAsrRouteTest(unittest.TestCase):
    def test_route_runs_all_steps_with_safe_report(self):
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            if "scripts/validate_offline_chain.py" in command:
                write_json_arg(
                    command,
                    {
                        "status": "ok",
                        "failedChecks": [],
                        "sourceEvidence": "real_no_caption_archive",
                        "offlineRoute": {
                            "decision": "use_asr_fallback",
                            "selectedSourceKind": "openai_asr",
                        },
                        "asr": {"used": True, "model": "gpt-4o-transcribe"},
                        "translation": {"model": "gpt-5.4-mini"},
                        "checks": [
                            {"name": "not_realtime_chain", "state": "pass"},
                            {"name": "zh_vtt_timeline_alignment", "state": "pass"},
                            {"name": "zh_srt_timeline_alignment", "state": "pass"},
                        ],
                    },
                )
            if "scripts/validate_production_readiness.py" in command:
                write_json_arg(
                    command,
                    {
                        "status": "ok",
                        "failedChecks": [],
                        "warnings": ["realtime_session"],
                        "offline": {
                            "status": "ok",
                            "offlineRoute": {"decision": "use_asr_fallback"},
                        },
                        "sundayManifest": {"status": "ok"},
                        "apiKeyMaterialIncluded": False,
                        "secretResourceNamesIncluded": False,
                    },
                )
            return completed(0, stdout="ok", stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            args = args_for(Path(tmp))
            original_route_paths = mod.route_paths

            def temp_route_paths(route_args):
                paths = original_route_paths(route_args)
                paths["offlineChainValidation"] = route_args.run_root / "no-caption-offline-chain-validation.json"
                paths["routeReadiness"] = route_args.run_root / "asr-route-readiness.json"
                return paths

            with patch.object(mod, "route_paths", side_effect=temp_route_paths), patch.object(
                mod.subprocess, "run", side_effect=fake_run
            ):
                report = mod.run_route(args)

        rendered = json.dumps(report)
        self.assertEqual(report["status"], "ok")
        self.assertEqual(
            [step["name"] for step in report["steps"]],
            [
                "run_offline_archive_preflight",
                "prepare_live_link_playback",
                "translate_playback_with_openai",
                "export_playback_captions",
                "validate_offline_chain",
                "validate_production_readiness",
            ],
        )
        self.assertIn("--allow-missing-realtime", calls[-1])
        self.assertIn("--run-manifest", calls[-1])
        self.assertIn("--sunday-manifest", calls[-1])
        self.assertIn("--gcs-dry-run", calls[1])
        self.assertIn("--gcs-dry-run", calls[3])
        self.assertIn("--no-discover", calls[0])
        self.assertIn("--no-discover", calls[1])
        self.assertIn("--sermon-start", calls[0])
        self.assertIn("--sermon-start", calls[1])
        self.assertIn("00:23:25", calls[0])
        self.assertIn("projects/p/secrets/openai-api-key/versions/latest", calls[1])
        self.assertNotIn("projects/p/secrets", rendered)
        self.assertNotIn("openai-api-key", rendered)
        self.assertFalse(report["apiKeyMaterialIncluded"])
        self.assertFalse(report["secretResourceNamesIncluded"])
        self.assertEqual(report["validation"]["offlineChain"]["sourceEvidence"], "real_no_caption_archive")
        self.assertEqual(report["validation"]["offlineChain"]["notRealtimeChain"], "pass")
        self.assertEqual(report["validation"]["offlineChain"]["asr"]["model"], "gpt-4o-transcribe")
        self.assertEqual(report["validation"]["offlineChain"]["translation"]["model"], "gpt-5.4-mini")
        self.assertEqual(report["validation"]["routeReadiness"]["status"], "ok")

    def test_optional_readiness_failure_does_not_fail_completed_asr_route(self):
        def fake_run(command, **kwargs):
            if "scripts/validate_offline_chain.py" in command:
                write_json_arg(
                    command,
                    {
                        "status": "ok",
                        "failedChecks": [],
                        "sourceEvidence": "unspecified",
                        "offlineSourceKind": "openai_asr",
                        "offlineRoute": {
                            "decision": "use_asr_fallback",
                            "selectedSourceKind": "openai_asr",
                        },
                        "asr": {"used": True, "model": "gpt-4o-transcribe"},
                        "translation": {"model": "gpt-5.4-mini"},
                        "checks": [
                            {"name": "asr_no_requested_caption_tracks", "state": "pass"},
                            {"name": "asr_audio_source_artifact", "state": "pass"},
                            {"name": "not_realtime_chain", "state": "pass"},
                            {"name": "zh_vtt_timeline_alignment", "state": "pass"},
                            {"name": "zh_srt_timeline_alignment", "state": "pass"},
                        ],
                    },
                )
            if "scripts/validate_production_readiness.py" in command:
                write_json_arg(command, {"status": "failed", "failedChecks": ["sunday_manifest"]})
                return completed(2, stdout="failed", stderr="")
            return completed(0, stdout="ok", stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            args = args_for(Path(tmp))
            original_route_paths = mod.route_paths

            def temp_route_paths(route_args):
                paths = original_route_paths(route_args)
                paths["offlineChainValidation"] = route_args.run_root / "no-caption-offline-chain-validation.json"
                paths["routeReadiness"] = route_args.run_root / "asr-route-readiness.json"
                return paths

            with patch.object(mod, "route_paths", side_effect=temp_route_paths), patch.object(
                mod.subprocess, "run", side_effect=fake_run
            ):
                report = mod.run_route(args)

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["optionalFailedSteps"], ["validate_production_readiness"])
        self.assertEqual(report["validation"]["offlineChain"]["sourceEvidence"], "real_no_caption_archive")
        self.assertIsNone(report["validation"]["routeReadiness"])

    def test_apply_gcs_removes_dry_run_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = args_for(Path(tmp), apply_gcs=True)
            commands = mod.route_commands(args, mod.route_paths(args))

        self.assertNotIn("--gcs-dry-run", commands[1])
        self.assertNotIn("--gcs-dry-run", commands[3])

    def test_stops_after_failed_step_and_sanitizes_tails(self):
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            if "scripts/prepare_live_link_playback.py" in command:
                return completed(
                    2,
                    stderr="bad sk-secret123 projects/p/secrets/openai-api-key/versions/latest",
                )
            return completed(0)

        with tempfile.TemporaryDirectory() as tmp:
            args = args_for(Path(tmp))
            with patch.object(mod.subprocess, "run", side_effect=fake_run):
                report = mod.run_route(args)

        rendered = json.dumps(report)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["failedSteps"], ["prepare_live_link_playback"])
        self.assertEqual(len(calls), 2)
        self.assertNotIn("sk-secret123", rendered)
        self.assertNotIn("openai-api-key", rendered)

    def test_rejects_realtime_model_for_offline_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = args_for(Path(tmp), asr_model="gpt-realtime-translate")
            with self.assertRaises(SystemExit):
                mod.validate_args(args)


def args_for(root: Path, **overrides):
    values = {
        "live_url": "https://youtube.test/watch?v=abc123&token=secret",
        "api_key_secret": "projects/p/secrets/openai-api-key/versions/latest",
        "sunday": "2026-06-28",
        "session_id": "no-caption-asr-route",
        "lang": ["en-orig", "en"],
        "sermon_start": "00:23:25",
        "asr_model": "gpt-4o-transcribe",
        "translation_model": "gpt-5.4-mini",
        "gcs_bucket": "sermon-zh-artifacts-ai-for-god",
        "gcs_prefix": "sundays/2026-06-28/runs/no-caption-asr-route",
        "apply_gcs": False,
        "run_root": root / "run",
        "out": root / "report.json",
    }
    values.update(overrides)
    return type("Args", (), values)()


def completed(returncode, stdout="{}", stderr=""):
    class Completed:
        pass

    item = Completed()
    item.returncode = returncode
    item.stdout = stdout
    item.stderr = stderr
    return item


def write_json_arg(command, data):
    out_index = command.index("--out") + 1
    out = Path(command[out_index])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
