"""One bounded Fresh Source → strict text → mock jobs → read-only join graph.

Component checks replace only the clean-code admission identity and SDK version
markers. They exercise real fixed callbacks, accounting, jobs and byte checks;
they are not proof of Prefect scheduling. Opt-in SDK tests use clean committed
code in separate processes with no execution-identity or engine substitution.
No interruption, crash-window, missing-acknowledgement or tamper cases live here.
"""
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import sermon_accounting as accounting
from scripts import sermon_completion as completion
from scripts import sermon_fresh_full_dag as dag
from scripts import sermon_fresh_source_prefect as source_engine
from scripts import sermon_log_contract as logs
from scripts import sermon_mock_tts_contract as mock_contract
from scripts import sermon_public_snapshot as public
from scripts import sermon_review_contracts as c
from scripts import weekly_pipeline_report as weekly
from tests.fresh_full_dag_fixture import (
    FullFreshDAGFixture, LOCALE, SOURCE_NODES, UNITS,
    assert_provider_bounds_unchanged, immutable_files, wait_for_original_jobs, preserve_full_evidence,
)


def assert_qualifications(value):
    assert value['productionEligible'] is False, value
    assert value['publicationAuthorized'] is False, value
    assert value['humanAcceptance'] == 'pending', value
    assert value['evidenceMode'] == 'synthetic', value


def assert_canonical_evidence(root, *, expected_calls=6):
    """Use the existing V1 validator and public read-only report consumer."""
    events, errors = accounting.read_events(root)
    assert not errors, errors
    assert events
    assert {event['contractVersion'] for event in events} == {logs.VERSION}
    for event in events:
        logs.validate_event(event)
    assert logs.replay_integrity(events)['status'] == 'consistent'
    assert len({event['runId'] for event in events}) == 1
    receipts = [event for event in events if event['event'] == 'api_attempt']
    assert len(receipts) == expected_calls
    requested = Counter(event['requestedModel'] for event in receipts)
    returned = Counter(event['model'] for event in receipts)
    assert requested == {'gpt-transcribe': 1, 'gpt-6-astra': 3, 'gpt-6-sol': 2}, requested
    # Duration-billed ASR omits the returned model name and token usage. V1
    # preserves those as unknown instead of copying the requested identity.
    assert returned == {None: 1, 'gpt-6-astra': 3, 'gpt-6-sol': 2}, returned
    audio = next(event for event in receipts if event['requestedModel'] == 'gpt-transcribe')
    assert audio['usage']['inputTokens'] is None and audio['usage']['outputTokens'] is None, audio['usage']
    report = weekly.project(root)
    assert report['reportGenerationNetworkCalls'] == 0
    assert report['receiptIntegrity']['status'] == 'consistent'
    assert report['observedProviderCalls']['directReceiptCount'] == expected_calls, report
    assert sum(len(run['usage']['directReceipts']) for run in report['runs']) == expected_calls
    assert all(run['usage']['combinedTokenTotal'] is None for run in report['runs'])
    return events


def assert_layers_and_accounting(layers, projected, *, new_calls):
    declared = layers['declaredNodes']
    assert set(declared) == set(SOURCE_NODES) | {'text.'+LOCALE, 'join.'+LOCALE, 'final.readonly'} | {
        'mock.'+op+'.'+unit for op in ('input', 'submit', 'observe', 'verify', 'gate') for unit in UNITS}
    assert all(declared[name] == 1 for name in SOURCE_NODES[:-1])
    assert declared['locale.freeze'] == declared['text.'+LOCALE] == 2
    assert all(declared[name] == 3 for name in declared if name.startswith('mock.'))
    assert declared['join.'+LOCALE] == declared['final.readonly'] == 4
    assert not layers['unmappedSpanIds'], layers
    assert layers['spans']
    containers = layers['containerSpans']
    assert containers, layers
    mapped_ids = {row['spanId'] for row in layers['spans']}
    container_ids = {row['spanId'] for row in containers}
    assert len(mapped_ids) == len(layers['spans'])
    assert len(container_ids) == len(containers) and not mapped_ids & container_ids
    assert all(row['layer'] is None and row['workUnitId'] is None and row['workflowId']
        and row['measurementScope'] == 'containing_workflow_all_layers_do_not_sum_with_children'
        for row in containers), containers
    assert all(row['ownerNodeId'] in declared and row['layer'] == declared[row['ownerNodeId']]
        for row in layers['spans'])
    assert projected['canonicalDirectApiAttempts'] == projected['summaryApiAttempts'] == 6, projected
    assert projected['invocationDirectApiAttempts'] == new_calls, projected
    assert projected['directCallsByLayer'] == {'1': 2, '2': 4, '3': 0, '4': 0}, projected
    assert projected['replayIntegrity'] == 'consistent', projected
    assert projected['receiptIntegrity'] == 'consistent', projected
    assert projected['realProviderCalls'] == 0
    assert projected['mockTTS'] == {'inputTokens': None, 'outputTokens': None,
        'estimatedUsd': None, 'usageStatus': 'not_applicable', 'costStatus': 'not_applicable'}


class FreshFullDAGComponents(unittest.TestCase):
    def setUp(self):
        self.f = FullFreshDAGFixture(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.enterContext(patch.object(accounting, 'execution_identity', return_value=self.f.plan['executionIdentity']))
        self.enterContext(patch.object(dag, 'version', return_value='component-only-no-sdk'))
        self.enterContext(patch.object(source_engine, 'version', return_value='component-only-no-sdk'))

    def make(self, config=None, *, recovery=None):
        return dag.FullFreshDAG(self.f.session(), self.f.recipe, self.f.authorization,
            self.f.locales, config or self.f.dag_config(), recovery=recovery)

    def execute_components(self, current):
        current.freeze()
        with current.stream.context(), accounting.accounting_session(current.root/'accounting', 'full_fresh_component'):
            current.activate()
            for node in current.nodes:
                current.execute(node['id'], [current.observations[key] for key in node['dependsOn']])
            current.observed_edges()
        return current.observations

    def projections(self, current):
        with current.stream.context():
            return current.layer_evidence(), current.accounting_projection()

    def test_full_source_text_mock_byte_gate_and_receipt_only_repeat(self):
        first = self.make(); observed = self.execute_components(first)
        self.assertEqual(len(first.nodes), 19)
        self.assertNotIn('source.existing', observed)
        self.assertTrue(observed['final.readonly']['readyForDownstream'], observed)
        self.assertEqual(len(self.f.transport.observations), 6)
        self.assertEqual(sum(value.get('newDispatch') is True for value in first.results.values()), 2)
        self.assertEqual(first.results['locale.freeze']['specs'][LOCALE]['groupPlan'], self.f.expected_groups)
        source = public.read_snapshot(self.f.root/'source.json')[0]
        self.assertFalse(source['translationEligible'])
        self.assertFalse(source['review']['humanApproval'])
        for unit in UNITS:
            checked = first.results['mock.verify.'+unit]['verification']
            self.assertEqual(checked['admissionStatus'], 'verified_synthetic')
            with first.stream.context():
                request, path = first._request(unit)
            artifact_path = path.parent.parent/'worker'/'fixture.wav'
            verified = mock_contract.verify_wav(artifact_path, request, checked['artifact'])
            self.assertEqual(verified, checked['artifact'])
            self.assertEqual(c.bytes_sha256(artifact_path.read_bytes()), checked['artifact']['sha256'])
            gate = first.results['mock.gate.'+unit]['gate']
            self.assertEqual(gate['fixtureGate'], 'passed')
            self.assertEqual(gate['reviewScope'], 'synthetic_fixture_bytes_only')
            self.assertIn('wav_full_decode', gate['requiredChecks'])
        original = immutable_files(self.f.root)
        self.assertTrue(original)
        state = json.loads(self.f.provider_state_path.read_text())
        assert_provider_bounds_unchanged(self.f.initial_provider_state, state, expected_requests=6)
        second = self.make(); repeated = self.execute_components(second)
        self.assertEqual(first.root, second.root)
        self.assertTrue(repeated['final.readonly']['readyForDownstream'], repeated)
        self.assertEqual(len(self.f.transport.observations), 6)
        self.assertEqual(sum(value.get('newDispatch') is True for value in second.results.values()), 0)
        self.assertEqual(original, {name: Path(name).read_bytes() for name in original})
        self.assertEqual(state, json.loads(self.f.provider_state_path.read_text()))
        events = assert_canonical_evidence(second.stream.directory)
        for row in repeated.values():
            assert_qualifications(row)
            for handle in row['completionHandles']:
                completion.validate_synthetic(handle, events, production_run_id=self.f.plan['providerConfig']['runId'])
        final = second.results['final.readonly']
        assert_qualifications(final)
        self.assertFalse(final['formalAudioPackageCreated'])
        self.assertEqual(final['listeningAcceptance'], 'not_performed')
        self.assertFalse((self.f.root/'diagnostic-previews').exists())
        with second.stream.context():
            self.assertEqual(len(second.observed_edges()), 19)
        layers, projected = self.projections(second)
        assert_layers_and_accounting(layers, projected, new_calls=0)

    def test_confirmed_failed_unit_retry_reuses_successful_neighbor(self):
        config = self.f.dag_config(faults={UNITS[0]: {
            'mode': 'fail_after_render', 'queueDelaySeconds': 0, 'runDelaySeconds': 0}})
        first = self.make(config); observed = self.execute_components(first)
        self.assertEqual(observed['mock.observe.'+UNITS[0]]['executionStatus'], 'failed', observed)
        self.assertTrue(observed['mock.gate.'+UNITS[1]]['readyForDownstream'], observed)
        for key in ('mock.verify.'+UNITS[0], 'mock.gate.'+UNITS[0], 'join.'+LOCALE, 'final.readonly'):
            self.assertFalse(observed[key]['readyForDownstream'], key)
            self.assertEqual(observed[key]['reason'], 'upstream_not_completed')
        self.assertNotIn('final.readonly', first.results)
        failed = first.results['mock.input.'+UNITS[0]]
        neighbor = first.results['mock.input.'+UNITS[1]]
        originals = immutable_files(self.f.root)
        repeated = self.make(config, recovery={UNITS[0]: failed['requestSha256']})
        observed = self.execute_components(repeated)
        self.assertTrue(observed['final.readonly']['readyForDownstream'], observed)
        self.assertEqual(sum(value.get('newDispatch') is True for value in repeated.results.values()), 1)
        self.assertEqual(repeated.results['mock.input.'+UNITS[0]]['attemptNumber'], 2)
        self.assertNotEqual(repeated.results['mock.input.'+UNITS[0]]['jobId'], failed['jobId'])
        self.assertEqual(repeated.results['mock.input.'+UNITS[1]]['jobId'], neighbor['jobId'])
        self.assertEqual(repeated.results['mock.input.'+UNITS[1]]['attemptNumber'], 1)
        self.assertEqual(originals, {name: Path(name).read_bytes() for name in originals})
        self.assertEqual(len(self.f.transport.observations), 6)
        assert_provider_bounds_unchanged(self.f.initial_provider_state,
            json.loads(self.f.provider_state_path.read_text()), expected_requests=6)

    def test_ordinary_timeout_rejects_retry_then_reconciles_original_receipt(self):
        config = self.f.dag_config(faults={UNITS[0]: {
            'mode': 'none', 'queueDelaySeconds': 0, 'runDelaySeconds': 2}}, observation_timeout=.01)
        first = self.make(config); observed = self.execute_components(first)
        self.assertEqual(observed['mock.observe.'+UNITS[0]]['executionStatus'], 'outcome_unknown', observed)
        self.assertFalse(observed['final.readonly']['readyForDownstream'])
        originals = {str(path): path.read_bytes() for path in (first.root/'mock-control'/'observations').glob('*.json')}
        rejected = self.make(config, recovery={UNITS[0]: first.results['mock.input.'+UNITS[0]]['requestSha256']})
        rejected.freeze()
        with rejected.stream.context(), self.assertRaises((ValueError, OSError)):
            rejected.activate()
        self.assertEqual(len(list((first.root/'mock-control'/'intents').glob('*.json'))), 2)
        wait_for_original_jobs(first.root)
        artifacts = immutable_files(self.f.root)
        repeated = self.make(config); observed = self.execute_components(repeated)
        self.assertTrue(observed['final.readonly']['readyForDownstream'], observed)
        self.assertEqual(sum(value.get('newDispatch') is True for value in repeated.results.values()), 0)
        self.assertEqual(len(self.f.transport.observations), 6)
        self.assertEqual(originals, {name: Path(name).read_bytes() for name in originals})
        self.assertEqual(artifacts, {name: Path(name).read_bytes() for name in artifacts})
        self.assertEqual(repeated.results['mock.observe.'+UNITS[0]]['reconciliation']['status'], 'succeeded')
        for unit in UNITS:
            self.assertEqual(first.results['mock.input.'+unit]['jobId'], repeated.results['mock.input.'+unit]['jobId'])
        assert_canonical_evidence(repeated.stream.directory)

    def test_malformed_frozen_membership_rejected_before_any_dispatch(self):
        config = self.f.dag_config(); del config['mockPolicy']['units'][UNITS[1]]
        with self.assertRaisesRegex(ValueError, 'policy_membership_changed'):
            self.make(config)
        current = self.make(); current.nodes[-1]['dependsOn'] = []
        with self.assertRaisesRegex(ValueError, 'frozen_plan_changed'):
            current.freeze()
        self.assertEqual(len(self.f.transport.observations), 0)
        self.assertEqual(json.loads(self.f.provider_state_path.read_text()), self.f.initial_provider_state)
        self.assertFalse((self.f.root/'source.json').exists())
        self.assertFalse(list(self.f.root.glob('fresh-full-dag/*/mock-control/intents/*.json')))

    def test_logical_layers_and_original_consumer_do_not_double_count_calls(self):
        current = self.make(); self.execute_components(current)
        layers, projected = self.projections(current)
        assert_layers_and_accounting(layers, projected, new_calls=6)
        events = assert_canonical_evidence(current.stream.directory)
        self.assertEqual(projected['canonicalRunId'], current.stream.run_id)
        self.assertEqual({row['runId'] for row in layers['spans']+layers['containerSpans']}, {current.stream.run_id})
        self.assertEqual({row['spanId'] for row in layers['spans']+layers['containerSpans']},
            {row['spanId'] for row in events if row['event'] == 'stage_started'})
        completed = {row['spanId']: row for row in events if row['event'] == 'stage_finished'}
        actual = public.read_snapshot(self.f.root/'fresh-source-causality.json')[0]['handles']
        expected = {'transcription': 'diagnostic.transcription', 'sourceCheck': 'diagnostic.source_model',
            'alignment': 'diagnostic.alignment', 'sourcePackage': 'diagnostic.source_package'}
        for name, stage in expected.items():
            self.assertEqual(actual[name]['stage'], stage)
            self.assertEqual(completed[actual[name]['spanId']]['stage'], stage)
            self.assertEqual(actual[name]['executionMode'], {'transcription': 'current_execution',
                'sourceCheck': 'current_execution', 'alignment': 'cache_replay',
                'sourcePackage': 'deterministic_validation'}[name])
            completion.validate(actual[name], events, production_run_id=self.f.plan['providerConfig']['runId'])
        self.assertEqual(actual['alignment']['dependsOn'], [actual['sourceCheck']['spanId']])
        self.assertIn(actual['alignment']['spanId'], actual['sourcePackage']['dependsOn'])


@unittest.skipUnless(os.environ.get('SERMON_TEST_PREFECT') == '1', 'optional genuine clean-process local Prefect SDK')
class ActualFreshFullPrefectTests(unittest.TestCase):
    def run_scenario(self, scenario):
        launch = ('import sys; sys.path.insert(0, sys.argv[1]); '
            'from tests.test_sermon_fresh_full_dag import run_clean_scenario; '
            'run_clean_scenario(sys.argv[1], sys.argv[2])')
        environment = {key: value for key, value in os.environ.items() if not key.startswith('PREFECT_')}
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-c', launch, str(Path(dag.__file__).resolve().parents[1]), scenario],
                cwd=directory, env=environment, capture_output=True, text=True, timeout=1500)
        self.assertEqual(result.returncode, 0, result.stdout[-5000:]+result.stderr[-16000:])
        self.assertIn('actual-fresh-full-'+scenario+'-ok', result.stdout)

    def test_actual_full_graph_then_clean_process_receipt_only_repeat(self):
        self.run_scenario('happy')

    def test_actual_confirmed_failure_explicit_retry_keeps_successful_neighbor(self):
        self.run_scenario('failure')

    def test_actual_ordinary_timeout_then_original_receipt_reconciliation(self):
        self.run_scenario('timeout')


def run_clean_scenario(repository, scenario):
    """Both invocations are separate actual SDK processes; no identity patches."""
    from tests.mock_tts_sdk_diagnostics import result_summary
    fixture = FullFreshDAGFixture(); fixture.setUp()
    def brief(value):
        return json.dumps(result_summary(value, fixture.root/'fresh-full-dag'/value['planSha256']), sort_keys=True)
    try:
        faults = {} if scenario == 'happy' else {UNITS[0]: {
            'mode': 'fail_after_render' if scenario == 'failure' else 'none',
            'queueDelaySeconds': 0, 'runDelaySeconds': 2 if scenario == 'timeout' else 0}}
        config = fixture.dag_config(faults=faults, observation_timeout=.01 if scenario == 'timeout' else 45)
        launch = ('import sys; sys.path.insert(0, sys.argv[1]); '
            'from tests.fresh_full_dag_fixture import clean_child; clean_child(sys.argv[2])')
        environment = {key: value for key, value in os.environ.items() if not key.startswith('PREFECT_')}
        original_seed_receipts = {str(path): path.read_bytes() for path in
            (fixture.seed.root/'budget').rglob('*.json')}
        results = []
        recovery = {}
        for number in (1, 2):
            result_path = fixture.root/('sdk-result-'+str(number)+'.json')
            payload_path = fixture.root/('sdk-invoke-'+str(number)+'.json')
            payload_path.write_text(json.dumps(fixture.payload(config, result_path,
                allow_calls=number == 1, recovery=recovery)))
            child = subprocess.run([sys.executable, '-c', launch, repository, str(payload_path)],
                cwd=str(fixture.root), env=environment, capture_output=True, text=True, timeout=650)
            assert child.returncode == 0, child.stdout[-4000:]+child.stderr[-14000:]
            result = json.loads(result_path.read_text()); results.append(result)
            assert result['syntheticProviderDispatches'] == (6 if number == 1 else 0), brief(result)
            assert result['newMockDispatches'] == (2 if number == 1 else 1 if scenario == 'failure' else 0), brief(result)
            assert result['realProviderCalls'] == result['realModelCalls'] == result['newMFACalls'] == 0, brief(result)
            assert len(result['nodes']) == len(result['engineEvidence']) == 19
            assert 'source.existing' not in result['nodes']
            engine = result['engineEvidence']
            assert len({row['flowRunId'] for row in engine.values()}) == 1
            assert len({row['taskRunId'] for row in engine.values()}) == 19
            assert all(row['engineState'] == 'Completed' for row in engine.values())
            assert all(row['timestamps']['startTime'] and row['timestamps']['endTime']
                and row['timestamps']['stateHistory'] for row in engine.values())
            frozen = fixture.root/'fresh-full-dag'/result['planSha256']
            nodes = public.read_snapshot(frozen/'plan.json')[0]['nodes']
            for node in nodes:
                assert engine[node['id']]['taskInputs'].get('upstream', []) == sorted(
                    engine[parent]['taskRunId'] for parent in node['dependsOn']), node
                assert_qualifications(result['nodes'][node['id']])
            assert_layers_and_accounting(result['layerEvidence'], result['accountingProjection'],
                new_calls=6 if number == 1 else 0)
            state = json.loads(fixture.provider_state_path.read_text())
            assert_provider_bounds_unchanged(fixture.initial_provider_state, state, expected_requests=6)
            assert original_seed_receipts == {name: Path(name).read_bytes() for name in original_seed_receipts}
            events = assert_canonical_evidence(frozen/'accounting')
            source_handles = public.read_snapshot(fixture.root/'fresh-source-causality.json')[0]['handles']
            ends = {event['spanId']: event for event in events if event['event'] == 'stage_finished'}
            for name, stage in (('transcription', 'diagnostic.transcription'), ('sourceCheck', 'diagnostic.source_model'),
                    ('alignment', 'diagnostic.alignment'), ('sourcePackage', 'diagnostic.source_package')):
                assert source_handles[name]['stage'] == ends[source_handles[name]['spanId']]['stage'] == stage
                assert source_handles[name]['executionMode'] == {'transcription': 'current_execution',
                    'sourceCheck': 'current_execution', 'alignment': 'cache_replay',
                    'sourcePackage': 'deterministic_validation'}[name]
                completion.validate(source_handles[name], events,
                    production_run_id=fixture.plan['providerConfig']['runId'])
            assert source_handles['alignment']['dependsOn'] == [source_handles['sourceCheck']['spanId']]
            if number == 1 and scenario != 'happy':
                assert result['status'] == 'incomplete', brief(result)
                assert result['nodes']['mock.observe.'+UNITS[0]]['executionStatus'] == (
                    'failed' if scenario == 'failure' else 'outcome_unknown'), brief(result)
                assert not result['nodes']['join.'+LOCALE]['readyForDownstream']
                assert not result['nodes']['final.readonly']['readyForDownstream']
                if scenario == 'failure':
                    assert result['nodes']['mock.gate.'+UNITS[1]]['readyForDownstream']
                    recovery = {UNITS[0]: result['nodes']['mock.input.'+UNITS[0]]['requestSha256']}
            else:
                assert result['status'] == 'synthetic_complete', brief(result)
                assert len(result['observedEdges']) == 19, result['observedEdges']
                assert_qualifications(result['finalProjection'])
                assert result['finalProjection']['formalAudioPackageCreated'] is False
                assert result['finalProjection']['listeningAcceptance'] == 'not_performed'
            wait_for_original_jobs(frozen)
            if number == 1:
                original = immutable_files(fixture.root)
                original_observations = {str(path): path.read_bytes() for path in
                    (frozen/'mock-control'/'observations').glob('*.json')}
                original_state = state
            else:
                assert result['planSha256'] == results[0]['planSha256']
                assert original == {name: Path(name).read_bytes() for name in original}
                assert original_observations == {name: Path(name).read_bytes() for name in original_observations}
                assert state == original_state
                assert result['nodes']['mock.input.'+UNITS[1]]['jobId'] == results[0]['nodes']['mock.input.'+UNITS[1]]['jobId']
                assert result['nodes']['mock.input.'+UNITS[0]]['attemptNumber'] == (2 if scenario == 'failure' else 1)
                if scenario == 'timeout':
                    reconciliations = [json.loads(path.read_text()) for path in
                        (frozen/'mock-control'/'reconciliations').glob('*.json')]
                    assert any(row['status'] == 'succeeded' for row in reconciliations)
                    assert result['nodes']['mock.input.'+UNITS[0]]['jobId'] == results[0]['nodes']['mock.input.'+UNITS[0]]['jobId']
        print('actual-fresh-full-'+scenario+'-ok')
    finally:
        try: preserve_full_evidence(fixture.root, scenario)
        finally: fixture.doCleanups()


if __name__ == '__main__':
    unittest.main()
