"""Synthetic contract tests; no provider/model/network. Cache decode is real."""
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from scripts import sermon_diagnostic_preview_worker as worker
from scripts import sermon_public_snapshot as public
from scripts import sermon_review_contracts as c
from tests import test_sermon_diagnostic_preview_worker as fixture
from tests import test_sermon_diagnostic_attempts as attempts_fixture

from scripts import sermon_historical_native_seed as helper


class ClosedParentTests(unittest.TestCase):
    def setUp(self):
        self.f = attempts_fixture.NewAttemptTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.plan_path = self.f.f.f.root / 'run-plan.json'
        self.plan = copy.deepcopy(self.f.plan)
        self.plan['executionIdentity']['gitCommit'] = helper.FROZEN_PARENT_COMMIT
        self.plan['executionIdentity']['loadedProjectCodeSha256']['scripts/sermon_diagnostic_preview_worker.py'] = helper.FROZEN_PARENT_WORKER_SHA256
        self.plan['providerConfig']['codeSha256'] = c.canonical_sha256(self.plan['executionIdentity'])
        self.plan_path.write_text(json.dumps(self.plan))
        state = json.loads(self.f.provider_path.read_text()); state['config'] = self.plan['providerConfig']
        self.f.provider_path.write_text(json.dumps(state))

    def close(self):
        return helper.attempts.close_parent(self.plan_path, instruction_reference_sha256='f'*64)

    def test_known_closed_parent_validation_never_mutates_ledger(self):
        self.close()
        before={p:p.read_bytes() for p in self.f.folder.rglob('*') if p.is_file()}
        observed=helper._closed_parent(self.plan_path, helper.delivery._Snapshot())
        self.assertEqual(observed[2], self.plan_path.parent.resolve())
        self.assertEqual({p:p.read_bytes() for p in before},before)
        self.assertEqual(len(self.f.f.calls),1)  # existing synthetic transcribe only

    def test_expired_but_no_explicit_close_is_not_adopted(self):
        with self.assertRaises(FileNotFoundError):helper._closed_parent(self.plan_path,helper.delivery._Snapshot())

    def test_unknown_provider_cannot_be_closed_or_adopted(self):
        state=json.loads(self.f.provider_path.read_text());next(iter(state['requests'].values()))['state']='outcome_unknown'
        self.f.provider_path.write_text(json.dumps(state))
        with self.assertRaisesRegex(c.ContractError,'reconciliation'):helper._closed_parent(self.plan_path,helper.delivery._Snapshot())

    def test_public_preflight_refuses_unknown_parent_before_reading_receipt(self):
        state=json.loads(self.f.provider_path.read_text());next(iter(state['requests'].values()))['state']='outcome_unknown'
        self.f.provider_path.write_text(json.dumps(state))
        seed=helper.HistoricalSeed(str(self.plan_path.resolve()),str(self.plan_path.parent/'missing-worker-receipt.json'))
        with self.assertRaisesRegex(c.ContractError,'reconciliation'):helper.preflight_parent(seed)
        self.assertEqual(len(self.f.f.calls),1)

    def test_wrong_reviewed_commit_or_loaded_worker_pin_rejected(self):
        for field in ('gitCommit','worker'):
            plan=copy.deepcopy(self.plan)
            if field=='gitCommit':plan['executionIdentity']['gitCommit']='a'*40
            else:plan['executionIdentity']['loadedProjectCodeSha256']['scripts/sermon_diagnostic_preview_worker.py']='0'*64
            self.plan_path.write_text(json.dumps(plan))
            with self.assertRaisesRegex(c.ContractError,'not_reviewed'):helper._closed_parent(self.plan_path,helper.delivery._Snapshot())
        self.plan_path.write_text(json.dumps(self.plan))
        self.close();close=self.f.folder/'provider-run/closed.json';value=json.loads(close.read_text())
        value['budgetStateFileSha256']='0'*64;close.write_text(json.dumps(value))
        with self.assertRaisesRegex(c.ContractError,'close_changed'):helper._closed_parent(self.plan_path,helper.delivery._Snapshot())


class SeedCacheTests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.PreviewWorkerTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        # Real fixed synthetic child, valid synthetic candidate, real PCM decode.
        with self.f.session():self.old_receipt=self.f.launch()
        self.old_spec=self.old_receipt['spec']
        self.checked=worker._spec(self.f.root,self.old_spec,self.f.context,True)[1]
        self.spec=copy.deepcopy(self.old_spec);self.spec['out']=str(self.f.root/'new-seeded-output')
        self.new_checked=copy.deepcopy(self.checked)
        self.new_checked['candidate']['candidateId']='different-synthetic-candidate-envelope'
        self.proof=dict(schemaVersion=helper.SCHEMA,status='historical_inspection_only',productionEligible=False,
            modelExecutedCurrentAttempt=False,originalRefs=self.old_receipt['artifacts'],units=[])
        manifest=worker._manifest(self.new_checked)
        for index,_ in enumerate(self.checked['candidate']['groups']):
            unit_path=Path(self.old_spec['out'])/f'receipts/unit-{index:04d}.json';wav=Path(self.old_spec['out'])/f'units/unit-{index:04d}.wav'
            unit=worker._read(unit_path)
            unit=dict(unit,candidateJsonSha256=c.canonical_sha256(self.new_checked['candidate']),previewContextSha256=c.canonical_sha256(manifest))
            self.proof['units'].append(dict(unitIndex=index,oldAudio=worker._ref(wav),oldUnit=worker._ref(unit_path),unit=unit))
        self.before={p:p.read_bytes() for p in Path(self.old_spec['out']).rglob('*') if p.is_file()}

    def test_actual_seed_and_renderer_cache_hit_zero_synth_with_new_envelope(self):
        seed=helper.HistoricalSeed(str(self.f.root/'run-plan.json'),self.old_receipt['receiptPath'])
        # Only historical authority/admission are synthetic. The seed writer,
        # ordinary unit admission, full decode and renderer cache branches run.
        with patch.object(helper,'inspect',return_value=self.proof),self.f.session():
            reference,span=helper.seed(self.f.root,self.f.subject,self.f.context,self.spec,self.new_checked,self.old_receipt['inputs'],seed,depends_on=[])
            self.assertTrue(span);self.assertEqual(worker._read(reference['path'])['status'],'historical_inspection_only')
            def forbidden(*args,**kwargs):raise AssertionError('cache rebind may not load or synthesize')
            with patch.object(worker.preview,'checked_context',return_value=self.new_checked):
                result=worker.preview.render({k:Path(v) for k,v in self.spec['paths'].items()},Path(self.spec['checkpoint_map_path']),
                    Path(self.spec['operation_policies_path']),Path(self.spec['out']),strict_rubric=self.new_checked['strict_rubric'],
                    diagnostic_context=self.f.context,deadline_monotonic=time.monotonic()+60,synth_factory=forbidden,
                    device='cpu',predecessor_spans=[span])
            self.assertEqual(len(result['renderedGroupIds']),len(self.proof['units']))
        self.assertEqual({p:p.read_bytes() for p in self.before},self.before)
        out=Path(self.spec['out'])
        self.assertFalse(list((out/'receipts').glob('*.attempt.json')))
        self.assertFalse((out/'worker-receipt.json').exists()) # helper cannot fabricate worker success
        for row in self.proof['units']:
            self.assertEqual(worker._ref(out/f"units/unit-{row['unitIndex']:04d}.wav")['fileBytesSha256'],row['oldAudio']['fileBytesSha256'])

    def test_partial_existing_seed_is_never_retried_or_dispatched(self):
        out=Path(self.spec['out']);out.mkdir();(out/'partial').write_bytes(b'unknown')
        with patch.object(helper,'inspect') as check,self.assertRaisesRegex(c.ContractError,'reconciliation'):
            helper.seed(self.f.root,self.f.subject,self.f.context,self.spec,self.new_checked,[],None)
        check.assert_not_called()

    def test_sound_identity_ignores_only_candidate_context_envelope(self):
        self.assertEqual(helper._sound(self.checked,self.old_spec,0),helper._sound(self.new_checked,self.spec,0))
        original=helper._sound(self.checked,self.old_spec,0)
        changes=[('targetText','changed'),('sourceUnitIds',['changed']),('translationGroupId','changed')]
        for key,value in changes:
            changed=copy.deepcopy(self.new_checked);changed['candidate']['groups'][0][key]=value
            self.assertNotEqual(helper._sound(changed,self.spec,0),original)
        for key,value in [('dtype','float32'),('seed',43),('attention','eager'),('instruct','different')]:
            self.assertNotEqual(helper._sound(self.new_checked,dict(self.spec,**{key:value}),0),original)
        for key,value in [('modelRevision','changed'),('speakerKey','changed'),('conditioningSha256','0'*64)]:
            changed=copy.deepcopy(self.new_checked);changed['adapter'][key]=value
            self.assertNotEqual(helper._sound(changed,self.spec,0),original)

    def test_untrusted_seed_type_is_rejected_before_any_file_io(self):
        with self.assertRaisesRegex(c.ContractError,'trusted_type'):
            helper.inspect(self.f.root,self.f.subject,self.f.context,self.spec,self.new_checked,[],{'parent_receipt_path':'arbitrary'})

    def inspect_fixture(self, changed=None, *, runtime_change=False, checkpoint_change=False, preflight=False):
        from contextlib import ExitStack
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);newroot=Path(tmp.name).resolve()
        config=dict(self.f.subject.config,runId='d'*64)
        subject=helper.provider.DiagnosticProvider(helper.budget.BudgetStore(newroot/'budget',self.f.store.authority),config)
        context=dict(self.f.context,runId=config['runId'],runConfigSha256=c.canonical_sha256(config),storeSha256=subject.store.store_sha256)
        new_spec=copy.deepcopy(self.spec);new_spec['out']=str(newroot/'native-output')
        old=copy.deepcopy(self.checked);new=copy.deepcopy(self.new_checked)
        old['native_runtime_binding']={'runtimeIdentity':'same'};new['native_runtime_binding']=dict(old['native_runtime_binding'])
        old['checkpoint_binding']={'treeSha256':'f'*64};new['checkpoint_binding']=dict(old['checkpoint_binding'])
        new['diagnostic_context']=context
        if changed:new['candidate']['groups'][0]['targetText']='changed sound'
        if runtime_change:new['native_runtime_binding']['runtimeIdentity']='changed'
        if checkpoint_change:new['checkpoint_binding']['treeSha256']='0'*64
        public.save_once(newroot/'run-plan.json',dict(runDirectory=str(newroot),providerConfig=config))
        oldplanpath=self.f.root/'run-plan.json';public.save_once(oldplanpath,dict(providerConfig=self.f.subject.config))
        saved=copy.deepcopy(self.old_receipt)
        saved.pop('receiptPath');saved.pop('receiptFileSha256');saved['offlineFixture']=False
        saved['schemaVersion']=getattr(worker,'V3_SCHEMA',worker.SCHEMA)
        saved.pop('historicalSeedProof',None)
        request_path=Path(saved['spec']['out'])/'worker-request.json';request=worker._read(request_path)
        request['workerCodeSha256']=helper.FROZEN_PARENT_WORKER_SHA256;request_path.write_text(json.dumps(request))
        saved['artifacts']=[worker._ref(row['path']) for row in saved['artifacts']]
        receipt_path=Path(self.old_receipt['receiptPath']);receipt_path.write_text(json.dumps(saved))
        seed=helper.HistoricalSeed(str(oldplanpath),str(receipt_path))
        oldplan={'providerConfig':self.f.subject.config}
        with ExitStack() as stack:
            stack.enter_context(patch.object(helper,'_closed_parent',return_value=(oldplan,oldplan,self.f.root,self.f.subject,{},worker._ref(oldplanpath))))
            stack.enter_context(patch.object(helper,'_lineage',return_value=[worker._ref(newroot/'run-plan.json')]))
            validate=stack.enter_context(patch.object(worker,'validate_preview_receipt',return_value=saved))
            stack.enter_context(patch.object(worker,'_spec',side_effect=[(saved['spec'],old,saved['inputs']),(new_spec,new,saved['inputs'])]))
            result=helper.preflight_parent(seed) if preflight else helper.inspect(newroot,subject,context,new_spec,new,saved['inputs'],seed)
            validate.assert_called_once()
            return result

    def test_inspection_requires_old_native_validator_and_exact_new_sound(self):
        proof=self.inspect_fixture()
        self.assertEqual(len(proof['units']),2)
        self.assertFalse(proof['modelExecutedCurrentAttempt']);self.assertFalse(proof['oldBudgetMoved'])
        self.assertEqual(proof['evidenceMode'],'historical_reuse')
        self.assertNotEqual(proof['currentRunId'],proof['originalRunId'])

    def test_public_parent_preflight_returns_bound_evidence_without_authority(self):
        report=self.inspect_fixture(preflight=True)
        self.assertFalse(report['grantsExecutionAuthority']);self.assertFalse(report['productionEligible'])
        self.assertEqual((report['providerCalls'],report['modelCalls']),(0,0))
        self.assertEqual(report['unitCount'],2)
        for key in ('parentPlan','closure','workerReceipt','workerRequest'):
            self.assertEqual(report[key],worker._ref(report[key]['path']))
        self.assertEqual(len(report['soundIdentitySha256']),2)

    def test_changed_sound_runtime_or_full_tree_blocks_before_seed(self):
        for options,reason in [({'changed':True},'sound_identity_changed'),({'runtime_change':True},'runtime_or_groups_changed'),
                               ({'checkpoint_change':True},'checkpoint_tree_changed')]:
            with self.subTest(options=options),self.assertRaisesRegex(c.ContractError,reason):self.inspect_fixture(**options)

    def test_complete_group_lane_required(self):
        self.assertEqual(len(helper._all_groups(self.spec,self.checked)),2)
        with self.assertRaisesRegex(c.ContractError,'complete_lane'):
            helper._all_groups(dict(self.spec,group_ids=[self.checked['candidate']['groups'][0]['translationGroupId']]),self.checked)



class WorkerV4MigrationTests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.PreviewWorkerTests();self.f.setUp();self.addCleanup(self.f.doCleanups)

    def test_only_exact_trusted_native_seed_type_is_admitted(self):
        seed=helper.HistoricalSeed(str(self.f.root/'run-plan.json'),str(self.f.out/'worker-receipt.json'))
        for value,offline in [(dict(parent_plan_path=seed.parent_plan_path),False),(seed,True)]:
            with self.subTest(offline=offline),self.assertRaisesRegex(c.ContractError,'trusted_native_required'):
                worker.launch_preview(self.f.root,self.f.subject,self.f.context,self.f.spec,historical_seed=value,offline_fixture=offline)

    def test_v4_explicit_null_missing_and_mismatched_proof_rejected(self):
        with self.f.session():receipt=self.f.launch()
        self.assertEqual(receipt['schemaVersion'],worker.SCHEMA)
        self.assertIsNone(receipt['historicalSeedProof'])
        request=worker._read(self.f.out/'worker-request.json')
        self.assertEqual(request['schemaVersion'],'sermon-diagnostic-preview-worker-request-v4')
        self.assertIsNone(request['historicalSeedProof'])
        path=Path(receipt['receiptPath'])
        for value in ('missing',worker._ref(self.f.out/'manifest.json')):
            saved={k:v for k,v in receipt.items() if k not in ('receiptPath','receiptFileSha256')}
            if value=='missing':saved.pop('historicalSeedProof')
            else:saved['historicalSeedProof']=value
            path.write_text(json.dumps(saved));envelope=dict(saved,receiptPath=str(path),receiptFileSha256=worker._ref(path)['fileBytesSha256'])
            with self.assertRaisesRegex(c.ContractError,'historical_seed_contract_changed'):
                worker.validate_preview_receipt(self.f.root,self.f.subject,self.f.context,envelope)

    def test_old_v3_request_cannot_execute_and_v4_requires_proof_field(self):
        path=self.f.root/'request-migration.json'
        for request,reason in [({'schemaVersion':'sermon-diagnostic-preview-worker-request-v3'},'request_version_changed'),
                               ({'schemaVersion':'sermon-diagnostic-preview-worker-request-v4'},'historical_seed_contract_changed')]:
            path.write_text(json.dumps(request))
            with patch.object(worker.harness,'bounded_process',side_effect=AssertionError('must not execute')), \
                 self.assertRaisesRegex(c.ContractError,reason):worker._worker(path)

    def test_v3_readonly_projection_keeps_full_checkpoint_flag_and_never_respawns(self):
        with self.f.session():receipt=self.f.launch()
        out=self.f.out;saved=worker._read(out/'worker-receipt.json');request=worker._read(out/'worker-request.json')
        saved['schemaVersion']=worker.V3_SCHEMA;saved.pop('historicalSeedProof')
        request['schemaVersion']='sermon-diagnostic-preview-worker-request-v3';request.pop('historicalSeedProof')
        request['workerCodeSha256']=worker.READONLY_NATIVE_WORKER_CODE_SHA256
        public.save_once(self.f.root/'run-plan.json',{'executionIdentity':{'gitCommit':helper.FROZEN_PARENT_COMMIT,
            'loadedProjectCodeSha256':{'scripts/sermon_diagnostic_preview_worker.py':helper.FROZEN_PARENT_WORKER_SHA256}}})
        digest=c.canonical_sha256(request);(out/'worker-request.json').write_text(json.dumps(request))
        (out/'worker-attempt.json').write_text(json.dumps({'workerAttemptId':digest,'requestSha256':digest,'status':'reserved'}))
        child=worker._read(out/'worker-result.json');child['requestSha256']=digest;(out/'worker-result.json').write_text(json.dumps(child))
        saved['workerAttemptId']=saved['requestSha256']=digest;saved['artifacts']=[worker._ref(row['path']) for row in saved['artifacts']]
        (out/'worker-receipt.json').write_text(json.dumps(saved));envelope=dict(saved,receiptPath=str(out/'worker-receipt.json'),receiptFileSha256=worker._ref(out/'worker-receipt.json')['fileBytesSha256'])
        with patch.object(worker,'_spec',wraps=worker._spec) as spec_check,patch.object(worker.harness,'bounded_process',side_effect=AssertionError('must not respawn')):
            worker.validate_preview_receipt(self.f.root,self.f.subject,self.f.context,envelope)
            self.assertFalse(spec_check.call_args.kwargs['legacy_checkpoint'])
            helper.delivery._inspect_preview(self.f.root,self.f.subject,self.f.context,self.f.f.candidate['targetLocale'],envelope,helper.delivery._Snapshot())
        before=(self.f.state_path.read_bytes(),self.f.ledger_path.read_bytes())
        with self.f.session(),patch.object(worker.harness,'bounded_process',side_effect=AssertionError('must not respawn')):
            self.assertEqual(self.f.launch(),envelope)
        self.assertEqual(before,(self.f.state_path.read_bytes(),self.f.ledger_path.read_bytes()))
        plan=worker._read(self.f.root/'run-plan.json');plan['executionIdentity']['loadedProjectCodeSha256']['scripts/sermon_diagnostic_preview_worker.py']='0'*64
        (self.f.root/'run-plan.json').write_text(json.dumps(plan))
        with self.assertRaisesRegex(c.ContractError,'worker_attempt_changed'):
            worker.validate_preview_receipt(self.f.root,self.f.subject,self.f.context,envelope)

if __name__=='__main__':unittest.main()
