"""Closed-parent native wiring: fixed fixtures only, no API or native model."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import tempfile
import unittest
from unittest.mock import patch

from scripts import sermon_fresh_diagnostic as fresh
from scripts import sermon_diagnostic_dag_session as sessions
from scripts import sermon_diagnostic_prefect_flow as flow
from scripts import sermon_historical_native_seed as native
from scripts import sermon_diagnostic_attempts as attempts
from scripts import sermon_diagnostic_preview_worker as worker
from scripts import sermon_public_snapshot as public
from scripts import sermon_review_contracts as c
from tests import test_sermon_diagnostic_attempts as attempt_fixtures
from tests import test_sermon_diagnostic_preview_worker as preview_fixtures


class NativeFreshFreezeTests(unittest.TestCase):
    def setUp(self):
        self.f=attempt_fixtures.NewAttemptV2Tests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        attempts.close_parent(self.f.path,instruction_reference_sha256='f'*64)
        self.plan,linkage=self.f.prepare()
        attempts.persist_new_attempt_v2(self.plan,linkage,self.f.auth)
        self.root=Path(self.plan['runDirectory'])
        self.source={'fixture':'source'};self.anchor={'fixture':'anchor'}
        public.save_once(self.root/'source.json',self.source);public.save_once(self.root/'anchor-manifest.json',self.anchor)
        self.worker_path=self.f.path.parent/'synthetic-native-worker-receipt.json';public.save_once(self.worker_path,{'synthetic':'no-model'})
        self.request_path=self.f.path.parent/'synthetic-native-worker-request.json';public.save_once(self.request_path,{'synthetic':'no-execution'})
        self.model_path=self.f.path.parent/'inert-checkpoint.safetensors';self.model_path.write_bytes(b'not model bytes'*10000)
        closure=self.f.path.parent/'budget'/attempts.budget.STORE_ID/'provider-run/closed.json'
        self.report={'schemaVersion':'sermon-historical-native-parent-preflight-v1','targetLocale':'zh-Hans',
            'parentPlan':worker._ref(self.f.path.resolve()),'workerReceipt':worker._ref(self.worker_path.resolve()),
            'closure':worker._ref(closure.resolve()),'workerRequest':worker._ref(self.request_path.resolve()),
            'originalInputs':[worker._ref(self.model_path.resolve())],'originalArtifacts':[worker._ref(self.worker_path.resolve())],
            'sourceJsonSha256':c.canonical_sha256(self.source),'anchorJsonSha256':c.canonical_sha256(self.anchor),
            'grantsExecutionAuthority':False,'productionEligible':False}
        self.report_path=self.root/'parent-native-preflight.json';public.save_once(self.report_path,self.report)
        self.spec={'schemaVersion':'sermon-fresh-historical-native-locale-v1','targetLocale':'zh-Hans',
            'parentPlan':worker._ref(self.f.path.resolve()),'workerReceipt':worker._ref(self.worker_path.resolve()),
            'parentPreflight':worker._ref(self.report_path.resolve())}
        self.session=fresh.FreshDiagnosticSession.__new__(fresh.FreshDiagnosticSession)
        self.session.root=self.root;self.session.plan=self.plan
        self.session.subject=SimpleNamespace(config=self.plan['providerConfig']);self.session.context={'fixture':'current'}
        self.session.binding={};self.session.offline_fixture=False
        self.session._historical_native_specification=None;self.session._historical_native_seeds={}
        self.session._historical_specification=None

    def preflight(self, specs=None, **kwargs):
        with patch.object(native,'preflight_parent',return_value=self.report):
            return fresh._preflight_historical_native_specs(specs or {'zh-Hans':self.spec},{'zh-Hans':None},
                offline_fixture=False,plan=kwargs.get('plan',self.plan))

    def configure(self):
        with patch.object(self.session,'_check'),patch.object(native,'preflight_parent',return_value=self.report):
            self.session.configure_historical_native({'zh-Hans':self.spec},['zh-Hans'])

    def test_ancestor_closure_current_plan_source_scopes_and_refs_frozen_without_old_writes(self):
        before={p:p.read_bytes() for p in self.f.path.parent.rglob('*.json') if p.is_file()}
        lanes=self.preflight();self.assertEqual(set(lanes),{'zh-Hans'})
        refs={r['path'] for r in lanes['zh-Hans']['references']}
        self.assertIn(str(self.root/'linked-history.json'),refs)
        self.assertIn(str(self.root/'authorization.json'),refs)
        self.assertIn(str(Path(native.__file__).resolve()),refs)
        self.assertIn(str(self.model_path.resolve()),refs)
        self.configure();self.session._check_historical_native_inputs()
        seed=self.session._historical_native_seeds['zh-Hans'];self.assertIs(type(seed),native.HistoricalSeed)
        self.assertEqual(seed.parent_plan_path,self.spec['parentPlan']['path'])
        self.assertEqual({p:p.read_bytes() for p in before},before)
        with patch.object(sessions.DiagnosticSession,'preview',return_value={'cache':'forwarded'}) as call:
            result=self.session.preview('zh-Hans',{'fixture':'spec'},depends_on=['real-leaf'])
        self.assertEqual(result,{'cache':'forwarded'});self.assertIs(call.call_args.kwargs['historical_seed'],seed)
        self.assertEqual(call.call_args.kwargs['depends_on'],['real-leaf'])
        with patch.object(sessions.DiagnosticSession,'preview',return_value={}) as call:self.session.preview('ko',{})
        self.assertNotIn('historical_seed',call.call_args.kwargs)

    def test_drift_sidecar_helper_or_parent_unit_and_wrong_locale_rejected(self):
        self.configure();sidecar=self.root/'fresh-historical-native-inputs.json';before=sidecar.read_bytes()
        sidecar.write_bytes(before+b' ')
        with self.assertRaisesRegex(c.ContractError,'inputs_changed'):self.session._check_historical_native_inputs()
        sidecar.write_bytes(before)
        self.model_path.write_bytes(b'changed checkpoint')
        with self.assertRaisesRegex(c.ContractError,'inputs_changed'):self.session._check_historical_native_inputs()
        with self.assertRaisesRegex(c.ContractError,'specs_invalid'):
            self.preflight({'zh-Hans':dict(self.spec,targetLocale='ko')})

    def test_source_scope_drift_or_unregistered_ancestor_rejected_before_paid_stage(self):
        plan=deepcopy(self.plan);plan['providerConfig']['sourceClipSha256']='0'*64
        with self.assertRaisesRegex(c.ContractError,'source_changed'):self.preflight(plan=plan)
        history_path=self.root/'linked-history.json';history=public.read_snapshot(history_path)[0]
        history['newPlanSha256']='0'*64;history_path.write_bytes(c.canonical_bytes(history))
        with self.assertRaisesRegex(c.ContractError,'lineage_changed'):self.preflight()
        self.assertFalse((self.root/'budget').exists())

    def test_new_source_hash_change_blocks_configuration_and_missing_proof_blocks_constructor(self):
        source_path=self.root/'source.json';source_path.write_bytes(c.canonical_bytes({'changed':'source'}))
        with self.assertRaisesRegex(c.ContractError,'source_changed'):self.configure()
        self.assertFalse((self.root/'fresh-historical-native-inputs.json').exists())
        with patch.object(fresh,'_preflight_preview_specs'),patch.object(fresh,'FreshDiagnosticSession') as constructor, \
             patch.object(native,'preflight_parent',side_effect=c.ContractError('historical_seed_parent_not_closed')):
            with self.assertRaisesRegex(c.ContractError,'not_closed'):
                fresh.run_fresh_diagnostic(self.plan,key='synthetic-unused',execute=True,source_recipe=None,
                    authorization={},locale_drafts={'zh-Hans':{}},preview_specs={},historical_native_specs={'zh-Hans':self.spec})
            constructor.assert_not_called()

    def test_large_aggregate_native_sidecar_replay_and_dag_inventory_stream_files(self):
        # Many bounded fields, not one overlarge string; same >256KB shape as
        # real ancestry/runtime aggregate evidence. Not a native model claim.
        self.report['syntheticPadding']=[{'index':i,'fixture':'p'*80} for i in range(3500)]
        self.report_path.write_bytes(c.canonical_bytes(self.report));self.spec['parentPreflight']=worker._ref(self.report_path.resolve())
        self.configure();self.session._check_historical_native_inputs()
        sidecar=self.root/'fresh-historical-native-inputs.json';self.assertGreater(sidecar.stat().st_size,256*1024)
        # Public immutable reader handles idempotent data above private cap.
        public.save_once(sidecar,self.session._historical_native_specification)
        scoped=SimpleNamespace(root=self.root,binding=self.session.binding,_path=lambda value,plugin=False:Path(value))
        with patch.object(Path,'read_bytes',side_effect=AssertionError('streaming guard must not read model bytes all at once')):
            inventory=flow._inventory({'locales':{}},scoped)
        self.assertIn(str(sidecar),inventory);self.assertIn(str(self.model_path.resolve()),inventory)
        self.model_path.write_bytes(b'changed after DAG freeze')
        self.assertNotEqual(flow._inventory({'locales':{}},scoped)[str(self.model_path.resolve())],inventory[str(self.model_path.resolve())])

    def test_real_preflight_stage_completes_before_locale_and_enters_dag_dependencies(self):
        from scripts import sermon_accounting as accounting
        session=self.session;session.evidence_mode='synthetic';session._historical_reuse={}
        captured={}
        def prepare(*args,**kwargs):
            with accounting.stage('fixture.source.leaf',depends_on=[]) as span:pass
            return {'completionSpans':[span],'evidence':{'syntheticSourceOnly':True}}
        class FixedDAG:
            nodes=[('text.zh-Hans',),('delivery.readonly',)]
            def __init__(self,session,config):captured['dag']=self
            def freeze(self):pass
            def execute(self,node):
                assert (session.root/'fresh-historical-native-inputs.json').exists()
                return {'readyForDownstream':False,'completionSpans':[]}
        locale_spec={'source':str(self.root/'source.json'),'anchor':str(self.root/'anchor-manifest.json'),
            'policy':str(self.root/'policy.json'),'rubric':str(self.root/'rubric.json')}
        preview_spec={'paths':{key:locale_spec[key] for key in ('source','anchor','policy')},
            'strict_rubric_path':locale_spec['rubric']}
        with patch.object(fresh,'_preflight_preview_specs'),patch.object(fresh,'FreshDiagnosticSession',return_value=session), \
             patch.object(session,'_check'),patch.object(session,'prepare_source',side_effect=prepare), \
             patch.object(native,'preflight_parent',return_value=self.report),patch.object(fresh,'freeze_locale_inputs',return_value={'zh-Hans':locale_spec}), \
             patch.object(flow,'DiagnosticDAG',FixedDAG):
            result=fresh.run_fresh_diagnostic(self.plan,key='unused-synthetic',execute=True,source_recipe={},authorization={},
                locale_drafts={'zh-Hans':{}},preview_specs={'zh-Hans':preview_spec},historical_native_specs={'zh-Hans':self.spec})
        self.assertEqual(result['status'],'incomplete')
        events=[json.loads(line) for file in (self.root/'fresh-diagnostic-logs').glob('*.jsonl') for line in file.read_text().splitlines()]
        completed=[row for row in events if row.get('event')=='stage_finished' and row.get('stage')=='diagnostic.historical_native_preflight']
        self.assertEqual(len(completed),1);self.assertEqual(completed[0]['status'],'completed')
        self.assertIn(completed[0]['spanId'],captured['dag'].initial_source_spans)
        self.assertFalse((self.root/'budget').exists())

    def test_none_keeps_normal_path_and_offline_fixture_cannot_adopt_native(self):
        with patch.object(native,'preflight_parent',side_effect=AssertionError('normal mode must not inspect historical data')):
            self.assertEqual(fresh._preflight_historical_native_specs(None,{},offline_fixture=True),{})
        with self.assertRaisesRegex(c.ContractError,'locales_invalid'):
            fresh._preflight_historical_native_specs({'zh-Hans':self.spec},{'zh-Hans':None},offline_fixture=True,plan=self.plan)


class NativeDAGHandoffTests(unittest.TestCase):
    def setUp(self):
        self.f=preview_fixtures.PreviewWorkerTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.session=sessions.DiagnosticSession.__new__(sessions.DiagnosticSession)
        self.session.root=self.f.root;self.session.offline_fixture=False;self.session.subject=self.f.subject;self.session.context=self.f.context
        locale=self.f.f.candidate['targetLocale'];self.locale=locale
        candidate_path=self.f.root/'locales'/locale/'machine-candidates/current/candidate.json'
        candidate_path.parent.mkdir(parents=True,exist_ok=True)
        public.save_once(candidate_path,self.f.f.candidate)
        self.session._locale_results={locale:{'status':'waiting_human','output':str(candidate_path.parent),
            'candidateSha256':c.canonical_sha256(self.f.f.candidate)}}
        self.session._locale_specs={locale:{**self.f.spec['paths'],'rubric':self.f.spec['strict_rubric_path']}}
        self.spec=deepcopy(self.f.spec);self.spec['paths'].pop('candidate');self.spec['out']=str(self.f.root/'diagnostic-previews'/locale/'native-new')

    def test_native_seed_exact_type_forwarded_after_actual_candidate_source_binding(self):
        seed=native.HistoricalSeed(str(self.f.root/'run-plan.json'),str(self.f.root/'old/worker-receipt.json'))
        with self.f.session(),patch.object(self.session,'_check'),patch.object(worker,'launch_preview',return_value={'fixture':'launch'}) as launch:
            self.session.preview(self.locale,self.spec,depends_on=['actual-leaf'],historical_seed=seed)
        self.assertIs(launch.call_args.kwargs['historical_seed'],seed)
        self.assertEqual(launch.call_args.kwargs['depends_on'],['actual-leaf'])
        self.assertIn('/locales/'+self.locale+'/machine-candidates/',launch.call_args.args[3]['paths']['candidate'])
        with self.f.session(),patch.object(self.session,'_check'),patch.object(worker,'launch_preview') as launch:
            self.session.preview(self.locale,self.spec)
        self.assertNotIn('historical_seed',launch.call_args.kwargs)

    def test_unknown_seed_and_fixture_refuse_before_any_worker(self):
        for seed,offline in [(dict(parent_plan_path='forged'),False),
                             (native.HistoricalSeed('unused','unused'),True)]:
            self.session.offline_fixture=offline
            with patch.object(self.session,'_check') as check,patch.object(worker,'launch_preview') as launch, \
                 self.assertRaisesRegex(c.ContractError,'native_seed_type_invalid'):
                self.session.preview(self.locale,self.spec,historical_seed=seed)
            launch.assert_not_called();check.assert_not_called()


if __name__=='__main__':unittest.main()
