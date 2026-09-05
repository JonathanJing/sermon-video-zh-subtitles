"""Production entry logging without model, notification or production work."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from scripts import run_codex_local_sermon_production as local
from scripts import run_sermon_production_supervisor_agent as supervisor
from scripts import sermon_accounting as accounting


class ProductionLoggingTests(unittest.TestCase):
    week = "2026-09-06"

    def setUp(self):
        # Accounting's Git/resources implementations have their own tests.
        for mocked in [patch.object(accounting, "execution_identity", return_value={"gitCommit": None}),
                       patch.object(accounting, "resource_snapshot", return_value={}),
                       patch.object(local, "completed_production_report", return_value=None),
                       patch.object(local.live_source_monitor, "send_sendgrid_notification", side_effect=AssertionError("No notifications"))]:
            mocked.start()
            self.addCleanup(mocked.stop)

    def args(self, module, root, mode="shadow"):
        argv = ["entry.py", "--sunday", self.week, "--state-file", str(root / "source-state.json"),
            "--work-root", str(root / "runs"), "--out", str(root / "report.json"), "--mode", mode]
        with patch("sys.argv", argv):
            args = module.parse_args()
        if module is local:
            args.skip_source_refresh = True
        args.api_key_secret = None
        args.notify_sendgrid_secret = None
        args.notify_recipients_secret = None
        args.notify_sender_secret = None
        return args

    def ledger(self, root):
        path = root / "runs" / self.week / "accounting/events.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()]

    def call(self, module, args, result):
        with patch.object(module, "parse_args", return_value=args), patch.object(supervisor, "run_agent", new=AsyncMock(return_value=result)), redirect_stdout(io.StringIO()):
            return module.main()

    def test_both_entries_preserve_success_and_business_status(self):
        for module in (local, supervisor):
            with self.subTest(entry=module.__name__), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                args = self.args(module, root)
                report = {"status": "observed", "finalSnapshot": {"recommendedAction": {"action": "wait_for_source"}}}
                self.assertEqual(self.call(module, args, report), 0)
                rows = self.ledger(root)
                event = next(row for row in rows if row.get("code") == "production.entry_result")
                self.assertEqual(event["fields"]["status"], "waiting")
                self.assertEqual(event["fields"]["exitCode"], 0)
                self.assertEqual([row["status"] for row in rows if row["event"] == "workflow_finished"], ["completed"])
                self.assertEqual(json.loads(args.out.read_text())["status"], "observed")
                self.assertEqual(len({row["runId"] for row in rows}), 1)

    def test_both_nonzero_cli_returns_are_failed_executions_without_changing_report(self):
        for module in (local, supervisor):
            with self.subTest(entry=module.__name__), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                args = self.args(module, root, mode="execute")
                self.assertEqual(self.call(module, args, {"status": "blocked"}), 2)
                rows = self.ledger(root)
                self.assertEqual([row["status"] for row in rows if row["event"] == "workflow_finished"], ["failed"])
                self.assertEqual([row["status"] for row in rows if row["event"] == "run_finished"], ["failed"])
                outcome = next(row for row in rows if row.get("code") == "production.entry_result")
                self.assertEqual(outcome["fields"]["status"], "blocked")
                self.assertEqual(outcome["fields"]["exitCode"], 2)
                self.assertEqual(json.loads(args.out.read_text())["status"], "blocked")

    def test_optional_unrecognized_metadata_does_not_change_success_or_enter_log(self):
        for module in (local, supervisor):
            with self.subTest(entry=module.__name__), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                args = self.args(module, root)
                report = {"status": "complete", "finalSnapshot": "private-extra-metadata", "completionLatch": []}
                self.assertEqual(self.call(module, args, report), 0)
                rows = self.ledger(root)
                self.assertNotIn("private-extra-metadata", json.dumps(rows))
                result = next(row for row in rows if row.get("code") == "production.entry_result")
                self.assertFalse(result["fields"]["cacheHit"])

    def test_verified_completion_latch_is_logged_without_refresh_or_agent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = self.args(local, root, mode="execute")
            args.skip_source_refresh = False
            report = {"status": "complete", "completionLatch": {"status": "already_complete"}}
            with patch.object(local, "parse_args", return_value=args), patch.object(local, "completed_production_report", return_value=report), \
                    patch.object(local, "refresh_source_state") as refresh, patch.object(supervisor, "run_agent") as agent, redirect_stdout(io.StringIO()):
                self.assertEqual(local.main(), 0)
            refresh.assert_not_called()
            agent.assert_not_called()
            event = next(row for row in self.ledger(root) if row.get("code") == "production.entry_result")
            self.assertTrue(event["fields"]["cacheHit"])

    def test_explicit_failed_generation_resume_keeps_original_exit_mapping(self):
        for status, code in (("completed", 0), ("blocked", 2)):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                args = self.args(local, root, mode="execute")
                args.resume_failed_generation = True
                with patch.object(local, "parse_args", return_value=args), \
                        patch.object(local.sermon_production_supervisor, "resume_failed_reading_pdf_generation", return_value={"status": status}), \
                        patch.object(local.sermon_production_supervisor, "production_snapshot", return_value={}), \
                        patch.object(supervisor, "run_agent") as agent, redirect_stdout(io.StringIO()):
                    self.assertEqual(local.main(), code)
                agent.assert_not_called()
                rows = self.ledger(root)
                self.assertEqual(next(row for row in rows if row["event"] == "run_finished")["status"], "completed" if code == 0 else "failed")

    def test_uncaught_exception_is_rethrown_and_message_never_enters_ledger(self):
        for module in (local, supervisor):
            with self.subTest(entry=module.__name__), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                args = self.args(module, root)
                secret_body = "Bearer fixture-secret-and-private-sermon-body"
                original = RuntimeError(secret_body)
                with patch.object(module, "parse_args", return_value=args), patch.object(supervisor, "run_agent", new=AsyncMock(side_effect=original)):
                    with self.assertRaises(RuntimeError) as raised:
                        module.main()
                self.assertIs(raised.exception, original)
                rows = self.ledger(root)
                self.assertNotIn(secret_body, json.dumps(rows))
                error = next(row for row in rows if row.get("code") == "production.entry_exception")
                self.assertEqual(error["error"]["errorType"], "RuntimeError")
                self.assertTrue(error["error"]["frames"])
                self.assertEqual(next(row for row in rows if row["event"] == "run_finished")["status"], "failed")

    def test_caught_source_refresh_failure_has_separate_safe_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = self.args(local, root)
            args.skip_source_refresh = False
            message = "source access failed with private-token"
            with patch.object(local, "refresh_source_state", side_effect=RuntimeError(message)):
                self.assertEqual(self.call(local, args, {"status": "observed"}), 0)
            rows = self.ledger(root)
            self.assertNotIn(message, json.dumps(rows))
            event = next(row for row in rows if row.get("code") == "production.source_refresh_failed")
            self.assertEqual(event["level"], "ERROR")
            self.assertEqual(event["error"]["errorType"], "RuntimeError")
            # Preserve the pre-existing business-report behavior separately.
            self.assertEqual(json.loads(args.out.read_text())["sourceRefresh"]["reason"], message)
            self.assertEqual(next(row for row in rows if row["event"] == "run_finished")["status"], "completed")

    def test_failed_exception_logging_preserves_original_failure_and_safe_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = self.args(supervisor, root)
            original = RuntimeError("private original failure")
            warning = io.StringIO()
            with patch.object(supervisor, "parse_args", return_value=args), \
                    patch.object(supervisor, "run_agent", new=AsyncMock(side_effect=original)), \
                    patch.object(accounting, "record_log", side_effect=OSError("private log disk detail")), redirect_stderr(warning):
                with self.assertRaises(RuntimeError) as raised:
                    supervisor.main()
            self.assertIs(raised.exception, original)
            self.assertTrue(warning.getvalue())
            self.assertNotIn("private", warning.getvalue())
            self.assertEqual(next(row for row in self.ledger(root) if row["event"] == "run_finished")["status"], "failed")

    def test_report_write_failures_are_inside_both_entry_sessions(self):
        for module in (local, supervisor):
            with self.subTest(entry=module.__name__), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                args = self.args(module, root)
                args.out.mkdir()
                with self.assertRaises(IsADirectoryError):
                    self.call(module, args, {"status": "complete"})
                rows = self.ledger(root)
                self.assertEqual(next(row for row in rows if row["event"] == "run_finished")["status"], "failed")

    def test_approval_argument_failure_is_recorded_without_attempting_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = self.args(supervisor, root)
            args.approve_window = True
            with patch.object(supervisor, "parse_args", return_value=args), patch.object(supervisor.Runner, "run") as model:
                with self.assertRaises(SystemExit):
                    supervisor.main()
            model.assert_not_called()
            self.assertEqual(next(row for row in self.ledger(root) if row["event"] == "run_finished")["status"], "failed")

    def test_successful_supervisor_sdk_records_only_aggregate_numeric_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = self.args(supervisor, root)
            usage = {"requests": 2, "input_tokens": 300, "output_tokens": 80, "total_tokens": 380}
            result = SimpleNamespace(final_output={"status": "complete", "action": "complete", "summary_zh": "private SDK output"},
                context_wrapper=SimpleNamespace(usage=SimpleNamespace(**usage, request_usage_entries=["private provider body"])),
                raw_responses=["private model response"])
            with patch.object(supervisor, "parse_args", return_value=args), patch.object(supervisor, "build_agent", return_value=object()), \
                    patch.object(supervisor.Runner, "run", new=AsyncMock(return_value=result)) as sdk, \
                    patch.object(supervisor.sermon_production_supervisor, "production_snapshot", return_value={"recommendedAction": {"action": "complete"}}), \
                    redirect_stdout(io.StringIO()):
                self.assertEqual(supervisor.main(), 0)
            sdk.assert_awaited_once()
            rows = self.ledger(root)
            started = next(row for row in rows if row["event"] == "sdk_call_started")
            finished = next(row for row in rows if row["event"] == "sdk_call_finished")
            self.assertEqual(finished["usage"], usage)
            self.assertEqual(finished["invocationId"], started["invocationId"])
            self.assertEqual(finished["status"], "completed")
            self.assertEqual(finished["model"], args.model)
            self.assertEqual(finished["measurementScope"], "sdk_aggregate_including_tools")
            self.assertFalse(finished["httpAttemptsKnown"])
            self.assertIsNone(finished["estimatedUsd"])
            self.assertNotIn("private", json.dumps(rows))
            self.assertFalse(any(row["event"] == "api_attempt" for row in rows))
            summary = json.loads((root / "runs" / self.week / "accounting/summary.json").read_text())
            self.assertEqual(summary["runs"][0]["unpricedSdkInvocations"], 1)
            self.assertEqual(summary["runs"][0]["overallCostStatus"], "partial")

    def test_missing_or_non_numeric_sdk_usage_remains_unknown(self):
        wrappers = [None, SimpleNamespace(usage=SimpleNamespace(requests=True, input_tokens=-1, output_tokens=float("inf"), total_tokens="private-body"))]
        for wrapper in wrappers:
            with self.subTest(wrapper=wrapper), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                args = self.args(supervisor, root)
                result = SimpleNamespace(final_output={"status": "complete", "action": "complete"}, context_wrapper=wrapper)
                with patch.object(supervisor, "parse_args", return_value=args), patch.object(supervisor, "build_agent", return_value=object()), \
                        patch.object(supervisor.Runner, "run", new=AsyncMock(return_value=result)), \
                        patch.object(supervisor.sermon_production_supervisor, "production_snapshot", return_value={"recommendedAction": {"action": "complete"}}), \
                        redirect_stdout(io.StringIO()):
                    self.assertEqual(supervisor.main(), 0)
                finished = next(row for row in self.ledger(root) if row["event"] == "sdk_call_finished")
                self.assertEqual(finished["usage"], {key: None for key in ("requests", "input_tokens", "output_tokens", "total_tokens")})

    def test_failed_sdk_invocation_is_recorded_without_body_or_fabricated_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = self.args(supervisor, root)
            failure = RuntimeError("private SDK request failure")
            with patch.object(supervisor, "parse_args", return_value=args), patch.object(supervisor, "build_agent", return_value=object()), \
                    patch.object(supervisor.Runner, "run", new=AsyncMock(side_effect=failure)) as sdk, \
                    patch.object(supervisor.sermon_production_supervisor, "production_snapshot") as snapshot:
                with self.assertRaises(RuntimeError) as raised:
                    supervisor.main()
            self.assertIs(raised.exception, failure)
            sdk.assert_awaited_once()
            snapshot.assert_not_called()
            rows = self.ledger(root)
            finished = next(row for row in rows if row["event"] == "sdk_call_finished")
            self.assertEqual(finished["status"], "failed")
            self.assertTrue(all(value is None for value in finished["usage"].values()))
            self.assertEqual(finished["error"]["errorType"], "RuntimeError")
            self.assertNotIn("private", json.dumps(rows))
            self.assertEqual(next(row for row in rows if row["event"] == "run_finished")["status"], "failed")

    def test_inherited_parent_and_actual_local_child_share_run_and_workflow_links(self):
        child_code = """import json, sys
from scripts import sermon_accounting as accounting
accounting.execution_identity = lambda: {}
accounting.resource_snapshot = lambda directory: {}
with accounting.accounting_session(sys.argv[1], 'fixture_generation_child') as child:
    accounting.record_log('fixture.child_result', fields={'status': 'completed', 'exitCode': 0})
    print(json.dumps({'runId': child['runId'], 'workflowId': child['workflowId']}))
"""
        for module in (local, supervisor):
            with self.subTest(entry=module.__name__), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                args = self.args(module, root)
                child_ids = []
                async def fake_agent(_args):
                    completed = subprocess.run([sys.executable, "-c", child_code, str(root / "unused-child-directory")],
                        cwd=local.REPO_ROOT, check=True, capture_output=True, text=True)
                    child_ids.append(json.loads(completed.stdout))
                    return {"status": "complete"}
                before = {key: os.environ.get(key) for key in (*accounting.ENV_KEYS, accounting.WORKFLOW_ENV)}
                with accounting.accounting_session(root / "parent", "fixture_parent") as parent:
                    with patch.object(module, "parse_args", return_value=args), patch.object(supervisor, "run_agent", side_effect=fake_agent), redirect_stdout(io.StringIO()):
                        self.assertEqual(module.main(), 0)
                    self.assertEqual(os.environ["SERMON_ACCOUNTING_RUN_ID"], parent["runId"])
                    self.assertEqual(os.environ[accounting.WORKFLOW_ENV], parent["workflowId"])
                self.assertEqual({key: os.environ.get(key) for key in before}, before)
                rows = [json.loads(line) for line in (root / "parent/events.jsonl").read_text().splitlines()]
                starts = [row for row in rows if row["event"] == "workflow_started"]
                self.assertEqual(len(starts), 3)
                self.assertEqual(len({row["runId"] for row in rows}), 1)
                self.assertEqual(starts[1]["parentWorkflowId"], parent["workflowId"])
                self.assertEqual(starts[2]["parentWorkflowId"], starts[1]["workflowId"])
                self.assertEqual(child_ids[0]["runId"], parent["runId"])
                self.assertFalse((root / "unused-child-directory").exists())
                self.assertFalse((root / "runs" / self.week / "accounting").exists())


if __name__ == "__main__":
    unittest.main()
