import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import run_multilingual_cd as cd


class MultilingualCDTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.candidate = self.root / "candidate"
        self.candidate.mkdir()
        (self.candidate / "build-report.json").write_text(json.dumps({
            "schemaVersion": "sermon-multilingual-hosting-candidate-v1",
            "status": "validated_not_deployed"}))
        self.out = self.root / "receipts"

    def fake_command(self, *args):
        output = Path(args[args.index("--out") + 1])
        build_hash = cd.hosting.digest(self.candidate / "build-report.json")
        if "deploy_feedback.py" in args[0]:
            output.mkdir()
            output /= "deployment-receipt.json"
            receipt = {"status": ("deployed_verification_pending" if "--execute" in args
                                  else "prepared_not_deployed")}
        elif "--preflight-baseline" in args or args[1] == "preflight":
            receipt = {"status": "pass", "buildReportSha256": build_hash}
        elif "deploy_multilingual_hosting.py" in args[0] or args[1] == "deploy":
            preflight = Path(args[args.index("--preflight") + 1])
            receipt = {"status": ("deployed_http_verification_pending" if "--execute" in args
                                  else "validated_not_deployed"),
                       "buildReportSha256": build_hash,
                       "preflightSha256": cd.hosting.digest(preflight)}
        else:
            receipt = {"status": "pass", "buildReportSha256": build_hash}
        output.write_text(json.dumps(receipt))
        self.commands.append(args)

    def test_plan_checks_baseline_and_does_not_publish(self):
        self.commands = []
        with patch.object(cd, "run_command", side_effect=self.fake_command), \
             patch.object(cd, "git_value", return_value="a" * 40):
            result = cd.release("production", self.candidate, self.out, execute=False)
        self.assertEqual(result["status"], "validated_not_deployed")
        self.assertEqual(len(self.commands), 2)
        self.assertIn("--preflight-baseline", self.commands[0])
        self.assertNotIn("--execute", self.commands[1])
        self.assertFalse((self.out / "http-verification.json").exists())

    def test_execute_requires_exact_checkout_and_verifies_after_deploy(self):
        self.commands = []
        build_hash = cd.hosting.digest(self.candidate / "build-report.json")
        with patch.object(cd, "run_command", side_effect=self.fake_command), \
             patch.object(cd, "git_value", return_value="a" * 40), \
             patch.object(cd, "require_release_checkout", return_value="a" * 40):
            result = cd.release("production", self.candidate, self.out, execute=True,
                                expected_commit="a" * 40,
                                expected_build_report_sha256=build_hash)
        self.assertEqual(result["status"], "published_http_verified")
        self.assertEqual(len(self.commands), 3)
        self.assertIn("--execute", self.commands[1])
        self.assertTrue((self.out / "http-verification.json").exists())

    def test_bad_candidate_hash_stops_before_network_or_output(self):
        with self.assertRaisesRegex(ValueError, "build report changed"):
            cd.release("production", self.candidate, self.out, execute=True,
                       expected_commit="a" * 40,
                       expected_build_report_sha256="0" * 64)
        self.assertFalse(self.out.exists())

    def test_http_receipt_must_bind_the_candidate(self):
        self.commands = []
        build_hash = cd.hosting.digest(self.candidate / "build-report.json")

        def wrong_http(*args):
            self.fake_command(*args)
            if args[0].endswith("verify_multilingual_hosting.py") and "--preflight-baseline" not in args:
                Path(args[args.index("--out") + 1]).write_text(json.dumps({
                    "status": "pass", "buildReportSha256": "0" * 64}))

        with patch.object(cd, "run_command", side_effect=wrong_http), \
             patch.object(cd, "git_value", return_value="a" * 40), \
             patch.object(cd, "require_release_checkout", return_value="a" * 40):
            with self.assertRaisesRegex(ValueError, "HTTP verification did not confirm"):
                cd.release("production", self.candidate, self.out, execute=True,
                           expected_commit="a" * 40,
                           expected_build_report_sha256=build_hash)
        self.assertFalse((self.out / "cd-receipt.json").exists())

    def test_legacy_week_requires_bound_release_and_prepares_feedback_first(self):
        legacy = self.root / "legacy"
        legacy.mkdir()
        (legacy / "build-report.json").write_text("{}")
        (legacy / "feedback-catalog.json").write_text("{}")
        (self.candidate / "feedback-catalog.json").write_text("{}")
        report_path = self.candidate / "build-report.json"
        report = json.loads(report_path.read_text())
        report.update(legacyWeeklyReleaseBuildReportSha256=cd.hosting.digest(
            legacy / "build-report.json"), feedbackEnabled=True,
            feedbackCatalogSha256=cd.hosting.digest(legacy / "feedback-catalog.json"))
        report_path.write_text(json.dumps(report))
        with self.assertRaisesRegex(ValueError, "requires its bound release"):
            cd.release("production", self.candidate, self.out, execute=False)
        self.commands = []
        with patch.object(cd, "run_command", side_effect=self.fake_command), \
             patch.object(cd, "git_value", return_value="a" * 40):
            result = cd.release("production", self.candidate, self.out,
                                execute=False, legacy_release=legacy)
        self.assertEqual(result["feedbackDeploymentStatus"], "prepared_not_deployed")
        self.assertIn("deploy_feedback.py", self.commands[1][0])
        self.assertIn("deploy_multilingual_hosting.py", self.commands[2][0])


if __name__ == "__main__":
    unittest.main()
