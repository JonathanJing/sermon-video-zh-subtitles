"""A ledger write failure must never cause another paid request."""
import io
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

import requests

from scripts import generate_notes_with_openai as notes
from scripts import sermon_accounting as accounting
from scripts import sermon_pipeline as pipeline


class AccountingRetrySafetyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        clean = {key: value for key, value in os.environ.items()
                 if key not in (*accounting.ENV_KEYS, accounting.WORKFLOW_ENV)}
        clean.update(SERMON_ACCOUNTING_DIR=self.directory.name,
                     SERMON_ACCOUNTING_RUN_ID="retry-fixture")
        for mocked in (patch.dict(os.environ, clean, clear=True),
                       patch.object(pipeline.time, "sleep"),
                       patch("sys.stderr", new_callable=io.StringIO)):
            mocked.start()
            self.addCleanup(mocked.stop)

    def fail_receipt_writes(self):
        original = accounting._write_event

        def write(event):
            if event["event"] == "api_attempt":
                raise OSError("SYNTHETIC_PRIVATE_DISK_ERROR")
            return original(event)

        return patch.object(accounting, "_write_event", side_effect=write)

    @staticmethod
    def urllib_response():
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({
            "id": "fixture-response", "choices": [], "usage": {"input_tokens": 1, "output_tokens": 1}
        }).encode()
        return response

    def events(self):
        events, damaged = accounting.read_events(self.directory.name)
        self.assertEqual(damaged, [])
        return events

    def test_successful_chat_response_with_failed_receipt_is_not_retried(self):
        with patch.object(pipeline.urllib.request, "urlopen", return_value=self.urllib_response()) as network, self.fail_receipt_writes():
            with self.assertRaises(accounting.AccountingWriteError):
                pipeline.chat_json("fixture-key", {"model": "gpt-6-astra"}, retries=3)
        self.assertEqual(network.call_count, 1)
        self.assertEqual([event["event"] for event in self.events()], ["api_attempt_started"])

    def test_network_error_with_failed_receipt_keeps_original_and_stops_both_retry_layers(self):
        for original_error in (
            urllib.error.URLError("SYNTHETIC_PRIVATE_NETWORK_ERROR"),
            urllib.error.HTTPError("https://example.invalid", 503, "unavailable", {}, io.BytesIO(b"private response")),
        ):
            for caller in ("chat", "request"):
                if hasattr(original_error, "sermon_logging_failed"):
                    delattr(original_error, "sermon_logging_failed")
                with self.subTest(error=type(original_error).__name__, caller=caller), patch.object(pipeline.urllib.request, "urlopen", side_effect=original_error) as network, self.fail_receipt_writes():
                    with self.assertRaises(type(original_error)) as caught:
                        if caller == "chat":
                            pipeline.chat_json("fixture-key", {"model": "gpt-6-astra"}, retries=3)
                        else:
                            request = pipeline.urllib.request.Request("https://example.invalid")
                            pipeline.request_json(request, retries=3)
                    self.assertIs(caught.exception, original_error)
                    self.assertTrue(getattr(original_error, "sermon_logging_failed", False))
                    self.assertEqual(network.call_count, 1)

    def test_healthy_ledger_preserves_normal_http_retry(self):
        error = urllib.error.HTTPError("https://example.invalid", 503, "unavailable", {}, io.BytesIO(b"retryable"))
        with patch.object(pipeline.urllib.request, "urlopen", side_effect=[error, self.urllib_response()]) as network:
            result = pipeline.chat_json("fixture-key", {"model": "gpt-6-astra"}, retries=2)
        self.assertEqual(result["id"], "fixture-response")
        self.assertEqual(network.call_count, 2)
        attempts = [event for event in self.events() if event["event"] == "api_attempt"]
        self.assertEqual([event["status"] for event in attempts], ["failed", "completed"])
        self.assertEqual(attempts[0]["httpStatus"], 503)

    def test_notes_successful_response_keeps_write_failure_distinct(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {"id": "notes-response", "usage": {"input_tokens": 1, "output_tokens": 1}}
        with patch.object(notes.requests, "post", return_value=response) as network, self.fail_receipt_writes():
            with self.assertRaises(accounting.AccountingWriteError):
                notes.request_openai_notes({"model": "gpt-6-astra"}, api_key="fixture-key")
        self.assertEqual(network.call_count, 1)

    def test_notes_network_and_decode_failures_preserve_original(self):
        for kind in ("network", "decode"):
            error = requests.ConnectionError("private network detail") if kind == "network" else ValueError("private decode detail")
            response = MagicMock(status_code=200)
            response.json.side_effect = error
            kwargs = {"side_effect": error} if kind == "network" else {"return_value": response}
            with self.subTest(kind=kind), patch.object(notes.requests, "post", **kwargs) as network, self.fail_receipt_writes():
                with self.assertRaises(type(error)) as caught:
                    notes.request_openai_notes({"model": "gpt-6-astra"}, api_key="fixture-key")
                self.assertIs(caught.exception, error)
                self.assertTrue(getattr(error, "sermon_logging_failed", False))
                self.assertEqual(network.call_count, 1)

    def test_notes_http_failure_remains_system_exit_when_receipt_write_fails(self):
        response = MagicMock(status_code=503)
        response.json.return_value = {"error": {"message": "fixture unavailable"}}
        with patch.object(notes.requests, "post", return_value=response) as network, self.fail_receipt_writes():
            with self.assertRaises(SystemExit) as caught:
                notes.request_openai_notes({"model": "gpt-6-astra"}, api_key="fixture-key")
        self.assertIn("HTTP 503", str(caught.exception))
        self.assertTrue(getattr(caught.exception, "sermon_logging_failed", False))
        self.assertEqual(network.call_count, 1)


if __name__ == "__main__":
    unittest.main()
