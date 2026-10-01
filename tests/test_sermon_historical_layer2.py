"""Historical paid cache provenance, strict rebinding and plugin-only repair."""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from scripts import sermon_historical_layer2 as h, sermon_strict_layer2 as strict
from scripts import sermon_strict_candidate_bridge as bridge, sermon_review_contracts as c
from scripts import sermon_review_budget as budget, sermon_diagnostic_provider as provider
from scripts import sermon_diagnostic_attempts as attempts, sermon_accounting as accounting, sermon_log_profile as profile
from scripts import target_language_policy as policies, produce_target_language_candidate as producer
from tests import test_sermon_diagnostic_provider as fixtures


class HistoricalLayer2Tests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ProviderTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.parent=self.f.f.root.resolve();self.new=self.parent.parent/(self.parent.name+'-new')
        self.addCleanup(lambda: __import__('shutil').rmtree(self.new,ignore_errors=True))
        self.identity=accounting.execution_identity();self.identity['trackedWorkingTreeDirty']=False
        self.enterContext(patch.object(accounting,'execution_identity',return_value=self.identity))
        self.f.provider=self.f.provider_for(codeSha256=c.canonical_sha256(self.identity))
        self.locale=self.parent/'locales/zh-Hans'
        groups=self.f.f.f.evidence['groups']
        first=deepcopy(groups[0])
        for key in ('sourceUnitIds','targetUtterances','coverage'):first[key]=[v for g in groups for v in g[key]]
        self.f.f.f.evidence['groups']=[first]
        self.group={k:first[k] for k in ('translationGroupId','sourceUnitIds')}
        self.f.prepared=strict.prepare(*self.f.f.args,self.group,request_limits=self.f.selected)
        self.cid='candidate.'+c.canonical_sha256(self.group)
        self.f.root=self.locale/'groups'/c.canonical_sha256(self.group)/'revisions/initial'
        self.network=self.enterContext(patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('network forbidden')))

    def build(self, *, failed=False):
        if failed:
            plugin=self.f.f.f.plugin_path
            plugin.write_text('''PLUGIN_ID="zh-Hans-sermon-v1"
PLUGIN_VERSION="test-v1"
def review_group(policy,english_units,group):
    return [{"checkId":check,"status":"pass" if "回想" in group["targetText"] else "fail",
             "evidence":"fixture missing declared surface"} for check in policy["languageReview"]["requiredChecks"]]
''')
            draft=deepcopy(self.f.prepared['policy']);draft.pop('componentSha256')
            draft['languageReview']['pluginImplementationSha256']=producer.plugin_implementation_sha256(plugin)
            draft['languageReview']['requiredChecks']=['term_surface_preservation']
            draft['terminology']['properNames']=[dict(source='Remember',target='回想',reviewStatus='project_established')]
            rubric=deepcopy(self.f.prepared['rubric']);rubric['requiredLanguagePluginChecks']=['term_surface_preservation']
            draft['reviewContract']['rubricCanonicalJsonSha256']=c.canonical_sha256(rubric)
            policy=policies.freeze_strict_policy(draft,rubric)
            self.f.f.args[2:]=[strict.material_bytes(policy),strict.material_bytes(rubric)]
            self.f.prepared=strict.prepare(*self.f.f.args,self.group,request_limits=self.f.selected)
        with self.session():
            self.f.subject.generate(self.f.prepared,self.f.root,self.cid,'initial','synthetic',self.f.provider,
                bounds=self.f.bound,usage_resolver=self.f.provider.usage_resolver)
            self.f.subject.review(self.f.prepared,self.f.root,self.cid,'initial','synthetic',self.f.provider,
                bounds=self.f.bound,usage_resolver=self.f.provider.usage_resolver)
        materials={}
        for key,data in zip(('englishSource','anchor','policy','rubric'),self.f.f.args):
            path=self.parent/'inputs'/(key+'.json');path.parent.mkdir(exist_ok=True);path.write_bytes(data)
            materials[key]=h.ref(path)
        locale_input=dict(productionRunId=self.f.provider.config['runId'],groups=[self.group],
            inputBytesSha256=[c.bytes_sha256(b) for b in self.f.f.args],requestLimits=self.f.selected)
        strict.save_once(self.locale/'locale-input.json',locale_input)
        plugin=self.f.f.f.plugin_path;language_root=self.locale/'language-evidence'
        try:
            actual=bridge.compile_candidate(*self.f.f.args,[(self.f.root,1)],plugin_path=plugin,
                expected_plugin_sha256=producer.plugin_implementation_sha256(plugin))
            language,bindings=actual['languageReceipt'],actual['revisionBindings']
        except bridge.LanguagePluginRejected as error:
            language,bindings=error.language_receipt,error.revision_bindings
        self.assertEqual(language['groupReviews'][0]['status'],'fail' if failed else 'pass')
        strict.save_once(language_root/'language-review.json',language)
        strict.save_once(language_root/'revision-bindings.json',{'groups':bindings})
        self.plan=dict(schemaVersion='sermon-bounded-diagnostic-plan-v1',runDirectory=str(self.parent),
            providerConfig=self.f.provider.config,authority=self.f.store.authority,executionIdentity=self.identity,
            sourceClipPath=str(self.parent/'unused-synthetic-clip.wav'))
        strict.save_once(self.parent/'run-plan.json',self.plan)
        attempts.close_parent(self.parent/'run-plan.json',instruction_reference_sha256='a'*64)
        baseline=attempts.observe_legacy_lineage(self.parent/'run-plan.json')
        auth=dict(schemaVersion=attempts.AUTH_SCHEMA_V2,parentPlanSha256=c.canonical_sha256(self.plan),
            legacyBaselineSha256=c.canonical_sha256(baseline),instructionReferenceSha256='b'*64,
            newRoot=str(self.new),newRunId='8'*64,newMaxRequests=10,newHardLimitMicrousd=4_000_000,
            newTotalWallSeconds=600,cumulativeMaxRequests=1000,cumulativeHardLimitMicrousd=110_000_000,
            scope='fresh_distinct_stage_no_old_replay')
        new,linkage=attempts.prepare_new_attempt_v2(self.parent/'run-plan.json',new_root=self.new,
            authorization=auth,execution_identity=self.identity,baseline=baseline)
        attempts.persist_new_attempt_v2(new,linkage,auth)
        self.spec=dict(schemaVersion=h.SPEC,parentPlanRef=h.ref(self.parent/'run-plan.json'),
            newPlanRef=h.ref(self.new/'run-plan.json'),linkedHistoryRef=h.ref(self.new/'linked-history.json'),
            parentLocaleRoot=str(self.locale),parentMaterialRefs=materials,parentLanguageRoot=str(language_root),
            parentPluginRef=h.ref(plugin))
        self.subject=h.HistoricalLayer2Reuse(self.spec)
        self.new_group=self.new/'locales/zh-Hans/groups'/c.canonical_sha256(self.group)
        self.snapshots={p:p.read_bytes() for p in self.parent.rglob('*.json')}
        return new

    def session(self):
        return profile.session(self.new/'logs','historical-test',work_kind='production',evidence_mode='synthetic')

    def run_group(self, caller=None):
        with self.session():
            return self.subject.run_group(self.f.prepared,root=self.new_group,candidate_id=self.cid,
                api_key='synthetic',caller=caller or Mock(side_effect=AssertionError('must not dispatch')))

    def assert_parent_unchanged(self):
        self.assertTrue(all(p.read_bytes()==data for p,data in self.snapshots.items()))

    def test_real_strict_cache_rebind_recomputes_receipts_zero_new_paid_or_d5(self):
        self.build();result=self.run_group();root=Path(result['root'])
        self.assertEqual(result['status'],'machine_review_passed')
        self.assertEqual(len(self.f.calls),2)
        self.assertFalse((self.new/'budget').exists())
        self.assertFalse((root/'generator.budget-binding.json').exists())
        self.assertNotEqual(c.read_snapshot(root/'review-receipt.json')[0]['revisionId'],'initial')
        proof,_=c.read_snapshot(root/'historical-rebind.json')
        h.validate_rebind(self.f.prepared,root,proof)
        with self.session():
            actual=bridge.compile_candidate(*self.f.f.args,[(root,1)],plugin_path=self.f.f.f.plugin_path,
                expected_plugin_sha256=producer.plugin_implementation_sha256(self.f.f.f.plugin_path))
        self.assertEqual(actual['languageReceipt']['groupReviews'][0]['status'],'pass')
        self.assertEqual(self.run_group(),result);self.assertEqual(len(self.f.calls),2)
        self.assert_parent_unchanged();self.network.assert_not_called()

    def test_inputs_prompt_limits_code_and_provenance_tamper_fail_without_fallback(self):
        self.build()
        changed=deepcopy(self.f.prepared);changed['requestLimits']['maxCompletionTokens']-=1
        with self.assertRaises(c.ContractError):self.subject.inspect(changed)
        with patch.object(accounting,'execution_identity',return_value={**self.identity,'trackedWorkingTreeDirty':True}):
            with self.assertRaises(c.ContractError):self.run_group()
        closed=self.parent/'budget'/budget.STORE_ID/'provider-run/closed.json'
        original=closed.read_bytes();closed.write_bytes(original+b' ')
        with self.assertRaises(c.ContractError):h.HistoricalLayer2Reuse(self.spec)
        closed.write_bytes(original)
        result=self.run_group();root=Path(result['root']);proof,_=c.read_snapshot(root/'historical-rebind.json')
        for mutate in (lambda p:p.update(newPaidRequests=1),lambda p:p.update(artifactRefs=[]),
                       lambda p:p['parentRefs'][0].update(bytesSha256='0'*64),lambda p:p.update(extra='private')):
            invalid=deepcopy(proof);mutate(invalid)
            with self.assertRaises(c.ContractError):h.validate_rebind(self.f.prepared,root,invalid)
        self.assertEqual(len(self.f.calls),2);self.network.assert_not_called()

    def test_plugin_only_failure_repairs_new_revision_preserves_sol_pass_and_paid_lineage(self):
        new=self.build(failed=True)
        self.f.f.f.evidence['groups'][0]['targetUtterances'].append('回想')
        store=budget.BudgetStore(self.new/'budget',new['authority'])
        paid=provider.DiagnosticProvider(store,new['providerConfig'],self.f.selected,executor=self.f.http,
            monotonic=lambda:self.f.clock,domain=lambda:'7'*64)
        paid.source_check_payload=Mock(side_effect=self.f.payload)
        result=self.run_group(paid);root=Path(result['root'])
        self.assertEqual(result['status'],'machine_review_passed')
        self.assertEqual(result['candidateRevision']['revisionNumber'],2)
        self.assertEqual(result['candidateRevision']['parentRevisionId'],'initial')
        self.assertEqual(paid.snapshot()['requestCount'],2)
        self.assertEqual(c.read_snapshot(store.root/budget.STORE_ID/'state.json')[0]['reservations'],{})
        repair=strict.load_repair(root);self.assertEqual(repair['triggerReview']['reviewVerdict'],'pass')
        self.assertEqual(repair['languagePluginRepair']['failedGroup']['status'],'fail')
        prompt=strict.generation_prompt(self.f.prepared,repair)
        self.assertEqual(prompt['input']['termSurfaceRepairs'][0]['target'],'回想')
        self.assertNotEqual(c.canonical_sha256(strict._payload(self.f.prepared,'translator',prompt)),
            c.read_snapshot(self.f.root/'generator.json')[0]['payloadSha256'])
        with self.session():
            actual=bridge.compile_candidate(*self.f.f.args,[(root,1)],plugin_path=self.f.f.f.plugin_path,
                expected_plugin_sha256=producer.plugin_implementation_sha256(self.f.f.f.plugin_path))
        self.assertEqual(actual['languageReceipt']['groupReviews'][0]['status'],'pass')
        dispatch=root/'translator-historical-dispatch-proof.json';original=dispatch.read_bytes()
        altered=c.decode_json(original);altered['payloadSha256']='0'*64
        dispatch.write_bytes(strict.material_bytes(altered))
        with self.session(),self.assertRaises(c.ContractError):
            bridge.compile_candidate(*self.f.f.args,[(root,1)],plugin_path=self.f.f.f.plugin_path,
                expected_plugin_sha256=producer.plugin_implementation_sha256(self.f.f.f.plugin_path))
        dispatch.write_bytes(original)
        returned,_=c.read_snapshot(root/'translator-historical-return-proof.json')
        response=Path(returned['providerReceiptRef']['path']);original=response.read_bytes();response.write_bytes(original+b' ')
        with self.assertRaises(c.ContractError):h.validate_repair_return(root,repair,'translator',returned)
        response.write_bytes(original)
        self.assertEqual(self.run_group(paid),result);self.assertEqual(paid.snapshot()['requestCount'],2)
        self.assert_parent_unchanged();self.network.assert_not_called()

    def test_unknown_repair_transport_is_retained_and_restart_never_retries(self):
        new=self.build(failed=True);calls=[]
        def unknown(*args,**kwargs):calls.append(1);raise TimeoutError('private provider failure')
        store=budget.BudgetStore(self.new/'budget',new['authority'])
        paid=provider.DiagnosticProvider(store,new['providerConfig'],self.f.selected,executor=unknown,
            monotonic=lambda:self.f.clock,domain=lambda:'7'*64)
        paid.source_check_payload=Mock(side_effect=self.f.payload)
        result=self.run_group(paid)
        self.assertEqual(result['status'],'reconciliation_required')
        self.assertEqual(len(calls),1);self.assertEqual(paid.snapshot()['requestCount'],1)
        self.assertEqual(self.run_group(paid),result);self.assertEqual(len(calls),1)
        self.assert_parent_unchanged();self.network.assert_not_called()

    def test_repair_logging_failure_propagates_without_settlement_or_retry(self):
        new=self.build(failed=True)
        store=budget.BudgetStore(self.new/'budget',new['authority'])
        paid=provider.DiagnosticProvider(store,new['providerConfig'],self.f.selected,executor=self.f.http,
            monotonic=lambda:self.f.clock,domain=lambda:'7'*64)
        paid.source_check_payload=Mock(side_effect=self.f.payload)
        with patch.object(strict,'generate',side_effect=accounting.AccountingWriteError('synthetic log failure')):
            with self.assertRaises(accounting.AccountingWriteError):self.run_group(paid)
        self.assertEqual(len(self.f.calls),2);self.assertEqual(paid.snapshot()['requestCount'],0)
        self.assert_parent_unchanged();self.network.assert_not_called()
