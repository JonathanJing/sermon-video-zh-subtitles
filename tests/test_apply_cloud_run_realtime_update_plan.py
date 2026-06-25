import json
import os
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import scripts.apply_cloud_run_realtime_update_plan as mod


class ApplyCloudRunRealtimeUpdatePlanTest(unittest.TestCase):
    def test_dry_run_does_not_execute_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = write_plan(Path(tmp))
            with patch.object(mod.subprocess, "run") as run:
                report = mod.apply_plan(args_for(plan, approve=False))

        self.assertEqual(report["status"], "dry_run")
        run.assert_not_called()
        self.assertIn("sermon-zh-caption-web", report["wouldApply"])
        self.assertEqual(report["requiredRuntimeEnv"], ["INTERNAL_TASK_TOKEN"])
        self.assertEqual(report["missingRuntimeEnv"], ["INTERNAL_TASK_TOKEN"])
        self.assertFalse(report["eventTokenIncluded"])
        self.assertFalse(report["secretReferencesIncluded"])

    def test_dry_run_accepts_secret_manager_runtime_token_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = write_plan(Path(tmp), include_update_secret=True)
            with patch.object(mod.subprocess, "run") as run:
                with patch.dict(os.environ, {}, clear=True):
                    report = mod.apply_plan(args_for(plan, approve=False))

        self.assertEqual(report["status"], "dry_run")
        self.assertEqual(report["missingRuntimeEnv"], [])
        self.assertEqual(report["runtimeTokenSources"], {"INTERNAL_TASK_TOKEN": "secret_manager"})
        run.assert_not_called()

    def test_approved_run_executes_apply_and_validations_with_token_redacted(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = write_plan(Path(tmp))
            calls = []

            def fake_run(command, **kwargs):
                calls.append(command)
                return completed(0, stdout="ok")

            with patch.object(mod.subprocess, "run", side_effect=fake_run):
                with patch.dict(os.environ, {"INTERNAL_TASK_TOKEN": "x" * 40}):
                    report = mod.apply_plan(args_for(plan, approve=True))

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["requiredRuntimeEnv"], ["INTERNAL_TASK_TOKEN"])
        self.assertEqual(report["missingRuntimeEnv"], [])
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[2][-4], "--internal-task-token")
        self.assertEqual(calls[2][-3], "x" * 40)
        serialized = json.dumps(report)
        self.assertNotIn("x" * 40, serialized)
        self.assertIn("<redacted-runtime-token>", serialized)

    def test_approved_run_can_read_validation_token_from_secret_manager(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = write_plan(Path(tmp), include_update_secret=True)
            calls = []

            def fake_run(command, **kwargs):
                calls.append(command)
                if command[:4] == ["gcloud", "secrets", "versions", "access"]:
                    return completed(0, stdout="secret-token\n")
                return completed(0, stdout="ok")

            with patch.object(mod.subprocess, "run", side_effect=fake_run):
                with patch.dict(os.environ, {}, clear=True):
                    report = mod.apply_plan(args_for(plan, approve=True))

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["missingRuntimeEnv"], [])
        self.assertEqual(report["runtimeTokenSources"], {"INTERNAL_TASK_TOKEN": "secret_manager"})
        self.assertEqual(len(calls), 4)
        self.assertEqual(calls[0][:4], ["gcloud", "secrets", "versions", "access"])
        self.assertEqual(calls[3][-4], "--internal-task-token")
        self.assertEqual(calls[3][-3], "secret-token")
        serialized = json.dumps(report)
        self.assertNotIn("secret-token", serialized)
        self.assertNotIn("internal-task-token:latest", serialized)
        self.assertNotIn("INTERNAL_TASK_TOKEN=internal-task-token", serialized)
        self.assertFalse(report["secretReferencesIncluded"])

    def test_validation_failure_can_run_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = write_plan(Path(tmp))
            outcomes = [completed(0, stdout="apply"), completed(2, stderr="bad"), completed(0, stdout="rolled back")]

            with patch.object(mod.subprocess, "run", side_effect=outcomes):
                with patch.dict(os.environ, {"INTERNAL_TASK_TOKEN": "x" * 40}):
                    report = mod.apply_plan(
                        args_for(plan, approve=True, rollback_on_failure=True)
                    )

        self.assertEqual(report["status"], "validation_failed")
        self.assertEqual(report["rollback"]["status"], "ok")
        self.assertEqual(report["validation"][0]["returncode"], 2)

    def test_missing_internal_task_token_stops_before_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = write_plan(Path(tmp))
            with patch.object(mod.subprocess, "run") as run:
                with patch.dict(os.environ, {}, clear=True):
                    report = mod.apply_plan(args_for(plan, approve=True))

        self.assertEqual(report["status"], "missing_runtime_env")
        self.assertEqual(report["missingRuntimeEnv"], ["INTERNAL_TASK_TOKEN"])
        self.assertIsNone(report["apply"])
        run.assert_not_called()


def args_for(plan: Path, *, approve: bool, rollback_on_failure=False):
    return Namespace(
        plan=plan,
        approve=approve,
        rollback_on_failure=rollback_on_failure,
        skip_validation=False,
        out=None,
    )


def write_plan(root: Path, *, include_update_secret=False) -> Path:
    apply_argv = [
        "gcloud",
        "run",
        "services",
        "update",
        "sermon-zh-caption-web",
        "--project",
        "ai-for-god",
        "--max-instances",
        "1",
    ]
    if include_update_secret:
        apply_argv.extend(
            [
                "--update-secrets",
                "INTERNAL_TASK_TOKEN=internal-task-token:latest",
            ]
        )
    plan = {
        "schemaVersion": 1,
        "commands": {
            "apply": {
                "argv": apply_argv
            },
            "rollback": {
                "argv": [
                    "gcloud",
                    "run",
                    "services",
                    "update",
                    "sermon-zh-caption-web",
                    "--max-instances",
                    "20",
                ]
            },
            "validate": [
                {
                    "argv": [
                        "python3",
                        "scripts/validate_cloud_run_realtime_config.py",
                        "--service",
                        "sermon-zh-caption-web",
                    ]
                },
                {
                    "argv": [
                        "python3",
                        "scripts/run_cloud_run_realtime_preflight.py",
                        "--internal-task-token",
                        "$INTERNAL_TASK_TOKEN",
                        "--out",
                        "artifacts/evidence/cloud-run-api-preflight.json",
                    ]
                },
            ],
        },
        "postApplyEvidence": ["artifacts/evidence/cloud-run-realtime-config.json"],
    }
    path = root / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    return path


def completed(returncode, stdout="", stderr=""):
    class Completed:
        pass

    item = Completed()
    item.returncode = returncode
    item.stdout = stdout
    item.stderr = stderr
    return item


if __name__ == "__main__":
    unittest.main()
