import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import scripts.plan_gcs_sunday_manifest_publish as mod
from tests.test_build_local_sunday_manifest_evidence import write_source_run
import scripts.build_local_sunday_manifest_evidence as local_builder


class PlanGcsSundayManifestPublishTest(unittest.TestCase):
    def test_plans_gcs_publish_from_local_contract_without_applying(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            local_root = root / "local"
            write_source_run(source)
            local_builder.build_local_sunday_manifest_evidence(
                sunday="2026-06-28",
                source_run_root=source,
                source_manifest=None,
                out_root=local_root,
                validation_out=None,
            )

            report = mod.build_publish_plan(
                sunday="2026-06-28",
                local_root=local_root,
                bucket="gs://sermon-zh-artifacts-ai-for-god",
                prefix="sundays",
                session_id="contract test",
                apply=False,
            )

        self.assertEqual(report["status"], "planned")
        self.assertEqual(report["artifactLocation"], "gcs")
        self.assertEqual(report["sessionId"], "contract-test")
        self.assertEqual(report["localValidation"]["status"], "ok")
        self.assertFalse(report["localValidation"]["publicGcsArtifacts"])
        self.assertTrue(report["gcsManifestValidation"]["publicGcsArtifacts"])
        self.assertEqual(
            report["stableManifestUri"],
            "gs://sermon-zh-artifacts-ai-for-god/sundays/2026-06-28/cloud-manifest.json",
        )
        self.assertEqual(len(report["artifacts"]), 3)
        self.assertIn("validate_sunday_manifest.py", " ".join(report["commands"][-1]))
        self.assertFalse(report["apiKeyMaterialIncluded"])
        self.assertFalse(report["secretResourceNamesIncluded"])

    def test_apply_runs_artifact_and_manifest_upload_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            local_root = root / "local"
            write_source_run(source)
            local_builder.build_local_sunday_manifest_evidence(
                sunday="2026-06-28",
                source_run_root=source,
                source_manifest=None,
                out_root=local_root,
                validation_out=None,
            )

            with mock.patch("scripts.plan_gcs_sunday_manifest_publish.subprocess.run") as run:
                run.return_value = type("Completed", (), {"returncode": 0})()
                report = mod.build_publish_plan(
                    sunday="2026-06-28",
                    local_root=local_root,
                    bucket="sermon-zh-artifacts-ai-for-god",
                    prefix="sundays",
                    session_id="contract",
                    apply=True,
                )

        self.assertEqual(report["status"], "applied")
        self.assertEqual(run.call_count, 5)
        self.assertEqual(len(report["appliedSteps"]), 5)
        self.assertTrue(all(step["returnCode"] == 0 for step in report["appliedSteps"]))

    def test_parse_args_requires_confirmation_for_production_stable_apply(self):
        argv = [
            "plan_gcs_sunday_manifest_publish.py",
            "--sunday",
            "2026-06-28",
            "--bucket",
            "sermon-zh-artifacts-ai-for-god",
            "--prefix",
            "sundays",
            "--apply",
        ]

        with mock.patch("sys.argv", argv):
            with self.assertRaises(SystemExit) as exc:
                mod.parse_args()

        self.assertIn("--confirm-production-stable", str(exc.exception))

    def test_parse_args_allows_confirmed_production_stable_apply(self):
        argv = [
            "plan_gcs_sunday_manifest_publish.py",
            "--sunday",
            "2026-06-28",
            "--bucket",
            "sermon-zh-artifacts-ai-for-god",
            "--prefix",
            "sundays",
            "--apply",
            "--confirm-production-stable",
        ]

        with mock.patch("sys.argv", argv):
            args = mod.parse_args()

        self.assertTrue(args.apply)
        self.assertTrue(args.confirm_production_stable)

    def test_parse_args_allows_staging_apply_without_production_confirmation(self):
        argv = [
            "plan_gcs_sunday_manifest_publish.py",
            "--sunday",
            "2026-06-28",
            "--bucket",
            "sermon-zh-artifacts-ai-for-god",
            "--prefix",
            "staging/sundays",
            "--apply",
        ]

        with mock.patch("sys.argv", argv):
            args = mod.parse_args()

        self.assertTrue(args.apply)
        self.assertFalse(args.confirm_production_stable)

    def test_refuses_when_local_contract_is_not_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.mkdir(exist_ok=True)
            (root / "cloud-manifest.json").write_text(
                json.dumps(
                    {
                        "status": "ready",
                        "sunday": "2026-06-28",
                        "outputs": [],
                        "apiKeyMaterialIncluded": False,
                        "secretResourceNamesIncluded": False,
                    }
                ),
                encoding="utf-8",
            )

            report = mod.build_publish_plan(
                sunday="2026-06-28",
                local_root=root,
                bucket="sermon-zh-artifacts-ai-for-god",
                prefix="sundays",
                session_id="contract",
                apply=False,
            )

        self.assertEqual(report["status"], "failed")
        self.assertIn("Local Sunday manifest contract failed", report["message"])


if __name__ == "__main__":
    unittest.main()
