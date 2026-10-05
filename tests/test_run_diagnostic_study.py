import json
import threading
import unittest
from unittest.mock import patch
from scripts import run_codex_layer2_test as command
from scripts.experiments import run_diagnostic_study as study
from scripts import codex_layer2_diagnostic as diagnostic
from scripts.production_concurrency_profile import profile_v1
from tests import test_source_bound_diagnostic_audio as audio_tests
from tests import test_codex_layer2_diagnostic as chain_tests

class DiagnosticStudyTests(unittest.TestCase):
    def setUp(self):
        audio=audio_tests.SourceBoundAudioTests();audio.setUp();self.addCleanup(audio.doCleanups)
        chain=chain_tests.DiagnosticChainTests();chain.setUp();self.addCleanup(chain.doCleanups)
        self.profile=profile_v1()
        chain.source['source']['media']['sha256']=study.admission.sha(audio.args.media)
        chain.rebind()
        diagnostic.freeze_fixture(chain.source,chain.anchor,chain.policy,chain.plan,chain.data.plugin_path,chain.fixture,
            authorization_ref='isolated test',code_commit='a'*40,translator_model='gpt-6.1-sol',concurrency_profile=self.profile)
        transport=chain.transport();transport.execution_identity['concurrencyProfile']=self.profile
        policy_path=chain.root/'resource-policy.json'
        policy_path.write_text(json.dumps({'schemaVersion':'sermon-unified-resource-policy-v1',
            'brokerRoot':str(chain.root/'broker'),'capacities':{'cpu':4,'online_api':4,'codex_cli':24,'spark_tts':1,'publisher':1}}))
        original=command.run_diagnostic_test
        def with_policy(*args,**kw):
            kw['resource_policy_path']=policy_path
            return original(*args,**kw)
        with patch.object(command,'run_diagnostic_test',side_effect=with_policy):
            lock=threading.Lock()
            def serial_fixture_process(*a,**kw):
                with lock:return chain.process(*a,**kw)
            chain.invoke(transport=transport,process=serial_fixture_process)
        self.chain=chain
        self.options=dict(fixture=chain.fixture,candidate=chain.out/'diagnostic-candidate.json',
            evidence=chain.out/'evidence.json',media=audio.args.media,out_dir=chain.root/'study',kind='outline',
            profile=self.profile,resource_policy={'schemaVersion':'sermon-unified-resource-policy-v1',
            'brokerRoot':str(chain.root/'broker'),'capacities':{'cpu':4,'online_api':4,'codex_cli':24,'spark_tts':1,'publisher':1}})

    def caller(self,prompt,**kw):
        self.assertEqual(kw['resource_class'],'business')
        self.assertEqual(kw['concurrency_profile'],self.profile)
        task=json.loads(prompt.split('INPUT:\n')[1])
        return {'sections':[{'title':'Diagnostic title','body':'Grounded draft.',
            'sourceUnitIds':[task['sourceUnits'][0]['sourceUnitId']]}]}

    def test_actual_candidate_readmission_and_pending_result(self):
        result=study.execute(**self.options,caller=self.caller)
        self.assertFalse(result['productionEligible'] or result['humanApproval'] or result['releaseEligible'])
        self.assertEqual(result['humanReview'],'pending')
        self.assertEqual(result['artifact']['kind'],'outline')
        self.assertTrue((self.options['out_dir']/'result.json').is_file())

    def test_tampered_candidate_starts_no_call(self):
        path=self.options['candidate'];value=json.loads(path.read_text());value['actualHumanApproval']=True
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'scope_changed'):
            study.execute(**self.options,caller=lambda *a,**kw:self.fail('model call'))

    def test_unknown_source_reference_rejected(self):
        with self.assertRaisesRegex(ValueError,'unknown source units'):
            study.execute(**self.options,caller=lambda *a,**kw:{'sections':[{'title':'T','body':'B','sourceUnitIds':['foreign']}]})
