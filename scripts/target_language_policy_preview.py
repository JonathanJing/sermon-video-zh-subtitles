"""Freeze actual model inputs; compare revisions without granting reuse/approval."""
from __future__ import annotations
import argparse
import copy
import json
import os
from pathlib import Path

try:
    from scripts.target_language_policy import canonical_sha256
except ImportError:
    from target_language_policy import canonical_sha256

SCHEMA = 'sermon-target-language-consumed-policy-v1'


def freeze_payload_preview(role: str, payload: dict, policy: dict, path: Path) -> dict:
    if role not in {'translator', 'reviewer'}:
        raise ValueError('Unknown model role')
    # This is the very payload passed to the provider, after request limits.
    preview = {'schemaVersion': SCHEMA, 'role': role,
               'payload': copy.deepcopy(payload), 'payloadSha256': canonical_sha256(payload),
               'policy': copy.deepcopy(policy), 'policySha256': canonical_sha256(policy),
               'humanApproval': False, 'status': 'input_frozen_not_execution_evidence'}
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if json.loads(path.read_text(encoding='utf-8')) != preview:
            raise ValueError(f'Frozen model input changed: {path}')
    else:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(preview, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
    return preview


def _changes(old, new, path=''):
    if isinstance(old, dict) and isinstance(new, dict):
        result = []
        for key in sorted(set(old) | set(new)):
            child = path + '/' + key
            if key not in old or key not in new:
                result.append(child)
            else:
                result.extend(_changes(old[key], new[key], child))
        return result
    if isinstance(old, list) and isinstance(new, list) and len(old) == len(new):
        return [child for i, (before, after) in enumerate(zip(old, new))
                for child in _changes(before, after, path + "/" + str(i))]
    return [] if old == new else [path]


def compare_previews(old: dict, new: dict, *, prior_outcome: str = 'unknown') -> dict:
    for preview in (old, new):
        if (preview.get('schemaVersion') != SCHEMA
                or preview.get('payloadSha256') != canonical_sha256(preview.get('payload'))
                or preview.get('policySha256') != canonical_sha256(preview.get('policy'))):
            raise ValueError('Preview identity changed')
    if old['role'] != new['role']:
        raise ValueError('Cannot compare different model roles')
    payload_changes = _changes(old['payload'], new['payload'])
    policy_changes = _changes(old['policy'], new['policy'])
    meaningful = [p for p in policy_changes if not p.startswith('/componentSha256/')]
    plugin_fields = {'/languageReview/pluginImplementationSha256', '/languageReview/pluginId',
                     '/languageReview/implementationStatus', '/languageReview/requiredChecks'}
    approval_fields = {'/sourceScope/termApprovalReceipt/reviewedBy',
                       '/sourceScope/termApprovalReceipt/reviewedAt',
                       '/sourceScope/termApprovalReceipt/userStatement',
                       '/sourceScope/termApprovalEvidence'}
    if payload_changes or any(p not in plugin_fields | approval_fields for p in meaningful):
        kind = 'content_modified'
        # A reviewer-only configuration/instruction edit starts at review.
        # Changed shared inputs or policy can invalidate translation too.
        reviewer_only = (new['role'] == 'reviewer'
                         and all(p.startswith('/reviewer/') for p in meaningful)
                         and all(p in {'/model', '/reasoning_effort', '/messages/0/content'}
                                 for p in payload_changes))
        closure = (['translator', 'reviewer', 'language_plugin', 'candidate', 'human_review', 'audio', 'release']
                   if not reviewer_only else
                   ['reviewer', 'language_plugin', 'candidate', 'human_review', 'audio', 'release'])
    elif any(p in plugin_fields for p in meaningful):
        kind = 'plugin_only_migration'
        closure = ['language_plugin', 'candidate', 'approval_binding', 'audio_binding', 'release_binding']
    elif meaningful:
        kind = 'approval_rebinding'
        closure = ['approval_binding', 'candidate_binding', 'audio_binding', 'release_binding']
    else:
        kind, closure = 'unchanged', []
    blocked = prior_outcome != 'succeeded'
    return {'schemaVersion': 'sermon-target-language-policy-change-plan-v1',
            'classification': kind, 'role': new['role'],
            'changedPayloadPaths': payload_changes, 'changedPolicyPaths': policy_changes,
            'dependencyClosure': closure, 'priorOutcome': prior_outcome,
            'blockedByPriorOutcome': blocked, 'modelPayloadUnchanged': not payload_changes,
            'automaticReuseAuthorized': False, 'humanApproval': False,
            'requiredAction': ('reconcile_original_outcome' if blocked else 'validate_revision_dependencies')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--after', type=Path, required=True)
    # Intentionally no outcome override on the inspection CLI. A preview does
    # not establish that a model or plugin passed.
    args = parser.parse_args()
    print(json.dumps(compare_previews(json.loads(args.before.read_text()),
                                     json.loads(args.after.read_text())), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
