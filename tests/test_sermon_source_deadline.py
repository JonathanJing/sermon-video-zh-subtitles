"""Original MFA deadline and controlled historical Source migration contracts."""
from pathlib import Path
from copy import deepcopy
import json,os,sys,tempfile,time,subprocess,unittest
from types import SimpleNamespace
from unittest.mock import patch
from scripts import mfa_alignment as mfa,mfa_backend as backend
from scripts import sermon_source_producer_compatibility as compat
from scripts import sermon_source_failure as failure,sermon_review_contracts as c
from scripts import sermon_fresh_diagnostic as entry,sermon_log_profile as profile,sermon_accounting as accounting
from scripts.sermon_pipeline import PreDispatchRejection
from tests import test_mfa_alignment as alignment_fixtures
from tests import test_sermon_fresh_diagnostic as source_fixtures


class OriginalDeadlineTests(unittest.TestCase):
    def setUp(self):
        self.network=self.enterContext(patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('network forbidden')))

    def test_real_hanging_child_is_killed_at_original_remaining_deadline(self):
        started=time.monotonic();deadline=started+.2
        with self.assertRaises(mfa.MFADeadlineReached):
            mfa.bounded_process([sys.executable,'-I','-B','-c','import time; time.sleep(5)'],
                timeout=300,deadline_monotonic=deadline,capture_output=True)
        self.assertGreaterEqual(time.monotonic(),deadline)
        self.assertLess(time.monotonic()-started,2.)
        self.network.assert_not_called()

    def test_expired_and_invalid_deadline_prevents_any_child_dispatch(self):
        with patch.object(mfa.subprocess,'run',side_effect=AssertionError('must not launch')) as run:
            with self.assertRaises(mfa.MFADeadlineReached):
                mfa.bounded_process(['inert'],timeout=1380,deadline_monotonic=time.monotonic()-1)
            for value in (True,float('nan'),float('inf'),'deadline'):
                with self.subTest(value=str(value)),self.assertRaises(ValueError):
                    mfa.bounded_process(['inert'],timeout=300,deadline_monotonic=value)
        run.assert_not_called()

    def test_full_alignment_retains_60_300_1380_caps_and_never_renews_remaining(self):
        f=alignment_fixtures.AlignmentTest();f.setUp();self.addCleanup(f.doCleanups)
        f.chunks=[{'id':2,'start':0.,'end':180.,'text':'No. But I can’t 73.'}]
        clock=[100.];timeouts=[]
        def run(command,**kwargs):
            timeouts.append((list(map(str,command)),kwargs['timeout']))
            result=f.fake_run(command,**kwargs);clock[0]+=5.;return result
        with patch.object(mfa.time,'monotonic',side_effect=lambda:clock[0]),patch.object(mfa.subprocess,'run',side_effect=run):
            result=mfa.align_reference_chunks(f.chunks,f.clip,f.root/'bounded',mfa_executable=f.exe,
                dictionary_path=f.dictionary,acoustic_model=f.acoustic,deadline_monotonic=400.)
        self.assertEqual([s['text'] for s in result],['No.','But I can’t 73.'])
        self.assertEqual([cap for _,cap in timeouts],[60,295.,290.])
        self.assertEqual(timeouts[1][0][0],'ffmpeg');self.assertEqual(timeouts[2][0][1],'align')
        # A larger budget preserves the existing 1380-second align cap for 180s.
        timeouts.clear();clock[0]=100.
        with patch.object(mfa.time,'monotonic',side_effect=lambda:clock[0]),patch.object(mfa.subprocess,'run',side_effect=run):
            other=mfa.align_reference_chunks(f.chunks,f.clip,f.root/'ample',mfa_executable=f.exe,
                dictionary_path=f.dictionary,acoustic_model=f.acoustic,deadline_monotonic=5500.)
        self.assertEqual([cap for _,cap in timeouts],[60,300,1380])
        self.assertEqual([(r['text'],r['start'],r['end']) for r in result],[(r['text'],r['start'],r['end']) for r in other])

    def test_g2p_is_bounded_and_success_after_deadline_is_not_admitted(self):
        f=alignment_fixtures.AlignmentTest();f.setUp();self.addCleanup(f.doCleanups)
        f.dictionary.write_text('no N OW\n');g2p=f.root/'g2p.zip';g2p.write_bytes(b'inert')
        clock=[100.];timeouts=[]
        def run(command,**kwargs):
            timeouts.append(kwargs['timeout']);result=f.fake_run(command,**kwargs);clock[0]+=5.;return result
        with patch.object(mfa.time,'monotonic',side_effect=lambda:clock[0]),patch.object(mfa.subprocess,'run',side_effect=run):
            mfa.align_reference_chunks(f.chunks,f.clip,f.root/'bounded',mfa_executable=f.exe,
                dictionary_path=f.dictionary,acoustic_model=f.acoustic,g2p_model=g2p,deadline_monotonic=400.)
        self.assertEqual(timeouts,[60,295.,290.,285.])
        clock[0]=100.
        def late(*args,**kwargs):clock[0]=401.;return subprocess.CompletedProcess(args[0],0)
        with patch.object(mfa.time,'monotonic',side_effect=lambda:clock[0]),patch.object(mfa.subprocess,'run',side_effect=late):
            with self.assertRaises(mfa.MFADeadlineReached):
                mfa.bounded_process(['inert'],timeout=300,deadline_monotonic=400.)

    def test_backend_versions_share_same_deadline_and_expiry_never_spark_fails_over(self):
        f=alignment_fixtures.AlignmentTest();f.setUp();self.addCleanup(f.doCleanups);f.exe.chmod(0o755)
        f.chunks=[{'id':2,'start':0.,'end':180.,'text':'No. But I can’t 73.'}]
        options={'mfa_executable':str(f.exe),'dictionary_path':str(f.dictionary),'acoustic_model':str(f.acoustic)}
        clock=[100.];caps=[]
        def run(command,**kwargs):caps.append(kwargs['timeout']);result=f.fake_run(command,**kwargs);clock[0]+=5.;return result
        with patch.object(mfa.time,'monotonic',side_effect=lambda:clock[0]),patch.object(mfa.subprocess,'run',side_effect=run),patch.object(backend.spark,'preflight',side_effect=AssertionError('network forbidden')):
            backend.align_reference_chunks(f.chunks,f.clip,f.root/'backend',local_options=options,
                spark_options={},allow_spark_fallback=False,deadline_monotonic=400.)
        self.assertEqual(caps,[60,60,290.,285.])
        with patch.object(backend,'local_identity',side_effect=mfa.MFADeadlineReached('mfa_original_deadline_reached')),patch.object(backend.spark,'preflight') as remote:
            with self.assertRaises(mfa.MFADeadlineReached):
                backend.preflight(local_options={},spark_options={},allow_spark_fallback=False,deadline_monotonic=time.monotonic()+5)
        remote.assert_not_called()
        with patch.object(backend.spark,'preflight') as remote:
            with self.assertRaisesRegex(ValueError,'mfa_deadline_requires_local_only'):
                backend.preflight(local_options={},spark_options={},deadline_monotonic=time.monotonic()+5)
        remote.assert_not_called()

    def test_forced_spark_with_original_deadline_rejects_before_any_backend_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);clip=root/'audio';clip.write_bytes(b'inert')
            args=dict(local_options={},spark_options={},backend='spark',
                      deadline_monotonic=time.monotonic()+5)
            with patch.object(backend.spark,'preflight') as remote, \
                 patch.object(backend.spark,'align_reference_chunks') as align, \
                 patch.object(backend,'local_identity') as local:
                with self.assertRaisesRegex(ValueError,'^mfa_deadline_requires_local_only$'):
                    backend.preflight(**args)
                with self.assertRaisesRegex(ValueError,'^mfa_deadline_requires_local_only$'):
                    backend.align_reference_chunks([{'text':'Hello.','start':0.,'end':1.}],
                        clip,root/'out',**args)
            remote.assert_not_called();align.assert_not_called();local.assert_not_called()
            self.assertFalse((root/'out').exists())

    def test_explicit_macbook_retains_original_deadline_without_spark(self):
        f=alignment_fixtures.AlignmentTest();f.setUp();self.addCleanup(f.doCleanups);f.exe.chmod(0o755)
        f.chunks=[{'id':2,'start':0.,'end':180.,'text':'No. But I can’t 73.'}]
        options={'mfa_executable':str(f.exe),'dictionary_path':str(f.dictionary),'acoustic_model':str(f.acoustic)}
        clock=[100.];caps=[]
        def run(command,**kwargs):
            caps.append(kwargs['timeout']);result=f.fake_run(command,**kwargs);clock[0]+=5.;return result
        with patch.object(mfa.time,'monotonic',side_effect=lambda:clock[0]), \
             patch.object(mfa.subprocess,'run',side_effect=run), \
             patch.object(backend.spark,'preflight') as remote, \
             patch.object(backend.spark,'align_reference_chunks') as remote_align:
            result=backend.align_reference_chunks(f.chunks,f.clip,f.root/'explicit-mac',
                local_options=options,spark_options={},backend='macbook',deadline_monotonic=400.)
        self.assertEqual(caps,[60,60,290.,285.])
        self.assertTrue(all(row['alignmentExecutionBackend']=='macbook-local' for row in result))
        self.assertEqual(json.loads((f.root/'explicit-mac/backend.json').read_text())['backend'],'macbook-local')
        remote.assert_not_called();remote_align.assert_not_called()


class SourceTransmissionTests(unittest.TestCase):
    def test_actual_source_builder_reuses_original_budget_deadline_without_dispatch(self):
        f=source_fixtures.FreshSourceTests();f.setUp();self.addCleanup(f.doCleanups)
        with f.subject._locked() as (_,state):deadline=state['startedMonotonic']+f.subject.config['totalWallSeconds']
        calls=len(f.f.transport.observations)
        with self.assertRaisesRegex(c.ContractError,'fresh_mfa_original_deadline_changed'):
            f.prepare(deadline_monotonic=deadline+5400)
        result=f.prepare(deadline_monotonic=deadline)
        self.assertFalse(result['source']['review']['humanApproval'])
        self.assertEqual(len(f.f.transport.observations),calls)

    def test_changed_asr_alignment_gets_exact_deadline_and_safe_typed_error(self):
        f=source_fixtures.FreshSourceTests();f.setUp();self.addCleanup(f.doCleanups)
        from scripts import sermon_fresh_diagnostic_source as source
        original=source.returned_receipt
        def changed(root,config,operation,model):
            receipt,ref=original(root,config,operation,model)
            if Path(root)==f.root and operation=='transcription.initial':
                receipt=deepcopy(receipt);receipt['response']['text']+=' Changed.'
            return receipt,ref
        runtime=f.root/'runtime.json';item=f.root/'inert-local-mfa';item.write_bytes(b'inert')
        runtime.write_bytes(c.canonical_bytes({'backend':'macbook-local','runtime':{'files':{
            'mfa_executable':{'path':str(item),'sha256':c.bytes_sha256(item.read_bytes())}}}}))
        with f.subject._locked() as (_,state):deadline=state['startedMonotonic']+f.subject.config['totalWallSeconds']
        calls=len(f.f.transport.observations)
        with patch.object(source,'returned_receipt',side_effect=changed),patch.object(backend,'align_reference_chunks',side_effect=mfa.MFADeadlineReached('private subprocess payload')) as align:
            with self.assertRaisesRegex(c.ContractError,'^fresh_mfa_original_deadline_reached$'):
                f.prepare(run_mfa=True,local_runtime_path=runtime)
        self.assertEqual(align.call_args.kwargs['deadline_monotonic'],deadline)
        self.assertFalse(align.call_args.kwargs['allow_spark_fallback']);self.assertFalse((f.root/'source.json').exists())
        self.assertEqual(len(f.f.transport.observations),calls)
        events,_=accounting.read_events(f.root/'logs')
        self.assertTrue(any(r['event']=='stage_finished' and r.get('stage')=='diagnostic.alignment' and r['status']=='failed' for r in events))


class TypedFailureTests(unittest.TestCase):
    def setUp(self):
        self.plan={'providerConfig':{'runId':'a'*64}}
        self.known={'unknownModelCallIds':[],'reservedMicrousd':123}

    def test_controlled_codes_only_preserve_pending_and_no_refunds(self):
        for error,reason in [(c.ContractError('fresh_mfa_original_deadline_reached'),'fresh_mfa_original_deadline_reached'),
            (PreDispatchRejection('provider_run_deadline_reached'),'provider_run_deadline_reached'),
            (ValueError('/private/audio model output credential'),'source_preparation_not_confirmed'),
            (c.ContractError('fresh_unapproved_code'),'source_preparation_not_confirmed'),
            (c.ContractError('invalid_snapshot_file'),'fresh_source_snapshot_invalid')]:
            with self.subTest(type=type(error).__name__):
                receipt=failure.receipt(error,plan=self.plan,provider_snapshot=self.known)
                self.assertEqual(receipt['reasonCode'],reason);self.assertEqual(receipt['status'],'blocked')
                self.assertEqual(receipt['schemaVersion'],'sermon-fresh-diagnostic-source-failure-v2')
                self.assertFalse(receipt['productionEligible']);self.assertEqual(receipt['humanAcceptance'],'pending')
                self.assertNotIn('credential',json.dumps(receipt));self.assertNotIn('/private',json.dumps(receipt))
        self.assertEqual(self.known['reservedMicrousd'],123)

    def test_unknown_outcomes_and_missing_snapshot_never_become_completed(self):
        for snapshot in (None,{'unknownModelCallIds':['opaque-call'],'reservedMicrousd':123}):
            receipt=failure.receipt(TimeoutError('private transport body'),plan=self.plan,provider_snapshot=snapshot)
            self.assertEqual(receipt['status'],'reconciliation_required');self.assertTrue(receipt['requiresReconciliation'])

    def test_real_entry_source_failed_stage_and_unknown_reraising_preserve_exit(self):
        from tests.test_sermon_diagnostic_prefect_flow import config_fixture
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);config=config_fixture(root,locales=('zh-Hans',));previews={k:v['previewSpec'] for k,v in config['locales'].items()}
            for index,snapshot in enumerate((self.known,{'unknownModelCallIds':['opaque'],'reservedMicrousd':123})):
                folder=root/str(index);folder.mkdir();error=c.ContractError('fresh_mfa_original_deadline_reached')
                def failed_source(*args):
                    raise error
                session=SimpleNamespace(root=folder,plan=self.plan,evidence_mode='synthetic',
                    subject=SimpleNamespace(config=self.plan['providerConfig'],snapshot=lambda:snapshot),
                    prepare_source=failed_source)
                with patch.object(entry,'FreshDiagnosticSession',return_value=session):
                    args=dict(key=None,execute=False,source_recipe={},authorization={},locale_drafts={'zh-Hans':{}},
                        preview_specs=previews,offline_transport=object())
                    if index:
                        with self.assertRaises(c.ContractError) as caught:entry.run_fresh_diagnostic(self.plan,**args)
                        self.assertIs(caught.exception,error)
                    else:self.assertEqual(entry.run_fresh_diagnostic(self.plan,**args)['status'],'blocked')
                receipt=c.read_snapshot(next((folder/'fresh-source-failures').glob('*.json')))[0]
                self.assertEqual(receipt['requiresReconciliation'],bool(index))
                events,_=accounting.read_events(folder/'fresh-diagnostic-logs')
                self.assertTrue(any(r['event']=='stage_finished' and r.get('stage')=='diagnostic.source_preparation' and r['status']=='failed' for r in events))
                self.assertTrue(any(r['event']=='run_finished' and r['status']==('failed' if index else 'completed') for r in events))


class PreciseCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.binding={key:'a'*64 for key in ('parentPlanSha256','newPlanSha256','sourceCanonicalSha256',
            'anchorCanonicalSha256','alignmentBytesSha256','asrReceiptSha256','sourceCheckReceiptSha256')}

    def test_exact_old_new_mapping_retains_historical_provenance_and_binding(self):
        result=compat.verify(compat.HISTORICAL_SOURCE_SHA256,compat.CURRENT_SOURCE_SHA256,compat.CURRENT_SOURCE_SHA256,self.binding)
        self.assertEqual(result['historicalProducerSha256'],compat.HISTORICAL_SOURCE_SHA256)
        self.assertEqual(result['binding'],self.binding);self.assertEqual(len(result['changedModules']),3)
        for key in ('newASRCalls','newSourceCheckCalls','newMFACalls'):self.assertEqual(result[key],0)
        self.assertEqual(result['sourceExecution'],'historical_receipts_reused_current_deterministic_inspection')
        self.assertFalse(result['productionEligible'])

    def test_unknown_deadline_or_semantic_hash_change_missing_binding_and_new_plan_drift_fail(self):
        for module in compat.CURRENT_SOURCE_SHA256:
            changed=dict(compat.CURRENT_SOURCE_SHA256);changed[module]='f'*64
            with self.subTest(module=module),self.assertRaises(c.ContractError):
                compat.verify(compat.HISTORICAL_SOURCE_SHA256,changed,changed,self.binding)
        with self.assertRaises(c.ContractError):
            compat.verify(compat.HISTORICAL_SOURCE_SHA256,compat.CURRENT_SOURCE_SHA256,compat.HISTORICAL_SOURCE_SHA256,self.binding)
        with self.assertRaises(c.ContractError):
            compat.verify(compat.HISTORICAL_SOURCE_SHA256,compat.CURRENT_SOURCE_SHA256,compat.CURRENT_SOURCE_SHA256,{})
        old=dict(compat.HISTORICAL_SOURCE_SHA256);old['scripts/mfa_alignment.py']='0'*64
        with self.assertRaises(c.ContractError):compat.verify(old,compat.CURRENT_SOURCE_SHA256,compat.CURRENT_SOURCE_SHA256,self.binding)


if __name__=='__main__':
    unittest.main()
