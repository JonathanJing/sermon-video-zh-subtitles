"""Finite structural findings from reviewer data, never exception messages.

The caller binds this finding to private response/input snapshots. Paths contain
only declared contract fields and bounded array indexes, never returned keys.
"""
from jsonschema import Draft202012Validator

SCHEMA = 'sermon-strict-review-structural-diagnostic-v1'
FIELDS = frozenset({'reviewedArtifactSha256', 'reviewVerdict', 'checks', 'issues',
    'assessedUnitIds', 'unassessedUnitIds', 'checkId', 'result', 'evidence',
    'issueId', 'reasonCode', 'severity', 'sourceUnitIds', 'targetUnitIds'})
REASONS = frozenset({'invalid_response_envelope', 'invalid_json', 'invalid_fields',
    'invalid_enum', 'invalid_field_type', 'invalid_field_bounds', 'invalid_field_value',
    'changed_reviewed_artifact', 'duplicate_check', 'duplicate_issue',
    'check_coverage_mismatch', 'coverage_partition_mismatch', 'invalid_evidence',
    'unsupported_pass', 'rework_evidence_missing', 'inconclusive_evidence_missing',
    'not_assessed_has_assessment', 'review_validation_failed'})


def finding(reason, path=()):
    if reason not in REASONS:
        raise ValueError('invalid_safe_review_reason')
    safe = []
    for part in path:
        if type(part) is str and part in FIELDS:
            safe.append(part)
        elif type(part) is int and 0 <= part <= 64:
            safe.append(part)
        else:
            break
    return {'reasonCode': reason, 'fieldPath': safe}


def classify(result, schema, expected_ids, required_checks):
    """Use trusted contract constraints and data; do not inspect error text."""
    error = next(Draft202012Validator(schema).iter_errors(result), None)
    if error is not None:
        rule = error.validator
        path = list(error.absolute_path)
        reason = {'required': 'invalid_fields', 'additionalProperties': 'invalid_fields',
            'enum': 'invalid_enum', 'type': 'invalid_field_type',
            'minItems': 'invalid_field_bounds', 'maxItems': 'invalid_field_bounds',
            'minLength': 'invalid_field_bounds', 'maxLength': 'invalid_field_bounds',
            'uniqueItems': 'invalid_field_value'}.get(rule, 'invalid_field_value')
        if rule == 'const' and path == ['reviewedArtifactSha256']:
            reason = 'changed_reviewed_artifact'
        if rule == 'required' and type(error.instance) is dict:
            missing=next((key for key in error.validator_value if key not in error.instance),None)
            if missing in FIELDS:path.append(missing)
        return finding(reason, path)
    # Only schema-valid data reaches semantic checks, making all set operations
    # safe even when a provider returns arbitrary nested JSON values.
    checks = result['checks']; issues = result['issues']
    for collection, key, reason in ((checks, 'checkId', 'duplicate_check'),
                                   (issues, 'issueId', 'duplicate_issue')):
        ids = [row[key] for row in collection]
        if len(ids) != len(set(ids)):
            return finding(reason, ['checks' if key == 'checkId' else 'issues'])
        for i, row in enumerate(collection):
            if not row['evidence'].strip():
                return finding('invalid_evidence', ['checks' if key == 'checkId' else 'issues', i, 'evidence'])
    if {row['checkId'] for row in checks} != set(required_checks):
        return finding('check_coverage_mismatch', ['checks'])
    assessed = set(result['assessedUnitIds']); unassessed = set(result['unassessedUnitIds'])
    if assessed & unassessed or assessed | unassessed != set(expected_ids):
        return finding('coverage_partition_mismatch')
    verdict = result['reviewVerdict']
    if verdict == 'pass' and (unassessed or issues or any(row['result'] != 'pass' for row in checks)):
        return finding('unsupported_pass', ['reviewVerdict'])
    if verdict == 'needs_rework' and (not issues or all(row['severity'] == 'uncertain' for row in issues)):
        return finding('rework_evidence_missing', ['reviewVerdict'])
    if verdict == 'inconclusive' and not (unassessed or any(row['result'] == 'not_assessed' for row in checks)
                                         or any(row['severity'] == 'uncertain' for row in issues)):
        return finding('inconclusive_evidence_missing', ['reviewVerdict'])
    if verdict == 'not_assessed' and (assessed or any(row['result'] != 'not_assessed' for row in checks)):
        return finding('not_assessed_has_assessment', ['reviewVerdict'])
    return finding('review_validation_failed')
