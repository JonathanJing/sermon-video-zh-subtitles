"""Read-only MFA identity checks with a versioned, public-safe comparison receipt.

A seed pins dependencies, a plan pins its producer, and an execution records its
own provenance. Host names and local paths never appear in returned receipts.
Legacy inspection records an unavailable event time; it never backfills history.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from scripts import sermon_public_snapshot as public
from scripts import sermon_review_contracts as c
from scripts.sermon_release_workflow import _safe_path

SCHEMA = 'sermon-mfa-identity-comparison-v1'
ADAPTER = 'scripts/mfa_alignment.py'
FILES = frozenset(('mfa_executable', 'dictionary_path', 'acoustic_model', 'g2p_model', 'spoken_forms_path'))
DEPENDENCIES = ('version', 'executionPlatform', 'files', 'nativeKalpy', 'condaRecords')
FIELDS = {
    'stable_dependency': frozenset(('runtime_schema', *DEPENDENCIES, 'dependency_file_health')),
    'frozen_producer': frozenset(('adapterSha256',)),
    'execution_provenance': frozenset(('executionHost', 'input_binding', 'alignment_artifacts', 'preflight_acceptance', 'receipt_integrity')),
}
REASONS = frozenset(('runtime_unknown', 'dependency_changed', 'dependency_file_changed',
    'producer_not_frozen', 'input_changed', 'alignment_artifact_changed', 'preflight_changed', 'receipt_changed'))
ROLES = frozenset(('frozen_plan', 'runtime_seed', 'execution_runtime', 'alignment_artifacts', 'preflight_receipt', 'comparison_receipt'))
SHA = re.compile(r'^[0-9a-f]{64}$')
SEMANTICS = {**{field: 'exact_canonical_value' for field in ('runtime_schema', *DEPENDENCIES, 'receipt_integrity', 'input_binding')},
    'adapterSha256': 'frozen_plan_adapter', 'executionHost': 'record_execution_provenance',
    'dependency_file_health': 'metadata_and_actual_files', 'alignment_artifacts': 'bound_alignment_artifacts',
    'preflight_acceptance': 'accepted_preflight'}
FIELD_REASONS = {**{field: 'dependency_changed' for field in DEPENDENCIES},
    'runtime_schema': 'runtime_unknown', 'dependency_file_health': 'dependency_file_changed',
    'adapterSha256': 'producer_not_frozen', 'executionHost': None, 'input_binding': 'input_changed',
    'alignment_artifacts': 'alignment_artifact_changed', 'preflight_acceptance': 'preflight_changed',
    'receipt_integrity': 'receipt_changed'}


def _is_sha(value):
    return type(value) is str and SHA.fullmatch(value) is not None


def _file_sha(path):
    """Bounded stable hash; do not follow symlinks or accept special files."""
    path = _safe_path(Path(path))
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        c.require(stat.S_ISREG(before.st_mode) and before.st_size <= 8 * 1024**3, 'mfa_identity_file_invalid')
        digest = hashlib.sha256()
        with os.fdopen(os.dup(fd), 'rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        c.require(identity(before) == identity(os.fstat(fd)) == identity(os.stat(path, follow_symlinks=False)),
                  'mfa_identity_file_changed')
        return digest.hexdigest()
    finally:
        os.close(fd)


def _read(path, file_sha):
    value, raw = public.read_snapshot(_safe_path(Path(path)))
    c.require(file_sha(path) == c.bytes_sha256(raw), 'mfa_identity_snapshot_changed')
    return value


def _known(value):
    if (type(value) is not dict or set(value) != {'schemaVersion', 'backend', 'runtime'}
            or type(value['schemaVersion']) is not int or value['schemaVersion'] != 1
            or value['backend'] != 'macbook-local'):
        return False
    runtime = value['runtime']
    if (type(runtime) is not dict or set(runtime) != {*DEPENDENCIES, 'adapterSha256', 'executionHost'}
            or not _is_sha(runtime['adapterSha256']) or runtime['executionPlatform'] != 'Darwin'
            or any(type(runtime[key]) is not str or not runtime[key].strip() or len(runtime[key]) > 4096
                   for key in ('version', 'executionHost'))
            or type(runtime['files']) is not dict or set(runtime['files']) != FILES):
        return False
    for name, ref in runtime['files'].items():
        if ref is None and name in {'g2p_model', 'spoken_forms_path'}:
            continue
        if (type(ref) is not dict or set(ref) != {'path', 'sha256'} or not _is_sha(ref['sha256'])
                or type(ref['path']) is not str or not Path(ref['path']).is_absolute()):
            return False
    for key in ('nativeKalpy', 'condaRecords'):
        if type(runtime[key]) is not dict:
            return False
        for name, sha in runtime[key].items():
            if type(name) is not str or not name or not _is_sha(sha):
                return False
            if key == 'nativeKalpy' and not Path(name).is_absolute():
                return False
            if key == 'condaRecords' and (Path(name).name != name or not name.endswith('.json')):
                return False
    return True


def _health(runtime, file_sha):
    expected = {ref['path']: ref['sha256'] for ref in runtime['files'].values() if ref}
    expected.update(runtime['nativeKalpy'])
    env = Path(runtime['files']['mfa_executable']['path']).parent.parent
    expected.update({str(env/'conda-meta'/name): sha for name, sha in runtime['condaRecords'].items()})
    observed = {}
    for path in sorted(expected):
        try:
            observed[path] = file_sha(path)
        except (OSError, c.ContractError):
            observed[path] = None
    # An unlisted native binary or package record is dependency drift too.
    native = {str(path) for path in env.glob('lib/python*/site-packages/_kalpy*.so')}
    records = {path.name for path in (env/'conda-meta').glob('*.json')}
    inventories = (native == set(runtime['nativeKalpy']) and records == set(runtime['condaRecords'])
        and os.access(runtime['files']['mfa_executable']['path'], os.X_OK))
    return expected, observed, expected == observed and inventories


def _row(category, field, expected, observed, reason, *, accepted=None, semantics='exact_canonical_value', refs=()):
    matched = expected == observed if accepted is None else accepted
    return {'category': category, 'field': field, 'expectedSha256': c.canonical_sha256(expected),
        'observedSha256': c.canonical_sha256(observed), 'hashSemantics': 'canonical_json_value',
        'matchSemantics': semantics, 'matchResult': 'match' if matched else 'mismatch',
        'rejectionReason': None if matched else reason, 'evidenceRefs': list(refs)}


def _binding(plan):
    config = plan['providerConfig']
    return {'planSha256': c.canonical_sha256(plan), 'runIdSha256': c.canonical_sha256(config['runId']),
        'inputSha256': c.canonical_sha256({key: config[key] for key in
            ('sourceMediaSha256', 'sourceAudioSha256', 'sourceClipSha256', 'sourceWindowSeconds')})}


def _finish(plan, phase, rows, evidence, observed_at, expected_receipt, prior=None):
    if expected_receipt is not None:
        validate_receipt(expected_receipt)
        observed_at = expected_receipt['observedAt']
    elif observed_at == 'now':
        observed_at = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    reason = next((row['rejectionReason'] for row in rows if row['rejectionReason']), None)
    result = {'schemaVersion': SCHEMA, 'kind': 'identity_comparison', 'phase': phase,
        'binding': _binding(plan), 'hashAlgorithm': 'sha256', 'canonicalization': 'sermon-canonical-json-v1',
        'observedAt': observed_at, 'observationStatus': 'observed' if observed_at else 'historical_event_time_unavailable',
        'comparisons': rows, 'evidence': evidence,
        'acceptance': {'result': 'rejected' if reason else 'accepted', 'rejectionReason': reason,
            'preflightReceiptSha256': c.canonical_sha256(prior) if prior is not None else None}}
    result['receiptSha256'] = c.canonical_sha256(result)
    validate_receipt(result)
    if expected_receipt is not None and result != expected_receipt:
        # Preserve the actual operands on rejection instead of collapsing a
        # dependency failure to an uninformative receipt error.
        if result['acceptance']['result'] == 'rejected':
            require_accepted(result)
        result['evidence'].append({'role': 'comparison_receipt', 'sha256': c.canonical_sha256(expected_receipt)})
        result['comparisons'].append(_row('execution_provenance', 'receipt_integrity',
            expected_receipt['receiptSha256'], result['receiptSha256'], 'receipt_changed', refs=('comparison_receipt',)))
        result['acceptance'].update(result='rejected', rejectionReason='receipt_changed')
        result['receiptSha256'] = c.canonical_sha256({key: value for key, value in result.items() if key != 'receiptSha256'})
        require_accepted(result)
    return result


def validate_receipt(receipt):
    """Strict whitelist validation, including result semantics and self hash."""
    c.require(type(receipt) is dict and set(receipt) == {'schemaVersion', 'kind', 'phase', 'binding',
        'hashAlgorithm', 'canonicalization', 'observedAt', 'observationStatus', 'comparisons', 'evidence',
        'acceptance', 'receiptSha256'} and receipt['schemaVersion'] == SCHEMA
        and receipt['kind'] == 'identity_comparison' and receipt['phase'] in {'preflight', 'post_alignment'}
        and receipt['hashAlgorithm'] == 'sha256' and receipt['canonicalization'] == 'sermon-canonical-json-v1',
        'mfa_identity_receipt_invalid')
    c.require(type(receipt['binding']) is dict and set(receipt['binding']) == {'planSha256', 'runIdSha256', 'inputSha256'}
        and all(_is_sha(value) for value in receipt['binding'].values()), 'mfa_identity_receipt_invalid')
    observed = receipt['observedAt']
    try:
        valid_time = observed is None or (type(observed) is str and observed.endswith('Z')
            and datetime.fromisoformat(observed.replace('Z', '+00:00')).utcoffset().total_seconds() == 0)
    except (ValueError, AttributeError):
        valid_time = False
    c.require(valid_time and receipt['observationStatus'] == ('observed' if observed else 'historical_event_time_unavailable'),
              'mfa_identity_receipt_invalid')
    evidence = receipt['evidence']
    c.require(type(evidence) is list and evidence and all(type(ref) is dict and set(ref) == {'role', 'sha256'}
        and ref['role'] in ROLES and _is_sha(ref['sha256']) for ref in evidence)
        and len({ref['role'] for ref in evidence}) == len(evidence), 'mfa_identity_receipt_invalid')
    refs = {ref['role'] for ref in evidence}
    rows = receipt['comparisons']
    c.require(type(rows) is list and rows, 'mfa_identity_receipt_invalid')
    seen = set()
    for row in rows:
        c.require(type(row) is dict and set(row) == {'category', 'field', 'expectedSha256', 'observedSha256',
            'hashSemantics', 'matchSemantics', 'matchResult', 'rejectionReason', 'evidenceRefs'}
            and row['category'] in FIELDS and row['field'] in FIELDS[row['category']]
            and _is_sha(row['expectedSha256']) and _is_sha(row['observedSha256'])
            and row['hashSemantics'] == 'canonical_json_value'
            and row['matchSemantics'] in {'exact_canonical_value', 'frozen_plan_adapter', 'record_execution_provenance',
                'metadata_and_actual_files', 'bound_alignment_artifacts', 'accepted_preflight'}
            and row['matchResult'] in {'match', 'mismatch'}
            and row['rejectionReason'] in REASONS | {None}
            and type(row['evidenceRefs']) is list and row['evidenceRefs']
            and all(type(ref) is str and ref in refs for ref in row['evidenceRefs']), 'mfa_identity_receipt_invalid')
        key = (row['category'], row['field'])
        c.require(key not in seen and (row['matchResult'] == 'match') == (row['rejectionReason'] is None),
                  'mfa_identity_receipt_invalid')
        c.require(row['matchSemantics'] == SEMANTICS[row['field']]
            and (row['rejectionReason'] is None or row['rejectionReason'] == FIELD_REASONS[row['field']])
            and (row['field'] != 'executionHost' or row['matchResult'] == 'match'), 'mfa_identity_receipt_invalid')
        if row['matchResult'] == 'match' and row['field'] != 'executionHost':
            c.require(row['expectedSha256'] == row['observedSha256'], 'mfa_identity_receipt_invalid')
        if row['matchSemantics'] not in {'metadata_and_actual_files', 'record_execution_provenance'}:
            c.require((row['expectedSha256'] == row['observedSha256']) == (row['matchResult'] == 'match'),
                      'mfa_identity_receipt_invalid')
        seen.add(key)
    required = {('stable_dependency', 'runtime_schema')}
    if receipt['phase'] == 'preflight':
        required.add(('frozen_producer', 'adapterSha256'))
        if rows[0]['matchResult'] == 'match':
            required.add(('stable_dependency', 'dependency_file_health'))
        if 'comparison_receipt' in refs:
            required.add(('execution_provenance', 'receipt_integrity'))
        c.require(refs - {'comparison_receipt'} == {'frozen_plan', 'runtime_seed'} and seen == required, 'mfa_identity_receipt_invalid')
    else:
        required.add(('execution_provenance', 'input_binding'))
        c.require({'frozen_plan', 'runtime_seed', 'execution_runtime'} <= refs, 'mfa_identity_receipt_invalid')
        if rows[0]['matchResult'] == 'match':
            required |= {('stable_dependency', field) for field in (*DEPENDENCIES, 'dependency_file_health')}
            required |= {('frozen_producer', 'adapterSha256'), ('execution_provenance', 'executionHost'),
                         ('execution_provenance', 'alignment_artifacts')}
        if 'preflight_receipt' in refs:
            required.add(('execution_provenance', 'preflight_acceptance'))
        if 'comparison_receipt' in refs:
            required.add(('execution_provenance', 'receipt_integrity'))
        c.require(seen == required, 'mfa_identity_receipt_invalid')
    c.require(next(ref['sha256'] for ref in evidence if ref['role'] == 'frozen_plan') == receipt['binding']['planSha256'],
              'mfa_identity_receipt_invalid')
    acceptance = receipt['acceptance']
    reason = next((row['rejectionReason'] for row in rows if row['rejectionReason']), None)
    c.require(type(acceptance) is dict and set(acceptance) == {'result', 'rejectionReason', 'preflightReceiptSha256'}
        and acceptance['result'] == ('rejected' if reason else 'accepted') and acceptance['rejectionReason'] == reason
        and (acceptance['preflightReceiptSha256'] is None or _is_sha(acceptance['preflightReceiptSha256']))
        and receipt['receiptSha256'] == c.canonical_sha256({key: value for key, value in receipt.items() if key != 'receiptSha256'}),
        'mfa_identity_receipt_invalid')
    return deepcopy(receipt)


def require_accepted(receipt):
    validate_receipt(receipt)
    if receipt['acceptance']['result'] != 'accepted':
        error = c.ContractError('mfa_identity_' + receipt['acceptance']['rejectionReason'])
        error.identity_comparison = deepcopy(receipt)
        raise error
    return receipt


def preflight(plan, runtime_path, *, file_sha256=None, expected_receipt=None, observed_at='now'):
    """No subprocesses: verify recipe dependencies and frozen adapter pre-pay."""
    file_sha = file_sha256 or _file_sha
    seed = _read(runtime_path, file_sha)
    refs = [{'role': 'frozen_plan', 'sha256': c.canonical_sha256(plan)},
            {'role': 'runtime_seed', 'sha256': c.canonical_sha256(seed)}]
    rows = [_row('stable_dependency', 'runtime_schema', True, _known(seed), 'runtime_unknown', refs=('runtime_seed',))]
    if _known(seed):
        expected, actual, healthy = _health(seed['runtime'], file_sha)
        rows.append(_row('stable_dependency', 'dependency_file_health', expected, actual, 'dependency_file_changed',
            accepted=healthy, semantics='metadata_and_actual_files', refs=('runtime_seed',)))
    frozen = plan['executionIdentity'].get('loadedProjectCodeSha256', {}).get(ADAPTER)
    actual = file_sha(Path(__file__).resolve().parents[1]/ADAPTER)
    rows.append(_row('frozen_producer', 'adapterSha256', frozen, actual, 'producer_not_frozen',
        semantics='frozen_plan_adapter', refs=('frozen_plan',)))
    return _finish(plan, 'preflight', rows, refs, observed_at, expected_receipt)


def _alignment_artifacts(plan, runtime, aligned, chunks, file_sha):
    c.require(type(aligned) is list and bool(aligned) and type(chunks) is list and bool(chunks), 'mfa_identity_alignment_required')
    window = plan['providerConfig']['sourceWindowSeconds']
    c.require(len(chunks) == 1 and chunks[0].get('id') == 'fresh-diagnostic' and chunks[0].get('start') == 0
        and chunks[0].get('end') == window[1] - window[0]
        and all(row.get('alignmentExecutionBackend') == 'macbook-local' for row in aligned),
        'mfa_identity_alignment_input_changed')
    root = _safe_path(Path(plan['runDirectory']))/'mfa'
    paths = {_safe_path(Path(row['mfaManifest'])) for row in aligned}
    c.require(len(paths) == 1 and all(root in path.parents for path in paths), 'mfa_identity_alignment_path_changed')
    refs = {}
    for path in paths:
        manifest = _read(path, file_sha); identity = manifest.get('identity')
        c.require(manifest.get('schemaVersion') == 1 and type(identity) is dict and identity.get('schemaVersion') == 1,
                  'mfa_identity_alignment_unknown')
        c.require(path.name == 'manifest.json' and path.parent.name == hashlib.sha256(
            json.dumps(identity, sort_keys=True).encode()).hexdigest(), 'mfa_identity_alignment_identity_changed')
        files = runtime['files']
        c.require(identity.get('adapterSha256') == runtime['adapterSha256']
            and identity.get('audioSha256') == plan['providerConfig']['sourceAudioSha256']
            and identity.get('mfa') == {**files['mfa_executable'], 'version': runtime['version']}
            and identity.get('dictionarySha256') == files['dictionary_path']['sha256']
            and identity.get('acousticSha256') == files['acoustic_model']['sha256']
            and all(identity.get(key) == (files[name]['sha256'] if files[name] else None)
                    for key, name in (('g2pSha256', 'g2p_model'), ('spokenFormsSha256', 'spoken_forms_path'))),
                  'mfa_identity_alignment_input_changed')
        expected_chunks = [{key: (' '.join(chunk[key].split()) if key == 'text' else chunk[key])
                            for key in ('id', 'start', 'end', 'text')} for chunk in chunks if chunk['text'].strip()]
        skipped_chunks = [{'id': chunk.get('id'), 'start': float(chunk['start']), 'end': float(chunk['end']), 'text': ''}
                          for chunk in chunks if not chunk['text'].strip()]
        c.require(bool(expected_chunks) and type(identity.get('chunks')) is list
            and [{key: chunk.get(key) for key in ('id', 'start', 'end', 'text')}
                 for chunk in identity['chunks']] == expected_chunks
            and identity.get('skippedEmptyReferenceChunks') == skipped_chunks,
            'mfa_identity_alignment_input_changed')
        # mfa_alignment numbers only prepared (nonempty) chunks, not input
        # positions. Never let a manifest replace a required raw alignment with
        # another healthy file or hide a missing output by omitting its key.
        expected_outputs = {f'aligned/speaker/chunk_{index:04d}.json' for index in range(len(identity['chunks']))}
        c.require(type(manifest.get('outputHashes')) is dict
            and set(manifest['outputHashes']) == expected_outputs, 'mfa_identity_alignment_output_changed')
        for name, sha in manifest['outputHashes'].items():
            c.require(type(name) is str and not Path(name).is_absolute() and '..' not in Path(name).parts
                and _is_sha(sha) and file_sha(path.parent/name) == sha, 'mfa_identity_alignment_output_changed')
            refs[str(path.parent/name)] = sha
        c.require(file_sha(path.parent/'dictionary.dict') == manifest.get('dictionaryUsedSha256'),
                  'mfa_identity_alignment_output_changed')
        segments = _read(path.parent/'segments.json', file_sha)
        c.require(segments == [{key: value for key, value in row.items() if key != 'alignmentExecutionBackend'}
                               for row in aligned], 'mfa_identity_alignment_output_changed')
        refs.update({str(path): file_sha(path), str(path.parent/'segments.json'): file_sha(path.parent/'segments.json'),
                     str(path.parent/'dictionary.dict'): file_sha(path.parent/'dictionary.dict')})
    return c.canonical_sha256(refs)


def validate_alignment(plan, runtime_path, observed_runtime_path, *, aligned_segments, reference_chunks,
                       file_sha256=None, preflight_receipt=None, expected_receipt=None, observed_at='now'):
    """Inspect actual alignment against its producer plan (parent plan for cache)."""
    file_sha = file_sha256 or _file_sha
    seed, observed = _read(runtime_path, file_sha), _read(observed_runtime_path, file_sha)
    refs = [{'role': 'frozen_plan', 'sha256': c.canonical_sha256(plan)},
        {'role': 'runtime_seed', 'sha256': c.canonical_sha256(seed)},
        {'role': 'execution_runtime', 'sha256': c.canonical_sha256(observed)}]
    known = _known(seed) and _known(observed)
    rows = [_row('stable_dependency', 'runtime_schema', True, known, 'runtime_unknown',
        refs=('runtime_seed', 'execution_runtime'))]
    rows.append(_row('execution_provenance', 'input_binding', True,
        _safe_path(Path(observed_runtime_path)) == _safe_path(Path(plan['runDirectory']))/'mfa/backend.json',
        'input_changed', refs=('frozen_plan', 'execution_runtime')))
    if known:
        old, new = seed['runtime'], observed['runtime']
        for field in DEPENDENCIES:
            rows.append(_row('stable_dependency', field, old[field], new[field], 'dependency_changed',
                refs=('runtime_seed', 'execution_runtime')))
        expected, actual, healthy = _health(new, file_sha)
        rows.append(_row('stable_dependency', 'dependency_file_health', expected, actual, 'dependency_file_changed',
            accepted=healthy, semantics='metadata_and_actual_files', refs=('execution_runtime',)))
        frozen = plan['executionIdentity'].get('loadedProjectCodeSha256', {}).get(ADAPTER)
        rows.append(_row('frozen_producer', 'adapterSha256', frozen, new['adapterSha256'], 'producer_not_frozen',
            semantics='frozen_plan_adapter', refs=('frozen_plan', 'execution_runtime')))
        rows.append(_row('execution_provenance', 'executionHost', old['executionHost'], new['executionHost'], None,
            accepted=True, semantics='record_execution_provenance', refs=('runtime_seed', 'execution_runtime')))
        try:
            artifact_sha = _alignment_artifacts(plan, new, aligned_segments, reference_chunks, file_sha)
            bound = True
        except (KeyError, TypeError, ValueError, OSError):
            artifact_sha, bound = c.canonical_sha256(None), False
        refs.append({'role': 'alignment_artifacts', 'sha256': artifact_sha})
        rows.append(_row('execution_provenance', 'alignment_artifacts', True, bound, 'alignment_artifact_changed',
            semantics='bound_alignment_artifacts', refs=('frozen_plan', 'execution_runtime', 'alignment_artifacts')))
    if preflight_receipt is not None:
        validate_receipt(preflight_receipt)
        valid = (preflight_receipt['phase'] == 'preflight' and preflight_receipt['binding'] == _binding(plan)
            and preflight_receipt['acceptance']['result'] == 'accepted'
            and next((ref['sha256'] for ref in preflight_receipt['evidence'] if ref['role'] == 'runtime_seed'), None)
                == c.canonical_sha256(seed))
        refs.append({'role': 'preflight_receipt', 'sha256': c.canonical_sha256(preflight_receipt)})
        rows.append(_row('execution_provenance', 'preflight_acceptance', True, valid, 'preflight_changed',
            semantics='accepted_preflight', refs=('frozen_plan', 'runtime_seed', 'preflight_receipt')))
    return _finish(plan, 'post_alignment', rows, refs, observed_at, expected_receipt, preflight_receipt)


def inspect_source_alignment(plan, recipe, evidence, aligned_segments, *, file_sha256=None):
    """Shared fresh/cache consumer. Never creates or changes historical receipts."""
    file_sha = file_sha256 or _file_sha
    version = evidence.get('schemaVersion')
    c.require(version in {'sermon-fresh-diagnostic-source-evidence-v1', 'sermon-fresh-diagnostic-source-evidence-v2'},
              'mfa_identity_source_schema_invalid')
    is_new = version.endswith('-v2')
    keys = {'schemaVersion', 'asr', 'sourceCheck', 'alignmentMode', 'sourceCanonicalSha256',
        'anchorCanonicalSha256', 'alignedSegmentsSha256', 'sourceReviewStatus',
        'sourceReviewContentSha256', 'contextSha256', 'productionEligible', 'humanAcceptance'}
    extra = {'mfaIdentityComparisonSha256', 'mfaIdentityPreflightSha256', 'sourceCausalitySha256'}
    c.require(set(evidence) == (keys | extra if is_new else keys)
        and (not is_new or all(evidence[key] is None or _is_sha(evidence[key]) for key in extra)),
        'mfa_identity_source_schema_invalid')
    if evidence['alignmentMode'] != 'fresh_local_mfa':
        c.require(evidence['alignmentMode'] == 'validated_prior_alignment_cache'
            and (not is_new or (evidence['mfaIdentityComparisonSha256'] is None
                               and evidence['mfaIdentityPreflightSha256'] is None)), 'mfa_identity_source_binding_changed')
        return None
    c.require(recipe['runMFA'] is True and 'local_runtime_path' in recipe['files'], 'mfa_identity_recipe_changed')
    seed = recipe['files']['local_runtime_path']
    c.require(file_sha(seed['path']) == seed['sha256'], 'mfa_identity_recipe_changed')
    root = Path(plan['runDirectory'])
    chunks = _read(root/'reference-chunks.json', file_sha)
    preflight_receipt = expected = None
    if is_new:
        preflight_receipt = _read(root/'mfa-identity-preflight.json', file_sha)
        expected = _read(root/'mfa-identity-comparison.json', file_sha)
        c.require(c.canonical_sha256(preflight_receipt) == evidence['mfaIdentityPreflightSha256']
            and c.canonical_sha256(expected) == evidence['mfaIdentityComparisonSha256'], 'mfa_identity_receipt_changed')
        require_accepted(preflight_receipt)
    receipt = validate_alignment(plan, seed['path'], root/'mfa/backend.json', aligned_segments=aligned_segments,
        reference_chunks=chunks, file_sha256=file_sha, preflight_receipt=preflight_receipt,
        expected_receipt=expected, observed_at=None)
    return require_accepted(receipt)
