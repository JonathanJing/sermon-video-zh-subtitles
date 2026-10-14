"""V3 route/actual-credential approval and cache admission; offline only."""
import copy
import contextlib
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from scripts import canonical_layer2_budget as b, canonical_layer2_controller as controller
from scripts import run_target_language_models as models, plan_run_budgets as planner, check_run_start as check
from tests import test_canonical_layer2_budget as fixtures
from tests.test_run_machine_qc_audio_test import OPENAI_ENV


class Layer2RuntimeAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.env = {**OPENAI_ENV, 'OPENAI_PROJECT_ID': 'proj_fixture'}
        environment = patch.dict(os.environ, self.env); environment.start(); self.addCleanup(environment.stop)
        self.base = fixtures.CanonicalLayer2BudgetTests(); self.base.setUp(); self.addCleanup(self.base.doCleanups)
        self.root = self.base.fixture.root
        self.runtime = b.selected_runtime_identity()
        self.path = self.root / 'runtime-budget.json'
        self.receipt = self.root / 'runtime-approval.json'
        self.write_v3()

    def write_v3(self, scope='run'):
        value = json.loads(self.base.auth_path.read_text())
        receipt = json.loads(self.base.receipt.read_text())
        receipt['schemaVersion'] = b.RUNTIME_APPROVAL_SCHEMA
        receipt['binding'].update(ledgerScope=scope, runtimeIdentity=self.runtime)
        self.receipt.write_text(json.dumps(receipt))
        value.update(schemaVersion=b.RUNTIME_SCHEMA, ledgerScope=scope, runtimeIdentity=self.runtime,
                     approvalReceipt=self.receipt.name)
        value['authority']['approvalSha256'] = b.sha(self.receipt)
        self.path.write_text(json.dumps(value))
        return b.load_authorization(self.base.config, self.path, self.base.code)

    def caller(self, transport):
        return b.BudgetedCaller(b.load_authorization(self.base.config, self.path, self.base.code),
            self.base.config, self.base.source, self.base.anchor, self.base.policy, transport=transport)

    def test_v3_both_scopes_and_controller_start_bind_actual_runtime(self):
        for scope in ('run', 'locale'):
            with self.subTest(scope=scope):
                auth = self.write_v3(scope)
                self.assertEqual(auth['scope'], scope)
                self.assertEqual(auth['runtimeIdentity'], self.runtime)
                controller.Controller(self.base.config.path, budget_authorization=self.path)
                for change in ({'OPENAI_PROJECT_ID':'proj_other'}, {'OPENAI_API_KEY':'different-synthetic-key'}):
                    with patch.dict(os.environ, change), self.assertRaisesRegex(ValueError, 'runtime_identity_changed'):
                        controller.Controller(self.base.config.path, budget_authorization=self.path)
        self.assertFalse(self.base.auth['root'].exists())

    def test_every_dispatch_refuses_changed_key_project_or_override_before_reservation(self):
        calls=[]; caller=self.caller(lambda *args: calls.append(1))
        for change in ({'OPENAI_PROJECT_ID':'proj_other'}, {'OPENAI_API_KEY':'different-synthetic-key'}):
            with patch.dict(os.environ, change), self.assertRaisesRegex(ValueError, 'runtime_identity_changed'):
                caller(os.environ['OPENAI_API_KEY'], self.base.payload)
        with self.assertRaisesRegex(ValueError, 'credential_changed'):
            caller('unapproved-key', self.base.payload)
        self.assertEqual(calls, []); self.assertFalse(caller.root.exists())

    def test_same_identity_cache_replays_but_changed_key_or_project_never_consumes_it(self):
        calls=[]
        def transport(key, payload):
            calls.append(1)
            return {'id':'offline-response', 'model':payload['model'], 'choices':[{'finish_reason':'stop',
                'message':{'content':'{"fixture":true}'}}], 'usage':{'prompt_tokens':20,'completion_tokens':10}}
        caller=self.caller(transport); output=self.root/'cache'/'translation.json'
        prompt={'instruction':'Translate.', 'input':{'english':'A full sentence.'}}
        from scripts.production_spark_admission import SessionBoundCaller
        wrapped = SessionBoundCaller(caller, requires_spark=False, outcome_guarded=True)
        args=('translator', prompt, self.base.policy, output, self.env['OPENAI_API_KEY'], wrapped)
        first=models._model_call(*args, request_limits=self.base.limits)
        self.assertEqual(models._model_call(*args, request_limits=self.base.limits), first)
        before=output.read_bytes()
        for change in ({'OPENAI_PROJECT_ID':'proj_other'}, {'OPENAI_API_KEY':'different-synthetic-key'}):
            with patch.dict(os.environ, change), self.assertRaisesRegex(ValueError, 'runtime_identity_changed|credential_changed'):
                models._model_call('translator',prompt,self.base.policy,output,os.environ['OPENAI_API_KEY'],wrapped,
                                   request_limits=self.base.limits)
        self.assertEqual(calls,[1]); self.assertEqual(output.read_bytes(),before)
        self.assertEqual(caller.execution_identity['runtimeIdentity'],self.runtime)
        # Even a separately approved new route cannot adopt the old parsed/raw
        # cache merely because payload and dev alias are unchanged.
        with patch.dict(os.environ, {'OPENAI_PROJECT_ID':'proj_other'}):
            self.runtime = b.selected_runtime_identity(); self.write_v3()
            next_caller = self.caller(transport)
            self.assertNotEqual(next_caller.execution_identity, caller.execution_identity)
            with self.assertRaises(ValueError):
                models._model_call('translator',prompt,self.base.policy,output,self.env['OPENAI_API_KEY'],next_caller,
                                   request_limits=self.base.limits)
        self.assertEqual(calls,[1])

    def test_new_budget_authorization_reuses_same_runtime_cache(self):
        calls=[]
        def transport(key, payload):
            calls.append(1)
            return {'id':'offline-response', 'model':payload['model'], 'choices':[{'finish_reason':'stop',
                'message':{'content':'{"fixture":true}'}}], 'usage':{'prompt_tokens':20,'completion_tokens':10}}
        caller=self.caller(transport)
        from scripts.production_spark_admission import SessionBoundCaller
        output=self.root/'repair-cache'/'translation.json'
        prompt={'instruction':'Translate.', 'input':{'english':'A full sentence.'}}
        first=models._model_call('translator',prompt,self.base.policy,output,self.env['OPENAI_API_KEY'],
                                 SessionBoundCaller(caller, requires_spark=False, outcome_guarded=True),
                                 request_limits=self.base.limits)
        first_auth=b.sha(self.path)
        self.write_v3('locale')
        self.assertNotEqual(first_auth,b.sha(self.path))
        next_caller=self.caller(transport)
        self.assertEqual(caller.execution_identity,next_caller.execution_identity)
        self.assertEqual(models._model_call('translator',prompt,self.base.policy,output,self.env['OPENAI_API_KEY'],
                                           SessionBoundCaller(next_caller, requires_spark=False, outcome_guarded=True),
                                           request_limits=self.base.limits),first)
        self.assertEqual(calls,[1])


    def test_new_approval_is_exact_and_legacy_cannot_be_silently_extended(self):
        original=json.loads(self.path.read_text())
        for mutation in ('missing','null-route','extra','old-approval','old-v2'):
            with self.subTest(mutation=mutation):
                value=copy.deepcopy(original);receipt=json.loads(self.receipt.read_text())
                if mutation=='missing':value.pop('runtimeIdentity')
                elif mutation=='null-route':value['runtimeIdentity']['openaiRoute']=None
                elif mutation=='extra':value['unapproved']='field'
                elif mutation=='old-approval':
                    receipt['schemaVersion']='sermon-canonical-layer2-budget-approval-v1'
                    self.receipt.write_text(json.dumps(receipt));value['authority']['approvalSha256']=b.sha(self.receipt)
                else:value['schemaVersion']=b.LOCALE_SCHEMA
                self.path.write_text(json.dumps(value))
                with self.assertRaises(ValueError): b.load_authorization(self.base.config,self.path,self.base.code)
                self.write_v3()
        # Frozen original v1 still loads, with no synthesized runtime binding.
        self.assertNotIn('runtimeIdentity',b.load_authorization(self.base.config,self.base.auth_path,self.base.code))
        value=json.loads(self.base.auth_path.read_text());value['runtimeIdentity']=self.runtime
        self.base.auth_path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'invalid_budget_authorization'):
            b.load_authorization(self.base.config,self.base.auth_path,self.base.code)

    def test_layer2_only_plan_actual_launcher_changed_project_or_key_fails(self):
        out=self.root/'plan';profile=json.loads(planner.PROFILE.read_text())
        stage=planner.layer2_files(out,self.base.config.path,list(self.base.config.lanes),profile,'clip',
                                  approved_by='Fixture',evidence='Offline',reviewed_at='2026-10-13')
        (out/'plan.json').write_text(json.dumps({'stages':[stage]}))
        env=self.root/'runtime.env'
        def write_env(key=self.env['OPENAI_API_KEY'],project='proj_fixture'):
            env.write_text(f'OPENAI_DEV_API_KEY={key}\nOPENAI_DEV_PROJECT_ID={project}\n');env.chmod(0o600)
        write_env()
        self.assertEqual(check.check_launcher_binding(out,'dev',env)['status'],'pass')
        for change in ({'key':'different-synthetic-key'},{'project':'proj_other'}):
            write_env(**change)
            self.assertEqual(check.check_launcher_binding(out,'dev',env)['status'],'fail')
        self.assertFalse(self.base.auth['root'].exists())

    def test_no_selected_launcher_refuses_planner_before_authority_creation(self):
        out=self.root/'unlaunched';profile=json.loads(planner.PROFILE.read_text())
        with patch.dict(os.environ,{},clear=True),self.assertRaisesRegex(ValueError,'explicit_launcher'):
            planner.layer2_files(out,self.base.config.path,list(self.base.config.lanes),profile,'clip',
                                approved_by='Fixture',evidence='Offline',reviewed_at='2026-10-13')
        self.assertFalse(out.exists())

    def test_continuation_ingests_v3_both_scopes_without_changing_legacy_shapes(self):
        from tests import test_sermon_unified_continuation as fixtures
        from scripts import sermon_unified_continuation as continuation
        from scripts.sermon_unified import contracts as c
        f=fixtures.ContinuationTests();f.setUp();self.addCleanup(f.doCleanups)
        # This pre-existing continuation fixture freezes controller code to a
        # synthetic witness; create approvals for that exact test witness.
        self.base.code=controller.code_identity()
        value=json.loads(self.base.auth_path.read_text());value['codeIdentitySha256']=self.base.code
        receipt=json.loads(self.base.receipt.read_text());receipt['binding']['codeIdentitySha256']=self.base.code
        self.base.receipt.write_text(json.dumps(receipt));value['authority']['approvalSha256']=b.sha(self.base.receipt)
        self.base.auth_path.write_text(json.dumps(value))
        for scope in ('run','locale'):
            with self.subTest(scope=scope):
                self.write_v3(scope)
                f.manifest['productionRunId']=self.base.config.run_id
                f.recipe['productionRunId']=self.base.config.run_id
                f.manifest['bindings']['layer2Configuration']={'path':str(self.base.config.path),'sha256':c.file_sha(self.base.config.path)}
                f.recipe['stages'][0]['requiredEvidence']=[{'kind':'budget_authorization','binding':'runtimeBudget',
                    'inputs':{'configuration':fixtures.token('binding','layer2Configuration')}}]
                f.bind_recipe()
                before=copy.deepcopy(f.state)
                actual=continuation.validate_evidence(f.state,f.recipe_path,f.root,'runtimeBudget',self.path)
                self.assertEqual(actual['sha256'],c.file_sha(self.path));self.assertEqual(f.state,before)

    def test_actual_layer2_only_preflight_requires_selected_matching_launcher(self):
        out=self.root/'full-plan'
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(planner.main(['--out',str(out),'--scale','clip','--locales','zh-Hans',
                '--stage','layer2','--total-usd','20','--approved-by','Fixture','--evidence','Offline',
                '--layer2-execution',str(self.base.config.path)]),0)
        env=self.root/'selected.env'
        for variant in ('matching','project','key','omitted'):
            with self.subTest(variant=variant):
                key='synthetic-other-key' if variant=='key' else self.env['OPENAI_API_KEY']
                project='proj_other' if variant=='project' else 'proj_fixture'
                env.write_text(f'OPENAI_DEV_API_KEY={key}\nOPENAI_DEV_PROJECT_ID={project}\n');env.chmod(0o600)
                args=['--budget-plan',str(out)]
                if variant!='omitted':args+=['--openai-environment','dev','--env-file',str(env)]
                stream=io.StringIO()
                with patch.object(check,'check_code',return_value=check.result('code','pass')),contextlib.redirect_stdout(stream):
                    code=check.main(args)
                report=json.loads(stream.getvalue());rows={item['check']:item for item in report['checks']}
                self.assertEqual(rows['budget']['status'],'pass')
                self.assertEqual(rows['environment_binding']['status'],'pass' if variant=='matching' else 'fail')
                self.assertEqual(code,0 if variant=='matching' else 1)
                self.assertNotIn(key,stream.getvalue())
        self.assertFalse(self.base.auth['root'].exists())
