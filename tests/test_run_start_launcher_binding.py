"""Real read-only launcher parsing against approved v4 QC identity; no dispatch."""
import contextlib
import hashlib
import io
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import check_run_start as check


class LauncherBindingTests(unittest.TestCase):
    def setUp(self):
        from tests.test_run_start_tools import PlanTests, run_plan
        fixture=PlanTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.base=fixture.base
        self.assertEqual(run_plan(*fixture.args())[0],0)
        self.plan=self.base/'run'
        from tests.test_run_machine_qc_audio_test import OPENAI_ENV
        self.key=OPENAI_ENV['OPENAI_API_KEY']
        self.env=self.base/'launcher.env'
        self.write_environment()

    def write_environment(self, *, key=None, project='proj_fixture'):
        self.env.write_text(f'OPENAI_DEV_API_KEY={key or self.key}\nOPENAI_DEV_PROJECT_ID={project}\n')
        self.env.chmod(0o600)

    def test_actual_launcher_same_identity_passes_without_mutating_environment_or_ledgers(self):
        before=dict(os.environ);raw=self.env.read_bytes()
        with patch('urllib.request.urlopen',side_effect=AssertionError('network forbidden')):
            identity=check.selected_launcher_identity('dev',self.env)
            result=check.check_launcher_binding(self.plan,'dev',self.env)
        self.assertEqual(result['status'],'pass')
        self.assertEqual(identity['credentialSha256'],hashlib.sha256(self.key.encode()).hexdigest())
        self.assertEqual(identity['openaiRoute']['projectId'],'proj_fixture')
        self.assertEqual(identity['openaiRoute']['credentialAlias'],'tongxing-dev-runtime')
        self.assertEqual(dict(os.environ),before);self.assertEqual(self.env.read_bytes(),raw)
        self.assertEqual(list(self.plan.rglob('source-budget.json')),[])
        self.assertNotIn(self.key,json.dumps(result))

    def test_same_environment_different_project_or_key_refuses(self):
        for field in ('project','key'):
            with self.subTest(field=field):
                self.write_environment(project='proj_other' if field=='project' else 'proj_fixture',
                                       key='synthetic-different-credential' if field=='key' else None)
                result=check.check_launcher_binding(self.plan,'dev',self.env)
                self.assertEqual(result['status'],'fail')
                self.assertNotIn(self.key,json.dumps(result));self.assertNotIn('synthetic-different-credential',json.dumps(result))

    def test_different_alias_or_route_metadata_cannot_pass_as_same_environment(self):
        plan=json.loads((self.plan/'plan.json').read_text());path=Path(plan['stages'][0]['authorization'])
        original=json.loads(path.read_text())
        for field,value in [('credentialAlias','unapproved-alias'),('schemaVersion','wrong-route-version'),('identitySource','unapproved-source')]:
            with self.subTest(field=field):
                auth=json.loads(json.dumps(original));auth['qcContext']['openaiRoute'][field]=value
                path.write_text(json.dumps(auth))
                self.assertEqual(check.check_launcher_binding(self.plan,'dev',self.env)['status'],'fail')
        path.write_text(json.dumps(original))

    def test_actual_main_fails_when_launcher_check_passes_but_project_differs(self):
        self.write_environment(project='proj_other')
        output=io.StringIO()
        with patch.object(check,'check_code',return_value=check.result('code','pass')),contextlib.redirect_stdout(output),patch('urllib.request.urlopen',side_effect=AssertionError('network forbidden')):
            code=check.main(['--budget-plan',str(self.plan),'--openai-environment','dev','--env-file',str(self.env)])
        report=json.loads(output.getvalue());by_name={row['check']:row for row in report['checks']}
        self.assertEqual(by_name['openai']['status'],'pass')
        self.assertEqual(by_name['budget']['status'],'pass')
        self.assertEqual(by_name['environment_binding']['status'],'fail')
        self.assertEqual(code,1);self.assertNotIn(self.key,output.getvalue())

    def test_unreadable_or_unsafe_file_fails_closed_without_secret_output(self):
        self.env.chmod(0o644)
        self.assertEqual(check.check_launcher_binding(self.plan,'dev',self.env)['status'],'fail')
        self.env.unlink()
        self.assertEqual(check.check_launcher_binding(self.plan,'dev',self.env)['status'],'fail')

    def test_actual_main_same_launcher_and_approval_pass(self):
        output=io.StringIO()
        with patch.object(check,'check_code',return_value=check.result('code','pass')),contextlib.redirect_stdout(output),patch('urllib.request.urlopen',side_effect=AssertionError('network forbidden')):
            code=check.main(['--budget-plan',str(self.plan),'--openai-environment','dev','--env-file',str(self.env)])
        report=json.loads(output.getvalue())
        self.assertEqual(code,0);self.assertEqual(report['status'],'pass')
        self.assertNotIn(self.key,output.getvalue())

    def test_env_file_without_environment_cannot_silently_skip_launcher(self):
        output=io.StringIO()
        with patch.object(check,'check_code',return_value=check.result('code','pass')),contextlib.redirect_stdout(output):
            code=check.main(['--budget-plan',str(self.plan),'--env-file',str(self.env)])
        report=json.loads(output.getvalue());rows={row['check']:row for row in report['checks']}
        self.assertEqual(code,1);self.assertEqual(rows['budget']['status'],'pass')
        self.assertEqual(rows['environment_binding']['status'],'fail')
        self.assertNotIn(self.key,output.getvalue())

    def test_code_only_with_no_launcher_input_retains_skip_contract(self):
        output=io.StringIO()
        with patch.object(check,'check_code',return_value=check.result('code','pass')),contextlib.redirect_stdout(output):
            code=check.main([])
        report=json.loads(output.getvalue());rows={row['check']:row for row in report['checks']}
        self.assertEqual(code,0);self.assertEqual(rows['openai']['status'],'skip')
        self.assertEqual(rows['budget']['status'],'skip');self.assertNotIn('environment_binding',rows)
