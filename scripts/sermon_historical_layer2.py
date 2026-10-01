"""Explicit closed-parent L2 rebind and one-group language-plugin repair.

Historical paid responses retain their original provider identity and ledger.
Current deterministic rebinds cost zero; language repairs use the pinned new
provider ledger, never invented D5 reservations or a fabricated semantic failure.
"""
from copy import deepcopy
from pathlib import Path

from scripts import sermon_review_contracts as c, sermon_review_budget as budget
from scripts import sermon_strict_layer2 as strict, sermon_accounting as accounting
from scripts import sermon_diagnostic_attempts as attempts
from scripts import sermon_public_snapshot as aggregate
from scripts.sermon_release_workflow import _safe_path

SPEC = 'sermon-historical-layer2-spec-v1'
REBIND = 'sermon-historical-layer2-rebind-v1'
REPAIR = 'sermon-language-plugin-repair-v1'
ENFORCEMENT = 'new_provider_ledger_historical_parent_repair'


def ref(path):
    path = _safe_path(Path(path))
    c.require(path.is_absolute() and path.is_file(), 'historical_snapshot_required')
    return {'path': str(path), 'bytesSha256': c.bytes_sha256(path.read_bytes())}


def check_ref(value, *, json_required=True, aggregate_schema=None):
    c.require(type(value) is dict and set(value) == {'path', 'bytesSha256'},
              'historical_snapshot_changed')
    c.require(aggregate_schema is None or
              (json_required and aggregate_schema == attempts.SCHEMA_V2),
              'historical_aggregate_type_required')
    path = _safe_path(Path(value['path']))
    c.require(path.is_absolute(), 'historical_snapshot_required')
    if json_required:
        # Only the versioned linked-attempt aggregate gets the larger bound.
        # Individual paid receipts and revision records retain the private cap.
        parsed, raw = (aggregate.read_snapshot if aggregate_schema else c.read_snapshot)(path)
    else:
        parsed, raw = None, path.read_bytes()
    c.require(c.bytes_sha256(raw) == value['bytesSha256'], 'historical_snapshot_changed')
    if aggregate_schema:
        c.require(type(parsed) is dict and parsed.get('schemaVersion') == aggregate_schema,
                  'historical_aggregate_type_required')
    return parsed, raw


def _no_dispatch(*args, **kwargs):
    raise c.ContractError('historical_cache_must_not_dispatch')


class HistoricalLayer2Reuse:
    def __init__(self, specification):
        keys = {'schemaVersion', 'parentPlanRef', 'newPlanRef', 'linkedHistoryRef',
                'parentLocaleRoot', 'parentMaterialRefs', 'parentLanguageRoot', 'parentPluginRef'}
        c.require(type(specification) is dict and set(specification) == keys and
                  specification['schemaVersion'] == SPEC, 'invalid_historical_layer2_spec')
        self.spec = deepcopy(specification)
        c.require(set(self.spec['parentMaterialRefs']) == {'englishSource', 'anchor', 'policy', 'rubric'},
                  'historical_materials_required')
        self._closed()

    def _closed(self):
        plan, _ = check_ref(self.spec['parentPlanRef'])
        new, _ = check_ref(self.spec['newPlanRef'])
        lineage, _ = check_ref(self.spec['linkedHistoryRef'], aggregate_schema=attempts.SCHEMA_V2)
        c.require(plan['schemaVersion'] == new['schemaVersion'] == 'sermon-bounded-diagnostic-plan-v1',
                  'historical_plan_required')
        parent, successor = map(lambda p: _safe_path(Path(p['runDirectory'])), (plan, new))
        c.require(parent.is_absolute() and successor.is_absolute() and parent != successor and
                  parent not in successor.parents and successor not in parent.parents,
                  'historical_roots_overlap')
        c.require(Path(self.spec['parentPlanRef']['path']) == parent/'run-plan.json' and
                  Path(self.spec['newPlanRef']['path']) == successor/'run-plan.json' and
                  Path(self.spec['linkedHistoryRef']['path']) == successor/'linked-history.json',
                  'historical_plan_path_changed')
        closed_path = parent/'budget'/budget.STORE_ID/'provider-run/closed.json'
        c.require(closed_path.is_file(), 'historical_parent_not_closed')
        closed, _ = c.read_snapshot(closed_path)
        terminal = attempts.terminal_parent(plan, _legacy_observation=True)
        expected = dict(schemaVersion=attempts.CLOSED_SCHEMA, runId=plan['providerConfig']['runId'],
            runConfigSha256=c.canonical_sha256(plan['providerConfig']),
            storeSha256=budget.BudgetStore(parent/'budget', plan['authority']).store_sha256,
            providerStateFileSha256=terminal['snapshots'][0]['bytesSha256'],
            budgetStateFileSha256=terminal['snapshots'][1]['bytesSha256'],
            closureEvidenceSha256=c.canonical_sha256(terminal),
            instructionReferenceSha256=closed.get('instructionReferenceSha256'),
            productionEligible=False, newDispatchAllowed=False)
        budget._hash(expected['instructionReferenceSha256'])
        c.require(closed == expected, 'historical_parent_closed_binding_changed')
        c.require(lineage.get('schemaVersion') == attempts.SCHEMA_V2 and
                  lineage.get('newPlanSha256') == c.canonical_sha256(new) and
                  lineage.get('authorizationSha256') == new['providerConfig']['approvalSha256'] == new['authority']['approvalSha256'] and
                  lineage.get('oldReplayAllowed') is False and lineage.get('oldLedgerAndDeadlineModified') is False and
                  lineage.get('productionEligible') is False and ref(closed_path) in lineage['parentClosureSnapshots'],
                  'historical_linked_attempt_required')
        rows = [r for r in lineage['parentEvidence'] if r['runDirectory'] == str(parent)]
        c.require(len(rows) == 1 and rows[0]['projectedPlan'] == plan and
                  all(rows[0].get(k) == v for k, v in terminal.items()), 'historical_parent_lineage_changed')
        attempts._verify_refs(lineage['legacyObservationBaseline']['snapshots'])
        for row in lineage['parentEvidence']:
            attempts._verify_refs(row['snapshots'])
        c.require(new['providerConfig']['runId'] != plan['providerConfig']['runId'] and
                  all(new['providerConfig'][k] == plan['providerConfig'][k] for k in
                      ('sourceMediaSha256', 'sourceClipSha256', 'sourceAudioSha256', 'sourceWindowSeconds')),
                  'historical_source_scope_changed')
        self.parent_plan, self.new_plan = plan, new
        self.parent, self.successor, self.closed_ref = parent, successor, ref(closed_path)
        return terminal

    def _current(self):
        self._closed()
        current=accounting.execution_identity()
        c.require(current['trackedWorkingTreeDirty'] is False and current == self.new_plan['executionIdentity'],
                  'historical_current_code_changed')

    def _inventory(self):
        from scripts import sermon_strict_candidate_bridge as bridge, produce_target_language_candidate as producer
        self._closed()
        if hasattr(self,'_inventory_cache'):
            for snapshot in self._inventory_cache_refs:check_ref(snapshot,json_required=False)
            return deepcopy(self._inventory_cache)
        locale_root = _safe_path(Path(self.spec['parentLocaleRoot']))
        language_root = _safe_path(Path(self.spec['parentLanguageRoot']))
        c.require(self.parent in locale_root.parents and locale_root in language_root.parents,
                  'historical_parent_paths_changed')
        locale, _ = c.read_snapshot(locale_root/'locale-input.json')
        raw = []
        for name in ('englishSource', 'anchor', 'policy', 'rubric'):
            value = self.spec['parentMaterialRefs'][name]
            c.require(self.parent in Path(value['path']).parents, 'historical_material_path_changed')
            raw.append(check_ref(value)[1])
        c.require(locale['inputBytesSha256'] == [c.bytes_sha256(b) for b in raw] and
                  locale['productionRunId'] == self.parent_plan['providerConfig']['runId'],
                  'historical_locale_inputs_changed')
        check_ref(self.spec['parentPluginRef'], json_required=False)
        plugin_path = Path(self.spec['parentPluginRef']['path'])
        language, _ = c.read_snapshot(language_root/'language-review.json')
        bindings, _ = c.read_snapshot(language_root/'revision-bindings.json')
        roots = [(locale_root/'groups'/c.canonical_sha256(g)/'revisions/initial', 1) for g in locale['groups']]
        try:
            actual = bridge.compile_candidate(*raw, roots, plugin_path=plugin_path,
                expected_plugin_sha256=producer.plugin_implementation_sha256(plugin_path),
                diagnostic_context=locale.get('diagnosticContext'))
            actual_language, actual_bindings = actual['languageReceipt'], actual['revisionBindings']
        except bridge.LanguagePluginRejected as exc:
            actual_language, actual_bindings = exc.language_receipt, exc.revision_bindings
        c.require(actual_language == language and actual_bindings == bindings['groups'],
                  'historical_language_evidence_changed')
        if (language_root/'failure.json').exists():
            failure, _ = c.read_snapshot(language_root/'failure.json')
            c.require(failure['schemaVersion'] == 'sermon-strict-locale-plugin-failure-v1' and
                      failure['localeInputSha256'] == c.canonical_sha256(locale) and
                      failure['languageReceiptSha256'] == c.canonical_sha256(language) and
                      failure['revisionBindingsSha256'] == c.canonical_sha256(bindings) and
                      failure['failedGroups'] == [g for g in language['groupReviews'] if g['status'] != 'pass'],
                      'historical_language_failure_changed')
        captured=[ref(locale_root/'locale-input.json'),ref(language_root/'language-review.json'),
            ref(language_root/'revision-bindings.json'),*self.spec['parentMaterialRefs'].values(),
            *[ref(p) for p in producer.plugin_implementation_sources(plugin_path)]]
        if (language_root/'failure.json').exists():captured.append(ref(language_root/'failure.json'))
        for (root,_),binding in zip(roots,actual_bindings):
            captured.extend(ref(root/name) for name in binding['artifacts'])
        self._inventory_cache=(locale_root,locale,raw,language);self._inventory_cache_refs=captured
        return deepcopy(self._inventory_cache)

    def inspect(self, prepared):
        locale_root, locale, raw, language = self._inventory()
        c.require([c.bytes_sha256(prepared['bytes'][k]) for k in ('englishSource', 'anchor', 'policy', 'rubric')] ==
                  [c.bytes_sha256(b) for b in raw] and prepared.get('requestLimits') == locale.get('requestLimits'),
                  'historical_current_materials_changed')
        c.require(prepared['group'] in locale['groups'], 'historical_group_not_in_parent')
        root = locale_root/'groups'/c.canonical_sha256(prepared['group'])/'revisions/initial'
        old = strict.prepare(*raw, prepared['group'], request_limits=locale.get('requestLimits'),
                             diagnostic_context=locale.get('diagnosticContext'))
        manifest, _ = c.read_snapshot(root/'revision.json')
        candidate, candidate_bytes = c.read_snapshot(root/'candidate.json')
        inputs, _ = c.read_snapshot(root/'review-input.json')
        receipt, _ = c.read_snapshot(root/'review-receipt.json')
        c.validate_candidate_artifact(manifest, candidate_bytes)
        c.require(inputs == strict.input_manifest(old, manifest, candidate_bytes), 'historical_review_input_changed')
        c.validate_review_binding(receipt, manifest, old['rubric'], inputs)
        c.require(receipt['executionStatus'] == 'succeeded' and receipt['reviewVerdict'] == 'pass' and
                  manifest['revisionNumber'] == 1, 'historical_semantic_review_not_passed')
        strict._validate_cached_review_evidence(receipt, manifest, root/'reviewer.json', old, inputs)
        provider_state, _ = c.read_snapshot(self.parent/'budget'/budget.STORE_ID/'provider-run/state.json')
        references = [self.spec['parentPlanRef'], self.closed_ref, self.spec['newPlanRef'], self.spec['linkedHistoryRef'],
                      ref(locale_root/'locale-input.json'), *self.spec['parentMaterialRefs'].values(),
                      ref(Path(self.spec['parentLanguageRoot'])/'language-review.json'),
                      ref(Path(self.spec['parentLanguageRoot'])/'revision-bindings.json'), self.spec['parentPluginRef']]
        for name in ('revision', 'candidate', 'review-input', 'review-receipt'):
            references.append(ref(root/(name+'.json')))
        for role, stem in (('translator', 'generator'), ('reviewer', 'reviewer')):
            saved, _ = c.read_snapshot(root/(stem+'.json'))
            response = strict.require_call_binding(root/(stem+'.json'), saved)
            request = strict.generation_prompt(prepared) if role == 'translator' else strict.prompt(
                prepared, role, candidate=candidate, input_manifest=strict.input_manifest(prepared, manifest, candidate_bytes))
            payload_sha = c.canonical_sha256(strict._payload(prepared, role, request))
            c.require(saved['payloadSha256'] == payload_sha and saved['model'] == prepared['policy'][role]['model'],
                      'historical_exact_payload_changed')
            call_id = response['accounting']['modelCallId']; row = provider_state['requests'].get(call_id)
            provider_path = self.parent/'budget'/budget.STORE_ID/'provider-run'/(call_id+'.json')
            paid, paid_bytes = c.read_snapshot(provider_path)
            c.require(row is not None and row['state'] == 'returned' and row['requestSha256'] == payload_sha and
                      row['receiptSha256'] == c.bytes_sha256(paid_bytes) and paid['modelCallId'] == call_id and
                      paid['payloadSha256'] == payload_sha and paid['response'] == response['response'],
                      'historical_paid_response_binding_changed')
            references.extend(ref(root/(stem+suffix+'.json')) for suffix in ('', '.raw', '.call'))
            references.append(ref(provider_path))
        groups = [g for g in language['groupReviews'] if g['translationGroupId'] == prepared['group']['translationGroupId']]
        c.require(len(groups) == 1, 'historical_plugin_group_missing')
        return dict(parentRoot=root, parentRevision=manifest, parentCandidateBytes=candidate_bytes,
                    parentReview=receipt, parentInput=inputs, language=language, groupReview=groups[0],
                    references=references)

    def run_group(self, prepared, *, root, candidate_id, api_key, caller, depends_on=None, completion_spans=None):
        self._current(); prior = self.inspect(prepared)
        c.require(prior['parentRevision']['candidateId'] == candidate_id, 'historical_candidate_identity_changed')
        parent_root = prior['parentRoot']; group_root = _safe_path(Path(root))
        c.require(self.successor in group_root.parents, 'historical_current_root_changed')
        repair = None
        if prior['groupReview']['status'] == 'pass':
            revision_id = 'historical-initial'; current = group_root/'revisions'/revision_id
            # Only returned response caches are seeded. No old manifests, receipts,
            # budget bindings, failure markers or provider ledger rows are copied.
            for stem in ('generator', 'reviewer'):
                for suffix in ('', '.raw', '.call'):
                    value, _ = c.read_snapshot(parent_root/(stem+suffix+'.json'))
                    strict.save_once(current/(stem+suffix+'.json'), value)
            transport, cache_only = _no_dispatch, True
        else:
            from scripts import sermon_diagnostic_provider as provider
            c.require(type(caller) is provider.DiagnosticProvider and caller.config == self.new_plan['providerConfig'] and
                      caller.store.root==self.successor/'budget' and caller.store.authority==self.new_plan['authority'],
                      'historical_repair_pinned_provider_required')
            revision_id = 'language-repair-2'; current = group_root/'revisions'/revision_id
            stamp = c.read_snapshot(current/'repair-plan.json')[0]['createdAt'] if (current/'repair-plan.json').exists() else strict.utc()
            repair = self._make_repair(prepared, prior, candidate_id, revision_id, stamp)
            strict.save_once(current/'language-plugin-repair.json', repair['languagePluginRepair'])
            transport, cache_only = caller, False
            stopped=self._repair_stop(current,repair,caller)
            if stopped is not None:return stopped
            self._repair_proof(prepared, current, repair, caller, 'translator')
        attempts._verify_refs(prior['references'])
        try:
            generated = strict.generate(prepared, current, candidate_id, revision_id, api_key, transport,
                cache_only=cache_only, repair=repair, depends_on=depends_on, completion_spans=completion_spans)
            if repair is not None:
                self._bind_return(current,repair,caller,'translator')
                self._repair_proof(prepared, current, repair, caller, 'reviewer')
            reviewed = strict.review(prepared, current, candidate_id, revision_id, api_key, transport,
                cache_only=cache_only, depends_on=depends_on, completion_spans=completion_spans)
        except accounting.AccountingWriteError:raise
        except (ValueError,OSError) as exc:
            if getattr(exc,'sermon_logging_failed',False):raise
            if repair is not None:
                stopped=self._repair_stop(current,repair,caller)
                if stopped is not None:return stopped
            raise
        if repair is not None:
            stopped=self._repair_stop(current,repair,caller)
            if stopped is not None:return stopped
            self._bind_return(current,repair,caller,'reviewer')
        if repair is None:
            proof = dict(schemaVersion=REBIND, specification=self.spec, parentRefs=prior['references'],
                newRoot=str(current), inputBytesSha256={k:c.bytes_sha256(v) for k,v in prepared['bytes'].items()},
                artifactRefs=[ref(current/name) for name in ('revision.json','candidate.json','review-input.json',
                    'review-receipt.json','generator.json','generator.raw.json','generator.call.json',
                    'reviewer.json','reviewer.raw.json','reviewer.call.json')],
                newPaidRequests=0, newBudgetReservations=0, historicalProviderPaidRequests=2,
                executionAuthority='none', productionEligible=False)
            strict.save_once(current/'historical-rebind.json', proof)
        attempts._verify_refs(prior['references'])
        self._current()
        return dict(schemaVersion='sermon-strict-group-controller-v1', status='machine_review_passed' if
            reviewed['executionStatus']=='succeeded' and reviewed['reviewVerdict']=='pass' else 'blocked',
            reasonCode='historical_paid_cache_rebound' if repair is None else 'language_plugin_repair_reviewed',
            root=str(current), revisionId=revision_id, revisionNumber=generated['revisionNumber'], reviewAttempt=1,
            candidateRevision=generated, reviewReceipt=reviewed, executionAuthority='none',
            budgetStatus='historical_paid_zero_current' if repair is None else ENFORCEMENT)

    def _bind_return(self, root, repair, caller, role):
        stem='generator' if role=='translator' else 'reviewer'
        saved,_=c.read_snapshot(root/(stem+'.json'));raw=strict.require_call_binding(root/(stem+'.json'),saved)
        call_id=raw['accounting']['modelCallId']
        proof=dict(schemaVersion='sermon-language-repair-return-v1',role=role,
            repairContextSha256=c.canonical_sha256(repair['languagePluginRepair']),newPlanRef=self.spec['newPlanRef'],
            payloadSha256=saved['payloadSha256'],rawRef=ref(root/(stem+'.raw.json')),
            providerReceiptRef=ref(caller.store.root/budget.STORE_ID/'provider-run'/(call_id+'.json')))
        validate_repair_return(root,repair,role,proof)
        strict.save_once(root/(role+'-historical-return-proof.json'),proof)

    def _repair_stop(self, root, repair, caller):
        path=root/'historical-repair-stop.json'
        context_sha=c.canonical_sha256(repair['languagePluginRepair'])
        result=dict(schemaVersion='sermon-strict-group-controller-v1',status='reconciliation_required',
            reasonCode='historical_repair_provider_outcome_unknown',root=str(root),
            revisionId=repair['plan']['toRevisionId'],revisionNumber=2,reviewAttempt=0,
            candidateRevision=None,reviewReceipt=None,executionAuthority='none',budgetStatus=ENFORCEMENT)
        if path.exists():
            saved,_=c.read_snapshot(path)
            c.require(set(saved)=={'schemaVersion','repairContextSha256','newPlanRef','providerStateRef','result'} and
                saved['schemaVersion']=='sermon-language-repair-unknown-v1' and
                saved['repairContextSha256']==context_sha and saved['newPlanRef']==self.spec['newPlanRef'] and
                saved['result']==result and Path(saved['providerStateRef']['path'])==root/'historical-provider-unknown.json',
                'historical_repair_stop_changed')
            check_ref(saved['providerStateRef'])
            return saved['result']
        snapshot=caller.snapshot()
        if not snapshot['unknownModelCallIds']:return None
        state,_=c.read_snapshot(caller.store.root/budget.STORE_ID/'provider-run/state.json')
        proof=root/'historical-provider-unknown.json';strict.save_once(proof,state)
        strict.save_once(path,dict(schemaVersion='sermon-language-repair-unknown-v1',repairContextSha256=context_sha,
            newPlanRef=self.spec['newPlanRef'],providerStateRef=ref(proof),result=result))
        return result

    def _make_repair(self, prepared, prior, candidate_id, revision_id, stamp):
        failed = prior['groupReview']
        c.require(failed['status']=='fail' and {r['checkId'] for r in failed['checks'] if r['status']=='fail'} ==
                  {'term_surface_preservation'}, 'historical_plugin_repair_not_supported')
        from scripts.language_review_plugins.diagnostic_structural import _contains
        candidate = c.decode_json(prior['parentCandidateBytes']); target = ''.join(candidate['targetUtterances'])
        source = ' '.join(u['english'] for u in prepared['units'])
        terms = [deepcopy(term) for terms_of_kind in prepared['policy']['terminology'].values() if type(terms_of_kind) is list for term in terms_of_kind if
                 type(term.get('source')) is str and type(term.get('target')) is str and term['target'] and
                 _contains(term['source'],source,latin_boundary=True) and
                 not _contains(term['target'],target,latin_boundary=prepared['policy']['targetLocale']=='es')]
        c.require(terms, 'historical_missing_term_not_proven')
        parent = prior['parentRevision']
        context = dict(schemaVersion=REPAIR, specification=self.spec, parentRefs=prior['references'],
            parentRevisionSha256=c.canonical_sha256(parent), parentReviewSha256=c.canonical_sha256(prior['parentReview']),
            originalSemanticReviewVerdict='pass', languageReceiptSha256=c.canonical_sha256(prior['language']),
            failedGroup=failed, termRepairs=terms, enforcementScope=ENFORCEMENT,
            newRunConfigSha256=c.canonical_sha256(self.new_plan['providerConfig']),
            newAuthoritySha256=c.canonical_sha256(self.new_plan['authority']),
            currentInputBytesSha256={k:c.bytes_sha256(v) for k,v in prepared['bytes'].items()},
            productionEligible=False, humanAcceptancePending=True)
        sidecars = {'language-constraints': c.canonical_bytes(context),
            'new-provider-budget': c.canonical_bytes(dict(enforcementScope=ENFORCEMENT,
                config=self.new_plan['providerConfig'], authority=self.new_plan['authority'])),
            'one-group-closure': c.canonical_bytes(dict(workUnitIds=parent['workUnitIds'], sourceUnitIds=parent['sourceUnitIds']))}
        plan = dict(schemaVersion='sermon-review-repair-plan-v1', repairPlanId='language.'+c.canonical_sha256(context)[:32],
            triggerReviewId='language-plugin.'+prepared['group']['translationGroupId'],
            triggerReceiptSha256=c.canonical_sha256(prior['language']),
            **{k:parent[k] for k in ('sourceIdentitySha256','sourcePackageSha256','anchorSha256','policySha256','candidateId','targetLocale')},
            rubricSha256=c.canonical_sha256(prepared['rubric']), fromRevisionId=parent['revisionId'],
            toRevisionId=revision_id, affectedWorkUnitIds=parent['workUnitIds'], reasonCodes=['language_rule_failed'],
            repairAction='repair_translation', dependencyClosureRef=strict.reference('one-group-closure',sidecars['one-group-closure']),
            constraintsRef=strict.reference('language-constraints',sidecars['language-constraints']),
            budgetRef=strict.reference('new-provider-budget',sidecars['new-provider-budget']),
            stateRevision=c.canonical_sha256(context), createdAt=stamp)
        c.validate_contract(plan)
        return dict(parentRevision=parent, parentCandidateBytes=prior['parentCandidateBytes'], plan=plan,
            triggerReview=prior['parentReview'], inputManifest=prior['parentInput'], sidecars=sidecars,
            priorRevisions=[], priorRepairs=[], languagePluginRepair=context)

    def _repair_proof(self, prepared, root, repair, caller, role):
        self._current(); validate_language_repair(prepared,repair['parentRevision']['candidateId'],repair['plan']['toRevisionId'],repair)
        c.require(caller.config==self.new_plan['providerConfig'] and caller.limits==prepared['requestLimits'] and
                  caller.store.root==self.successor/'budget' and caller.store.authority==self.new_plan['authority'],
                  'historical_repair_provider_changed')
        caller.preflight(prepared,'content_revision' if role=='translator' else 'review',root,repair if role=='translator' else None)
        if role=='translator': request=strict.generation_prompt(prepared,repair)
        else:
            manifest,_=c.read_snapshot(root/'revision.json');candidate,data=c.read_snapshot(root/'candidate.json')
            request=strict.prompt(prepared,role,candidate=candidate,input_manifest=strict.input_manifest(prepared,manifest,data))
        strict.save_once(root/(role+'-historical-dispatch-proof.json'),dict(schemaVersion='sermon-language-repair-dispatch-v1',
            enforcementScope=ENFORCEMENT, role=role, repairContextSha256=c.canonical_sha256(repair['languagePluginRepair']),
            newPlanRef=self.spec['newPlanRef'], payloadSha256=c.canonical_sha256(strict._payload(prepared,role,request)),
            requestLimits=prepared['requestLimits'], productionEligible=False))


def validate_language_repair(prepared, candidate_id, revision_id, repair):
    c.require(type(repair) is dict and set(repair)=={'parentRevision','parentCandidateBytes','plan','triggerReview',
        'inputManifest','sidecars','priorRevisions','priorRepairs','languagePluginRepair'}, 'invalid_language_plugin_repair')
    context=repair['languagePluginRepair'];c.require(context.get('schemaVersion')==REPAIR,'invalid_language_plugin_repair')
    inspector=HistoricalLayer2Reuse(context['specification']);prior=inspector.inspect(prepared)
    expected=inspector._make_repair(prepared,prior,candidate_id,revision_id,repair['plan']['createdAt'])
    c.require(repair==expected and prior['parentRevision']['candidateId']==candidate_id,
              'language_plugin_repair_binding_changed')
    return repair


def validate_rebind(prepared, root, proof):
    c.require(type(proof) is dict and set(proof)=={'schemaVersion','specification','parentRefs','newRoot',
        'inputBytesSha256','artifactRefs','newPaidRequests','newBudgetReservations','historicalProviderPaidRequests',
        'executionAuthority','productionEligible'}, 'historical_rebind_changed')
    inspector=HistoricalLayer2Reuse(proof.get('specification'));prior=inspector.inspect(prepared)
    c.require(proof.get('schemaVersion')==REBIND and proof.get('parentRefs')==prior['references'] and
              proof.get('newRoot')==str(root) and prior['groupReview']['status']=='pass' and
              proof.get('newPaidRequests')==0 and proof.get('newBudgetReservations')==0 and
              proof.get('historicalProviderPaidRequests')==2 and proof.get('executionAuthority')=='none' and
              proof.get('productionEligible') is False and proof.get('inputBytesSha256')==
              {k:c.bytes_sha256(v) for k,v in prepared['bytes'].items()}, 'historical_rebind_changed')
    expected=[ref(Path(root)/name) for name in ('revision.json','candidate.json','review-input.json',
        'review-receipt.json','generator.json','generator.raw.json','generator.call.json',
        'reviewer.json','reviewer.raw.json','reviewer.call.json')]
    c.require(proof['artifactRefs']==expected, 'historical_rebind_artifacts_changed')
    return proof


def validate_repair_return(root, repair, role, proof):
    context=repair['languagePluginRepair'];spec=context['specification']
    c.require(type(proof) is dict and set(proof)=={'schemaVersion','role','repairContextSha256','newPlanRef',
        'payloadSha256','rawRef','providerReceiptRef'} and proof['schemaVersion']=='sermon-language-repair-return-v1' and
        proof['role']==role and proof['repairContextSha256']==c.canonical_sha256(context) and
        proof['newPlanRef']==spec['newPlanRef'], 'historical_repair_return_changed')
    plan,_=check_ref(spec['newPlanRef']);successor=Path(plan['runDirectory'])
    stem='generator' if role=='translator' else 'reviewer'
    c.require(successor in Path(root).parents and proof['rawRef']==ref(Path(root)/(stem+'.raw.json')),
        'historical_repair_return_changed')
    saved,_=c.read_snapshot(Path(root)/(stem+'.json'));raw=strict.require_call_binding(Path(root)/(stem+'.json'),saved)
    call_id=raw['accounting']['modelCallId'];folder=successor/'budget'/budget.STORE_ID/'provider-run'
    c.require(proof['providerReceiptRef']==ref(folder/(call_id+'.json')),'historical_repair_return_changed')
    paid,paid_bytes=check_ref(proof['providerReceiptRef']);state,_=c.read_snapshot(folder/'state.json')
    row=state['requests'].get(call_id)
    c.require(state['config']==plan['providerConfig'] and row is not None and row['state']=='returned' and
        row['receiptSha256']==c.bytes_sha256(paid_bytes) and
        proof['payloadSha256']==saved['payloadSha256']==raw['payloadSha256']==row['requestSha256']==paid['payloadSha256'] and
        paid['modelCallId']==call_id and paid['response']==raw['response'],'historical_repair_paid_return_unproven')
    return proof
