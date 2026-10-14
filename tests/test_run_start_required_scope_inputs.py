"""QC plans require a selected launcher; page checks require explicit target origin."""
import contextlib
import io
import json
import unittest
from unittest.mock import patch
from scripts import check_run_start as check


class RequiredPreflightScopeTests(unittest.TestCase):
    def run_check(self,args):
        output=io.StringIO()
        with patch.object(check,'check_code',return_value=check.result('code','pass')),contextlib.redirect_stdout(output):
            code=check.main(args)
        value=json.loads(output.getvalue());return code,{row['check']:row for row in value['checks']}

    def test_valid_qc_only_plan_without_launcher_environment_fails(self):
        from tests.test_run_start_tools import PlanTests,run_plan
        fixture=PlanTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.assertEqual(run_plan(*fixture.args())[0],0)
        with patch.object(check,'check_openai') as launcher,patch.object(check,'urlopen',side_effect=AssertionError('network forbidden')):
            code,rows=self.run_check(['--budget-plan',str(fixture.base/'run')])
        self.assertEqual(rows['budget']['status'],'pass');self.assertEqual(rows['openai']['status'],'skip')
        self.assertEqual(rows['environment_binding']['status'],'fail');self.assertEqual(code,1)
        launcher.assert_not_called()

    def test_qc_only_plan_with_actual_matching_launcher_passes(self):
        from tests.test_run_start_tools import PlanTests,run_plan
        from tests.test_run_machine_qc_audio_test import OPENAI_ENV
        fixture=PlanTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.assertEqual(run_plan(*fixture.args())[0],0)
        env=fixture.base/'launcher.env';env.write_text('OPENAI_DEV_API_KEY='+OPENAI_ENV['OPENAI_API_KEY']+'\nOPENAI_DEV_PROJECT_ID=proj_fixture\n');env.chmod(0o600)
        with patch.object(check,'urlopen',side_effect=AssertionError('network forbidden')):
            code,rows=self.run_check(['--budget-plan',str(fixture.base/'run'),'--openai-environment','dev','--env-file',str(env)])
        self.assertEqual(code,0);self.assertEqual(rows['environment_binding']['status'],'pass')

    def test_page_id_without_origin_fails_before_any_catalog_read_for_both_environments(self):
        for environment in ['dev','prod']:
            with self.subTest(environment=environment),patch.object(check,'check_openai',return_value=check.result('openai','pass')),patch.object(check,'urlopen') as http:
                code,rows=self.run_check(['--page-id','new-page','--openai-environment',environment])
                self.assertEqual(code,1);self.assertEqual(rows['page']['status'],'fail');self.assertIn('--origin',rows['page']['problems'][0]);http.assert_not_called()

    def test_explicit_production_origin_is_the_actual_catalog_target(self):
        urls=[]
        def read(request,timeout):
            urls.append(request.full_url)
            return contextlib.nullcontext(io.BytesIO(b'{"pages":[]}'))
        with patch.object(check,'check_openai',return_value=check.result('openai','pass')),patch.object(check,'urlopen',side_effect=read):
            code,rows=self.run_check(['--page-id','new-page','--openai-environment','prod','--origin','https://production.example.invalid'])
        self.assertEqual(code,0);self.assertEqual(rows['page']['origin'],'https://production.example.invalid')
        self.assertEqual(urls,['https://production.example.invalid/multilingual-v3.json','https://production.example.invalid/multilingual-v4.json'])

    def test_code_only_without_plan_launcher_or_page_preserves_skip(self):
        with patch.object(check,'urlopen') as http,patch.object(check,'check_openai') as launcher:
            code,rows=self.run_check([])
        self.assertEqual(code,0)
        for name in ['openai','budget','page']:self.assertEqual(rows[name]['status'],'skip')
        self.assertNotIn('environment_binding',rows);http.assert_not_called();launcher.assert_not_called()
