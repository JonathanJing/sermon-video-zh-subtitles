import importlib.util
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "refresh_production_preflight_evidence.py"
SPEC = importlib.util.spec_from_file_location("refresh_production_preflight_evidence", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class RefreshProductionPreflightEvidenceTest(unittest.TestCase):
    def test_builds_read_only_refresh_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = args_for(evidence_dir=Path(tmp) / "evidence")
            paths = mod.evidence_paths(args.evidence_dir)
            commands = mod.build_commands(args, paths)

        self.assertIn("cloudRunConfig", commands)
        self.assertIn("cloudRunUpdatePlan", commands)
        self.assertIn("cloudRunUpdateDryRun", commands)
        self.assertIn("cloudRunApiPreflight", commands)
        self.assertIn("deployedWebrtcSession", commands)
        self.assertIn("requiredModelAccess", commands)
        self.assertIn("modelAccessRecoveryPlan", commands)
        self.assertIn("serverRealtimeContract", commands)
        self.assertIn("webRealtimeContract", commands)
        self.assertIn("stableCorrectionContract", commands)
        self.assertIn("live1130RunPlan", commands)
        self.assertIn("offlineWorkerPlan", commands)
        self.assertIn("publicCaptionViewRuntime", commands)
        self.assertIn("noCaptionAsrPlan", commands)
        self.assertIn("offlineAsrSampleChain", commands)
        self.assertIn("localSundayManifestEvidence", commands)
        self.assertIn("gcsManifestPublishPlan", commands)
        self.assertIn("productionMatrix", commands)
        self.assertIn("productionUnblockPlan", commands)
        self.assertIn("operatorApprovalBundle", commands)
        self.assertIn("--cloud-run-service", commands["requiredModelAccess"])
        self.assertIn("gpt-5.4-mini", commands["requiredModelAccess"])
        self.assertIn("--create-realtime-session", commands["cloudRunApiPreflight"])
        self.assertIn("--internal-task-token", commands["cloudRunApiPreflight"])
        self.assertIn("$INTERNAL_TASK_TOKEN", commands["cloudRunApiPreflight"])
        self.assertIn("run_deployed_webrtc_session_smoke.py", " ".join(commands["deployedWebrtcSession"]))
        self.assertIn("--internal-task-token", commands["deployedWebrtcSession"])
        self.assertIn("$INTERNAL_TASK_TOKEN", commands["deployedWebrtcSession"])
        self.assertIn(str(paths["deployedWebrtcSession"]), commands["deployedWebrtcSession"])
        self.assertIn("write_model_access_recovery_plan.py", " ".join(commands["modelAccessRecoveryPlan"]))
        self.assertIn(str(paths["requiredModelAccess"]), commands["modelAccessRecoveryPlan"])
        self.assertIn(str(paths["alternativeModelAccess"]), commands["modelAccessRecoveryPlan"])
        self.assertIn("validate_server_realtime_contract.py", " ".join(commands["serverRealtimeContract"]))
        self.assertIn("validate_web_realtime_contract.py", " ".join(commands["webRealtimeContract"]))
        self.assertIn("--deployed-webrtc-session-report", commands["productionMatrix"])
        self.assertIn(str(paths["deployedWebrtcSession"]), commands["productionMatrix"])
        self.assertIn("validate_stable_correction_contract.py", " ".join(commands["stableCorrectionContract"]))
        self.assertIn("write_1130_live_realtime_run_plan.py", " ".join(commands["live1130RunPlan"]))
        self.assertIn("write_worker_caption_first_plan.py", " ".join(commands["offlineWorkerPlan"]))
        self.assertIn("validate_public_caption_view_runtime.py", " ".join(commands["publicCaptionViewRuntime"]))
        self.assertIn("--public-caption-view-runtime-report", commands["productionMatrix"])
        self.assertIn("--realtime-handoff-validation-report", commands["productionMatrix"])
        self.assertIn("realtime-public-sse-smoke.json", str(paths["realtimePublicSse"]))
        self.assertNotIn(".local.json", str(paths["realtimePublicSse"]))
        self.assertIn("write_no_caption_asr_fallback_plan.py", " ".join(commands["noCaptionAsrPlan"]))
        self.assertIn("build_no_caption_asr_sample_chain.py", " ".join(commands["offlineAsrSampleChain"]))
        self.assertIn(str(paths["offlineAsrSmoke"]), commands["offlineAsrSampleChain"])
        self.assertIn(str(paths["offlineAsrSampleChainValidation"]), commands["offlineAsrSampleChain"])
        self.assertIn("--no-caption-asr-plan-report", commands["productionMatrix"])
        self.assertIn(str(paths["noCaptionAsrPlan"]), commands["productionMatrix"])
        self.assertIn("--offline-asr-chain-validation-report", commands["productionMatrix"])
        self.assertIn(str(paths["offlineAsrChainValidation"]), commands["productionMatrix"])
        self.assertIn("--offline-asr-route-run-report", commands["productionMatrix"])
        self.assertIn(str(paths["offlineAsrRouteRun"]), commands["productionMatrix"])
        self.assertIn("--offline-asr-sample-chain-validation-report", commands["productionMatrix"])
        self.assertIn(str(paths["offlineAsrSampleChainValidation"]), commands["productionMatrix"])
        self.assertIn("build_local_sunday_manifest_evidence.py", " ".join(commands["localSundayManifestEvidence"]))
        self.assertIn("--offline-chain-validation-out", commands["localSundayManifestEvidence"])
        self.assertIn("plan_gcs_sunday_manifest_publish.py", " ".join(commands["gcsManifestPublishPlan"]))
        self.assertIn("--sunday", commands["gcsManifestPublishPlan"])
        self.assertIn("--offline-worker-plan-report", commands["productionMatrix"])
        self.assertIn("--gcs-manifest-publish-plan", commands["productionMatrix"])
        self.assertIn("--openai-alternative-model-access-preflight-report", commands["productionMatrix"])
        self.assertIn("write_production_unblock_plan.py", " ".join(commands["productionUnblockPlan"]))
        self.assertIn("--cloud-run-update-plan", commands["productionUnblockPlan"])
        self.assertIn(str(paths["cloudRunUpdatePlan"]), commands["productionUnblockPlan"])
        self.assertIn("write_operator_approval_bundle.py", " ".join(commands["operatorApprovalBundle"]))
        self.assertIn(str(paths["productionUnblockPlan"]), commands["operatorApprovalBundle"])
        self.assertIn(str(paths["live1130RunPlan"]), commands["operatorApprovalBundle"])
        self.assertIn("write_production_go_live_sequence.py", " ".join(commands["productionGoLiveSequence"]))
        self.assertIn(str(paths["operatorApprovalBundle"]), commands["productionGoLiveSequence"])
        self.assertIn(str(paths["modelAccessRecoveryPlan"]), commands["productionGoLiveSequence"])
        self.assertIn(str(paths["noCaptionAsrPlan"]), commands["productionGoLiveSequence"])
        self.assertIn(str(paths["live1130RunPlan"]), commands["productionGoLiveSequence"])
        self.assertIn("validate_realtime_handoff.py", " ".join(commands["realtimeHandoffValidation"]))
        self.assertIn(str(paths["live1130RunPlan"]), commands["realtimeHandoffValidation"])
        self.assertIn(str(paths["operatorApprovalBundle"]), commands["realtimeHandoffValidation"])
        self.assertIn(str(paths["productionGoLiveSequence"]), commands["realtimeHandoffValidation"])
        self.assertIn("--cloud-run-config-report", commands["goalAudit"])
        self.assertIn("--cloud-run-api-preflight-report", commands["goalAudit"])
        self.assertIn("--evidence-matrix-report", commands["goalAudit"])
        self.assertIn("--openai-model-access-preflight-report", commands["goalAudit"])
        self.assertIn(str(paths["requiredModelAccess"]), commands["goalAudit"])
        self.assertNotIn("services update", " ".join(" ".join(command) for command in commands.values()))

    def test_report_declares_realtime_session_metadata_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = args_for(evidence_dir=Path(tmp) / "evidence", dry_run=True)
            report = mod.refresh_evidence(args)

        self.assertEqual(report["expectedRealtimeSession"]["model"], "gpt-realtime-translate")
        self.assertEqual(report["expectedRealtimeSession"]["targetLanguage"], "zh")
        self.assertEqual(report["expectedRealtimeSession"]["audioSourceKind"], "ipad_mic")
        self.assertIn(
            "realtime_local_session_metadata",
            report["expectedValidationChecks"]["cloudRunApiPreflight"],
        )

    def test_refresh_continues_after_failed_model_access(self):
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            joined = " ".join(command)
            return completed(
                2 if "run_openai_model_access_preflight.py" in joined and "gpt-5.4-mini" in command else 0
            )

        with tempfile.TemporaryDirectory() as tmp:
            args = args_for(evidence_dir=Path(tmp) / "evidence", out=Path(tmp) / "refresh.json")
            with patch.dict(mod.os.environ, {"INTERNAL_TASK_TOKEN": "test-runtime-token"}), patch.object(
                mod.subprocess, "run", side_effect=fake_run
            ):
                report = mod.refresh_evidence(args)
            mod.write_report(args.out, report)
            written = json.loads(args.out.read_text())

        self.assertEqual(report["status"], "incomplete")
        self.assertIn("requiredModelAccess", report["failedSteps"])
        self.assertEqual(report["incompleteSteps"], [])
        self.assertEqual(len(calls), 26)
        self.assertIn("prepare_cloud_run_realtime_update_plan.py", " ".join(calls[1]))
        self.assertIn("apply_cloud_run_realtime_update_plan.py", " ".join(calls[2]))
        self.assertIn("run_deployed_webrtc_session_smoke.py", " ".join(calls[4]))
        self.assertIn("write_model_access_recovery_plan.py", " ".join(calls[7]))
        self.assertIn("validate_server_realtime_contract.py", " ".join(calls[8]))
        self.assertIn("validate_web_realtime_contract.py", " ".join(calls[9]))
        self.assertIn("validate_stable_correction_contract.py", " ".join(calls[10]))
        self.assertIn("write_1130_live_realtime_run_plan.py", " ".join(calls[11]))
        self.assertTrue(any("validate_public_caption_view_runtime.py" in " ".join(call) for call in calls))
        self.assertTrue(any("write_no_caption_asr_fallback_plan.py" in " ".join(call) for call in calls))
        self.assertTrue(any("build_no_caption_asr_sample_chain.py" in " ".join(call) for call in calls))
        self.assertTrue(any("build_local_sunday_manifest_evidence.py" in " ".join(call) for call in calls))
        self.assertTrue(any("plan_gcs_sunday_manifest_publish.py" in " ".join(call) for call in calls))
        self.assertIn("collect_production_evidence_matrix.py", " ".join(calls[-8]))
        self.assertIn("write_production_unblock_plan.py", " ".join(calls[-7]))
        self.assertIn("write_operator_approval_bundle.py", " ".join(calls[-6]))
        self.assertIn("audit_production_goal_readiness.py", " ".join(calls[-5]))
        self.assertIn("write_production_go_live_sequence.py", " ".join(calls[-4]))
        self.assertIn("validate_realtime_handoff.py", " ".join(calls[-3]))
        self.assertIn("collect_production_evidence_matrix.py", " ".join(calls[-2]))
        self.assertIn("audit_production_goal_readiness.py", " ".join(calls[-1]))
        self.assertFalse(written["apiKeyMaterialIncluded"])
        self.assertFalse(written["secretResourceNamesIncluded"])
        self.assertFalse(written["eventTokenIncluded"])
        self.assertEqual(written["mode"], "full")
        self.assertEqual(written["skippedSteps"], [])

    def test_dry_run_plans_without_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = args_for(evidence_dir=Path(tmp) / "evidence", dry_run=True)
            with patch.object(mod.subprocess, "run") as run:
                report = mod.refresh_evidence(args)

        self.assertEqual(report["status"], "planned")
        self.assertEqual(report["steps"], {})
        self.assertEqual(report["failedSteps"], [])
        self.assertEqual(report["incompleteSteps"], [])
        run.assert_not_called()

    def test_local_only_skips_external_cloud_run_and_openai_checks(self):
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            joined = " ".join(command)
            self.assertNotIn("validate_cloud_run_realtime_config.py", joined)
            self.assertNotIn("run_cloud_run_realtime_preflight.py", joined)
            self.assertNotIn("run_deployed_webrtc_session_smoke.py", joined)
            self.assertNotIn("run_openai_model_access_preflight.py", joined)
            return completed(0)

        with tempfile.TemporaryDirectory() as tmp:
            args = args_for(evidence_dir=Path(tmp) / "evidence", out=Path(tmp) / "refresh.json", local_only=True)
            with patch.object(mod.subprocess, "run", side_effect=fake_run):
                report = mod.refresh_evidence(args)

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["mode"], "local_only")
        self.assertEqual(sorted(report["skippedSteps"]), sorted(mod.LOCAL_ONLY_SKIP_STEPS))
        self.assertTrue(any("validate_web_realtime_contract.py" in " ".join(call) for call in calls))
        self.assertTrue(any("validate_server_realtime_contract.py" in " ".join(call) for call in calls))
        self.assertTrue(any("validate_stable_correction_contract.py" in " ".join(call) for call in calls))
        self.assertTrue(any("write_1130_live_realtime_run_plan.py" in " ".join(call) for call in calls))
        self.assertTrue(any("validate_realtime_handoff.py" in " ".join(call) for call in calls))
        self.assertFalse(any("gcloud" in " ".join(call) for call in calls))

    def test_refresh_separates_expected_incomplete_reports_from_failed_steps(self):
        def fake_run(command, **kwargs):
            joined = " ".join(command)
            if "collect_production_evidence_matrix.py" in joined or "audit_production_goal_readiness.py" in joined:
                return completed(2, stdout='{"status":"incomplete"}')
            return completed(0)

        with tempfile.TemporaryDirectory() as tmp:
            args = args_for(evidence_dir=Path(tmp) / "evidence", out=Path(tmp) / "refresh.json")
            with patch.dict(mod.os.environ, {"INTERNAL_TASK_TOKEN": "test-runtime-token"}), patch.object(
                mod.subprocess, "run", side_effect=fake_run
            ):
                report = mod.refresh_evidence(args)

        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["failedSteps"], [])
        self.assertEqual(report["incompleteSteps"], ["productionMatrix", "goalAudit"])
        self.assertEqual(report["steps"]["productionMatrix"]["status"], "incomplete")
        self.assertEqual(report["steps"]["goalAudit"]["status"], "incomplete")

    def test_go_live_sequence_runs_after_current_refresh_report_is_written(self):
        observed = {}

        def fake_run(command, **kwargs):
            joined = " ".join(command)
            if "run_openai_model_access_preflight.py" in joined and "gpt-5.4-mini" in command:
                return completed(2)
            if "write_production_go_live_sequence.py" in joined:
                report_path = Path(command[command.index("--preflight-refresh") + 1])
                observed["reportExists"] = report_path.is_file()
                observed["report"] = json.loads(report_path.read_text(encoding="utf-8"))
            if "validate_realtime_handoff.py" in joined:
                observed["validationAfterGoLive"] = bool(observed.get("reportExists"))
            return completed(0)

        with tempfile.TemporaryDirectory() as tmp:
            args = args_for(evidence_dir=Path(tmp) / "evidence", out=Path(tmp) / "evidence" / "production-preflight-refresh.json")
            with patch.dict(mod.os.environ, {"INTERNAL_TASK_TOKEN": "test-runtime-token"}), patch.object(
                mod.subprocess, "run", side_effect=fake_run
            ):
                report = mod.refresh_evidence(args)

        self.assertTrue(observed["reportExists"])
        self.assertIn("requiredModelAccess", observed["report"]["failedSteps"])
        self.assertIn("productionGoLiveSequence", report["steps"])
        self.assertEqual(report["steps"]["productionGoLiveSequence"]["status"], "ok")
        self.assertTrue(observed["validationAfterGoLive"])
        self.assertIn("realtimeHandoffValidation", report["steps"])
        self.assertEqual(report["steps"]["realtimeHandoffValidation"]["status"], "ok")

    def test_refresh_redacts_step_output_tails(self):
        sensitive = (
            "sk-testsecret projects/p/secrets/openai-api-key/versions/latest "
            "operator-admin-token internal-task-token"
        )

        with tempfile.TemporaryDirectory() as tmp:
            args = args_for(evidence_dir=Path(tmp) / "evidence", out=Path(tmp) / "refresh.json")
            with patch.dict(mod.os.environ, {"INTERNAL_TASK_TOKEN": "test-runtime-token"}), patch.object(
                mod.subprocess, "run", return_value=completed(0, stdout=sensitive, stderr=sensitive)
            ):
                report = mod.refresh_evidence(args)

        rendered = json.dumps(report)
        self.assertNotIn("sk-testsecret", rendered)
        self.assertNotIn("projects/p/secrets/openai-api-key", rendered)
        self.assertNotIn("operator-admin-token", rendered)
        self.assertNotIn("INTERNAL_TASK_TOKEN=internal-task-token", rendered)
        self.assertIn("--internal-task-token", rendered)
        self.assertIn("sk-REDACTED", rendered)
        self.assertIn("<redacted-secret-name>", rendered)

    def test_refresh_redaction_preserves_token_option_names(self):
        text = (
            "python3 scripts/run_cloud_run_realtime_preflight.py "
            "--create-realtime-session --internal-task-token $INTERNAL_TASK_TOKEN "
            "--update-secrets OPERATOR_ADMIN_TOKEN=operator-admin-token:latest,"
            "INTERNAL_TASK_TOKEN=internal-task-token:latest"
        )

        redacted = mod.sanitize_tail(text)

        self.assertIn("--internal-task-token", redacted)
        self.assertNotIn("operator-admin-token:latest", redacted)
        self.assertNotIn("INTERNAL_TASK_TOKEN=internal-task-token", redacted)
        self.assertIn("OPERATOR_ADMIN_TOKEN=<redacted-secret-name>:latest", redacted)

    def test_runtime_placeholder_expands_only_for_execution(self):
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            return completed(0)

        command = ["python3", "script.py", "--internal-task-token", "$INTERNAL_TASK_TOKEN"]
        with patch.dict(mod.os.environ, {"INTERNAL_TASK_TOKEN": "test-runtime-token"}), patch.object(
            mod.subprocess, "run", side_effect=fake_run
        ):
            step = mod.run_command("cloudRunApiPreflight", command)

        self.assertEqual(step["status"], "ok")
        self.assertEqual(calls[0], ["python3", "script.py", "--internal-task-token", "test-runtime-token"])
        self.assertEqual(command, ["python3", "script.py", "--internal-task-token", "$INTERNAL_TASK_TOKEN"])

    def test_runtime_placeholder_missing_env_fails_before_subprocess(self):
        command = ["python3", "script.py", "--internal-task-token", "$INTERNAL_TASK_TOKEN"]
        with patch.dict(mod.os.environ, {}, clear=True), patch.object(mod.subprocess, "run") as run:
            step = mod.run_command("cloudRunApiPreflight", command)

        self.assertEqual(step["status"], "failed")
        self.assertEqual(step["returnCode"], 2)
        self.assertIn("INTERNAL_TASK_TOKEN is required", step["stderrTail"])
        run.assert_not_called()


def args_for(**overrides):
    values = {
        "service": "sermon-zh-caption-web",
        "project": "ai-for-god",
        "region": "us-west1",
        "base_url": "https://example.test",
        "sunday": "2026-06-28",
        "realtime_event_gcs_prefix": "gs://bucket/realtime-events",
        "required_model": "gpt-5.4-mini",
        "alternative_model": "gpt-5.5",
        "evidence_dir": Path("artifacts/evidence"),
        "out": Path("artifacts/evidence/production-preflight-refresh.json"),
        "dry_run": False,
        "local_only": False,
    }
    values.update(overrides)
    return Namespace(**values)


def completed(returncode, stdout="{}", stderr=""):
    class Completed:
        pass

    item = Completed()
    item.returncode = returncode
    item.stdout = stdout
    item.stderr = stderr
    return item


if __name__ == "__main__":
    unittest.main()
