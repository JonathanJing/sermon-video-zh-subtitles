import json
import sys
import tempfile
import unittest
from pathlib import Path

import scripts.write_production_unblock_plan as mod


class WriteProductionUnblockPlanTest(unittest.TestCase):
    def test_builds_ordered_plan_with_approval_and_model_dependency(self):
        matrix = matrix_report()
        publish_plan = {
            "status": "planned",
            "sunday": "2026-06-28",
            "localRoot": "artifacts/evidence/manifest-promotion-guard",
            "bucket": "sermon-zh-artifacts-ai-for-god",
            "prefix": "sundays",
            "sessionId": "local-manifest-contract",
            "stableManifestUri": "gs://bucket/sundays/2026-06-28/cloud-manifest.json",
            "artifacts": [{}, {}, {}],
        }

        report = mod.build_unblock_plan(
            matrix=matrix,
            publish_plan=publish_plan,
            cloud_run_update_plan="artifacts/evidence/cloud-run-realtime-update-plan.json",
        )

        self.assertEqual(report["status"], "ready_for_approval")
        self.assertTrue(report["requiresApproval"])
        self.assertEqual(report["operatorApprovalBundle"], "artifacts/evidence/operator-approval-bundle.json")
        self.assertEqual(report["approvalStepCount"], 2)
        self.assertGreaterEqual(report["externalDependencyCount"], 1)
        self.assertEqual(report["steps"][0]["id"], "apply_cloud_run_realtime_config")
        self.assertIn("--plan", report["steps"][0]["commands"][0])
        self.assertIn("artifacts/evidence/cloud-run-realtime-update-plan.json", report["steps"][0]["commands"][0])
        self.assertEqual(report["steps"][1]["id"], "publish_sunday_manifest_to_gcs")
        rendered_publish_commands = json.dumps(report["steps"][1]["commands"])
        self.assertIn("--apply", rendered_publish_commands)
        self.assertIn("--confirm-production-stable", rendered_publish_commands)
        model_step = next(step for step in report["steps"] if step["id"] == "fix_required_gpt_5_4_mini_access")
        self.assertTrue(model_step["doNotSubstitute"])
        self.assertEqual(model_step["availableButNotConfiguredModels"], ["gpt-5.5"])
        self.assertEqual(model_step["recoveryPlan"], "artifacts/evidence/model-access-recovery-plan.json")
        preflight_step = next(step for step in report["steps"] if step["id"] == "rerun_cloud_run_api_preflight")
        rendered_preflight_commands = json.dumps(preflight_step["commands"])
        self.assertIn("--create-realtime-session", rendered_preflight_commands)
        self.assertIn("--internal-task-token", rendered_preflight_commands)
        self.assertIn("$INTERNAL_TASK_TOKEN", rendered_preflight_commands)
        self.assertIn("realtime_local_session_metadata", preflight_step["expectedChecks"])
        sse_step = next(step for step in report["steps"] if step["id"] == "rerun_deployed_public_sse_smoke")
        rendered_sse_commands = json.dumps(sse_step["commands"])
        self.assertIn("run_realtime_public_sse_smoke.py", rendered_sse_commands)
        self.assertIn("--realtime-event-gcs-prefix", rendered_sse_commands)
        self.assertIn("gs://sermon-zh-artifacts-ai-for-god/realtime-events", rendered_sse_commands)
        self.assertIn("--web-realtime-contract-report", rendered_sse_commands)
        self.assertIn("artifacts/evidence/web-realtime-contract.json", rendered_sse_commands)
        self.assertIn("$INTERNAL_TASK_TOKEN", rendered_sse_commands)
        self.assertIn("browser_normalized_event_payloads", sse_step["expectedChecks"])
        self.assertIn("sse_stable_correction_matches_draft_segment", sse_step["expectedChecks"])
        self.assertIn("session_jsonl_validation", sse_step["expectedChecks"])
        realtime_step = next(step for step in report["steps"] if step["id"] == "run_real_realtime_field_session")
        self.assertEqual(realtime_step["sourceRow"], "realtime_live")
        self.assertEqual(realtime_step["dependency"], "post_approval_validation")
        rendered_realtime_commands = json.dumps(realtime_step["commands"])
        self.assertIn("run_realtime_live_session.py", rendered_realtime_commands)
        self.assertIn("validate_realtime_session.py", rendered_realtime_commands)
        self.assertIn("gpt-realtime-translate", rendered_realtime_commands)
        self.assertIn("gpt-5.4-mini", rendered_realtime_commands)
        self.assertIn("stable_correction_matches_realtime_draft_segment", realtime_step["expectedChecks"])
        self.assertIn("stable_correction_context", realtime_step["expectedChecks"])
        asr_step = next(step for step in report["steps"] if step["id"] == "run_real_no_caption_archive_asr_route")
        self.assertEqual(asr_step["planReport"], "artifacts/evidence/no-caption-asr-fallback-plan.json")
        self.assertIn("asr_no_requested_caption_tracks", asr_step["expectedChecks"])
        self.assertIn("asr_audio_source_artifact", asr_step["expectedChecks"])
        self.assertIn("not_realtime_chain", asr_step["expectedChecks"])
        self.assertTrue(report["modelPolicy"]["observedAlternativeModelsAreNotSubstitutes"])
        self.assertFalse(report["apiKeyMaterialIncluded"])
        self.assertFalse(report["secretResourceNamesIncluded"])
        self.assertFalse(report["eventTokenIncluded"])

    def test_complete_matrix_has_complete_unblock_plan(self):
        report = mod.build_unblock_plan(
            matrix={"status": "complete", "summary": {"passed": 14}, "matrix": []},
            publish_plan=None,
        )

        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["steps"], [])

    def test_stable_correction_deployed_validation_is_not_model_access_dependency(self):
        matrix = matrix_report()
        for row in matrix["matrix"]:
            if row["id"] == "stable_correction":
                row["state"] = "warn"
                row["nextAction"] = (
                    "Local stable correction session validation passed. Rerun realtime public SSE smoke against "
                    "the deployed Cloud Run URL, or validate the real saved realtime JSONL with --require-stable-correction."
                )
                row["observed"] = {
                    "baseUrl": "http://127.0.0.1:8768",
                    "sessionValidation": {
                        "status": "ok",
                        "counts": {"stableCorrectionEvents": 1},
                    },
                    "stableCorrection": {"matched": True},
                }

        report = mod.build_unblock_plan(matrix=matrix, publish_plan=None)

        step = next(step for step in report["steps"] if step.get("sourceRow") == "stable_correction")
        self.assertEqual(step["id"], "validate_deployed_stable_correction_session")
        self.assertEqual(step["dependency"], "prior_step")
        rendered = json.dumps(step["commands"])
        self.assertIn("validate_realtime_session.py", rendered)
        self.assertIn("--require-stable-correction", rendered)
        self.assertIn("stable_correction_matches_realtime_draft_segment", step["expectedChecks"])
        self.assertIn("stable_correction_context", step["expectedChecks"])

    def test_main_writes_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            matrix = root / "matrix.json"
            out = root / "unblock.json"
            matrix.write_text(json.dumps(matrix_report()), encoding="utf-8")

            argv = [
                "write_production_unblock_plan.py",
                "--evidence-matrix",
                str(matrix),
                "--out",
                str(out),
            ]
            original_argv = sys.argv
            try:
                sys.argv = argv
                exit_code = mod.main()
            finally:
                sys.argv = original_argv

            written = json.loads(out.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(written["status"], "ready_for_approval")


def matrix_report():
    return {
        "status": "incomplete",
        "summary": {"passed": 7, "failed": 3, "warnings": 4, "missing": 0, "total": 14},
        "matrix": [
            {
                "id": "cloud_run_realtime_config",
                "state": "fail",
                "nextAction": "Apply the approved Cloud Run realtime update plan.",
                "observed": {"status": "failed"},
            },
            {
                "id": "cloud_run_api_preflight",
                "state": "warn",
                "nextAction": "Rerun preflight with --create-realtime-session.",
            },
            {
                "id": "realtime_public_sse_contract",
                "state": "warn",
                "nextAction": "Rerun realtime public SSE smoke against Cloud Run.",
            },
            {
                "id": "realtime_live",
                "state": "warn",
                "nextAction": "Realtime OpenAI smoke passed on synthetic audio only.",
            },
            {
                "id": "stable_correction",
                "state": "fail",
                "nextAction": "Fix gpt-5.4-mini model access.",
                "observed": {
                    "model": "gpt-5.4-mini",
                    "failureKind": "model_unavailable_or_not_found",
                    "httpStatus": 400,
                    "error": "The requested model 'gpt-5.4-mini' does not exist.",
                    "availableButNotConfiguredModels": ["gpt-5.5"],
                },
            },
            {
                "id": "offline_caption_route",
                "state": "fail",
                "nextAction": "Fix offline translation model/access issue.",
                "observed": {
                    "model": "gpt-5.4-mini",
                    "failureKind": "model_unavailable_or_not_found",
                    "httpStatus": 400,
                    "error": "The requested model 'gpt-5.4-mini' does not exist.",
                },
            },
            {
                "id": "offline_asr_route",
                "state": "warn",
                "nextAction": "Run a real no-caption YouTube archive.",
            },
            {
                "id": "cloud_run_gcs_manifest",
                "state": "warn",
                "nextAction": "Upload/promote the manifest and artifacts to GCS.",
            },
        ],
    }


if __name__ == "__main__":
    unittest.main()
