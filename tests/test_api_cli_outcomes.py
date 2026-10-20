import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from tongxing_production.compute import legacy_openai  # C4: the remote-call group lives here
from scripts import api_cli_outcomes as outcomes
from scripts.production_spark_admission import SessionBoundCaller


def reconciliation_evidence(request_sha256, response, *, terminal_failure=False):
    return {'schemaVersion': outcomes.RECONCILIATION_EVIDENCE_SCHEMA,
            'requestSha256': request_sha256, 'responseSha256': outcomes._digest(response),
            'terminalFailure': terminal_failure, 'terminalResponseEvidence': 'observed-provider-receipt'}


class ApiCliOutcomeTests(unittest.TestCase):
    def test_replay_gate_is_read_only_and_checks_unknown_frozen_and_legacy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'outcomes'
            def provider(payload): return {'ok': payload}
            binding = outcomes.execution_binding(provider, {'payload': 1})
            outcomes.assert_replay_admitted(root, purpose='test', binding=binding)
            self.assertFalse(root.exists())
            SessionBoundCaller(provider, purpose='test', requires_spark=False, outcome_directory=root)(1)
            def snapshot():
                return {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
                        for p in root.rglob('*') if p.is_file()}
            before = snapshot()
            outcomes.assert_replay_admitted(root, purpose='test', binding=binding)
            self.assertEqual(snapshot(), before)
            changed = dict(binding, runtimeRoute={'different': True})
            with self.assertRaisesRegex(ValueError, 'frozen_execution_binding_changed'):
                outcomes.assert_replay_admitted(root, purpose='test', binding=changed)
            path = next(root.glob('*/outcome.json')); row = json.loads(path.read_text())
            row['status'] = 'unknown'; outcomes._write(path, row)
            before = snapshot()
            with self.assertRaisesRegex(ValueError, 'reconciliation_required'):
                outcomes.assert_replay_admitted(root, purpose='test', binding=binding)
            self.assertEqual(snapshot(), before)
            row.update(schemaVersion=outcomes.V2_SCHEMA, status='returned')
            outcomes._write(path, row)
            with self.assertRaisesRegex(ValueError, 'legacy_execution_binding_requires_explicit_reconciliation'):
                outcomes.assert_replay_admitted(root, purpose='test', binding=binding)

    def test_recorded_received_or_unknown_json_cannot_be_replaced(self):
        for status in ('received', 'unknown'):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                def provider():
                    outcomes.observed_response(b'{"real": 1}', http_status=200)
                    return {'real': 1}
                wrapped = SessionBoundCaller(provider, requires_spark=False, outcome_directory=directory)
                wrapped()
                path = next(Path(directory).glob('*/outcome.json'))
                row = json.loads(path.read_text()); row['status'] = status
                row.pop('response'); row.pop('responseSha256'); outcomes._write(path, row)
                before = path.read_bytes()
                wrong = {'fake': 2}
                with self.assertRaisesRegex(ValueError, 'recorded_response_mismatch'):
                    outcomes.reconcile(directory, row['requestSha256'], wrong,
                                       reconciliation_evidence(row['requestSha256'], wrong))
                self.assertEqual(path.read_bytes(), before)
                exact = {'real': 1}
                outcomes.reconcile(directory, row['requestSha256'], exact,
                                   reconciliation_evidence(row['requestSha256'], exact))
                self.assertEqual(outcomes.recover(directory, row['requestSha256'], row['purpose']), exact)
                saved = json.loads(path.read_text())
                self.assertEqual(saved['reconciliationBinding']['responseSha256'], outcomes._digest(exact))
                saved['reconciliationBinding']['responseSha256'] = 'f' * 64
                outcomes._write(path, saved)
                with self.assertRaisesRegex(ValueError, 'reconciliation_binding_mismatch'):
                    outcomes.recover(directory, row['requestSha256'], row['purpose'])

    def test_unknown_without_raw_requires_versioned_request_response_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            def provider(): raise TimeoutError('actual unknown')
            wrapped = SessionBoundCaller(provider, requires_spark=False, outcome_directory=directory)
            with self.assertRaises(TimeoutError): wrapped()
            path = next(Path(directory).glob('*/outcome.json')); row = json.loads(path.read_text())
            response = {'observed': 'provider-or-cli-result'}
            valid = reconciliation_evidence(row['requestSha256'], response)
            invalid = [ {'terminalResponseEvidence': 'truthy pointer'},
                       dict(valid, requestSha256='a' * 64), dict(valid, responseSha256='b' * 64),
                       dict(valid, terminalFailure=True), dict(valid, terminalFailure='false') ]
            for evidence in invalid:
                with self.subTest(evidence=evidence):
                    before = path.read_bytes()
                    with self.assertRaisesRegex(ValueError, 'evidence_binding_mismatch'):
                        outcomes.reconcile(directory, row['requestSha256'], response, evidence)
                    self.assertEqual(path.read_bytes(), before)
            outcomes.reconcile(directory, row['requestSha256'], response, valid)
            self.assertEqual(outcomes.recover(directory, row['requestSha256'], row['purpose']), response)

    def test_non_json_or_http_failure_cannot_be_reconciled_to_success(self):
        for body, http_status, message in [(b'not JSON', 200, 'not_json'),
                                           (b'{"error":"rejected"}', 503, 'failure_cannot_be_success')]:
            with self.subTest(body=body), tempfile.TemporaryDirectory() as directory:
                def provider():
                    outcomes.observed_response(body, http_status=http_status)
                    return {'fixture': True}
                SessionBoundCaller(provider, requires_spark=False, outcome_directory=directory)()
                path = next(Path(directory).glob('*/outcome.json')); row = json.loads(path.read_text())
                row.update(status='received'); row.pop('response'); row.pop('responseSha256')
                outcomes._write(path, row); before = path.read_bytes()
                response = {'error':'rejected'} if http_status == 503 else {'fake': True}
                with self.assertRaisesRegex(ValueError, message):
                    outcomes.reconcile(directory, row['requestSha256'], response,
                                       reconciliation_evidence(row['requestSha256'], response))
                self.assertEqual(path.read_bytes(), before)
                if http_status == 503:
                    outcomes.reconcile(directory, row['requestSha256'], response,
                        reconciliation_evidence(row['requestSha256'], response, terminal_failure=True), terminal_failure=True)
                    with self.assertRaises(outcomes.TerminalOutcomeError):
                        outcomes.recover(directory, row['requestSha256'], row['purpose'])

    def test_received_without_raw_is_not_operator_success(self):
        with tempfile.TemporaryDirectory() as directory:
            def provider(): raise TimeoutError('unknown')
            with self.assertRaises(TimeoutError):
                SessionBoundCaller(provider, requires_spark=False, outcome_directory=directory)()
            path = next(Path(directory).glob('*/outcome.json')); row = json.loads(path.read_text())
            row['status'] = 'received'; outcomes._write(path, row); before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, 'response_bytes_required'):
                outcomes.reconcile(directory, row['requestSha256'], {}, reconciliation_evidence(row['requestSha256'], {}))
            self.assertEqual(path.read_bytes(), before)

    def test_completed_cli_failure_is_terminal_other_requests_continue_and_timeout_unknown(self):
        import subprocess
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            def cli(payload):
                calls.append(payload)
                if payload == 'timeout':
                    raise subprocess.TimeoutExpired('fixture-cli', 1)
                outcomes.observed_cli_terminal(returncode=2 if payload == 'nonzero' else 0,
                    stdout=b'actual stdout', stderr=b'actual stderr', output=b'not valid JSON')
                if payload == 'nonzero': raise subprocess.CalledProcessError(2, 'fixture-cli')
                if payload == 'parse': raise json.JSONDecodeError('parse failure', '', 0)
                return {'valid': True}
            wrapped = SessionBoundCaller(cli, requires_spark=False, outcome_directory=directory)
            for payload, failure in [('nonzero', subprocess.CalledProcessError), ('parse', json.JSONDecodeError)]:
                with self.subTest(payload=payload):
                    with self.assertRaises(failure): wrapped(payload)
                    with self.assertRaises(outcomes.TerminalOutcomeError): wrapped(payload)
            self.assertEqual(calls, ['nonzero', 'parse'])
            self.assertEqual(wrapped('success'), {'valid': True})
            rows = [json.loads(p.read_text()) for p in Path(directory).glob('*/outcome.json')]
            self.assertTrue(all('cliTerminal' in row and 'httpStatus' not in row for row in rows))
            self.assertEqual(sorted(row['status'] for row in rows), ['returned', 'terminal_failure', 'terminal_failure'])
            with self.assertRaises(subprocess.TimeoutExpired): wrapped('timeout')
            with self.assertRaisesRegex(ValueError, 'reconciliation_required'): wrapped('later')
            self.assertEqual(calls, ['nonzero', 'parse', 'success', 'timeout'])
            unknown = next(json.loads(p.read_text()) for p in Path(directory).glob('*/outcome.json')
                           if json.loads(p.read_text())['status'] == 'unknown')
            self.assertNotIn('cliTerminal', unknown)

    def test_received_cli_can_only_close_exact_recorded_terminal_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            def cli():
                outcomes.observed_cli_terminal(returncode=0, stdout=b'{"event":"completed"}',
                                               stderr=b'', output=b'{"actual":1}')
                return {'actual': 1}
            SessionBoundCaller(cli, requires_spark=False, outcome_directory=directory)()
            path = next(Path(directory).glob('*/outcome.json')); row = json.loads(path.read_text())
            row.update(status='received'); row.pop('response'); row.pop('responseSha256')
            outcomes._write(path, row); before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, 'requires_failure_reconciliation'):
                outcomes.reconcile(directory, row['requestSha256'], {'fake': 2},
                    reconciliation_evidence(row['requestSha256'], {'fake': 2}))
            self.assertEqual(path.read_bytes(), before)
            with self.assertRaisesRegex(ValueError, 'recorded_response_mismatch'):
                outcomes.reconcile(directory, row['requestSha256'], {'error': 'invented'},
                    reconciliation_evidence(row['requestSha256'], {'error': 'invented'}, terminal_failure=True),
                    terminal_failure=True)
            self.assertEqual(path.read_bytes(), before)
            envelope = row['cliTerminal']
            outcomes.reconcile(directory, row['requestSha256'], envelope,
                               reconciliation_evidence(row['requestSha256'], envelope, terminal_failure=True),
                               terminal_failure=True)
            with self.assertRaises(outcomes.TerminalOutcomeError):
                outcomes.recover(directory, row['requestSha256'], row['purpose'])

    def test_cli_private_terminal_bytes_are_omitted_from_export(self):
        from scripts import export_run_digest as exporter
        import base64
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root/'source'; dest = root/'export'
            raw = b'PRIVATE-MODEL-OUTPUT-NOT-FOR-REPORT'
            def cli():
                outcomes.observed_cli_terminal(returncode=2, stdout=raw, stderr=raw, output=raw)
                raise RuntimeError('completed rejected CLI')
            with self.assertRaises(RuntimeError):
                SessionBoundCaller(cli, requires_spark=False, outcome_directory=source)()
            self.assertEqual(exporter.main([str(source), '--out', str(dest), '--name', '20261014-cli-private']), 0)
            report = dest/'20261014-cli-private'
            text = '\n'.join(p.read_text() for p in report.rglob('*') if p.is_file())
            self.assertNotIn(raw.decode(), text)
            self.assertNotIn(base64.b64encode(raw).decode(), text)
            self.assertEqual(exporter.verify(report, []), [])
            metadata = next(p for p in report.rglob('outcome.json'))
            value = json.loads(metadata.read_text())
            self.assertNotIn('cliTerminal', value)
            self.assertEqual(value['status'], 'terminal_failure')

    def test_code_identity_is_stable_across_first_execution_and_detects_changed_nested_code(self):
        namespace = {}
        exec(compile("def provider(values):\n    def inner(value):\n        return value + 7\n    return {'result': [inner(value) for value in values]}\n",
                     '<first-execution-identity>', 'exec'), namespace)
        provider = namespace['provider']
        arguments = {'values': [1, 2]}
        before = outcomes.execution_binding(provider, arguments)
        with tempfile.TemporaryDirectory() as directory:
            wrapped = SessionBoundCaller(provider, requires_spark=False, outcome_directory=directory)
            self.assertEqual(wrapped([1, 2]), {'result': [8, 9]})
            self.assertEqual(outcomes.execution_binding(provider, arguments), before)
            self.assertEqual(wrapped([1, 2]), {'result': [8, 9]})
            # Keep the callable/module/qualname and source path, change nested
            # code only: bytecode fallback must still reject a different implementation.
            changed = {}
            exec(compile("def provider(values):\n    def inner(value):\n        return value + 8\n    return {'result': [inner(value) for value in values]}\n",
                         '<first-execution-identity>', 'exec'), changed)
            provider.__code__ = changed['provider'].__code__
            after = outcomes.execution_binding(provider, arguments)
            self.assertNotEqual(after['caller']['bytecodeSha256'], before['caller']['bytecodeSha256'])
            with self.assertRaisesRegex(ValueError, 'frozen_execution_binding_changed'):
                wrapped([1, 2])

    def test_code_identity_distinguishes_typed_constants(self):
        def provider(): return 1
        code = provider.__code__
        integer = outcomes._digest(outcomes._code_identity(code))
        boolean = outcomes._digest(outcomes._code_identity(code.replace(co_consts=(None, True))))
        self.assertNotEqual(integer, boolean)

    def test_received_invalid_body_closes_only_bound_failure_then_next_request_can_continue(self):
        for body in (b'{invalid json', b'\xff\xfe invalid utf8'):
            with self.subTest(body=body), tempfile.TemporaryDirectory() as directory:
                calls = []
                def provider(payload):
                    calls.append(payload)
                    outcomes.observed_response(body if payload == 'original' else b'{"ok":true}', http_status=200)
                    return {'ok': True}
                wrapped = SessionBoundCaller(provider, requires_spark=False, outcome_directory=directory)
                wrapped('original')
                path = next(Path(directory).glob('*/outcome.json')); row = json.loads(path.read_text())
                # Crash after raw receipt persisted and before parsed result.
                row.update(status='received'); row.pop('response'); row.pop('responseSha256')
                outcomes._write(path, row); before = path.read_bytes()
                failure = {'schemaVersion': outcomes.RAW_FAILURE_SCHEMA,
                    'requestSha256': row['requestSha256'], 'rawBodySha256': row['rawBodySha256'],
                    'httpStatus': 200, 'notDispatchedReason': None}
                for field, value in [('requestSha256', 'a' * 64), ('rawBodySha256', 'b' * 64),
                                     ('httpStatus', 503), ('notDispatchedReason', 'invented')]:
                    wrong = dict(failure, **{field: value})
                    with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'raw_failure_binding_mismatch'):
                        outcomes.reconcile(directory, row['requestSha256'], wrong,
                            reconciliation_evidence(row['requestSha256'], wrong, terminal_failure=True), terminal_failure=True)
                    self.assertEqual(path.read_bytes(), before)
                with self.assertRaisesRegex(ValueError, 'not_json'):
                    outcomes.reconcile(directory, row['requestSha256'], failure,
                                       reconciliation_evidence(row['requestSha256'], failure))
                self.assertEqual(path.read_bytes(), before)
                with self.assertRaisesRegex(ValueError, 'reconciliation_required'):
                    wrapped('next')
                self.assertEqual(calls, ['original'])
                outcomes.reconcile(directory, row['requestSha256'], failure,
                    reconciliation_evidence(row['requestSha256'], failure, terminal_failure=True), terminal_failure=True)
                saved = json.loads(path.read_text())
                self.assertEqual(saved['status'], 'terminal_failure')
                self.assertEqual(saved['rawBodyBase64'], row['rawBodyBase64'])
                self.assertEqual(saved['failure'], failure)
                with self.assertRaises(outcomes.TerminalOutcomeError): wrapped('original')
                self.assertEqual(wrapped('next'), {'ok': True})
                self.assertEqual(calls, ['original', 'next'])

    def test_legacy_truthy_evidence_retained_current_or_explicit_new_evidence_requires_string(self):
        for schema in (outcomes.LEGACY_SCHEMA, outcomes.V2_SCHEMA, outcomes.SCHEMA):
            with self.subTest(schema=schema), tempfile.TemporaryDirectory() as directory:
                def provider(): raise TimeoutError('unknown')
                with self.assertRaises(TimeoutError):
                    SessionBoundCaller(provider, requires_spark=False, outcome_directory=directory)()
                path = next(Path(directory).glob('*/outcome.json')); row = json.loads(path.read_text())
                row['schemaVersion'] = schema; outcomes._write(path, row); before = path.read_bytes()
                response = {'legacy': True}
                new = reconciliation_evidence(row['requestSha256'], response)
                new['terminalResponseEvidence'] = True
                with self.assertRaisesRegex(ValueError, 'terminal_evidence_required'):
                    outcomes.reconcile(directory, row['requestSha256'], response, new)
                self.assertEqual(path.read_bytes(), before)
                if schema == outcomes.SCHEMA:
                    with self.assertRaisesRegex(ValueError, 'terminal_evidence_required'):
                        outcomes.reconcile(directory, row['requestSha256'], response, {'terminalResponseEvidence': True})
                    self.assertEqual(path.read_bytes(), before)
                else:
                    outcomes.reconcile(directory, row['requestSha256'], response, {'terminalResponseEvidence': True})
                    self.assertEqual(outcomes.recover(directory, row['requestSha256'], row['purpose']), response)

    def test_legacy_truthy_evidence_does_not_waive_recorded_raw_response_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            def provider():
                outcomes.observed_response(b'{"real":1}', http_status=200)
                return {'real': 1}
            SessionBoundCaller(provider, requires_spark=False, outcome_directory=directory)()
            path = next(Path(directory).glob('*/outcome.json')); row = json.loads(path.read_text())
            row.update(schemaVersion=outcomes.V2_SCHEMA, status='received')
            row.pop('response'); row.pop('responseSha256'); outcomes._write(path, row); before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, 'recorded_response_mismatch'):
                outcomes.reconcile(directory, row['requestSha256'], {'fake':2}, {'terminalResponseEvidence': True})
            self.assertEqual(path.read_bytes(), before)
            outcomes.reconcile(directory, row['requestSha256'], {'real':1}, {'terminalResponseEvidence': True})
            self.assertEqual(outcomes.recover(directory, row['requestSha256'], row['purpose']), {'real':1})

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
                               reconciliation_evidence(row['requestSha256'], {'recovered':True}))
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
        from scripts import tongxing_host  # noqa: F401  binds the production package ports
        from tongxing_production.workflows.dual_pdf import pipeline as pipeline
        with tempfile.TemporaryDirectory() as tmp, \
             patch.dict('os.environ', {'SERMON_ACCOUNTING_DIR':tmp}), \
             patch('tongxing_production.compute.budget_capability.require_bounded_api_payload'), \
             patch.object(legacy_openai, 'json_request', side_effect=TimeoutError('unknown')) as request, \
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
                reconciliation_evidence(row['requestSha256'], {'httpStatus':429}, terminal_failure=True),terminal_failure=True)
            with self.assertRaises(outcomes.TerminalOutcomeError): wrapped({'request':1})

    def test_legacy_returned_receipt_remains_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            wrapped=SessionBoundCaller(lambda: {'ok':True},requires_spark=False,outcome_directory=tmp)
            wrapped(); path=next(Path(tmp).glob('*/outcome.json'))
            row=json.loads(path.read_text());row['schemaVersion']=outcomes.LEGACY_SCHEMA
            path.write_text(json.dumps(row))
            self.assertEqual(outcomes.recover(tmp,row['requestSha256'],'production-model-call'),{'ok':True})

    def test_confirmed_no_dispatch_terminal_failure_preserves_reason(self):
        from tongxing_production.workflows.dual_pdf.pipeline import PreDispatchRejection
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
                with patch('tongxing_production.compute.openai_runtime.selected_route',return_value=route):
                    wrapped=SessionBoundCaller(first,requires_spark=False,outcome_directory=tmp)
                    wrapped('secret-original',{'request':1})
                    old=outcomes.request_identity(first,('secret-original',{'request':1}),{},wrapped.purpose)
                    newroute={**route,'environment':'prod','credentialAlias':'tongxing-prod-runtime'} if kind=='route' else route
                    with patch('tongxing_production.compute.openai_runtime.selected_route',return_value=newroute):
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
