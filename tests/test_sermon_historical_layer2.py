"""Historical paid cache provenance, strict rebinding and plugin-only repair."""
from copy import deepcopy
import tempfile, subprocess
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from scripts import sermon_historical_layer2 as h, sermon_strict_layer2 as strict
from scripts import run_bounded_diagnostic as bounded
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
        # Real identity checks run in a committed isolated Git fixture; no
        # dependence on the caller's uncommitted worktree or private run roots.
        git_root=Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        (git_root/'scripts').mkdir()
        clone=git_root/'scripts/sermon_accounting.py'
        clone.write_bytes(Path(accounting.__file__).read_bytes())
        for args in (('init','-q'),('add','.'),('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','fixture')):
            subprocess.run(['git','--no-optional-locks','-C',str(git_root),*args],capture_output=True,check=True,timeout=5)
        self.enterContext(patch.object(accounting,'__file__',str(clone)))
        self.identity=accounting.execution_identity()
        self.assertIs(self.identity['trackedWorkingTreeDirty'],False)
        self.f.provider=self.f.provider_for(codeSha256=c.canonical_sha256(self.identity))
        self.locale=self.parent/'locales/zh-Hans'
        groups=self.f.f.f.evidence['groups']
        first=deepcopy(groups[0])
        for key in ('sourceUnitIds','targetUtterances','coverage'):first[key]=[v for g in groups for v in g[key]]
        self.f.f.f.evidence['groups']=[first]
        self.group={k:first[k] for k in ('translationGroupId','sourceUnitIds')}
        self.f.f.rule_context['groupPlan'] = [self.group]
        self.f.prepared=strict.prepare(*self.f.f.args,self.group,request_limits=self.f.selected,
                                       rule_preflight=self.f.f.rule_preflight, rule_context=self.f.f.rule_context)
        self.cid='candidate.'+c.canonical_sha256(self.group)
        self.f.root=self.locale/'groups'/c.canonical_sha256(self.group)/'revisions/initial'
        self.network=self.enterContext(patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('network forbidden')))

    def build(self, *, failed=False, repair_steps=0, version=1, review_attempt=1):
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
            from scripts import run_target_language_models as models
            from scripts import target_language_rule_preflight as rule_preflight
            source, anchor = c.decode_json(self.f.f.args[0]), c.decode_json(self.f.f.args[1])
            request = producer.prepare_request(source, anchor, policy, strict_rubric=rubric)
            receipt = rule_preflight.preflight(request, policy, plugin, [self.group])
            self.f.prepared=strict.prepare(*self.f.f.args,self.group,request_limits=self.f.selected,
                                           rule_preflight=receipt, rule_context={'pluginPath': str(plugin), 'groupPlan': [self.group]})
        if repair_steps:
            import json
            from scripts import sermon_strict_controller as controller
            original=self.f.http;reviews=[]
            def semantic_failure(req,timeout,**kw):
                response=original(req,timeout,**kw)
                payload=json.loads(req.data)
                if payload['model']=='gpt-6-sol':
                    reviews.append(1)
                    if len(reviews)<=repair_steps:
                        inp=json.loads(payload['messages'][1]['content'])
                        value=json.loads(response['choices'][0]['message']['content'])
                        value['reviewVerdict']='needs_rework'
                        value['checks'][0]['result']='fail'
                        value['issues']=[dict(issueId='known.fixture.issue.'+str(len(reviews)),reasonCode='meaning_omission' if len(reviews)==1 else 'negation_error',severity='major',
                            sourceUnitIds=[inp['sourceUnitIds'][0]],targetUnitIds=[],evidence='synthetic omission')]
                        response['choices'][0]['message']['content']=json.dumps(value)
                return response
            self.f.provider.executor=semantic_failure
            with self.session():
                result=controller.run_group(self.f.prepared,root=self.f.root.parent.parent,store=self.f.store,
                    job_root=self.parent/'jobs',production_run_id=self.f.provider.config['runId'],
                    graph=[dict(workUnitId=self.f.prepared['workUnitId'],layer=2,targetLocale='zh-Hans',dependsOn=[])],
                    candidate_id=self.cid,api_key='synthetic',caller=self.f.provider,bounds=self.f.bound,
                    usage_resolver=self.f.provider.usage_resolver,created_at='2026-10-01T00:00:00Z')
            self.assertEqual(result['status'],'machine_review_passed',result['reasonCode'])
            self.f.root=Path(result['root'])
        else:
            with self.session():
                self.f.subject.generate(self.f.prepared,self.f.root,self.cid,'initial','synthetic',self.f.provider,
                    bounds=self.f.bound,usage_resolver=self.f.provider.usage_resolver)
                self.f.subject.review(self.f.prepared,self.f.root,self.cid,'initial','synthetic',self.f.provider,
                    bounds=self.f.bound,usage_resolver=self.f.provider.usage_resolver)
        if review_attempt==2:
            with self.session():
                strict.review(self.f.prepared,self.f.root,self.cid,'initial','synthetic',self.f.provider,attempt_number=2)
        materials={}
        for key,data in zip(('englishSource','anchor','policy','rubric'),self.f.f.args):
            path=self.parent/'inputs'/(key+'.json');path.parent.mkdir(exist_ok=True);path.write_bytes(data)
            materials[key]=h.ref(path)
        locale_input=dict(productionRunId=self.f.provider.config['runId'],groups=[self.group],
            inputBytesSha256=[c.bytes_sha256(b) for b in self.f.f.args],requestLimits=self.f.selected,
            **({'rulePreflight':self.f.prepared['rulePreflight'], 'ruleContext':self.f.prepared['ruleContext']} if 'rulePreflight' in self.f.prepared else {}))
        strict.save_once(self.locale/'locale-input.json',locale_input)
        plugin=self.f.f.f.plugin_path;language_root=self.locale/'language-evidence'
        try:
            actual=bridge.compile_candidate(*self.f.f.args,[(self.f.root,review_attempt)],plugin_path=plugin,
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
        self.spec=dict(schemaVersion=h.SPEC if version==1 else h.SPEC_V2,parentPlanRef=h.ref(self.parent/'run-plan.json'),
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
        self.subject.bind_current()
        with self.session(), bounded.bounded_network_only():
            return self.subject.run_group(self.f.prepared,root=self.new_group,candidate_id=self.cid,
                api_key='synthetic',caller=caller or Mock(side_effect=AssertionError('must not dispatch')))

    def assert_parent_unchanged(self):
        self.assertTrue(all(p.read_bytes()==data for p,data in self.snapshots.items()))

    def test_large_linked_history_aggregate_preserves_private_receipt_limit_and_exact_hash(self):
        self.build()
        lineage, _ = c.read_snapshot(self.new/'linked-history.json')
        # Model a long accumulated lineage using complete closed-parent evidence
        # and baseline projections, rather than an unrelated padding string.
        lineage['parentEvidence'] *= 300
        lineage['legacyObservationBaseline']['observations'] *= 300
        path = self.new/'large-linked-history.json'
        raw = c.canonical_bytes(lineage)
        self.assertGreater(len(raw), 1_730_059)
        self.assertLess(len(raw), h.aggregate.MAX_BYTES)
        path.write_bytes(raw)
        reference = h.ref(path)
        parsed, returned = h.check_ref(reference, aggregate_schema=attempts.SCHEMA_V2)
        self.assertEqual(parsed, lineage)
        self.assertEqual(returned, raw)
        with self.assertRaisesRegex(c.ContractError, 'invalid_snapshot_file'):
            h.check_ref(reference)  # Ordinary receipts retain the 256 KiB bound.
        with self.assertRaisesRegex(c.ContractError, 'historical_snapshot_changed'):
            h.check_ref({**reference, 'bytesSha256': '0'*64}, aggregate_schema=attempts.SCHEMA_V2)
        lineage['schemaVersion'] = 'sermon-provider-receipt-v1'
        path.write_bytes(c.canonical_bytes(lineage))
        with self.assertRaisesRegex(c.ContractError, 'historical_aggregate_type_required'):
            h.check_ref(h.ref(path), aggregate_schema=attempts.SCHEMA_V2)
        with self.assertRaisesRegex(c.ContractError, 'historical_aggregate_type_required'):
            h.check_ref(h.ref(path), aggregate_schema='sermon-provider-receipt-v1')
        self.assertEqual(len(self.f.calls), 2)
        self.assert_parent_unchanged();self.network.assert_not_called()

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


class HistoricalFinalRevisionV2Tests(unittest.TestCase):
    setUp=HistoricalLayer2Tests.setUp
    build=HistoricalLayer2Tests.build
    session=HistoricalLayer2Tests.session
    run_group=HistoricalLayer2Tests.run_group
    assert_parent_unchanged=HistoricalLayer2Tests.assert_parent_unchanged
    def test_closed_ordinary_repair_rebind_cold_replay_and_full_plugin_zero_dispatch(self):
        self.build(repair_steps=1,version=2)
        self.assertEqual(len(self.f.calls),4)
        original_repair=strict.load_repair(self.f.root)
        prior=self.subject.inspect(self.f.prepared)
        self.assertEqual(prior['historicalAncestorPaidRequests'],2)
        self.assertEqual(len(prior['archivedRepairRefs']),7)
        result=self.run_group();root=Path(result['root'])
        self.assertEqual(result['revisionId'],original_repair['plan']['toRevisionId'])
        self.assertEqual(result['revisionNumber'],2)
        self.assertEqual(result['status'],'machine_review_passed')
        self.assertEqual(strict.load_repair(root),original_repair)
        proof,_=c.read_snapshot(root/'historical-rebind.json')
        self.assertEqual(proof['schemaVersion'],h.REBIND_V2)
        self.assertEqual(proof['historicalAncestorPaidRequests'],2)
        self.assertEqual(proof['newPaidRequests'],0)
        self.assertFalse((self.new/'budget').exists())
        self.assertFalse((root/'generator.budget-binding.json').exists())
        self.assertFalse((root/'translator-historical-dispatch-proof.json').exists())
        h.validate_rebind(self.f.prepared,root,proof)
        with self.session():
            result2=bridge.compile_candidate(*self.f.f.args,[(root,1)],plugin_path=self.f.f.f.plugin_path,
                expected_plugin_sha256=producer.plugin_implementation_sha256(self.f.f.f.plugin_path))
        self.assertEqual(result2['languageReceipt']['groupReviews'][0]['status'],'pass')
        self.subject=h.HistoricalLayer2Reuse(self.spec)  # Cold inspector, persisted evidence only.
        self.assertEqual(self.run_group(),result)
        self.assertEqual(len(self.f.calls),4)
        self.assert_parent_unchanged();self.network.assert_not_called()

    def test_three_revision_ancestors_bound_no_new_reservations(self):
        self.build(repair_steps=2,version=2)
        prior=self.subject.inspect(self.f.prepared)
        self.assertEqual(prior['parentRevision']['revisionNumber'],3)
        self.assertEqual(prior['historicalAncestorPaidRequests'],4)
        self.assertEqual(len(prior['archivedRepairRefs']),14)
        result=self.run_group()
        self.assertEqual(result['revisionNumber'],3)
        proof,_=c.read_snapshot(Path(result['root'])/'historical-rebind.json')
        h.validate_rebind(self.f.prepared,Path(result['root']),proof)
        self.assertEqual(len(self.f.calls),6)
        self.assertFalse((self.new/'budget').exists());self.assert_parent_unchanged()

    def test_v2_initial_revision_compatibility_and_proof_tamper(self):
        self.build(version=2);result=self.run_group();root=Path(result['root'])
        self.assertEqual(result['revisionId'],'initial')
        proof,_=c.read_snapshot(root/'historical-rebind.json')
        self.assertEqual(proof['archivedRepairRefs'],[])
        self.assertEqual(proof['historicalAncestorPaidRequests'],0)
        for mutation in (lambda v:v.update(archivedRepairRefs=[self.spec['parentPlanRef']]),
            lambda v:v.update(historicalAncestorPaidRequests=2),lambda v:v.update(selectedRevisionId='fake'),
            lambda v:v.update(reviewAttemptNumber=2),lambda v:v.update(newBudgetReservations=1)):
            invalid=deepcopy(proof);mutation(invalid)
            with self.assertRaises(c.ContractError):h.validate_rebind(self.f.prepared,root,invalid)
        self.assertEqual(len(self.f.calls),2);self.assert_parent_unchanged()

    def test_repaired_prompt_ancestor_raw_binding_and_missing_cache_never_fallback(self):
        self.build(repair_steps=1,version=2)
        cold=lambda:h.HistoricalLayer2Reuse(self.spec)
        changed=deepcopy(self.f.prepared);changed['requestLimits']['maxCompletionTokens']-=1
        with self.assertRaises(c.ContractError):cold().inspect(changed)
        prior=cold().inspect(self.f.prepared)
        initial=self.f.root.parent/'initial'
        raw=initial/'reviewer.raw.json';saved=raw.read_bytes();value=c.decode_json(saved)
        value['response']['usage']['prompt_tokens']+=1;raw.write_bytes(c.canonical_bytes(value))
        with self.assertRaises(c.ContractError):cold().inspect(self.f.prepared)
        raw.write_bytes(saved)
        original=Path(prior['archivedRepairRefs'][0]['path']);saved=original.read_bytes()
        value=c.decode_json(saved);value['createdAt']='2026-10-01T00:00:01Z';original.write_bytes(c.canonical_bytes(value))
        with self.assertRaises(c.ContractError):cold().inspect(self.f.prepared)
        original.write_bytes(saved)
        value=dict(schemaVersion='fixture');strict.save_once(self.f.root/'historical-rebind.json',value)
        with self.assertRaises(c.ContractError):cold().inspect(self.f.prepared)
        (self.f.root/'historical-rebind.json').unlink()
        # Removed selected cache must not create a new paid request.
        cache=self.f.root/'generator.json';saved=cache.read_bytes();cache.unlink()
        with self.assertRaises((OSError,c.ContractError)):self.run_group()
        cache.write_bytes(saved)
        self.assertEqual(len(self.f.calls),4);self.assert_parent_unchanged();self.network.assert_not_called()

    def test_v2_closed_parent_and_cold_code_guard_prevent_rebind(self):
        self.build(repair_steps=1,version=2)
        closed=self.parent/'budget'/budget.STORE_ID/'provider-run/closed.json'
        saved=closed.read_bytes();closed.unlink()
        with self.assertRaisesRegex(c.ContractError,'historical_parent_not_closed'):
            h.HistoricalLayer2Reuse(self.spec)
        closed.write_bytes(saved)
        self.subject=h.HistoricalLayer2Reuse(self.spec)
        with patch.object(accounting,'execution_identity',return_value={**self.identity,'gitCommit':'0'*40}):
            with self.assertRaisesRegex(c.ContractError,'historical_current_code_changed'):self.run_group()
        self.assertFalse(self.new_group.exists())
        self.assertEqual(len(self.f.calls),4);self.assert_parent_unchanged();self.network.assert_not_called()

    def test_v2_rejects_actual_language_plugin_repair_origin(self):
        new=self.build(failed=True)
        self.f.f.f.evidence['groups'][0]['targetUtterances'].append('回想')
        store=budget.BudgetStore(self.new/'budget',new['authority'])
        paid=provider.DiagnosticProvider(store,new['providerConfig'],self.f.selected,executor=self.f.http,
            monotonic=lambda:self.f.clock,domain=lambda:'7'*64)
        paid.source_check_payload=Mock(side_effect=self.f.payload)
        result=self.run_group(paid);root=Path(result['root'])
        binding=dict(revisionId=result['revisionId'],reviewAttemptNumber=1,candidateId=self.cid,
            workUnitId=self.f.prepared['workUnitId'],artifacts={})
        with self.assertRaisesRegex(c.ContractError,'historical_ordinary_repair_required'):
            h.inspect_final_origin(self.f.prepared,self.new/'locales/zh-Hans',binding,
                store.root/budget.STORE_ID/'provider-run',new['providerConfig'])
        self.assertEqual(len(self.f.calls),4);self.assert_parent_unchanged();self.network.assert_not_called()

    def test_actual_final_second_review_attempt_selects_exact_suffix_cache(self):
        self.build(version=2,review_attempt=2)
        result=self.run_group();root=Path(result['root'])
        self.assertEqual(result['reviewAttempt'],2)
        self.assertTrue((root/'reviewer-2.raw.json').is_file())
        self.assertFalse((root/'reviewer.json').exists())
        proof,_=c.read_snapshot(root/'historical-rebind.json')
        h.validate_rebind(self.f.prepared,root,proof)
        with self.session():
            actual=bridge.compile_candidate(*self.f.f.args,[(root,2)],plugin_path=self.f.f.f.plugin_path,
                expected_plugin_sha256=producer.plugin_implementation_sha256(self.f.f.f.plugin_path))
        self.assertEqual(actual['languageReceipt']['groupReviews'][0]['status'],'pass')
        self.assertEqual(len(self.f.calls),3)
        self.subject=h.HistoricalLayer2Reuse(self.spec)
        self.assertEqual(self.run_group(),result)
        self.assertEqual(len(self.f.calls),3)
        self.assertFalse((self.new/'budget').exists());self.assert_parent_unchanged()
