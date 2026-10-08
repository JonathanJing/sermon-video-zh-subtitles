"""Private RQC D1 contracts. Validation is evidence checking, never admission.

Canonical JSON v1 = UTF-8, sorted object keys, compact separators, no NaN,
no Unicode normalization, array order preserved. Byte hashes are separate.
Receipt content hashes exclude ONLY receiptSha256, avoiding self-reference.
Artifact references are opaque identities; this module never opens their IDs.
"""
from __future__ import annotations

from datetime import datetime
from functools import lru_cache
import hashlib
import json
import math
import os
import re
from pathlib import Path
import stat

from jsonschema import Draft202012Validator, FormatChecker, validators

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 256 * 1024
HARD_CHECKS = frozenset({'completeMeaning', 'negationsNumbersNames', 'quotationAttribution', 'noAddedMeaning'})
VERSIONS = frozenset({'sermon-candidate-revision-v1', 'sermon-review-receipt-v1',
    'sermon-review-gate-decision-v1', 'sermon-review-repair-plan-v1',
    'sermon-review-rubric-v1', 'sermon-review-input-manifest-v1'})


class ContractError(ValueError):
    """Fixed error codes only, without private text or provider exception bodies."""


def require(condition, code):
    if not condition: raise ContractError(code)


def canonical_bytes(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise ContractError('invalid_json_value') from exc


def canonical_sha256(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def bytes_sha256(value):
    require(type(value) is bytes, 'expected_file_bytes')
    return hashlib.sha256(value).hexdigest()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate_json_key')
        result[key] = value
    return result


def decode_json(data, *, max_bytes=MAX_BYTES):
    require(type(data) is bytes and len(data) <= max_bytes, 'private_contract_size_limit')
    try:
        return json.loads(data.decode('utf-8'), object_pairs_hook=_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ContractError('nonfinite_json_number')))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ContractError('invalid_json_bytes') from exc


def read_snapshot(path, *, max_bytes=MAX_BYTES):
    """Read a caller-selected regular file; no paths are accepted from receipts."""
    require(type(max_bytes) is int and 0 < max_bytes, 'invalid_snapshot_limit')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_size <= max_bytes, 'invalid_snapshot_file')
        with os.fdopen(os.dup(fd), 'rb') as stream: data = stream.read(max_bytes + 1)
        after = os.fstat(fd); named = os.stat(path, follow_symlinks=False)
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        require(identity(before) == identity(after) == identity(named), 'snapshot_changed_during_read')
        value = decode_json(data, max_bytes=max_bytes)
        return value, data
    finally:
        os.close(fd)


def _strict_json(value):
    if type(value) is dict: return all(type(k) is str and _strict_json(v) for k,v in value.items())
    if type(value) is list: return all(_strict_json(v) for v in value)
    return value is None or type(value) in (str, int, bool) or type(value) is float and math.isfinite(value)


@lru_cache(maxsize=8)
def validator(version):
    require(isinstance(version, str) and (version in VERSIONS or version == 'sermon-target-language-policy-v3'), 'unsupported_review_contract')
    schema = json.loads((ROOT/'schemas'/(version+'.schema.json')).read_text())
    Draft202012Validator.check_schema(schema)
    checker = FormatChecker()
    @checker.checks('date-time', raises=(ValueError, TypeError))
    def utc(value):
        return isinstance(value,str) and value.endswith('Z') and datetime.fromisoformat(value).tzinfo is not None
    cls = validators.extend(Draft202012Validator, type_checker=Draft202012Validator.TYPE_CHECKER.redefine('integer', lambda _,v:type(v) is int))
    return cls(schema, format_checker=checker)


def receipt_sha256(receipt):
    return canonical_sha256({k:v for k,v in receipt.items() if k != 'receiptSha256'})


def _review_semantics(row):
    require(row['receiptSha256'] == receipt_sha256(row), 'review_receipt_hash_mismatch')
    checks = row['checks']; check_ids = [c['checkId'] for c in checks]
    require(len(check_ids) == len(set(check_ids)), 'duplicate_review_check')
    issue_ids = [i['issueId'] for i in row['issues']]
    require(len(issue_ids) == len(set(issue_ids)), 'duplicate_review_issue')
    coverage = row['coverage']; expected = set(coverage['expectedUnitIds'])
    assessed, unassessed = set(coverage['assessedUnitIds']), set(coverage['unassessedUnitIds'])
    require(not assessed & unassessed and assessed | unassessed == expected, 'review_coverage_partition_mismatch')
    require(all(set(i['sourceUnitIds']) <= expected for i in row['issues']), 'issue_outside_source_scope')
    for key in ('reviewerModelActual','providerResponseId'):
        require(row[key] is not None or key in row['missingReasons'], 'missing_provider_null_reason')
    succeeded = row['executionStatus'] == 'succeeded'
    if not succeeded:
        require(row['reviewVerdict'] == 'not_assessed' and not assessed and
                all(c['result'] == 'not_assessed' for c in checks) and not row['issues'], 'execution_failure_is_not_content_failure')
        return
    require(row['reviewerModelActual'] == row['reviewerModelRequested'], 'review_model_identity_mismatch')
    require(set(check_ids) == HARD_CHECKS, 'required_review_check_missing')
    require(all(c['result'] == 'not_assessed' or c['evidenceRefs'] for c in checks), 'review_check_evidence_missing')
    if row['reviewVerdict'] == 'pass':
        require(not unassessed and not row['issues'] and all(c['result'] == 'pass' for c in checks), 'unsupported_content_pass')
    elif row['reviewVerdict'] == 'needs_rework':
        require(bool(row['issues']) and any(i['severity'] != 'uncertain' for i in row['issues']), 'rework_requires_known_content_issue')
    elif row['reviewVerdict'] == 'inconclusive':
        require(bool(unassessed) or any(c['result'] == 'not_assessed' for c in checks)
                or any(i['severity'] == 'uncertain' for i in row['issues']), 'inconclusive_evidence_missing')
    else:
        require(not assessed and all(c['result'] == 'not_assessed' for c in checks), 'not_assessed_has_assessment')


def validate_gate_admission(admission_status, reason_codes, allowed_next_actions):
    """Enforce the public admission/action relationship shared by receipts and observations."""
    actions = set(allowed_next_actions)
    if admission_status == 'admitted':
        require(actions == {'prepare_layer3'} and reason_codes == ['all_required_evidence_passed'],
                'admitted_gate_evidence_missing')
    else:
        require('prepare_layer3' not in actions, 'blocked_gate_cannot_prepare_layer3')


def validate_contract(value):
    require(type(value) is dict and _strict_json(value), 'invalid_review_contract_value')
    require(len(canonical_bytes(value)) <= MAX_BYTES, 'private_contract_size_limit')
    version = value.get('schemaVersion')
    require(isinstance(version, str) and version in VERSIONS, 'unsupported_review_contract')
    require(next(validator(version).iter_errors(value),None) is None, 'invalid_review_contract_schema')
    refs = {}
    def inspect_refs(item):
        if isinstance(item, dict):
            if set(item) == {'artifactId','canonicalJsonSha256','fileBytesSha256','mediaType'}:
                previous = refs.setdefault(item['artifactId'], item)
                require(previous == item, 'conflicting_artifact_reference')
            for child in item.values(): inspect_refs(child)
        elif isinstance(item, list):
            for child in item: inspect_refs(child)
    inspect_refs(value)
    if version == 'sermon-candidate-revision-v1':
        require(value['artifactSha256'] == value['artifactCanonicalJsonSha256'], 'candidate_hash_alias_conflict')
        initial = value['revisionNumber'] == 1
        require((value['parentRevisionId'] is None) == initial and (value['repairPlanId'] is None) == initial, 'revision_lineage_incomplete')
        require(value['parentRevisionId'] != value['revisionId'], 'revision_self_parent')
        require(len(value['workUnitIds']) == 1, 'initial_revision_scope_is_one_translation_group')
    elif version == 'sermon-review-receipt-v1': _review_semantics(value)
    elif version == 'sermon-review-rubric-v1':
        require(set(value['requiredChecks']) == HARD_CHECKS, 'rubric_hard_checks_changed')
    elif version == 'sermon-review-gate-decision-v1':
        validate_gate_admission(value['admissionStatus'], value['reasonCodes'], value['allowedNextActions'])
        if value['admissionStatus'] == 'admitted':
            require(value['reviewReceiptRefs'] and value['approvalReceiptRefs'], 'admitted_gate_evidence_missing')
    elif version == 'sermon-review-repair-plan-v1':
        if value['repairAction'] == 'repair_translation':
            require(value['fromRevisionId'] != value['toRevisionId'], 'content_repair_requires_new_revision')
        else:
            require(value['fromRevisionId'] == value['toRevisionId'], 'noncontent_action_cannot_revise_candidate')
    return value


def validate_candidate_artifact(manifest, artifact_bytes):
    validate_contract(manifest)
    require(manifest['schemaVersion'] == 'sermon-candidate-revision-v1', 'expected_candidate_revision')
    artifact = decode_json(artifact_bytes)
    require(manifest['artifactBytesSha256'] == bytes_sha256(artifact_bytes)
            and manifest['artifactSha256'] == canonical_sha256(artifact), 'candidate_artifact_hash_mismatch')
    require(type(artifact) is dict and set(artifact) == {'translationGroupId','sourceUnitIds','targetUtterances','coverage'}, 'invalid_frozen_group_artifact')
    require(type(artifact['translationGroupId']) is str and
            re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}', artifact['translationGroupId']) is not None, 'invalid_translation_group_id')
    require(artifact['sourceUnitIds'] == manifest['sourceUnitIds'] and
            manifest['workUnitIds'] == ['l2.' + manifest['targetLocale'] + '.' + artifact['translationGroupId']], 'candidate_group_scope_mismatch')
    texts = artifact['targetUtterances']
    require(type(texts) is list and 1 <= len(texts) <= 64 and
            all(type(text) is str and text.strip() and len(text) <= 16384 for text in texts), 'invalid_candidate_utterances')
    target_ids = [manifest['workUnitIds'][0] + '.utterance.' + str(i+1).zfill(4) for i in range(len(texts))]
    require(manifest['targetUnitIds'] == target_ids, 'candidate_target_unit_mapping_mismatch')
    coverage = artifact['coverage']
    require(type(coverage) is list and len(coverage) == len(manifest['sourceUnitIds']) and
            all(type(row) is dict and set(row) == {'sourceUnitId','targetText'} for row in coverage), 'invalid_candidate_coverage')
    require([row['sourceUnitId'] for row in coverage] == manifest['sourceUnitIds'], 'candidate_source_coverage_mismatch')
    compact = lambda text: re.sub(r'\s+', '', text)
    actual_text = compact(''.join(texts))
    require(all(type(row['targetText']) is str and row['targetText'].strip() and
                compact(row['targetText']) in actual_text for row in coverage), 'candidate_coverage_text_not_present')
    return artifact


def validate_review_binding(review, candidate, rubric, input_manifest):
    """Validate matching snapshots; a successful return is NOT a Gate Decision."""
    for value in (review,candidate,rubric,input_manifest): validate_contract(value)
    require([v['schemaVersion'] for v in (review,candidate,rubric,input_manifest)] ==
            ['sermon-review-receipt-v1','sermon-candidate-revision-v1','sermon-review-rubric-v1','sermon-review-input-manifest-v1'], 'wrong_binding_contract_types')
    for key in ('candidateId','revisionId','targetLocale','workUnitIds','sourceIdentitySha256','sourcePackageSha256','anchorSha256','policySha256'):
        require(review[key] == candidate[key] == input_manifest[key], 'review_binding_mismatch')
    require(review['reviewedArtifactSha256'] == candidate['artifactSha256'] == input_manifest['reviewedArtifactSha256'], 'reviewed_artifact_mismatch')
    require(review['rubricSha256'] == input_manifest['rubricSha256'] == canonical_sha256(rubric)
            and rubric['targetLocale'] == candidate['targetLocale'], 'rubric_binding_mismatch')
    require(review['reviewerInputManifestSha256'] == canonical_sha256(input_manifest)
            and review['reviewerPromptVersion'] == input_manifest['reviewerPromptVersion'], 'review_input_binding_mismatch')
    require(review['coverage']['expectedUnitIds'] == candidate['sourceUnitIds'] == input_manifest['sourceUnitIds'], 'review_expected_coverage_mismatch')
    require(all(set(issue['targetUnitIds']) <= set(candidate['targetUnitIds']) for issue in review['issues']), 'issue_outside_target_scope')
    refs = input_manifest['materialRefs']
    for kind,key in [('candidate','artifactSha256'),('englishSource','sourcePackageSha256'),('anchor','anchorSha256'),('policy','policySha256')]:
        require(refs[kind]['canonicalJsonSha256'] == candidate[key], 'input_material_canonical_hash_mismatch')
    for kind,key in [('candidate','artifactBytesSha256'),('englishSource','sourcePackageBytesSha256'),('anchor','anchorBytesSha256'),('policy','policyBytesSha256')]:
        require(refs[kind]['fileBytesSha256'] == candidate[key], 'input_material_bytes_hash_mismatch')
    require(refs['rubric']['canonicalJsonSha256'] == canonical_sha256(rubric), 'input_rubric_material_mismatch')
    return {'bindingStatus':'consistent', 'reviewVerdict':review['reviewVerdict'], 'admissionStatus':None,
            'executionAuthority':'none'}


def validate_repair_binding(plan, review, candidate):
    for value in (plan,review,candidate): validate_contract(value)
    require([v['schemaVersion'] for v in (plan,review,candidate)] ==
            ['sermon-review-repair-plan-v1','sermon-review-receipt-v1','sermon-candidate-revision-v1'], 'wrong_repair_contract_types')
    require(plan['triggerReviewId'] == review['reviewId'] and plan['triggerReceiptSha256'] == review['receiptSha256'], 'repair_trigger_mismatch')
    for key in ('candidateId','targetLocale','sourceIdentitySha256','sourcePackageSha256','anchorSha256','policySha256'):
        require(plan[key] == review[key] == candidate[key], 'repair_object_binding_mismatch')
    require(plan['rubricSha256'] == review['rubricSha256'] and
            plan['fromRevisionId'] == review['revisionId'] == candidate['revisionId'] and
            review['reviewedArtifactSha256'] == candidate['artifactSha256'], 'repair_revision_binding_mismatch')
    require(set(candidate['workUnitIds']) <= set(plan['affectedWorkUnitIds']), 'repair_scope_omits_failed_unit')
    issue_codes = {issue['reasonCode'] for issue in review['issues']}
    plan_reasons = set(plan['reasonCodes'])
    if plan['repairAction'] == 'repair_translation':
        require(review['executionStatus'] == 'succeeded' and review['reviewVerdict'] == 'needs_rework', 'content_repair_requires_content_failure')
        require(plan_reasons <= issue_codes, 'repair_reason_not_in_review')
        require(not plan_reasons & {'source_ambiguity','evidence_insufficient','contradictory_reviews'},
                'content_repair_reason_requires_escalation')
    elif plan['repairAction'] == 'retry_review':
        require(review['executionStatus'] in {'failed','cancelled'} and review['reviewVerdict'] == 'not_assessed', 'review_retry_requires_known_execution_failure')
        require(plan_reasons == {'review_execution_failed'}, 'review_retry_reason_mismatch')
    elif plan['repairAction'] == 'request_source_review':
        require(review['executionStatus'] == 'succeeded' and review['reviewVerdict'] in {'needs_rework','inconclusive'}
                and 'source_ambiguity' in issue_codes, 'source_review_requires_source_ambiguity')
        require(plan_reasons <= issue_codes and 'source_ambiguity' in plan_reasons, 'repair_reason_not_in_review')
    elif plan['repairAction'] == 'request_human_review':
        require(review['executionStatus'] == 'succeeded' and review['reviewVerdict'] in {'needs_rework','inconclusive'},
                'human_review_requires_unresolved_review')
        require(plan_reasons <= issue_codes, 'repair_reason_not_in_review')
    elif plan['repairAction'] == 'escalate_engineering':
        require(review['executionStatus'] in {'failed','cancelled'} and review['reviewVerdict'] == 'not_assessed',
                'engineering_escalation_requires_execution_failure')
        require(plan_reasons == {'review_execution_failed'}, 'engineering_escalation_reason_mismatch')
    else:
        # Timing and synthesis evidence is outside the semantic review receipt;
        # this binding cannot authorize those actions without their own evidence.
        require(False, 'repair_action_requires_nonreview_evidence')
    require(review['executionStatus'] != 'outcome_unknown', 'unknown_outcome_requires_reconciliation')
    return {'bindingStatus':'consistent','executionAuthority':'none'}


def validate_revision_lineage(candidate, parent=None, repair=None):
    validate_contract(candidate)
    require(candidate['schemaVersion'] == 'sermon-candidate-revision-v1', 'expected_candidate_revision')
    if candidate['revisionNumber'] == 1:
        require(parent is None and repair is None, 'initial_revision_has_parent')
        return
    require(parent is not None and repair is not None, 'revision_lineage_receipts_missing')
    validate_contract(parent); validate_contract(repair)
    require(parent['schemaVersion'] == 'sermon-candidate-revision-v1' and
            repair['schemaVersion'] == 'sermon-review-repair-plan-v1', 'wrong_revision_lineage_contract_types')
    for key in ('candidateId','targetLocale','sourceIdentitySha256','sourcePackageSha256','anchorSha256','policySha256'):
        require(repair[key] == parent[key] == candidate[key], 'revision_repair_object_binding_mismatch')
    # Initial rollout revisions and plans are scoped to exactly one translation group.
    require(set(repair['affectedWorkUnitIds']) == set(parent['workUnitIds']) == set(candidate['workUnitIds']),
            'revision_repair_scope_mismatch')
    require(candidate['parentRevisionId'] == parent['revisionId'] == repair['fromRevisionId'] and
            candidate['revisionId'] == repair['toRevisionId'] and candidate['repairPlanId'] == repair['repairPlanId']
            and candidate['revisionNumber'] == parent['revisionNumber'] + 1
            and repair['repairAction'] == 'repair_translation', 'revision_lineage_binding_mismatch')
    for key in ('candidateId','targetLocale','workUnitIds','sourceIdentitySha256','sourcePackageSha256','anchorSha256','policySha256','sourceUnitIds',
                'sourcePackageBytesSha256','anchorBytesSha256','policyBytesSha256'):
        require(candidate[key] == parent[key], 'revision_changes_frozen_source_or_policy')
