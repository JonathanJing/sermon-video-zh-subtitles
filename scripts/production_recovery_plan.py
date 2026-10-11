#!/usr/bin/env python3
"""Read-only Layer 3 cache recovery planning; never dispatch or migrate a cache.

The expected-intent snapshot must contain complete identities produced by the
canonical renderer for the desired job/settings. It is evidence to compare,
not permission to overwrite results, approve content, or release a lease.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import sermon_sentence_interpretation as identity
from scripts import validate_target_language_audio_unit as integrity
from scripts import build_target_language_audio_package as package

VERSION = 'sermon-production-recovery-plan-v1'
PACKAGE_FIELDS = {'jobJsonSha256', 'jobFileSha256', 'candidateJsonSha256'}
CONTEXT_FIELDS = {'sourceJsonSha256', 'anchorJsonSha256', 'translationPolicySha256'}
MODEL_INPUT_FIELDS = {'textSha256', 'spokenTextSha256', 'deliveryInstruction',
                      'model', 'modelRevision', 'checkpointSha256', 'conditioningRef',
                      'speakerKey', 'languageParameter', 'seed', 'temperature',
                      'repetitionPenalty', 'maxNewTokens', 'dtype', 'attention',
                      'ratePolicy', 'batchWindowInputsSha256', 'batchSize',
                      'batchWindowUnitIndices', 'batchWindowStart', 'batchSeedPolicy'}
REQUIRED_INTENT_FIELDS = {
    'schemaVersion', 'unitIndex', 'jobJsonSha256', 'jobFileSha256',
    'sourceJsonSha256', 'anchorJsonSha256', 'translationPolicySha256',
    'candidateJsonSha256', 'adapterFileSha256', 'adapterId', 'model',
    'modelRevision', 'conditioningRef', 'checkpointMapFileSha256',
    'operationPoliciesFileSha256', 'checkpointSha256', 'speakerId', 'speakerKey',
    'targetLocale', 'languageParameter', 'groupId', 'sourceUnitIds', 'textSha256',
    'rendererSha256', 'seed', 'temperature', 'repetitionPenalty', 'maxNewTokens',
    'dtype', 'attention', 'deliveryInstruction', 'ratePolicy',
}
ROLES = ('reuse', 'revalidate', 'recompute', 'unknown')


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


class Snapshot:
    """Detect changes to both existing evidence and observed missing files."""
    def __init__(self):
        self.files = {}

    def watch(self, path):
        path = Path(path)
        require(not path.is_symlink(), 'symlink_evidence_refused')
        require(not path.exists() or path.is_file(), 'evidence_not_regular_file')
        digest = identity.sha256(path) if path.is_file() else None
        if path in self.files:
            require(self.files[path] == digest, 'evidence_changed_during_planning')
        self.files[path] = digest
        return digest

    def read(self, path):
        digest = self.watch(path)
        if digest is None:
            return None
        require(Path(path).stat().st_size <= 16 * 1024 * 1024, 'json_evidence_too_large')
        data = Path(path).read_bytes()
        require(hashlib.sha256(data).hexdigest() == digest, 'evidence_changed_during_planning')
        value = json.loads(data)
        require(isinstance(value, dict), 'object_evidence_required')
        require(identity.sha256(path) == digest, 'evidence_changed_during_planning')
        return value

    def check(self):
        for path, digest in list(self.files.items()):
            require(not path.is_symlink() and (identity.sha256(path) if path.is_file() else None) == digest,
                    'evidence_changed_during_planning')


def _safe(root, relative):
    require(isinstance(relative, str) and relative and not Path(relative).is_absolute(),
            'relative_artifact_path_required')
    path = root / relative
    require('..' not in Path(relative).parts and path.resolve().is_relative_to(root),
            'artifact_path_escapes_root')
    # A symlinked parent can silently redirect an absent output within the root.
    require(not any(p.is_symlink() for p in [path, *path.parents] if p != root.parent),
            'symlink_artifact_refused')
    return path


def _job_binding(job, job_file_sha, unit, index):
    return {'unitIndex': index, 'jobJsonSha256': identity.json_sha256(job),
            'jobFileSha256': job_file_sha, 'targetLocale': job['targetLocale'],
            'groupId': unit['translationGroupId'], 'sourceUnitIds': unit['sourceUnitIds'],
            'textSha256': hashlib.sha256(unit['text'].encode()).hexdigest(),
            'sourceJsonSha256': job['inputs']['englishSourcePackage']['jsonSha256'],
            'anchorJsonSha256': job['inputs']['anchorManifest']['jsonSha256'],
            'candidateJsonSha256': job['inputs']['targetLanguageCandidate']['jsonSha256']}


def _changes(stored, desired):
    result = []
    for field in sorted(set(stored) | set(desired)):
        if stored.get(field) != desired.get(field):
            category = ('package_binding' if field in PACKAGE_FIELDS else
                        'context_dependency' if field in CONTEXT_FIELDS else
                        'batch_window' if field.startswith('batch') or field.startswith('replica') else
                        'model_input_or_runtime')
            result.append({'field': field, 'category': category,
                           'storedValue': stored.get(field), 'expectedValue': desired.get(field)})
    return result


def _batch_bound(commit, intent, units):
    size = intent.get('batchSize', 1)
    require(type(size) is int and size in (1, 2, 4, 8), 'unsupported_batch_size')
    if size == 1:
        return
    index = intent['unitIndex']
    start = index // size * size
    indices = list(range(start, min(start + size, units)))
    generation = commit.get('generationBatch', {})
    require(intent.get('batchWindowStart') == start and intent.get('batchWindowUnitIndices') == indices
            and generation.get('unitIndices') == indices
            and generation.get('seed') == intent.get('seed', -1) + start
            and isinstance(intent.get('batchWindowInputsSha256'), str),
            'full_batch_window_generation_binding_missing')


def _job_dependencies(snap, job_path, job):
    """Verify the artifacts the canonical job actually names, not inferred DAGs."""
    problems = []
    for role, artifact in job['inputs'].items():
        if not isinstance(artifact, dict) or 'path' not in artifact:
            problems.append(role + ':artifact_binding_missing')
            continue
        path = Path(artifact['path'])
        if not path.is_absolute():
            path = job_path.parent / path
        try:
            digest = snap.watch(path)
            if digest is None or digest != artifact.get('sha256'):
                problems.append(role + ':file_identity_unavailable_or_changed')
            elif 'jsonSha256' in artifact and identity.json_sha256(snap.read(path)) != artifact['jsonSha256']:
                problems.append(role + ':json_identity_changed')
        except (ValueError, TypeError, OSError):
            problems.append(role + ':dependency_evidence_invalid')
    return problems


def _plan_layer3(job_path: Path, *, render_root: Path | None = None,
                expected_intents_path: Path | None = None,
                execution_state_path: Path | None = None,
                lock_status: str = 'not_present') -> dict:
    """Audit durable unit bytes; all actions remain advisory and unexecuted.

    A terminal snapshot records a historical observation only. It does not
    acquire a live producer lock or confer dispatch authority.
    """
    snap = Snapshot()
    job_path = Path(job_path).absolute()
    job = snap.read(job_path)
    require(job is not None, 'canonical_job_required')
    package.speech.validate_speech_job_schema(job, 'recovery job')
    require(job.get('status') == 'prepared_for_target_language_speech' and job.get('synthesisEligible') is True,
            'canonical_synthesis_eligible_job_required')
    root = Path(render_root or job_path.parent).absolute()
    require(root.is_dir() and not root.is_symlink() and root == root.resolve(),
            'existing_regular_render_root_required')
    root = root.resolve()
    job_sha, job_file_sha = identity.json_sha256(job), snap.files[job_path]
    require(all(unit.get('unitIndex') == index for index, unit in enumerate(job['units']))
            and len({u['translationGroupId'] for u in job['units']}) == len(job['units'])
            and len({u['outputRelativePath'] for u in job['units']}) == len(job['units']),
            'job_unit_indices_groups_or_paths_not_unique')
    dependency_problems = _job_dependencies(snap, job_path, job)
    expected = None
    if expected_intents_path is not None:
        envelope = snap.read(expected_intents_path)
        require(envelope is not None and envelope.get('schemaVersion') == 'sermon-l3-recovery-intent-snapshot-v1'
                and envelope.get('jobJsonSha256') == job_sha and envelope.get('jobFileSha256') == job_file_sha,
                'expected_intents_job_binding_changed')
        expected = envelope.get('intents')
        require(isinstance(expected, list) and len(expected) == len(job['units']), 'complete_expected_intents_required')
        for index, (unit, intent) in enumerate(zip(job['units'], expected)):
            require(isinstance(intent, dict) and REQUIRED_INTENT_FIELDS <= intent.keys()
                    and all(intent.get(k) == v for k, v in _job_binding(job, job_file_sha, unit, index).items()),
                    'expected_intent_incomplete_or_wrong_job_unit')
            size = intent.get('batchSize', 1)
            require(type(size) is int and size in (1, 2, 4, 8), 'unsupported_batch_size')
            if size != 1:
                start = index // size * size
                require(intent.get('batchWindowStart') == start
                        and intent.get('batchWindowUnitIndices') == list(range(start, min(start + size, len(expected))))
                        and isinstance(intent.get('batchWindowInputsSha256'), str),
                        'expected_batch_window_incomplete')
    owner = 'not_checked'
    if execution_state_path is not None:
        state = snap.read(execution_state_path)
        require(state is not None and state.get('schemaVersion') == 'sermon-l3-recovery-execution-snapshot-v1'
                and state.get('jobJsonSha256') == job_sha and state.get('jobFileSha256') == job_file_sha,
                'execution_snapshot_job_binding_changed')
        owner = state.get('status')
        require(owner in ('terminal', 'active', 'unknown'), 'execution_snapshot_status_invalid')
        require(state.get('renderRoot') == str(root), 'execution_snapshot_render_root_changed')
    if lock_status == 'busy':
        owner = 'active'
    rows = []
    for index, unit in enumerate(job['units']):
        paths = {name: _safe(root, relative) for name, relative in {
            'audio': unit['outputRelativePath'], 'intent': f'receipts/unit-{index:04d}.intent.json',
            'commit': f'receipts/unit-{index:04d}.render.json', 'receipt': f'receipts/unit-{index:04d}.json',
            'started': f'receipts/unit-{index:04d}.started.json'}.items()}
        partial = paths['audio'].with_suffix('.partial.wav')
        audio_sha, partial_sha, started_sha = snap.watch(paths['audio']), snap.watch(partial), snap.watch(paths['started'])
        row = {'unitIndex': index, 'textGroupId': unit['translationGroupId'], 'classification': 'unknown',
               'reasons': [], 'changes': [], 'audioSha256': audio_sha or partial_sha,
               'modelRequestChanged': None, 'modelRecomputeRequired': None,
               'blocked': False, 'batchWindowUnitIndices': [index],
               'downstreamInvalidation': [], 'dispatchAuthorized': False}
        try:
            intent, commit, receipt = (snap.read(paths[k]) for k in ('intent', 'commit', 'receipt'))
            desired = expected[index] if expected is not None else _job_binding(job, job_file_sha, unit, index)
            if intent is not None:
                row['changes'] = _changes(intent, desired) if expected is not None else [
                    change for change in _changes(intent, desired) if change['field'] in desired]
                row['batchWindowUnitIndices'] = intent.get('batchWindowUnitIndices', [index])
            if expected is not None:
                row['batchWindowUnitIndices'] = desired.get('batchWindowUnitIndices', [index])
            if commit is not None:
                require(intent is not None and commit.get('identity') == intent
                        and commit.get('audioSha256') == (audio_sha or partial_sha)
                        and (audio_sha or partial_sha) is not None, 'committed_audio_identity_or_hash_changed')
                _batch_bound(commit, intent, len(job['units']))
                if row['changes']:
                    categories = {c['category'] for c in row['changes']}
                    fields = {c['field'] for c in row['changes']}
                    # A changed source/anchor/policy or implementation hash alone
                    # cannot establish which model-facing inputs changed.
                    actual_request_change = (True if fields & MODEL_INPUT_FIELDS else
                                             False if categories <= {'package_binding'} else None)
                    row.update(classification='revalidate', modelRequestChanged=actual_request_change,
                               modelRecomputeRequired=None, blocked=True)
                    row['reasons'].append('cross_identity_cache_requires_canonical_admission_no_migration')
                    if actual_request_change is True:
                        row['reasons'].append('changed_context_or_sound_identity_cannot_reuse_directly')
                    elif actual_request_change is False:
                        row['reasons'].append('package_binding_change_does_not_establish_model_recompute')
                    else:
                        row['reasons'].append('changed_dependency_or_implementation_actual_model_input_impact_unknown')
                    integrity.probe_full_decode(paths['audio'] if audio_sha else partial)
                else:
                    row.update(classification='revalidate', modelRequestChanged=False, modelRecomputeRequired=False)
                    if expected is None:
                        row['reasons'].append('current_generation_identity_not_supplied')
                        row['blocked'] = True
                    elif partial_sha is not None and audio_sha is None:
                        row['reasons'].append('committed_partial_requires_transaction_reconciliation')
                    elif receipt is None:
                        row['reasons'].append('durable_audio_requires_missing_receipt_rebuild')
                    else:
                        integrity.validate_receipt(job_path, index, paths['audio'], receipt,
                            validated_job=job, validated_job_file_sha256=job_file_sha)
                        row['classification'] = 'reuse'
                        row['reasons'].append('exact_intent_commit_hash_decode_and_receipt_match')
                    if row['classification'] == 'revalidate':
                        integrity.probe_full_decode(paths['audio'] if audio_sha else partial)
            elif audio_sha is not None or partial_sha is not None or started_sha is not None:
                row.update(classification='unknown', blocked=True)
                row['reasons'].append('uncommitted_or_started_result_requires_reconciliation')
            elif row['changes']:
                row.update(classification='revalidate', blocked=True)
                row['reasons'].append('existing_intent_changed_new_root_or_canonical_admission_required')
            elif expected is None:
                row.update(classification='unknown', blocked=True)
                row['reasons'].append('missing_result_generation_identity_not_supplied')
            else:
                row.update(classification='recompute', modelRequestChanged=False, modelRecomputeRequired=True)
                row['reasons'].append('missing_unit_with_expected_generation_identity')
                if owner != 'terminal':
                    row['blocked'] = True
                    row['reasons'].append('owner_not_verified_proposed_recompute_only')
        except (ValueError, KeyError, TypeError, OSError) as exc:
            row.update(classification='unknown', blocked=True, modelRecomputeRequired=None)
            row['reasons'].append('invalid_evidence_requires_reconciliation:' + str(exc))
        if owner in ('active', 'unknown'):
            row['blocked'] = True
            row['reasons'].append('owner_' + owner + '_no_dispatch_or_release')
        if dependency_problems:
            row['blocked'] = True
            row['reasons'].append('named_upstream_dependencies_require_reconciliation')
        if row['classification'] != 'reuse':
            row['downstreamInvalidation'] = ['locale_schedule_track_cues_revalidation',
                                              'locale_audio_package_and_listening_binding_revalidation',
                                              'locale_release_binding_revalidation']
        rows.append(row)
    windows = {}
    for row in rows:
        if row['classification'] != 'recompute':
            continue
        indices = row['batchWindowUnitIndices']
        key = tuple(indices)
        windows.setdefault(key, {'unitIndices': indices, 'submitMissingUnitIndices': [],
                                 'preserveCommittedUnitIndices': [], 'blocked': False})
        windows[key]['submitMissingUnitIndices'].append(row['unitIndex'])
    for indices, window in windows.items():
        window['preserveCommittedUnitIndices'] = [i for i in indices if rows[i]['classification'] in ('reuse', 'revalidate')
                                                  and rows[i]['modelRecomputeRequired'] is False]
        window['blocked'] = any(rows[i]['blocked'] or rows[i]['classification'] == 'unknown' for i in indices)
    manifest_path = _safe(root, 'render-manifest.json')
    manifest = snap.read(manifest_path)
    manifest_status = 'missing_requires_rebuild'
    if manifest is not None:
        manifest_status = 'requires_canonical_package_validation'
        if manifest.get('targetLanguageSpeechJobJsonSha256') != job_sha:
            manifest_status = 'job_binding_changed'
        for key in ('track', 'schedule', 'captions'):
            artifact = manifest.get(key)
            if not isinstance(artifact, dict) or snap.watch(_safe(root, artifact.get('path'))) != artifact.get('sha256'):
                manifest_status = 'asset_identity_changed_requires_reconciliation'
                break
    snap.check()
    counts = {role: sum(r['classification'] == role for r in rows) for role in ROLES}
    blocked = [r['unitIndex'] for r in rows if r['blocked']]
    result = {'schemaVersion': VERSION, 'layer': 'L3', 'targetLocale': job['targetLocale'],
              'jobJsonSha256': job_sha, 'jobFileSha256': job_file_sha,
              'ownerObservation': owner, 'counts': counts, 'units': rows,
              'formalRenderLockObservation': lock_status,
              'namedJobDependencyProblems': dependency_problems,
              'batchReplay': list(windows.values()),
              'plannedModelUnitEvaluations': sum(len(w['unitIndices']) for w in windows.values()),
              'plannedMissingUnitCommits': counts['recompute'],
              'blockedScope': {'unitIndices': blocked,
                  'wholeLayerDispatchBlocked': owner in ('active', 'unknown', 'not_checked') or bool(dependency_problems),
                  'manifestStatus': manifest_status},
              'formalPackageIdentityChangedDoesNotImplyModelRecompute': True,
              'crossJobAsrCacheMigrationImplemented': False,
              'producerAdmissionRequired': True, 'formalAdmissionValidated': False,
              'dispatchAuthorized': False, 'resourceReleaseAuthorized': False,
              'humanApprovalCreated': False, 'modelCalls': 0, 'existingArtifactsModified': False,
              'evidenceSetSha256': identity.json_sha256({str(p): h for p, h in snap.files.items()})}
    result['planSha256'] = identity.json_sha256(result)
    return result


def plan_layer3(job_path: Path, *, render_root: Path | None = None,
                expected_intents_path: Path | None = None,
                execution_state_path: Path | None = None) -> dict:
    """Hold an existing formal producer lock shared, without creating it.

    An unavailable lock is observed as active. Missing locks are reported and
    never replaced by a newly-created planning lock or dispatch permission.
    """
    root = Path(render_root or Path(job_path).parent).absolute()
    require(root.is_dir() and root == root.resolve(), 'existing_regular_render_root_required')
    lock_path = _safe(root, '.formal-render.lock')
    with ExitStack() as resources:
        status = 'not_present'
        locked_inode = None
        if lock_path.exists():
            require(lock_path.is_file() and not lock_path.is_symlink(), 'formal_render_lock_invalid')
            handle = resources.enter_context(os.fdopen(os.open(lock_path, os.O_RDONLY | os.O_NOFOLLOW), 'rb'))
            opened = os.fstat(handle.fileno())
            named = lock_path.lstat()
            require(stat.S_ISREG(opened.st_mode) and (opened.st_dev, opened.st_ino) == (named.st_dev, named.st_ino),
                    'formal_render_lock_changed')
            locked_inode = (opened.st_dev, opened.st_ino)
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
                status = 'shared_read_lock_held'
            except BlockingIOError:
                status = 'busy'
        result = _plan_layer3(job_path, render_root=root, expected_intents_path=expected_intents_path,
                             execution_state_path=execution_state_path, lock_status=status)
        if locked_inode is not None:
            named = lock_path.lstat()
            require(stat.S_ISREG(named.st_mode) and locked_inode == (named.st_dev, named.st_ino),
                    'formal_render_lock_changed')
        else:
            require(not lock_path.exists() and not lock_path.is_symlink(), 'formal_render_lock_changed')
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', required=True, type=Path)
    parser.add_argument('--render-root', type=Path)
    parser.add_argument('--expected-intents', type=Path)
    parser.add_argument('--execution-state', type=Path)
    # Stdout is the only output: no implicit report writes into a live root.
    args = parser.parse_args()
    print(json.dumps(plan_layer3(args.job, render_root=args.render_root,
        expected_intents_path=args.expected_intents, execution_state_path=args.execution_state),
        ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
