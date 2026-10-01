"""Real Source builders/receipts reused by a distinct zero-model fixture attempt."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import sermon_accounting as accounting, sermon_cached_fresh_diagnostic_source as cache
from scripts import sermon_diagnostic_attempts as attempts, sermon_diagnostic_provider as provider
from scripts import sermon_fresh_diagnostic as entry, sermon_log_profile as profile
from scripts import sermon_public_snapshot as public, sermon_review_budget as budget, sermon_review_contracts as c
from scripts import sermon_strict_layer2 as strict
from tests import test_sermon_fresh_diagnostic as source_fixtures


class CachedFreshSourceTests(unittest.TestCase):
    def setUp(self):
        fixture=source_fixtures.FreshSourceTests();fixture.setUp();self.addCleanup(fixture.doCleanups);self.fixture=fixture
        fixture.prepare()
        self.parent=fixture.root;self.parent_plan=fixture.plan
        public.save_once(self.parent/'run-plan.json',self.parent_plan)
        public.save_once(self.parent/'fresh-source-recipe.json',{'files':{key:{'path':str(value),
            'sha256':cache.fresh._sha(value)} for key,value in fixture.recipe.items() if key.endswith('_path')},
            'runMFA':False,'authorizationSha256':c.canonical_sha256(fixture.authorization)})
        attempts.close_parent(self.parent/'run-plan.json',instruction_reference_sha256='f'*64)
        old=attempts.terminal_parent(self.parent_plan)
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()/'next'
        self.auth={'schemaVersion':attempts.AUTH_SCHEMA,'parentPlanSha256':c.canonical_sha256(self.parent_plan),
            'parentSnapshotsSha256':c.canonical_sha256([old]),'instructionReferenceSha256':'f'*64,
            'newMaxRequests':4,'newHardLimitMicrousd':1000000,'newTotalWallSeconds':1200,
            'cumulativeMaxRequests':130,'cumulativeHardLimitMicrousd':50000000}
        self.plan,self.lineage=attempts.prepare_new_attempt(self.parent_plan,new_root=self.root,
            authorization=self.auth,execution_identity=self.parent_plan['executionIdentity'])
        attempts.persist_new_attempt(self.plan,self.lineage,self.auth)
        self.subject=provider.DiagnosticProvider(budget.BudgetStore(self.root/'budget',self.plan['authority']),
            self.plan['providerConfig'],executor=fixture.f.transport)
        # Initialize only the new attempt's actual clock/state, not a request.
        with self.subject._locked():pass
        self.calls=len(fixture.f.transport.observations)
        self.parent_files={str(path):path.read_bytes() for path in self.parent.rglob('*.json')}

    def prepare(self,authorization=None):
        with profile.session(self.root/'logs','cached-source-fixture',work_kind='engineering',evidence_mode='synthetic'):
            return cache.prepare_source(self.plan,self.subject,parent_plan_path=self.parent/'run-plan.json',
                authorization=authorization or self.fixture.authorization)

    def test_actual_parent_source_and_new_context_zero_dispatch_with_immutable_replay(self):
        result=self.prepare()
        self.assertEqual(result['source'],public.read_snapshot(self.parent/'source.json')[0])
        self.assertEqual(result['anchor'],public.read_snapshot(self.parent/'anchor-manifest.json')[0])
        self.assertNotEqual(result['context']['runId'],self.parent_plan['providerConfig']['runId'])
        self.assertEqual(result['context']['storeSha256'],self.subject.store.store_sha256)
        self.assertEqual(result['context']['continuationCodeCommit'],self.plan['executionIdentity']['gitCommit'])
        self.assertFalse(result['source']['translationEligible'])
        self.assertEqual(result['evidence']['historicalSourceProviderCalls'],2)
        for key in ('newASRCalls','newSourceCheckCalls','newMFACalls'):self.assertEqual(result['evidence'][key],0)
        self.assertEqual(result['evidence'],self.prepare()['evidence'])
        cache.validate_evidence(self.plan,self.subject,result['context'],result['evidence'])
        with self.subject._locked() as (_,state):self.assertEqual(state['requests'],{})
        self.assertEqual(len(self.fixture.f.transport.observations),self.calls)
        self.assertEqual(self.parent_files,{path:Path(path).read_bytes() for path in self.parent_files})

    def test_tampered_parent_source_or_current_copy_cannot_be_adopted(self):
        result=self.prepare()
        current=public.read_snapshot(self.root/'source.json')[0];current['review']['humanApproval']=True
        (self.root/'source.json').write_bytes(c.canonical_bytes(current))
        with self.assertRaisesRegex(c.ContractError,'fresh_source_cache_current_source_changed'):
            cache.validate_evidence(self.plan,self.subject,result['context'],result['evidence'])
        (self.root/'source.json').write_bytes(c.canonical_bytes(result['source']))
        aligned=Path(result['source']['transcript']['artifact']['path'])
        aligned.write_bytes(aligned.read_bytes()+b' ')
        with self.assertRaisesRegex(c.ContractError,'fresh_source_cache_alignment_binding_changed'):
            cache.validate_evidence(self.plan,self.subject,result['context'],result['evidence'])

    def test_unknown_parent_or_unclosed_parent_remains_blocked(self):
        folder=self.parent/'budget'/budget.STORE_ID/'provider-run'
        state=public.read_snapshot(folder/'state.json')[0]
        next(iter(state['requests'].values()))['state']='outcome_unknown'
        (folder/'state.json').write_bytes(c.canonical_bytes(state))
        with self.assertRaisesRegex(c.ContractError,'attempt_parent_reconciliation_required'):self.prepare()
        (folder/'closed.json').unlink()
        with self.assertRaisesRegex(c.ContractError,'fresh_source_cache_closed_parent_required'):self.prepare()
        self.assertFalse((self.root/'source.json').exists())

    def test_lineage_and_source_scope_mismatch_do_not_write_outputs(self):
        wrong=deepcopy(self.plan);wrong['providerConfig']['sourceMediaSha256']='0'*64
        with self.assertRaisesRegex(c.ContractError,'fresh_source_cache_runtime_binding_changed'):
            cache._capture(wrong,self.subject,self.parent/'run-plan.json',self.fixture.authorization)
        parent_path=self.parent/'run-plan.json';original=parent_path.read_bytes()
        changed=deepcopy(self.parent_plan);changed['providerConfig']['sourceMediaSha256']='0'*64
        parent_path.write_bytes(c.canonical_bytes(changed))
        with self.assertRaisesRegex(c.ContractError,'fresh_source_cache_source_scope_changed'):self.prepare()
        parent_path.write_bytes(original)
        path=self.root/'linked-history.json';history=public.read_snapshot(path)[0];history['parentEvidence']=[]
        path.write_bytes(c.canonical_bytes(history))
        with self.assertRaisesRegex(c.ContractError,'fresh_source_cache_parent_not_in_lineage'):self.prepare()
        self.assertFalse((self.root/'source.json').exists())

    def test_unapproved_source_stays_pending_and_cannot_gain_production_approval(self):
        with self.assertRaisesRegex(c.ContractError,'fresh_source_cache_test_authorization_required'):
            self.prepare(authorization=dict(self.fixture.authorization,productionEligible=True))
        source=public.read_snapshot(self.parent/'source.json')[0];source['review']['humanApproval']=True
        (self.parent/'source.json').write_bytes(c.canonical_bytes(source))
        with self.assertRaises(c.ContractError):self.prepare()
        self.assertFalse((self.root/'source.json').exists())

    def test_cached_simulation_and_producer_identity_drift_are_rejected(self):
        result=self.prepare()
        auth=public.read_snapshot(self.root/'cached-source-authorization.json')[0]
        auth['humanReviewMode']='approved_for_production'
        (self.root/'cached-source-authorization.json').write_bytes(c.canonical_bytes(auth))
        with self.assertRaisesRegex(c.ContractError,'fresh_source_cache_test_authorization_required'):
            cache.validate_evidence(self.plan,self.subject,result['context'],result['evidence'])
        original=cache._ref
        def producer_drift(path):
            result=original(path)
            return dict(result,bytesSha256='0'*64) if Path(path).name=='mfa_alignment.py' else result
        with patch.object(cache,'_ref',side_effect=producer_drift):
            with self.assertRaisesRegex(c.ContractError,'fresh_source_cache_producer_code_changed'):
                cache._capture(self.plan,self.subject,self.parent/'run-plan.json',self.fixture.authorization)
        dirty=deepcopy(self.plan);dirty['executionIdentity']['trackedWorkingTreeDirty']=True
        with self.assertRaisesRegex(c.ContractError,'fresh_source_cache_code_binding_changed'):
            cache._capture(dirty,self.subject,self.parent/'run-plan.json',self.fixture.authorization)
        with self.assertRaisesRegex(c.ContractError,'fresh_source_cache_fixed_provider_required'):
            cache._capture(self.plan,object(),self.parent/'run-plan.json',self.fixture.authorization)

    def test_fixed_session_cached_source_consumes_ready_source_for_new_strict_inputs(self):
        identity=self.plan['executionIdentity'];transport=self.fixture.f.transport
        public.save_once(self.root/'offline-business-scope.json',{'schemaVersion':'sermon-offline-business-scope-v1',
            'fixtureId':transport.fixture_id,'providerConfigSha256':c.canonical_sha256(self.subject.config),
            'storeSha256':self.subject.store.store_sha256,'mode':'offline_fixture','productionEligible':False})
        with patch.object(accounting,'execution_identity',return_value=identity):
            session=entry.FreshDiagnosticSession(self.plan,offline_transport=transport)
            with profile.session(self.root/'session-logs','cached-source-entry-fixture',work_kind='engineering',evidence_mode='synthetic'):
                prepared=session.prepare_cached_source(self.parent/'run-plan.json',self.fixture.authorization)
                draft=self.root/'draft-policy.json';rubric=self.root/'draft-rubric.json'
                public.save_once(draft,self.fixture.f.policy);public.save_once(rubric,self.fixture.f.rubric)
                # An inert fixture plugin belongs to this run's strict scope.
                plugin=self.root/'plugin.py';plugin.write_bytes(Path(self.fixture.f.locale_specs['zh-Hans']['pluginPath']).read_bytes())
                specs=entry.freeze_locale_inputs(session,{'zh-Hans':{'policy':str(draft),'rubric':str(rubric),'pluginPath':str(plugin)}})
                self.assertEqual(prepared['evidence'],session.inspect_source()['sourceEvidence'])
                policy=public.read_snapshot(specs['zh-Hans']['policy'])[0]
                self.assertEqual(policy['sourceScope']['englishSourcePackageJsonSha256'],prepared['context']['sourceCanonicalSha256'])
        with self.subject._locked() as (_,state):self.assertEqual(state['requests'],{})
        self.assertEqual(len(transport.observations),self.calls)

    def test_unified_entry_dev_builder_failure_keeps_safe_terminal_receipt_and_reraises(self):
        from types import SimpleNamespace
        from tests.test_sermon_diagnostic_prefect_flow import config_fixture
        identity=self.plan['executionIdentity'];transport=self.fixture.f.transport
        public.save_once(self.root/'offline-business-scope.json',{'schemaVersion':'sermon-offline-business-scope-v1',
            'fixtureId':transport.fixture_id,'providerConfigSha256':c.canonical_sha256(self.subject.config),
            'storeSha256':self.subject.store.store_sha256,'mode':'offline_fixture','productionEligible':False})
        draft=self.root/'draft-policy.json';rubric=self.root/'draft-rubric.json'
        public.save_once(draft,self.fixture.f.policy);public.save_once(rubric,self.fixture.f.rubric)
        plugin=self.root/'plugin.py';plugin.write_bytes(Path(self.fixture.f.locale_specs['zh-Hans']['pluginPath']).read_bytes())
        drafts={'zh-Hans':{'policy':str(draft),'rubric':str(rubric),'pluginPath':str(plugin)}}
        config=config_fixture(self.root/'inert-preview-contract',locales=('zh-Hans',))
        previews={loc:lane['previewSpec'] for loc,lane in config['locales'].items()}
        # This test exercises post-traversal Dev failure, not translation/TTS.
        observation={'readyForDownstream':False,'completionSpans':[]}
        dag=SimpleNamespace(nodes=[('delivery.readonly','delivery',None,())],
            results={'delivery.readonly':observation},freeze=lambda:None,execute=lambda _:observation)
        baseline=self.root/'private-baseline-path';baseline.mkdir();(baseline/'firebase.json').write_text('{}')
        with patch.object(accounting,'execution_identity',return_value=identity),patch.object(entry.flow,'DiagnosticDAG',return_value=dag):
            with self.assertRaisesRegex(c.ContractError,'^dev_snapshot_target_invalid$'):
                entry.run_fresh_diagnostic(self.plan,key=None,execute=False,source_recipe=None,
                    source_cache_parent_plan_path=self.parent/'run-plan.json',authorization=self.fixture.authorization,
                    locale_drafts=drafts,preview_specs=previews,offline_transport=transport,
                    dev_snapshot={'baseline':str(baseline),'out':str(self.root/'dev-candidate'),'page_id':'fixture'})
        files=list((self.root/'fresh-diagnostic-failures').glob('*.json'));self.assertEqual(len(files),1)
        failed,data=public.read_snapshot(files[0])
        self.assertEqual(failed['status'],'failed');self.assertEqual(failed['reasonCode'],'dev_snapshot_target_invalid')
        self.assertEqual(failed['errorType'],'ContractError')
        self.assertNotIn(b'private-baseline-path',data)
        last=next((self.root/'fresh-diagnostic-results').glob('*.json'));result,result_bytes=public.read_snapshot(last)
        self.assertEqual(failed['lastCompletedResultRef']['canonicalJsonSha256'],c.canonical_sha256(result))
        self.assertEqual(failed['lastCompletedResultRef']['bytesSha256'],c.bytes_sha256(result_bytes))
        self.assertFalse(failed['productionEligible']);self.assertEqual(failed['humanAcceptance'],'pending')
        with self.subject._locked() as (_,state):self.assertEqual(state['requests'],{})
        self.assertEqual(len(transport.observations),self.calls)
        events,_=accounting.read_events(self.root/'fresh-diagnostic-logs')
        self.assertTrue(any(row['event']=='run_finished' and row['status']=='failed' for row in events))
        self.assertEqual(self.parent_files,{path:Path(path).read_bytes() for path in self.parent_files})


class FreshPreviewPreflightTests(unittest.TestCase):
    def test_fixture_scope_and_future_source_paths_need_no_native_runtime(self):
        from tests.test_sermon_diagnostic_prefect_flow import config_fixture
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);config=config_fixture(root,locales=('zh-Hans',))
            previews={locale:lane['previewSpec'] for locale,lane in config['locales'].items()}
            previews['zh-Hans']['paths']['source']=str(root/'future-source.json')
            from scripts import sermon_native_preview_runtime as native
            with patch.object(native,'validate',side_effect=AssertionError('fixture must not inspect native')):
                entry._preflight_preview_specs(previews,{'zh-Hans':{}},offline_fixture=True)
                previews['zh-Hans']['runtime_manifest_path']=str(root/'untrusted-runtime.json')
                with self.assertRaisesRegex(c.ContractError,'fresh_diagnostic_fixture_cannot_claim_native_runtime'):
                    entry._preflight_preview_specs(previews,{'zh-Hans':{}},offline_fixture=True)

    def test_invalid_live_runtime_contract_rejected_before_provider_or_paid_source(self):
        from tests.test_sermon_diagnostic_prefect_flow import config_fixture
        with tempfile.TemporaryDirectory() as directory:
            config=config_fixture(Path(directory),locales=('zh-Hans',))
            previews={locale:lane['previewSpec'] for locale,lane in config['locales'].items()}
            previews['zh-Hans']['execute']=True
            with patch.object(entry,'FreshDiagnosticSession',side_effect=AssertionError('provider must not initialize')):
                with self.assertRaisesRegex(c.ContractError,'fresh_diagnostic_preview_runtime_manifest_required'):
                    entry.run_fresh_diagnostic({},key='unused',execute=True,source_recipe={},authorization={},
                        locale_drafts={'zh-Hans':{}},preview_specs=previews)
            previews['zh-Hans']['runtime_manifest_path']=str(Path(directory)/'missing-runtime.json')
            with patch.object(entry,'FreshDiagnosticSession',side_effect=AssertionError('provider must not initialize')):
                with self.assertRaisesRegex(c.ContractError,'fresh_diagnostic_preview_checkpoint_manifest_required'):
                    entry.run_fresh_diagnostic({},key='unused',execute=True,source_recipe={},authorization={},
                        locale_drafts={'zh-Hans':{}},preview_specs=previews)
            previews['zh-Hans'].update(checkpoint_manifest_path=str(Path(directory)/'missing-checkpoint.json'),
                checkpoint_stage_declaration_path=str(Path(directory)/'missing-declaration.json'))
            with patch.object(entry,'FreshDiagnosticSession',side_effect=AssertionError('provider must not initialize')):
                with self.assertRaises((ValueError,OSError)):
                    entry.run_fresh_diagnostic({},key='unused',execute=True,source_recipe={},authorization={},
                        locale_drafts={'zh-Hans':{}},preview_specs=previews)

    def test_real_checkpoint_tree_and_declaration_checked_before_provider_initialization(self):
        from tests.test_sermon_preview_checkpoint_manifest import CheckpointManifestTests
        from tests.test_sermon_diagnostic_prefect_flow import config_fixture
        from scripts import sermon_native_preview_runtime as native
        fixture=CheckpointManifestTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        bindings={'previewCheckpointManifest':fixture.binding['checkpointManifest']['fileBytesSha256'],
                  'previewCheckpointTree':fixture.binding['treeSha256']}
        run,declaration,_=fixture.declaration(bindings)
        plan=c.read_snapshot(run/'run-plan.json')[0]
        config=config_fixture(run,locales=('zh-Hans',))
        previews={locale:lane['previewSpec'] for locale,lane in config['locales'].items()}
        previews['zh-Hans'].update(execute=True,runtime_manifest_path=str(run/'runtime.json'),
            checkpoint_manifest_path=str(fixture.path),checkpoint_stage_declaration_path=str(declaration))
        before={str(path):path.read_bytes() for path in fixture.root.rglob('*') if path.is_file()}
        # Only the independent native Python prefix seam is mocked. Complete
        # checkpoint and frozen declaration validation run with real bytes.
        with patch.object(native,'validate',return_value={'fixture':'native-prefix-only'}):
            entry._preflight_preview_specs(previews,{'zh-Hans':{}},offline_fixture=False,plan=plan)
            self.assertEqual(before,{str(path):path.read_bytes() for path in fixture.root.rglob('*') if path.is_file()})
            with self.assertRaisesRegex(c.ContractError,'fresh_diagnostic_fixture_cannot_claim_native_runtime'):
                previews['zh-Hans']['execute']=False
                entry._preflight_preview_specs(previews,{'zh-Hans':{}},offline_fixture=True,plan=plan)
            previews['zh-Hans']['execute']=True
            (fixture.checkpoint/'speech_tokenizer/model.safetensors').write_bytes(b'changed auxiliary weights')
            with patch.object(entry,'FreshDiagnosticSession',side_effect=AssertionError('provider must not initialize')):
                with self.assertRaisesRegex(c.ContractError,'checkpoint_tree_changed'):
                    entry.run_fresh_diagnostic(plan,key='unused',execute=True,source_recipe={},authorization={},
                        locale_drafts={'zh-Hans':{}},preview_specs=previews)
