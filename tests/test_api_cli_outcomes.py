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
            # Only the original frozen caller and credential can replay this response.
            self.assertEqual(SessionBoundCaller(fail, requires_spark=False,
                outcome_directory=root)('key1', {'model':'test'}), {'recovered':True})

    def test_started_crash_blocks_and_evidence_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); row = root / ('a'*64) / 'outcome.json'
            outcomes._write(row, {'schemaVersion':outcomes.V2_SCHEMA, 'requestSha256':'a'*64,'purpose':'production-model-call','status':'started'})
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
                (root/'cli').write_text('#!/bin/sh\nexit 0\n');(root/'cli').chmod(0o700)
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
            outcomes._write(root/('a'*64)/'outcome.json', {'schemaVersion':outcomes.V2_SCHEMA,'requestSha256':'a'*64,'purpose':'production-model-call','status':'started'})
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
                pipeline.chat_json('secret', {'model':'gpt-6-astra','reasoning_effort':'medium', 'messages':[{'role':'user','content':'synthetic'}], 'response_format':{'type':'json_object'}}, retries=3)
            self.assertEqual(request.call_count, 1)

    def test_cache_binding_damage_or_wrong_directory_never_replays(self):
        for field, value in [('schemaVersion','wrong'), ('purpose','different'),
                             ('requestSha256','b'*64), ('status','terminal_failure')]:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                call = Mock(return_value={'ok':True})
                wrapped = SessionBoundCaller(call, requires_spark=False, outcome_directory=tmp)
                wrapped()
                path = next(Path(tmp).glob('*/outcome.json'))
                row = json.loads(path.read_text()); row[field] = value
                path.write_text(json.dumps(row))
                with self.assertRaisesRegex(ValueError, 'binding_mismatch'):
                    wrapped()
                self.assertEqual(call.call_count, 1)

    def test_http_rejection_terminal_and_corrected_request_can_continue(self):
        import io
        import urllib.error
        with tempfile.TemporaryDirectory() as tmp:
            def rejected(payload):
                raise urllib.error.HTTPError('https://example.invalid',429,'rate limit',{},io.BytesIO(b'{}'))
            wrapped = SessionBoundCaller(rejected, requires_spark=False, outcome_directory=tmp)
            with self.assertRaises(urllib.error.HTTPError): wrapped({'request':1})
            with self.assertRaises(outcomes.TerminalOutcomeError): wrapped({'request':1})
            with self.assertRaisesRegex(ValueError,'frozen_execution_binding_changed'):
                SessionBoundCaller(lambda payload: {'ok':True}, requires_spark=False,
                    outcome_directory=tmp)({'request':2})

    def test_raw_decode_failure_body_bound_and_failure_reconciliation_not_success(self):
        import base64
        with tempfile.TemporaryDirectory() as tmp:
            def decode(payload):
                outcomes.observed_response(b'{not valid json', http_status=200)
                return json.loads('{not valid json')
            wrapped = SessionBoundCaller(decode, requires_spark=False, outcome_directory=tmp)
            with self.assertRaises(json.JSONDecodeError): wrapped({'request':1})
            row = json.loads(next(Path(tmp).glob('*/outcome.json')).read_text())
            self.assertEqual(row['status'],'terminal_failure')
            self.assertEqual(base64.b64decode(row['rawBodyBase64']),b'{not valid json')
            with self.assertRaises(outcomes.TerminalOutcomeError): wrapped({'request':1})
        with tempfile.TemporaryDirectory() as tmp:
            def unknown(payload): raise TimeoutError('uncertain')
            wrapped = SessionBoundCaller(unknown, requires_spark=False, outcome_directory=tmp)
            with self.assertRaises(TimeoutError): wrapped({'request':1})
            row = json.loads(next(Path(tmp).glob('*/outcome.json')).read_text())
            outcomes.reconcile(tmp,row['requestSha256'],{'httpStatus':429},
                {'terminalResponseEvidence':'observed-provider-rejection'},terminal_failure=True)
            with self.assertRaises(outcomes.TerminalOutcomeError): wrapped({'request':1})

    def test_legacy_returned_receipt_remains_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            wrapped=SessionBoundCaller(lambda: {'ok':True},requires_spark=False,outcome_directory=tmp)
            wrapped(); path=next(Path(tmp).glob('*/outcome.json'))
            row=json.loads(path.read_text());row['schemaVersion']=outcomes.LEGACY_SCHEMA
            path.write_text(json.dumps(row))
            self.assertEqual(outcomes.recover(tmp,row['requestSha256'],'production-model-call'),{'ok':True})

    def test_confirmed_no_dispatch_terminal_failure_preserves_reason(self):
        from scripts.sermon_pipeline import PreDispatchRejection
        with tempfile.TemporaryDirectory() as tmp:
            def guarded(payload):
                outcomes.observed_no_dispatch('provider_configuration_blocked')
                raise PreDispatchRejection('provider_configuration_blocked')
            wrapped=SessionBoundCaller(guarded,requires_spark=False,outcome_directory=tmp)
            with self.assertRaises(PreDispatchRejection):wrapped({'request':1})
            row=json.loads(next(Path(tmp).glob('*/outcome.json')).read_text())
            self.assertEqual(row['status'],'terminal_failure')
            self.assertEqual(row['notDispatchedReason'],'provider_configuration_blocked')
            with self.assertRaises(outcomes.TerminalOutcomeError):wrapped({'request':1})

    def test_received_body_tampering_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            def called():
                outcomes.observed_response(b'{}')
                return {}
            wrapped=SessionBoundCaller(called,requires_spark=False,outcome_directory=tmp)
            wrapped();path=next(Path(tmp).glob('*/outcome.json'))
            row=json.loads(path.read_text());row['rawBodySha256']='b'*64
            path.write_text(json.dumps(row))
            with self.assertRaisesRegex(ValueError,'raw_response_identity_mismatch'):wrapped()

    def test_legacy_unknown_explicit_failed_reconciliation_migrates_to_v2(self):
        with tempfile.TemporaryDirectory() as tmp:
            def unknown(): raise TimeoutError('unknown')
            wrapped=SessionBoundCaller(unknown,requires_spark=False,outcome_directory=tmp)
            with self.assertRaises(TimeoutError):wrapped()
            path=next(Path(tmp).glob('*/outcome.json'));row=json.loads(path.read_text())
            row['schemaVersion']=outcomes.LEGACY_SCHEMA;path.write_text(json.dumps(row))
            outcomes.reconcile(tmp,row['requestSha256'],{'httpStatus':503},
                {'terminalResponseEvidence':'provider-terminal-rejection'},terminal_failure=True)
            saved=json.loads(path.read_text())
            self.assertEqual(saved['schemaVersion'],outcomes.V2_SCHEMA)
            self.assertEqual(saved['reconciledFromSchemaVersion'],outcomes.LEGACY_SCHEMA)
            with self.assertRaises(outcomes.TerminalOutcomeError):
                outcomes.recover(tmp,row['requestSha256'],'production-model-call')

    def test_route_credential_and_implementation_changes_cannot_replay_or_dispatch(self):
        route={'schemaVersion':'sermon-openai-runtime-route-v1','environment':'dev',
               'projectId':'proj_test','credentialAlias':'tongxing-dev-runtime','identitySource':'configured_runtime'}
        calls=[]
        def first(api_key,payload):calls.append(1);return {'old':True}
        def changed(api_key,payload):calls.append(2);return {'new':True}
        for kind in ('route','key','implementation'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as tmp:
                with patch('scripts.sermon_openai_runtime.selected_route',return_value=route):
                    wrapped=SessionBoundCaller(first,requires_spark=False,outcome_directory=tmp)
                    wrapped('secret-original',{'request':1})
                    old=outcomes.request_identity(first,('secret-original',{'request':1}),{},wrapped.purpose)
                    newroute={**route,'environment':'prod','credentialAlias':'tongxing-prod-runtime'} if kind=='route' else route
                    with patch('scripts.sermon_openai_runtime.selected_route',return_value=newroute):
                        caller=changed if kind=='implementation' else first
                        key='secret-changed' if kind=='key' else 'secret-original'
                        self.assertNotEqual(old,outcomes.request_identity(caller,(key,{'request':1}),{},wrapped.purpose))
                        before=len(calls)
                        with self.assertRaisesRegex(ValueError,'frozen_execution_binding_changed'):
                            SessionBoundCaller(caller,requires_spark=False,outcome_directory=tmp)(key,{'request':1})
                        self.assertEqual(len(calls),before)

    def test_codex_upgrade_same_path_and_symlink_target_bytes_cannot_replay(self):
        calls=[]
        def invoke(*,codex_cli):calls.append(1);return {'ok':True}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);binary=root/'binary';binary.write_text('#!/bin/sh\nexit 0\n');binary.chmod(0o700)
            link=root/'codex';link.symlink_to(binary)
            wrapped=SessionBoundCaller(invoke,requires_spark=False,outcome_directory=root/'outcomes')
            wrapped(codex_cli=link)
            old=outcomes.request_identity(invoke,(),{'codex_cli':link},wrapped.purpose)
            binary.write_text('#!/bin/sh\nexit 1\n')
            self.assertNotEqual(old,outcomes.request_identity(invoke,(),{'codex_cli':link},wrapped.purpose))
            with self.assertRaisesRegex(ValueError,'frozen_execution_binding_changed'):
                wrapped(codex_cli=link)
            self.assertEqual(calls,[1])
