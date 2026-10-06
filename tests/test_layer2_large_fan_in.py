"""Long valid sources must not fail after paying for all translation groups."""
import copy
import json
import unittest
from pathlib import Path

from scripts import build_english_source_package as english
from scripts import sermon_sentence_interpretation as anchors
from scripts import target_language_policy as policies
from scripts import sermon_accounting as accounting
from scripts import weekly_pipeline_report as weekly
from scripts import canonical_layer2_cache_recovery as recovery
from scripts import canonical_layer2_controller as controller
from scripts import run_target_language_models as models
from tests import test_canonical_layer2_controller as fixtures
from tests import test_build_english_source_package as source_fixtures


class LargeLayer2FanInTests(unittest.TestCase):
    def fixture(self, count):
        c = fixtures.CanonicalLayer2ControllerTests('test_real_producer_and_plugin_create_only_human_pending_candidate')
        c.setUp(); self.addCleanup(c.doCleanups)
        source = source_fixtures.EnglishSourcePackageTests()
        source.setUp(); self.addCleanup(source.doCleanups)
        segments = []
        for i in range(count):
            row = copy.deepcopy(source.segments[0]); row['id'] = i; row['referenceChunkId'] = 'block-1'
            row['start'] += i * 3; row['end'] += i * 3
            for word in row['wordTimes']:
                word['start'] += i * 3; word['end'] += i * 3
            segments.append(row)
        source_fixtures.write_json(source.segments_path, segments)
        anchor = anchors.build_anchor_manifest(segments, source_path=source.segments_path, unit_policy=anchors.UNIT_POLICY_V2)
        source_fixtures.write_json(source.manifest_path, anchor)
        summary = json.loads(source.summary_path.read_text())
        summary.update(sourceDurationSeconds=count*3+10, sermonStartSeconds=0, sermonEndSeconds=count*3)
        source_fixtures.write_json(source.summary_path, summary)
        review = source.root / 'review.json'
        source_fixtures.write_json(review, dict(schemaVersion=english.REVIEW_SCHEMA_VERSION,
            alignedSegmentsSha256=english.file_sha256(source.segments_path),
            anchorManifestJsonSha256=english.json_sha256(anchor), humanApproval=True,
            reviewedBy='Synthetic source reviewer', reviewedAt='2026-09-30T00:00:00Z',
            reviewedSourceUnitIds=[u['sourceUnitId'] for u in anchor['sourceUnits']],
            checks={k:'approved' for k in english.APPROVED_CHECKS}))
        f=c.fixture.fixture
        f.source=source.build(review_path=review); f.anchor=anchor
        policy=copy.deepcopy(f.policy);policy.pop('componentSha256')
        policy['sourceScope']['englishSourcePackageJsonSha256']=english.json_sha256(f.source)
        policy['sourceScope']['anchorManifestSha256']=english.json_sha256(anchor)
        f.policy=policies.freeze_policy(policy)
        for name,value in [('source',f.source),('anchor',anchor),('policy',f.policy)]:c.fixture.write(name+'.json',value)
        calls=[]
        def caller(key,payload):
            data=json.loads(payload['messages'][1]['content']);calls.append(payload['model'])
            ids=data['sourceUnitIds']
            answer={'translationGroupId':data['translationGroupId'],'sourceUnitIds':ids,
                    'targetUtterances':['不要害怕。'], 'coverage':[{'sourceUnitId':i,'targetText':'不要害怕。'} for i in ids]}
            if payload['reasoning_effort']==f.policy['reviewer']['reasoningEffort']:
                answer['semanticReview']={'status':'pass','checks':{k:'pass' for k in models.SEMANTIC_CHECKS},
                                          'evidence':'Synthetic independent review','uncertainty':[],'issues':[]}
            role = 'reviewer' if payload['reasoning_effort']==f.policy['reviewer']['reasoningEffort'] else 'translator'
            return {'id':role+'-'+data['translationGroupId'],'model':payload['model'],
                    'choices':[{'finish_reason':'stop','message':{'content':json.dumps(answer)}}]}
        return c, f, calls, caller

    def assert_dag(self, directory, count):
        events, damaged=accounting.read_events(directory);self.assertFalse(damaged)
        runs=weekly.project(directory)['runs'];self.assertTrue(runs)
        for run in runs:self.assertEqual(run['status'],'projected',run['diagnostics'])
        starts={e['spanId']:e for e in events if e['event']=='stage_started'}
        joins=[e for e in starts.values() if e['stage'].startswith('layer2.evidence_join.')]
        self.assertTrue(joins)
        self.assertTrue(all(len(e['dependsOn'] or [])<=64 for e in starts.values()))
        for run_id in {e['runId'] for e in starts.values()}:
            ids={e['spanId'] for e in starts.values() if e['runId']==run_id}
            assembly=next(e for e in starts.values() if e['runId']==run_id and e['stage'].startswith('layer2.evidence_assembly.'))
            seen=set()
            def walk(span):
                if span in seen:return
                seen.add(span)
                for dep in starts[span]['dependsOn'] or []:walk(dep)
            walk(assembly['spanId'])
            reviews=[e for e in starts.values() if e['spanId'] in ids and e['stage'].startswith('layer2.review_validation.')]
            self.assertEqual(len(reviews),count)
            self.assertTrue(all(e['spanId'] in seen for e in reviews))

    def test_65_group_worker_and_cache_only_recovery_preserve_every_dependency(self):
        c,f,calls,caller=self.fixture(65)
        with c.active() as (config,code,key,_):c.execute(config,code,key,caller=caller)
        candidate=(c.output/'candidate.json').read_bytes()
        self.assertEqual(len(calls),130)
        (c.output/'candidate.json').unlink();(c.output/'evidence.json').unlink()
        revision=controller.snapshot(controller.load_configuration(c.path))['stateRevision']
        recovered=recovery.recover(c.path,'zh-Hans',revision)
        self.assertEqual(recovered['modelCalls'],0)
        self.assertEqual(len(calls),130)
        self.assertEqual((c.output/'candidate.json').read_bytes(),candidate)
        self.assert_dag(c.output/'accounting',65)

    def test_129_group_actual_producer_can_assemble_and_resume_without_calls(self):
        c,f,calls,caller=self.fixture(129)
        out=c.output
        first=models.run_accounted(f.source,f.anchor,f.policy,out,'fixture-key',caller,None,f.plugin_path,None,None)
        self.assertEqual(len(first['groups']),129);self.assertEqual(len(calls),258)
        (out/'evidence.json').unlink()
        second=models.run_accounted(f.source,f.anchor,f.policy,out,'',lambda *_:self.fail('cache called transport'),None,
                                    f.plugin_path,None,None,cache_only=True)
        self.assertEqual(first,second)
        self.assert_dag(out/'accounting',129)

    def test_multilevel_join_keeps_all_4097_inputs_and_rejects_duplicate_labels(self):
        from unittest.mock import patch
        events=[]
        original=[f'span-{i}' for i in range(4097)]
        with patch.object(accounting, '_emit', side_effect=events.append):
            result=accounting.bounded_dependencies('fixture.join', original, work_unit_id='fixture.join')
        self.assertLessEqual(len(result),64)
        joins={e['spanId']:e['dependsOn'] for e in events if e['event']=='stage_started'}
        self.assertTrue(all(len(deps)<=64 for deps in joins.values()))
        reached=set()
        def walk(span):
            if span in joins:
                for dep in joins[span]:walk(dep)
            else:reached.add(span)
        for span in result:walk(span)
        self.assertEqual(reached,set(original))
        for bad in [original+['span-0'], ['unsafe label'], 'not-a-list']:
            with self.assertRaises(ValueError):
                accounting.bounded_dependencies('fixture.join',bad,work_unit_id='fixture.join')
