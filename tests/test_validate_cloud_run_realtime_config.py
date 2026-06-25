import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import scripts.validate_cloud_run_realtime_config as mod


class ValidateCloudRunRealtimeConfigTest(unittest.TestCase):
    def test_accepts_single_instance_realtime_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            service_path = Path(tmp) / "service.json"
            service_path.write_text(json.dumps(service_fixture()), encoding="utf-8")

            report = mod.validate_cloud_run_realtime_config(
                Namespace(
                    service_json=service_path,
                    service=None,
                    project=None,
                    region=None,
                    allow_multi_instance=False,
                    out=None,
                )
            )

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["failedChecks"], [])
        self.assertEqual(report["cloudRun"]["maxInstances"], 1)
        self.assertIn("REALTIME_EVENT_GCS_PREFIX", report["cloudRun"]["configuredEnv"])
        self.assertFalse(report["apiKeyMaterialIncluded"])
        self.assertFalse(report["secretResourceNamesIncluded"])
        self.assertNotIn("projects/123/secrets", json.dumps(report))

    def test_rejects_multi_instance_without_explicit_override(self):
        fixture = service_fixture()
        fixture["spec"]["template"]["metadata"]["annotations"]["autoscaling.knative.dev/maxScale"] = "20"
        report = report_for(fixture)

        self.assertEqual(report["status"], "failed")
        self.assertIn("single_instance_realtime_sse", report["failedChecks"])

    def test_rejects_missing_realtime_gcs_prefix(self):
        fixture = service_fixture()
        fixture["spec"]["template"]["spec"]["containers"][0]["env"] = [
            item
            for item in fixture["spec"]["template"]["spec"]["containers"][0]["env"]
            if item["name"] != "REALTIME_EVENT_GCS_PREFIX"
        ]
        report = report_for(fixture)

        self.assertEqual(report["status"], "failed")
        self.assertIn("realtime_event_gcs_prefix", report["failedChecks"])

    def test_rejects_direct_secret_env_values(self):
        fixture = service_fixture()
        fixture["spec"]["template"]["spec"]["containers"][0]["env"].append(
            {"name": "OPERATOR_ADMIN_TOKEN", "value": "raw-token"}
        )
        report = report_for(fixture)

        self.assertEqual(report["status"], "failed")
        self.assertIn("no_direct_secret_env_values", report["failedChecks"])

    def test_supports_cloud_run_v2_shape(self):
        fixture = {
            "name": "projects/p/locations/us-west1/services/sermon-zh-caption-web",
            "template": {
                "scaling": {"maxInstanceCount": 1},
                "maxInstanceRequestConcurrency": 80,
                "containers": [
                    {
                        "env": [
                            {"name": "APP_TIMEZONE", "value": "America/Los_Angeles"},
                            {"name": "SERMON_ARTIFACT_BUCKET", "value": "bucket"},
                            {"name": "SERMON_ARTIFACT_PREFIX", "value": "sundays"},
                            {
                                "name": "REALTIME_EVENT_GCS_PREFIX",
                                "value": "gs://bucket/realtime-events",
                            },
                            {
                                "name": "OPENAI_API_KEY",
                                "valueSource": {"secretKeyRef": {"secret": "openai-api-key"}},
                            },
                            {
                                "name": "OPERATOR_ADMIN_TOKEN",
                                "valueSource": {"secretKeyRef": {"secret": "operator-admin-token"}},
                            },
                            {
                                "name": "INTERNAL_TASK_TOKEN",
                                "valueSource": {"secretKeyRef": {"secret": "internal-task-token"}},
                            },
                        ]
                    }
                ],
            },
            "status": {"conditions": [{"type": "Ready", "status": "True"}]},
        }

        report = report_for(fixture)

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["cloudRun"]["maxInstances"], 1)
        self.assertEqual(report["cloudRun"]["containerConcurrency"], 80)

    def test_wrong_json_shape_fails_without_traceback(self):
        report = report_for({"schemaVersion": 1, "status": "failed", "checks": []})

        self.assertEqual(report["status"], "failed")
        self.assertIn("realtime_event_gcs_prefix", report["failedChecks"])


def report_for(fixture):
    with tempfile.TemporaryDirectory() as tmp:
        service_path = Path(tmp) / "service.json"
        service_path.write_text(json.dumps(fixture), encoding="utf-8")
        return mod.validate_cloud_run_realtime_config(
            Namespace(
                service_json=service_path,
                service=None,
                project=None,
                region=None,
                allow_multi_instance=False,
                out=None,
            )
        )


def service_fixture():
    return {
        "metadata": {"name": "sermon-zh-caption-web"},
        "spec": {
            "template": {
                "metadata": {"annotations": {"autoscaling.knative.dev/maxScale": "1"}},
                "spec": {
                    "containerConcurrency": 80,
                    "containers": [
                        {
                            "env": [
                                {"name": "APP_TIMEZONE", "value": "America/Los_Angeles"},
                                {"name": "SERMON_ARTIFACT_BUCKET", "value": "sermon-zh-artifacts-ai-for-god"},
                                {"name": "SERMON_ARTIFACT_PREFIX", "value": "sundays"},
                                {
                                    "name": "REALTIME_EVENT_GCS_PREFIX",
                                    "value": "gs://sermon-zh-artifacts-ai-for-god/realtime-events",
                                },
                                {
                                    "name": "OPENAI_API_KEY_SECRET",
                                    "value": "projects/123/secrets/openai-api-key/versions/latest",
                                },
                                {
                                    "name": "OPERATOR_ADMIN_TOKEN",
                                    "valueFrom": {"secretKeyRef": {"name": "operator-admin-token"}},
                                },
                                {
                                    "name": "INTERNAL_TASK_TOKEN",
                                    "valueFrom": {"secretKeyRef": {"name": "internal-task-token"}},
                                },
                            ]
                        }
                    ],
                },
            }
        },
        "status": {"conditions": [{"type": "Ready", "status": "True"}]},
    }


if __name__ == "__main__":
    unittest.main()
