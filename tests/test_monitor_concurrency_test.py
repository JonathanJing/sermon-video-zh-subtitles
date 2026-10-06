import fcntl
import json
import unittest
from unittest.mock import patch
from scripts.experiments import monitor_concurrency_test as monitor
from tests import test_run_concurrency_preflight as fixtures

class DiagnosticMonitorTests(unittest.TestCase):
    def setUp(self):
        self.helper=fixtures.DiagnosticCommandDAGTests();self.helper.setUp();self.addCleanup(self.helper.doCleanups)
        self.helper.prepare([self.helper.node('source',kind='source')])

    def test_default_zero_calls_and_no_monitor_directory(self):
        with patch.object(monitor.codex,'call_json') as call:
            self.assertEqual(monitor.monitor(self.helper.out)['status'],'ready')
            call.assert_not_called()
        self.assertFalse((self.helper.out/'supervision').exists())

    def test_live_owner_observed_running_but_abandoned_owner_stays_unknown(self):
        root,plan=monitor.batch._load(self.helper.out)
        folder,started,_=monitor.batch._paths(root,'source')
        monitor.batch._write(started,{'planSha256':monitor.batch.jobs._digest(plan)})
        path=root/'owner.lock'
        with path.open('a') as handle:
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            snap=monitor.snapshot(root)
            self.assertEqual(snap['nodes']['source']['status'],'running')
            self.assertTrue(snap['ownerObservedActive'])
        snap=monitor.snapshot(root)
        self.assertEqual(snap['nodes']['source']['status'],'unknown_outcome')
        self.assertEqual(snap['status'],'blocked')

    def test_luna_uses_reserved_slot_and_completed_monitor_ends(self):
        monitor.batch.run(self.helper.out,execute=True,executor=self.helper.executor)
        calls=[]
        def call(prompt,**kwargs):
            calls.append(kwargs)
            return {'assessment':'complete','findings':[]}
        result=monitor.monitor(self.helper.out,execute=True,caller=call,session_verifier=lambda: {'status':'offline_test'},sleep=lambda _:self.fail('finished wait'))
        self.assertEqual(result['status'],'complete')
        self.assertEqual(calls[0]['model'],'gpt-6-luna')
        self.assertEqual(calls[0]['resource_class'],'supervisor')
        self.assertEqual(calls[0]['resource_policy'],self.helper.policy)
        self.assertFalse(result['productionEligible'])
        resumed=monitor.monitor(self.helper.out,execute=True,caller=lambda *a,**kw:self.fail('completed monitor call'))
        self.assertEqual(resumed['status'],'complete')

    def test_gemini_uses_separate_session_and_online_api_transport(self):
        monitor.batch.run(self.helper.out,execute=True,executor=self.helper.executor)
        calls=[]
        def call(prompt,**kwargs):
            calls.append(kwargs)
            return {'assessment':'complete','findings':[]}
        result=monitor.monitor(self.helper.out,execute=True,provider='gemini',caller=call,
            session_verifier=lambda: {'status':'offline_test'},sleep=lambda _:self.fail('finished wait'))
        self.assertEqual(result['status'],'complete')
        self.assertEqual(calls[0]['model'],'gemini-3.8-flash')
        self.assertEqual(calls[0]['service_tier'],None)
        self.assertEqual(calls[0]['resource_class'],'supervisor')
        self.assertTrue((self.helper.out/'supervision-gemini'/'turn-000.json').is_file())
