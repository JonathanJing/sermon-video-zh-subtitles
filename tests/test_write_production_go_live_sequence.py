import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import scripts.write_production_go_live_sequence as mod


class WriteProductionGoLiveSequenceTest(unittest.TestCase):
    def test_sequence_consolidates_handoff_reports_without_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = write_reports(root)
            report = mod.build_sequence(args_for(paths))

        self.assertEqual(report["status"], "not_ready_for_go_live")
        self.assertEqual(report["handoffReports"]["operatorApprovalBundle"], str(paths["operator"]))
        self.assertEqual(report["handoffReports"]["modelAccessRecoveryPlan"], str(paths["model"]))
        self.assertEqual(report["handoffReports"]["noCaptionAsrFallbackPlan"], str(paths["asr"]))
        self.assertEqual(report["handoffReports"]["live1130RealtimeRunPlan"], str(paths["live"]))
        self.assertEqual(report["handoffReports"]["productionMatrix"], str(paths["matrix"]))
        stages = {stage["id"]: stage for stage in report["sequence"]}
        self.assertEqual(stages["operator_approval"]["state"], "approval_required")
        self.assertEqual(stages["post_approval_validation"]["state"], "blocked_until_operator_approval")
        self.assertEqual(stages["live_1130_realtime_run"]["state"], "ready_for_operator_review")
        self.assertEqual(stages["live_1130_realtime_run"]["targetWindow"]["liveCaptionStart"], "11:30 PT")
        self.assertEqual(
            stages["live_1130_realtime_run"]["modelPolicy"]["realtimeDraftModel"],
            "gpt-realtime-translate",
        )
        live_validation_commands = json.dumps(stages["live_1130_realtime_run"]["liveValidationCommands"])
        self.assertIn("run_realtime_public_sse_smoke.py", live_validation_commands)
        self.assertIn("--web-realtime-contract-report", live_validation_commands)
        self.assertIn("validate_realtime_session.py", live_validation_commands)
        self.assertIn(
            "scripts/run_realtime_stabilizer_loop.py",
            stages["live_1130_realtime_run"]["stabilizerFallbackCommand"],
        )
        live_choices = {
            choice["id"]: choice for choice in stages["live_1130_realtime_run"]["operatorChoices"]
        }
        self.assertTrue(live_choices["browser_webrtc_ipad_or_iphone_mic"]["default"])
        self.assertIn(
            "artifacts/evidence/web-realtime-contract.json",
            live_choices["browser_webrtc_ipad_or_iphone_mic"]["evidenceReports"],
        )
        self.assertIn(
            "artifacts/evidence/realtime-public-sse-smoke.json",
            live_choices["browser_webrtc_ipad_or_iphone_mic"]["evidenceReports"],
        )
        rendered_server_choice = json.dumps(live_choices["server_worker_authorized_audio"]["command"])
        self.assertIn("run_realtime_live_session.py", rendered_server_choice)
        self.assertIn("gpt-realtime-translate", rendered_server_choice)
        self.assertIn("gpt-5.4-mini", rendered_server_choice)
        post_approval_commands = json.dumps(stages["post_approval_validation"]["commands"])
        self.assertIn("--create-realtime-session", post_approval_commands)
        self.assertIn("--internal-task-token", post_approval_commands)
        self.assertIn("$INTERNAL_TASK_TOKEN", post_approval_commands)
        self.assertIn("run_realtime_public_sse_smoke.py", post_approval_commands)
        self.assertIn("--realtime-event-gcs-prefix", post_approval_commands)
        self.assertIn("--web-realtime-contract-report", post_approval_commands)
        self.assertIn("artifacts/evidence/web-realtime-contract.json", post_approval_commands)
        self.assertIn("realtime-public-sse-smoke.session-validation.json", post_approval_commands)
        self.assertIn("realtime_local_session_metadata", stages["post_approval_validation"]["expectedValidationChecks"])
        self.assertIn(
            "browser_normalized_event_payloads",
            stages["post_approval_validation"]["expectedValidationChecks"],
        )
        self.assertIn(
            "sse_stable_correction_matches_draft_segment",
            stages["post_approval_validation"]["expectedValidationChecks"],
        )
        self.assertIn("session_jsonl_validation", stages["post_approval_validation"]["expectedValidationChecks"])
        self.assertEqual(stages["required_model_recovery"]["state"], "blocked_by_required_model_access")
        self.assertTrue(stages["required_model_recovery"]["doNotSubstitute"])
        self.assertEqual(stages["real_no_caption_asr_validation"]["state"], "needs_real_no_caption_archive")
        asr_commands = json.dumps(stages["real_no_caption_asr_validation"]["commands"])
        self.assertIn("run_no_caption_archive_asr_route.py", asr_commands)
        self.assertIn("gpt-4o-transcribe", asr_commands)
        self.assertIn("gpt-5.4-mini", asr_commands)
        expanded_asr_commands = json.dumps(stages["real_no_caption_asr_validation"]["expandedCommands"])
        self.assertIn("prepare_live_link_playback.py", expanded_asr_commands)
        self.assertIn("translate_playback_with_openai.py", expanded_asr_commands)
        self.assertIn("validate_offline_chain.py", expanded_asr_commands)
        self.assertIn("no-caption-offline-chain-validation.json", expanded_asr_commands)
        self.assertIn(
            "artifacts/evidence/no-caption-offline-chain-validation.json",
            stages["real_no_caption_asr_validation"]["requiredReports"],
        )
        self.assertIn(
            "validate_offline_chain.py status is ok and not_realtime_chain passes.",
            stages["real_no_caption_asr_validation"]["passCriteria"],
        )
        self.assertIn(
            "validate_offline_chain.py confirms no requested English caption track exists before ASR fallback.",
            stages["real_no_caption_asr_validation"]["passCriteria"],
        )
        self.assertIn(
            "validate_offline_chain.py confirms the openai_asr output source_file is an extracted audio artifact.",
            stages["real_no_caption_asr_validation"]["passCriteria"],
        )
        self.assertIn(
            "--offline-asr-chain-validation-report",
            stages["real_no_caption_asr_validation"]["nextAction"],
        )
        self.assertIn("Offline post-live subtitle evidence includes not_realtime_chain=pass.", report["passCriteria"])
        self.assertIn(
            "A real authorized YouTube archive with no requested English caption track proves the gpt-4o-transcribe ASR fallback from an extracted audio artifact.",
            report["passCriteria"],
        )
        self.assertIn("cloudRunConfig", report["blockingSummary"]["failedPreflightSteps"])
        self.assertIn("goalAudit", report["blockingSummary"]["incompletePreflightSteps"])
        self.assertIn("operator_approval", report["blockingSummary"]["blockingStages"])
        final_commands = json.dumps(stages["final_readiness_audit"]["commands"])
        self.assertIn("refresh_production_preflight_evidence.py", final_commands)
        self.assertIn("write_production_go_live_sequence.py", final_commands)
        self.assertNotIn("collect_production_evidence_matrix.py", final_commands)
        rendered = json.dumps(report)
        self.assertNotIn("projects/", rendered)
        self.assertNotIn("/secrets/", rendered)
        self.assertNotIn("sk-test", rendered)
        self.assertFalse(report["apiKeyMaterialIncluded"])
        self.assertFalse(report["secretResourceNamesIncluded"])
        self.assertFalse(report["eventTokenIncluded"])
        self.assertTrue(report["guards"]["doesNotApplyCloudRun"])
        self.assertTrue(report["guards"]["doesNotUploadGcs"])

    def test_sequence_can_be_ready_when_all_gates_are_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = write_reports(
                root,
                preflight={"status": "ok", "failedSteps": [], "incompleteSteps": []},
                goal={"status": "complete", "failedChecks": [], "summary": {"externalMissing": 0}},
                unblock={"status": "complete", "approvalStepCount": 0},
                operator={"status": "no_approval_steps", "approvalStepCount": 0},
                model={"status": "complete", "modelPolicy": {"doNotSubstitute": True}},
                asr={"status": "complete", "requiredModels": {"offlineAsr": "gpt-4o-transcribe"}},
            )
            report = mod.build_sequence(args_for(paths))

        self.assertEqual(report["status"], "ready_for_go_live")
        self.assertEqual(report["blockingSummary"]["blockingStages"], [])

    def test_sequence_uses_current_matrix_when_no_caption_plan_is_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = write_reports(
                root,
                preflight={
                    "status": "incomplete",
                    "failedSteps": [],
                    "incompleteSteps": ["productionMatrix", "productionUnblockPlan", "goalAudit"],
                },
                goal={"status": "complete", "failedChecks": [], "summary": {"externalMissing": 0}},
                unblock={"status": "complete", "approvalStepCount": 0, "steps": []},
                operator={"status": "no_approval_steps", "approvalStepCount": 0},
                asr={"status": "needs_real_no_caption_archive"},
                matrix={
                    "status": "complete",
                    "matrix": [
                        {
                            "id": "offline_asr_route",
                            "state": "pass",
                            "evidence": "artifacts/evidence/no-caption-asr-route-run.json",
                            "observed": {
                                "status": "ok",
                                "models": {
                                    "offlineAsr": "gpt-4o-transcribe",
                                    "offlineTranslation": "gpt-5.4-mini",
                                },
                            },
                        }
                    ],
                },
            )
            report = mod.build_sequence(args_for(paths))

        stages = {stage["id"]: stage for stage in report["sequence"]}
        self.assertEqual(stages["real_no_caption_asr_validation"]["state"], "complete")
        self.assertEqual(stages["final_readiness_audit"]["state"], "complete")
        self.assertEqual(report["status"], "ready_for_go_live")
        self.assertEqual(report["blockingSummary"]["incompletePreflightSteps"], [])
        self.assertEqual(
            stages["real_no_caption_asr_validation"]["currentEvidence"]["matrixRow"],
            "offline_asr_route",
        )

    def test_model_recovery_stage_is_omitted_when_current_matrix_does_not_need_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = write_reports(
                root,
                preflight={"status": "incomplete", "failedSteps": [], "incompleteSteps": ["productionMatrix", "goalAudit"]},
                unblock={
                    "status": "ready_for_approval",
                    "approvalStepCount": 2,
                    "steps": [
                        {"id": "apply_cloud_run_realtime_config", "requiresApproval": True},
                        {"id": "publish_sunday_manifest_to_gcs", "requiresApproval": True},
                        {"id": "validate_deployed_stable_correction_session", "dependency": "prior_step"},
                    ],
                },
                model={
                    "status": "waiting_for_required_model_access",
                    "requiredModel": "gpt-5.4-mini",
                    "alternativeModel": "gpt-5.5",
                    "modelPolicy": {"doNotSubstitute": True},
                },
            )
            report = mod.build_sequence(args_for(paths))

        stages = {stage["id"]: stage for stage in report["sequence"]}
        self.assertNotIn("required_model_recovery", stages)
        self.assertEqual(stages["real_no_caption_asr_validation"]["dependsOn"], ["post_approval_validation"])
        self.assertNotIn("required_model_recovery", stages["final_readiness_audit"]["dependsOn"])
        self.assertNotIn("required_model_recovery", report["blockingSummary"]["blockingStages"])

    def test_live_stage_is_pending_when_unblock_plan_has_realtime_live_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = write_reports(
                root,
                unblock={
                    "status": "ready_for_approval",
                    "approvalStepCount": 2,
                    "steps": [
                        {"id": "apply_cloud_run_realtime_config", "requiresApproval": True},
                        {
                            "id": "run_real_realtime_field_session",
                            "sourceRow": "realtime_live",
                            "state": "pending",
                            "reason": "Run the 11:30 iPad mic or authorized live source.",
                            "commands": [["python3", "scripts/run_realtime_live_session.py"]],
                            "expectedChecks": ["caption_events", "input_transcript_events"],
                        },
                    ],
                },
            )
            report = mod.build_sequence(args_for(paths))

        stages = {stage["id"]: stage for stage in report["sequence"]}
        live = stages["live_1130_realtime_run"]
        self.assertEqual(live["state"], "pending_realtime_field_run")
        self.assertIn("run_realtime_live_session.py", json.dumps(live["commands"]))
        self.assertIn("run_realtime_public_sse_smoke.py", json.dumps(live["liveValidationCommands"]))
        self.assertIn("input_transcript_events", live["expectedChecks"])
        self.assertIn("live_1130_realtime_run", report["blockingSummary"]["blockingStages"])

    def test_main_writes_sequence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = write_reports(root)
            out = root / "go-live.json"
            original_argv = sys.argv
            try:
                sys.argv = [
                    "write_production_go_live_sequence.py",
                    "--sunday",
                    "2026-06-28",
                    "--preflight-refresh",
                    str(paths["preflight"]),
                    "--goal-audit",
                    str(paths["goal"]),
                    "--unblock-plan",
                    str(paths["unblock"]),
                    "--operator-approval-bundle",
                    str(paths["operator"]),
                    "--model-access-recovery-plan",
                    str(paths["model"]),
                    "--no-caption-asr-plan",
                    str(paths["asr"]),
                    "--live-1130-run-plan",
                    str(paths["live"]),
                    "--production-matrix",
                    str(paths["matrix"]),
                    "--out",
                    str(out),
                ]
                exit_code = mod.main()
            finally:
                sys.argv = original_argv

            written = json.loads(out.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(written["sunday"], "2026-06-28")


def args_for(paths):
    return Namespace(
        sunday="2026-06-28",
        preflight_refresh=paths["preflight"],
        goal_audit=paths["goal"],
        unblock_plan=paths["unblock"],
        operator_approval_bundle=paths["operator"],
        model_access_recovery_plan=paths["model"],
        no_caption_asr_plan=paths["asr"],
        live_1130_run_plan=paths["live"],
        production_matrix=paths["matrix"],
        out=None,
    )


def write_reports(root: Path, **overrides):
    defaults = {
        "preflight": {
            "status": "incomplete",
            "failedSteps": ["cloudRunConfig", "requiredModelAccess"],
            "incompleteSteps": ["goalAudit"],
        },
        "goal": {
            "status": "incomplete",
            "failedChecks": ["external:cloud-run-config"],
            "summary": {"externalMissing": 6},
        },
        "unblock": {"status": "ready_for_approval", "approvalStepCount": 2},
        "operator": {"status": "approval_required", "approvalStepCount": 2},
        "model": {
            "status": "waiting_for_required_model_access",
            "requiredModel": "gpt-5.4-mini",
            "alternativeModel": "gpt-5.5",
            "modelPolicy": {"doNotSubstitute": True},
        },
        "asr": {
            "status": "needs_real_no_caption_archive",
            "requiredModels": {
                "offlineAsr": "gpt-4o-transcribe",
                "offlineTranslation": "gpt-5.4-mini",
                "forbiddenOfflineModel": "gpt-realtime-translate",
            },
            "runnerCommand": [
                "python3",
                "scripts/run_no_caption_archive_asr_route.py",
                "--live-url",
                "<NO_CAPTION_YOUTUBE_LIVE_ARCHIVE_URL>",
                "--api-key-secret",
                "<OPENAI_API_KEY_SECRET_RESOURCE>",
                "--sunday",
                "2026-06-28",
                "--asr-model",
                "gpt-4o-transcribe",
                "--translation-model",
                "gpt-5.4-mini",
            ],
            "commands": [
                [
                    "python3",
                    "scripts/prepare_live_link_playback.py",
                    "--asr-model",
                    "gpt-4o-transcribe",
                    "--web-out",
                    "artifacts/evidence/2026-06-28-no-caption-asr-route/web/playback-simulation.generated.js",
                ],
                [
                    "python3",
                    "scripts/translate_playback_with_openai.py",
                    "--model",
                    "gpt-5.4-mini",
                ],
                [
                    "python3",
                    "scripts/validate_offline_chain.py",
                    "--out",
                    "artifacts/evidence/no-caption-offline-chain-validation.json",
                ],
            ],
            "passCriteria": [
                "run_offline_archive_preflight.py reports decision=use_asr_fallback.",
                "Prepared offline report has caption_source.kind=openai_asr.",
                "validate_offline_chain.py confirms no requested English caption track exists before ASR fallback.",
                "validate_offline_chain.py confirms the openai_asr output source_file is an extracted audio artifact.",
                "ASR model is gpt-4o-transcribe.",
                "Chinese translation model is gpt-5.4-mini.",
                "validate_offline_chain.py status is ok and not_realtime_chain passes.",
            ],
        },
        "live": {
            "status": "ready_for_operator_review",
            "targetWindow": {"liveCaptionStart": "11:30 PT", "publicReadinessDeadline": "11:50 PT"},
            "modelPolicy": {
                "realtimeDraftModel": "gpt-realtime-translate",
                "stableCorrectionModel": "gpt-5.4-mini",
                "offlineAsrModel": "gpt-4o-transcribe",
                "offlineTranslationModel": "gpt-5.4-mini",
                "forbiddenOfflineModel": "gpt-realtime-translate",
            },
            "operatorChoices": [
                {
                    "id": "browser_webrtc_ipad_or_iphone_mic",
                    "default": True,
                    "source": "iPad/iPhone mic",
                    "path": "browser WebRTC -> gpt-realtime-translate -> backend session events -> public caption SSE",
                    "expectedAudioSourceKind": "ipad_mic",
                    "operatorAction": "Open the admin page, choose iPad mic realtime mode, and start the microphone session.",
                    "evidenceReports": [
                        "artifacts/evidence/web-realtime-contract.json",
                        "artifacts/evidence/realtime-public-sse-smoke.json",
                    ],
                },
                {
                    "id": "server_worker_authorized_audio",
                    "default": False,
                    "source": "authorized audio URL/file or authorized YouTube live source",
                    "path": "server media worker -> gpt-realtime-translate -> backend session events -> public caption SSE",
                    "expectedAudioSourceKinds": ["authorized_audio_url", "authorized_audio_file", "authorized_youtube_source"],
                    "command": [
                        "python3",
                        "scripts/run_realtime_live_session.py",
                        "--realtime-model",
                        "gpt-realtime-translate",
                        "--stable-model",
                        "gpt-5.4-mini",
                    ],
                },
            ],
            "liveValidationCommands": [
                [
                    "python3",
                    "scripts/run_realtime_public_sse_smoke.py",
                    "--web-realtime-contract-report",
                    "artifacts/evidence/web-realtime-contract.json",
                ],
                [
                    "python3",
                    "scripts/validate_realtime_session.py",
                    "--expected-model",
                    "gpt-realtime-translate",
                ],
            ],
            "stabilizerFallbackCommand": [
                "python3",
                "scripts/run_realtime_stabilizer_loop.py",
                "--model",
                "gpt-5.4-mini",
            ],
        },
        "matrix": {
            "status": "incomplete",
            "matrix": [
                {
                    "id": "offline_asr_route",
                    "state": "missing",
                }
            ],
        },
    }
    defaults.update(overrides)
    paths = {
        "preflight": root / "production-preflight-refresh.json",
        "goal": root / "production-goal-readiness-audit.json",
        "unblock": root / "production-unblock-plan.json",
        "operator": root / "operator-approval-bundle.json",
        "model": root / "model-access-recovery-plan.json",
        "asr": root / "no-caption-asr-fallback-plan.json",
        "live": root / "live-1130-realtime-run-plan.json",
        "matrix": root / "production-evidence-matrix.json",
    }
    for key, path in paths.items():
        path.write_text(json.dumps(defaults[key]), encoding="utf-8")
    return paths


if __name__ == "__main__":
    unittest.main()
