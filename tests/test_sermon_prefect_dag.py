"""Synthetic adapter checks; no provider, model, real approval or publication."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from contextlib import chdir
import json
import os
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import sermon_log_profile as profile
from scripts import sermon_dag_contract as contract
from scripts import sermon_prefect_dag as pilot
from scripts import sermon_review_budget as budget
from scripts import sermon_workflow_jobs as jobs
from scripts.sermon_execution_harness import work_lock, WorkAlreadyRunning


class PilotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/'pilot'

    def setup_plan(self,**kw):
        plan = contract.make_plan(run_id='1'*64,input_identity_sha256='2'*64,**kw)
        with work_lock(self.root):
            pilot.initialize(self.root,plan)
        self.enterContext(profile.session(self.root/'accounting','pilot_test',work_kind='control',evidence_mode='synthetic'))
        return plan,pilot.Runner(self.root,plan)

    def test_closed_plan_and_no_type_coercion(self):
        plan = contract.make_plan(run_id='1'*64,input_identity_sha256='2'*64)
        for field,value in [('productionEligible',True),('mode','production'),('mockRequestLimit',True)]:
            other = deepcopy(plan); other[field]=value
            with self.assertRaises(ValueError): contract.validate_plan(other)
        with self.assertRaises(ValueError):
            contract.make_plan(run_id='1'*64,input_identity_sha256='2'*64,scenarios={'source':[]})

    def test_existing_evidence_root_cannot_be_adopted(self):
        self.root.mkdir(); (self.root/'original-ledger.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'dedicated_root'): self.setup_plan()
        self.assertEqual((self.root/'original-ledger.json').read_text(),'{}')

    def test_owner_lock_and_runtime_identity_are_required(self):
        plan,runner = self.setup_plan()
        with work_lock(self.root),self.assertRaises(WorkAlreadyRunning):
            with work_lock(self.root): pass
        with patch.object(pilot,'code_identity',return_value='a'*64),self.assertRaisesRegex(ValueError,'code_changed'):
            pilot.load(self.root)

    def test_runtime_identity_covers_transitive_execution_and_validation_modules(self):
        required = {'sermon_job_liveness.py', 'sermon_log_contract.py', 'sermon_log_outbox.py',
                    'sermon_review_observation.py', 'sermon_clock_evidence.py',
                    'sermon_workflow_evidence.py', 'sermon_release_workflow.py',
                    'sermon_guarded_command.py'}
        self.assertTrue(required.issubset(set(pilot.CLOSURE)))

    def test_human_wait_does_not_launch_or_take_resource(self):
        plan,runner = self.setup_plan(simulated_human=False)
        with patch.object(jobs,'start_job') as start:
            result=runner.execute(plan['nodes'][0])
        start.assert_not_called()
        self.assertEqual(result['reason'],'real_human_review_pending')
        self.assertFalse((self.root/'mock-budget').exists())

    def test_same_locale_audio_always_required_including_text_only(self):
        plan,_ = self.setup_plan(text_only=('ko',))
        nodes={n['id']:n for n in plan['nodes']}
        self.assertEqual(set(nodes['page.ko']['dependsOn']),{'text.ko','audio.ko'})
        self.assertEqual(nodes['audio.ko']['resourcePool'],'fixed')

    def test_exit_zero_without_business_receipt_is_not_admission(self):
        plan,runner=self.setup_plan(locales=('ko',))
        with patch.object(jobs,'start_job',return_value={'status':'succeeded'}):
            value=runner.execute(plan['nodes'][0])
        self.assertEqual(value['executionStatus'],'blocked')

    def test_real_process_replay_is_exact_no_second_dispatch(self):
        plan,runner=self.setup_plan(locales=('ko',),text_only=('ko',))
        results={}
        for node in plan['nodes']:
            results[node['id']]=runner.execute(node,[results[x] for x in node['dependsOn']])
        self.assertTrue(all(v['executionStatus']=='completed' for v in results.values()),results)
        protected=[p for p in self.root.rglob('*.json') if 'snapshot' not in p.name]
        before={p:p.read_bytes() for p in protected}
        for node in plan['nodes']:
            replay=runner.execute(node,[results[x] for x in node['dependsOn']])
            self.assertEqual(replay['receiptSha256'],results[node['id']]['receiptSha256'])
        self.assertEqual(before,{p:p.read_bytes() for p in protected})
        ledger=pilot.read(self.root/'mock-budget'/budget.STORE_ID/'state.json')
        self.assertEqual(len(ledger['reservations']),1)
        self.assertTrue(all(v['realHumanStatus']!='approved' for v in results.values()))

    def test_parallel_budget_exhaustion_allows_only_one_synthetic_request(self):
        plan,runner=self.setup_plan(mock_request_limit=1,delay_seconds=.2)
        source=runner.execute(plan['nodes'][0])
        texts=[n for n in plan['nodes'] if n['layer']==2]
        with ThreadPoolExecutor(3) as pool:
            values=list(pool.map(lambda n:runner.execute(n,[source]),texts))
        self.assertEqual(sum(v['executionStatus']=='completed' for v in values),1,values)
        ledger=pilot.read(self.root/'mock-budget'/budget.STORE_ID/'state.json')
        self.assertEqual(len(ledger['reservations']),1)

    def test_unknown_preserves_reservation_and_blocks_descendants_and_replay(self):
        plan,runner=self.setup_plan(locales=('ko',),scenarios={'text.ko':'outcome_unknown'})
        source=runner.execute(plan['nodes'][0])
        text=runner.execute(plan['nodes'][1],[source])
        self.assertEqual(text['executionStatus'],'outcome_unknown',text)
        audio=runner.execute(plan['nodes'][2],[text])
        self.assertEqual(audio['reason'],'upstream_not_admitted')
        before=(self.root/'mock-budget'/budget.STORE_ID/'state.json').read_bytes()
        replay=runner.execute(plan['nodes'][1],[source])
        self.assertEqual(replay['executionStatus'],'outcome_unknown')
        self.assertEqual(before,(self.root/'mock-budget'/budget.STORE_ID/'state.json').read_bytes())

    def test_receipt_telemetry_must_match_actual_completed_trace(self):
        plan,runner=self.setup_plan(locales=('ko',))
        result=runner.execute(plan['nodes'][0])
        self.assertEqual(result['executionStatus'],'completed',result)
        path=self.root/'nodes/source/receipt.json'; original=pilot.read(path)
        for field,value in [('spanId','f'*32),('elapsedSeconds',-1),('elapsedSeconds',.001),
                            ('completedAt','not-a-date'),('completedAt','2020-01-01T00:00:00+00:00')]:
            changed={**original,field:value};jobs._persist(path,changed)
            with self.assertRaises(ValueError):pilot.valid_receipt(self.root,plan,plan['nodes'][0],{})
        jobs._persist(path,original)
        self.assertEqual(pilot.valid_receipt(self.root,plan,plan['nodes'][0],{}),original)

    def test_ambient_prefect_settings_and_imported_context_are_rejected(self):
        for key in ('PREFECT_SERVER_DATABASE_CONNECTION_URL','PREFECT_API_DATABASE_CONNECTION_URL',
                    'PREFECT_PROFILE','PREFECT_HOME','prefect_api_url'):
            with patch.dict(os.environ,{key:'synthetic-value'}),self.assertRaisesRegex(ValueError,'ambient'):
                pilot.isolated_prefect_environment(self.root)
        with patch.dict(sys.modules,{'prefect':object()}),self.assertRaisesRegex(ValueError,'fresh_prefect'):
            pilot.isolated_prefect_environment(self.root)

    def test_hostile_file_settings_rejected_before_prefect_import_or_side_effects(self):
        plan=contract.make_plan(run_id='1'*64,input_identity_sha256='2'*64)
        outside=Path(self.temp.name)/'outside-marker'
        samples={'.env':'PREFECT_API_URL=https://synthetic.invalid/api\n',
                 'prefect.toml':'[server]\nmemo_store_path="'+str(outside)+'"\n',
                 'pyproject.toml':'[tool.prefect.api]\nurl="https://synthetic.invalid/api"\n'}
        import builtins
        original=builtins.__import__
        def guarded(name,*args,**kwargs):
            if name=='prefect' or name.startswith('prefect.'):
                outside.write_text('unexpected SDK import side effect')
                raise AssertionError('Prefect must not be imported')
            return original(name,*args,**kwargs)
        for filename,contents in samples.items():
            cwd=Path(self.temp.name)/('cwd-'+filename.replace('.','_'));cwd.mkdir()
            (cwd/filename).write_text(contents)
            with chdir(cwd),patch('builtins.__import__',side_effect=guarded), \
                 patch.object(pilot.socket.socket,'connect') as connect, \
                 self.assertRaisesRegex(ValueError,'file_prefect_settings'):
                pilot.run(self.root,plan)
            connect.assert_not_called();self.assertFalse(outside.exists())
        # A broken symlink must be rejected without following/reading it.
        cwd=Path(self.temp.name)/'links';cwd.mkdir();(cwd/'.env').symlink_to(outside)
        with chdir(cwd),self.assertRaisesRegex(ValueError,'file_prefect_settings'):
            pilot.isolated_prefect_environment(self.root)

    def test_late_caller_config_cannot_enter_import_cwd(self):
        plan=contract.make_plan(run_id='1'*64,input_identity_sha256='2'*64)
        caller=Path(self.temp.name)/'caller';caller.mkdir()
        import builtins
        original=builtins.__import__;seen=[]
        class StopBeforeSDK(Exception):pass
        def guarded(name,*args,**kwargs):
            if name=='prefect':
                (caller/'.env').write_text('PREFECT_API_URL=https://synthetic.invalid/api\n')
                self.assertNotEqual(Path.cwd(),caller)
                self.assertTrue(Path.cwd().is_relative_to(self.root.resolve()))
                self.assertFalse((Path.cwd()/'.env').exists())
                self.assertEqual(os.environ['DO_NOT_TRACK'],'1')
                seen.append(True)
                raise StopBeforeSDK()
            return original(name,*args,**kwargs)
        with chdir(caller),patch.dict(os.environ,dict(os.environ)), \
             patch('builtins.__import__',side_effect=guarded),self.assertRaises(StopBeforeSDK):
            pilot.run(self.root,plan)
        self.assertEqual(seen,[True])

    def test_existing_profile_is_rejected_and_sdk_tracking_disabled_before_import(self):
        home=self.root/'prefect';home.mkdir(parents=True)
        profile=home/'profiles.toml';profile.write_text('[profiles.hostile]\nPREFECT_API_URL="https://synthetic.invalid"\n')
        with self.assertRaisesRegex(ValueError,'file_prefect_settings'):
            pilot.isolated_prefect_environment(self.root)
        profile.unlink()
        # Only this isolated test environment is changed, never a user profile.
        with patch.dict(os.environ,{},clear=True):
            actual,database=pilot.isolated_prefect_environment(self.root)
            self.assertEqual(os.environ['DO_NOT_TRACK'],'1')
            self.assertEqual(os.environ['PREFECT_SERVER_MEMO_STORE_PATH'],str(home/'memo_store.toml'))
            self.assertEqual(actual,home)

    def test_active_lifetime_latches_dispatch_before_releasing_slot(self):
        plan,runner=self.setup_plan(resource_limits={'fixed':4,'api':1,'local_model':1})
        source=runner.execute(plan['nodes'][0])
        texts=[n for n in plan['nodes'] if n['layer']==2]
        with patch.object(jobs,'start_job',return_value={'status':'running'}) as start, \
             patch.object(pilot.time,'monotonic',side_effect=[0,100]):
            first=runner.execute(texts[0],[source])
            second=runner.execute(texts[1],[source])
        self.assertEqual(first['executionStatus'],'outcome_unknown')
        self.assertEqual(second['reason'],'prior_worker_lifetime_unresolved')
        self.assertEqual(start.call_count,1)

    def test_polling_error_or_lost_start_ack_latches_before_next_dispatch(self):
        plan,runner=self.setup_plan(resource_limits={'fixed':4,'api':1,'local_model':1})
        source=runner.execute(plan['nodes'][0])
        texts=[n for n in plan['nodes'] if n['layer']==2]
        with patch.object(jobs,'start_job',return_value={'status':'running'}) as start, \
             patch.object(jobs,'inspect_job',side_effect=OSError('synthetic')):
            first=runner.execute(texts[0],[source]);second=runner.execute(texts[1],[source])
            self.assertEqual(start.call_count,1)
            self.assertEqual(second['reason'],'prior_worker_lifetime_unresolved')
        runner=pilot.Runner(self.root,plan)
        with patch.object(jobs,'start_job',side_effect=OSError('lost_ack')) as start:
            first=runner.execute(texts[0],[source]);second=runner.execute(texts[1],[source])
            self.assertEqual(start.call_count,1)
            self.assertEqual(second['reason'],'prior_worker_lifetime_unresolved')

    def test_restarted_owner_blocks_prior_active_or_uncertain_jobs(self):
        plan,runner=self.setup_plan()
        folder=self.root/'jobs'/('a'*64);folder.mkdir(parents=True)
        for status in ('queued','running','uncertain'):
            with patch.object(jobs,'peek_job',return_value={'status':status}), \
                 patch.object(jobs,'start_job') as start:
                restarted=pilot.Runner(self.root,plan)
                value=restarted.execute(plan['nodes'][0])
                self.assertEqual(value['reason'],'prior_worker_lifetime_unresolved')
                start.assert_not_called()

    def test_corrupt_dependency_is_rejected_before_job_launch(self):
        plan,runner=self.setup_plan(locales=('ko',))
        source=runner.execute(plan['nodes'][0])
        output=self.root/'nodes/source/output.json'
        value=json.loads(output.read_text());value['syntheticOutput']=False
        jobs._persist(output,value)
        with patch.object(jobs,'start_job') as start:
            result=runner.execute(plan['nodes'][1],[source])
        start.assert_not_called()
        self.assertEqual(result['executionStatus'],'blocked')

if __name__=='__main__': unittest.main()
