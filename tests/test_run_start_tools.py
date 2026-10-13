"""Artifact-bound planning and read-only preflight; no real model, SSH or Hosting calls."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from urllib.error import HTTPError

from scripts import check_run_start as check, plan_run_budgets as plan
from scripts import machine_qc_budget_authorization as auth


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return path


def run_plan(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = plan.main(list(args))
    return code, out.getvalue()


class PlanTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        self.base = Path(directory.name)
        from tests.test_canonical_layer2_controller import CanonicalLayer2ControllerTests
        fixture=CanonicalLayer2ControllerTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        values=fixture.fixture.fixture
        self.source=values.source;self.anchor=values.anchor;self.policy=values.policy
        write(self.base/'source.json', self.source)
        write(self.base/'anchor.json', self.anchor)
        for locale in plan.LOCALES:
            policy=json.loads(json.dumps(self.policy));policy['targetLocale']=locale
            write(self.base/f'{locale}.json',policy)
        from tests.test_run_machine_qc_audio_test import OPENAI_ENV
        self.manifest = write(self.base / 'inputs.json', {
            'schemaVersion':'sermon-machine-qc-inputs-v3', 'environment':'dev',
            'openaiRoute':{'schemaVersion':'sermon-openai-runtime-route-v1','environment':'dev','projectId':'proj_fixture',
                           'credentialAlias':'tongxing-dev-runtime','identitySource':'configured_runtime'},
            'credentialSha256':auth.credential_fingerprint(OPENAI_ENV['OPENAI_API_KEY']), 'source':'source.json',
            'anchor':'anchor.json','policies':{locale:f'{locale}.json' for locale in plan.LOCALES}})

    def args(self, name='run', locales='ko', total='20', extra=()):
        return ['--out',str(self.base/name),'--scale','clip','--locales',locales,'--total-usd',total,
                '--approved-by','Fixture operator','--evidence','Offline injected transport only',
                '--qc-inputs',str(self.manifest),*extra]

    def load(self, name='run'):
        return json.loads((self.base/name/'plan.json').read_text())

    def test_planned_approval_is_consumed_only_under_its_approved_project(self):
        from scripts import run_machine_qc_clip_test as driver
        from tests.test_run_machine_qc_audio_test import OPENAI_ENV
        run_plan(*self.args());stage=self.load()['stages'][0]
        paths={'source':str(self.base/'source.json'),'anchor':str(self.base/'anchor.json'),'policy':str(self.base/'ko.json')}
        environment={**OPENAI_ENV,'OPENAI_PROJECT_ID':'proj_fixture'}
        with mock.patch.dict('os.environ',environment),mock.patch('urllib.request.urlopen',side_effect=AssertionError('paid dispatch')):
            judge=driver.api_judge_for_resolved(Path(stage['authorization']),{'ko':paths},requested_locales=['ko'])
            self.assertEqual(judge.ledger.qc_context['openaiRoute']['projectId'],'proj_fixture')
            with mock.patch.dict('os.environ',{'OPENAI_PROJECT_ID':'proj_unapproved'}):
                with self.assertRaisesRegex(ValueError,'qc_budget_context_changed'):
                    driver.api_judge_for_resolved(Path(stage['authorization']),{'ko':paths},requested_locales=['ko'])
            with mock.patch.dict('os.environ',{'OPENAI_API_KEY':'different-synthetic-key'}):
                with self.assertRaisesRegex(ValueError,'qc_budget_context_changed'):
                    driver.api_judge_for_resolved(Path(stage['authorization']),{'ko':paths},requested_locales=['ko'])
        self.assertFalse((Path(stage['budgetRoot'])/'source-budget.json').exists())

    def test_serial_recommendation_issues_no_authority_until_one_stage_selected(self):
        code, output = run_plan(*self.args(locales='ko,es',total='10'))
        self.assertEqual(code,1)
        self.assertEqual(json.loads(output)['mode'],'one_stage_at_a_time')
        self.assertFalse((self.base/'run').exists())
        self.assertEqual(run_plan(*self.args(locales='ko,es',total='10',extra=['--stage','qc.ko']))[0],0)
        self.assertEqual([s['stage'] for s in self.load()['stages']],['qc.ko'])
        self.assertFalse((self.base/'run/qc-es').exists())
        self.assertLessEqual(self.load()['schedule']['worstCaseUsd'],10)

    def test_qc_approval_binds_one_locale_inputs_environment_and_secondary_cost(self):
        self.assertEqual(run_plan(*self.args(locales='ko,es'))[0],0)
        for stage in self.load()['stages']:
            value = auth.validate(stage['authorization'],context=stage['qcContext'],require_scope=True)
            self.assertEqual(value['qcContext']['targetLocale'],stage['stage'][3:])
            self.assertEqual(value['qcContext']['runId'],value['qcContext']['englishSourcePackageJsonSha256'])
            self.assertEqual(value['qcContext']['environment'],'dev')
            self.assertEqual(value['authority']['bounds']['globalBounds']['costMicrousd'],5_525_000)
            self.assertEqual(value['authority']['bounds']['globalBounds']['requests'],950)
        self.assertEqual(check.check_budget(self.base/'run')['status'],'pass')

    def test_reuse_requires_same_frozen_context_and_an_actual_prior_ledger(self):
        from scripts import sermon_source_budget as source
        run_plan(*self.args())
        first = self.load()['stages'][0]
        value = auth.validate(first['authorization'])
        with self.assertRaises(SystemExit):
            run_plan(*self.args('run2',extra=['--reuse-from',str(self.base/'run')]))
        self.assertFalse((self.base/'run2').exists())
        ledger = source.SourceBudget(value['budgetRoot'],{
            'approvalSha256':value['authority']['approvalSha256'],
            'globalBounds':value['authority']['bounds']['globalBounds'],
            'requestLimits':value['authority']['requestLimits']},verify=lambda:None,max_concurrent=16)
        with ledger._locked() as (saved_ledger,path):
            source.jobs._persist(path,saved_ledger)
        run_plan(*self.args('run2',extra=['--reuse-from',str(self.base/'run')]))
        second = auth.validate(self.load('run2')['stages'][0]['authorization'])
        self.assertEqual(second['reuseBudgetRoots'],[str(Path(value['budgetRoot']).resolve())])
        self.assertEqual(check.check_budget(self.base/'run2')['status'],'pass')
        with self.assertRaises(SystemExit):
            run_plan(*self.args('duplicate',extra=['--reuse-from',str(self.base/'run'),'--reuse-from',str(self.base/'run')]))
        self.assertFalse((self.base/'duplicate').exists())
        write(self.base/'source.json',{'source':'different sermon'})
        with self.assertRaises((ValueError,KeyError)):
            run_plan(*self.args('run3',extra=['--reuse-from',str(self.base/'run')]))
        self.assertFalse((self.base/'run3').exists())

    def test_missing_input_context_and_invalid_money_never_write_authority(self):
        args=self.args();i=args.index('--qc-inputs');del args[i:i+2]
        with self.assertRaises(SystemExit): run_plan(*args)
        for number in ('nan','inf','-1'):
            with self.subTest(number=number),self.assertRaises(ValueError):run_plan(*self.args(total=number))
        self.assertFalse((self.base/'run').exists())
        profile=json.loads(plan.PROFILE.read_text())
        profile['qc']['secondaryAsr']['capUsdPerLocale']['clip']=-1
        path=write(self.base/'profile.json',profile)
        with self.assertRaises(ValueError):run_plan(*self.args(extra=['--profile',str(path)]))
        self.assertFalse((self.base/'run').exists())

    def test_aggregate_total_settlement_and_stage_schedule_are_approval_bound(self):
        for field in ('totalUsd','settledUsd','schedule'):
            name='aggregate-'+field;run_plan(*self.args(name,extra=['--settled-usd','1']))
            self.assertEqual(check.check_budget(self.base/name)['status'],'pass')
            value=self.load(name)
            if field=='totalUsd':value[field]+=100
            elif field=='settledUsd':value[field]=0
            else:value[field]['mode']='edited'
            if field!='schedule':value['schedule']=plan.schedule(value['stages'],total=value['totalUsd'],settled=value['settledUsd'])
            write(self.base/name/'plan.json',value)
            result=check.check_budget(self.base/name)
            self.assertEqual(result['status'],'fail')
            self.assertIn('Aggregate',result['problems'][0])

    def test_no_stage_fits_and_existing_output_are_refused(self):
        code,_=run_plan(*self.args(total='1'));self.assertEqual(code,1)
        self.assertFalse((self.base/'run').exists())
        write(self.base/'run/keep.json',{'user':'work'})
        with self.assertRaises(SystemExit):run_plan(*self.args())
        self.assertTrue((self.base/'run/keep.json').exists())

    def test_auth_approval_input_or_plan_tampering_never_returns_green(self):
        for mutation in ('root','bounds','request','context','approval','source','cap','reuse'):
            with self.subTest(mutation=mutation):
                name='run-'+mutation;run_plan(*self.args(name));p=self.load(name);s=p['stages'][0]
                path=Path(s['authorization']);v=json.loads(path.read_text())
                if mutation=='approval':
                    receipt=path.parent/v['approvalReceipt'];d=json.loads(receipt.read_text());d['operatorEvidence']='edited';write(receipt,d)
                elif mutation=='source':write(self.base/'source.json',{'source':'edited'})
                elif mutation=='cap':
                    s['capUsd']=0.1;p['schedule']=plan.schedule(p['stages'],total=p['totalUsd'],settled=0)
                else:
                    if mutation=='root':v['budgetRoot']=str(self.base/'other')
                    elif mutation=='bounds':v['authority']['bounds']['globalBounds']['requests']+=1
                    elif mutation=='request':v['authority']['requestLimits']['maxCompletionTokens']=16
                    elif mutation=='context':v['qcContext']['environment']='prod'
                    elif mutation=='reuse':v['reuseBudgetRoots']=[str(self.base/'unapproved')]
                    write(path,v)
                    # Even if a changed plan pins the edited authorization hash, the signed binding rejects it.
                    s['authorizationSha256']=plan.file_sha256(path)
                write(self.base/name/'plan.json',p)
                self.assertEqual(check.check_budget(self.base/name)['status'],'fail')
                write(self.base/'source.json',self.source)

    def test_old_plan_and_other_root_authority_are_refused_read_only(self):
        run_plan(*self.args());p=self.load();root=Path(p['stages'][0]['budgetRoot']);root.mkdir()
        write(root/'source-budget.json',{'authority':{'approvalSha256':'f'*64}})
        before={str(f):f.read_bytes() for f in (self.base/'run').rglob('*') if f.is_file()}
        self.assertEqual(check.check_budget(self.base/'run')['status'],'fail')
        self.assertEqual(before,{str(f):f.read_bytes() for f in (self.base/'run').rglob('*') if f.is_file()})
        p['schemaVersion']='sermon-run-budget-plan-v1';write(self.base/'run/plan.json',p)
        self.assertEqual(check.check_budget(self.base/'run')['status'],'fail')

    def test_week_authority_is_locale_sharded_and_bound_by_the_actual_validator(self):
        from tests.test_canonical_layer2_controller import CanonicalLayer2ControllerTests
        from scripts import canonical_layer2_budget as budget,canonical_layer2_controller as controller
        fixture=CanonicalLayer2ControllerTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        profile=json.loads(plan.PROFILE.read_text());config=controller.load_configuration(fixture.path)
        selected=list(config.lanes)
        stage=plan.layer2_files(self.base/'week',fixture.path,selected,profile,'week',approved_by='Fixture',
                               evidence='Offline only',reviewed_at='2026-10-13T00:00:00Z')
        value=json.loads(Path(stage['authorization']).read_text())
        self.assertEqual(value['schemaVersion'],budget.LOCALE_SCHEMA)
        self.assertEqual(value['ledgerScope'],'locale')
        admitted=budget.load_authorization(config,stage['authorization'],controller.code_identity())
        self.assertEqual(admitted['scope'],'locale')
        self.assertGreaterEqual(value['authority']['globalBounds']['requests'],922)
        self.assertEqual(budget.LOCALE_LEDGER_MAX_BYTES,8*1024*1024)

    def test_an_underfunded_actual_week_is_rejected_before_writing(self):
        from tests.test_canonical_layer2_controller import CanonicalLayer2ControllerTests
        from scripts import canonical_layer2_controller as controller
        fixture=CanonicalLayer2ControllerTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        profile=json.loads(plan.PROFILE.read_text())
        with mock.patch.object(controller.models,'group_plan',return_value=[{}]*461):
            with self.assertRaisesRegex(ValueError,'initial 922 calls'):
                plan.layer2_files(self.base/'week',fixture.path,list(controller.load_configuration(fixture.path).lanes),
                                 profile,'week',approved_by='Fixture',evidence='offline',reviewed_at='2026-10-13')
        self.assertFalse((self.base/'week').exists())

    def test_invalid_qc_contracts_are_rejected_before_issuing_any_approval(self):
        write(self.base/'source.json',{'notASource':True})
        with self.assertRaises((ValueError,KeyError)):
            run_plan(*self.args())
        self.assertFalse((self.base/'run').exists())

    def test_current_unknown_and_corrupt_paid_ledgers_fail_without_writing(self):
        from scripts import sermon_source_budget as source
        run_plan(*self.args());stage=self.load()['stages'][0];value=auth.validate(stage['authorization'])
        def timeout(*args):raise TimeoutError('injected, no provider request')
        ledger=source.SourceBudget(value['budgetRoot'],{
            'approvalSha256':value['authority']['approvalSha256'],
            'globalBounds':value['authority']['bounds']['globalBounds'],
            'requestLimits':value['authority']['requestLimits']},verify=lambda:None,transport=timeout,max_concurrent=16)
        with self.assertRaises(TimeoutError):
            ledger.call(operation='judge.'+'a'*64,identity={'model':'fixture'},
                        bounds={'requests':1,'wallTimeMs':1,'costMicrousd':1},request=b'{}',
                        api_key='offline-fixture',content_type='application/json',endpoint='https://example.invalid')
        path=Path(value['budgetRoot'])/'source-budget.json';before=path.read_bytes()
        self.assertEqual(check.check_budget(self.base/'run')['status'],'fail')
        self.assertEqual(path.read_bytes(),before)
        path.write_text('{bad-json')
        self.assertEqual(check.check_budget(self.base/'run')['status'],'fail')
        self.assertEqual(path.read_text(),'{bad-json')

    def test_paid_metadata_migration_and_reuse_provenance_never_false_green(self):
        from scripts import sermon_source_budget as source,sermon_workflow_jobs as jobs
        from tests.test_source_budget_settlement import IDENTITY,BOUNDS,OPERATION,USAGE
        run_plan(*self.args());first=self.load()['stages'][0];v=auth.validate(first['authorization'])
        authority={'approvalSha256':v['authority']['approvalSha256'],
                   'globalBounds':v['authority']['bounds']['globalBounds'],'requestLimits':v['authority']['requestLimits']}
        def store(root,authority,reuse=()):
            return source.SourceBudget(root,authority,verify=lambda:None,max_concurrent=16,reuse_roots=reuse,
                transport=lambda *args:{'model':'gpt-6.1-sol','usage':USAGE})
        def call(ledger):
            return ledger.call(operation=OPERATION,identity=IDENTITY,bounds=BOUNDS,request=b'{}',api_key='fixture',content_type='application/json',endpoint='https://example.invalid')
        call(store(v['budgetRoot'],authority));path=Path(v['budgetRoot'])/'source-budget.json';saved=json.loads(path.read_text())
        self.assertEqual(check.check_budget(self.base/'run')['status'],'pass')
        for kind in ('concurrency','extra','resource'):
            damaged=json.loads(json.dumps(saved))
            if kind=='concurrency':damaged['maxConcurrent']=2
            elif kind=='extra':damaged['extra']=True
            else:damaged['resourcePolicySha256']='a'*64
            write(path,damaged);before=path.read_bytes()
            self.assertEqual(check.check_budget(self.base/'run')['status'],'fail')
            self.assertEqual(path.read_bytes(),before)
        write(path,saved)
        run_plan(*self.args('run2',extra=['--reuse-from',str(self.base/'run')]))
        v2=auth.validate(self.load('run2')['stages'][0]['authorization'])
        a2={**authority,'approvalSha256':v2['authority']['approvalSha256']}
        dest=store(v2['budgetRoot'],a2,[v['budgetRoot']]);call(dest)
        self.assertEqual(check.check_budget(self.base/'run2')['status'],'pass')
        response=next((dest.root/'responses').iterdir());body=json.loads(response.read_text())
        body.pop('reusedFrom');write(response,body)
        ledger_path=dest.root/'source-budget.json';value=json.loads(ledger_path.read_text())
        value['requests'][OPERATION]['responseSha256']=jobs._digest(body);write(ledger_path,value)
        self.assertEqual(check.check_budget(self.base/'run2')['status'],'fail')
        # A legacy destination with valid content still needs explicit v4 migration for reuse.
        value['schemaVersion']=source.LEDGER_V3;value.pop('reuseBudgetRoots');write(ledger_path,value)
        self.assertEqual(check.check_budget(self.base/'run2')['status'],'fail')

    def test_layer2_policy_bytes_and_locale_shard_pending_calls_are_checked(self):
        from tests.test_canonical_layer2_controller import CanonicalLayer2ControllerTests
        from scripts import canonical_layer2_controller as controller,canonical_layer2_budget as l2
        from scripts import sermon_review_budget as budget,sermon_workflow_jobs as jobs
        fixture=CanonicalLayer2ControllerTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        config=controller.load_configuration(fixture.path);locales=','.join(config.lanes)
        args=['--out',str(self.base/'l2'),'--scale','week','--locales',locales,'--total-usd','100',
              '--approved-by','Fixture','--evidence','offline','--layer2-execution',str(fixture.path),'--stage','layer2']
        self.assertEqual(run_plan(*args)[0],0)
        self.assertEqual(check.check_budget(self.base/'l2')['status'],'pass')
        path=next(iter(config.lanes.values()))['policy'];original=path.read_bytes();v=json.loads(original)
        v['targetLocale']='ko';write(path,v)
        self.assertEqual(check.check_budget(self.base/'l2')['status'],'fail');path.write_bytes(original)
        value=self.load('l2')['stages'][0];admitted=l2.load_authorization(config,value['authorization'],controller.code_identity())
        root=l2.ledger_root(admitted,next(iter(config.lanes)));store=budget.BudgetStore(root,admitted['value']['authority'],max_ledger_bytes=l2.LOCALE_LEDGER_MAX_BYTES)
        # An actual reservation through the canonical store, without execution.
        identity=budget.chain_identity(dict(zip(budget.IDENTITY_FIELDS,['a'*64,'b'*64,'c'*64,'d'*64,'e'*64,next(iter(config.lanes)),f'l2.{next(iter(config.lanes))}.group1'])))
        store.reserve(identity=identity,operation_id='op1',kind='initial_generation',revision_id='r1',revision_number=1,
                      input_sha256='d'*64,bounds={'requests':1,'inputTokens':1,'outputTokens':1,'wallTimeMs':1,'costMicrousd':1})
        before={str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()}
        self.assertEqual(check.check_budget(self.base/'l2')['status'],'fail')
        self.assertEqual(before,{str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()})


class StartCheckTests(unittest.TestCase):
    def test_page_v4_404_is_empty_but_other_http_errors_are_reported(self):
        def response(request,timeout):
            if request.full_url.endswith('v4.json'):
                raise HTTPError(request.full_url,404,'absent',{},None)
            return contextlib.nullcontext(io.BytesIO(b'{"pages":[{"id":"existing"}]}'))
        with mock.patch.object(check,'urlopen',side_effect=response):
            self.assertEqual(check.check_page('new','https://example.invalid')['status'],'pass')
            self.assertEqual(check.check_page('existing','https://example.invalid')['status'],'fail')
        with mock.patch.object(check,'urlopen',side_effect=HTTPError('url',500,'error',{},None)):
            self.assertEqual(check.check_page('new','https://example.invalid')['status'],'fail')

    def test_missing_expected_identities_cannot_return_green(self):
        from scripts import machine_quality_waiver as waiver
        with mock.patch.object(check,'git',side_effect=['a'*40,'']),mock.patch.object(waiver,'implementation_sha256',return_value='b'*64):
            self.assertEqual(check.check_code(None,None)['status'],'fail')
        with mock.patch.object(check,'git',side_effect=['a'*40,'']),mock.patch.object(waiver,'implementation_sha256',return_value='b'*64):
            self.assertEqual(check.check_code('a'*40,'b'*64)['status'],'pass')
        with mock.patch.object(check,'git',side_effect=['a'*40,'']),mock.patch.object(waiver,'implementation_sha256',return_value='b'*64):
            self.assertEqual(check.check_code('a'*8,'b'*64)['status'],'fail')

    def test_api_only_needs_no_spark_session_and_gpu_still_needs_it(self):
        with mock.patch.object(check,'ssh',return_value=mock.Mock(returncode=0,stdout='spark')),mock.patch.dict('os.environ',{},clear=True):
            self.assertEqual(check.check_spark('host',False,None)['session'],'not_required_api_only')
            self.assertEqual(check.check_spark('host',True,None)['status'],'fail')

    def test_fresh_paths_reject_an_occupied_directory(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)
            self.assertEqual(check.check_fresh([path,path/'new'])['status'],'pass')
            (path/'user.txt').write_text('keep')
            self.assertEqual(check.check_fresh([path])['status'],'fail')


if __name__=='__main__':unittest.main()
