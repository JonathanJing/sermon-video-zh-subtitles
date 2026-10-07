"""Real provider adapters and logging over offline HTTP; no API/model calls."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import sermon_accounting as accounting
from scripts import sermon_completion as completion
from scripts import sermon_fresh_diagnostic as entry
from scripts import sermon_fresh_source_causality as causality
from scripts import sermon_log_profile as profile
from scripts import sermon_review_contracts as c
from scripts import sermon_review_budget as budget
from scripts import sermon_diagnostic_provider as provider
from scripts import sermon_bounded_business_callbacks as callbacks
from scripts import sermon_public_snapshot as public
from tests import test_sermon_fresh_diagnostic as fixtures


class FreshCausalityTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.FreshSourceTests(); f.setUp(); self.addCleanup(f.doCleanups); self.f=f
        self.root=f.f.root/'real-leaf-run'; self.root.mkdir()
        self.plan=deepcopy(f.plan); self.plan['runDirectory']=str(self.root)
        self.subject=provider.DiagnosticProvider(budget.BudgetStore(self.root/'budget',self.plan['authority']),
            self.plan['providerConfig'],executor=f.f.transport)
        callbacks.BoundedBusinessCallbacks(self.subject,self.root,source_clip=f.f.original.clip,
            fixture_id=f.f.transport.fixture_id,offline=True)
        self.recipe=dict(f.recipe)

    def execute(self):
        with patch.object(accounting,'execution_identity',return_value=self.plan['executionIdentity']):
            session=entry.FreshDiagnosticSession(self.plan,offline_transport=self.f.f.transport)
            with profile.session(self.root/'logs','fresh-semantic-fixture',work_kind='engineering',evidence_mode='synthetic'):
                result=session.prepare_source(self.recipe,self.f.authorization)
        self.value=public.read_snapshot(self.root/'fresh-source-causality.json')[0]
        self.events=accounting.read_events(self.root/'logs')[0]
        self.frozen_recipe=public.read_snapshot(self.root/'fresh-source-recipe.json')[0]
        self.result=result
        return result

    def validate(self,value=None,events=None):
        evidence=self.result['evidence']
        return causality.validate(value or self.value,events or self.events,plan=self.plan,recipe=self.frozen_recipe,
            asr_ref=evidence['asr'],review_ref=evidence['sourceCheck'],aligned_sha256=evidence['alignedSegmentsSha256'],
            source_sha256=evidence['sourceCanonicalSha256'])

    def test_actual_provider_leaves_reach_alignment_and_package(self):
        before=len(self.f.f.transport.observations); result=self.execute()
        self.assertEqual(len(self.f.f.transport.observations)-before,2)
        self.validate()
        handles=self.value['handles']
        self.assertEqual(handles['transcription']['stage'],'diagnostic.transcription')
        self.assertEqual(handles['sourceCheck']['stage'],'diagnostic.source_model')
        self.assertEqual(handles['alignment']['dependsOn'],[handles['sourceCheck']['spanId']])
        self.assertTrue(all(h['attemptId'] and h['workUnitId'] for h in handles.values()))
        self.assertEqual(result['evidence']['sourceCausalitySha256'],c.canonical_sha256(self.value))
        self.assertFalse(result['evidence']['productionEligible'])
        self.f.network.assert_not_called()

    def test_empty_edge_wrong_attempt_cross_run_artifact_and_conflicting_terminal_rejected(self):
        self.execute()
        for name,key,value in [('empty','dependsOn',[]),('attempt','attemptId','wrong'),
                              ('run','runId','wrong'),('artifact','artifactSha256','f'*64)]:
            changed=deepcopy(self.value);changed['handles']['sourceCheck'][key]=value
            with self.subTest(name=name),self.assertRaises(c.ContractError):self.validate(changed)
        ends=[e for e in self.events if e.get('event')=='stage_finished' and e.get('spanId')==self.value['handles']['sourceCheck']['spanId']]
        bad=deepcopy(ends[0]);bad['status']='failed'
        with self.assertRaises(c.ContractError):self.validate(events=self.events+[bad])
        self.validate(events=self.events+ends)  # equivalent outbox replay
        changed=deepcopy(self.value); plan=deepcopy(self.plan);plan['providerConfig']['runId']='f'*64
        changed['runId']='f'*64;changed['planSha256']=c.canonical_sha256(plan)
        for handle in changed['handles'].values():handle['productionRunId']='f'*64
        original=self.plan;self.plan=plan
        try:
            with self.assertRaises(c.ContractError):self.validate(changed)
        finally:self.plan=original

    def test_missing_leaf_and_container_substitution_rejected(self):
        self.execute()
        changed=deepcopy(self.value);del changed['handles']['sourceCheck']
        with self.assertRaises(c.ContractError):self.validate(changed)
        changed=deepcopy(self.value);changed['handles']['sourceCheck']=deepcopy(changed['handles']['intake'])
        with self.assertRaises(c.ContractError):self.validate(changed)
        handle=self.value['handles']['sourceCheck']; events=deepcopy(self.events)
        child=next(e for e in events if e['event']=='stage_started' and e['spanId']==self.value['handles']['alignment']['spanId'])
        child['parentSpanId']=handle['spanId']
        with self.assertRaises(c.ContractError):self.validate(events=events)

    def test_resume_checks_original_causality_without_new_provider_dispatch(self):
        self.execute();before=len(self.f.f.transport.observations)
        original={p:p.read_bytes() for p in (self.root/'fresh-source-causality.json',self.root/'fresh-source-evidence.json')}
        with patch.object(accounting,'execution_identity',return_value=self.plan['executionIdentity']):
            resumed=entry.FreshDiagnosticSession(self.plan,offline_transport=self.f.f.transport)
            with profile.session(self.root/'resume-logs','fresh-resume-fixture',work_kind='engineering',evidence_mode='synthetic'):
                result=resumed.prepare_source(self.recipe,self.f.authorization)
        self.assertEqual(len(self.f.f.transport.observations),before)
        self.assertEqual(result['evidence'],self.result['evidence'])
        self.assertEqual(original,{p:p.read_bytes() for p in original})

    def test_invalid_seed_and_unfrozen_consumer_reject_before_provider(self):
        before=len(self.f.f.transport.observations)
        seed=Path(self.recipe['prior_aligned_path']);original=seed.read_bytes();seed.write_bytes(b'[]')
        with self.assertRaises(c.ContractError):self.execute()
        self.assertEqual(len(self.f.f.transport.observations),before)
        seed.write_bytes(original)
        self.assertFalse((self.root/'fresh-source-evidence.json').exists())

    def test_known_invalid_source_metadata_rejects_before_any_provider(self):
        path=Path(self.recipe['prior_source_path']);source=c.read_snapshot(path)[0]
        source['source']['serviceDate']='not-a-date';path.write_bytes(c.canonical_bytes(source))
        before=len(self.f.f.transport.observations)
        with self.assertRaisesRegex(c.ContractError,'consumer_incompatible'):self.execute()
        self.assertEqual(len(self.f.f.transport.observations),before)

    def test_coherent_handle_and_artifact_rewrite_cannot_reuse_original_log(self):
        self.execute(); original=self.result
        for key,field in [('transcription','asr'),('sourceCheck','sourceCheck'),
                          ('alignment','alignedSegmentsSha256'),('sourcePackage','sourceCanonicalSha256')]:
            changed=deepcopy(self.value);changed['handles'][key]['artifactSha256']='f'*64
            self.result=deepcopy(original)
            if key in {'transcription','sourceCheck'}:self.result['evidence'][field]['receiptSha256']='f'*64
            else:self.result['evidence'][field]='f'*64
            with self.subTest(key=key),self.assertRaises(c.ContractError):self.validate(changed)
        self.result=original

    def test_persisted_mfa_preflight_resumes_without_rewriting_or_redispatch(self):
        from tests.test_sermon_mfa_identity import runtime_fixture, write_json
        runtime=self.root/'runtime.json';write_json(runtime,runtime_fixture(self.root))
        recipe=dict(self.recipe,run_mfa=True,local_runtime_path=runtime)
        before=len(self.f.f.transport.observations)
        for attempt in (1,2):
            with patch.object(accounting,'execution_identity',return_value=self.plan['executionIdentity']):
                session=entry.FreshDiagnosticSession(self.plan,offline_transport=self.f.f.transport)
                with profile.session(self.root/('interrupted-'+str(attempt)),'interrupted-fixture',
                        work_kind='engineering',evidence_mode='synthetic'):
                    with patch.object(entry.source_adapter,'prepare_source',side_effect=RuntimeError('fixture interruption')):
                        with self.assertRaisesRegex(RuntimeError,'fixture interruption'):
                            session.prepare_source(recipe,self.f.authorization)
            path=self.root/'mfa-identity-preflight.json'
            if attempt==1:original=path.read_bytes()
            else:self.assertEqual(path.read_bytes(),original)
        self.assertEqual(len(self.f.f.transport.observations)-before,2)

    def test_interrupted_model_log_recovery_keeps_old_run_partial(self):
        from scripts import sermon_pipeline as pipeline, sermon_log_contract as contract
        before=len(self.f.f.transport.observations)
        with patch.object(accounting,'execution_identity',return_value=self.plan['executionIdentity']):
            session=entry.FreshDiagnosticSession(self.plan,offline_transport=self.f.f.transport)
            with profile.session(self.root/'logs','interrupted-log-fixture',work_kind='engineering',evidence_mode='synthetic'):
                with patch.object(pipeline,'record_api_attempt',side_effect=accounting.AccountingWriteError('fixture failure')):
                    with self.assertRaises(accounting.AccountingWriteError):
                        session.prepare_source(self.recipe,self.f.authorization)
        prior=(self.root/'logs/events.jsonl').read_bytes()
        self.execute()
        self.assertEqual(len(self.f.f.transport.observations)-before,2)
        self.assertTrue((self.root/'logs/events.jsonl').read_bytes().startswith(prior))
        self.assertEqual(self.value['handles']['transcription']['executionMode'],'cache_replay')
        self.assertEqual(contract.replay_integrity(self.events)['status'],'partial')
        self.validate()

    def test_provider_cached_completion_is_explicit_reuse_not_model_execution(self):
        with patch.object(accounting,'execution_identity',return_value=self.f.plan['executionIdentity']):
            session=entry.FreshDiagnosticSession(self.f.plan,offline_transport=self.f.f.transport)
            before=len(self.f.f.transport.observations)
            with profile.session(self.f.root/'reuse-logs','reuse-fixture',work_kind='engineering',evidence_mode='synthetic'):
                result=session.prepare_source(self.f.recipe,self.f.authorization)
        value=public.read_snapshot(self.f.root/'fresh-source-causality.json')[0]
        self.assertEqual(len(self.f.f.transport.observations),before)
        for key in ('transcription','sourceCheck'):
            self.assertEqual(value['handles'][key]['executionMode'],'cache_replay')
            self.assertTrue(value['handles'][key]['stage'].endswith('_reuse'))


if __name__=='__main__':unittest.main()
