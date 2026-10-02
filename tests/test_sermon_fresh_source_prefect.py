"""Six actual Source/locale stages; no claim of text/TTS engine takeover."""
from copy import deepcopy
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import sermon_accounting as accounting
from scripts import sermon_bounded_business_callbacks as offline
from scripts import sermon_fresh_diagnostic as fresh
from scripts import sermon_fresh_source_prefect as engine
from scripts import sermon_log_contract as log
from scripts import sermon_review_contracts as c
from scripts import sermon_public_snapshot as public
from tests import test_sermon_fresh_source_causality as fixtures


class SourceEngineFixture(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.FreshCausalityTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.seed = self.f.f.f
        self.root, self.plan, self.recipe = self.f.root, self.f.plan, self.f.recipe
        self.authorization = self.f.f.authorization
        policy, rubric, plugin = self.root/'policy-draft.json', self.root/'rubric-draft.json', self.root/'fixture-plugin.py'
        policy.write_bytes(c.canonical_bytes(self.seed.policy)); rubric.write_bytes(c.canonical_bytes(self.seed.rubric))
        plugin.write_bytes(Path(self.seed.locale_specs['zh-Hans']['pluginPath']).read_bytes())
        self.locales = {'zh-Hans': {'policy': str(policy), 'rubric': str(rubric), 'pluginPath': str(plugin)}}

    def session(self):
        return fresh.FreshDiagnosticSession(self.plan, offline_transport=self.seed.transport)


def clean_child(payload_path):
    value = json.loads(Path(payload_path).read_text())
    expected = value['plan']['executionIdentity']
    repository = Path(engine.__file__).resolve().parents[1]
    for name, digest in expected['loadedProjectCodeSha256'].items():
        assert name.startswith('scripts/') and name.endswith('.py')
        assert c.bytes_sha256((repository/name).read_bytes()) == digest
        importlib.import_module(name[:-3].replace('/', '.'))
    assert accounting.execution_identity() == expected, 'fresh clean code identity must match'
    def respond(request, timeout, *, deadline):
        assert value['allowSourceCalls'], 'normal repeat must not call synthetic providers'
        if request.full_url.endswith('/audio/transcriptions'):
            if value.get('fixtureFault') == 'unknown':
                raise TimeoutError('synthetic source timeout')
            return {'text': value['fixtureSourceText'], 'usage': {'type': 'duration', 'seconds': 180}}
        payload = json.loads(request.data)
        assert payload['model'] == 'gpt-6-astra'
        return {'id': 'fresh-source-fixture', 'model': payload['model'],
            'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(value['fixtureSourceReview'])}}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 20}}
    transport = offline.OfflineHTTPTransport(respond, fixture_id='diagnostic-dag-fixture')
    session = fresh.FreshDiagnosticSession(value['plan'], offline_transport=transport)
    result = engine.run(session, value['recipe'], value['authorization'], value['locales'])
    Path(value['resultPath']).write_text(json.dumps(result))
    return result


class FreshSourceEngineComponents(unittest.TestCase):
    def setUp(self):
        self.f = SourceEngineFixture(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.enterContext(patch.object(accounting, 'execution_identity', return_value=self.f.plan['executionIdentity']))
        self.enterContext(patch.object(engine, 'version', return_value='component-only-no-sdk'))

    def run_components(self):
        dag = engine.FreshSourceDAG(self.f.session(), self.f.recipe, self.f.authorization, self.f.locales)
        dag.freeze()
        with dag.stream.context(), accounting.accounting_session(dag.root/'accounting', 'source-engine-component'):
            dag.stages.freeze()
            for node in dag.nodes:
                dag.execute(node['id'], [dag.observations[key] for key in node['dependsOn']])
        return dag

    def test_fixed_six_boundaries_and_declared_locale_membership(self):
        before = len(self.f.seed.transport.observations)
        dag = self.run_components()
        self.assertTrue(dag.observations['locale.freeze']['readyForDownstream'], dag.observations)
        self.assertEqual(len(self.f.seed.transport.observations)-before, 2)
        self.assertEqual(len(dag.nodes), 6)
        self.assertEqual(dag.results['locale.freeze']['specs']['zh-Hans']['groupPlan'], dag.expected_groups)
        self.assertFalse(dag.binding['downstreamEngineTakeover'])
        events, errors = accounting.read_events(dag.stream.directory)
        self.assertFalse(errors)
        self.assertEqual(log.replay_integrity(events)['status'], 'consistent')
        self.assertEqual({r['runId'] for r in events}, {dag.stream.run_id})
        for node in dag.nodes[1:]:
            proof = dag.observations[node['id']]['completion']
            parent = dag.observations[node['dependsOn'][0]]['completion']
            self.assertIn(parent['spanId'], proof['dependsOn'])

    def test_preflight_failure_blocks_every_downstream_engine_operation(self):
        path = Path(self.f.recipe['prior_source_path'])
        value = public.read_snapshot(path)[0]; value['source']['serviceDate'] = 'invalid-date'
        path.write_bytes(c.canonical_bytes(value))
        before = len(self.f.seed.transport.observations)
        dag = self.run_components()
        self.assertEqual(dag.observations['source.preflight']['status'], 'failed', dag.observations)
        self.assertTrue(all(row['status'] == 'blocked' for key, row in dag.observations.items() if key != 'source.preflight'))
        self.assertEqual(len(self.f.seed.transport.observations), before)
        self.assertFalse((self.f.root/'source.json').exists())
        self.assertFalse((self.f.root/'fresh-inputs').exists())
        events, _ = accounting.read_events(dag.stream.directory)
        self.assertEqual(log.replay_integrity(events)['status'], 'consistent')


@unittest.skipUnless(os.environ.get('SERMON_TEST_PREFECT') == '1', 'optional genuine clean-process Prefect SDK')
class ActualFreshSourcePrefectTests(unittest.TestCase):
    def run_scenario(self, scenario):
        script = r'''
import json, os, subprocess, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from tests.test_sermon_fresh_source_prefect import SourceEngineFixture
f=SourceEngineFixture(); f.setUp()
try:
    scenario=sys.argv[2]
    if scenario=='preflight':
        source_path=Path(f.recipe['prior_source_path']);invalid=json.loads(source_path.read_text())
        invalid['source']['serviceDate']='invalid-date';source_path.write_text(json.dumps(invalid))
    payload={'plan':f.plan, 'recipe':{k:str(v) if isinstance(v,Path) else v for k,v in f.recipe.items()},
        'authorization':f.authorization,'locales':f.locales,'fixtureSourceText':f.seed.transcript,
        'fixtureSourceReview':f.seed.content,'fixtureFault':scenario,'allowSourceCalls':True,'resultPath':str(f.root/'first.json')}
    launch="import sys;sys.path.insert(0,sys.argv[1]);from tests.test_sermon_fresh_source_prefect import clean_child;clean_child(sys.argv[2])"
    env={k:v for k,v in os.environ.items() if not k.startswith('PREFECT_')}
    results=[]
    for number in ((1,2) if scenario=='happy' else (1,)):
        path=f.root/('invoke-'+str(number)+'.json');path.write_text(json.dumps(payload))
        child=subprocess.run([sys.executable,'-c',launch,sys.argv[1],str(path)],cwd=str(f.root),env=env,
            capture_output=True,text=True,timeout=600)
        assert child.returncode==0,child.stdout[-3000:]+child.stderr[-10000:]
        result=json.loads(Path(payload['resultPath']).read_text());results.append(result)
        if scenario=='happy':
            assert result['status']=='synthetic_source_complete',result
            assert result['syntheticProviderDispatches']==(2 if number==1 else 0),result
        else:
            assert result['status']=='incomplete',result
            assert result['syntheticProviderDispatches']==(1 if scenario=='unknown' else 0),result
            failed='transcription.initial' if scenario=='unknown' else 'source.preflight'
            expected='outcome_unknown' if scenario=='unknown' else 'failed'
            assert result['nodes'][failed]['status']==expected,result
            assert all(row['status']=='blocked' for key,row in result['nodes'].items() if key not in
                ({'source.preflight',failed} if scenario=='unknown' else {failed})),result
            assert not (f.root/'source.json').exists()
        assert result['realProviderCalls']==result['newMFACalls']==result['textOrTTSDispatches']==0
        assert result['productionEligible'] is False and result['downstreamEngineTakeover'] is False
        assert len(result['engineEvidence'])==6
        assert all(row['engineState']=='Completed' and row['timestamps']['stateHistory'] for row in result['engineEvidence'].values())
        if number==1:
            original={str(p):p.read_bytes() for p in (f.root/'fresh-source-stages').glob('*.json')}
        else:
            assert all(Path(p).read_bytes()==data for p,data in original.items())
        payload['allowSourceCalls']=False;payload['resultPath']=str(f.root/'second.json')
    if scenario=='happy':assert results[0]['planSha256']==results[1]['planSha256']
    print('actual-six-source-'+scenario+'-ok')
finally:f.doCleanups()
'''
        env = {k: v for k, v in os.environ.items() if not k.startswith('PREFECT_')}
        with tempfile.TemporaryDirectory() as root:
            result = subprocess.run([sys.executable, '-c', script, str(Path(engine.__file__).resolve().parents[1]), scenario],
                cwd=root, env=env, capture_output=True, text=True, timeout=1400)
        self.assertEqual(result.returncode, 0, result.stdout[-5000:]+result.stderr[-16000:])
        self.assertIn('actual-six-source-'+scenario+'-ok', result.stdout)

    def test_actual_six_tasks_then_clean_process_receipt_only_repeat(self):
        self.run_scenario('happy')

    def test_actual_preflight_failure_blocks_later_tasks(self):
        self.run_scenario('preflight')

    def test_actual_source_unknown_blocks_review_alignment_package_and_locales(self):
        self.run_scenario('unknown')


if __name__ == '__main__':
    unittest.main()
