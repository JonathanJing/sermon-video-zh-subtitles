"""Fixed fresh diagnostic entry: real Source -> strict text -> preview -> inspect.

Only an explicit execute plus injected credential enables provider calls. This
entry creates no formal Audio/Release Package. A reviewed Dev diagnostic snapshot
can be published only by its explicit publication option and frozen target. The original store/clock are preserved
on replay; changed code/source/policy requires its proper new attempt identity.
"""
from copy import deepcopy
from contextlib import contextmanager
from pathlib import Path
import importlib

from scripts import run_bounded_diagnostic as bounded
from scripts import sermon_accounting as accounting
from scripts import sermon_completion as completion
from scripts import sermon_mfa_identity as mfa_identity
from scripts import sermon_log_profile as profile
from scripts import sermon_review_contracts as c
from scripts import sermon_public_snapshot as public
from scripts import sermon_strict_layer2 as strict
from scripts import sermon_diagnostic_context as diagnostic
from scripts import sermon_bounded_business_callbacks as offline
from scripts import sermon_diagnostic_dag_session as sessions
from scripts import sermon_diagnostic_prefect_flow as flow
from scripts import sermon_fresh_diagnostic_source as source_adapter
from scripts import sermon_cached_fresh_diagnostic_source as cached_source
from scripts import target_language_policy as policy_builder
from scripts import produce_target_language_candidate as producer
from scripts import run_target_language_models as models
from scripts.sermon_release_workflow import _safe_path

TERMINAL_REASONS=frozenset({'diagnostic_continuation_code_changed','diagnostic_dag_binding_changed',
    'diagnostic_prior_outcome_requires_reconciliation','diagnostic_flow_frozen_inputs_changed',
    'diagnostic_dag_source_or_clock_changed','fresh_dev_snapshot_inputs_invalid',
    'fresh_dev_publication_scope_invalid','fresh_diagnostic_preview_locales_changed',
    'strict_bridge_plugin_rejected','dev_snapshot_target_invalid','dev_snapshot_output_scope_changed',
    'dev_diagnostic_page_invalid','dev_machine_candidate_changed','dev_preview_candidate_changed',
    'dev_preview_without_candidate','dev_preview_unit_changed','dev_preview_audio_path_invalid',
    'dev_preview_duration_changed','dev_preview_mode_changed','dev_preview_track_short',
    'dev_snapshot_formal_catalog_changed','dev_stage_results_binding_changed','dev_stage_results_invalid',
    'dev_http_asset_changed','dev_http_range_changed','dev_publication_outcome_requires_reconciliation',
    'dev_publication_replay_changed','dev_publication_requires_reconciliation','dev_publish_context_changed',
    'dev_publish_explicit_authorization_required','dev_publish_fixture_scope_forbidden',
    'dev_publish_original_deadline_reached','dev_publish_provider_outcome_unknown','dev_publish_run_changed',
    'dev_publish_snapshot_changed','dev_publish_target_changed','dev_publish_timeout_invalid',
    'fresh_historical_layer2_inputs_changed','fresh_historical_layer2_locales_invalid',
    'fresh_historical_layer2_already_frozen','fresh_historical_layer2_type_invalid',
    'fresh_historical_layer2_new_plan_changed','fresh_historical_native_specs_invalid',
    'fresh_historical_native_ref_changed','fresh_historical_native_parent_changed',
    'fresh_historical_native_locales_invalid','fresh_historical_native_already_frozen',
    'fresh_historical_native_inputs_changed','fresh_historical_native_source_changed'})


@contextmanager
def _terminal_failure_receipt(session):
    """Persist safe post-Source failures and rethrow the original exception."""
    try:
        yield
    except accounting.AccountingWriteError:
        raise
    except Exception as exc:
        if getattr(exc,'sermon_logging_failed',False):
            raise
        # Exception messages may include source text, paths or provider bodies.
        reason=str(exc) if type(exc) is c.ContractError and str(exc) in TERMINAL_REASONS else 'unclassified_stage_failure'
        failed={'schemaVersion':'sermon-fresh-diagnostic-terminal-failure-v1','status':'failed',
            'reasonCode':reason,'errorType':type(exc).__name__,
            'runId':session.subject.config['runId'],'planSha256':c.canonical_sha256(session.plan),
            'diagnosticContextSha256':c.canonical_sha256(session.context),
            'sourceEvidenceSha256':c.canonical_sha256(session.binding['sourceEvidence']),
            'lastCompletedResultRef':deepcopy(getattr(session,'_last_completed_result_ref',None)),
            'productionEligible':False,'humanAcceptance':'pending','executionAuthority':'none'}
        try:
            strict.save_once(session.root/'fresh-diagnostic-failures'/(c.canonical_sha256(failed)+'.json'),failed)
        except Exception:
            # Preserve the business exception; do not claim the sidecar exists.
            exc.sermon_failure_receipt_persistence_failed=True
        raise


def _save_result(session,result):
    path=session.root/'fresh-diagnostic-results'/(c.canonical_sha256(result)+'.json')
    data=strict.save_once(path,result)
    session._last_completed_result_ref={'artifactId':'fresh-diagnostic-result',
        'canonicalJsonSha256':c.canonical_sha256(result),'bytesSha256':c.bytes_sha256(data)}


def preload_execution_modules(plugin_paths=()):
    """Call BEFORE freezing a fresh plan; imports only fixed local stage code."""
    for name in ('sermon_workflow_evidence','sermon_diagnostic_delivery_preflight','sermon_dev_diagnostic_snapshot',
                 'sermon_native_preview_runtime','sermon_strict_candidate_bridge','sermon_strict_controller',
                 'sermon_strict_budget_adapter','sermon_strict_locale','prepare_target_language_speech_job',
                 'render_formal_target_language_speech','render_multilingual_voice_demos',
                 'validate_target_language_audio_unit','sermon_local_model_observation',
                 'sermon_model_call_report','sermon_model_call_observation','sermon_openai_runtime',
                 'sermon_trace_artifacts','sermon_review_diagnostics','sermon_preview_checkpoint_manifest',
                 'sermon_fresh_source_evidence','sermon_historical_layer2','sermon_historical_native_seed','sermon_historical_identity','sermon_source_producer_compatibility','sermon_source_failure'):
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
        self._cached_source=False
        self._historical_reuse={}; self._historical_specification=None
        self._historical_native_seeds={}; self._historical_native_specification=None

    def _check(self):
        active=profile.current()
        c.require(active is not None and active['evidenceMode']==self.evidence_mode,'diagnostic_dag_accounting_mode_changed')
        identity=accounting._identity.get()
        c.require(identity and self.root in self._path(identity[0]).parents,'diagnostic_dag_accounting_outside_scope')
        current=accounting.execution_identity(); frozen=self.plan['executionIdentity']
        c.require(current==frozen,'diagnostic_continuation_code_changed')
        self._check_historical_inputs()
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
            if self._cached_source:
                cached_source.validate_evidence(self.plan,self.subject,self.context,self.binding['sourceEvidence'])
            else:
                # Use the same read-only identity gate at every downstream
                # boundary, not only delivery. A valid completion proves what
                # finished then; it cannot certify MFA artifacts/dependencies
                # that have changed since Source preparation.
                from scripts import sermon_fresh_source_evidence as inspector
                inspector.validate_fresh_source_evidence(self.root, self.plan, self.subject,
                    self.context, self.binding['sourceEvidence'])
        return self.binding['sourceEvidence'] if self.binding else None

    def _check_historical_inputs(self):
        self._check_historical_native_inputs()
        if self._historical_specification is not None:
            from scripts import sermon_historical_layer2 as historical
            frozen_spec,data=c.read_snapshot(self._historical_specification_path)
            c.require(frozen_spec==self._historical_specification
                and c.bytes_sha256(data)==self.binding['historicalLayer2Inputs']['bytesSha256']
                and set(self._historical_reuse)==set(frozen_spec['locales'])
                and all(type(resolver) is historical.HistoricalLayer2Reuse
                    and resolver.spec==frozen_spec['locales'][locale] for locale,resolver in self._historical_reuse.items()),
                'fresh_historical_layer2_inputs_changed')

    def _check_historical_native_inputs(self):
        frozen=getattr(self,'_historical_native_specification',None)
        if frozen is None:
            return
        from scripts import sermon_historical_native_seed as historical
        from scripts import sermon_diagnostic_delivery_preflight as delivery
        files=delivery._Snapshot()
        path=self._historical_native_specification_path
        actual=files.json(path)
        c.require(actual==frozen and files.file(path)==self.binding['historicalNativeInputs']['bytesSha256']
            and set(self._historical_native_seeds)==set(frozen['locales']), 'fresh_historical_native_inputs_changed')
        for locale,lane in frozen['locales'].items():
            seed=self._historical_native_seeds[locale]
            spec=lane['specification']
            c.require(type(seed) is historical.HistoricalSeed
                and seed==historical.HistoricalSeed(spec['parentPlan']['path'],spec['workerReceipt']['path']),
                'fresh_historical_native_inputs_changed')
            # Stable streaming FD hashes: never materialize multi-GB checkpoint
            # bytes and never replace this guard with an mtime-only cache.
            for reference in lane['references']:
                c.require(files.file(reference['path'])==reference['fileBytesSha256'],
                    'fresh_historical_native_inputs_changed')
        files.recheck()

    def configure_historical_native(self, specifications, locales, *, parent_preflight=None):
        """Bind closed native V3 evidence to current Source; no model authority."""
        self._check()
        c.require(getattr(self,'_historical_native_specification',None) is None,
            'fresh_historical_native_already_frozen')
        lanes=_preflight_historical_native_specs(specifications,{locale:None for locale in locales},
            offline_fixture=self.offline_fixture,plan=self.plan)
        c.require(parent_preflight is None or lanes==parent_preflight,'fresh_historical_native_parent_changed')
        from scripts import sermon_historical_native_seed as historical
        from scripts import sermon_diagnostic_delivery_preflight as delivery
        files=delivery._Snapshot();source=files.json(self.root/'source.json');anchor=files.json(self.root/'anchor-manifest.json')
        for lane in lanes.values():
            c.require(lane['parentPreflight']['sourceJsonSha256']==c.canonical_sha256(source)
                and lane['parentPreflight']['anchorJsonSha256']==c.canonical_sha256(anchor),
                'fresh_historical_native_source_changed')
        frozen={'schemaVersion':'sermon-fresh-historical-native-inputs-v1',
            'runId':self.subject.config['runId'],'originalPlanSha256':c.canonical_sha256(self.plan),
            'diagnosticContextSha256':c.canonical_sha256(self.context),'locales':lanes,
            'productionEligible':False,'humanAcceptance':'pending','executionAuthority':'none'}
        path=self.root/'fresh-historical-native-inputs.json';data=public.save_once(path,frozen)
        self._historical_native_specification=frozen;self._historical_native_specification_path=path
        self._historical_native_seeds={locale:historical.HistoricalSeed(lane['specification']['parentPlan']['path'],
            lane['specification']['workerReceipt']['path']) for locale,lane in lanes.items()}
        self.binding['historicalNativeInputs']={'path':str(path),'bytesSha256':c.bytes_sha256(data)}
        self._check()

    def preview(self, locale, spec, *, depends_on=None):
        seed=getattr(self,'_historical_native_seeds',{}).get(locale)
        return super().preview(locale,spec,depends_on=depends_on,
            **({'historical_seed':seed} if seed is not None else {}))

    def configure_historical_locales(self, specifications, locales):
        """Freeze explicit closed-parent rebind specs, never general callbacks."""
        from scripts import sermon_historical_layer2 as historical
        self._check()
        c.require(type(specifications) is dict and bool(specifications)
            and set(specifications)<=set(locales) and c._strict_json(specifications),
            'fresh_historical_layer2_locales_invalid')
        c.require(self._historical_specification is None,'fresh_historical_layer2_already_frozen')
        resolvers={locale:historical.HistoricalLayer2Reuse(spec) for locale,spec in specifications.items()}
        c.require(all(type(resolver) is historical.HistoricalLayer2Reuse for resolver in resolvers.values()),
            'fresh_historical_layer2_type_invalid')
        for locale,resolver in resolvers.items():
            new,_=historical.check_ref(resolver.spec['newPlanRef'])
            c.require(new==self.plan and Path(resolver.spec['newPlanRef']['path'])==self.root/'run-plan.json'
                and c.read_snapshot(Path(resolver.spec['parentMaterialRefs']['policy']['path']))[0]['targetLocale']==locale,
                'fresh_historical_layer2_new_plan_changed')
        frozen={'schemaVersion':'sermon-fresh-historical-layer2-inputs-v1',
            'runId':self.subject.config['runId'],'diagnosticContextSha256':c.canonical_sha256(self.context),
            'locales':deepcopy(specifications),'productionEligible':False,'humanAcceptance':'pending'}
        path=self.root/'fresh-historical-layer2-inputs.json';data=strict.save_once(path,frozen)
        self._historical_specification=frozen;self._historical_specification_path=path
        self._historical_reuse=resolvers
        self.binding['historicalLayer2Inputs']={'path':str(path),'bytesSha256':c.bytes_sha256(data)}
        self._check()

    def run_locale(self, locale, spec, *, depends_on=None):
        return super().run_locale(locale,spec,depends_on=depends_on,
            historical_reuse=self._historical_reuse.get(locale))

    def prepare_source(self, recipe, authorization):
        active = profile.current() or {}
        c.require(active.get('productionRunId') in (None, self.subject.config['runId']),
            'fresh_causality_production_run_changed')
        with profile.context(productionRunId=self.subject.config['runId']):
            return self._prepare_source(recipe, authorization)

    def _prepare_source(self, recipe, authorization):
        self._check()
        c.require(type(recipe) is dict and set(recipe) <= {'prior_plan_path','prior_source_path','prior_aligned_path',
            'prior_summary_path','audio_path','run_mfa','local_runtime_path'} and {'prior_plan_path','prior_source_path',
            'prior_aligned_path','prior_summary_path','audio_path'} <= set(recipe),'fresh_source_recipe_invalid')
        file_refs={key:{'path':str(_safe_path(Path(value))),'sha256':source_adapter._sha(value)}
                   for key,value in recipe.items() if key.endswith('_path') and value is not None}
        frozen_recipe = {'schemaVersion':'sermon-fresh-source-recipe-v2','files':file_refs,
            'runMFA':recipe.get('run_mfa',False),'authorizationSha256':c.canonical_sha256(authorization)}
        existing_recipe = self.root/'fresh-source-recipe.json'
        if existing_recipe.exists():
            prior_recipe = c.read_snapshot(existing_recipe)[0]
            # Legacy receipts retain their original schema and evidence. They
            # can be inspected/reused, never backfilled with invented leaves.
            if 'schemaVersion' not in prior_recipe:
                frozen_recipe.pop('schemaVersion')
        strict.save_once(existing_recipe, frozen_recipe)
        if (self.root/'fresh-source-evidence.json').exists():
            from scripts import sermon_fresh_source_evidence as inspector
            prepared = {key:c.read_snapshot(self.root/name)[0] for key,name in
                (('source','source.json'),('anchor','anchor-manifest.json'),
                 ('context','diagnostic-context.json'),('evidence','fresh-source-evidence.json'))}
            with accounting.stage('diagnostic.source_resume', depends_on=[],
                    work_unit_id='source.resume', executor_type='deterministic_program', cache_hit=True) as resume_span:
                inspector.validate_fresh_source_evidence(self.root,self.plan,self.subject,
                    prepared['context'],prepared['evidence'])
            prepared['completionSpans']=[resume_span]
        else:
            with accounting.stage('diagnostic.source_preflight', depends_on=[],
                    work_unit_id='source.preflight', executor_type='deterministic_program') as intake_span:
                source_adapter.preflight_recipe(self.plan, recipe, authorization)
                if recipe.get('run_mfa',False):
                    preflight_path=self.root/'mfa-identity-preflight.json'
                    previous=c.read_snapshot(preflight_path)[0] if preflight_path.exists() else None
                    comparison=mfa_identity.preflight(self.plan, recipe.get('local_runtime_path'),
                        expected_receipt=previous)
                    strict.save_once(preflight_path, comparison)
                    mfa_identity.require_accepted(comparison)
                accounting.record_workload('diagnostic.source_recipe_binding', {
                    'recipeSha256':c.canonical_sha256(frozen_recipe), 'planSha256':c.canonical_sha256(self.plan)})
            intake=completion.capture(intake_span, production_run_id=self.subject.config['runId'],
                artifact_sha256=c.canonical_sha256(frozen_recipe), artifact_kind='frozen_recipe',
                execution_mode='deterministic_validation')
            # Return typed actual provider leaves, never their parent wrappers.
            asr=self.runner.transcribe(_safe_path(Path(recipe['audio_path'])).read_bytes(),
                depends_on=[intake['spanId']],completion_result=True)
            review=self.runner.source_check(operation_id='source.initial',
                depends_on=[asr['completion']['spanId']],completion_result=True)
            with self.subject._locked() as (_,state):
                self.subject._remaining(state)
                original_deadline=state['startedMonotonic']+self.subject.config['totalWallSeconds']
            prepared=source_adapter.prepare_source(self.plan,self.subject,**recipe,authorization=authorization,
                deadline_monotonic=original_deadline,source_completions={
                    'intake':intake,'transcription':asr['completion'],'sourceCheck':review['completion']})
        return self.adopt_prepared_source(prepared)

    def adopt_prepared_source(self, prepared):
        """Bind completed builder output, then apply the full existing Source gate."""
        self.context=prepared['context']
        self.binding={'schemaVersion':'sermon-fresh-diagnostic-session-v1','originalPlanSha256':c.canonical_sha256(self.plan),
            'diagnosticContextSha256':c.canonical_sha256(self.context),'sourceEvidence':prepared['evidence'],
            'runId':self.context['runId'],'storeSha256':self.subject.store.store_sha256,'evidenceMode':self.evidence_mode,
            'humanAcceptance':'pending','productionEligible':False,'implementationSha256':c.bytes_sha256(Path(__file__).read_bytes())}
        self.source_spans=prepared['completionSpans']
        self._check()
        return prepared

    def inspect_delivery(self, previews, expected_locales):
        from scripts import sermon_diagnostic_delivery_preflight as delivery
        evidence = self._check()
        c.require(evidence is not None and self.context is not None, 'fresh_source_preparation_required')
        return delivery.inspect_fresh_delivery(self.root, self.subject, self.context, previews,
            expected_locales=expected_locales, plan=self.plan, source_evidence=evidence)

    def inspect_source(self):
        evidence=self._check()
        c.require(evidence is not None,'fresh_source_preparation_required')
        inspected={'status':'existing_evidence_validated','sourceEvidence':evidence,'humanAcceptance':'pending',
                   'newASRCalls':0,'newSourceCheckCalls':0,'productionEligible':False}
        if self._cached_source:
            inspected.update(newMFACalls=0,historicalSourceProviderCalls=2,
                sourceExecution='historical_receipts_reused_current_deterministic_inspection')
        return inspected

    def prepare_cached_source(self, parent_plan_path, authorization):
        """A distinct attempt consumes closed-parent Source, never its budget."""
        self._check()
        c.require(self.context is None or self._cached_source,'fresh_source_cache_mode_changed')
        prepared=cached_source.prepare_source(self.plan,self.subject,parent_plan_path=parent_plan_path,
                                             authorization=authorization)
        self.context=prepared['context'];self._cached_source=True
        self.binding={'schemaVersion':'sermon-fresh-diagnostic-session-v1','originalPlanSha256':c.canonical_sha256(self.plan),
            'diagnosticContextSha256':c.canonical_sha256(self.context),'sourceEvidence':prepared['evidence'],
            'runId':self.context['runId'],'storeSha256':self.subject.store.store_sha256,'evidenceMode':self.evidence_mode,
            'humanAcceptance':'pending','productionEligible':False,'implementationSha256':c.bytes_sha256(Path(__file__).read_bytes())}
        self.source_spans=prepared['completionSpans'];self._check()
        return prepared


def _preflight_historical_native_specs(specifications, locale_drafts, *, offline_fixture, plan=None):
    """Zero-dispatch validation before Source or any paid locale repair.

    V1 JSON specification contains only exact hashed refs; a persisted public
    parent preflight is inspection evidence, never an execution authority.
    Normal callers use None and retain their existing behavior.
    """
    if specifications is None:
        return {}
    from scripts import sermon_historical_native_seed as historical
    from scripts import sermon_diagnostic_delivery_preflight as delivery
    c.require(not offline_fixture and type(specifications) is dict and bool(specifications)
        and set(specifications)<=set(locale_drafts) and set(specifications)<=flow.LOCALES,
        'fresh_historical_native_locales_invalid')
    c.require(type(plan) is dict and Path(plan['runDirectory']).is_absolute(),'fresh_historical_native_specs_invalid')
    new_root=_safe_path(Path(plan['runDirectory']))
    files=delivery._Snapshot();lanes={}
    helper_ref={'path':str(Path(historical.__file__).resolve()),
                'fileBytesSha256':files.file(Path(historical.__file__).resolve())}
    for locale,spec in specifications.items():
        c.require(type(spec) is dict and set(spec)=={'schemaVersion','targetLocale','parentPlan','workerReceipt','parentPreflight'}
            and spec['schemaVersion']=='sermon-fresh-historical-native-locale-v1' and spec['targetLocale']==locale,
            'fresh_historical_native_specs_invalid')
        for key in ('parentPlan','workerReceipt','parentPreflight'):
            ref=spec[key]
            c.require(type(ref) is dict and set(ref)=={'path','fileBytesSha256'}
                and files.file(ref['path'])==ref['fileBytesSha256'],'fresh_historical_native_ref_changed')
        seed=historical.HistoricalSeed(spec['parentPlan']['path'],spec['workerReceipt']['path'])
        observed=historical.preflight_parent(seed)
        persisted=files.json(spec['parentPreflight']['path'])
        c.require(persisted==observed and observed['targetLocale']==locale
            and observed['parentPlan']==spec['parentPlan'] and observed['workerReceipt']==spec['workerReceipt']
            and observed['grantsExecutionAuthority'] is False and observed['productionEligible'] is False,
            'fresh_historical_native_parent_changed')
        from scripts import sermon_diagnostic_attempts as attempts
        parent_plan,parent_root=attempts._project(spec['parentPlan']['path'])
        c.require(all(plan['providerConfig'][key]==parent_plan['providerConfig'][key] for key in
            ('sourceMediaSha256','sourceClipSha256','sourceAudioSha256','sourceWindowSeconds')),
            'fresh_historical_native_source_changed')
        lineage=historical._lineage(new_root,plan,parent_plan,parent_root,files)
        history=files.json(new_root/'linked-history.json')
        ancestors=[{'path':ref['path'],'fileBytesSha256':ref['bytesSha256']}
            for ref in (*history['legacyObservationBaseline']['snapshots'],*history['parentClosureSnapshots'])]
        refs=[helper_ref,*lineage,*ancestors,*[spec[k] for k in ('parentPlan','workerReceipt','parentPreflight')],observed['closure'],
              observed['workerRequest'],*observed['originalInputs'],*observed['originalArtifacts']]
        refs=list({ref['path']:deepcopy(ref) for ref in refs}.values())
        files.refs(refs)
        lanes[locale]={'specification':deepcopy(spec),'parentPreflight':deepcopy(observed),'references':refs}
    files.recheck()
    return lanes


def _preflight_preview_specs(preview_specs, locale_drafts, *, offline_fixture, plan=None):
    """Validate cheap native input contracts before any paid Source stage."""
    from scripts import sermon_diagnostic_preview_worker as worker
    from scripts import sermon_native_preview_runtime as native
    from scripts import sermon_preview_checkpoint_manifest as checkpoint
    checkpoint_keys={'checkpoint_manifest_path','checkpoint_stage_declaration_path'}
    c.require(type(preview_specs) is dict and set(preview_specs)==set(locale_drafts)
        and bool(preview_specs) and set(preview_specs)<=flow.LOCALES,'fresh_diagnostic_preview_locales_changed')
    for spec in preview_specs.values():
        c.require(type(spec) is dict and worker.REQUIRED <= set(spec)
            and set(spec) <= worker.REQUIRED|worker.OPTIONS|{'fixture_behavior','runtime_manifest_path'}|checkpoint_keys
            and type(spec['execute']) is bool and spec['execute'] is (not offline_fixture),
            'fresh_diagnostic_preview_mode_changed')
        c.require(type(spec['paths']) is dict and set(spec['paths'])==set(worker.PATH_KEYS)-{'candidate'},
            'fresh_diagnostic_preview_candidate_owned_by_session')
        c.require(offline_fixture or 'runtime_manifest_path' in spec,'fresh_diagnostic_preview_runtime_manifest_required')
        c.require(not offline_fixture or 'runtime_manifest_path' not in spec,'fresh_diagnostic_fixture_cannot_claim_native_runtime')
        c.require(offline_fixture or 'fixture_behavior' not in spec,'fresh_diagnostic_preview_fixture_forbidden')
        c.require(offline_fixture or checkpoint_keys <= set(spec),'fresh_diagnostic_preview_checkpoint_manifest_required')
        c.require(not offline_fixture or not checkpoint_keys & set(spec),'fresh_diagnostic_fixture_cannot_claim_checkpoint_manifest')
        for value in (*spec['paths'].values(),*[spec[key] for key in
                ('checkpoint_map_path','operation_policies_path','strict_rubric_path','out',*sorted(checkpoint_keys))
                if key in spec]):
            c.require(type(value) is str and Path(value).is_absolute(),'fresh_diagnostic_preview_absolute_path_required')
            _safe_path(value)  # Future Source/policy outputs need not exist yet.
        if not offline_fixture:
            native.validate(_safe_path(spec['runtime_manifest_path']),require_process=True)
            c.require(type(plan) is dict,'fresh_diagnostic_preview_checkpoint_plan_required')
            manifest_path=_safe_path(spec['checkpoint_manifest_path'])
            manifest=c.read_snapshot(manifest_path)[0]
            bound=checkpoint.validate(manifest_path,root=manifest['checkpointRoot'],
                checkpoint_ref=manifest['checkpointRef'],conditioning_sha256=manifest['conditioningSha256'])
            checkpoint.validate_declaration(Path(plan['runDirectory']),
                _safe_path(spec['checkpoint_stage_declaration_path']),bound,
                {'runConfigSha256':c.canonical_sha256(plan['providerConfig']),
                 'continuationCodeCommit':plan['executionIdentity']['gitCommit']})


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
                         execute_publish=False, publication_approval_sha256=None, source_cache_parent_plan_path=None,
                         historical_locale_specs=None, historical_native_specs=None):
    """Unified fixed sequential DAG. Business ledgers decide all replay/retries.

    Produces preview/read-only delivery evidence, plus optional explicitly
    authorized Dev snapshot publication and HTTP verification. Does not call
    Prefect's cache, grant human approval, or relabel preview as formal release.
    """
    c.require(type(execute_publish) is bool and (not execute_publish or (dev_snapshot is not None
        and offline_transport is None)), 'fresh_dev_publication_scope_invalid')
    if execute_publish:
        import re
        c.require(type(publication_approval_sha256) is str and re.fullmatch('[a-f0-9]{64}',publication_approval_sha256),
                  'fresh_dev_publication_scope_invalid')
    c.require(source_cache_parent_plan_path is None or source_recipe is None,'fresh_source_cache_recipe_conflict')
    _preflight_preview_specs(preview_specs,locale_drafts,offline_fixture=offline_transport is not None,plan=plan)
    native_preflight=_preflight_historical_native_specs(historical_native_specs,locale_drafts,
        offline_fixture=offline_transport is not None,plan=plan)
    session=FreshDiagnosticSession(plan,key=key,execute=execute,request_limits=request_limits,offline_transport=offline_transport)
    with profile.session(session.root/'fresh-diagnostic-logs','fresh_diagnostic',work_kind='production',
                         evidence_mode=session.evidence_mode,production_run_id=session.subject.config['runId']):
        try:
            with accounting.stage('diagnostic.source_preparation',depends_on=[],executor_type='deterministic_program'):
                prepared=(session.prepare_cached_source(source_cache_parent_plan_path,authorization)
                          if source_cache_parent_plan_path is not None else session.prepare_source(source_recipe,authorization))
        except Exception as exc:
            from scripts import sermon_source_failure as source_failure
            if isinstance(exc,accounting.AccountingWriteError) or getattr(exc,'sermon_logging_failed',False):
                raise
            try:
                provider_snapshot=session.subject.snapshot()
            except Exception:
                provider_snapshot=None
            failed=source_failure.receipt(exc,plan=session.plan,provider_snapshot=provider_snapshot)
            strict.save_once(session.root/'fresh-source-failures'/(c.canonical_sha256(failed)+'.json'),failed)
            if failed['requiresReconciliation']:
                raise  # Preserve unknown calls, ledger corruption and original exit.
            return failed
        with _terminal_failure_receipt(session):
            specs=freeze_locale_inputs(session,locale_drafts)
            if historical_locale_specs is not None:
                session.configure_historical_locales(historical_locale_specs,specs)
            native_preflight_spans=[]
            if historical_native_specs is not None:
                with accounting.stage('diagnostic.historical_native_preflight',
                        work_unit_id='diagnostic.historical_native_preflight', executor_type='deterministic_program',
                        depends_on=prepared['completionSpans']) as native_preflight_span:
                    session.configure_historical_native(historical_native_specs,specs,parent_preflight=native_preflight)
                    accounting.record_workload('diagnostic.historical_native_preflight', {
                        'localeCount':len(native_preflight),'providerDispatchOccurred':False,
                        'modelExecutedCurrentAttempt':False,'productionEligible':False})
                native_preflight_spans=[native_preflight_span]
            c.require(set(preview_specs)==set(specs),'fresh_diagnostic_preview_locales_changed')
            config={'schemaVersion':flow.SCHEMA,'locales':{loc:{'localeSpec':spec,'previewSpec':deepcopy(preview_specs[loc])}
                                                        for loc,spec in specs.items()}}
            for locale,lane in config['locales'].items():
                for key in ('source','anchor','policy'):
                    lane['previewSpec']['paths'][key]=lane['localeSpec'][key]
                lane['previewSpec']['strict_rubric_path']=lane['localeSpec']['rubric']
            dag=flow.DiagnosticDAG(session,config); dag.freeze()
            dag.initial_source_spans=[*prepared['completionSpans'],*native_preflight_spans]
            results={node[0]:dag.execute(node[0]) for node in dag.nodes}
            result={'schemaVersion':'sermon-fresh-diagnostic-result-v1','nodes':results,
                'status':'diagnostic_traversal_complete' if results['delivery.readonly']['readyForDownstream'] else 'incomplete',
                'productionEligible':False,'humanAcceptance':'pending','publicationAuthorized':False,'formalAudioPackageCreated':False,
                'formalReleasePackageCreated':False,'planSha256':c.canonical_sha256(plan),'sourceEvidenceSha256':c.canonical_sha256(prepared['evidence'])}
            _save_result(session,result)
            if dev_snapshot is not None:
                from scripts import sermon_dev_diagnostic_snapshot as dev
                c.require(type(dev_snapshot) is dict and set(dev_snapshot)=={'baseline','out','page_id'},'fresh_dev_snapshot_inputs_invalid')
                previews={loc:dag.results[f'preview.{loc}'] for loc in specs if f'preview.{loc}' in dag.results}
                leaves=[span for observation in results.values() for span in observation['completionSpans']]
                stages={'schemaVersion':'sermon-dev-diagnostic-stage-results-v1','runId':session.subject.config['runId'],
                    'diagnosticContextSha256':c.canonical_sha256(session.context),'nodes':results}
                built=dev.build_snapshot(session,**dev_snapshot,preview_receipts=previews,stage_results=stages,depends_on=leaves)
                result={**result,'devSnapshot':built,'publicationStatus':'not_deployed'}
                _save_result(session,result)
                if execute_publish:
                    publication={'schemaVersion':'sermon-dev-diagnostic-publication-authorization-v1',
                        'manifestSha256':c.canonical_sha256(built['manifest']),'project':dev.PROJECT,'site':dev.PROJECT,
                        'origin':dev.ORIGIN,'publicationScope':'diagnostic_preview_only','productionEligible':False,
                        'approvalSha256':publication_approval_sha256}
                    delivery=dev.publish_and_verify(built,plan=plan,authorization=publication,execute=True,
                        depends_on=built['completionSpans'])
                    result={**result,'publicationStatus':delivery['status'],'publicationReceipt':delivery}
                    _save_result(session,result)
            return result
