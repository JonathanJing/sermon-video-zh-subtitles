"""plan_run_budgets.py writes bound budget files from the run profile; check_run_start.py reads only."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import check_run_start as check
from scripts import plan_run_budgets as plan


def run_plan(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = plan.main(list(args))
    return code, out.getvalue()


class PlanTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name)

    def test_schedule_says_whether_stages_may_run_together(self):
        stages = [{"capUsd": 4.5}, {"capUsd": 3.5}, {"capUsd": 3.5}]
        self.assertEqual(plan.schedule(stages, total=20, settled=7)["mode"], "all_stages_may_run_together")
        self.assertEqual(plan.schedule(stages, total=20, settled=10.3)["mode"], "one_stage_at_a_time")
        self.assertEqual(plan.schedule(stages, total=12, settled=10.3)["mode"], "does_not_fit")

    def test_qc_roots_are_one_per_locale_and_bind_their_approval_and_reuse_roots(self):
        code, _ = run_plan("--out", str(self.base / "run"), "--scale", "clip", "--locales", "ko,es",
                           "--total-usd", "20", "--approved-by", "Jony", "--evidence", "chat 2026-10-13")
        self.assertEqual(code, 0)
        written = json.loads((self.base / "run/plan.json").read_text())
        self.assertEqual([stage["stage"] for stage in written["stages"]], ["qc.ko", "qc.es"])
        for locale in ("ko", "es"):
            folder = self.base / "run" / f"qc-{locale}"
            authorization = json.loads((folder / "api-budget-authorization.json").read_text())
            approval_path = folder / authorization["approvalReceipt"]
            approval = json.loads(approval_path.read_text())
            self.assertEqual(authorization["authority"]["approvalSha256"], hashlib.sha256(approval_path.read_bytes()).hexdigest())
            self.assertEqual(approval["binding"], {"budgetRoot": authorization["budgetRoot"], **authorization["authority"]["bounds"]})
            self.assertEqual(approval["binding"]["globalBounds"]["costMicrousd"], 3_500_000)
            self.assertEqual((approval["reviewedBy"], approval["operatorEvidence"]), ("Jony", "chat 2026-10-13"))
        # A second plan of the same run names the first plan's roots for reuse, in both files.
        code, _ = run_plan("--out", str(self.base / "run-2"), "--scale", "clip", "--locales", "ko",
                           "--total-usd", "20", "--settled-usd", "1", "--approved-by", "Jony", "--evidence", "chat",
                           "--reuse-from", str(self.base / "run"))
        self.assertEqual(code, 0)
        authorization = json.loads((self.base / "run-2/qc-ko/api-budget-authorization.json").read_text())
        approval = json.loads((self.base / "run-2/qc-ko/api-budget-approval.json").read_text())
        reuse = [str((self.base / "run/qc-ko/.api-budget").resolve())]
        self.assertEqual(authorization["reuseBudgetRoots"], reuse)
        self.assertEqual(approval["binding"]["reuseBudgetRoots"], reuse)

    def test_nothing_is_written_without_a_named_approval_or_when_one_stage_cannot_fit(self):
        with self.assertRaises(SystemExit):
            run_plan("--out", str(self.base / "a"), "--scale", "clip", "--total-usd", "20",
                     "--approved-by", " ", "--evidence", "chat")
        code, output = run_plan("--out", str(self.base / "b"), "--scale", "week", "--total-usd", "20",
                                "--approved-by", "Jony", "--evidence", "chat")
        self.assertEqual((code, json.loads(output)["mode"]), (1, "does_not_fit"))
        self.assertFalse((self.base / "a").exists() or (self.base / "b").exists())

    def test_a_plan_never_overwrites_an_existing_directory(self):
        (self.base / "used").mkdir(); (self.base / "used" / "x").write_text("x")
        with self.assertRaises(SystemExit):
            run_plan("--out", str(self.base / "used"), "--scale", "clip", "--total-usd", "20",
                     "--approved-by", "Jony", "--evidence", "chat")


class StartCheckTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name)
        with contextlib.redirect_stdout(io.StringIO()):
            plan.main(["--out", str(self.base / "run"), "--scale", "clip", "--locales", "ko", "--total-usd", "20",
                       "--approved-by", "Jony", "--evidence", "chat"])

    def test_an_intact_plan_passes_and_a_changed_approval_fails(self):
        self.assertEqual(check.check_budget(self.base / "run")["status"], "pass")
        approval = self.base / "run/qc-ko/api-budget-approval.json"
        approval.write_text(approval.read_text().replace("chat", "edited"))
        self.assertEqual(check.check_budget(self.base / "run")["status"], "fail")

    def test_a_root_already_used_by_another_approval_fails(self):
        root = Path(json.loads((self.base / "run/plan.json").read_text())["stages"][0]["budgetRoot"])
        root.mkdir(parents=True)
        (root / "source-budget.json").write_text(json.dumps({"authority": {"approvalSha256": "f" * 64}}))
        result = check.check_budget(self.base / "run")
        self.assertEqual(result["status"], "fail")
        self.assertIn("another approval", result["problems"][0])

    def test_fresh_dirs_must_be_new_or_empty(self):
        (self.base / "empty").mkdir()
        self.assertEqual(check.check_fresh([self.base / "new", self.base / "empty"])["status"], "pass")
        self.assertEqual(check.check_fresh([self.base / "run"])["status"], "fail")

    def test_a_page_id_already_live_fails(self):
        catalogs = {"multilingual-v3.json": {"pages": [{"id": "week"}]},
                    "multilingual-v4.json": {"pages": [{"id": "week"}, {"id": "mockup-taken"}]}}
        def fake(request, timeout):
            return contextlib.nullcontext(io.BytesIO(json.dumps(catalogs[request.full_url.rsplit("/", 1)[1]]).encode()))
        with mock.patch.object(check, "urlopen", fake):
            self.assertEqual(check.check_page("mockup-new", "https://example.invalid")["status"], "pass")
            taken = check.check_page("mockup-taken", "https://example.invalid")
        self.assertEqual(taken["status"], "fail")
        self.assertEqual(taken["problems"], ["mockup-taken already in multilingual-v4.json"])

    def test_api_only_runs_need_no_spark_session(self):
        with mock.patch.object(check, "ssh", return_value=mock.Mock(returncode=0, stdout="spark")), \
             mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(check.check_spark("host", False, None)["session"], "not_required_api_only")
            gpu = check.check_spark("host", True, None)
        self.assertEqual(gpu["status"], "fail")
        self.assertIn("SPARK_EXCLUSIVE_SESSION_ID", gpu["problems"][0])


if __name__ == "__main__":
    unittest.main()
