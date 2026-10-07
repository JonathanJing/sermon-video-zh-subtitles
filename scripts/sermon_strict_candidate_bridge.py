"""Explicit private RQC -> existing public Candidate compatibility boundary.

This adapter performs no model calls, approval, dispatch or policy downgrade.
Call under the authoritative workflow lock; the caller must CAS a second
snapshot before creating a Layer 3 intent. CLI/default producers stay legacy.
"""
import copy
from pathlib import Path

from scripts import sermon_review_contracts as c
from scripts import sermon_strict_layer2 as strict
from scripts import produce_target_language_candidate as producer
from scripts import prepare_target_language_speech_job as handoff
from scripts.sermon_release_workflow import _safe_path


class LanguagePluginRejected(c.ContractError):
    """Known plugin verdict; retain its exact receipt without granting admission."""

    def __init__(self, receipt, revision_bindings):
        super().__init__('strict_bridge_plugin_rejected')
        self.language_receipt = copy.deepcopy(receipt)
        self.revision_bindings = copy.deepcopy(revision_bindings)
        self.failed_groups = [copy.deepcopy(row) for row in receipt['groupReviews']
                              if row['status'] != 'pass']


def compile_candidate(source_bytes, anchor_bytes, policy_bytes, rubric_bytes,
                      revisions, *, plugin_path, expected_plugin_sha256, diagnostic_context=None):
    """Validate complete current group receipts; return human-pending artifacts.

    ``revisions`` is an ordered sequence of trusted local revision directories
    and explicit reviewer attempt numbers. No path is taken from model output.
    The result's bindings cover every byte read, including raw provider proof.
    """
    source, anchor, policy, rubric = [c.decode_json(b) for b in
        (source_bytes, anchor_bytes, policy_bytes, rubric_bytes)]
    request = producer.prepare_request(source, anchor, policy, strict_rubric=rubric, diagnostic_context=diagnostic_context)
    c.require(type(revisions) in (list, tuple) and 1 <= len(revisions) <= 4096,
              'strict_bridge_revision_count')
    groups, bindings, seen, snapshots, rule_receipts = [], [], set(), [], []
    generation = {role: {'model': policy[role]['model'],
        'promptVersion': policy[role]['promptVersion'], 'requestIds': []}
        for role in ('translator', 'reviewer')}
    for root, attempt in revisions:
        c.require(type(attempt) is int and 1 <= attempt <= 2, 'strict_bridge_review_attempt')
        root = _safe_path(root)
        captured = {}

        def read(name):
            value, data = c.read_snapshot(root / name)
            captured[name] = data
            return value, data

        if diagnostic_context is not None:
            from scripts.sermon_diagnostic_context import validate_context
            c.require(read('diagnostic-context.json')[0] == validate_context(diagnostic_context), 'strict_bridge_diagnostic_context_changed')
        else:
            c.require(not (root/'diagnostic-context.json').exists(), 'strict_bridge_diagnostic_context_required')
        manifest, _ = read('revision.json')
        artifact, artifact_bytes = read('candidate.json')
        c.validate_candidate_artifact(manifest, artifact_bytes)
        repair=strict.load_repair(root)
        if repair is not None:
            for name in ('parent-revision','parent-candidate','repair-plan','trigger-review','repair-input','repair-sidecars','repair-history'):
                read(name+'.json')
        c.validate_revision_lineage(manifest,repair['parentRevision'] if repair else None,repair['plan'] if repair else None)
        group = {k: artifact[k] for k in ('translationGroupId', 'sourceUnitIds')}
        limits = read('request-limits.json')[0] if (root / 'request-limits.json').exists() else None
        rules = read('rule-preflight.json')[0] if (root / 'rule-preflight.json').exists() else None
        if rules is not None:
            rule_receipts.append(rules)
            context = read('rule-context.json')[0]
            c.require(_safe_path(Path(context['pluginPath'])) == _safe_path(Path(plugin_path)),
                      'strict_bridge_rule_plugin_changed')
        prepared = strict.prepare(source_bytes, anchor_bytes, policy_bytes, rubric_bytes, group, request_limits=limits, diagnostic_context=diagnostic_context, rule_preflight=rules,
            rule_context=read('rule-context.json')[0] if rules is not None else None)
        dispatch_proofs={}
        if repair is not None:strict.validate_repair(prepared,manifest['candidateId'],manifest['revisionId'],repair)
        if repair is not None and 'languagePluginRepair' in repair:
            from scripts.sermon_historical_layer2 import validate_repair_return
            read('language-plugin-repair.json')
            for role in ('translator','reviewer'):
                returned,_=read(role+'-historical-return-proof.json')
                validate_repair_return(root,repair,role,returned)
                proof,_=read(role+'-historical-dispatch-proof.json')
                c.require(proof.get('schemaVersion')=='sermon-language-repair-dispatch-v1' and
                    proof.get('repairContextSha256')==c.canonical_sha256(repair['languagePluginRepair']) and
                    proof.get('enforcementScope')=='new_provider_ledger_historical_parent_repair',
                    'strict_bridge_language_repair_proof_changed')
                dispatch_proofs[role]=proof
        if (root/'historical-rebind.json').exists():
            from scripts.sermon_historical_layer2 import validate_rebind
            proof,_=read('historical-rebind.json');validate_rebind(prepared,root,proof)
        for key, value in strict.common_identity(prepared, manifest['candidateId'], manifest['revisionId']).items():
            c.require(manifest[key] == value, 'strict_bridge_current_identity_changed')
        for data, key in ((source_bytes, 'sourcePackageBytesSha256'),
                          (anchor_bytes, 'anchorBytesSha256'), (policy_bytes, 'policyBytesSha256')):
            c.require(c.bytes_sha256(data) == manifest[key], 'strict_bridge_input_bytes_changed')
        c.require(group['translationGroupId'] not in seen, 'strict_bridge_duplicate_group')
        seen.add(group['translationGroupId'])
        inputs, _ = read('review-input.json')
        c.require(inputs == strict.input_manifest(prepared, manifest, artifact_bytes),
                  'strict_bridge_input_manifest_changed')
        suffix = '' if attempt == 1 else '-' + str(attempt)
        receipt, receipt_bytes = read('review-receipt' + suffix + '.json')
        c.validate_review_binding(receipt, manifest, rubric, inputs)
        c.require(receipt['executionStatus'] == 'succeeded' and receipt['reviewVerdict'] == 'pass',
                  'strict_bridge_review_not_passed')
        results = {}
        for role, stem in (('translator', 'generator'), ('reviewer', 'reviewer' + suffix)):
            result, data = read(stem + '.json')
            raw, _ = read(stem + '.raw.json')
            call, _ = read(stem + '.call.json')
            strict.require_call_binding(root / (stem + '.json'), result)
            c.require(result['model'] == policy[role]['model'], 'strict_bridge_actual_model_changed')
            # Bind persisted request identity to the current immutable inputs.
            prompt = (strict.generation_prompt(prepared, repair) if role=='translator' else
                      strict.prompt(prepared, role, candidate=artifact, input_manifest=inputs))
            payload = strict._payload(prepared, role, prompt)
            if role in dispatch_proofs:
                proof=dispatch_proofs[role]
                c.require(set(proof)=={'schemaVersion','enforcementScope','role','repairContextSha256','newPlanRef',
                    'payloadSha256','requestLimits','productionEligible'} and proof['role']==role and
                    proof['newPlanRef']==repair['languagePluginRepair']['specification']['newPlanRef'] and
                    proof['payloadSha256']==c.canonical_sha256(payload) and proof['requestLimits']==limits and
                    proof['productionEligible'] is False,'strict_bridge_language_repair_proof_changed')
            c.require(result['payloadSha256'] == c.canonical_sha256(payload),
                      'strict_bridge_request_payload_changed')
            if role == 'translator':
                c.require(result['result'] == artifact and
                    manifest['generationReceiptRef'] == strict.reference('generation', data),
                    'strict_bridge_generation_changed')
            else:
                ref = strict.reference('review-result', data)
                expected = strict.review_result(result['result'], manifest, ref)
                c.require(all(receipt[k] == v for k, v in expected.items()) and
                    receipt['evidenceRefs'] == [ref] and receipt['modelCallId'] == call['modelCallId'] and
                    receipt['reviewerModelActual'] == result['model'] and
                    receipt['providerResponseId'] == result['requestId'], 'strict_bridge_review_proof_changed')
            generation[role]['requestIds'].append(result['requestId'])
            results[role] = result
        c.require(results['translator']['requestId'] != results['reviewer']['requestId'],
                  'strict_bridge_response_identity_reused')
        # Public schema preserves text exactly; evidence names the private receipt.
        groups.append({**copy.deepcopy(artifact), 'semanticReview': {
            'status': 'pass', 'checks': {row['checkId']: row['result'] for row in receipt['checks']},
            'evidence': 'Strict Review Receipt canonical SHA-256: ' + c.canonical_sha256(receipt),
            'uncertainty': [], 'issues': []},
            'translatorRequestId': results['translator']['requestId'],
            'reviewerRequestId': results['reviewer']['requestId']})
        for name, data in captured.items():
            c.require(c.read_snapshot(root / name)[1] == data, 'strict_bridge_snapshot_changed')
        snapshots.append((root, captured))
        bindings.append({'workUnitId': prepared['workUnitId'], 'candidateId': manifest['candidateId'],
            'revisionId': manifest['revisionId'], 'reviewAttemptNumber': attempt,
            'artifacts': {name: strict.reference(name, data) for name, data in captured.items()}})
    translator_ids, reviewer_ids = [generation[role]['requestIds'] for role in ('translator', 'reviewer')]
    c.require(len(set(translator_ids + reviewer_ids)) == len(translator_ids + reviewer_ids),
              'strict_bridge_response_identity_reused')
    evidence = {**request, 'generation': generation, 'groups': groups}
    c.require(len(rule_receipts) in (0, len(revisions))
        and len({c.canonical_sha256(item) for item in rule_receipts}) <= 1,
        'strict_bridge_rule_preflight_changed')
    actual_plan = [{k: row[k] for k in ('translationGroupId', 'sourceUnitIds')} for row in groups]
    c.require(all(c.decode_json(captured['rule-context.json'])['groupPlan'] == actual_plan
                  for _, captured in snapshots if 'rule-context.json' in captured),
              'strict_bridge_rule_group_plan_changed')
    rule_receipt = rule_receipts[0] if rule_receipts else None
    plugin = producer.run_language_plugin(source, anchor, policy, request, evidence,
        Path(plugin_path), expected_plugin_sha256, strict_rubric=rubric, diagnostic_context=diagnostic_context,
        rule_preflight_receipt=rule_receipt)
    # Retain the actual result only after rechecking the evidence it assessed.
    for root, captured in snapshots:
        for name, data in captured.items():
            c.require(c.read_snapshot(root / name)[1] == data, 'strict_bridge_snapshot_changed')
    if any(row['status'] != 'pass' for row in plugin['groupReviews']):
        raise LanguagePluginRejected(plugin, bindings)
    if rule_receipt is not None:
        from scripts.target_language_rule_preflight import verify_consumer_receipt
        verify_consumer_receipt(request, policy, Path(plugin_path), evidence, rule_receipt)
    candidate_groups = []
    for group, result in zip(groups, plugin['groupReviews']):
        candidate_groups.append({**{k: copy.deepcopy(v) for k, v in group.items()
            if k not in ('translatorRequestId', 'reviewerRequestId')},
            'targetText': ''.join(group['targetUtterances']),
            'languageReview': {'status': result['status'], 'pluginId': plugin['pluginId'],
                'policySha256': plugin['languageReviewPolicySha256'], 'checks': result['checks']}})
    candidate = {'schemaVersion': handoff.CANDIDATE_SCHEMA, 'sourceLocale': 'en',
        **{k: request[k] for k in ('targetLocale', 'englishSourcePackageJsonSha256',
                                   'anchorManifestSha256', 'translationPolicySha256')},
        'status': 'machine_review_pass_human_review_pending', 'releaseEligible': False,
        'generation': generation, 'groups': candidate_groups,
        'modelReview': {'status': 'pass', 'reviewedGroupIds': [g['translationGroupId'] for g in groups]},
        'humanReview': {'translation': 'pending', 'reviewer': None, 'reviewedAt': None, 'reviewedGroupIds': []}}
    handoff._validate_schema(candidate, 'sermon-target-language-candidate-v2.schema.json', 'strict public candidate')
    handoff.validate_target_candidate(source, anchor, candidate, require_human_approval=False, diagnostic_context=diagnostic_context)
    handoff.validate_policy_binding(candidate, policy, strict_rubric=rubric, diagnostic_context=diagnostic_context)
    for root, captured in snapshots:
        for name, data in captured.items():
            c.require(c.read_snapshot(root / name)[1] == data, 'strict_bridge_snapshot_changed')
    return {'candidate': candidate, 'languageReceipt': plugin, 'revisionBindings': bindings,
            'executionAuthority': 'none', 'admissionStatus': 'waiting_human'}


def validate_approved_chain(source_bytes, anchor_bytes, policy_bytes, rubric_bytes,
                            revisions, *, candidate, human_receipt, plugin_path, expected_plugin_sha256):
    """Recompute the machine/plugin chain and validate independently supplied approval.

    This returns evidence, never an admission token. Call again under the same
    authoritative lock/CAS boundary to prevent a stale identity dispatch.
    """
    result = compile_candidate(source_bytes, anchor_bytes, policy_bytes, rubric_bytes,
        revisions, plugin_path=plugin_path, expected_plugin_sha256=expected_plugin_sha256)
    pending = result['candidate']
    c.require(type(candidate) is dict and set(candidate) == set(pending) and
        all(candidate[k] == pending[k] for k in pending if k not in ('status', 'humanReview')),
        'strict_bridge_public_candidate_changed')
    source, anchor, policy, rubric = [c.decode_json(b) for b in
        (source_bytes, anchor_bytes, policy_bytes, rubric_bytes)]
    handoff._validate_schema(candidate, 'sermon-target-language-candidate-v2.schema.json', 'approved candidate')
    released = handoff.validate_released_candidate(source, anchor, candidate, human_receipt)
    handoff.validate_policy_binding(candidate, policy, strict_rubric=rubric)
    return {**result, 'candidate': copy.deepcopy(candidate),
        'humanReceiptSha256': c.canonical_sha256(human_receipt), 'textPolicy': released['textPolicy'],
        'publicCandidateSha256': c.canonical_sha256(candidate), 'admissionStatus': 'validated_only'}
