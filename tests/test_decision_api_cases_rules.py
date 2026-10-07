"""Offline ABI, producer-rule oracles and shared-evidence checks; no model calls."""
import copy
import json
import hashlib
from collections import Counter
from pathlib import Path
import tempfile
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

    def test_task_specific_choices_and_explicit_policies(self):
        for case in rules.build_rule_cases():
            if case['a']['kind']!='program':continue
            adapter=case['a']['adapter']
            for question in case['b']['questions']:
                self.assertEqual([c['value'] for c in question['choices']],
                                 rules.TASK_CHOICES[adapter][question['name']])
                self.assertIn(rules.RULE_INSTRUCTIONS[adapter],question['instructions'])
            self.assertEqual(case['sharedEvidence']['decisionTask']['rulesVersion'],rules.RULES_VERSION)
            if case['stageId']=='E04':
                self.assertEqual({c['value'] for c in case['b']['questions'][0]['choices']},
                                 {'pass','requires_review'})
            if case['stageId']=='E07':
                self.assertNotIn('repair_translation',str(case['b']['questions']))
                self.assertIn('NOW',case['b']['questions'][1]['instructions'])

    def test_evidence_reference_files_exist(self):
        for name in ('candidate-artifact','candidate-revision','review-fail','review-pass','rubric','input-manifest','gate-waiting'):
            self.assertTrue((rules.ROOT/'tests/fixtures/rqc'/(name+'.json')).is_file())
        self.assertTrue((rules.ROOT/'scripts/target_audio_timing_plan.py').is_file())


class RealRuleCasesTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.folder=self.root/'corpus'
        self.folder.mkdir();(self.folder/'review').mkdir()
        self.corpus=patch.object(rules,'REAL_RULE_CORPUS',Path('corpus'))
        self.corpus.start();self.addCleanup(self.corpus.stop)
        source={'source':{'sourceId':'fixture-original-source','media':{'sha256':'f'*64}}}
        anchor={'sourceUnits':[{'sourceUnitId':f'u{i}'} for i in range(8)]}
        source_ref=self.save('source.json',source);anchor_ref=self.save('anchor.json',anchor)
        units=[];rendered=[];results=[]
        for index in range(8):
            text='神爱世人';recognized=text if index%2==0 else '神世人'
            text_sha=hashlib.sha256(text.encode()).hexdigest();audio_sha=hashlib.sha256(str(index).encode()).hexdigest()
            status,similarity,differences,_=rules._screen_values(text,recognized,'zh-Hans',.88)
            units.append({'unitIndex':index,'translationGroupId':f'g{index}','sourceUnitIds':[f'u{index}'],'text':text})
            rendered.append({'textGroupId':f'g{index}','targetTextSha256':text_sha,'audio':{'sha256':audio_sha,'path':'never-read.wav'}})
            results.append({'textGroupId':f'g{index}','targetTextSha256':text_sha,'audioSha256':audio_sha,
                            'recognized':recognized,'status':status,'similarity':similarity,'differences':differences})
        job={'targetLocale':'zh-Hans','inputs':{'englishSourcePackage':source_ref,'anchorManifest':anchor_ref},'units':units}
        manifest={'targetLocale':'zh-Hans','targetLanguageSpeechJobJsonSha256':rules._json_sha(job),
                  'englishSourcePackageJsonSha256':rules._json_sha(source),'track':{'sha256':'a'*64},'units':rendered}
        receipt={'schemaVersion':'sermon-target-language-audio-screening-v1','targetLocale':'zh-Hans',
                 'targetLanguageSpeechJobJsonSha256':rules._json_sha(job),'trackSha256':'a'*64,
                 'coverage':1.0,'minSimilarity':.88,'model':'fixture-shared-asr','modelRevision':'fixture',
                 'reviewedGroupIds':[u['translationGroupId'] for u in units],
                 'unitAudioSha256s':[r['audioSha256'] for r in results],'results':results}
        self.save('job.json',job);self.save('render-manifest.json',manifest)
        self.save('review/asr-screening.json',receipt)

    def save(self,name,value):
        path=self.folder/name;path.write_text(json.dumps(value,ensure_ascii=False))
        return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                'jsonSha256':rules._json_sha(value)}

    def test_real_balanced_sample_bound_to_complete_corpus_without_gold(self):
        cases=rules.build_real_rule_cases(self.root,max_cases=4)
        self.assertEqual(len(cases),4)
        self.assertEqual(Counter(rules.run_rule_a(c)['labels']['status'] for c in cases),
                         {'pass':2,'requires_review':2})
        self.assertEqual(len({c['clusterId'] for c in cases}),1)
        for case in cases:
            self.assertIsNone(case['expected'])
            self.assertEqual(case['oracleKind'],'unadjudicated_real_input')
            self.assertEqual(case['sourceKind'],'frozen_real_shared_asr')
            self.assertEqual(case['provenance']['fullCorpusUnitCount'],8)
            self.assertTrue(case['provenance']['fullCorpusUnitCoverageVerified'])
            self.assertFalse(case['provenance']['independentSemanticGold'])
            self.assertEqual(json.loads(case['b']['input']),case['sharedEvidence'])
            self.assertNotIn('similarity',case['sharedEvidence'])
            self.assertNotIn('status',case['sharedEvidence'])
            self.assertNotIn('differences',case['sharedEvidence'])
            self.assertIn('sourceFileSha256',case['provenance'])
        self.assertEqual(cases,rules.build_real_rule_cases(self.root,max_cases=4))

    def test_all_units_checked_including_unsampled_tail(self):
        path=self.folder/'review/asr-screening.json';value=json.loads(path.read_text())
        value['results'][-1]['recognized']='changed unselected ASR'
        self.save('review/asr-screening.json',value)
        with self.assertRaisesRegex(ValueError,'derived_rule_mismatch'):
            rules.build_real_rule_cases(self.root,max_cases=1)

    def test_source_binding_or_unit_text_tampering_fails(self):
        source=json.loads((self.folder/'source.json').read_text());source['changed']=True
        self.save('source.json',source)
        with self.assertRaisesRegex(ValueError,'source_binding_mismatch'):
            rules.build_real_rule_cases(self.root)

    def test_only_json_read_never_missing_media(self):
        original=rules._read_frozen_json
        visited=[]
        def checked(path):
            self.assertEqual(Path(path).suffix,'.json');visited.append(path)
            return original(path)
        with patch.object(rules,'_read_frozen_json',side_effect=checked):
            self.assertEqual(len(rules.build_real_rule_cases(self.root)),8)
        self.assertEqual(len(visited),5)

    def test_revision_independent_original_source_cluster(self):
        first=rules.build_real_rule_cases(self.root,max_cases=4)
        manifest=json.loads((self.folder/'render-manifest.json').read_text());manifest['audioRevision']='next'
        self.save('render-manifest.json',manifest)
        second=rules.build_real_rule_cases(self.root,max_cases=4)
        self.assertEqual([c['clusterId'] for c in first],[c['clusterId'] for c in second])
        self.assertEqual([c['caseId'] for c in first],[c['caseId'] for c in second])
        self.assertNotEqual(first[0]['provenance']['renderManifestFileSha256'],
                            second[0]['provenance']['renderManifestFileSha256'])

if __name__=='__main__':unittest.main()
