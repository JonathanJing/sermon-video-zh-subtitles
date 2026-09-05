import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import sermon_accounting as accounting
from scripts import sermon_logs


class LogViewerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / "accounting"
        env = patch.dict(os.environ, {k: "" for k in (*accounting.ENV_KEYS, accounting.WORKFLOW_ENV)})
        env.start()
        self.addCleanup(env.stop)

    def invoke(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            code = sermon_logs.main([str(self.directory), *args])
        return code, output.getvalue()

    def test_latest_run_filter_is_read_only_and_previous_failure_remains(self):
        with self.assertRaises(ValueError), accounting.accounting_session(self.directory, "failed"):
            raise ValueError("private-exception-body")
        with accounting.accounting_session(self.directory, "resumed") as session:
            accounting.record_log("cache_verified", fields={"cacheHit": True})
        before = {p.name: p.read_bytes() for p in self.directory.iterdir()}
        code, output = self.invoke("--check", "--json")
        result = json.loads(output)
        self.assertEqual(code, 0)
        self.assertEqual(result["runId"], session["runId"])
        self.assertEqual(result["errorEvents"], 0)
        self.assertEqual(self.invoke("--run-id", "all", "--check")[0], 2)
        after = {p.name: p.read_bytes() for p in self.directory.iterdir()}
        self.assertEqual(before, after)
        self.assertNotIn("private-exception-body", output)

    def test_level_tail_and_safe_failure_location(self):
        with accounting.accounting_session(self.directory, "fixture"):
            for _ in range(3):
                accounting.record_log("retry_scheduled", level="WARNING", fields={"httpStatus": 429})
            try:
                raise RuntimeError("Authorization: Bearer private-secret")
            except RuntimeError as exc:
                accounting.record_log("request_failed", level="ERROR", exception=exc)
        code, output = self.invoke("--level", "WARNING", "--tail", "2", "--json", "--check")
        result = json.loads(output)
        self.assertEqual(code, 2)
        self.assertEqual(result["matchingEvents"], 4)
        self.assertEqual(len(result["events"]), 2)
        self.assertEqual(result["events"][-1]["frames"][-1]["file"], "tests/test_sermon_logs.py")
        self.assertNotIn("private-secret", output)
        self.assertNotIn("private-secret", (self.directory / "operations.log").read_text())

    def test_incomplete_call_is_not_reported_as_success(self):
        with accounting.accounting_session(self.directory, "fixture"):
            accounting.record_api_started("gpt-6-astra")
        code, output = self.invoke("--check", "--json")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output)["unfinished"][0]["event"], "api_attempt_started")

    def test_corrupt_ledger_is_reported_without_body(self):
        with accounting.accounting_session(self.directory, "fixture"):
            pass
        with (self.directory / "events.jsonl").open("a") as stream:
            stream.write('{"private":"truncated')
        code, output = self.invoke("--check", "--json")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output)["ledgerIntegrity"], "incomplete_corrupt_events")
        self.assertNotIn("truncated", output)

    def test_unavailable_and_unknown_run_have_explicit_exit_status(self):
        self.assertEqual(self.invoke("--check")[0], 3)
        with accounting.accounting_session(self.directory, "fixture"):
            pass
        self.assertEqual(self.invoke("--run-id", "absent", "--check")[0], 3)


if __name__ == "__main__":
    unittest.main()
