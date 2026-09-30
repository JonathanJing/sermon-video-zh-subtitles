"""Opt-in writer failure drills; all model facts are synthetic, no transport."""
import copy
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import sermon_accounting as accounting
from scripts import sermon_log_contract as contract
from scripts import sermon_log_outbox as outbox
from scripts import sermon_log_profile as profile
from scripts import sermon_review_observation as review
from scripts import weekly_pipeline_report as weekly
from scripts import export_sermon_trace as otlp
from scripts import export_observability_trace as safe
from scripts import sermon_logs as logs
from tests.test_accounting_log_contract import fixture
from tests.test_sermon_review_contracts import load


class ProfileWriterTests(unittest.TestCase):
    def test_prepare_freezes_identity_without_reserving_invalid_sequence(self):
        with tempfile.TemporaryDirectory() as tmp:
            def build(e,p,s):return dict(fixture('stage-start'),eventId=e,producerId=p,sequence=s)
            first=outbox.prepare(tmp,build)
            with self.assertRaises(contract.ContractError):outbox.prepare(tmp,lambda e,p,s:{**build(e,p,s),'prompt':'no'})
            second=outbox.prepare(tmp,build)
            self.assertEqual(second['sequence'],first['sequence']+1)
            self.assertEqual(second['producerId'],first['producerId'])
            self.assertFalse((Path(tmp)/'events.jsonl').exists())

    def test_preappend_failure_replays_same_event_without_external_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            event=fixture('stage-start')
            with patch.object(outbox,'_append',side_effect=OSError('fault')),self.assertRaises(OSError):outbox.deliver(tmp,event)
            self.assertEqual(accounting.read_events(tmp)[0],[])
            result=outbox.replay_pending(tmp)
            self.assertEqual(result,{'replayedEvents':1,'externalActions':0})
            self.assertEqual(accounting.read_events(tmp)[0],[event])
            self.assertEqual(outbox.replay_pending(tmp)['replayedEvents'],0)

    def test_postappend_preack_crash_duplicates_same_facts_and_replay_dedups(self):
        with tempfile.TemporaryDirectory() as tmp:
            event=fixture('stage-start');original=Path.unlink
            def fail(path,*args,**kwargs):
                if path.parent.name=='.pending-events':raise OSError('fault')
                return original(path,*args,**kwargs)
            with patch.object(Path,'unlink',fail),self.assertRaises(OSError):outbox.deliver(tmp,event)
            self.assertEqual(accounting.read_events(tmp)[0],[event])
            outbox.replay_pending(tmp)
            rows,damaged=accounting.read_events(tmp)
            self.assertFalse(damaged);self.assertEqual(rows,[event,event])
            self.assertEqual(contract.replay_integrity(rows)['equivalentDuplicatesIgnored'],1)
            self.assertEqual(weekly.project(tmp)['duplicateEventsIgnored'],1)

    def test_folder_persistence_precedes_intent_and_ledger_ack(self):
        with tempfile.TemporaryDirectory() as tmp:
            timeline=[];sync=outbox.jobs._sync_directory_ancestry;persist=outbox.jobs._persist;append=outbox._append
            def synced(path):sync(path);timeline.append('ancestry')
            def persisted(path,value):persist(path,value);timeline.append('intent' if path.parent.name=='.pending-events' else 'profile')
            def appended(fd,event):append(fd,event);timeline.append('append')
            with patch.object(outbox.jobs,'_sync_directory_ancestry',synced),patch.object(outbox.jobs,'_persist',persisted),patch.object(outbox,'_append',appended):
                outbox.deliver(Path(tmp)/'new'/'ledger',fixture('stage-start'))
            self.assertEqual(timeline,['ancestry','profile','intent','append'])
            responder=[]
            with patch.object(outbox.jobs,'_sync_directory_ancestry',side_effect=OSError('fault')):
                with self.assertRaises(OSError):
                    outbox.deliver(Path(tmp)/'failed',fixture('stage-start'));responder.append('called')
            self.assertFalse(responder)

    def test_transient_ledger_creation_race_retries_only_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            opened=outbox.os.open;failures=[]
            def once(path,*args,**kwargs):
                if path=='events.jsonl' and not failures:
                    failures.append(True);raise FileNotFoundError('darwin_creation_race')
                return opened(path,*args,**kwargs)
            with patch.object(outbox.os,'open',side_effect=once):outbox.deliver(tmp,fixture('stage-start'))
            self.assertEqual(len(accounting.read_events(tmp)[0]),1)
            self.assertEqual(len(failures),1)

    def test_rejects_symlinks_and_oversize_before_append(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);outside=root/'outside';outside.mkdir();(outside/'events.jsonl').write_text('sentinel')
            (root/'link').symlink_to(outside,target_is_directory=True)
            for folder in (root/'link',):
                with self.assertRaises((ValueError,OSError)):outbox.deliver(folder,fixture('stage-start'))
            ledger=root/'ledger';ledger.mkdir();(ledger/'events.jsonl').symlink_to(outside/'events.jsonl')
            with self.assertRaises((ValueError,OSError)):outbox.deliver(ledger,fixture('stage-start'))
            self.assertEqual((outside/'events.jsonl').read_text(),'sentinel')
            event=dict(fixture('stage-start'),extra='x'*contract.MAX_EVENT_BYTES)
            with self.assertRaisesRegex(contract.ContractError,'event_size_limit'):outbox.deliver(root/'oversize',event)
            self.assertFalse((root/'oversize').exists())

    def test_thread_and_process_append_have_no_loss_and_separate_producers(self):
        with tempfile.TemporaryDirectory() as tmp:
            def deliver(i):
                event=outbox.prepare(tmp,lambda e,p,s:dict(fixture('stage-start'),eventId=e,producerId=p,sequence=s,spanId=f'span-{i}'))
                outbox.deliver(tmp,event)
            with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(deliver,range(12)))
            code="""from scripts import sermon_log_outbox as o
from tests.test_accounting_log_contract import fixture
import sys
for i in range(3):
 e=o.prepare(sys.argv[1],lambda e,p,s:dict(fixture('stage-start'),eventId=e,producerId=p,sequence=s,spanId='child-'+str(i)))
 o.deliver(sys.argv[1],e)
"""
            subprocess.run([sys.executable,'-c',code,tmp],check=True,capture_output=True)
            rows,damaged=accounting.read_events(tmp)
            self.assertFalse(damaged);self.assertEqual(len(rows),15);self.assertEqual(len({r['eventId'] for r in rows}),15)
            producers={r['producerId'] for r in rows};self.assertEqual(len(producers),2)
            self.assertEqual(sorted(len([r for r in rows if r['producerId']==p]) for p in producers),[3,12])
            for p in producers:
                values=sorted(r['sequence'] for r in rows if r['producerId']==p)
                self.assertEqual(values,list(range(1,len(values)+1)))

    def test_process_context_propagates_and_downgrade_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            with profile.session(tmp,'synthetic',work_kind='production',evidence_mode='synthetic'):
                with accounting.stage('parent',work_unit_id='l2.zh-Hans.group.001',depends_on=[]) as parent:
                    env=accounting.subprocess_environment()
                    code="from scripts import sermon_accounting as a\nwith a.stage('child',depends_on=[]):a.record_workload('child',{'segmentCount':1})"
                    subprocess.run([sys.executable,'-c',code],env=env,check=True,capture_output=True)
                    broken=dict(env);broken.pop(profile.PROFILE_ENV);broken.pop(profile.CONTEXT_ENV)
                    result=subprocess.run([sys.executable,'-c',code],env=broken,capture_output=True)
                    self.assertNotEqual(result.returncode,0)
            rows,damaged=accounting.read_events(tmp);self.assertFalse(damaged)
            self.assertTrue(all(contract.valid_event(r) for r in rows))
            child=next(r for r in rows if r['event']=='stage_started' and r['stage']=='child')
            self.assertEqual(child['parentSpanId'],parent);self.assertEqual(child['workUnitId'],'l2.zh-Hans.group.001')
            self.assertEqual(len({r['runId'] for r in rows}),1)
            self.assertEqual(contract.replay_integrity(rows)['status'],'consistent')

    def test_api_fields_are_observed_and_log_failure_never_calls_transport(self):
        with tempfile.TemporaryDirectory() as tmp:
            with profile.session(tmp,'synthetic',work_kind='production',evidence_mode='synthetic'):
                with profile.context(logicalCallId='review.1',attemptNumber=1,role='quality_review'):
                    with accounting.stage('review',work_unit_id='l2.zh-Hans.group.001',executor_type='production_model',depends_on=[]):
                        aid=accounting.record_api_started('gpt-6-sol',{'requestPayloadSha256':'a'*64})
                        accounting.record_api_attempt('gpt-6-sol',{'id':'fixture-response'},.01,attempt_id=aid)
                        called=[]
                        with patch.object(outbox,'deliver',side_effect=OSError('fault')):
                            with self.assertRaises(accounting.AccountingWriteError):
                                accounting.record_api_started('gpt-6-sol');called.append(True)
                        self.assertFalse(called)
            rows,_=accounting.read_events(tmp);end=next(r for r in rows if r['event']=='api_attempt')
            self.assertIsNone(end['model']);self.assertIsNone(end['providerScopeKey']);self.assertEqual(end['usageStatus'],'not_reported')
            self.assertTrue(all(v is None for v in end['usage'].values()))
            self.assertEqual(end['providerResponseId'],end['responseId']);self.assertEqual(end['modelCallId'],aid)
            self.assertEqual(end['missingReasons']['inputTokens'],'provider_not_reported')
            # Failed emit consumed a sequence: readers expose the loss, never synthesize a model retry.
            self.assertEqual(logs.inspect_logs(tmp,run_id='all')['status'],'needs_attention')

    def test_review_states_hashes_and_repair_chain_survive_all_readers(self):
        with tempfile.TemporaryDirectory() as tmp:
            with profile.session(tmp,'synthetic',work_kind='production',evidence_mode='synthetic'):
                with accounting.stage('rqc',work_unit_id='l2.zh-Hans.group.001',depends_on=[]):
                    for name in ('candidate-revision','review-fail','gate-waiting','repair-plan'):review.record(load(name))
            rows,damaged=accounting.read_events(tmp);self.assertFalse(damaged)
            expected=review.observations(rows);self.assertEqual(len(expected),4)
            self.assertEqual(expected[1]['evidence']['executionStatus'],'succeeded')
            self.assertEqual(expected[1]['evidence']['reviewVerdict'],'needs_rework')
            self.assertIsNone(expected[1]['evidence']['admissionStatus'])
            self.assertEqual(expected[2]['evidence']['admissionStatus'],'waiting_human')
            self.assertEqual(expected[3]['evidence']['triggerReceiptSha256'],load('review-fail')['receiptSha256'])
            reports=[accounting.summarize(tmp),weekly.project(tmp)['runs'][0],otlp.export(tmp)[1]]
            for result in reports:self.assertEqual(result['reviewObservations'],expected)
            safe.export(Path(tmp),Path(tmp)/'safe')
            self.assertEqual(weekly.project(Path(tmp)/'safe')['runs'][0]['reviewObservations'],expected)
            self.assertIn('meaning_omission',weekly.markdown(weekly.project(tmp)))
            invalid=copy.deepcopy(next(e for e in rows if e['event']=='rqc_observation' and e['role']=='quality_review'))
            invalid['rqcEvidence']['admissionStatus']='admitted'
            self.assertFalse(contract.valid_event(invalid))
            invalid['rqcEvidence']['prompt']='private'
            self.assertFalse(contract.valid_event(invalid))

    def test_direct_gate_observations_cannot_manufacture_admission(self):
        with tempfile.TemporaryDirectory() as tmp:
            with profile.session(tmp,'synthetic',work_kind='production',evidence_mode='synthetic'):
                with accounting.stage('rqc',work_unit_id='l2.zh-Hans.group.001',depends_on=[]):
                    review.record(load('gate-waiting'))
            rows,_=accounting.read_events(tmp)
            event=next(r for r in rows if r['event']=='rqc_observation')
            self.assertTrue(contract.valid_event(event))
            forged=copy.deepcopy(event)
            forged['rqcEvidence'].update(admissionStatus='admitted',allowedNextActions=['prepare_layer3'],
                                         reasonCodes=['arbitrary_reason'])
            self.assertFalse(contract.valid_event(forged))
            forged['rqcEvidence']['reasonCodes']=['all_required_evidence_passed']
            forged['rqcEvidence']['allowedNextActions']=['prepare_layer3','retry_review']
            self.assertFalse(contract.valid_event(forged))
            forged['rqcEvidence'].update(admissionStatus='waiting_human',allowedNextActions=['prepare_layer3'],
                                         reasonCodes=['all_required_evidence_passed'])
            self.assertFalse(contract.valid_event(forged))

    def test_legacy_session_stays_legacy_and_profile_cannot_mix_same_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            with accounting.accounting_session(tmp,'legacy'):
                with accounting.stage('old'):pass
            rows,_=accounting.read_events(tmp);self.assertTrue(all('contractVersion' not in r for r in rows))
            event=fixture('stage-start');event['runId']=rows[0]['runId']
            with self.assertRaisesRegex(ValueError,'run_contract_version_mismatch'):outbox.deliver(tmp,event)
            self.assertEqual(accounting.read_events(tmp)[0],rows)


if __name__=='__main__':unittest.main()


class DurableProfileContextTests(unittest.TestCase):
    def test_detached_job_restores_private_bounded_context_and_runs_once(self):
        import time
        from scripts import sermon_workflow_jobs as jobs
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ledger=root/'accounting';jobroot=root/'jobs'
            code="from scripts import sermon_accounting as a\nwith a.stage('worker',depends_on=[]):a.record_workload('worker',{'segmentCount':1})"
            command=[sys.executable,'-c',code]
            with profile.session(ledger,'synthetic',work_kind='production',evidence_mode='synthetic'):
                with accounting.stage('dispatch',work_unit_id='l2.zh-Hans.group.001',depends_on=[]) as dispatch:
                    result=jobs.start_job(jobroot,{'stage':'profile-test'},command,5)
                    deadline=time.monotonic()+8
                    while time.monotonic()<deadline:
                        result=jobs.inspect_job(jobroot,result['jobId'])
                        if result['status'] in {'succeeded','failed','uncertain'}:break
                        time.sleep(.025)
                    self.assertEqual(result['status'],'succeeded')
                    self.assertEqual(jobs.start_job(jobroot,{'stage':'profile-test'},command,5),result)
            rows,damaged=accounting.read_events(ledger);self.assertFalse(damaged)
            child=next(e for e in rows if e['event']=='stage_started' and e['stage']=='worker')
            self.assertEqual(child['jobId'],result['jobId']);self.assertEqual(child['dispatchSpanId'],dispatch)
            self.assertIsNone(child['parentSpanId'])
            self.assertEqual(child['workUnitId'],'l2.zh-Hans.group.001')
            self.assertEqual(len([e for e in rows if e['event']=='stage_started' and e['stage']=='worker']),1)
            sidecar=jobs._read(jobroot/result['jobId']/'accounting-context.json')
            self.assertTrue(all(k.startswith('SERMON_ACCOUNTING_') for k in sidecar['environment']))
            self.assertNotIn('PATH',sidecar['environment'])
            with self.assertRaises(ValueError):profile.restore_job_environment(sidecar,'a'*64)
            self.assertEqual(contract.replay_integrity(rows)['status'],'consistent')

    def test_changed_context_before_worker_never_executes(self):
        from scripts import sermon_workflow_jobs as jobs
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);jobroot=root/'jobs';identity={'stage':'context-tamper'};key=jobs._digest(identity)
            with profile.session(root/'ledger','synthetic',work_kind='production',evidence_mode='synthetic'):
                with patch.object(jobs.subprocess,'Popen',side_effect=KeyboardInterrupt):
                    with self.assertRaises(KeyboardInterrupt):jobs.start_job(jobroot,identity,[sys.executable,'-c','pass'],5)
            path=jobroot/key/'accounting-context.json';value=jobs._read(path);value['environment'][profile.CONTEXT_ENV]='{}';jobs._persist(path,value)
            with jobs._lock(jobroot,key) as (folder,fd,held),patch.object(jobs,'bounded_process') as runner:
                self.assertTrue(held)
                with self.assertRaisesRegex(ValueError,'job_accounting_context_changed'):jobs._worker(jobroot,key,fd)
                runner.assert_not_called()


class AtomicTraceArtifactTests(unittest.TestCase):
    def test_failed_replace_preserves_old_report_and_bound_ledger_digest(self):
        import hashlib
        from scripts import sermon_trace_artifacts as artifacts
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)/'output';artifacts.new_directory(directory)
            path=directory/'report.json';artifacts.write(path,'old')
            with patch.object(artifacts.os,'replace',side_effect=OSError('fault')),self.assertRaises(OSError):artifacts.write(path,'new')
            self.assertEqual(path.read_text(),'old');self.assertEqual(list(directory.iterdir()),[path])
            self.assertEqual(path.stat().st_mode&0o777,0o600)
            with profile.session(Path(tmp)/'ledger','synthetic',work_kind='control',evidence_mode='synthetic'):
                with accounting.stage('step',depends_on=[]):pass
            ledger=Path(tmp)/'ledger';digest=hashlib.sha256((ledger/'events.jsonl').read_bytes()).hexdigest()
            self.assertEqual(weekly.project(ledger)['sourceLedgerSha256'],digest)
            self.assertEqual(accounting.summarize(ledger)['sourceLedgerSha256'],digest)
