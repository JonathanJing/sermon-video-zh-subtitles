"""Real pump/broker handoffs; media only, no provider or formal approval."""
import copy
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest import TestCase
from unittest.mock import patch

from tests import test_sermon_unified_cli as cli_fixture
from scripts.sermon_unified import contracts as c, runtime as r, resources, adapters


class ResourceRuntimeTests(TestCase):
    setUp = cli_fixture.UnifiedCliTests.setUp
    freeze = cli_fixture.UnifiedCliTests.freeze

    def bind_policy(self, cpu=1):
        self.policy={'schemaVersion':'sermon-unified-resource-policy-v1',
                     'brokerRoot':str(self.base/'broker'),
                     'capacities':{'cpu':cpu,'online_api':24,'codex_cli':24,'spark_tts':1,'publisher':1}}
        path=self.base/'resources.json';path.write_text(json.dumps(self.policy))
        self.m['bindings']['resourcePolicy']={'path':str(path),'sha256':c.file_sha(path)}

    def second(self):
        manifest=copy.deepcopy(self.m);manifest['productionRunId']='second'
        return r.submit(manifest,self.base,self.root,c.plan_hash(manifest))

    def test_shared_capacity_and_zero_dispatch_while_busy(self):
        self.bind_policy();first=self.freeze();second=self.second()
        entered=threading.Event();done=threading.Event()
        def held(m,base,step,out):
            entered.set()
            if not done.wait(10): raise TimeoutError('test failed to release')
            return adapters.execute(m,base,step,out)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(r.pump,self.root,first['runKey'],executor=held)
            try:
                self.assertTrue(entered.wait(10))
                waiting=r.pump(self.root,second['runKey'],executor=lambda *a:self.fail('over capacity'))
                row=waiting['steps']['media']
                self.assertEqual(row['process'],'not_started')
                self.assertEqual(row['reason'],'resource_capacity_busy')
                self.assertNotIn('intentSha256',row);self.assertNotIn('reservedMicroUsd',row)
                self.assertFalse(waiting['events'])
                self.assertEqual(r._project(waiting)[1][0]['code'],'resource_capacity_busy')
            finally:
                done.set()
            future.result(timeout=10)
        result=r.pump(self.root,second['runKey'])
        self.assertEqual(result['steps']['media']['process'],'succeeded')
        r.pump(self.root,second['runKey'],executor=lambda *a:self.fail('duplicate dispatch'))

    def test_unknown_retains_capacity_and_stops_other_run(self):
        self.bind_policy();first=self.freeze();second=self.second()
        def lost(*args): raise TimeoutError('provider outcome unknown')
        state=r.pump(self.root,first['runKey'],executor=lost)
        self.assertEqual(state['steps']['media']['process'],'waiting_reconciliation')
        r.pump(self.root,first['runKey'],executor=lambda *a:self.fail('unknown replay'))
        waiting=r.pump(self.root,second['runKey'],executor=lambda *a:self.fail('unknown capacity released'))
        self.assertEqual(waiting['steps']['media']['reason'],'resource_capacity_busy')

    def test_reservation_before_intent_crash_is_not_replayed(self):
        self.bind_policy();state=self.freeze();step=state['manifest']['steps'][0]
        operation=c.digest(c.job_identity(state['manifest'],step))
        resources.reserve(self.policy,operation_id=operation,
                          owner={'runKey':state['runKey'],'attemptId':state['attemptId']},resource='cpu')
        result=r.pump(self.root,state['runKey'],executor=lambda *a:self.fail('orphan replay'))
        self.assertEqual(result['steps']['media']['process'],'waiting_reconciliation')
        self.assertEqual(result['steps']['media']['reason'],'resource_reservation_unknown')

    def test_receipt_commit_then_release_crash_recovers_without_dispatch(self):
        self.bind_policy();state=self.freeze()
        with patch.object(resources,'release',side_effect=RuntimeError('crash after commit')):
            with self.assertRaises(RuntimeError): r.pump(self.root,state['runKey'])
        self.assertEqual(r.load(self.root,state['runKey'])['steps']['media']['process'],'succeeded')
        r.pump(self.root,state['runKey'],executor=lambda *a:self.fail('replay after commit'))
        second=self.second();self.assertEqual(r.pump(self.root,second['runKey'])['steps']['media']['process'],'succeeded')

    def test_owner_rechecks_capacity_released_by_other_run(self):
        self.bind_policy();state=self.freeze()
        resources.reserve(self.policy,operation_id='external',owner='external',resource='cpu')
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(r.run_owner,self.root,state['runKey'])
            try:
                # Deterministically observe the saved capacity wait before releasing.
                import time
                deadline=time.monotonic()+10
                while r.load(self.root,state['runKey'])['steps']['media'].get('reason')!='resource_capacity_busy':
                    self.assertLess(time.monotonic(),deadline);time.sleep(.02)
            finally:
                resources.release(self.policy,operation_id='external',owner='external')
            self.assertEqual(future.result(timeout=10)['steps']['media']['process'],'succeeded')

    def test_invalid_policy_plan_is_read_only_and_bound(self):
        self.bind_policy();original=c.plan_hash(self.m)
        path=self.base/'resources.json';p=copy.deepcopy(self.policy);p['capacities']['spark_tts']=8
        path.write_text(json.dumps(p));self.m['bindings']['resourcePolicy']['sha256']=c.file_sha(path)
        self.assertNotEqual(original,c.plan_hash(self.m))
        self.assertIn('resource_policy_invalid',c.admit(self.m,self.base))
        self.assertFalse((self.base/'broker').exists())

    def test_online_adapter_reserves_entire_lane(self):
        self.bind_policy()
        for adapter in ('source.prepare','canonical.layer2','study.produce'):
            self.assertEqual(r.resource_claim(self.policy,{'adapter':adapter}),('online_api',24))
        self.assertEqual(r.resource_claim(self.policy,{'adapter':'canonical.audio'}),('spark_tts',1))

    def test_revision_reuse_keeps_original_terminal_resource_identity(self):
        self.bind_policy();state=self.freeze();r.pump(self.root,state['runKey'])
        state=r.load(self.root,state['runKey'])
        state=r.mutate(self.root,state['runKey'],'drain',state['stateRevision'])
        self.m['runRevision']=2
        revised=r.submit(self.m,self.base,self.root,c.plan_hash(self.m),state['stateRevision'])
        self.assertEqual(revised['revisionReuse']['reused'],['media'])
        r.pump(self.root,state['runKey'],executor=lambda *a:self.fail('revision replay'))

    def test_changed_terminal_receipt_never_frees_unknown_capacity(self):
        self.bind_policy();state=self.freeze()
        with patch.object(resources,'release',side_effect=RuntimeError('crash')):
            with self.assertRaises(RuntimeError):r.pump(self.root,state['runKey'])
        state=r.load(self.root,state['runKey']);step=state['manifest']['steps'][0]
        path=r.folder(self.root,state['runKey'])/('response-'+c.digest(c.job_identity(state['manifest'],step))+'.json')
        path.write_text('{}')
        with self.assertRaises(c.ContractError):r.pump(self.root,state['runKey'])
        second=self.second()
        waiting=r.pump(self.root,second['runKey'],executor=lambda *a:self.fail('corrupt receipt freed permit'))
        self.assertEqual(waiting['steps']['media']['reason'],'resource_capacity_busy')

    def test_revision_reuse_releases_origin_broker_not_new_policy(self):
        self.bind_policy();state=self.freeze();r.pump(self.root,state['runKey'])
        state=r.load(self.root,state['runKey'])
        state=r.mutate(self.root,state['runKey'],'drain',state['stateRevision'])
        self.m['runRevision']=2
        self.policy['brokerRoot']=str(self.base/'new-broker')
        path=self.base/'new-resource-policy.json';path.write_text(json.dumps(self.policy))
        self.m['bindings']['resourcePolicy']={'path':str(path),'sha256':c.file_sha(path)}
        revised=r.submit(self.m,self.base,self.root,c.plan_hash(self.m),state['stateRevision'])
        self.assertEqual(revised['revisionReuse']['reused'],['media'])
        r.pump(self.root,state['runKey'],executor=lambda *a:self.fail('new broker replay'))
        self.assertFalse((self.base/'new-broker').exists())

    def test_revision_can_remove_opt_in_policy_without_losing_origin_receipt(self):
        self.bind_policy();state=self.freeze();r.pump(self.root,state['runKey'])
        state=r.load(self.root,state['runKey'])
        state=r.mutate(self.root,state['runKey'],'drain',state['stateRevision'])
        self.m['runRevision']=2;self.m['bindings'].pop('resourcePolicy')
        revised=r.submit(self.m,self.base,self.root,c.plan_hash(self.m),state['stateRevision'])
        self.assertEqual(revised['revisionReuse']['reused'],['media'])
        r.pump(self.root,state['runKey'],executor=lambda *a:self.fail('removed policy replay'))
