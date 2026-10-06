"""Offline ABI, producer-rule oracles and shared-evidence checks; no model calls."""
import copy
import json
from collections import Counter
import unittest
from unittest.mock import patch
from scripts.experiments import decision_api_cases_rules as rules

class RuleCasesTests(unittest.TestCase):
    def test_smoke_counts_and_json_shared_evidence(self):
        cases=rules.build_rule_cases()
        counts=Counter(case['stageId'] for case in cases if case['a']['kind']=='program')
        self.assertEqual(counts,{'E03':12,'E04':12,'E05':12,'E07':12})
        self.assertEqual(len({c['caseId'] for c in cases}),len(cases))
        for case in cases:
            self.assertEqual(json.loads(case['b']['input']),case['sharedEvidence'])
            self.assertEqual(case['sourceKind'],'developer_fixture')
    def test_every_program_oracle_uses_actual_adapter(self):
        for case in rules.build_rule_cases():
            if case['a']['kind']!='program':continue
            original=copy.deepcopy(case)
            with self.subTest(caseId=case['caseId']):
                self.assertEqual(rules.run_rule_a(case),case['expected'])
                self.assertEqual(case,original)
    def test_no_fake_human_baseline(self):
        missing=[c for c in rules.build_rule_cases() if c['stageId'] in ('E06','E08')]
        self.assertEqual(len(missing),2)
        self.assertEqual({c['stageId']: c['subtaskId'] for c in missing},
                         {'E06': 'study_semantic_triage', 'E08': 'feedback_comment_triage'})
        for case in missing:
            self.assertEqual(case['oracleKind'],'no_executable_baseline')
            self.assertIsNone(case['expected'])
            self.assertEqual(rules.run_rule_a(case)['status'],'no_executable_baseline')
    def test_timing_and_supervisor_do_not_leak_derived_answers(self):
        for case in rules.build_rule_cases():
            if case['stageId']=='E05':
                self.assertNotIn('failures',case['sharedEvidence'])
                self.assertNotIn('failureReasons',case['sharedEvidence'])
                self.assertIn('rows',case['sharedEvidence'])
                self.assertIn('policy',case['sharedEvidence'])
            if case['stageId']=='E07':
                self.assertNotIn('recommendedAction',case['b']['input'])
    def test_adapters_call_existing_pure_functions(self):
        cases=rules.build_rule_cases()
        for adapter,target,value in [
            ('plan_repair','scripts.sermon_repair_planning.plan_repair',{'action':'sentinel','status':'sentinel','reasonCode':'sentinel'}),
            ('provider_error','scripts.sermon_provider_error.diagnostic',{'reasonCode':'sentinel'}),
            ('supervisor_recommend_action','scripts.sermon_production_supervisor.recommend_action',{'action':'sentinel','humanActionRequired':False})]:
            case=next(c for c in cases if c['a']['adapter']==adapter)
            with patch(target,return_value=value) as called:
                result=rules.run_rule_a(case)
                self.assertTrue(called.called)
                self.assertIn('sentinel',result['labels'].values())
        case=next(c for c in cases if c['a']['adapter']=='target_audio_timing_plan')
        with patch('scripts.target_audio_timing_plan.plan',return_value={'formalScheduleStatus':'sentinel','unchangedAudioCannotFitSerialTimeline':False}) as called:
            self.assertEqual(rules.run_rule_a(case)['labels']['formalScheduleStatus'],'sentinel')
            called.assert_called_once()
    def test_questions_use_official_choice_shape_and_cover_oracle(self):
        for case in rules.build_rule_cases():
            for question in case['b']['questions']:
                self.assertEqual(set(question),{'name','type','instructions','choices'})
                self.assertEqual(question['type'],'choice')
                choices=[choice['value'] for choice in question['choices']]
                self.assertEqual(len(choices),len(set(choices)))
                self.assertIn(case['expected']['labels'][question['name']],choices)
                for choice in question['choices']:
                    self.assertEqual(set(choice),{'value','description'})

    def test_evidence_reference_files_exist(self):
        for name in ('candidate-artifact','candidate-revision','review-fail','review-pass','rubric','input-manifest','gate-waiting'):
            self.assertTrue((rules.ROOT/'tests/fixtures/rqc'/(name+'.json')).is_file())
        self.assertTrue((rules.ROOT/'scripts/target_audio_timing_plan.py').is_file())

if __name__=='__main__':unittest.main()
