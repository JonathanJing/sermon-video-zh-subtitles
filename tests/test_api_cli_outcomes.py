import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from scripts import api_cli_outcomes as outcomes
from scripts.production_spark_admission import SessionBoundCaller


class ApiCliOutcomeTests(unittest.TestCase):
    def test_missing_context_rejects_before_dispatch(self):
        caller = Mock()
        with patch.dict('os.environ', {}, clear=True):
            with self.assertRaisesRegex(ValueError, 'directory_required_before_dispatch'):
                SessionBoundCaller(caller, requires_spark=False)()
        caller.assert_not_called()

    def test_unknown_blocks_changed_request_and_new_wrapper_until_response_reconciled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def fail(api_key, payload):
                raise TimeoutError('unknown')
            with self.assertRaises(TimeoutError):
                SessionBoundCaller(fail, requires_spark=False, outcome_directory=root)('key1', {'model':'test'})
            retry = Mock(return_value={'unexpected':True})
            with self.assertRaisesRegex(ValueError, 'reconciliation_required'):
                SessionBoundCaller(retry, requires_spark=False, outcome_directory=root)('key2', {'model':'changed'})
            retry.assert_not_called()
            path = next(root.glob('*/outcome.json'))
            row = json.loads(path.read_text())
            self.assertEqual(row['status'], 'unknown')
            self.assertNotIn('key1', path.read_text())
            outcomes.reconcile(root, row['requestSha256'], {'recovered':True},
                               {'terminalResponseEvidence':'provider-receipt-local.json'})
            # Same stable signature/key rotation replays the reconciled response.
            def returned(api_key, payload):
                self.fail('reconciled response redispatched')
            self.assertEqual(SessionBoundCaller(returned, requires_spark=False,
                outcome_directory=root)('key2', {'model':'test'}), {'recovered':True})

    def test_started_crash_blocks_and_evidence_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); row = root / ('a'*64) / 'outcome.json'
            outcomes._write(row, {'schemaVersion':outcomes.SCHEMA, 'requestSha256':'a'*64,'status':'started'})
            with self.assertRaisesRegex(ValueError, 'reconciliation_required'):
                SessionBoundCaller(lambda: None, requires_spark=False, outcome_directory=root)()
            with self.assertRaisesRegex(ValueError, 'terminal_evidence_required'):
                outcomes.reconcile(root, 'a'*64, {}, {})

    def test_success_is_durable_before_return_nested_helper_replays_without_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            def inner(payload): calls.append(payload); return {'ok':True}
            def outer(payload):
                return SessionBoundCaller(inner, requires_spark=False)(payload)
            wrapped = SessionBoundCaller(outer, requires_spark=False, outcome_directory=tmp)
            self.assertEqual(wrapped({'max_tokens':1}), {'ok':True})
            self.assertEqual(wrapped({'max_tokens':1}), {'ok':True})
            self.assertEqual(len(calls), 1)
            self.assertEqual(wrapped({'max_tokens':2}), {'ok':True})
            self.assertEqual(len(calls), 2)

    def test_existing_budget_gate_runs_without_legacy_directory_or_spark(self):
        caller = Mock(return_value={'budgeted':True})
        with patch.dict('os.environ', {}, clear=True):
            self.assertEqual(SessionBoundCaller(caller, requires_spark=False,
                outcome_guarded=True)(), {'budgeted':True})
        caller.assert_called_once()

    def test_actual_notes_and_reading_timeout_paths_preserve_unknown(self):
        from scripts import generate_notes_with_openai as notes
        from scripts import build_sermon_reading_edition_with_openai as reading
        for module, target, invoke in (
            (notes, '_request_openai_notes', lambda root: notes.request_openai_notes({'model':'test'}, 'secret')),
            (reading, '_codex_json', lambda root: reading.codex_json({'messages':[]},
                codex_cli=root/'cli', model='test', reasoning_effort='medium',
                schema_path=root/'schema.json', output_path=root/'response.json')),
        ):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); (root/'schema.json').write_text('{}')
                with patch.dict('os.environ', {'SERMON_ACCOUNTING_DIR':tmp}), \
                     patch.object(module, target, side_effect=TimeoutError('unknown')) as transport:
                    with self.assertRaises(TimeoutError): invoke(root)
                    with self.assertRaisesRegex(ValueError, 'reconciliation_required'): invoke(root)
                self.assertEqual(transport.call_count, 1)

    def test_subprocess_cannot_dispatch_after_crashed_started_receipt(self):
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outcomes._write(root/('a'*64)/'outcome.json', {'status':'started'})
            result = subprocess.run([sys.executable, '-c',
                'from scripts.production_spark_admission import SessionBoundCaller; '
                'import sys; SessionBoundCaller(lambda: print("DISPATCHED"), '
                'requires_spark=False, outcome_directory=sys.argv[1])()', tmp],
                text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('DISPATCHED', result.stdout)
            self.assertIn('reconciliation_required', result.stderr)

    def test_legacy_text_unknown_never_retries_inside_hold(self):
        from scripts import sermon_pipeline as pipeline
        with tempfile.TemporaryDirectory() as tmp, \
             patch.dict('os.environ', {'SERMON_ACCOUNTING_DIR':tmp}), \
             patch('scripts.strict_budget_capability.require_bounded_api_payload'), \
             patch.object(pipeline, 'json_request', side_effect=TimeoutError('unknown')) as request, \
             patch.object(pipeline.time, 'sleep'):
            with self.assertRaises(TimeoutError):
                pipeline.chat_json('secret', {'model':'test'}, retries=3)
            self.assertEqual(request.call_count, 1)
