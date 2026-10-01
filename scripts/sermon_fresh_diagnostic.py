"""Fixed fresh diagnostic entry: real Source -> strict text -> preview -> inspect.

Only an explicit execute plus injected credential enables provider calls. This
entry creates no formal Audio/Release Package and publishes nothing. A reviewed
Dev snapshot is a separate output/action. The original store/clock are preserved
on replay; changed code/source/policy requires its proper new attempt identity.
"""
from copy import deepcopy
from pathlib import Path
import importlib

from scripts import run_bounded_diagnostic as bounded
from scripts import sermon_accounting as accounting
from scripts import sermon_log_profile as profile
from scripts import sermon_review_contracts as c
from scripts import sermon_strict_layer2 as strict
from scripts import sermon_diagnostic_context as diagnostic
from scripts import sermon_bounded_business_callbacks as offline
from scripts import sermon_diagnostic_dag_session as sessions
from scripts import sermon_diagnostic_prefect_flow as flow
from scripts import sermon_fresh_diagnostic_source as source_adapter
from scripts import target_language_policy as policy_builder
from scripts import produce_target_language_candidate as producer
from scripts import run_target_language_models as models
from scripts.sermon_release_workflow import _safe_path


def preload_execution_modules(plugin_paths=()):
    """Call BEFORE freezing a fresh plan; imports only fixed local stage code."""
    for name in ('sermon_diagnostic_delivery_preflight','sermon_dev_diagnostic_snapshot',
                 'sermon_native_preview_runtime','sermon_strict_candidate_bridge','sermon_strict_controller',
                 'sermon_strict_budget_adapter','sermon_strict_locale','prepare_target_language_speech_job',
                 'render_formal_target_language_speech','render_multilingual_voice_demos',
                 'validate_target_language_audio_unit','sermon_local_model_observation'):
        importlib.import_module('scripts.'+name)
    repository=Path(__file__).resolve().parents[1]
    for path in plugin_paths:
        path=_safe_path(Path(path))
        c.require(path.is_relative_to(repository/'scripts/language_review_plugins') and path.suffix=='.py',
                  'fresh_diagnostic_plugin_scope_invalid')
        importlib.import_module('.'.join(path.relative_to(repository).with_suffix('').parts))
    return accounting.execution_identity()


class FreshDiagnosticSession(sessions.DiagnosticSession):
    """Trusted fresh source adapter; not a generic user callback or continuation."""
    def __init__(self, plan, *, key=None, execute=False, request_limits=None, offline_transport=None):
        fixture=offline_transport is not None
        c.require((not fixture and execute is True and type(key) is str and 0<len(key)<=1024 and key.isascii()) or
            (fixture and type(offline_transport) is offline.OfflineHTTPTransport and key is None and execute is False),
                  'fresh_diagnostic_explicit_execute_required')
        self.root,self.subject=bounded.prepare_plan(plan)
        c.require(fixture or not (self.root/'offline-business-scope.json').exists(), 'diagnostic_dag_fixture_cannot_become_live')
        if request_limits is not None:
            from scripts import sermon_diagnostic_provider as provider
            self.subject=provider.DiagnosticProvider(self.subject.store,self.subject.config,request_limits=request_limits)
        if fixture:
            self.subject.executor=offline_transport
            marker={'schemaVersion':'sermon-offline-business-scope-v1','fixtureId':offline_transport.fixture_id,
                'providerConfigSha256':c.canonical_sha256(self.subject.config),'storeSha256':self.subject.store.store_sha256,
                'mode':'offline_fixture','productionEligible':False}
            c.require(c.read_snapshot(self.root/'offline-business-scope.json')[0]==marker,'diagnostic_dag_offline_scope_required')
        strict.save_once(self.root/'run-plan.json',plan)
        strict.save_once(self.root/'fresh-request-limits.json',self.subject.limits)
        self.plan=deepcopy(plan); self.offline_fixture=fixture; self.evidence_mode='synthetic' if fixture else 'current_execution'
        self.transport=self.subject.executor
        self.runner=bounded.BoundedRun(self.subject,offline.OFFLINE_KEY if fixture else key,self.root,source_clip=plan['sourceClipPath'])
        self._locale_results={}; self._locale_specs={}; self.context=None; self.binding=None

    def _check(self):
        active=profile.current()
        c.require(active is not None and active['evidenceMode']==self.evidence_mode,'diagnostic_dag_accounting_mode_changed')
        identity=accounting._identity.get()
        c.require(identity and self.root in self._path(identity[0]).parents,'diagnostic_dag_accounting_outside_scope')
        current=accounting.execution_identity(); frozen=self.plan['executionIdentity']
        c.require(current==frozen,'diagnostic_continuation_code_changed')
        c.require(c.read_snapshot(self.root/'run-plan.json')[0]==self.plan and self.subject.executor is self.transport
            and self.subject.config==self.plan['providerConfig'] and
            c.read_snapshot(self.root/'fresh-request-limits.json')[0]==self.subject.limits,'diagnostic_dag_binding_changed')
        bounded.verify_source_clip(self.plan['sourceClipPath'],self.subject.config['sourceClipSha256'])
        recipe_path=self.root/'fresh-source-recipe.json'
        if recipe_path.exists():
            frozen_recipe=c.read_snapshot(recipe_path)[0]
            c.require(all(source_adapter._sha(row['path'])==row['sha256'] for row in frozen_recipe['files'].values()),
                      'fresh_source_recipe_changed')
        with self.subject._locked() as (_,state):
            self.subject._remaining(state)
            c.require(all(row['state'] in ('returned','rejected') for row in state['requests'].values()),
                      'diagnostic_prior_outcome_requires_reconciliation')
        if self.context is not None:
            source=c.read_snapshot(self.root/'source.json')[0]; anchor=c.read_snapshot(self.root/'anchor-manifest.json')[0]
            diagnostic.validate_source(source,anchor,self.context)
            c.require(c.read_snapshot(self.root/'fresh-source-evidence.json')[0]==self.binding['sourceEvidence'],
                      'fresh_source_evidence_changed')
            for operation,model,key in (('transcription.initial','gpt-transcribe','asr'),('source.initial','gpt-6-astra','sourceCheck')):
                _,reference=source_adapter.returned_receipt(self.root,self.subject.config,operation,model)
                c.require(reference==self.binding['sourceEvidence'][key],'fresh_source_receipt_binding_changed')
        return self.binding['sourceEvidence'] if self.binding else None

    def prepare_source(self, recipe, authorization):
        self._check()
        c.require(type(recipe) is dict and set(recipe) <= {'prior_plan_path','prior_source_path','prior_aligned_path',
            'prior_summary_path','audio_path','run_mfa','local_runtime_path'} and {'prior_plan_path','prior_source_path',
            'prior_aligned_path','prior_summary_path','audio_path'} <= set(recipe),'fresh_source_recipe_invalid')
        file_refs={key:{'path':str(_safe_path(Path(value))),'sha256':source_adapter._sha(value)}
                   for key,value in recipe.items() if key.endswith('_path') and value is not None}
        strict.save_once(self.root/'fresh-source-recipe.json',{'files':file_refs,'runMFA':recipe.get('run_mfa',False),
            'authorizationSha256':c.canonical_sha256(authorization)})
        # Genuine provider callbacks own request receipts, stop guards and cache.
        with accounting.stage('diagnostic.fresh_asr',depends_on=[],executor_type='production_model') as asr_span:
            self.runner.transcribe(_safe_path(Path(recipe['audio_path'])).read_bytes())
        with accounting.stage('diagnostic.fresh_source_check',depends_on=[asr_span],executor_type='production_model') as review_span:
            self.runner.source_check(operation_id='source.initial')
        prepared=source_adapter.prepare_source(self.plan,self.subject,**recipe,authorization=authorization,depends_on=[review_span])
        self.context=prepared['context']
        self.binding={'schemaVersion':'sermon-fresh-diagnostic-session-v1','originalPlanSha256':c.canonical_sha256(self.plan),
            'diagnosticContextSha256':c.canonical_sha256(self.context),'sourceEvidence':prepared['evidence'],
            'runId':self.context['runId'],'storeSha256':self.subject.store.store_sha256,'evidenceMode':self.evidence_mode,
            'humanAcceptance':'pending','productionEligible':False,'implementationSha256':c.bytes_sha256(Path(__file__).read_bytes())}
        self.source_spans=prepared['completionSpans']
        self._check()
        return prepared

    def inspect_source(self):
        evidence=self._check()
        c.require(evidence is not None,'fresh_source_preparation_required')
        return {'status':'existing_evidence_validated','sourceEvidence':evidence,'humanAcceptance':'pending',
                'newASRCalls':0,'newSourceCheckCalls':0,'productionEligible':False}


def freeze_locale_inputs(session, locale_drafts):
    """Use ordinary policy drafts; no private prompt/schema/term workarounds."""
    session._check(); root=session.root
    source=c.read_snapshot(root/'source.json')[0]; anchor=c.read_snapshot(root/'anchor-manifest.json')[0]
    groups=[{'translationGroupId':f'fresh-g{i//3+1:03d}','sourceUnitIds':[x['sourceUnitId'] for x in anchor['sourceUnits'][i:i+3]]}
            for i in range(0,len(anchor['sourceUnits']),3)]
    specs={}
    c.require(type(locale_drafts) is dict and bool(locale_drafts) and set(locale_drafts)<=flow.LOCALES,
              'fresh_diagnostic_locales_invalid')
    for locale,files in locale_drafts.items():
        c.require(type(files) is dict and set(files)=={'policy','rubric','pluginPath'},'fresh_diagnostic_policy_inputs_invalid')
        draft=c.read_snapshot(_safe_path(files['policy']))[0]; rubric=c.read_snapshot(_safe_path(files['rubric']))[0]
        plugin=_safe_path(files['pluginPath']); plugin_sha=producer.plugin_implementation_sha256(plugin)
        c.require(draft['targetLocale']==locale,'fresh_diagnostic_policy_locale_changed')
        draft.pop('componentSha256',None)
        draft['sourceScope']['englishSourcePackageJsonSha256']=c.canonical_sha256(source)
        draft['sourceScope']['anchorManifestSha256']=c.canonical_sha256(anchor)
        draft['languageReview']['pluginImplementationSha256']=plugin_sha
        policy=policy_builder.freeze_strict_policy(draft,rubric)
        request=producer.prepare_request(source,anchor,policy,strict_rubric=rubric,diagnostic_context=session.context)
        prepared=[strict.prepare(*[c.canonical_bytes(x) for x in (source,anchor,policy,rubric)],group,
                  request_limits=session.subject.limits,diagnostic_context=session.context)
                  for group in models.group_plan(request,anchor,groups)]
        session.subject.preflight_locale(prepared); models.require_plugin_identity(plugin,plugin_sha)
        # Exercise the full checked-in loader/check schema before paid L2 work.
        # The synthetic text is an explicit loader probe, never an admitted
        # candidate or claimed semantic/language pass.
        probe={**deepcopy(request),'groups':[{**groups[0],'targetUtterances':[
            {'zh-Hans':'预检','ko':'사전 점검','es':'Prueba'}[locale]]}]}
        loaded=producer.run_language_plugin(source,anchor,policy,request,probe,plugin,plugin_sha,
            strict_rubric=rubric,diagnostic_context=session.context)
        c.require(loaded['pluginImplementationSha256']==plugin_sha,'fresh_diagnostic_plugin_loader_changed')
        folder=root/'fresh-inputs'/locale
        strict.save_once(folder/'plugin-loader-preflight.json',{'schemaVersion':'sermon-diagnostic-plugin-loader-preflight-v1',
            'evidenceMode':'synthetic_contract_probe','actualTranslationAcceptance':False,'pluginId':loaded['pluginId'],
            'pluginVersion':loaded['pluginVersion'],'pluginImplementationSha256':plugin_sha})
        strict.save_once(folder/'policy.json',policy); strict.save_once(folder/'rubric.json',rubric)
        graph=[{'workUnitId':'l1.fresh.source','layer':1,'targetLocale':None,'dependsOn':[]}]+[
            {'workUnitId':x['workUnitId'],'layer':2,'targetLocale':locale,'dependsOn':['l1.fresh.source']} for x in prepared]
        spec={'source':str(root/'source.json'),'anchor':str(root/'anchor-manifest.json'),'policy':str(folder/'policy.json'),
              'rubric':str(folder/'rubric.json'),'graph':graph,'pluginPath':str(plugin),'pluginSha256':plugin_sha,'groupPlan':groups}
        strict.save_once(folder/'spec.json',spec); specs[locale]=spec
    return specs


def run_fresh_diagnostic(plan, *, key, execute=False, source_recipe, authorization, locale_drafts,
                         preview_specs, request_limits=None, dev_snapshot=None, offline_transport=None,
                         execute_publish=False, publication_approval_sha256=None):
    """Unified fixed sequential DAG. Business ledgers decide all replay/retries.

    Produces preview/read-only delivery evidence only. Does not call Prefect's
    cache, grant human approval, publish Hosting, or relabel preview as release.
    """
    c.require(type(execute_publish) is bool and (not execute_publish or (dev_snapshot is not None
        and offline_transport is None)), 'fresh_dev_publication_scope_invalid')
    if execute_publish:
        import re
        c.require(type(publication_approval_sha256) is str and re.fullmatch('[a-f0-9]{64}',publication_approval_sha256),
                  'fresh_dev_publication_scope_invalid')
    session=FreshDiagnosticSession(plan,key=key,execute=execute,request_limits=request_limits,offline_transport=offline_transport)
    with profile.session(session.root/'fresh-diagnostic-logs','fresh_diagnostic',work_kind='production',
                         evidence_mode=session.evidence_mode,production_run_id=session.subject.config['runId']):
        try:
            prepared=session.prepare_source(source_recipe,authorization)
        except Exception as exc:
            # Safe typed code only; legacy builder messages may contain paths.
            import re
            reason=str(exc) if type(exc) is c.ContractError and re.fullmatch('fresh_[a-z0-9_]{1,100}',str(exc)) else 'source_preparation_not_confirmed'
            failed={'schemaVersion':'sermon-fresh-diagnostic-source-failure-v1','status':'blocked',
                'reasonCode':reason,'errorType':type(exc).__name__,'productionEligible':False,'humanAcceptance':'pending'}
            strict.save_once(session.root/'fresh-source-failures'/(c.canonical_sha256(failed)+'.json'),failed)
            return failed
        specs=freeze_locale_inputs(session,locale_drafts)
        c.require(set(preview_specs)==set(specs),'fresh_diagnostic_preview_locales_changed')
        config={'schemaVersion':flow.SCHEMA,'locales':{loc:{'localeSpec':spec,'previewSpec':deepcopy(preview_specs[loc])}
                                                    for loc,spec in specs.items()}}
        for locale,lane in config['locales'].items():
            for key in ('source','anchor','policy'):
                lane['previewSpec']['paths'][key]=lane['localeSpec'][key]
            lane['previewSpec']['strict_rubric_path']=lane['localeSpec']['rubric']
        dag=flow.DiagnosticDAG(session,config); dag.freeze()
        dag.initial_source_spans=prepared['completionSpans']
        results={node[0]:dag.execute(node[0]) for node in dag.nodes}
        result={'schemaVersion':'sermon-fresh-diagnostic-result-v1','nodes':results,
            'status':'diagnostic_traversal_complete' if results['delivery.readonly']['readyForDownstream'] else 'incomplete',
            'productionEligible':False,'humanAcceptance':'pending','publicationAuthorized':False,'formalAudioPackageCreated':False,
            'formalReleasePackageCreated':False,'planSha256':c.canonical_sha256(plan),'sourceEvidenceSha256':c.canonical_sha256(prepared['evidence'])}
        strict.save_once(session.root/'fresh-diagnostic-results'/(c.canonical_sha256(result)+'.json'),result)
        if dev_snapshot is not None:
            from scripts import sermon_dev_diagnostic_snapshot as dev
            c.require(type(dev_snapshot) is dict and set(dev_snapshot)=={'baseline','out','page_id'},'fresh_dev_snapshot_inputs_invalid')
            previews={loc:dag.results[f'preview.{loc}'] for loc in specs if f'preview.{loc}' in dag.results}
            leaves=[span for observation in results.values() for span in observation['completionSpans']]
            stages={'schemaVersion':'sermon-dev-diagnostic-stage-results-v1','runId':session.subject.config['runId'],
                'diagnosticContextSha256':c.canonical_sha256(session.context),'nodes':results}
            built=dev.build_snapshot(session,**dev_snapshot,preview_receipts=previews,stage_results=stages,depends_on=leaves)
            result={**result,'devSnapshot':built,'publicationStatus':'not_deployed'}
            strict.save_once(session.root/'fresh-diagnostic-results'/(c.canonical_sha256(result)+'.json'),result)
            if execute_publish:
                publication={'schemaVersion':'sermon-dev-diagnostic-publication-authorization-v1',
                    'manifestSha256':c.canonical_sha256(built['manifest']),'project':dev.PROJECT,'site':dev.PROJECT,
                    'origin':dev.ORIGIN,'publicationScope':'diagnostic_preview_only','productionEligible':False,
                    'approvalSha256':publication_approval_sha256}
                delivery=dev.publish_and_verify(built,plan=plan,authorization=publication,execute=True,
                    depends_on=built['completionSpans'])
                result={**result,'publicationStatus':delivery['status'],'publicationReceipt':delivery}
                strict.save_once(session.root/'fresh-diagnostic-results'/(c.canonical_sha256(result)+'.json'),result)
        return result
