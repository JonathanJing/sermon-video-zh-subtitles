"""Exercise the real durable owner with bounded offline workers."""
import json
import threading
import time
from unittest.mock import patch
from tests.test_sermon_unified_cli import UnifiedCliTests
from scripts.sermon_unified import contracts as c, runtime as r
from scripts.production_concurrency_profile import profile_v1


class ParallelOwnerTests(UnifiedCliTests):
    def setUp(self):
        super().setUp()
        policy={'schemaVersion':'sermon-unified-resource-policy-v1','brokerRoot':str(self.base/'broker'),
                'capacities':{'cpu':4,'online_api':4,'codex_cli':24,'spark_tts':1,'publisher':1}}
        for key,value in [('resourcePolicy',policy),('concurrencyProfile',profile_v1())]:
            path=self.base/(key+'.json');path.write_text(json.dumps(value))
            self.m['bindings'][key]={'path':str(path),'sha256':c.file_sha(path)}

    def tasks(self, count=8):
        self.m['steps']=[{'id':f'm{i}','stageId':'media_verify','adapter':'media.verify',
                         'dependsOn':[],'scope':'media_verified'} for i in range(count)]

    def success(self,m):
        return {'status':'succeeded','artifact':'verified','kind':'media_identity','mediaSha256':m['source']['mediaSha256']}

    def test_four_actual_branches_resume_without_redispatch(self):
        self.tasks();state=self.freeze();counts={'live':0,'peak':0,'calls':0};lock=threading.Lock()
        barrier=threading.Barrier(4)
        def work(m,base,step,out):
            with lock:
                counts['live']+=1;counts['calls']+=1;counts['peak']=max(counts['peak'],counts['live'])
            barrier.wait(timeout=10)
            time.sleep(.03)
            with lock:counts['live']-=1
            return self.success(m)
        r.pump(self.root,state['runKey'],executor=work)
        end=r.load(self.root,state['runKey'])
        self.assertEqual((counts['peak'],counts['calls']),(4,8))
        self.assertTrue(all(row['process']=='succeeded' for row in end['steps'].values()))
        r.pump(self.root,state['runKey'],executor=lambda *a:self.fail('duplicate effect'))
        self.assertEqual(r._project(end)[0],'succeeded')

    def test_dependencies_wait_for_verified_completion(self):
        self.tasks(4);self.m['steps'][2]['dependsOn']=['m0'];self.m['steps'][3]['dependsOn']=['m1']
        state=self.freeze();seen=[];lock=threading.Lock()
        def work(m,base,step,out):
            snapshot=r.load(self.root,state['runKey'])
            self.assertTrue(all(snapshot['steps'][dep]['process']=='succeeded' for dep in step['dependsOn']))
            with lock:seen.append(step['id'])
            return self.success(m)
        r.pump(self.root,state['runKey'],executor=work)
        self.assertEqual(set(seen),{'m0','m1','m2','m3'})

    def test_unknown_drains_siblings_stops_new_admission_and_never_replays(self):
        self.tasks();state=self.freeze();barrier=threading.Barrier(4);seen=[]
        def work(m,base,step,out):
            seen.append(step['id']);barrier.wait(timeout=10)
            if step['id']=='m0':raise TimeoutError('unknown provider outcome')
            time.sleep(.1);return self.success(m)
        r.pump(self.root,state['runKey'],executor=work)
        end=r.load(self.root,state['runKey'])
        self.assertEqual(len(seen),4)
        self.assertEqual(end['steps']['m0']['process'],'waiting_reconciliation')
        self.assertTrue(all(end['steps'][s]['process']=='succeeded' for s in ['m1','m2','m3']))
        r.pump(self.root,state['runKey'],executor=lambda *a:self.fail('unknown replay'))
        policy=r.resource_policy(end['manifest'])
        from scripts.sermon_unified import resources
        ledger=resources._load(resources._safe_path(policy['brokerRoot'])/resources.BROKER_LOCK_ID,policy)
        self.assertEqual(sum(row['status']=='held' for row in ledger['reservations'].values()),1)

    def test_single_pump_owner(self):
        self.tasks(1);state=self.freeze()
        def work(m,base,step,out):
            with self.assertRaisesRegex(c.ContractError,'owner_busy'):
                r.pump(self.root,state['runKey'],executor=lambda *a:self.fail('second owner'))
            return self.success(m)
        r.pump(self.root,state['runKey'],executor=work)
