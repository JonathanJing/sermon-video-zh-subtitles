"""Resume partial QC under its original approval, never pay a cross-root miss."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from scripts import plan_run_budgets as planner, check_run_start as check
from scripts import run_machine_qc_clip_test as driver
from tests import test_run_start_tools as fixtures

SCHEMA={'type':'object','properties':{'status':{'type':'string'}},'required':['status'],'additionalProperties':False}


class QcResumePlanTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.PlanTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        profile=json.loads(planner.PROFILE.read_text());profile['qc']['requests']['clip']=1
        profile['qc']['secondaryAsr']['requests']['clip']=1
        self.profile=self.f.base/'profile.json';self.profile.write_text(json.dumps(profile))
        self.assertEqual(fixtures.run_plan(*self.f.args(extra=['--profile',str(self.profile)]))[0],0)
        self.stage=self.f.load()['stages'][0];self.auth=Path(self.stage['authorization'])
        self.paths={'source':str(self.f.base/'source.json'),'anchor':str(self.f.base/'anchor.json'),'policy':str(self.f.base/'ko.json')}
        self.calls=[];self.judge=self.new_judge()
        self.first=('judge','Review','first',SCHEMA);self.next=('judge','Review','unfinished',SCHEMA)
        self.assertEqual(self.judge(*self.first),{'status':'pass'})

    def new_judge(self):
        judge=driver.api_judge_for_resolved(self.auth,{'ko':self.paths},requested_locales=['ko'])
        def transport(*args):
            self.calls.append(1)
            return {'model':'gpt-6.1-sol','choices':[{'finish_reason':'stop','message':{'content':'{"status":"pass"}'}}],
                    'usage':{'prompt_tokens':10,'completion_tokens':10,'total_tokens':20}}
        judge.ledger.transport=transport
        return judge

    def resume(self,name='resumed',extra=()):
        return fixtures.run_plan(*self.f.args(name,extra=['--resume-qc-authorization',str(self.auth),*extra]))

    def business_files(self):
        root=Path(self.stage['budgetRoot'])
        return {str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}

    def test_half_complete_resume_references_old_authority_and_only_unfinished_call_pays_once(self):
        before=self.business_files();auth_bytes=self.auth.read_bytes()
        self.assertEqual(self.resume()[0],0)
        stage=self.f.load('resumed')['stages'][0]
        self.assertEqual(stage['executionMode'],'resume_prior_authority')
        self.assertEqual(Path(stage['authorization']).resolve(),Path(self.stage['authorization']).resolve())
        for key in ('authorizationSha256','approvalSha256','budgetRoot','capUsd'):
            self.assertEqual(stage[key],self.stage[key])
        self.assertEqual(stage['remainingReservationBounds']['requests'],1)
        self.assertEqual(self.business_files(),before);self.assertEqual(self.auth.read_bytes(),auth_bytes)
        self.assertFalse((self.f.base/'resumed/qc-ko').exists())
        self.assertEqual(check.check_budget(self.f.base/'resumed')['status'],'pass')
        resumed=self.new_judge()
        self.assertEqual(resumed(*self.first),{'status':'pass'});self.assertEqual(self.calls,[1])
        self.assertEqual(resumed(*self.next),{'status':'pass'});self.assertEqual(self.calls,[1,1])
        resumed(*self.next);self.assertEqual(self.calls,[1,1])
        with self.assertRaisesRegex(ValueError,'source_budget_exhausted'):
            resumed('judge','Review','third',SCHEMA)
        self.assertEqual(self.calls,[1,1])
        with self.assertRaisesRegex(ValueError,'exhausted'):
            self.resume('exhausted')
        self.assertFalse((self.f.base/'exhausted').exists())

    def test_unknown_old_operation_and_mismatched_actual_launcher_refuse_without_writes(self):
        before=self.business_files()
        for change in ({'OPENAI_PROJECT_ID':'proj_other'},{'OPENAI_API_KEY':'different-synthetic-key'}):
            with patch.dict(os.environ,change),self.assertRaisesRegex(ValueError,'identity changed'):
                self.resume('wrong')
            self.assertFalse((self.f.base/'wrong').exists());self.assertEqual(self.business_files(),before)
        self.judge.ledger.transport=lambda *args: (_ for _ in ()).throw(TimeoutError('offline unknown'))
        with self.assertRaises(TimeoutError):self.judge(*self.next)
        before=self.business_files()
        with self.assertRaisesRegex(ValueError,'outcome unknown'):
            self.resume('unknown')
        self.assertFalse((self.f.base/'unknown').exists());self.assertEqual(self.business_files(),before)
        self.assertEqual(self.calls,[1])

    def test_context_changed_or_modes_mixed_refuse_before_plan_or_authority(self):
        before=self.business_files()
        with self.assertRaises(SystemExit):
            self.resume('mixed',extra=['--reuse-from',str(self.f.base/'run')])
        self.assertFalse((self.f.base/'mixed').exists())
        policy=self.f.base/'ko.json';value=json.loads(policy.read_text());value['targetLocale']='es';policy.write_text(json.dumps(value))
        with self.assertRaises(ValueError):self.resume('changed-context')
        self.assertFalse((self.f.base/'changed-context').exists());self.assertEqual(self.business_files(),before)

    def test_replay_only_new_root_still_refuses_unfinished_operation(self):
        self.assertEqual(fixtures.run_plan(*self.f.args('replay',extra=['--reuse-from',str(self.f.base/'run')]))[0],0)
        replay_stage=self.f.load('replay')['stages'][0]
        replay=driver.api_judge_for_resolved(Path(replay_stage['authorization']),{'ko':self.paths},requested_locales=['ko'])
        replay.ledger.transport=lambda *args:self.fail('cross-root miss may not pay')
        self.assertEqual(replay(*self.first),{'status':'pass'})
        with self.assertRaisesRegex(ValueError,'source_reuse_operation_missing'):replay(*self.next)
        self.assertEqual(self.calls,[1])
        with self.assertRaisesRegex(ValueError,'Replay-only'):
            planner.resume_qc_stage(
                Path(replay_stage['authorization']),replay_stage['qcContext'])

    def test_current_implementation_changed_refuses_original_authority_without_writes(self):
        before=self.business_files()
        with patch('scripts.machine_quality_waiver.implementation_sha256',return_value='f'*64):
            with self.assertRaisesRegex(ValueError,'context_changed'):
                self.resume('stale-implementation')
        self.assertFalse((self.f.base/'stale-implementation').exists());self.assertEqual(self.business_files(),before)
