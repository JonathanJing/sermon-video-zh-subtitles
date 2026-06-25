import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import scripts.write_operator_approval_bundle as mod


class WriteOperatorApprovalBundleTest(unittest.TestCase):
    def test_bundle_summarizes_cloud_run_and_gcs_approval_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            no_caption = write_json(root / "no-caption.json", no_caption_asr_plan())
            unblock = write_json(root / "unblock.json", unblock_plan(no_caption))
            cloud_plan = write_json(root / "cloud-plan.json", cloud_update_plan())
            dry_run = write_json(root / "dry-run.json", cloud_dry_run())
            gcs = write_json(root / "gcs-plan.json", gcs_plan())
            live_1130 = write_json(root / "live-1130.json", live_1130_run_plan())

            report = mod.build_bundle(args_for(unblock, cloud_plan, dry_run, gcs, live_1130))

        self.assertEqual(report["status"], "approval_required")
        self.assertEqual(report["approvalStepCount"], 2)
        self.assertEqual(
            [item["id"] for item in report["requiredApprovals"]],
            ["apply_cloud_run_realtime_config", "publish_sunday_manifest_to_gcs"],
        )
        self.assertTrue(report["guards"]["doesNotApplyCloudRun"])
        self.assertTrue(report["guards"]["doesNotUploadGcs"])
        self.assertTrue(report["guards"]["gcsProductionStableRequiresConfirmFlag"])
        steps = {step["id"]: step for step in report["approvalSteps"]}
        cloud = steps["apply_cloud_run_realtime_config"]
        publish = steps["publish_sunday_manifest_to_gcs"]
        self.assertEqual(cloud["approvalKind"], "cloud_run_runtime_update")
        self.assertIn("--max-instances", cloud["applyCommand"])
        self.assertIn("--remove-env-vars", cloud["rollbackCommand"])
        self.assertEqual(len(cloud["validationCommands"]), 3)
        rendered_validation = json.dumps(cloud["validationCommands"])
        self.assertIn("run_cloud_run_realtime_preflight.py", rendered_validation)
        self.assertIn("run_realtime_public_sse_smoke.py", rendered_validation)
        self.assertIn("--web-realtime-contract-report", rendered_validation)
        self.assertIn("artifacts/evidence/web-realtime-contract.json", rendered_validation)
        self.assertIn("realtime_local_session_metadata", cloud["expectedValidationChecks"])
        self.assertIn("browser_normalized_event_payloads", cloud["expectedValidationChecks"])
        self.assertIn("sse_stable_correction_matches_draft_segment", cloud["expectedValidationChecks"])
        self.assertIn("session_jsonl_validation", cloud["expectedValidationChecks"])
        rendered_top_level_validation = json.dumps(report["postApprovalValidation"]["commands"])
        self.assertIn("run_cloud_run_realtime_preflight.py", rendered_top_level_validation)
        self.assertIn("run_realtime_public_sse_smoke.py", rendered_top_level_validation)
        self.assertIn("session_jsonl_validation", report["postApprovalValidation"]["expectedChecks"])
        self.assertIn(
            "artifacts/evidence/cloud-run-api-preflight.json",
            report["postApprovalValidation"]["requiredEvidence"],
        )
        self.assertTrue(report["rollback"]["available"])
        self.assertIn("--remove-env-vars", json.dumps(report["rollback"]["commands"]))
        self.assertTrue(report["rollback"]["requiresExplicitApproval"])
        self.assertIn("artifacts/evidence/web-realtime-contract.json", report["postApprovalEvidence"])
        self.assertIn("artifacts/evidence/realtime-public-sse-smoke.json", report["postApprovalEvidence"])
        self.assertIn("rerun_cloud_run_api_preflight", [step["id"] for step in report["postApprovalFollowupSteps"]])
        no_caption_followup = next(step for step in report["postApprovalFollowupSteps"] if step["id"] == "run_real_no_caption_archive_asr_route")
        rendered_no_caption = json.dumps(no_caption_followup["commands"])
        self.assertIn("run_no_caption_archive_asr_route.py", rendered_no_caption)
        self.assertIn("gpt-4o-transcribe", rendered_no_caption)
        self.assertIn("gpt-5.4-mini", rendered_no_caption)
        self.assertIn("run_offline_archive_preflight.py", json.dumps(no_caption_followup["expandedCommands"]))
        self.assertEqual(no_caption_followup["planStatus"], "needs_real_no_caption_archive")
        self.assertEqual(report["live1130Runbook"]["status"], "ready_for_operator_review")
        self.assertEqual(report["live1130Runbook"]["targetWindow"]["liveCaptionStart"], "11:30 PT")
        self.assertEqual(report["live1130Runbook"]["modelPolicy"]["realtimeDraftModel"], "gpt-realtime-translate")
        self.assertEqual(report["live1130Runbook"]["modelPolicy"]["offlineTranslationModel"], "gpt-5.4-mini")
        self.assertEqual(
            report["live1130Runbook"]["defaultPath"],
            "browser WebRTC -> gpt-realtime-translate -> backend session events -> public caption SSE",
        )
        self.assertEqual(
            report["live1130Runbook"]["postLiveOfflineHandoff"]["trigger"],
            "Run only after the YouTube live archive is available.",
        )
        live_validation_commands = json.dumps(report["live1130Runbook"]["liveValidationCommands"])
        self.assertIn("run_realtime_public_sse_smoke.py", live_validation_commands)
        self.assertIn("--web-realtime-contract-report", live_validation_commands)
        self.assertIn("validate_realtime_session.py", live_validation_commands)
        self.assertIn(
            "scripts/run_realtime_stabilizer_loop.py",
            report["live1130Runbook"]["stabilizerFallbackCommand"],
        )
        server_choice = next(
            choice
            for choice in report["live1130Runbook"]["operatorChoices"]
            if choice["id"] == "server_worker_authorized_audio"
        )
        browser_choice = next(
            choice
            for choice in report["live1130Runbook"]["operatorChoices"]
            if choice["id"] == "browser_webrtc_ipad_or_iphone_mic"
        )
        self.assertIn("artifacts/evidence/web-realtime-contract.json", browser_choice["evidenceReports"])
        self.assertIn("artifacts/evidence/realtime-public-sse-smoke.json", browser_choice["evidenceReports"])
        rendered_server_command = json.dumps(server_choice["command"])
        self.assertIn("scripts/run_realtime_live_session.py", rendered_server_command)
        self.assertIn("gpt-realtime-translate", rendered_server_command)
        self.assertIn("gpt-5.4-mini", rendered_server_command)
        self.assertTrue(cloud["secretReferencesIncluded"])
        self.assertEqual(publish["approvalKind"], "gcs_manifest_publish")
        self.assertEqual(publish["stableManifestUri"], "gs://bucket/sundays/2026-06-28/cloud-manifest.json")
        self.assertEqual(publish["artifactCount"], 3)
        self.assertTrue(publish["productionStableConfirmRequired"])
        self.assertIn("--confirm-production-stable", json.dumps(publish["approvalCommands"]))
        rendered = json.dumps(report)
        self.assertNotIn("projects/", rendered)
        self.assertNotIn("/secrets/", rendered)
        self.assertNotIn("evt_", rendered)
        self.assertFalse(report["apiKeyMaterialIncluded"])
        self.assertFalse(report["secretResourceNamesIncluded"])
        self.assertFalse(report["eventTokenIncluded"])

    def test_no_approval_steps_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            unblock = write_json(root / "unblock.json", {"schemaVersion": 1, "steps": []})

            report = mod.build_bundle(
                args_for(unblock, root / "missing.json", root / "missing2.json", root / "missing3.json", root / "missing4.json")
            )

        self.assertEqual(report["status"], "no_approval_steps")
        self.assertEqual(report["approvalStepCount"], 0)
        self.assertEqual(report["requiredApprovals"], [])
        self.assertFalse(report["rollback"]["available"])

    def test_main_writes_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "bundle.json"
            unblock = write_json(root / "unblock.json", unblock_plan())
            cloud_plan = write_json(root / "cloud-plan.json", cloud_update_plan())
            dry_run = write_json(root / "dry-run.json", cloud_dry_run())
            gcs = write_json(root / "gcs-plan.json", gcs_plan())
            live_1130 = write_json(root / "live-1130.json", live_1130_run_plan())
            original_argv = sys.argv
            try:
                sys.argv = [
                    "write_operator_approval_bundle.py",
                    "--sunday",
                    "2026-06-28",
                    "--unblock-plan",
                    str(unblock),
                    "--cloud-run-update-plan",
                    str(cloud_plan),
                    "--cloud-run-dry-run",
                    str(dry_run),
                    "--gcs-publish-plan",
                    str(gcs),
                    "--live-1130-run-plan",
                    str(live_1130),
                    "--out",
                    str(out),
                ]
                exit_code = mod.main()
            finally:
                sys.argv = original_argv

            written = json.loads(out.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(written["status"], "approval_required")


def args_for(unblock, cloud_plan, dry_run, gcs, live_1130):
    return Namespace(
        sunday="2026-06-28",
        unblock_plan=unblock,
        cloud_run_update_plan=cloud_plan,
        cloud_run_dry_run=dry_run,
        gcs_publish_plan=gcs,
        live_1130_run_plan=live_1130,
        out=None,
    )


def write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def unblock_plan(no_caption_plan=None):
    no_caption_step = []
    if no_caption_plan:
        no_caption_step = [
            {
                "id": "run_real_no_caption_archive_asr_route",
                "sourceRow": "offline_asr_route",
                "state": "pending",
                "dependency": "real_source",
                "requiresApproval": False,
                "planReport": str(no_caption_plan),
            }
        ]
    return {
        "schemaVersion": 1,
        "steps": [
            {
                "id": "apply_cloud_run_realtime_config",
                "state": "approval_required",
                "requiresApproval": True,
                "reason": "Apply the approved Cloud Run realtime update plan.",
                "commands": [["python3", "scripts/apply_cloud_run_realtime_update_plan.py", "--approve"]],
            },
            {
                "id": "publish_sunday_manifest_to_gcs",
                "state": "approval_required",
                "requiresApproval": True,
                "reason": "Upload/promote the manifest and artifacts to GCS.",
                "stableManifestUri": "gs://bucket/sundays/2026-06-28/cloud-manifest.json",
                "artifactCount": 3,
                "commands": [
                    [
                        "python3",
                        "scripts/plan_gcs_sunday_manifest_publish.py",
                        "--apply",
                        "--confirm-production-stable",
                    ]
                ],
            },
            {
                "id": "rerun_cloud_run_api_preflight",
                "sourceRow": "cloud_run_api_preflight",
                "state": "pending",
                "requiresApproval": False,
                "commands": [["python3", "scripts/run_cloud_run_realtime_preflight.py"]],
            },
            {
                "id": "rerun_deployed_public_sse_smoke",
                "sourceRow": "realtime_public_sse_contract",
                "state": "pending",
                "requiresApproval": False,
                "commands": [
                    [
                        "python3",
                        "scripts/run_realtime_public_sse_smoke.py",
                        "--web-realtime-contract-report",
                        "artifacts/evidence/web-realtime-contract.json",
                    ]
                ],
            },
            *no_caption_step,
        ],
    }


def cloud_update_plan():
    return {
        "status": "approval_required",
        "secretReferencesIncluded": True,
        "plannedChanges": [
            {"name": "single_instance_realtime_sse", "needed": True},
            {"name": "realtime_event_gcs_prefix", "needed": True},
        ],
    }


def cloud_dry_run():
    return {
        "status": "dry_run",
        "wouldApply": [
            "gcloud",
            "run",
            "services",
            "update",
            "sermon-zh-caption-web",
            "--max-instances",
            "1",
            "--update-secrets",
            "OPERATOR_ADMIN_TOKEN=<redacted-secret>",
        ],
        "wouldRollback": [
            "gcloud",
            "run",
            "services",
            "update",
            "sermon-zh-caption-web",
            "--remove-env-vars",
            "REALTIME_EVENT_GCS_PREFIX",
        ],
        "wouldValidate": [["python3", "scripts/validate_cloud_run_realtime_config.py"]],
    }


def gcs_plan():
    return {
        "status": "planned",
        "stableManifestUri": "gs://bucket/sundays/2026-06-28/cloud-manifest.json",
        "runManifestUri": "gs://bucket/sundays/2026-06-28/runs/test/artifacts/cloud-manifest.json",
        "artifacts": [{}, {}, {}],
        "commands": [["gcloud", "storage", "cp", "local", "gs://bucket/object"]],
        "localValidation": {"status": "ok"},
        "gcsManifestValidation": {"status": "ok"},
    }


def live_1130_run_plan():
    return {
        "status": "ready_for_operator_review",
        "sunday": "2026-06-28",
        "targetWindow": {
            "liveCaptionStart": "11:30 PT",
            "publicReadinessDeadline": "11:50 PT",
        },
        "modelPolicy": {
            "realtimeDraftModel": "gpt-realtime-translate",
            "stableCorrectionModel": "gpt-5.4-mini",
            "offlineAsrModel": "gpt-4o-transcribe",
            "offlineTranslationModel": "gpt-5.4-mini",
            "forbiddenOfflineModel": "gpt-realtime-translate",
            "doNotSubstituteAlternativeForRequiredMini": True,
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
        "passCriteria": [
            "Realtime session uses gpt-realtime-translate and targetLanguage=zh.",
            "Offline post-live route never uses gpt-realtime-translate.",
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
        "postLiveOfflineHandoff": {
            "trigger": "Run only after the YouTube live archive is available.",
            "captionFirst": ["Try requested English captions/VTT first.", "Translate with gpt-5.4-mini."],
            "noCaptionFallback": ["Transcribe with gpt-4o-transcribe.", "Translate with gpt-5.4-mini."],
        },
        "guards": {
            "doesNotApplyCloudRun": True,
            "doesNotCallOpenAI": True,
            "doesNotUploadGcs": True,
            "requiresExplicitOperatorApprovalForMutation": True,
        },
    }


def no_caption_asr_plan():
    return {
        "status": "needs_real_no_caption_archive",
        "runnerCommand": [
            "python3",
            "scripts/run_no_caption_archive_asr_route.py",
            "--live-url",
            "<NO_CAPTION_YOUTUBE_LIVE_ARCHIVE_URL>",
            "--api-key-secret",
            "<OPENAI_API_KEY_SECRET_RESOURCE>",
            "--sunday",
            "2026-06-28",
            "--session-id",
            "no-caption-asr-route",
            "--asr-model",
            "gpt-4o-transcribe",
            "--translation-model",
            "gpt-5.4-mini",
        ],
        "commands": [
            [
                "python3",
                "scripts/run_offline_archive_preflight.py",
                "--live-url",
                "<NO_CAPTION_YOUTUBE_LIVE_ARCHIVE_URL>",
                "--asr-model",
                "gpt-4o-transcribe",
            ],
            [
                "python3",
                "scripts/translate_playback_with_openai.py",
                "--model",
                "gpt-5.4-mini",
            ],
        ],
    }


if __name__ == "__main__":
    unittest.main()
