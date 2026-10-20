"""Resume start checks recompute live reservations; completed replay keeps its old authority."""
import json
import unittest
from pathlib import Path
from scripts import check_run_start as check, plan_run_budgets as planner
from tongxing_production.review import qc_text_run as driver
from tests import test_run_start_tools as fixtures

SCHEMA={'type':'object','properties':{'status':{'type':'string'}},'required':['status'],'additionalProperties':False}


class ResumeRemainingPreflightTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.PlanTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.calls=[]

    def prepare(self,requests):
        profile=json.loads(planner.PROFILE.read_text());profile['qc']['requests']['clip']=requests-1;profile['qc']['secondaryAsr']['requests']['clip']=1
        path=self.f.base/'profile.json';path.write_text(json.dumps(profile))
        self.assertEqual(fixtures.run_plan(*self.f.args(extra=['--profile',str(path)]))[0],0)
        self.stage=self.f.load()['stages'][0];self.auth=Path(self.stage['authorization']);self.root=Path(self.stage['budgetRoot'])
        self.paths={'source':str(self.f.base/'source.json'),'anchor':str(self.f.base/'anchor.json'),'policy':str(self.f.base/'ko.json')}
        self.judge=self.new_judge();self.judge('judge','Review','first',SCHEMA)
        self.assertEqual(fixtures.run_plan(*self.f.args('resume',extra=['--resume-qc-authorization',str(self.auth)]))[0],0)
        return self.f.base/'resume'

    def new_judge(self):
        judge=driver.api_judge_for_resolved(self.auth,{'ko':self.paths},requested_locales=['ko'])
        def transport(*args):
            self.calls.append(1)
            return {'model':'gpt-6.1-sol','choices':[{'finish_reason':'stop','message':{'content':'{"status":"pass"}'}}],
                    'usage':{'prompt_tokens':10,'completion_tokens':10,'total_tokens':20}}
        judge.ledger.transport=transport;return judge

    def snapshot(self):
        return {str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in self.f.base.rglob('*') if p.is_file()}

    def test_more_returned_calls_can_exhaust_a_previously_positive_resume_plan(self):
        plan=self.prepare(2)
        self.assertEqual(check.check_budget(plan)['status'],'pass')
        self.judge('judge','Review','second',SCHEMA);self.assertEqual(self.calls,[1,1])
        before=self.snapshot();result=check.check_budget(plan)
        self.assertEqual(result['status'],'fail');self.assertIn('exhausted',result['problems'][0])
        self.assertEqual(self.snapshot(),before)
        # Finished work replays directly under its original authority, with no new plan/call.
        replay=self.new_judge();self.assertEqual(replay('judge','Review','first',SCHEMA),{'status':'pass'})
        self.assertEqual(replay('judge','Review','second',SCHEMA),{'status':'pass'});self.assertEqual(self.calls,[1,1])

    def test_lower_but_positive_remaining_does_not_need_snapshot_equality(self):
        plan=self.prepare(4)
        frozen=self.f.load('resume')['stages'][0]['remainingReservationBounds']
        self.judge('judge','Review','second',SCHEMA)
        before=self.snapshot();result=check.check_budget(plan)
        self.assertEqual(result['status'],'pass')
        current=result['observedResumeRemainingReservationBounds']['qc.ko']
        self.assertEqual((frozen['requests'],current['requests']),(3,2))
        self.assertTrue(all(value>0 for value in current.values()));self.assertEqual(self.snapshot(),before)

    def test_removed_original_root_is_not_treated_as_fresh_authority(self):
        import shutil
        plan=self.prepare(2);shutil.rmtree(self.root)
        before=self.snapshot();result=check.check_budget(plan)
        self.assertEqual(result['status'],'fail');self.assertIn('missing',result['problems'][0])
        self.assertEqual(self.snapshot(),before);self.assertFalse(self.root.exists())

    def exhaust_nonrequest_dimension(self,metric):
        from scripts import tongxing_host  # noqa: F401  binds the production package ports
        from tongxing_production.orchestration import jobs
        import os
        plan=self.prepare(4)
        frozen=self.f.load('resume')['stages'][0]['remainingReservationBounds']
        identity={'model':'gpt-6.1-sol','fixture':'fill-'+metric}
        bounds={'requests':1,'wallTimeMs':1,'costMicrousd':1};bounds[metric]=frozen[metric]
        self.judge.ledger.call(operation='judge.'+jobs._digest(identity),identity=identity,bounds=bounds,
                              request=b'{}',api_key=os.environ['OPENAI_API_KEY'],content_type='application/json',
                              endpoint='https://api.openai.com/v1/chat/completions')
        before=self.snapshot();result=check.check_budget(plan)
        self.assertEqual(result['status'],'fail');self.assertIn('exhausted',result['problems'][0])
        self.assertEqual(self.snapshot(),before)
        ledger=json.loads((self.root/'source-budget.json').read_text())
        self.assertEqual(ledger['authority']['globalBounds']['requests']-len(ledger['requests']),2)

    def test_wall_time_exhaustion_refuses_even_with_requests_remaining(self):
        self.exhaust_nonrequest_dimension('wallTimeMs')

    def test_reserved_cost_exhaustion_refuses_even_with_requests_remaining(self):
        self.exhaust_nonrequest_dimension('costMicrousd')
