"""Frozen complete-cache inputs for durable spoken revisions; never calls a model."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import run_target_language_models as models
from scripts import sermon_workflow_jobs as jobs
from scripts.sermon_release_workflow import _safe_path

SCHEMA = 'sermon-canonical-spoken-cache-manifest-v1'
IDENTITY_KEYS = ('schemaVersion', 'sourceLocale', 'targetLocale',
                 'englishSourcePackageJsonSha256', 'anchorManifestSha256',
                 'translationPolicySha256', 'sourceUnits')


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def file_sha(path):
    return hashlib.sha256(_safe_path(path).read_bytes()).hexdigest()


def read_manifest(path):
    value = jobs._read(_safe_path(path))
    require(isinstance(value, dict) and set(value) == {
        'schemaVersion', 'requestJsonSha256', 'evidenceJsonSha256', 'files'}
        and value['schemaVersion'] == SCHEMA and isinstance(value['files'], dict)
        and {'request.json', 'evidence.json'} <= set(value['files']),
        'invalid_spoken_cache_manifest')
    for name, digest in value['files'].items():
        require(isinstance(name, str) and Path(name).name == name
                and isinstance(digest, str) and len(digest) == 64
                and all(c in '0123456789abcdef' for c in digest),
                'invalid_spoken_cache_manifest_entry')
    return value


def complete_cache(root):
    """Validate actual completed raw replies against parsed caches and evidence."""
    models.require_reconciled_requests(root)
    request, evidence = (jobs._read(_safe_path(root / name))
                         for name in ('request.json', 'evidence.json'))
    require(all(evidence.get(key) == request.get(key) for key in IDENTITY_KEYS),
            'spoken_prior_evidence_request_mismatch')
    groups = evidence.get('groups')
    require(isinstance(groups, list) and groups, 'spoken_prior_complete_evidence_required')
    names = ['request.json', 'evidence.json']
    for index, group in enumerate(groups, 1):
        review = group.get('semanticReview', {})
        require(review.get('status') == 'pass' and not review.get('issues')
                and isinstance(review.get('uncertainty'), list) and not review['uncertainty']
                and isinstance(review.get('issues'), list)
                and isinstance(review.get('evidence'), str) and review['evidence'].strip()
                and set(review.get('checks', {})) == set(models.SEMANTIC_CHECKS)
                and all(value == 'pass' for value in review['checks'].values()),
                'spoken_prior_group_not_pass')
        utterances = models._utterances(group.get('targetUtterances'))
        coverage = group.get('coverage')
        require(isinstance(coverage, list)
                and [row.get('sourceUnitId') for row in coverage] == group.get('sourceUnitIds')
                and all(isinstance(row.get('targetText'), str)
                        and models._coverage_substring(row['targetText'], ''.join(utterances)) for row in coverage)
                and group.get('translatorRequestId') != group.get('reviewerRequestId'),
                'spoken_prior_coverage_or_request_identity_invalid')
        for role, suffix, request_key in (
                ('translator', 'astra', 'translatorRequestId'),
                ('reviewer', 'sol', 'reviewerRequestId')):
            name = f'group-{index:04d}-{suffix}.json'
            raw_name = f'group-{index:04d}-{suffix}.raw.json'
            parsed, raw = (jobs._read(_safe_path(root / item)) for item in (name, raw_name))
            response = raw.get('response', {})
            require(parsed.get('model') == models.MODEL_ROLES[role]
                    and parsed.get('requestId') == group.get(request_key)
                    and parsed.get('requestId') == response.get('id')
                    and isinstance(parsed.get('payloadSha256'), str)
                    and raw.get('payloadSha256') == parsed['payloadSha256'],
                    'spoken_prior_response_identity_mismatch')
            result = json.loads(models.completed_response_content(response, parsed['model'], role))
            require(result == parsed.get('result')
                    and result.get('translationGroupId') == group.get('translationGroupId')
                    and result.get('sourceUnitIds') == group.get('sourceUnitIds'),
                    'spoken_prior_raw_parsed_mismatch')
            if role == 'reviewer':
                require(result == {k: v for k, v in group.items()
                                   if k not in ('translatorRequestId', 'reviewerRequestId')},
                        'spoken_prior_reviewed_text_mismatch')
            names.extend((name, raw_name))
    return request, evidence, names


def prepare_manifest(root):
    root = _safe_path(root)
    request, evidence, names = complete_cache(root)
    return {'schemaVersion': SCHEMA, 'requestJsonSha256': jobs._digest(request),
            'evidenceJsonSha256': jobs._digest(evidence),
            'files': {name: file_sha(root / name) for name in names}}


def verify_cache(root, manifest):
    actual = prepare_manifest(root)
    require(actual == manifest, 'spoken_prior_cache_manifest_mismatch')
    request, evidence = jobs._read(root / 'request.json'), jobs._read(root / 'evidence.json')
    require(jobs._digest(request) == manifest['requestJsonSha256']
            and jobs._digest(evidence) == manifest['evidenceJsonSha256'],
            'spoken_cache_changed_during_verification')
    return request, evidence


def validate_context(spec, request, anchor, policy):
    manifest = read_manifest(spec['cacheManifest'])
    previous, evidence = verify_cache(spec['reuseFrom'], manifest)
    require(previous == request, 'spoken_prior_request_changed')
    plan = models.group_plan(request, anchor, None)
    models.validate_revision_brief(jobs._read(spec['brief']), request, plan, evidence)
    require(all(policy[role]['model'] == model for role, model in models.MODEL_ROLES.items()),
            'spoken_model_policy_changed')
    return manifest


def snapshot_cache(spec, destination, manifest):
    """Save verified immutable bytes under the current durable job for audited reuse."""
    verify_cache(spec['reuseFrom'], manifest)
    destination = _safe_path(destination)
    destination.mkdir(exist_ok=True)
    for name, digest in manifest['files'].items():
        target = _safe_path(destination / name)
        if target.exists():
            require(file_sha(target) == digest, 'spoken_snapshot_changed')
            continue
        content = _safe_path(spec['reuseFrom'] / name).read_bytes()
        require(hashlib.sha256(content).hexdigest() == digest, 'spoken_cache_changed_during_snapshot')
        with target.open('xb') as stream:
            stream.write(content)
        target.chmod(0o444)
    verify_cache(destination, manifest)
    return destination
