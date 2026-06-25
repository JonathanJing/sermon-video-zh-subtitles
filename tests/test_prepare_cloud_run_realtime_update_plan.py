import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import scripts.prepare_cloud_run_realtime_update_plan as mod


class PrepareCloudRunRealtimeUpdatePlanTest(unittest.TestCase):
    def test_failed_config_generates_redacted_approval_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "config.json"
            report.write_text(json.dumps(failed_config_report()), encoding="utf-8")

            plan = mod.build_plan(args_for(report))

        self.assertEqual(plan["status"], "approval_required")
        self.assertTrue(plan["requiresExplicitApproval"])
        self.assertIn("single_instance_realtime_sse", plan["currentConfig"]["failedChecks"])
        self.assertIn("--max-instances 1", plan["commands"]["apply"]["shell"])
        self.assertIn("REALTIME_EVENT_GCS_PREFIX=gs://bucket/realtime-events", plan["commands"]["apply"]["shell"])
        self.assertIn("OPERATOR_ADMIN_TOKEN=operator-admin-token:latest", plan["commands"]["apply"]["shell"])
        self.assertIn("--max-instances 20", plan["commands"]["rollback"]["shell"])
        self.assertFalse(plan["apiKeyMaterialIncluded"])
        self.assertTrue(plan["secretReferencesIncluded"])
        self.assertFalse(plan["secretResourceNamesIncluded"])
        self.assertNotIn("projects/123/secrets", json.dumps(plan))

    def test_ready_config_marks_plan_already_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "config.json"
            data = failed_config_report()
            data["status"] = "ok"
            data["failedChecks"] = []
            data["cloudRun"]["maxInstances"] = 1
            data["cloudRun"]["configuredEnv"] = [
                "APP_TIMEZONE",
                "SERMON_ARTIFACT_BUCKET",
                "SERMON_ARTIFACT_PREFIX",
                "REALTIME_EVENT_GCS_PREFIX",
                "OPENAI_API_KEY_SECRET",
                "OPERATOR_ADMIN_TOKEN",
                "INTERNAL_TASK_TOKEN",
            ]
            report.write_text(json.dumps(data), encoding="utf-8")

            plan = mod.build_plan(args_for(report))

        self.assertEqual(plan["status"], "already_ready")
        self.assertFalse(plan["requiresExplicitApproval"])


def args_for(report: Path) -> Namespace:
    return Namespace(
        config_report=report,
        service="sermon-zh-caption-web",
        project="ai-for-god",
        region="us-west1",
        realtime_event_gcs_prefix="gs://bucket/realtime-events",
        operator_admin_secret="operator-admin-token",
        internal_task_secret="internal-task-token",
        out=None,
    )


def failed_config_report() -> dict:
    return {
        "schemaVersion": 1,
        "status": "failed",
        "failedChecks": [
            "single_instance_realtime_sse",
            "realtime_event_gcs_prefix",
            "operator_admin_token",
            "internal_task_token",
        ],
        "cloudRun": {
            "service": "sermon-zh-caption-web",
            "project": "ai-for-god",
            "region": "us-west1",
            "ready": True,
            "maxInstances": 20,
            "containerConcurrency": 80,
            "configuredEnv": [
                "APP_TIMEZONE",
                "OPENAI_API_KEY_SECRET",
                "SERMON_ARTIFACT_BUCKET",
                "SERMON_ARTIFACT_PREFIX",
            ],
        },
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


if __name__ == "__main__":
    unittest.main()
