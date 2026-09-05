"""Fault injection and correlation checks; no models or network are used."""
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from scripts import sermon_accounting as accounting


class LoggingReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.keys = (*accounting.ENV_KEYS, accounting.WORKFLOW_ENV)
        clean_env = {key: value for key, value in os.environ.items() if key not in self.keys}
        for mocked in (
            patch.dict(os.environ, clean_env, clear=True),
            patch.object(accounting, "execution_identity", return_value={}),
            patch.object(accounting, "_workflow_evidence", return_value={}),
        ):
            mocked.start()
            self.addCleanup(mocked.stop)
        self.variables = (accounting._identity, accounting._workflow, accounting._stage, accounting._span)
        for variable in self.variables:
            token = variable.set(None)
            self.addCleanup(variable.reset, token)

    def assert_context_clean(self):
        self.assertTrue(all(key not in os.environ for key in self.keys))
        self.assertEqual([variable.get() for variable in self.variables], [None] * 4)

    def test_independent_thread_sessions_keep_both_api_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_entered, second_entered, first_exited = (threading.Event() for _ in range(3))
            failures = []

            def first():
                try:
                    with accounting.accounting_session(root / "first", "first"):
                        accounting.record_api_attempt("gpt-transcribe", {"usage": {"seconds": 1}}, .1)
                        first_entered.set()
                        if not second_entered.wait(5):
                            raise AssertionError("second session did not enter")
                except BaseException as exc:
                    failures.append(exc)
                finally:
                    first_exited.set()

            def second():
                try:
                    if not first_entered.wait(5):
                        raise AssertionError("first session did not enter")
                    with accounting.accounting_session(root / "second", "second"):
                        second_entered.set()
                        if not first_exited.wait(5):
                            raise AssertionError("first session did not finish")
                        accounting.record_api_attempt("gpt-transcribe", {"usage": {"seconds": 2}}, .2)
                except BaseException as exc:
                    failures.append(exc)

            threads = [threading.Thread(target=target, daemon=True) for target in (first, second)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(10)
            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(failures, [])
            runs = [accounting.summarize(root / name)["runs"][0] for name in ("first", "second")]
            self.assertNotEqual(runs[0]["runId"], runs[1]["runId"])
            self.assertEqual([run["apiAttempts"] for run in runs], [1, 1])
            self.assertEqual([run["status"] for run in runs], ["completed", "completed"])
            self.assert_context_clean()

    def test_stage_write_failure_preserves_business_exception_and_cleans_context(self):
        original_emit = accounting._emit
        original_error = ValueError("PRIVATE_BUSINESS_BODY")

        def emit(event):
            if event["event"] == "stage_finished" and event["stage"] == "work":
                raise OSError("PRIVATE_DISK_BODY")
            return original_emit(event)

        with tempfile.TemporaryDirectory() as tmp, patch.object(accounting, "_emit", side_effect=emit), patch("sys.stderr", new_callable=io.StringIO) as stderr:
            with self.assertRaises(ValueError) as caught:
                with accounting.accounting_session(tmp, "fixture"):
                    with accounting.stage("work"):
                        raise original_error
            self.assertIs(caught.exception, original_error)
            self.assertIn("SERMON_LOGGING_WRITE_FAILED", stderr.getvalue())
            self.assertNotIn("PRIVATE", stderr.getvalue())
            self.assert_context_clean()

    def test_session_setup_and_finalize_failures_restore_environment(self):
        for target in ("run_started", "workflow_finished"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as tmp:
                original_emit = accounting._emit

                def emit(event):
                    if event["event"] == target:
                        raise OSError("PRIVATE_WRITE_BODY")
                    return original_emit(event)

                with patch.object(accounting, "_emit", side_effect=emit), patch("sys.stderr", new_callable=io.StringIO):
                    with self.assertRaises(OSError):
                        with accounting.accounting_session(tmp, "fixture"):
                            pass
                self.assert_context_clean()

    def test_finalize_failure_does_not_replace_original_failure(self):
        original_emit = accounting._emit
        original_error = RuntimeError("PRIVATE_PROCESS_BODY")

        def emit(event):
            if event["event"] == "workflow_finished":
                raise OSError("PRIVATE_WRITE_BODY")
            return original_emit(event)

        with tempfile.TemporaryDirectory() as tmp, patch.object(accounting, "_emit", side_effect=emit), patch("sys.stderr", new_callable=io.StringIO):
            with self.assertRaises(RuntimeError) as caught:
                with accounting.accounting_session(tmp, "fixture"):
                    raise original_error
            self.assertIs(caught.exception, original_error)
            self.assert_context_clean()

    def test_nested_setup_failure_restores_existing_parent_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            with accounting.accounting_session(tmp, "parent"):
                before_env = {key: os.environ.get(key) for key in self.keys}
                before_context = [variable.get() for variable in self.variables]
                original_emit = accounting._emit

                def emit(event):
                    if event["event"] == "workflow_started" and event["workflow"] == "child":
                        raise OSError("PRIVATE_SETUP_BODY")
                    return original_emit(event)

                with patch.object(accounting, "_emit", side_effect=emit):
                    with self.assertRaises(OSError):
                        with accounting.accounting_session(tmp, "child"):
                            self.fail("failed setup must not execute the body")
                self.assertEqual({key: os.environ.get(key) for key in self.keys}, before_env)
                self.assertEqual([variable.get() for variable in self.variables], before_context)
                accounting.record_log("parent.continues")
            self.assert_context_clean()

    def test_metadata_settings_and_log_drop_sensitive_bodies(self):
        marker = "PRIVATE_BODY bearer credential sermon transcript"
        with tempfile.TemporaryDirectory() as tmp:
            with accounting.accounting_session(tmp, "privacy", {"week": "2026-09-06", "sourceVideoSha256": "a" * 64, "api_key": marker, "prompt": marker}):
                attempt = accounting.record_api_started("gpt-transcribe", {"reasoning_effort": "medium", "prompt": marker, "authorization": marker})
                accounting.record_api_attempt("gpt-transcribe", {"usage": {"seconds": 1}}, .1, attempt_id=attempt)
                try:
                    raise RuntimeError(marker)
                except RuntimeError as exc:
                    accounting.record_log("fixture.failed", level="ERROR", fields={"count": 1, "message": marker, "command": marker, "status": marker}, exception=exc)
            for path in Path(tmp).iterdir():
                if path.is_file():
                    self.assertNotIn(marker.encode(), path.read_bytes(), path.name)
            events, damaged = accounting.read_events(tmp)
            self.assertEqual(damaged, [])
            self.assertEqual(next(event for event in events if event["event"] == "run_started")["metadata"], {"week": "2026-09-06", "sourceVideoSha256": "a" * 64})
            started = next(event for event in events if event["event"] == "api_attempt_started")
            self.assertEqual(started["settings"], {"reasoning_effort": "medium"})
            log = next(event for event in events if event["event"] == "log")
            self.assertEqual(log["fields"], {"count": 1})
            self.assertEqual(log["error"]["errorType"], "RuntimeError")
            self.assertTrue(log["error"]["frames"])

    def test_bad_json_schema_is_reported_without_losing_valid_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            with accounting.accounting_session(tmp, "valid"):
                pass
            path = Path(tmp) / "events.jsonl"
            bad = {"schemaVersion": accounting.SCHEMA, "event": "stage_started", "eventId": "malformed", "runId": "other", "recordedAt": accounting.now()}
            missing_billing = {**bad, "event": "stage_finished", "eventId": "missing-billing", "stage": "work", "spanId": "span", "status": "completed", "cacheHit": False, "elapsedSeconds": 1.0}
            with path.open("a") as stream:
                for event in (bad, missing_billing):
                    stream.write(json.dumps(event) + "\n")
            before = path.read_bytes()
            result = accounting.summarize(tmp)
            self.assertEqual(result["ledgerIntegrity"]["status"], "incomplete_corrupt_events")
            self.assertEqual(len(result["ledgerIntegrity"]["damagedEvents"]), 2)
            self.assertEqual(result["runs"][0]["status"], "completed")
            self.assertEqual(path.read_bytes(), before)

    def test_new_ledger_and_projections_are_private_even_under_open_umask(self):
        old_umask = os.umask(0)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp) / "private"
                with accounting.accounting_session(directory, "permissions"):
                    accounting.record_log("fixture.ready")
                files = list(directory.iterdir())
                self.assertIn("events.jsonl", {path.name for path in files})
                self.assertIn("summary.json", {path.name for path in files})
                self.assertIn("stages.csv", {path.name for path in files})
                for path in files:
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600, path.name)
                self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
        finally:
            os.umask(old_umask)

    def test_nested_and_subprocess_workflows_preserve_parent_and_run_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            with accounting.accounting_session(tmp, "parent") as parent:
                with accounting.accounting_session(Path(tmp) / "ignored-child-directory", "nested") as nested:
                    accounting.record_log("nested.ready")
                self.assertEqual(os.environ[accounting.WORKFLOW_ENV], parent["workflowId"])
                code = (
                    "from scripts.sermon_accounting import accounting_session,record_log\n"
                    "with accounting_session('unused-inherited-directory', 'subprocess'):\n"
                    " record_log('subprocess.ready')\n"
                )
                subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1], check=True, capture_output=True, text=True, timeout=15)
            events, damaged = accounting.read_events(tmp)
            self.assertEqual(damaged, [])
            started = {event["workflow"]: event for event in events if event["event"] == "workflow_started"}
            self.assertEqual(set(started), {"parent", "nested", "subprocess"})
            self.assertEqual(len({event["runId"] for event in started.values()}), 1)
            self.assertIsNone(started["parent"]["parentWorkflowId"])
            for name in ("nested", "subprocess"):
                self.assertEqual(started[name]["parentWorkflowId"], parent["workflowId"])
                self.assertNotEqual(started[name]["workflowId"], parent["workflowId"])
            self.assertEqual(nested["runId"], parent["runId"])
            for event in events:
                if event["event"] == "log":
                    name = event["code"].split(".")[0]
                    self.assertEqual(event["workflowId"], started[name]["workflowId"])
                    self.assertTrue(event["spanId"])
            self.assert_context_clean()


if __name__ == "__main__":
    unittest.main()
