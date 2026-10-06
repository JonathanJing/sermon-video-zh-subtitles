import contextlib
import copy
from datetime import datetime,timedelta,timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
import wave
from unittest.mock import patch
from scripts import sermon
from scripts.sermon_unified import contracts as c,runtime as r
from scripts.sermon_unified_observability import project,events,compare

class UnifiedCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.root=self.base/'store'
        self.media=self.base/'source.wav'
        with wave.open(str(self.media),'wb') as w:
            w.setparams((1,2,16000,0,'NONE','not compressed'));w.writeframes(b'\0\0'*1600)
        self.modules=['scripts/sermon_unified/contracts.py']
        self.addCleanup(patch.stopall)
        patch.object(c,'required_modules',return_value=self.modules).start()
        t=datetime.now(timezone.utc)
        self.m={'schemaVersion':'sermon-unified-run-manifest-v2','productionRunId':'test','runRevision':1,'jobRoot':'stable-test',
            'content':{'contentId':'test','pageId':'test','category':'podcast','sourceDate':None},
            'source':{'sourceId':'source','mediaSha256':c.file_sha(self.media),'durationSeconds':.1,
                      'window':{'startSeconds':0,'endSeconds':.1,'timeBase':'source_media','approvalReceiptSha256':None}},
            'locales':['zh-Hans'],'canaryScope':'media_verified','activeScope':'media_verified','finalScope':'dual_production_verified',
            'policies':[{'locale':'zh-Hans','policySha256':'a'*64,'promptSha256':'b'*64,'pluginSha256':'c'*64}],
            'budget':{'currency':'USD','limitMicroUsd':0},'transport':'provider',
            'executionAdmission':{'modules':self.modules,'closureSha256':c.closure(self.modules)},
            'bindings':{'media':{'path':str(self.media),'sha256':c.file_sha(self.media)}},
            'executionWindow':{'timezone':'America/Los_Angeles','startsAt':(t-timedelta(minutes=1)).isoformat(),'deadlineAt':(t+timedelta(minutes=20)).isoformat()},
            'steps':[{'id':'media','stageId':'media_verify','adapter':'media.verify','dependsOn':[],'scope':'media_verified'}]}
    def freeze(self):
        return r.submit(self.m,self.base,self.root,c.plan_hash(self.m))
    def test_real_media_adapter_and_result_contract(self):
        state=self.freeze();r.pump(self.root,state['runKey'])
        state=r.load(self.root,state['runKey']);result=sermon.state_result('job.status',state)
        c.validate(result,'sermon-cli-result-v2')
        self.assertEqual(result['outcome'],'succeeded');self.assertFalse(result['execution']['productionEligible'])
        self.assertEqual(result['execution']['remainingSteps'],0)
    def test_status_does_not_write_or_reconcile(self):
        state=self.freeze();before={p:(p.read_bytes(),p.stat().st_mtime_ns) for p in self.root.rglob('*') if p.is_file()}
        sermon.state_result('job.status',r.load(self.root,state['runKey']))
        self.assertEqual(before,{p:(p.read_bytes(),p.stat().st_mtime_ns) for p in self.root.rglob('*') if p.is_file()})
    def test_100_transitions_with_persistent_intents(self):
        self.m['steps']=[{'id':f'm{i}','stageId':'media_verify','adapter':'media.verify',
                         'dependsOn':[] if i==0 else [f'm{i-1}'],'scope':'media_verified'} for i in range(100)]
        state=self.freeze()
        calls=[]
        def fixed(m,base,step,out):
            calls.append(step['id']);return {'status':'succeeded','artifact':'verified','kind':'media_identity','mediaSha256':m['source']['mediaSha256']}
        r.pump(self.root,state['runKey'],executor=fixed)
        state=r.load(self.root,state['runKey']);report=project(state)
        self.assertEqual(len(calls),100);self.assertEqual(report['completedSteps'],100)
        self.assertEqual(report['handoff']['count'],99);self.assertLessEqual(report['handoff']['p95Seconds'],2)
        r.pump(self.root,state['runKey'],executor=lambda *a: self.fail('duplicate dispatch'))
        self.assertEqual(len(events(state)),200);self.assertEqual(events(state,after=state['events'][-1]['eventId']),[])
    def test_completed_response_cannot_be_replaced(self):
        state=self.freeze();r.pump(self.root,state['runKey']);state=r.load(self.root,state['runKey'])
        sid=c.digest(c.job_identity(self.m,self.m['steps'][0]));path=r.folder(self.root,state['runKey'])/('response-'+sid+'.json')
        response=c.read(path);response['result']['durationSeconds']=999;path.write_text(json.dumps(response))
        with self.assertRaises(c.ContractError):r.finish(self.root,state['runKey'],'media',path)
    def test_expired_window_never_calls_adapter(self):
        self.m['executionWindow']['startsAt']=(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()
        self.m['executionWindow']['deadlineAt']=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()
        state=self.freeze();r.pump(self.root,state['runKey'],executor=lambda *a:self.fail('expired dispatch'))
        self.assertEqual(r.load(self.root,state['runKey'])['steps']['media']['reason'],'execution_window_expired')
    def test_wait_timeout_leaves_state_unchanged(self):
        state=self.freeze();args=sermon.parser().parse_args(['job','wait','--run-id',state['runKey'],'--state-root',str(self.root),'--timeout','0'])
        result,code=sermon.run(args);self.assertEqual(code,3);self.assertFalse(r.load(self.root,state['runKey'])['cancelRequested'])
    def test_host_locator_does_not_change_plan_but_closure_does(self):
        h=c.plan_hash(self.m);other=copy.deepcopy(self.m);other['provenance']={'hostname':'other'}
        other['bindings']['media']['path']='/different/path';self.assertEqual(h,c.plan_hash(other))
        other['executionAdmission']['closureSha256']='d'*64;self.assertNotEqual(h,c.plan_hash(other))
    def test_changed_media_admission_is_zero_effect(self):
        self.media.write_bytes(b'bad');before=list(self.base.rglob('*'))
        self.assertIn('binding_changed',c.admit(self.m,self.base));self.assertEqual(before,list(self.base.rglob('*')))
    def test_comparison_rejects_quality_changes_and_preserves_missing(self):
        a={k:'same' for k in ('sourceSha256','policySha256','qualityReceiptSha256','scope','workload','cacheMode')}
        self.assertIsNone(compare(a,a)['deltas']['gpuSeconds'])
        with self.assertRaises(ValueError):compare(a,dict(a,qualityReceiptSha256='changed'))

if __name__=='__main__':unittest.main()

class RevisionTests(UnifiedCliTests):
    def test_revision_reuses_completed_identity_and_keeps_archive(self):
        state=self.freeze();r.pump(self.root,state['runKey'])
        state=r.load(self.root,state['runKey']);state=r.mutate(self.root,state['runKey'],'drain',state['stateRevision'])
        self.m['runRevision']=2
        self.m['executionWindow']['deadlineAt']=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()
        new=r.submit(self.m,self.base,self.root,c.plan_hash(self.m),state['stateRevision'])
        self.assertEqual(new['revisionReuse']['reused'],['media'])
        self.assertTrue(new['steps']['media']['cacheValidation'])
        self.assertEqual(new['events'][-1]['eventType'],'cache.reused')
        self.assertIn('originComputeSeconds',new['steps']['media'])
        self.assertTrue((r.folder(self.root,state['runKey'])/'revision-1.json').is_file())
        r.pump(self.root,state['runKey'],executor=lambda *a:self.fail('repeated effect'))
    def test_revision_unknown_cannot_be_cleared(self):
        state=self.freeze();state['admission']='closed';state['steps']['media']['process']='waiting_reconciliation'
        state=r.save(self.root,state['runKey'],state,state['stateRevision']);self.m['runRevision']=2
        with self.assertRaises(c.ContractError):r.submit(self.m,self.base,self.root,c.plan_hash(self.m),state['stateRevision'])
    def test_changed_step_invalidates_downstream(self):
        state=self.freeze();r.pump(self.root,state['runKey']);state=r.load(self.root,state['runKey'])
        state=r.mutate(self.root,state['runKey'],'drain',state['stateRevision'])
        self.m['runRevision']=2;self.m['steps'][0]['timeoutSeconds']=100
        new=r.submit(self.m,self.base,self.root,c.plan_hash(self.m),state['stateRevision'])
        self.assertEqual(new['revisionReuse']['reused'],[])
        self.assertEqual(new['steps']['media']['process'],'not_started')
