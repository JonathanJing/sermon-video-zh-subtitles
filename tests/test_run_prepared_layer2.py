import json
import unittest
from tests import test_codex_layer2_diagnostic as fixtures
from scripts.experiments import run_prepared_layer2 as command

class PreparedLayer2GateTests(unittest.TestCase):
    def setUp(self):
        h=fixtures.DiagnosticChainTests();h.setUp();self.addCleanup(h.doCleanups);h.freeze();self.h=h
        self.result=h.root/'source-result.json'
        self.value={'mode':'frozen_source_judge8','sourceASR':'reused_frozen_source',
            'machineJudgeStatus':'approved_for_layer2_shadow','productionEligible':False,'humanApproval':False,
            'anchorPath':str(h.fixture/'anchor.json')}
        self.result.write_text(json.dumps(self.value))

    def invoke(self,runner):
        return command.run(self.h.fixture,self.result,self.h.root/'out',self.h.root/'policy.json',runner=runner)

    def test_matching_frozen_anchor_can_dispatch(self):
        seen=[]
        self.invoke(lambda *args,**kw:seen.append((args,kw)))
        self.assertEqual(len(seen),1)
        self.assertEqual(seen[0][1]['translator_model'],'gpt-6.1-sol')

    def test_rejected_or_fresh_source_cannot_reuse_old_fixture(self):
        for field,value in [('machineJudgeStatus','rejected_for_layer2_shadow'),('mode','fresh_source_asr4_mfa_judge8'),('humanApproval',True)]:
            current=dict(self.value,**{field:value});self.result.write_text(json.dumps(current))
            with self.subTest(field=field),self.assertRaises(ValueError):
                self.invoke(lambda *args,**kw:self.fail('blocked dispatch'))

    def test_changed_anchors_block_before_cli(self):
        path=self.h.root/'different-anchor.json';anchor=dict(self.h.anchor,sourceUnits=[])
        path.write_text(json.dumps(anchor));self.value['anchorPath']=str(path);self.result.write_text(json.dumps(self.value))
        with self.assertRaisesRegex(ValueError,'anchor differs'):
            self.invoke(lambda *args,**kw:self.fail('stale dispatch'))

    def test_explicit_test_only_disagreement_can_dispatch_without_approval(self):
        self.value['machineJudgeStatus']='rejected_for_layer2_shadow'
        self.result.write_text(json.dumps(self.value))
        judge=self.h.root/'machine-judge.json'
        judge.write_text(json.dumps({'sentences':[{'sourceSentenceId':'0-s125','verdict':'fail'}]}))
        receipt=self.h.root/'adjudication.json'
        receipt.write_text(json.dumps({'schemaVersion':'diagnostic-source-disagreement-v1',
            'simulationOnly':True,'productionEligible':False,'humanApproval':False,'publishEligible':False,
            'sourceResultSha256':command._sha(self.result),'machineJudgeSha256':command._sha(judge),
            'disputedSentenceIds':['0-s125']}))
        seen=[]
        command.run(self.h.fixture,self.result,self.h.root/'out',self.h.root/'policy.json',
            test_adjudication=receipt,runner=lambda *args,**kw:seen.append(kw))
        self.assertEqual(len(seen),1)
