"""Accounting integration checks: no model/network calls or PDF rendering."""
import argparse
import contextlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

from scripts import build_sermon_reading_edition_with_openai as reading
from scripts import generate_notes_with_openai as notes
from scripts import sermon_accounting as accounting


class ReadingAccountingTests(unittest.TestCase):
    def test_cache_hit_does_not_repeat_api_attempt(self):
        block = {"id": 0, "start": 0, "end": 2, "en": "Hello.", "zh": "你好。"}
        reply = {"model": "test-model", "choices": [{"message": {"content": json.dumps({"blocks": [{"id": 0, "zh": "您好。"}]})}}]}
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(reading, "chat_json", return_value=reply) as api, mock.patch.object(reading, "stage", side_effect=lambda *a, **k: contextlib.nullcontext()) as stages:
            options = dict(model="test-model", reasoning_effort="medium", qa_pass=False,
                           provider="openai", codex_cli=Path("unused"), schema_path=Path("unused"))
            first = reading.edit_batch("secret", [block], [block], 0, Path(temp), **options)
            second = reading.edit_batch("secret", [block], [block], 0, Path(temp), **options)
        self.assertEqual(first, second)
        api.assert_called_once()
        stages.assert_called_once_with("reading.batch_cache", cache_hit=True, billing="local")

    def test_two_passes_have_distinct_stage_labels(self):
        block = {"id": 0, "zh": "你好。"}
        with mock.patch.object(reading, "edit_batch", return_value={"blocks": [block]}), mock.patch.object(reading, "stage", side_effect=lambda *a, **k: contextlib.nullcontext()) as stages:
            for qa_pass in (False, True):
                result = reading.run_edit_pass("secret", [block], Path("unused"), model="test-model",
                    reasoning_effort="medium", batch_size=1, workers=2, qa_pass=qa_pass,
                    provider="openai", codex_cli=Path("unused"), schema_path=Path("unused"))
                self.assertEqual(result[0]["zh"], block["zh"])
        self.assertEqual(stages.call_args_list, [mock.call("reading.edit_pass_1", billing="api"), mock.call("reading.edit_pass_2", billing="api")])

    def test_threaded_pass_receipts_keep_stage_and_cache_spend_separate(self):
        block = {"id": 0, "start": 0, "end": 2, "en": "Hello.", "zh": "你好。"}
        calls = []

        def fake_api(api_key, payload):
            calls.append(payload)
            reply = {"id": f"response-{len(calls)}", "model": "test-model",
                     "usage": {"prompt_tokens": 10, "completion_tokens": 3},
                     "choices": [{"message": {"content": json.dumps({"blocks": [{"id": 0, "zh": "您好。"}]})}}]}
            # The real chat_json owns this receipt; the reading caller must not add one.
            accounting.record_api_attempt("test-model", reply, .01)
            return reply

        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(os.environ), mock.patch.object(reading, "chat_json", side_effect=fake_api):
            for key in accounting.ENV_KEYS:
                os.environ.pop(key, None)
            root = Path(temp)
            with accounting.accounting_session(root/"accounting", "test_reading"):
                for qa_pass in (False, True, False):
                    reading.run_edit_pass("private", [block], root, model="test-model",
                        reasoning_effort="medium", batch_size=1, workers=2, qa_pass=qa_pass,
                        provider="openai", codex_cli=Path("unused"), schema_path=Path("unused"))
            events = [json.loads(line) for line in (root/"accounting/events.jsonl").read_text().splitlines()]
        attempts = [event for event in events if event["event"] == "api_attempt"]
        self.assertEqual([event["stage"] for event in attempts], ["reading.edit_pass_1", "reading.edit_pass_2"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(len({event["attemptId"] for event in attempts}), 2)
        self.assertEqual(sum(event["event"] == "stage_finished" and event.get("cacheHit", False) for event in events), 1)

    def test_standalone_main_enters_session(self):
        for module, attr, workflow in [(reading, "outdir", "sermon_reading_edition"), (notes, "out_dir", "sermon_interpretation_notes")]:
            with self.subTest(workflow=workflow):
                args = argparse.Namespace(**{attr: Path("output")})
                with mock.patch.object(module, "parse_args", return_value=args), mock.patch.object(module, "accounting_session", return_value=contextlib.nullcontext()) as session, mock.patch.object(module, "_main", return_value=0) as run:
                    self.assertEqual(module.main(), 0)
                session.assert_called_once_with(Path("output/accounting"), workflow)
                run.assert_called_once_with(args)

    def test_codex_failure_is_scoped_without_api_billing(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(reading.subprocess, "run", return_value=argparse.Namespace(returncode=1, stderr="failed", stdout="")), mock.patch.object(reading, "stage", return_value=contextlib.nullcontext()) as stages:
            with self.assertRaises(RuntimeError):
                reading.codex_json({"messages": [{"content": "system"}, {"content": "user"}]}, codex_cli=Path("unused"), model="test", reasoning_effort="medium", schema_path=Path("unused"), output_path=Path(temp)/"result.json")
        stages.assert_called_once_with("reading.codex_call", billing="codex")


class NotesAttemptAccountingTests(unittest.TestCase):
    def test_success_records_one_raw_usage_response(self):
        body = {"id": "response-test", "usage": {"input_tokens": 17, "output_tokens": 5}, "output_text": "{}"}
        response = mock.Mock(status_code=200)
        response.json.return_value = body
        with mock.patch.object(notes.requests, "post", return_value=response), mock.patch.object(notes, "record_api_attempt") as record:
            self.assertIs(notes.request_openai_notes({"model": "test"}, "private"), body)
        record.assert_called_once()
        self.assertIs(record.call_args.kwargs["response"], body)
        self.assertEqual(record.call_args.kwargs["model"], "test")
        self.assertGreaterEqual(record.call_args.kwargs["elapsed_seconds"], 0)
        self.assertNotIn("private", str(record.call_args))

    def test_notes_pdf_has_local_stage_separate_from_generation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args = argparse.Namespace(api_key_secret=None, max_slices=0, model="test",
                reasoning_effort="medium", request_timeout_seconds=10,
                out_dir=root/"notes", model_output_dir=root/"model-output",
                pdf_out=root/"notes.pdf", pdf_qa_out=None, font_path=None,
                gcs_bucket=None, manifest=None)
            with contextlib.ExitStack() as stack:
                stack.enter_context(mock.patch.object(notes, "read_note_source", return_value={"segments": []}))
                stack.enter_context(mock.patch.object(notes, "build_note_slices", return_value=[{"text": "source"}]))
                stack.enter_context(mock.patch.object(notes, "resolve_api_key", return_value="private"))
                stack.enter_context(mock.patch.object(notes, "build_openai_request", return_value={"model": "test"}))
                stack.enter_context(mock.patch.object(notes, "request_openai_notes", return_value={"output_text": "{}"}))
                stack.enter_context(mock.patch.object(notes, "normalize_insights", return_value={}))
                render = stack.enter_context(mock.patch.object(notes, "render_interpretation_pdf", return_value={"status": "pass"}))
                stages = stack.enter_context(mock.patch.object(notes, "stage", side_effect=lambda *a, **k: contextlib.nullcontext()))
                stack.enter_context(mock.patch("builtins.print"))
                self.assertEqual(notes._main(args), 0)
            render.assert_called_once()
            self.assertEqual(stages.call_args_list, [mock.call("notes.generate", billing="api"), mock.call("notes.render_pdf", billing="local")])
            self.assertTrue((root/"notes.qa.json").exists())

    def test_network_http_and_decode_failures_record_once(self):
        bad_http = mock.Mock(status_code=429)
        bad_http.json.return_value = {"error": {"message": "retry later"}}
        bad_json = mock.Mock(status_code=200)
        bad_json.json.side_effect = ValueError("invalid JSON")
        cases = [(requests.Timeout("sensitive transport detail"), None, requests.Timeout, "Timeout"),
                 (None, bad_http, SystemExit, "HTTP429"),
                 (None, bad_json, ValueError, "ValueError")]
        for failure, response, expected, error_type in cases:
            with self.subTest(error_type=error_type), mock.patch.object(notes.requests, "post", side_effect=failure, return_value=response), mock.patch.object(notes, "record_api_attempt") as record:
                with self.assertRaises(expected):
                    notes.request_openai_notes({"model": "test"}, "private")
                record.assert_called_once()
                kwargs = record.call_args.kwargs
                self.assertEqual(kwargs["status"], "failed")
                self.assertEqual(kwargs["error_type"], error_type)
                self.assertIsNone(kwargs["response"])
                self.assertNotIn("sensitive", str(kwargs))
                self.assertNotIn("private", str(kwargs))


if __name__ == "__main__":
    unittest.main()
