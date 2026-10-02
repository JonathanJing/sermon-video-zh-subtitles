from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from scripts import sermon_diagnostic_attempts as attempts, sermon_diagnostic_provider as provider
from scripts import sermon_review_budget as budget, sermon_review_contracts as c
from scripts import sermon_strict_layer2 as strict
from tests import test_run_bounded_diagnostic as fixtures


class NewAttemptTests(unittest.TestCase):
    def setUp(self):
        self.runtime=fixtures.BoundedRunTests();self.runtime.setUp();self.addCleanup(self.runtime.doCleanups)
        self.f=self.runtime
        self.identity={'gitCommit':'a'*40,'trackedWorkingTreeDirty':False,
            'loadedProjectCodeSha256':{'scripts/source.py':'b'*64},'pythonVersion':'3.12',
            'platform':'darwin','architecture':'arm64','scope':'loaded'}
        config=dict(self.f.subject.config,codeSha256=c.canonical_sha256(self.identity))
        self.now=500.0
        self.subject=provider.DiagnosticProvider(self.f.subject.store,config,executor=self.f.capture,
            domain=lambda:'7'*64,monotonic=lambda:self.now)
        self.plan={'schemaVersion':'sermon-bounded-diagnostic-plan-v1','runDirectory':str(self.f.f.root),
            'providerConfig':config,'authority':self.subject.store.authority,
            'executionIdentity':self.identity,'sourceClipPath':str(self.f.clip)}
        strict.save_once(self.f.f.root/'run-plan.json',self.plan)
        with self.f.f.session():self.subject.transcribe('synthetic',self.f.raw)
        self.folder=self.f.f.root/'budget'/budget.STORE_ID
        self.provider_path=self.folder/'provider-run/state.json'
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.newroot=Path(tmp.name)/'new'
        self.parents=[attempts.terminal_parent(self.plan)]
        self.authorization={'schemaVersion':attempts.AUTH_SCHEMA,'parentPlanSha256':c.canonical_sha256(self.plan),
            'parentSnapshotsSha256':c.canonical_sha256(self.parents),'instructionReferenceSha256':'f'*64,
            'newMaxRequests':2,'newHardLimitMicrousd':1000000,'newTotalWallSeconds':1200,
            'cumulativeMaxRequests':10,'cumulativeHardLimitMicrousd':5000000}

    def prepare(self,**options):
        args=dict(new_root=self.newroot,authorization=self.authorization,execution_identity=self.identity)
        args.update(options);return attempts.prepare_new_attempt(self.plan,**args)

    def test_expired_parent_prepares_new_clock_without_mutation_or_api(self):
        self.now=10000
        with self.assertRaisesRegex(ValueError,'deadline'):
            with self.subject._locked() as (_,state):self.subject._remaining(state)
        old=self.provider_path.read_bytes();ledger=(self.folder/'state.json').read_bytes()
        plan,linkage=self.prepare();attempts.persist_new_attempt(plan,linkage,self.authorization)
        attempts.persist_new_attempt(plan,linkage,self.authorization)
        self.assertNotEqual(plan['providerConfig']['runId'],self.plan['providerConfig']['runId'])
        self.assertEqual(plan['providerConfig']['totalWallSeconds'],1200)
        self.assertEqual(self.provider_path.read_bytes(),old)
        self.assertEqual((self.folder/'state.json').read_bytes(),ledger)
        self.assertFalse((self.newroot/'budget').exists())
        self.assertEqual(len(self.f.calls),1)
        for key in ('sourceMediaSha256','sourceClipSha256','sourceAudioSha256','sourceWindowSeconds',
                    'credentialReferenceSha256','projectId','organizationId'):
            self.assertEqual(plan['providerConfig'][key],self.plan['providerConfig'][key])

    def test_unknown_provider_result_never_gets_new_attempt(self):
        state=json.loads(self.provider_path.read_bytes());next(iter(state['requests'].values()))['state']='outcome_unknown'
        self.provider_path.write_text(json.dumps(state))
        with self.assertRaisesRegex(c.ContractError,'reconciliation_required'):self.prepare()
        self.assertFalse(self.newroot.exists());self.assertEqual(len(self.f.calls),1)

    def test_changed_receipt_or_authorization_is_rejected(self):
        state=json.loads(self.provider_path.read_bytes());call=next(iter(state['requests']))
        path=self.folder/'provider-run'/(call+'.json');path.write_text('{}')
        with self.assertRaisesRegex(c.ContractError,'receipt_changed'):self.prepare()
        self.assertFalse(self.newroot.exists())

    def test_no_implicit_cap_increase_or_parent_directory_reuse(self):
        for key,value in [('cumulativeMaxRequests',2),('cumulativeHardLimitMicrousd',1),
                          ('parentSnapshotsSha256','0'*64),('newMaxRequests',125)]:
            with self.subTest(key=key),self.assertRaises(c.ContractError):
                self.prepare(authorization=dict(self.authorization,**{key:value}))
        for root in (self.f.f.root,self.f.f.root/'nested',self.f.f.root.parent):
            with self.subTest(root=root),self.assertRaisesRegex(c.ContractError,'roots_overlap'):
                self.prepare(new_root=root)

    def test_parent_changed_after_preparation_cannot_be_persisted(self):
        plan,linkage=self.prepare();self.provider_path.write_bytes(self.provider_path.read_bytes()+b' ')
        with self.assertRaisesRegex(c.ContractError,'parent_changed_before_persist'):
            attempts.persist_new_attempt(plan,linkage,self.authorization)
        self.assertFalse(self.newroot.exists())

    def test_duplicate_ancestors_and_dirty_new_code_do_not_create_attempt(self):
        with self.assertRaisesRegex(c.ContractError,'duplicate_parent'):
            self.prepare(ancestor_plans=[self.plan])
        with self.assertRaisesRegex(c.ContractError,'invalid_extension_identity'):
            self.prepare(execution_identity=dict(self.identity,trackedWorkingTreeDirty=True))


class NewAttemptV2Tests(unittest.TestCase):
    def setUp(self):
        self.fixture=NewAttemptTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.f=self.fixture;self.path=self.f.f.f.root/'run-plan.json'
        self.baseline=attempts.observe_legacy_lineage(self.path)
        self.auth=dict(schemaVersion=attempts.AUTH_SCHEMA_V2,parentPlanSha256=c.canonical_sha256(self.f.plan),
            legacyBaselineSha256=c.canonical_sha256(self.baseline),instructionReferenceSha256='f'*64,
            newRoot=str(self.f.newroot.resolve()),newRunId='d'*64,newMaxRequests=2,newHardLimitMicrousd=1000000,
            newTotalWallSeconds=1200,cumulativeMaxRequests=10,cumulativeHardLimitMicrousd=5000000,
            scope='fresh_distinct_stage_no_old_replay')

    def prepare(self,**changes):
        args=dict(new_root=self.f.newroot,authorization=self.auth,execution_identity=self.f.identity,baseline=self.baseline)
        args.update(changes)
        with unittest.mock.patch.object(attempts.provider,'boot_identity',return_value='7'*64), \
             unittest.mock.patch.object(attempts.time,'monotonic',return_value=10000.):
            return attempts.prepare_new_attempt_v2(self.path,**args)

    def test_v2_fixed_target_and_one_use_replay_keep_original_unchanged(self):
        before={r['path']:Path(r['path']).read_bytes() for r in self.baseline['snapshots']}
        plan,linkage=self.prepare()
        with unittest.mock.patch.object(attempts.provider,'boot_identity',return_value='7'*64), \
             unittest.mock.patch.object(attempts.time,'monotonic',return_value=10000.):
            attempts.persist_new_attempt_v2(plan,linkage,self.auth);attempts.persist_new_attempt_v2(plan,linkage,self.auth)
        self.assertEqual(before,{p:Path(p).read_bytes() for p in before})
        self.assertFalse((self.f.newroot/'budget').exists())
        self.assertEqual(plan['providerConfig']['runId'],self.auth['newRunId'])
        with self.assertRaisesRegex(c.ContractError,'target_changed'):
            self.prepare(new_root=self.f.newroot.parent/'different')
        changed=dict(plan,runDirectory=str(self.f.newroot.parent/'other'))
        with self.assertRaisesRegex(c.ContractError,'linkage_changed'):
            attempts.persist_new_attempt_v2(changed,linkage,self.auth)
        self.assertEqual(len(list((self.path.parent/'new-attempt-authorizations').glob('*.json'))),1)
        changed_auth=dict(self.auth,newRoot=str((self.f.newroot.parent/'fork').resolve()),newRunId='e'*64,
            instructionReferenceSha256='a'*64)
        with self.assertRaisesRegex(c.ContractError,'successor_already_reserved'):
            self.prepare(new_root=changed_auth['newRoot'],authorization=changed_auth)
        self.assertFalse((self.f.newroot.parent/'fork').exists())

    def test_active_parent_needs_permanent_close_and_cached_read_still_works(self):
        with unittest.mock.patch.object(attempts.provider,'boot_identity',return_value='7'*64), \
             unittest.mock.patch.object(attempts.time,'monotonic',return_value=501.):
            with self.assertRaisesRegex(c.ContractError,'still_dispatchable'):
                attempts.prepare_new_attempt_v2(self.path,new_root=self.f.newroot,authorization=self.auth,
                    execution_identity=self.f.identity,baseline=self.baseline)
        before=self.f.provider_path.read_bytes();closed=attempts.close_parent(self.path,instruction_reference_sha256='f'*64)
        self.assertTrue(closed.exists());self.assertEqual(before,self.f.provider_path.read_bytes())
        with self.f.f.f.session():
            cached=self.f.subject.transcribe('synthetic',self.f.f.raw)
        self.assertIsInstance(cached,dict);self.assertEqual(len(self.f.f.calls),1)
        from scripts import sermon_pipeline as pipeline
        with self.assertRaisesRegex(pipeline.PreDispatchRejection,'permanently_closed'):
            self.f.subject._reserve('new-call',{'api':{'model':'gpt-transcribe'}},self.f.subject.limits,
                audio_bounds=dict(requests=1,wallTimeMs=1,costMicrousd=1))
        self.assertEqual(before,self.f.provider_path.read_bytes());self.prepare()

    def test_unknown_provider_never_enters_legacy_observation(self):
        state=json.loads(self.f.provider_path.read_bytes());next(iter(state['requests'].values()))['state']='outcome_unknown'
        self.f.provider_path.write_text(json.dumps(state))
        with self.assertRaisesRegex(c.ContractError,'reconciliation_required'):attempts.observe_legacy_lineage(self.path)

    def test_legacy_unsettled_d5_uses_full_cap_without_settlement_or_refund(self):
        bounds=dict(requests=1,inputTokens=8192,outputTokens=4096,wallTimeMs=300000,costMicrousd=307200)
        # An explicitly synthetic unfinished ledger reservation, no provider/model call.
        identity={key:'a'*64 for key in budget.IDENTITY_FIELDS[:5]}
        identity.update(targetLocale='zh-Hans',workUnitId='l2.zh-Hans.synthetic')
        self.f.subject.store.reserve(identity,operation_id='synthetic.intent',kind='initial_generation',
            revision_id='r1',revision_number=1,input_sha256='b'*64,bounds=bounds)
        before=(self.f.folder/'state.json').read_bytes()
        with self.assertRaisesRegex(c.ContractError,'reconciliation_required'):attempts.terminal_parent(self.f.plan)
        b=attempts.observe_legacy_lineage(self.path)
        self.assertEqual(b['priorRequestCount'],self.f.subject.config['maxRequests'])
        self.assertEqual(b['priorReservedMicrousd'],self.f.subject.config['hardLimitMicrousd'])
        self.assertFalse(b['oldReplayAllowed']);self.assertEqual(b['refundedMicrousd'],0)
        self.assertEqual(before,(self.f.folder/'state.json').read_bytes())

    def test_closure_cannot_omit_fixed_ancestor_or_change_source_binding(self):
        other=NewAttemptTests();other.setUp();self.addCleanup(other.doCleanups)
        root=other.f.f.root;plan=deepcopy(other.plan);plan['providerConfig']['runId']='c'*64
        state=json.loads(other.provider_path.read_bytes());state['config']=plan['providerConfig'];other.provider_path.write_text(json.dumps(state))
        (root/'run-plan.json').write_text(json.dumps(plan))
        history=dict(schemaVersion=attempts.SCHEMA,parentEvidence=[attempts.terminal_parent(plan)])
        (self.path.parent/'linked-history.json').write_text(json.dumps(history))
        b=attempts.observe_legacy_lineage(self.path)
        self.assertEqual(len(b['observations']),2)
        missing=deepcopy(b);missing['observations']=missing['observations'][:1]
        with self.assertRaisesRegex(c.ContractError,'baseline_changed'):attempts.validate_baseline(missing)
        b['observations'][0]['projectedPlan']['providerConfig']['sourceMediaSha256']='0'*64
        with self.assertRaises(c.ContractError):attempts.validate_baseline(b)
