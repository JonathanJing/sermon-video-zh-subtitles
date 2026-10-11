"""Ordinary component checks and opt-in genuine clean-process Prefect acceptance.

The component suite substitutes the inherited clean-code admission gate and
uses a component-only SDK version marker, so optional Prefect is not required.
It is never evidence of actual Prefect engine scheduling. No interruption or
crash-window scenarios are added here.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from scripts import sermon_accounting as accounting
from scripts import sermon_completion as completion
from scripts import sermon_log_contract as logs
from scripts import sermon_log_profile as profile
from scripts import sermon_mock_tts_dag as dag
from scripts import sermon_review_contracts as c
from scripts import sermon_workflow_jobs as jobs
from scripts.sermon_diagnostic_dag_session import DiagnosticSession
from tests.mock_tts_dag_fixture import MockTTSDAGFixture


class MockTTSDAGComponents(unittest.TestCase):
    def setUp(self):
        self.f = MockTTSDAGFixture(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.enterContext(patch.object(accounting, 'execution_identity', return_value=self.f.execution_identity))
        self.enterContext(patch.object(dag, 'version', return_value='component-only-no-sdk'))

    def make(self, config=None, *, recovery=None):
        session = DiagnosticSession(self.f.plan, self.f.continuation, offline_transport=self.f.transport, request_limits=self.f.request_limits)
        return dag.MockTTSDAG(session, config or self.f.dag_config(), recovery=recovery)

    def execute_components(self, current):
        current.freeze()
        with current.stream.context(), accounting.accounting_session(current.root/'accounting', 'mock_tts_dag_component'):
            current.activate()
            for node in current.nodes:
                current.execute(node['id'], [current.observations[key] for key in node['dependsOn']])
            current.observed_edges()
        return current.observations

    def test_explicit_v1_migration_keeps_mock_root_and_recovery_identity(self):
        original = self.make()
        old = deepcopy(original.binding)
        old['diagnosticBinding']['sessionBinding']['schemaVersion'] = 'sermon-diagnostic-dag-session-v1'
        old['diagnosticBinding']['sessionBinding']['implementationSha256'] = 'a'*64
        old['diagnosticBinding']['codeSha256'] = 'b'*64
        old['codeFiles'] = {k:'c'*64 for k in old['codeFiles']}
        old['mockImplementationSha256'] = 'd'*64
        root = self.f.root/'mock-tts-dag'/c.canonical_sha256(old)
        root.mkdir(parents=True)
        from scripts import sermon_public_snapshot as public
        public.save_once(root/'plan.json', old)
        saved = (root/'plan.json').read_bytes()
        marker = root/'original-recovery.json'; marker.write_bytes(b'preserved')
        limits_path = self.f.root/'continuation-request-limits.json'
        limits_path.unlink()
        invalid = deepcopy(old); invalid['permissions']['providerCalls'] = True
        invalid_root = self.f.root/'mock-tts-dag'/c.canonical_sha256(invalid)
        invalid_root.mkdir(parents=True); public.save_once(invalid_root/'plan.json', invalid)
        rejected = DiagnosticSession(self.f.plan,self.f.continuation,
            offline_transport=self.f.transport, request_limits=self.f.request_limits,
            resume_binding=invalid['diagnosticBinding']['sessionBinding'])
        with self.assertRaises(ValueError):
            dag.MockTTSDAG(rejected,self.f.dag_config(),resume_plan=invalid_root/'plan.json')
        self.assertFalse(limits_path.exists())
        active = DiagnosticSession(self.f.plan,self.f.continuation,
            offline_transport=self.f.transport, request_limits=self.f.request_limits,
            resume_binding=old['diagnosticBinding']['sessionBinding'])
        migrated = dag.MockTTSDAG(active,self.f.dag_config(),resume_plan=root/'plan.json')
        migrated.freeze()
        self.assertEqual(migrated.root,root)
        self.assertEqual(migrated.invocation_binding['planSha256'],root.name)
        self.assertEqual((root/'plan.json').read_bytes(),saved)
        self.assertEqual(marker.read_bytes(),b'preserved')
        self.assertEqual(len(self.f.transport.observations),2)
        receipt = public.read_snapshot(root/'session-binding-migration.json')[0]
        self.assertFalse(receipt['providerRetry'])
        receipt['executionBinding']['codeFiles']['scripts/sermon_mock_tts_dag.py'] = 'f'*64
        migrated._migration = receipt
        with self.assertRaises(ValueError): migrated._check()

    def test_cross_continuation_v1_resume_reuses_paid_results_and_mock_requests(self):
        legacy_authority = deepcopy(self.f.continuation)
        old_session = DiagnosticSession(self.f.plan,legacy_authority,
            offline_transport=self.f.transport, request_limits=self.f.request_limits)
        # Reproduce a v1 producer before it added the session schema revision.
        old_session.binding['schemaVersion'] = 'sermon-diagnostic-dag-session-v1'
        original = dag.MockTTSDAG(old_session,self.f.dag_config())
        self.assertTrue(self.execute_components(original)['final.readonly']['readyForDownstream'])
        before_plan = (original.root/'plan.json').read_bytes()
        before = {p:p.read_bytes() for p in (original.root/'mock-control/requests').rglob('*') if p.is_file()}
        calls = len(self.f.transport.observations)
        current_authority = deepcopy(legacy_authority)
        new_identity = deepcopy(self.f.execution_identity)
        new_identity['gitCommit'] = 'a'*40 if new_identity['gitCommit'] != 'a'*40 else 'b'*40
        current_authority['executionIdentity'] = new_identity
        current_authority['diagnosticContext']['continuationCodeCommit'] = new_identity['gitCommit']
        with patch.object(accounting,'execution_identity',return_value=new_identity):
            current = DiagnosticSession(self.f.plan,current_authority,offline_transport=self.f.transport,
                resume_binding=original.binding['diagnosticBinding']['sessionBinding'],
                legacy_continuation=legacy_authority)
            resumed = dag.MockTTSDAG(current,self.f.dag_config(),resume_plan=original.root/'plan.json')
            result = self.execute_components(resumed)
            self.assertTrue(result['final.readonly']['readyForDownstream'],result)
        self.assertEqual(resumed.root,original.root)
        self.assertEqual((original.root/'plan.json').read_bytes(),before_plan)
        self.assertEqual(calls,len(self.f.transport.observations))
        self.assertEqual(sum(v.get('newDispatch') is True for v in resumed.results.values()),0)
        self.assertEqual(before,{p:p.read_bytes() for p in (original.root/'mock-control/requests').rglob('*') if p.is_file()})

    def test_actual_callbacks_jobs_gate_join_and_normal_repeat_dispatch_nothing(self):
        first = self.make(); result = self.execute_components(first)
        self.assertTrue(result['final.readonly']['readyForDownstream'], result)
        self.assertEqual(len(self.f.transport.observations), 6)
        self.assertEqual(sum(v.get('newDispatch') is True for v in first.results.values()), 2)
        artifacts = {p: p.read_bytes() for p in (first.root/'mock-control'/'requests').rglob('*') if p.is_file()}
        second = self.make(); repeated = self.execute_components(second)
        self.assertEqual(first.root, second.root)
        self.assertTrue(repeated['final.readonly']['readyForDownstream'], repeated)
        self.assertEqual(sum(v.get('newDispatch') is True for v in second.results.values()), 0)
        self.assertEqual(len(self.f.transport.observations), 6)
        self.assertEqual(artifacts, {p: p.read_bytes() for p in (first.root/'mock-control'/'requests').rglob('*') if p.is_file()})
        events, errors = accounting.read_events(first.stream.directory)
        self.assertFalse(errors)
        self.assertEqual(logs.replay_integrity(events)['status'], 'consistent')
        for row in repeated.values():
            for handle in row['completionHandles']:
                completion.validate_synthetic(handle, events, production_run_id=self.f.context['runId'])
        final = second.results['final.readonly']
        self.assertFalse(final['productionEligible'])
        self.assertFalse(final['formalAudioPackageCreated'])
        self.assertFalse(final['publicationAuthorized'])
        self.assertEqual(final['humanAcceptance'], 'pending')
        self.assertEqual(final['listeningAcceptance'], 'not_performed')
        self.assertFalse((self.f.root/'diagnostic-previews').exists())

    def test_known_worker_failure_then_explicit_retry_keeps_successful_neighbor(self):
        config = self.f.dag_config(faults={'zh-Hans.g1': {
            'mode': 'fail_after_render', 'queueDelaySeconds': 0, 'runDelaySeconds': 0}})
        current = self.make(config)
        result = self.execute_components(current)
        self.assertEqual(result['mock.observe.zh-Hans.g1']['executionStatus'], 'failed', result)
        self.assertTrue(result['mock.gate.zh-Hans.g2']['readyForDownstream'], result)
        for key in ('mock.verify.zh-Hans.g1', 'mock.gate.zh-Hans.g1', 'join.zh-Hans', 'final.readonly'):
            self.assertFalse(result[key]['readyForDownstream'], key)
            self.assertEqual(result[key]['reason'], 'upstream_not_completed')
        self.assertEqual(sum(v.get('newDispatch') is True for v in current.results.values()), 2)
        self.assertNotIn('final.readonly', current.results)
        failed = current.results['mock.input.zh-Hans.g1']
        successful = current.results['mock.input.zh-Hans.g2']
        recovery = {'zh-Hans.g1': failed['requestSha256']}
        repeated = self.make(config, recovery=recovery); result = self.execute_components(repeated)
        self.assertTrue(result['final.readonly']['readyForDownstream'], result)
        self.assertEqual(sum(v.get('newDispatch') is True for v in repeated.results.values()), 1)
        self.assertEqual(repeated.results['mock.input.zh-Hans.g1']['attemptNumber'], 2)
        self.assertEqual(repeated.results['mock.input.zh-Hans.g2']['jobId'], successful['jobId'])
        self.assertEqual(len(self.f.transport.observations), 6)
        with repeated.stream.context():
            selected = repeated._selection(successful['unit'])
            self.assertEqual(selected[0], 1)
            self.assertEqual(repeated._selection(failed['unit'])[0], 2)

    def test_ordinary_observer_timeout_then_later_original_receipt_reconciles(self):
        config = self.f.dag_config(faults={'zh-Hans.g1': {
            'mode': 'none', 'queueDelaySeconds': 0, 'runDelaySeconds': 2}}, observation_timeout=.01)
        first = self.make(config); result = self.execute_components(first)
        self.assertEqual(result['mock.observe.zh-Hans.g1']['executionStatus'], 'outcome_unknown', result)
        originals = {p: p.read_bytes() for p in (first.root/'mock-control'/'observations').glob('*.json')}
        failed_recovery = self.make(config, recovery={'zh-Hans.g1': first.results['mock.input.zh-Hans.g1']['requestSha256']})
        failed_recovery.freeze()
        with failed_recovery.stream.context(), self.assertRaises((ValueError, OSError)):
            failed_recovery.activate()
        self.assertEqual(len(list((first.root/'mock-control'/'intents').glob('*.json'))), 2)
        deadline = time.monotonic()+60
        while time.monotonic() < deadline:
            ids = [json.loads(p.read_text())['jobId'] for p in (first.root/'mock-control'/'intents').glob('*.json')]
            if all(jobs.peek_job(first.root/'mock-control'/'jobs', key)['status'] not in {'queued', 'running'} for key in ids): break
            time.sleep(.03)
        repeated = self.make(config); result = self.execute_components(repeated)
        self.assertTrue(result['final.readonly']['readyForDownstream'], result)
        self.assertEqual(sum(v.get('newDispatch') is True for v in repeated.results.values()), 0)
        self.assertEqual(originals, {p: p.read_bytes() for p in originals})
        self.assertEqual(repeated.results['mock.observe.zh-Hans.g1']['reconciliation']['status'], 'succeeded')

    def test_prelaunch_capacity_failure_is_blocked_not_unknown(self):
        config = self.f.dag_config(); config['mockPolicy']['maxConcurrentJobs'] = 1
        current = self.make(config); current.freeze()
        with current.stream.context():
            current.activate()
            source = current.execute('source.existing', [])
            text = current.execute('text.zh-Hans', [source])
            first = current.execute('mock.input.zh-Hans.g1', [text])
            current.execute('mock.submit.zh-Hans.g1', [first])
            second = current.execute('mock.input.zh-Hans.g2', [text])
            with patch.object(dag.control.jobs, 'peek_job', return_value={'status': 'running'}), \
                    patch.object(dag.control.subprocess, 'run', side_effect=AssertionError('capacity must prevent launch')) as launch:
                result = current.execute('mock.submit.zh-Hans.g2', [second])
            self.assertEqual(result['executionStatus'], 'blocked', result)
            self.assertFalse(result['processed'])
            self.assertFalse(result['readyForDownstream'])
            self.assertEqual(result['reason'], 'mock_tts_capacity_blocked')
            self.assertEqual(result['completionHandles'], [])
            launch.assert_not_called()
            self.assertEqual(len(list((current.client.root/'intents').glob('*.json'))), 1)
            _, first_path = current._request('zh-Hans.g1')
            self.assertEqual(current.client.observe(first_path)['status'], 'succeeded')

    def test_policy_and_graph_membership_are_rejected_before_dispatch(self):
        config = self.f.dag_config(); del config['mockPolicy']['units']['zh-Hans.g2']
        with self.assertRaisesRegex(ValueError, 'policy_membership_changed'): self.make(config)
        current = self.make(); current.nodes[-1]['dependsOn'] = []
        with self.assertRaisesRegex(ValueError, 'frozen_plan_changed'): current.freeze()
        self.assertEqual(len(self.f.transport.observations), 2)
        self.assertFalse((self.f.root/'mock-tts-dag').exists())

    def test_combined_delay_recovery_membership_and_timing_unknowns(self):
        config = self.f.dag_config(observation_timeout=.01)
        config['mockPolicy']['workerTimeoutSeconds'] = 1
        config['faults']['zh-Hans.g1'] = {'mode': 'none', 'queueDelaySeconds': .6, 'runDelaySeconds': .6}
        with self.assertRaisesRegex(ValueError, 'mock_dag_fault_invalid'):
            self.make(config)
        with self.assertRaisesRegex(ValueError, 'mock_dag_recovery_selection_invalid'):
            self.make(recovery={'unknown.group': 'a'*64})
        self.assertEqual(len(self.f.transport.observations), 2)
        timing = dag.timing_coverage()
        self.assertEqual(timing['criticalPathStatus'], 'partial')
        for key in ('criticalPathSeconds', 'etaSeconds', 'resourceQueueSeconds', 'providerQueueSeconds'):
            self.assertIsNone(timing[key])
            self.assertTrue(timing['missingReasons'][key])

    def test_candidate_membership_changed_and_missing_dependency_cannot_dispatch(self):
        current = self.make(); current.freeze()
        with current.stream.context():
            current.activate()
            source = current.execute('source.existing', [])
            text = current.execute('text.zh-Hans', [source])
            self.assertTrue(text['readyForDownstream'], text)
            missing = current.execute('mock.input.zh-Hans.g1', [])
            self.assertFalse(missing['readyForDownstream'])
            self.assertEqual(missing['reason'], 'mock_dag_dependency_membership_changed')
            candidate_path = Path(current.results['text.zh-Hans']['callbackResult']['output'])/'candidate.json'
            candidate = json.loads(candidate_path.read_text()); candidate['groups'].pop()
            candidate_path.write_text(json.dumps(candidate))
            changed = current.execute('mock.input.zh-Hans.g2', [text])
            self.assertFalse(changed['readyForDownstream'])
        self.assertFalse((current.root/'mock-control'/'intents').exists())

    def test_input_binding_and_cross_run_completion_reject_without_dispatch(self):
        current = self.make(); current.freeze()
        with current.stream.context():
            current.activate()
            source = current.execute('source.existing', [])
            text = current.execute('text.zh-Hans', [source])
            current.execute('mock.input.zh-Hans.g1', [text])
            input_result = current.results['mock.input.zh-Hans.g1']
            self.assertNotIn('candidateSha256', input_result['inputBinding'])
            request_path = Path(input_result['requestPath'])
            binding_path = request_path.parent.parent/'unit-input.json'
            binding = json.loads(binding_path.read_text()); binding['utteranceSha256'] = 'f'*64
            binding_path.write_text(json.dumps(binding))
            submitted = current.execute('mock.submit.zh-Hans.g1', [current.observations['mock.input.zh-Hans.g1']])
            self.assertFalse(submitted['readyForDownstream'])
            cross_run = deepcopy(text); cross_run['completionHandles'][0]['productionRunId'] = 'f'*64
            rejected = current.execute('mock.input.zh-Hans.g2', [cross_run])
            self.assertFalse(rejected['readyForDownstream'])
        self.assertFalse((current.root/'mock-control'/'intents').exists())


@unittest.skipUnless(os.environ.get('SERMON_TEST_PREFECT') == '1', 'optional genuine clean-process local Prefect SDK')
class ActualMockTTSPrefectTests(unittest.TestCase):
    def run_scenario(self, scenario):
        script = r'''
import json, os, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from scripts import sermon_mock_tts_dag as dag
from scripts import sermon_workflow_jobs as jobs
from scripts.sermon_diagnostic_dag_session import DiagnosticSession
from tests.mock_tts_dag_fixture import MockTTSDAGFixture
from tests.mock_tts_sdk_diagnostics import result_summary, preserve_evidence
f=MockTTSDAGFixture(); f.setUp()
scenario=sys.argv[2]
def brief(value):
    return result_summary(value,f.root/'mock-tts-dag'/value['planSha256'])
try:
    faults={} if scenario=='happy' else {'zh-Hans.g1': {'mode':
        'fail_after_render' if scenario=='failure' else 'none',
        'queueDelaySeconds': 0, 'runDelaySeconds': 2 if scenario=='timeout' else 0}}
    config=f.dag_config(faults=faults, observation_timeout=.01 if scenario=='timeout' else 45)
    # Obtain the canonical existing ledger path from the actual store, not a replacement.
    from scripts import sermon_review_budget as budget
    state_path=f.subject.store.root/budget.STORE_ID/'provider-run'/'state.json'
    original_state=json.loads(state_path.read_text())
    child_script="import sys; sys.path.insert(0, sys.argv[1]); from tests.mock_tts_dag_fixture import resume_in_clean_process; resume_in_clean_process(sys.argv[2])"
    env={k:v for k,v in os.environ.items() if not k.startswith('PREFECT_')}
    first_result=f.root/'sdk-first-result.json'
    first_payload=f.root/'sdk-first.json'
    first_payload.write_text(json.dumps({'plan':f.plan, 'continuation':f.continuation,
        'config':config, 'resumeResultPath':str(first_result), 'fixtureGroups':f.original.groups,
        'allowNewFixtureResponses':True}))
    first=subprocess.run([sys.executable, '-c', child_script, sys.argv[1], str(first_payload)],
        cwd=str(f.root), env=env, capture_output=True, text=True, timeout=600)
    assert first.returncode==0, first.stdout[-3000:]+first.stderr[-9000:]
    result=json.loads(first_result.read_text())
    assert result['newMockDispatches']==2, brief(result)
    assert result['syntheticProviderDispatches']==4, brief(result)
    assert result['realProviderCalls']==0 and result['newSourceCalls']==0
    assert len(f.transport.observations)==2  # Only historical Source fixture calls in this parent.
    assert f.subject.snapshot()['requestCount']==6
    checked_state=json.loads(state_path.read_text())
    assert checked_state['startedMonotonic']==original_state['startedMonotonic']
    assert checked_state['config']==original_state['config']
    assert all(checked_state['requests'][key]==row for key,row in original_state['requests'].items())
    assert len({row['flowRunId'] for row in result['engineEvidence'].values()})==1
    assert len({row['taskRunId'] for row in result['engineEvidence'].values()})==len(result['nodes'])
    assert all(row['engineState']=='Completed' for row in result['engineEvidence'].values())
    assert all(row['timestamps']['startTime'] and row['timestamps']['endTime']
        and row['timestamps']['stateHistory'] for row in result['engineEvidence'].values())
    assert result['timingCoverage']['criticalPathSeconds'] is None
    assert result['timingCoverage']['etaSeconds'] is None
    assert all(row['humanAcceptance']=='pending' and row['productionEligible'] is False
        for row in result['nodes'].values())
    if scenario=='failure':
        assert result['status']=='incomplete', brief(result)
        assert result['nodes']['mock.observe.zh-Hans.g1']['executionStatus']=='failed', brief(result)
        assert result['nodes']['mock.gate.zh-Hans.g2']['readyForDownstream'], brief(result)
        assert not result['nodes']['join.zh-Hans']['readyForDownstream']
    if scenario!='failure':
        if scenario=='happy':
            assert result['status']=='synthetic_complete', brief(result)
            assert len(result['observedEdges'])==14, result['observedEdges']
        else:
            assert result['status']=='incomplete', brief(result)
            assert result['nodes']['mock.observe.zh-Hans.g1']['executionStatus']=='outcome_unknown', brief(result)
    frozen=f.root/'mock-tts-dag'/result['planSha256']
    deadline=time.monotonic()+90
    while time.monotonic()<deadline:
        ids=[json.loads(p.read_text())['jobId'] for p in (frozen/'mock-control'/'intents').glob('*.json')]
        if all(jobs.peek_job(frozen/'mock-control'/'jobs', key)['status'] not in {'queued','running'} for key in ids):
            break
        time.sleep(.05)
    originals={str(p):p.read_bytes() for p in (frozen/'mock-control'/'requests').rglob('*') if p.is_file()}
    resume_result=f.root/'sdk-resume-result.json'
    payload=f.root/'sdk-resume.json'
    recovery = {'zh-Hans.g1': result['nodes']['mock.input.zh-Hans.g1']['requestSha256']} if scenario=='failure' else {}
    payload.write_text(json.dumps({'plan':f.plan, 'continuation':f.continuation,
        'config':config, 'recovery':recovery, 'resumeResultPath':str(resume_result)}))
    repeated=subprocess.run([sys.executable, '-c', child_script, sys.argv[1], str(payload)],
        cwd=str(f.root), env=env, capture_output=True, text=True, timeout=600)
    assert repeated.returncode==0, repeated.stdout[-3000:]+repeated.stderr[-9000:]
    again=json.loads(resume_result.read_text())
    assert again['planSha256']==result['planSha256']
    assert again['status']=='synthetic_complete', brief(again)
    assert again['newMockDispatches']==(1 if scenario=='failure' else 0) and again['syntheticProviderDispatches']==0, brief(again)
    assert all(Path(path).read_bytes()==value for path,value in originals.items())
    assert again['nodes']['mock.input.zh-Hans.g2']['jobId']==result['nodes']['mock.input.zh-Hans.g2']['jobId']
    if scenario=='failure':
        assert again['nodes']['mock.input.zh-Hans.g1']['attemptNumber']==2
        assert again['nodes']['mock.input.zh-Hans.g1']['jobId']!=result['nodes']['mock.input.zh-Hans.g1']['jobId']
    assert len(again['observedEdges'])==14
    print('actual-mock-tts-prefect-'+scenario+'-ok')
finally:
    try: preserve_evidence(f.root,scenario)
    finally: f.doCleanups()
'''
        env = {k: v for k, v in os.environ.items() if not k.startswith('PREFECT_')}
        with tempfile.TemporaryDirectory() as root:
            result = subprocess.run([sys.executable, '-c', script, str(dag.diagnostic.pilot.REPO), scenario],
                cwd=root, env=env, capture_output=True, text=True, timeout=1000)
        self.assertEqual(result.returncode, 0, result.stdout[-5000:]+result.stderr[-12000:])
        self.assertIn('actual-mock-tts-prefect-'+scenario+'-ok', result.stdout)

    def test_actual_frozen_graph_and_normal_clean_process_repeat(self):
        self.run_scenario('happy')

    def test_actual_known_failure_explicit_partial_retry_and_successful_neighbor_reuse(self):
        self.run_scenario('failure')

    def test_actual_observer_timeout_then_original_receipt_reconciliation(self):
        self.run_scenario('timeout')


if __name__ == '__main__':
    unittest.main()
