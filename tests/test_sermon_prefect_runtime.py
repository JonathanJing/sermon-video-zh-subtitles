"""Opt-in real local Prefect engine checks, with synthetic business subprocesses."""
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts import sermon_dag_contract as contract
from scripts import sermon_prefect_dag as pilot


@unittest.skipUnless(os.environ.get('SERMON_TEST_PREFECT')=='1','optional local Prefect integration')
class PrefectRuntimeTests(unittest.TestCase):
    def test_three_locales_engine_processes_trace_replay_and_capacity(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'run'; plan_path=Path(temp)/'plan.json'
            plan=contract.make_plan(run_id='3'*64,input_identity_sha256='4'*64,delay_seconds=.4)
            plan_path.write_text(json.dumps(plan))
            argv=[sys.executable,str(pilot.REPO/'scripts/run_sermon_prefect_dag.py'),'mock',
                  '--root',str(root),'--plan',str(plan_path)]
            first=subprocess.run(argv,capture_output=True,text=True,timeout=120)
            self.assertEqual(first.returncode,0,first.stderr[-6000:])
            snapshot=pilot.read(root/'snapshot.json')
            self.assertEqual(len(snapshot['nodes']),10)
            self.assertTrue(all(r['executionStatus']=='completed' for r in snapshot['nodes'].values()))
            receipts={p.parent.name:pilot.read(p) for p in (root/'nodes').glob('*/receipt.json')}
            self.assertEqual(len(receipts),10)
            self.assertEqual(len({r['flowRunId'] for r in snapshot['nodes'].values()}),1)
            rows=[json.loads(line) for line in (root/'accounting/events.jsonl').read_text().splitlines()]
            stages={r['spanId']:r for r in rows if r['event']=='stage_finished' and r['stage'].startswith('pilot.mock.')}
            self.assertEqual(len(stages),10)
            self.assertFalse(any(r['event'].startswith('api_attempt') for r in rows))
            for key,receipt in receipts.items():
                row=stages[receipt['spanId']]
                self.assertEqual(row['jobId'],snapshot['nodes'][key]['jobId'])
                self.assertEqual(row['evidenceMode'],'synthetic')
                self.assertEqual(row['executorType'],'deterministic_program')
                self.assertIsNotNone(row['queuedAt']);self.assertIsNotNone(row['dependencyReadyAt'])
                self.assertEqual(set(row['dependsOn']),{receipts[d]['spanId'] for d in receipt['dependencies']})
                self.assertFalse(receipt['productionEligible'])
            for prefix,cap in [('text.',2),('audio.',1)]:
                events=[]
                for key,receipt in receipts.items():
                    if key.startswith(prefix):
                        events.extend([(datetime.fromisoformat(receipt['startedAt']),1),
                                       (datetime.fromisoformat(receipt['completedAt']),-1)])
                count=peak=0
                for _,delta in sorted(events):count+=delta;peak=max(peak,count)
                self.assertLessEqual(peak,cap)
                if prefix=='text.':self.assertEqual(peak,2,'independent branches did not overlap')
            original={p:p.read_bytes() for p in (root/'nodes').rglob('*.json')}
            budget_before=(root/'mock-budget'/pilot.budget.STORE_ID/'state.json').read_bytes()
            second=subprocess.run(argv,capture_output=True,text=True,timeout=120)
            self.assertEqual(second.returncode,0,second.stderr[-4000:])
            self.assertEqual(original,{p:p.read_bytes() for p in original})
            self.assertEqual(budget_before,(root/'mock-budget'/pilot.budget.STORE_ID/'state.json').read_bytes())
            after=[json.loads(line) for line in (root/'accounting/events.jsonl').read_text().splitlines()]
            self.assertEqual(sum(r['event']=='stage_started' and r['stage'].startswith('pilot.mock.') for r in after),10)

if __name__=='__main__':unittest.main()
