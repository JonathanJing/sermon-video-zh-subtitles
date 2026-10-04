import threading
import time
from unittest.mock import patch
from tests.test_sermon_unified_cli import UnifiedCliTests
from scripts.sermon_unified import runtime as r,contracts as c
from scripts import sermon_workflow_jobs as jobs


class OwnerWaitTests(UnifiedCliTests):
    def test_detached_owner_survives_review_wait_and_observes_revision(self):
        state=self.freeze();key=state['runKey'];state['steps']['media']['process']='blocked'
        state=r.save(self.root,key,state,state['stateRevision']);calls=[];errors=[]
        def once(root,key):
            calls.append(1);return r.load(root,key)
        def worker():
            try:r.run_owner(self.root,key)
            except BaseException as exc:errors.append(exc)
        with patch.object(r,'pump',side_effect=once):
            thread=threading.Thread(target=worker);thread.start();time.sleep(.25)
            self.assertTrue(thread.is_alive())
            state=r.load(self.root,key);state['steps']['media'].update(process='succeeded',artifact='verified')
            r.save(self.root,key,state,state['stateRevision']);thread.join(3)
        self.assertFalse(thread.is_alive());self.assertFalse(errors);self.assertEqual(len(calls),2)
    def test_inflight_finish_merges_concurrent_cancel_without_losing_response(self):
        state=self.freeze();key=state['runKey'];step=self.m['steps'][0]
        state['steps']['media'].update(process='running',intentSha256=c.digest(c.job_identity(self.m,step)))
        state=r.save(self.root,key,state,state['stateRevision'])
        path=r.folder(self.root,key)/'response.json'
        jobs._persist(path,{'identity':c.job_identity(self.m,step),'result':{'status':'succeeded',
            'kind':'media_identity','artifact':'verified','mediaSha256':self.m['source']['mediaSha256']}})
        original=r.save;called=[]
        def racing(root,key,value,expected=None):
            if not called:
                called.append(1);current=r.load(root,key)
                current['cancelRequested']=True;current['admission']='closed'
                original(root,key,current,current['stateRevision'])
            return original(root,key,value,expected)
        with patch.object(r,'save',side_effect=racing):
            result=r.finish(self.root,key,'media',path)
        self.assertTrue(result['cancelRequested']);self.assertEqual(result['steps']['media']['process'],'succeeded')
