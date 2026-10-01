"""Scheduling/input-boundary tests; session business validators are tested separately."""
import copy
import io
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import sermon_diagnostic_prefect_flow as flow
from scripts import sermon_review_contracts as c
from scripts import sermon_log_profile as profile


class SessionFixture:
    """Explicit orchestration-only fixture, never accepted by production API."""
    def __init__(self, root):
        self.root = root
        self.offline_fixture = True
        self.evidence_mode = 'synthetic'
        self.binding = {'fixtureId': 'dag-unit-fixture', 'storeSha256': '1' * 64}
        self.context = {'fixture': True}
        self.subject = SimpleNamespace(config={'runId': '2' * 64}, executor=
            flow.offline.OfflineHTTPTransport(lambda *a, **k: {}, fixture_id='dag-unit-fixture'))
        self.calls = []
        self.failed = set()
        self.unknown = set()

    def _path(self, value, *, plugin=False):
        path = flow._path(str(value))
        c.require(self.root in path.parents, 'diagnostic_dag_path_outside_scope')
        return path

    def inspect_source(self):
        self.calls.append(('source', None))
        return {'humanAcceptance': 'pending', 'productionEligible': False, 'sourceSha256': '3' * 64}

    def run_locale(self, locale, spec, *, depends_on=None):
        self.calls.append(('locale', locale))
        if locale in self.unknown: raise TimeoutError('synthetic unknown')
        if locale in self.failed: return {'status': 'blocked', 'groups': []}
        root = self.root / 'locales' / locale / 'machine-candidates' / 'synthetic'
        root.mkdir(parents=True, exist_ok=True)
        candidate = {'targetLocale': locale, 'releaseEligible': False, 'humanReview': {'translation': 'pending'}}
        (root / 'candidate.json').write_bytes(c.canonical_bytes(candidate))
        return {'status': 'waiting_human', 'candidateSha256': c.canonical_sha256(candidate),
                'output': str(root), 'groups': []}

    def preview(self, locale, spec, *, depends_on=None):
        self.calls.append(('preview', locale))
        return {'status': 'preview_only', 'humanAcceptance': 'pending', 'productionEligible': False,
                'offlineFixture': True, 'receiptFileSha256': c.canonical_sha256({'locale': locale})}

    def inspect_delivery(self, previews, expected_locales):
        self.calls.append(('delivery', None))
        assert set(previews) == set(expected_locales)
        result = {'status': 'diagnostic_traversal_complete', 'humanAcceptance': 'pending',
                  'productionEligible': False, 'publicationAuthorized': False, 'formalAudioPackageCreated': False}
        return {**result, 'resultSha256': c.canonical_sha256(result)}


def config_fixture(root, locales=('zh-Hans', 'ko')):
    root.mkdir(exist_ok=True)
    def write(name, value):
        path = root / name
        path.write_bytes(c.canonical_bytes(value))
        return str(path)
    common = {key: write(key + '.json', {}) for key in ('source', 'anchor', 'rubric', 'adapter', 'registry')}
    plugin = root / 'plugin.py'; plugin.write_text('# inert fixture, never executed\n')
    checkpoint = root / 'checkpoint'; checkpoint.mkdir()
    (checkpoint / 'model.safetensors').write_bytes(b'never loaded')
    (checkpoint / 'config.json').write_text('{}')
    checkpoint_map = write('checkpoint-map.json', {'checkpoints': [{'path': str(checkpoint)}]})
    operations = write('operations.json', {})
    lanes = {}
    for locale in locales:
        policy = write(locale + '.policy.json', {'targetLocale': locale})
        spec = {key: common[key] for key in ('source', 'anchor', 'rubric')}
        spec.update(policy=policy, graph=[], groupPlan=[], pluginPath=str(plugin), pluginSha256='4' * 64)
        preview = {'paths': {key: common[key] for key in ('source', 'anchor', 'adapter', 'registry')},
            'checkpoint_map_path': checkpoint_map, 'operation_policies_path': operations,
            'strict_rubric_path': common['rubric'], 'out': str(root / 'diagnostic-previews' / locale / 'fixture'), 'execute': False}
        preview['paths']['policy'] = policy
        lanes[locale] = {'localeSpec': spec, 'previewSpec': preview}
    return {'schemaVersion': flow.SCHEMA, 'locales': lanes}


class DiagnosticFlowTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.config = config_fixture(self.root)
        self.session = SessionFixture(self.root)
        self.enterContext(patch.object(flow, '_session_class', return_value=SessionFixture))
        # Original worker receipt validation is covered by the actual integration
        # fixture, not these orchestration-only tests.
        self.enterContext(patch.object(flow.preview_worker, 'validate_preview_receipt', side_effect=lambda *args: args[-1]))

    def execute(self, dag):
        with profile.session(self.root / 'logs', 'diagnostic-flow-unit', work_kind='engineering', evidence_mode='synthetic'):
            dag.freeze()
            return {node[0]: dag.execute(node[0]) for node in dag.nodes}

    def checkpoint_contract(self, config):
        # Orchestration inventory only; actual complete-tree/declaration
        # validation is exercised by the worker and fresh-entry contracts.
        auxiliary=self.root/'speech-tokenizer.bin';auxiliary.write_bytes(b'inert auxiliary weights')
        manifest=self.root/'checkpoint-manifest.json'
        manifest.write_bytes(c.canonical_bytes({'files':[{'path':str(auxiliary)}]}))
        declaration=self.root/'checkpoint-stage-declaration.json';declaration.write_text('{}')
        for lane in config['locales'].values():
            lane['previewSpec'].update(checkpoint_manifest_path=str(manifest),
                checkpoint_stage_declaration_path=str(declaration))
        return manifest,declaration,auxiliary

    def test_fixed_graph_preview_candidate_not_caller_supplied_and_all_gates_pending(self):
        dag = flow.DiagnosticDAG(self.session, self.config)
        self.assertEqual(dag.nodes[0], ('source.existing', 'source', None, ()))
        self.assertEqual(len(dag.nodes), 6)
        results = self.execute(dag)
        self.assertTrue(results['delivery.readonly']['readyForDownstream'])
        self.assertEqual(self.session.calls, [('source', None), ('locale', 'ko'), ('preview', 'ko'),
                                             ('locale', 'zh-Hans'), ('preview', 'zh-Hans'), ('delivery', None)])
        self.assertTrue(all(row['humanAcceptance'] == 'pending' and not row['productionEligible'] for row in results.values()))
        from scripts import sermon_accounting as accounting
        events, errors = accounting.read_events(self.root / 'logs'); self.assertFalse(errors)
        starts = {event['spanId']: event for event in events if event['event'] == 'stage_started'}
        self.assertEqual(starts[results['preview.ko']['completionSpans'][0]]['dependsOn'],
                         results['text.ko']['completionSpans'])
        self.assertTrue(list((dag.root / 'results' / 'delivery.readonly').glob('*.json')))

    def test_one_failed_locale_blocks_only_its_preview_and_final_inspection(self):
        self.session.failed.add('ko')
        results = self.execute(flow.DiagnosticDAG(self.session, self.config))
        self.assertFalse(results['text.ko']['readyForDownstream'])
        self.assertEqual(results['preview.ko']['reason'], 'upstream_not_completed')
        self.assertTrue(results['preview.zh-Hans']['readyForDownstream'])
        self.assertEqual(results['delivery.readonly']['reason'], 'upstream_not_completed')
        self.assertNotIn(('preview', 'ko'), self.session.calls)
        self.assertNotIn(('delivery', None), self.session.calls)

    def test_unknown_does_not_become_retry_or_success(self):
        self.session.unknown.add('ko')
        results = self.execute(flow.DiagnosticDAG(self.session, self.config))
        self.assertEqual(results['text.ko']['executionStatus'], 'outcome_unknown')
        self.assertIsNone(results['text.ko']['processed'])
        self.assertEqual(self.session.calls.count(('locale', 'ko')), 1)
        self.assertTrue(results['preview.zh-Hans']['readyForDownstream'])

    def test_changed_static_file_blocks_before_session_call(self):
        dag = flow.DiagnosticDAG(self.session, self.config)
        dag.freeze()
        policy = Path(self.config['locales']['ko']['localeSpec']['policy'])
        policy.write_text('{"targetLocale":"es"}')
        with profile.session(self.root / 'logs', 'diagnostic-flow-unit', work_kind='engineering', evidence_mode='synthetic'):
            result = dag.execute('source.existing')
        self.assertEqual(result['executionStatus'], 'blocked')
        self.assertEqual(self.session.calls, [])

    def test_live_v2_runtime_manifest_is_accepted_and_frozen_as_static_input(self):
        # This only exercises the DAG contract/inventory; no native runtime,
        # model, transport or session callback is invoked by the fixture.
        self.session.offline_fixture=False
        config=copy.deepcopy(self.config)
        manifest=self.root/'runtime-manifest.json'
        runtime_file=self.root/'runtime-binding-file';runtime_file.write_bytes(b'inert runtime fixture')
        manifest.write_bytes(c.canonical_bytes({'fixture':'inventory-only-not-native',
            'files':[{'path':str(runtime_file),'sha256':c.bytes_sha256(runtime_file.read_bytes())}]}))
        for lane in config['locales'].values():
            lane['previewSpec'].update(execute=True,runtime_manifest_path=str(manifest))
        checkpoint,declaration,auxiliary=self.checkpoint_contract(config)
        dag=flow.DiagnosticDAG(self.session,config)
        self.assertEqual(dag.binding['inputFiles'][str(manifest)],c.bytes_sha256(manifest.read_bytes()))
        self.assertEqual(dag.binding['inputFiles'][str(runtime_file)],c.bytes_sha256(runtime_file.read_bytes()))
        for path in (checkpoint,declaration,auxiliary):
            self.assertEqual(dag.binding['inputFiles'][str(path)],c.bytes_sha256(path.read_bytes()))
        dag.freeze()
        original=manifest.read_bytes()
        manifest.write_text('{"changed":true}')
        with self.assertRaisesRegex(c.ContractError,'diagnostic_flow_frozen_inputs_changed'):
            dag._check()
        manifest.write_bytes(original)
        runtime_file.write_bytes(b'inert runtime fixture')
        auxiliary.write_bytes(b'changed auxiliary weights')
        with self.assertRaisesRegex(c.ContractError,'diagnostic_flow_frozen_inputs_changed'):
            dag._check()
        auxiliary.write_bytes(b'inert auxiliary weights')
        runtime_file.write_bytes(b'changed runtime fixture')
        with self.assertRaisesRegex(c.ContractError,'diagnostic_flow_frozen_inputs_changed'):
            dag._check()
        self.assertEqual(self.session.calls,[])

    def test_checkpoint_inputs_required_for_live_and_forbidden_for_fixture_before_read(self):
        config=copy.deepcopy(self.config);self.session.offline_fixture=False
        for lane in config['locales'].values():
            lane['previewSpec'].update(execute=True,runtime_manifest_path=str(self.root/'runtime.json'))
        with patch.object(flow.public,'read_snapshot',side_effect=AssertionError('unexpected input read')):
            with self.assertRaisesRegex(c.ContractError,'diagnostic_flow_preview_checkpoint_manifest_required'):
                flow.DiagnosticDAG(self.session,config)
        self.session.offline_fixture=True;config=copy.deepcopy(self.config)
        for lane in config['locales'].values():
            lane['previewSpec']['checkpoint_manifest_path']=str(self.root/'checkpoint.json')
        with patch.object(flow.public,'read_snapshot',side_effect=AssertionError('unexpected input read')):
            with self.assertRaisesRegex(c.ContractError,'diagnostic_flow_fixture_cannot_claim_checkpoint_manifest'):
                flow.DiagnosticDAG(self.session,config)
        self.assertEqual(self.session.calls,[])

    def test_live_manifest_required_and_fixture_cannot_claim_native_before_read(self):
        config=copy.deepcopy(self.config)
        for lane in config['locales'].values():lane['previewSpec']['execute']=True
        self.session.offline_fixture=False
        with patch.object(flow.public,'read_snapshot',side_effect=AssertionError('unexpected input read')):
            with self.assertRaisesRegex(c.ContractError,'diagnostic_flow_preview_runtime_manifest_required'):
                flow.DiagnosticDAG(self.session,config)
        self.session.offline_fixture=True
        config=copy.deepcopy(self.config)
        for lane in config['locales'].values():
            lane['previewSpec']['runtime_manifest_path']=str(self.root/'untrusted-runtime.json')
        with patch.object(flow.public,'read_snapshot',side_effect=AssertionError('unexpected input read')):
            with self.assertRaisesRegex(c.ContractError,'diagnostic_flow_fixture_cannot_claim_native_runtime'):
                flow.DiagnosticDAG(self.session,config)
        self.assertEqual(self.session.calls,[])

    def test_live_manifest_must_be_caller_selected_absolute_nonredirected_file(self):
        self.session.offline_fixture=False
        config=copy.deepcopy(self.config)
        manifest=self.root/'runtime.json';manifest.write_text('{}')
        for lane in config['locales'].values():
            lane['previewSpec'].update(execute=True,runtime_manifest_path=str(manifest))
        self.checkpoint_contract(config)
        lane=config['locales']['ko']['previewSpec']
        lane['runtime_manifest_path']='relative.json'
        with self.assertRaisesRegex(c.ContractError,'diagnostic_flow_absolute_path_required'):
            flow.DiagnosticDAG(self.session,config)
        outside=Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        manifest=outside/'runtime.json';manifest.write_text('{}')
        link=self.root/'redirected-runtime.json';link.symlink_to(manifest)
        lane['runtime_manifest_path']=str(link)
        with self.assertRaisesRegex(ValueError,'Symlink'):
            flow.DiagnosticDAG(self.session,config)
        self.assertEqual(self.session.calls,[])

    def test_relative_paths_candidate_injection_live_preview_and_outside_output_rejected(self):
        changes = [lambda lane: lane['localeSpec'].update(policy='relative.json'),
                   lambda lane: lane['previewSpec']['paths'].update(candidate=str(self.root / 'candidate.json')),
                   lambda lane: lane['previewSpec'].update(execute=True),
                   lambda lane: lane['previewSpec'].update(out=str(self.root.parent / 'outside-preview'))]
        for change in changes:
            config = copy.deepcopy(self.config); change(config['locales']['ko'])
            with self.assertRaises(ValueError): flow.DiagnosticDAG(self.session, config)
        self.assertEqual(self.session.calls, [])
        self.assertFalse((self.root / 'diagnostic-prefect').exists())

    def test_external_direct_nested_and_checkpoint_inputs_are_rejected_before_external_reads(self):
        outside = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        sentinel = outside / 'private.json'; sentinel.write_text('{"private":"never read"}')
        config = copy.deepcopy(self.config)
        config['locales']['ko']['localeSpec']['source'] = str(sentinel)
        config['locales']['ko']['previewSpec']['paths']['source'] = str(sentinel)
        with patch.object(flow.public, 'read_snapshot', side_effect=AssertionError('unexpected input read')):
            with self.assertRaisesRegex(ValueError, 'outside_scope'): flow.DiagnosticDAG(self.session, config)
        registry = Path(self.config['locales']['ko']['previewSpec']['paths']['registry'])
        original = Path.open
        def guarded(path, *args, **kwargs):
            if path.resolve().is_relative_to(outside): raise AssertionError('external input read')
            return original(path, *args, **kwargs)
        registry.write_text(json.dumps({'authorization': {'path': str(sentinel)}}))
        with patch.object(Path, 'open', guarded), self.assertRaisesRegex(ValueError, 'outside_scope'):
            flow.DiagnosticDAG(self.session, self.config)
        registry.write_text('{}')
        mapping = Path(self.config['locales']['ko']['previewSpec']['checkpoint_map_path'])
        mapping.write_text(json.dumps({'checkpoints': [{'path': str(outside)}]}))
        with patch.object(Path, 'open', guarded), self.assertRaisesRegex(ValueError, 'outside_scope'):
            flow.DiagnosticDAG(self.session, self.config)
        self.assertEqual(list(outside.iterdir()), [sentinel])
        self.assertFalse((self.root / 'diagnostic-prefect').exists())
        self.assertEqual(self.session.calls, [])

    def test_redirected_accounting_results_and_observations_reject_before_writes_or_lock(self):
        outside = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        dag = flow.DiagnosticDAG(self.session, self.config)
        dag.root.mkdir(parents=True)
        for name in ('accounting', 'results', 'observations'):
            link = dag.root / name; link.symlink_to(outside, target_is_directory=True)
            with self.subTest(name=name):
                with self.assertRaises(ValueError): dag.freeze()
                with self.assertRaises(ValueError): flow.run(self.session, self.config)
                self.assertEqual(list(outside.iterdir()), [])
                self.assertFalse((dag.root.parent / '.harness-locks').exists())
            link.unlink()
        self.assertEqual(self.session.calls, [])

    def test_replay_keeps_immutable_result_files_and_calls_original_session_again(self):
        first = flow.DiagnosticDAG(self.session, self.config)
        self.execute(first)
        saved = {path: path.read_bytes() for path in (first.root / 'results').rglob('*.json')}
        second = flow.DiagnosticDAG(self.session, self.config)
        self.execute(second)
        self.assertEqual(first.root, second.root)
        self.assertEqual(saved, {path: path.read_bytes() for path in (second.root / 'results').rglob('*.json')})
        # Business ledgers, not this orchestration adapter, decide cache replay.
        self.assertEqual(self.session.calls.count(('locale', 'ko')), 2)

    def test_failure_projection_preserves_safe_code_without_exception_body(self):
        self.session.inspect_source = lambda: (_ for _ in ()).throw(ValueError('diagnostic_original_source_changed'))
        observed = self.execute(flow.DiagnosticDAG(self.session, self.config))
        self.assertEqual(observed['source.existing']['reason'], 'diagnostic_original_source_changed')
        self.session.inspect_source = lambda: (_ for _ in ()).throw(ValueError('secret /private/path or transcript'))
        observed = self.execute(flow.DiagnosticDAG(self.session, self.config))
        self.assertEqual(observed['source.existing']['reason'], 'callback_or_evidence_not_confirmed')

    def test_plain_callable_or_transport_cannot_replace_trusted_session(self):
        self.session.subject.executor = lambda *args: {}
        with self.assertRaisesRegex(ValueError, 'offline_session_required'):
            flow.DiagnosticDAG(self.session, self.config)

    def test_static_http_fixture_uses_exact_request_bytes_only(self):
        from urllib.request import Request
        fixture = self.root / 'responses.json'
        fixture.write_text(json.dumps({'fixtureId': 'static-http', 'responses': {
            c.bytes_sha256(b'known'): {'id': 'fixture-response'}}}))
        transport = flow.fixture_transport(fixture)
        request = Request('https://example.invalid', data=b'known', headers={'Authorization': 'Bearer offline-fixture'})
        self.assertEqual(transport(request, 1, deadline=2), {'id': 'fixture-response'})
        request.data = b'unknown'
        with self.assertRaisesRegex(ValueError, 'response_missing'): transport(request, 1, deadline=2)

    def test_cli_requires_explicit_mode_and_required_inputs(self):
        for missing in ([], ['--plan', '/a', '--continuation', '/b', '--spec', '/c', '--fixture-responses', '/d']):
            with patch('sys.stderr', new=io.StringIO()), self.assertRaises(SystemExit): flow.main(missing)


class ActualDiagnosticFlowTests(unittest.TestCase):
    def test_actual_source_strict_locale_worker_delivery_and_replay_preserve_original_store(self):
        from scripts import sermon_accounting as accounting
        from scripts import sermon_diagnostic_dag_session as sessions
        from scripts import sermon_review_budget as budget
        from tests.diagnostic_dag_fixture import DiagnosticDAGFixture
        f = DiagnosticDAGFixture(); self.addCleanup(f.doCleanups); f.setUp()
        config = {'schemaVersion': flow.SCHEMA, 'locales': {locale: {
            'localeSpec': f.locale_specs[locale], 'previewSpec': f.preview_specs[locale]} for locale in f.locale_specs}}
        with patch.object(accounting, 'execution_identity', return_value=f.execution_identity):
            session = sessions.DiagnosticSession(f.plan, f.continuation, offline_transport=f.transport)
            dag = flow.DiagnosticDAG(session, config)
            path = f.root / 'budget' / budget.STORE_ID / 'provider-run/state.json'
            original = c.read_snapshot(path)[0]
            from scripts import sermon_log_profile as profile
            with profile.session(f.root/'flow-logs', 'flow-context-check', work_kind='control',
                                 evidence_mode='synthetic', production_run_id=f.context['runId']):
                dag.freeze()
                results = {node[0]: dag.execute(node[0]) for node in dag.nodes}
                self.assertTrue(results['delivery.readonly']['readyForDownstream'], results)
                self.assertEqual(results['delivery.readonly']['businessStatus'], 'diagnostic_traversal_complete')
                worker_receipt = dag.results['preview.zh-Hans']['receiptPath']
                worker_bytes = Path(worker_receipt).read_bytes()
                replay_session = sessions.DiagnosticSession(f.plan, f.continuation, offline_transport=f.transport)
                replay = flow.DiagnosticDAG(replay_session, config); replay.freeze()
                again = {node[0]: replay.execute(node[0]) for node in replay.nodes}
                self.assertTrue(again['delivery.readonly']['readyForDownstream'], again)
                self.assertEqual(Path(worker_receipt).read_bytes(), worker_bytes)
            final = c.read_snapshot(path)[0]
        rows, errors = accounting.read_events(f.root/'flow-logs')
        self.assertFalse(errors)
        model_events = [row for row in rows if row.get('executorType') == 'production_model']
        self.assertTrue(model_events)
        self.assertTrue(all(row['workKind'] == 'production' and row['evidenceMode'] == 'synthetic'
                            for row in model_events), model_events)
        dag_events = [row for row in rows if row.get('event') in {'stage_started', 'stage_finished'} and (row.get('stage') or '').startswith('diagnostic.dag.')]
        self.assertTrue(dag_events)
        self.assertTrue(all(row['workKind'] == 'control' for row in dag_events), dag_events)
        self.assertEqual(len(f.transport.observations), 6)
        self.assertEqual(original['startedMonotonic'], final['startedMonotonic'])
        self.assertEqual(original['config'], final['config'])
        for key, value in original['requests'].items(): self.assertEqual(final['requests'][key], value)
        self.assertTrue(all(row['humanAcceptance'] == 'pending' and not row['productionEligible'] for row in results.values()))


@unittest.skipUnless(os.environ.get('SERMON_TEST_PREFECT') == '1', 'optional actual local Prefect SDK')
class ActualPrefectRuntimeTests(unittest.TestCase):
    def test_fresh_clean_process_actual_session_workers_and_readonly_delivery(self):
        script = r'''
import sys
sys.path.insert(0, sys.argv[1])
from scripts import sermon_diagnostic_prefect_flow as flow
from scripts.sermon_diagnostic_dag_session import DiagnosticSession
from scripts import sermon_review_budget as budget
from scripts import sermon_review_contracts as c
from tests.diagnostic_dag_fixture import DiagnosticDAGFixture
fixture=DiagnosticDAGFixture(); fixture.setUp()
config={'schemaVersion':flow.SCHEMA,'locales':{locale:{'localeSpec':fixture.locale_specs[locale],
    'previewSpec':fixture.preview_specs[locale]} for locale in fixture.locale_specs}}
state=fixture.root/'budget'/budget.STORE_ID/'provider-run/state.json'
before=c.read_snapshot(state)[0]
session=DiagnosticSession(fixture.plan,fixture.continuation,offline_transport=fixture.transport)
result=flow.run(session,config)
assert result['status']=='diagnostic_traversal_complete', result
assert len(fixture.transport.observations)==6
assert all(row['humanAcceptance']=='pending' and not row['productionEligible'] for row in result['nodes'].values())
assert len({row['flowRunId'] for row in result['nodes'].values()})==1
after=c.read_snapshot(state)[0]
assert before['startedMonotonic']==after['startedMonotonic']
assert all(after['requests'][key]==value for key,value in before['requests'].items())
print('actual-diagnostic-prefect-ok')
'''
        with tempfile.TemporaryDirectory() as root:
            result = subprocess.run([sys.executable, '-c', script, str(flow.pilot.REPO)],
                cwd=root, capture_output=True, text=True, timeout=180)
        self.assertEqual(result.returncode, 0, result.stdout[-3000:] + result.stderr[-7000:])
        self.assertIn('actual-diagnostic-prefect-ok', result.stdout)


if __name__ == '__main__':
    unittest.main()
