"""Opt-in fixed Layer 2 admission using canonical gates and existing durable jobs.

Default shadow is read-only. Execution creates machine-reviewed candidates only;
source and independent human review receipts must already exist. No audio, release,
publication, bounded agent or arbitrary command dispatch is implemented here.
"""
from __future__ import annotations

import argparse
import copy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re

from ..contracts import pipeline_definition as pipeline
from . import auto_repair
from . import backend as _text
from . import budget as budget_tools
from . import candidate as producer
from . import group_revision
from . import models
from . import rule_preflight
from contextlib import nullcontext


class _HostModule:
    """A host module looked up at each call, so the package imports without a host."""
    def __init__(self, get):
        self._get = get

    def __getattr__(self, name):
        return getattr(self._get(), name)


durable = _HostModule(lambda: _text.current().unmoved.durable_jobs())
packages = _HostModule(lambda: _text.current().unmoved.package_inspection())
liveness = _HostModule(lambda: _text.current().unmoved.liveness())
accounting = _HostModule(lambda: _text.current().unmoved.accounting_module())
api_concurrency = _HostModule(lambda: _text.current().unmoved.api_concurrency_module())
source_meaning = _HostModule(lambda: _text.current().unmoved.source_meaning_module())  # review/
jobs = _HostModule(lambda: _text.current().core.jobs)


def _safe_path(path):
    return _text.current().core.safe_path(path)


def work_lock(work):
    return _text.current().workspace.work_lock(work)


def __getattr__(name):
    if name == 'ROOT':  # the host checkout; operator tools and tests read it
        return _text.current().core.repo_root
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
SCHEMA = 'sermon-canonical-layer2-execution-v1'
CONCURRENT_SCHEMA = 'sermon-canonical-layer2-execution-v2'
# v3 = v1 plus the bounded auto-repair loop and its own explicit capacity:
# groupWorkers concurrent groups per locale job (collection mode never writes a
# plugin stop receipt, so groups need not be serialized) and maxActiveLocales
# locale jobs at once. It does not accept the v2 Codex CLI concurrency profile;
# API requests still share the job root's 24 in-flight slots.
AUTO_REPAIR_SCHEMA = 'sermon-canonical-layer2-execution-v3'
SHADOW_SCHEMA = 'sermon-canonical-layer2-execution-v4'
# v5 = v3 plus gate 4: layer2AutoRepair may name, per locale, a failed back-translation QC
# receipt of that lane's passed repair chain. v3/v4 keep their exact field set; a v3
# configuration needs no migration and becomes v5 only to carry a QC repair.
QC_REPAIR_SCHEMA = 'sermon-canonical-layer2-execution-v5'
# v6 is the production-only, OpenAI-API payload-cache contract.  Older schemas
# keep their exact field sets and behavior; enabling this changes the execution,
# budget and durable input identities explicitly.
PAYLOAD_CACHE_SCHEMA = 'sermon-canonical-layer2-execution-v6'
# v7 is v6 plus an explicit failed-job partial-round predecessor.  It can reuse
# complete direct-paid responses without pretending that a missing success
# sidecar passed semantic or language-plugin review.
PARTIAL_RECOVERY_SCHEMA = 'sermon-canonical-layer2-execution-v7'
# v8 is v3 plus a per-locale operator group revision (text/group_revision.py): the lane
# translates again only the groups its revision request lists and carries every other
# group from the named prior candidate. It does not combine with v5-v7 fields.
GROUP_REVISION_SCHEMA = 'sermon-canonical-layer2-execution-v8'
PAYLOAD_CACHE_CONFIG_SCHEMA = 'sermon-canonical-layer2-payload-cache-config-v1'
PAYLOAD_CACHE_SNAPSHOT_SCHEMA = 'sermon-canonical-layer2-payload-cache-snapshot-v1'
PARTIAL_RECOVERY_CONFIG_SCHEMA = 'sermon-canonical-layer2-partial-recovery-config-v1'
PARTIAL_RECOVERY_SNAPSHOT_SCHEMA = 'sermon-canonical-layer2-partial-recovery-snapshot-v1'
PARTIAL_RECOVERY_RECEIPT_SCHEMA = 'sermon-canonical-layer2-partial-recovery-receipt-v1'
MAX_PAYLOAD_CACHE_GROUPS = 4096
MAX_PAYLOAD_CACHE_FILE_BYTES = 4 * 1024 * 1024
MAX_AUTO_REPAIR_LOCALES = 3


def _auto_repair_binding(value, *, allow_qc=False):
    required = {'routingVersion', 'groupWorkers', 'maxActiveLocales'}
    qc = value.get('backTranslationQc', {}) if isinstance(value, dict) else None
    optional = {'sourceMeaningNotes', 'backTranslationQc'} if allow_qc else {'sourceMeaningNotes'}
    require(isinstance(value, dict) and required <= set(value) <= required | optional
            and value['routingVersion'] == auto_repair.ROUTING_VERSION
            # Optional: the Layer 1 machine audio adjudication notes (meaning-notes.json beside its receipt)
            # that ride the repair briefs of the groups holding their units.
            and (type(value.get('sourceMeaningNotes', 'x')) is str and value.get('sourceMeaningNotes', 'x'))
            # Optional (gate 4): per locale, the failed text QC receipt of that lane's passed repair chain;
            # its failed groups reopen the chain for one repair round (layer2_auto_repair._reopen_for_qc).
            and isinstance(qc, dict) and ('backTranslationQc' not in value or bool(qc))
            and all(locale in pipeline.LOCALES and type(path) is str and path for locale, path in qc.items())
            and type(value['groupWorkers']) is int
            and 1 <= value['groupWorkers'] <= api_concurrency.MAX_GROUP_WORKERS_PER_LOCALE
            and type(value['maxActiveLocales']) is int
            and 1 <= value['maxActiveLocales'] <= MAX_AUTO_REPAIR_LOCALES, 'invalid_execution_configuration')
    return dict(value)
MODES = ('deterministic_shadow', 'deterministic_execute')
ADMISSION_LOCK = jobs._digest({'purpose': 'canonical-layer2-admission-v1'})
MAX_CONFIG_BYTES = 1024 * 1024
MAX_ACTIVE_LAYER2_JOBS = 1
LIVENESS_POLICY = {'schemaVersion': liveness.SCHEMA, 'startTimeoutSeconds': 60,
                   'heartbeatIntervalSeconds': 30, 'heartbeatTimeoutSeconds': 90,
                   'noProgressTimeoutSeconds': 900}


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def _json(path):
    path = _safe_path(path)
    require(path.is_file() and path.stat().st_size <= MAX_CONFIG_BYTES, 'invalid_configuration_file')
    value = jobs._read(path)
    require(isinstance(value, dict), 'invalid_configuration_object')
    return value


def _path(root, value):
    require(isinstance(value, str) and bool(value.strip()) and len(value) <= 4096, 'invalid_configuration_path')
    return _safe_path(root / value)


def _overlap(a, b):
    return a == b or a in b.parents or b in a.parents


@dataclass(frozen=True)
class Configuration:
    path: Path
    inspection_root: Path
    inspection: dict
    job_root: Path
    run_id: str
    lanes: dict
    sha256: str
    concurrency_profile: dict | None = None
    resource_policy: dict | None = None
    auto_repair: dict | None = None
    candidate_mode: str = 'production'
    payload_cache: dict | None = None
    partial_recovery: dict | None = None
    group_revision: dict | None = None


def _file_digest(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _payload_cache_snapshot(root):
    """Bind exactly the prior evidence the runner may consume.

    A root may be partial: missing success receipts are cache misses.  Once a
    receipt exists, its receipt/cache/raw/preview bytes are all part of the
    execution identity.  Started markers are also bound so an unknown paid
    outcome cannot appear or disappear after durable admission.
    """
    root = _safe_path(root)
    require(root.is_dir() and not root.is_symlink(), 'invalid_payload_cache_root')
    receipts = {}
    markers = []
    for entry in root.iterdir():
        require(not entry.is_symlink(), 'payload_cache_symlink_not_supported')
        receipt_match = re.fullmatch(r'(group-[0-9]{4})-payload-cache-success\.json', entry.name)
        marker_match = re.fullmatch(r'group-[0-9]{4}-(?:astra|sol)\.started\.json', entry.name)
        if receipt_match:
            require(entry.is_file() and entry.stat().st_size <= MAX_PAYLOAD_CACHE_FILE_BYTES,
                    'invalid_payload_cache_file')
            receipts[receipt_match.group(1)] = entry
        elif marker_match:
            require(entry.is_file() and entry.stat().st_size <= MAX_PAYLOAD_CACHE_FILE_BYTES,
                    'invalid_payload_cache_file')
            stem = entry.name.removesuffix('.started.json')
            require((root / f'{stem}.json').is_file() or (root / f'{stem}.raw.json').is_file(),
                    'payload_cache_unknown_paid_outcome')
            markers.append(entry)
    require(len(receipts) <= MAX_PAYLOAD_CACHE_GROUPS, 'payload_cache_group_limit_exceeded')
    files = list(markers)
    for stem, receipt_path in sorted(receipts.items()):
        receipt = _json(receipt_path)
        require(receipt.get('schemaVersion') == models.PAYLOAD_CACHE_SUCCESS_SCHEMA,
                'invalid_payload_cache_success_receipt')
        files.append(receipt_path)
        for suffix in ('astra.json', 'astra.raw.json', 'astra.policy-preview.json',
                       'sol.json', 'sol.raw.json', 'sol.policy-preview.json'):
            bound = root / f'{stem}-{suffix}'
            require(bound.is_file() and not bound.is_symlink()
                    and bound.stat().st_size <= MAX_PAYLOAD_CACHE_FILE_BYTES,
                    'incomplete_payload_cache_success_evidence')
            files.append(bound)
    rows = [{'name': path.name, 'sha256': _file_digest(path), 'bytes': path.stat().st_size}
            for path in sorted(set(files), key=lambda item: item.name)]
    snapshot = {'schemaVersion': PAYLOAD_CACHE_SNAPSHOT_SCHEMA,
                'payloadCacheImplementationSha256': models.PAYLOAD_CACHE_IMPLEMENTATION_SHA256,
                'successfulGroups': len(receipts), 'files': rows}
    snapshot['sha256'] = jobs._digest(snapshot)
    return snapshot


def _payload_cache_binding(value, path, locales):
    required_keys = {'schemaVersion', 'emitSuccess', 'priorSuccessRoots'}
    require(isinstance(value, dict)
            and required_keys <= set(value) <= required_keys | {'cacheRequired'}
            and value.get('schemaVersion') == PAYLOAD_CACHE_CONFIG_SCHEMA
            and value.get('emitSuccess') is True
            and type(value.get('cacheRequired', False)) is bool
            and isinstance(value.get('priorSuccessRoots'), dict)
            and set(value['priorSuccessRoots']) <= set(locales)
            and all(type(item) is str and item for item in value['priorSuccessRoots'].values()),
            'invalid_payload_cache_configuration')
    cache_required = value.get('cacheRequired', False)
    require(not cache_required or set(value['priorSuccessRoots']) == set(locales),
            'required_payload_cache_needs_prior_root_per_locale')
    result = {}
    for locale in sorted(locales):
        root = (_path(path.parent, value['priorSuccessRoots'][locale])
                if locale in value['priorSuccessRoots'] else None)
        snapshot = _payload_cache_snapshot(root) if root is not None else None
        require(snapshot is None or snapshot['successfulGroups'] > 0,
                'payload_cache_source_has_no_success_receipts')
        descriptor = {'schemaVersion': PAYLOAD_CACHE_CONFIG_SCHEMA,
                      'emitSuccess': True,
                      'cacheRequired': cache_required,
                      'payloadCacheImplementationSha256': models.PAYLOAD_CACHE_IMPLEMENTATION_SHA256,
                      'priorSnapshotSha256': snapshot['sha256'] if snapshot is not None else None,
                      'successfulGroups': snapshot['successfulGroups'] if snapshot is not None else 0}
        result[locale] = {'root': root, 'snapshot': snapshot, 'required': cache_required,
                          'identity': jobs._digest(descriptor), 'descriptor': descriptor}
    return result


def _partial_recovery_snapshot(failed_job_root, failed_job_id, round_root,
                               direct_budget_root, locale):
    failed_job_root = _safe_path(failed_job_root)
    round_root = _safe_path(round_root)
    direct_budget_root = _safe_path(direct_budget_root)
    require(re.fullmatch(r'[0-9a-f]{64}', failed_job_id) is not None
            and failed_job_root.is_dir() and not failed_job_root.is_symlink()
            and round_root.is_dir() and not round_root.is_symlink()
            and direct_budget_root.is_dir() and not direct_budget_root.is_symlink(),
            'invalid_partial_recovery_source')
    folder = _safe_path(failed_job_root / failed_job_id)
    request_path, state_path = folder / 'request.json', folder / 'state.json'
    request, state = jobs._read(request_path), jobs._read(state_path)
    require(jobs._request_valid(request, failed_job_id)
            and state.get('schemaVersion') == jobs.SCHEMA
            and state.get('jobId') == failed_job_id and state.get('status') == 'failed'
            and state.get('requestSha256') == jobs._digest(request)
            and _command_option(request.get('command'), '--locale') == locale
            and _command_option(request.get('command'), '--expected-job') == failed_job_id,
            'partial_recovery_requires_failed_bound_job')
    round_request = _json(round_root / 'request.json')
    require(round_request.get('targetLocale') == locale
            and isinstance(round_request.get('sourceUnits'), list)
            and bool(round_request['sourceUnits']), 'partial_recovery_round_identity_changed')
    files = [round_root / name for name in ('request.json', 'rule-preflight.json', 'run-identity.json')]
    markers = {}
    for entry in round_root.iterdir():
        require(not entry.is_symlink(), 'partial_recovery_symlink_not_supported')
        if re.fullmatch(r'group-[0-9]{4}-(?:astra|sol)\.started\.json', entry.name):
            markers[entry.name.removesuffix('.started.json')] = entry
        elif re.fullmatch(r'group-[0-9]{4}-(?:astra|sol)(?:\.raw|\.policy-preview)?\.json', entry.name) \
                or re.fullmatch(r'group-[0-9]{4}-payload-cache-success\.json', entry.name):
            require(entry.is_file() and entry.stat().st_size <= MAX_PAYLOAD_CACHE_FILE_BYTES,
                    'invalid_partial_recovery_file')
            files.append(entry)
    require(len(markers) <= MAX_PAYLOAD_CACHE_GROUPS * 2,
            'partial_recovery_group_limit_exceeded')
    for stem, marker in sorted(markers.items()):
        bound = tuple(round_root / f'{stem}{suffix}' for suffix in
                      ('.json', '.raw.json', '.policy-preview.json'))
        require(all(path.is_file() and not path.is_symlink()
                    and path.stat().st_size <= MAX_PAYLOAD_CACHE_FILE_BYTES for path in bound),
                'partial_recovery_unknown_paid_outcome')
        files.extend((marker, *bound))
    store, _, ledger = budget_tools.BudgetedCaller._store_snapshot(
        direct_budget_root, budget_tools.LOCALE_LEDGER_MAX_BYTES)
    require(ledger['schemaVersion'] == budget_tools.budget.SCHEMA
            and bool(ledger['reservations'])
            and all(row.get('phase') == 'result'
                    and (row.get('result') or {}).get('executionStatus') == 'succeeded'
                    and 'settlement' not in row for row in ledger['reservations'].values()),
            'partial_recovery_budget_has_unknown_or_reused_result')
    rows = [{'name': str(path.relative_to(round_root)), 'sha256': _file_digest(path),
             'bytes': path.stat().st_size}
            for path in sorted(set(files), key=lambda item: str(item))]
    snapshot = {
        'schemaVersion': PARTIAL_RECOVERY_SNAPSHOT_SCHEMA,
        'locale': locale, 'failedJobId': failed_job_id,
        'failedRequestSha256': jobs._digest(request),
        'failedStateSha256': jobs._digest(state),
        'roundRequestSha256': jobs._digest(round_request),
        'roundFiles': rows,
        'directBudgetRoot': str(direct_budget_root),
        'directBudgetStoreSha256': store.store_sha256,
        'directBudgetStateSha256': jobs._digest(ledger),
        'directBudgetReservations': len(ledger['reservations']),
    }
    snapshot['sha256'] = jobs._digest(snapshot)
    return snapshot


def _partial_recovery_binding(value, path, locales, payload_cache):
    require(isinstance(value, dict) and set(value) == {'schemaVersion', 'locales'}
            and value.get('schemaVersion') == PARTIAL_RECOVERY_CONFIG_SCHEMA
            and isinstance(value.get('locales'), dict) and bool(value['locales'])
            and set(value['locales']) <= set(locales),
            'invalid_partial_recovery_configuration')
    result = {}
    for locale, item in sorted(value['locales'].items()):
        require(isinstance(item, dict) and set(item) == {
                    'failedJobRoot', 'failedJobId', 'roundRoot', 'directPaidBudgetRoot'},
                'invalid_partial_recovery_configuration')
        failed_job_root = _path(path.parent, item['failedJobRoot'])
        round_root = _path(path.parent, item['roundRoot'])
        direct_budget_root = _path(path.parent, item['directPaidBudgetRoot'])
        require(payload_cache is not None and locale in payload_cache
                and payload_cache[locale]['root'] == round_root,
                'partial_recovery_requires_matching_success_root')
        snapshot = _partial_recovery_snapshot(
            failed_job_root, item['failedJobId'], round_root, direct_budget_root, locale)
        result[locale] = {
            'failedJobRoot': failed_job_root, 'failedJobId': item['failedJobId'],
            'roundRoot': round_root, 'budgetRoot': direct_budget_root,
            'snapshot': snapshot, 'identity': snapshot['sha256'],
        }
    return result


def load_configuration(path):
    path = _safe_path(Path(path).absolute())
    value = _json(path)
    required_keys = {'schemaVersion', 'productionRunId', 'inspectionConfig', 'jobRoot', 'locales'}
    # v1-v3 remain production contracts; shadow has a distinct v4 identity.
    candidate_mode = value.get('candidateMode', 'production') if isinstance(value, dict) else 'production'
    require(((set(value) == required_keys and value['schemaVersion'] == SCHEMA)
             or (set(value) == required_keys | {'concurrencyProfile', 'resourcePolicy'}
                 and value['schemaVersion'] == CONCURRENT_SCHEMA)
             or (set(value) == required_keys | {'layer2AutoRepair'}
                 and value['schemaVersion'] in {AUTO_REPAIR_SCHEMA, QC_REPAIR_SCHEMA})
             or (set(value) == required_keys | {'layer2AutoRepair', 'layer2PayloadCache'}
                 and value['schemaVersion'] == PAYLOAD_CACHE_SCHEMA)
             or (set(value) == required_keys | {'layer2AutoRepair', 'layer2PayloadCache',
                                                  'layer2PartialRecovery'}
                 and value['schemaVersion'] == PARTIAL_RECOVERY_SCHEMA)
             or (set(value) == required_keys | {'layer2AutoRepair', 'candidateMode'}
                 and value['schemaVersion'] == SHADOW_SCHEMA and candidate_mode == 'shadow')
             or (set(value) == required_keys | {'layer2AutoRepair', 'layer2GroupRevision'}
                 and value['schemaVersion'] == GROUP_REVISION_SCHEMA))
            and pipeline._sha(value['productionRunId'])
            and isinstance(value['locales'], dict) and bool(value['locales'])
            and set(value['locales']) <= set(pipeline.LOCALES), 'invalid_execution_configuration')
    repair_binding = (_auto_repair_binding(value['layer2AutoRepair'],
                                           allow_qc=value['schemaVersion'] in {QC_REPAIR_SCHEMA,
                                                                               PAYLOAD_CACHE_SCHEMA,
                                                                               PARTIAL_RECOVERY_SCHEMA})
                      if value['schemaVersion'] in {AUTO_REPAIR_SCHEMA, SHADOW_SCHEMA, QC_REPAIR_SCHEMA,
                                                    PAYLOAD_CACHE_SCHEMA, PARTIAL_RECOVERY_SCHEMA,
                                                    GROUP_REVISION_SCHEMA} else None)
    payload_cache = (_payload_cache_binding(value['layer2PayloadCache'], path, value['locales'])
                     if value['schemaVersion'] in {PAYLOAD_CACHE_SCHEMA, PARTIAL_RECOVERY_SCHEMA} else None)
    partial_recovery = (_partial_recovery_binding(
        value['layer2PartialRecovery'], path, value['locales'], payload_cache)
        if value['schemaVersion'] == PARTIAL_RECOVERY_SCHEMA else None)
    require(partial_recovery is None or repair_binding['groupWorkers'] == 1,
            'partial_recovery_requires_serial_group_worker')
    revisions = None
    if value['schemaVersion'] == GROUP_REVISION_SCHEMA:
        named = value['layer2GroupRevision']
        # The operator's per-group notes are the revision's only brief; meaning notes reopen a repair chain.
        require('sourceMeaningNotes' not in repair_binding, 'invalid_execution_configuration')
        require(isinstance(named, dict) and bool(named) and set(named) <= set(value['locales'])
                and all(type(item) is str and item for item in named.values()), 'invalid_execution_configuration')
        revisions = {}
        for locale, item in sorted(named.items()):
            try:
                loaded = group_revision.load_request(_path(path.parent, item))
            except (OSError, ValueError, KeyError, TypeError) as error:
                raise ValueError('invalid_group_revision_request') from error
            require(loaded['value']['targetLocale'] == locale, 'invalid_group_revision_request')
            revisions[locale] = loaded
    inspection_path = _path(path.parent, value['inspectionConfig'])
    inspection = _json(inspection_path)
    require(inspection.get('schemaVersion') == packages.SCHEMA
            and isinstance(inspection.get('locales'), dict)
            and set(value['locales']) <= set(inspection['locales']), 'execution_locale_not_in_inspection')
    root = inspection_path.parent
    job_root = _path(path.parent, value['jobRoot'])
    input_paths = [path, inspection_path, _path(root, inspection.get('source')),
                   _path(root, inspection.get('anchor'))]
    if payload_cache:
        input_paths.extend(item['root'] for item in payload_cache.values() if item['root'] is not None)
    if partial_recovery:
        input_paths.extend(item for binding in partial_recovery.values()
                           for item in (binding['failedJobRoot'], binding['roundRoot'], binding['budgetRoot']))
    if revisions:
        input_paths.extend(item for loaded in revisions.values() for item in group_revision.input_paths(loaded))
    if repair_binding and repair_binding.get('sourceMeaningNotes'):
        notes_path = _path(path.parent, repair_binding['sourceMeaningNotes'])
        repair_binding['sourceMeaningNotes'] = str(notes_path)
        input_paths.append(notes_path)
    if repair_binding and repair_binding.get('backTranslationQc'):
        require(set(repair_binding['backTranslationQc']) <= set(value['locales']), 'invalid_execution_configuration')
        qc_paths = {locale: _path(path.parent, item) for locale, item in repair_binding['backTranslationQc'].items()}
        repair_binding['backTranslationQc'] = {locale: str(item) for locale, item in qc_paths.items()}
        input_paths.extend(qc_paths.values())
    concurrency_profile = resource_policy = None
    if 'concurrencyProfile' in value:
        load_profile = _text.current().compute.load_profile
        profile_path = _path(path.parent, value['concurrencyProfile'])
        resource_path = _path(path.parent, value['resourcePolicy'])
        concurrency_profile = load_profile(profile_path)
        resource_policy = _text.current().resources.validate_policy(_json(resource_path))
        require(resource_policy['capacities']['codex_cli'] == concurrency_profile['totalCodexSlots'],
                'concurrency_profile_requires_shared_24_slot_broker')
        input_paths.extend((profile_path, resource_path))
    lanes, plugin_hashes = {}, {}
    for locale, lane in sorted(value['locales'].items()):
        require(isinstance(lane, dict) and set(lane) == {'outputDirectory', 'plugin'}, 'invalid_execution_lane')
        output, plugin = (_path(path.parent, lane[key]) for key in ('outputDirectory', 'plugin'))
        require(plugin.is_file() and not _overlap(output, job_root), 'invalid_execution_paths')
        inspect_lane = inspection['locales'][locale]
        require(isinstance(inspect_lane, dict), 'invalid_inspection_lane')
        policy = _path(root, inspect_lane.get('policy'))
        if payload_cache is not None:
            require(models.production_backend(_json(policy)) == 'openai_api',
                    'payload_cache_requires_openai_api')
        candidate = output / 'candidate.json'
        if 'candidate' in inspect_lane:
            require(_path(root, inspect_lane['candidate']) == candidate, 'candidate_output_path_changed')
        # No execution field can inject an argv/model/secret/approval override.
        lanes[locale] = {'output': output, 'plugin': plugin, 'policy': policy, 'candidate': candidate}
        plugin_hashes[locale] = producer.plugin_implementation_sha256(plugin)
        input_paths.extend((plugin, policy))
    outputs = [lane['output'] for lane in lanes.values()]
    # Derived durable roots: clearing a lane output must never erase repair or budget history.
    durable = [job_root.parent / ('.' + job_root.name + suffix) for suffix in ('.layer2-repair', '.layer2-budget')]
    cache_roots = ([item['root'] for item in payload_cache.values() if item['root'] is not None]
                   if payload_cache else [])
    non_cache_inputs = [item for item in input_paths if item not in cache_roots]
    require(not any(_overlap(output, path) for output in outputs for path in input_paths + durable)
            and not any(_overlap(cache_root, path) for cache_root in cache_roots
                        for path in [job_root, *durable, *non_cache_inputs])
            and not any(_overlap(a, b) for i, a in enumerate(cache_roots)
                        for b in cache_roots[i + 1:])
            and not any(_overlap(a, b) for i, a in enumerate(outputs) for b in outputs[i + 1:]),
            'execution_paths_overlap')
    binding = {'execution': value, 'inspection': inspection, 'plugins': plugin_hashes}
    if payload_cache is not None:
        binding['payloadCacheSnapshots'] = {
            locale: item['descriptor'] for locale, item in sorted(payload_cache.items())}
    if partial_recovery is not None:
        binding['partialRecoverySnapshots'] = {
            locale: item['snapshot'] for locale, item in sorted(partial_recovery.items())}
    if concurrency_profile is not None:
        binding.update(concurrencyProfile=concurrency_profile, resourcePolicy=resource_policy)
    sha = jobs._digest(binding)
    return Configuration(path, root, inspection, job_root, value['productionRunId'], lanes, sha,
                         concurrency_profile, resource_policy, repair_binding,
                         candidate_mode, payload_cache, partial_recovery, revisions)


def repair_ledger_root(config):
    """Fixed per-run ledger beside the job root, like the budget root; clearing a
    lane's output directory never resets the repair history."""
    return config.job_root.parent / ('.' + config.job_root.name + '.layer2-repair')


def code_identity():
    # Pin the runtime source/schema closure, not a branch name or stale commit
    # label. The worker rechecks it before any paid call and candidate admission.
    # Code that moved into the production package runs from there; scripts/
    # keeps only its import facade, so the package source is part of the closure. Package commands
    # also run through tools/ops/run.py, which binds the host and picks the module, so it is hashed too.
    root = _text.current().core.repo_root
    files = sorted([*root.joinpath('scripts').rglob('*.py'), *root.joinpath('packages/production/src').rglob('*.py'),
                    *root.joinpath('schemas').rglob('*.json'), root / 'docs/series-terminology.zh.md',
                    root / 'tools/ops/sermon_unified_preflight.py', root / 'tools/ops/run.py'])
    return jobs._digest({str(p.relative_to(root)): hashlib.sha256(_safe_path(p).read_bytes()).hexdigest() for p in files})


def package_view(config):
    effective = copy.deepcopy(config.inspection)
    for locale, lane in config.lanes.items():
        candidate = _safe_path(lane['candidate'])
        if candidate.exists():
            effective['locales'][locale]['candidate'] = str(candidate)
        else:
            # Only this registered future output may be absent. An existing
            # invalid package is always validated and blocks the lane.
            effective['locales'][locale].pop('candidate', None)
    view = packages.inspect_configuration(config.inspection_root, effective, candidate_mode=config.candidate_mode)
    notes = (getattr(config, 'auto_repair', None) or {}).get('sourceMeaningNotes')
    if notes:
        # The meaning notes the repair loop reads are a Layer 1 input of every text job: new notes are
        # a new job identity (durable._input_identity), which `reopen-repair` lets supersede a failed one.
        digest = jobs._digest(_json(Path(notes)))
        view['packageIdentities']['sourceMeaningNotes'] = digest
        view['stateRevision'] = jobs._digest({'packages': view['stateRevision'], 'sourceMeaningNotes': digest})
    for locale, qc in sorted(((getattr(config, 'auto_repair', None) or {}).get('backTranslationQc') or {}).items()):
        # A failed back-translation QC receipt is an input of that locale's text job (gate 4):
        # a new receipt is a new job identity whose worker reopens the passed repair chain.
        digest = jobs._digest(_json(Path(qc)))
        view['packageIdentities']['backTranslationQc.' + locale] = digest
        view['stateRevision'] = jobs._digest({'packages': view['stateRevision'],
                                              'backTranslationQc.' + locale: digest})
    for locale, loaded in sorted((getattr(config, 'group_revision', None) or {}).items()):
        # The group list, notes, prior candidate and operator decision are inputs of that locale's
        # text job: a new list or note is a new job identity.
        key = 'groupRevision.' + locale
        view['packageIdentities'][key] = group_revision.identity(loaded)
        view['stateRevision'] = jobs._digest({'packages': view['stateRevision'], key: view['packageIdentities'][key]})
    for locale, binding in sorted((getattr(config, 'payload_cache', None) or {}).items()):
        # The resolved path stays in the execution configuration. Durable
        # identity receives only the content/implementation descriptor digest.
        key = 'payloadCache.' + locale
        view['packageIdentities'][key] = binding['identity']
        view['stateRevision'] = jobs._digest({'packages': view['stateRevision'], key: binding['identity']})
    for locale, binding in sorted((getattr(config, 'partial_recovery', None) or {}).items()):
        key = 'partialRecovery.' + locale
        view['packageIdentities'][key] = binding['identity']
        view['stateRevision'] = jobs._digest({'packages': view['stateRevision'], key: binding['identity']})
    return view


def _payload_cache_for(config, locale):
    binding = (getattr(config, 'payload_cache', None) or {}).get(locale)
    return (binding['root'] if binding else None, bool(binding),
            binding['identity'] if binding else None, binding['required'] if binding else False)


def _partial_recovery_for(config, locale):
    return (getattr(config, 'partial_recovery', None) or {}).get(locale)


def join_jobs(config, view):
    """The package view joined with this run's durable jobs, a reopen checked against its lane's evidence."""
    return durable.project(view, config.job_root, config.run_id, verify_reopen=_reopen_verifier(config))


def _reopen_verifier(config):
    """Checks a reopen receipt against the evidence it names before its failed job may yield.

    Every receipt along a chain names this lane's repair ledger as it was: the entry at
    its sequence is the one it hashed, that entry stopped, and every group the receipt
    reopened was stopped there for source review. The receipt naming the text node's
    identity now is the one a new job runs under, so it is checked in full: its notes are
    the configured notes, and its groups are the ones those notes reopen from that entry
    or, once the reopened job has begun, the ones its worker's reopen entry records under
    those same notes. Its
    configuration and code hashes record what the controller ran under; both may change
    after a reopen (a deploy, a configuration edit) without changing what it proved, and
    the worker checks its own before any paid call."""
    ledgers = {}

    def verify(receipt, observed, expected):
        locale = receipt['identity']['workUnitId'][len('text.'):]
        require(locale in config.lanes and bool(config.auto_repair), 'reopen_lane_not_registered')
        original = jobs._read(_safe_path(config.job_root / receipt['jobId'] / 'request.json'))
        _, cache_enabled, cache_identity, _ = _payload_cache_for(config, locale)
        require(_command_option(original.get('command'), '--expected-payload-cache')
                == (cache_identity if cache_enabled else None), 'reopen_payload_cache_binding_changed')
        recovery = _partial_recovery_for(config, locale)
        require(_command_option(original.get('command'), '--expected-partial-recovery')
                == (recovery['identity'] if recovery is not None else None),
                'reopen_partial_recovery_binding_changed')
        if locale not in ledgers:
            source, anchor, policy = _lane_values(config, locale, observed)
            ledgers[locale] = (auto_repair.load_ledger(repair_ledger_root(config), auto_repair.lineage(
                producer.prepare_request(source, anchor, policy, candidate_mode=config.candidate_mode))), source, anchor)
        entries, source, anchor = ledgers[locale]
        sequence, groups = receipt['repairLedgerSequence'], receipt['reopenedGroups']
        head = entries[sequence - 1] if sequence <= len(entries) else None
        require(head is not None and auto_repair.json_sha256(head) == receipt['repairLedgerHeadSha256']
                and head['outcome'] == 'stopped', 'reopen_ledger_head_changed')
        # A human ruling (layer2_human_ruling) may also answer a request_human_review stop.
        reasons = {'request_source_review', 'request_human_review'}
        held = {row['translationGroupId'] for row in head['stopped'] if row['reasonCode'] in reasons}
        require(set(groups) <= held, 'reopen_group_not_stopped_for_source_review')
        if receipt['nextIdentity'] != expected:
            return
        require(receipt['meaningNotesSha256'] == observed['packageIdentities'].get('sourceMeaningNotes'),
                'reopen_meaning_notes_changed')
        notes = source_meaning.load_meaning_notes(Path(config.auto_repair['sourceMeaningNotes']),
                                                  source=source, anchor=anchor)
        if len(entries) > sequence:
            # The reopen entry must be the one a worker wrote under these notes: an entry written under
            # earlier notes (whose chain may since have passed) cannot vouch for a receipt toward new ones.
            reopened = entries[sequence]
            require('reopenedBy' in reopened
                    and reopened['reopenedBy']['meaningNotesSha256'] == observed['packageIdentities']['sourceMeaningNotes'],
                    'reopen_entry_notes_changed')
            require(sorted(row['translationGroupId'] for row in reopened['groups']) == groups,
                    'reopen_groups_changed')
        else:
            require(sorted(auto_repair.reopenable_groups(entries, notes)) == groups, 'reopen_groups_changed')
    return verify


def snapshot(config):
    view = join_jobs(config, package_view(config))
    rejected = []
    for locale in config.lanes:
        unit = 'text.' + locale
        if view['nodes'].get(unit, {}).get('status') == 'ready':
            try:
                _inputs(config, locale, view)
            except (ValueError, OSError, KeyError, TypeError) as error:
                reason = 'layer2_rule_preflight_failed' if str(error).startswith('Layer 2 rule preflight:') else 'fixed_layer2_admission_invalid'
                view['nodes'][unit].update(status='blocked', reasonCode=reason)
                rejected.append(unit)
    view['stateRevision'] = jobs._digest({'packageAndJobs': view['stateRevision'],
                                        'configuration': config.sha256, 'rejectedLanes': sorted(rejected)})
    return view


def _lane_values(config, locale, view):
    """The lane's source, anchor and policy, as the view inspected them."""
    lane = config.lanes[locale]
    paths = {'source': _path(config.inspection_root, config.inspection['source']),
             'anchor': _path(config.inspection_root, config.inspection['anchor']),
             'policy.' + locale: lane['policy']}
    values = {key: packages._read_package(path.parent, str(path), {}, key) for key, path in paths.items()}
    require(all(jobs._digest(value) == view['packageIdentities'].get(key) for key, value in values.items()),
            'inputs_changed_after_inspection')
    return values['source'], values['anchor'], values['policy.' + locale]


def _inputs(config, locale, view):
    lane = config.lanes[locale]
    source, anchor, policy = _lane_values(config, locale, view)
    require(producer.plugin_implementation_sha256(lane['plugin']) == policy['languageReview']['pluginImplementationSha256'],
            'plugin_does_not_match_frozen_policy')
    # Fixed production models and the canonical runner's worker budget bound paid work.
    efforts = models.production_efforts(policy)
    require(all(policy[role]['model'] == model and policy[role]['reasoningEffort'] == efforts[role]
                for role, model in models.production_models(policy).items()), 'production_model_policy_changed')
    require(policy['batching']['batchSize'] == 1 and type(policy['batching']['workers']) is int
            and 1 <= policy['batching']['workers'] <= api_concurrency.MAX_GROUP_WORKERS_PER_LOCALE,
            'invalid_production_worker_budget')
    request = producer.prepare_request(source, anchor, policy, candidate_mode=config.candidate_mode)
    plan = models.group_plan(request, anchor)
    rule_preflight.preflight(request, policy, lane['plugin'], plan)
    return source, anchor, policy


def _revision_gate(config, locale, view):
    """None when ``locale`` has no group revision or its request passes every pre-dispatch check;
    otherwise the public reason (and the unlisted groups the current plugin rejects).

    Read-only: shadow and execute ticks run it before a job exists, so a list that misses a
    failing group is corrected without leaving a failed durable job behind."""
    loaded = (getattr(config, 'group_revision', None) or {}).get(locale)
    if loaded is None:
        return None
    try:
        source, anchor, policy = _inputs(config, locale, view)
        request = producer.prepare_request(source, anchor, policy, candidate_mode=config.candidate_mode)
        rules = rule_preflight.preflight(request, policy, config.lanes[locale]['plugin'],
                                         models.group_plan(request, anchor))
        group_revision.prepare(loaded, source, anchor, policy, config.lanes[locale]['plugin'], rules)
    except group_revision.GroupRevisionGateFailed as failed:
        return {'reasonCode': 'group_revision_unlisted_groups_fail_current_checks',
                'unlistedFailures': failed.report['unlistedFailures']}
    except (ValueError, OSError, KeyError, TypeError) as error:
        reason = str(error).split(':')[0]
        return {'reasonCode': reason if reason.startswith('group_revision_') else 'group_revision_inputs_invalid'}
    return None


def _unreconciled_paid_call(config, locale):
    """A started-call marker with neither a validated cache nor a saved raw
    response is an unknown paid outcome. The runner's reconciliation check uses
    the same rule, so one malformed but persisted response does not block other
    locales."""
    lane = config.lanes.get(locale)
    if lane is None or not lane['output'].is_dir():
        return False
    for marker in lane['output'].rglob('*.started.json'):
        stem = marker.name.removesuffix('.started.json')
        if not (marker.with_name(f'{stem}.json').is_file() or marker.with_name(f'{stem}.raw.json').is_file()):
            return True
    return False


def _locale_capacity(config):
    if config.concurrency_profile:
        return config.concurrency_profile['maxActiveLocales']
    if getattr(config, 'auto_repair', None):
        return config.auto_repair['maxActiveLocales']
    return MAX_ACTIVE_LAYER2_JOBS


def _worker_command(config, locale, job_id, code_sha, budget_authorization=None):
    # The host names the package entry (tools/ops/run.py text.controller); recovery
    # compares this argv with the one the durable job recorded.
    command = _text.current().worker_command('worker', '--config', str(config.path),
            '--locale', locale, '--expected-configuration', config.sha256,
            '--expected-code', code_sha, '--expected-job', job_id)
    _, enabled, identity, _ = _payload_cache_for(config, locale)
    if enabled:
        command += ['--expected-payload-cache', identity]
    recovery = _partial_recovery_for(config, locale)
    if recovery is not None:
        command += ['--expected-partial-recovery', recovery['identity']]
    if budget_authorization is not None:
        command += ['--budget-authorization', str(budget_authorization['path']),
                    '--expected-budget', budget_authorization['sha256']]
    return command


def _command_option(command, name):
    require(isinstance(command, list) and command.count(name) <= 1, 'original_execution_binding_changed')
    if name not in command:
        return None
    index = command.index(name)
    require(index + 1 < len(command) and isinstance(command[index + 1], str),
            'original_execution_binding_changed')
    return command[index + 1]


class Controller:
    def __init__(self, config_path, *, mode='deterministic_shadow', budget_authorization=None):
        require(mode in MODES, 'invalid_controller_mode')
        self.config = load_configuration(config_path)
        self.code_sha = code_identity()
        self.mode = mode
        self.budget_authorization = (budget_tools.load_authorization(
            self.config, budget_authorization, self.code_sha) if budget_authorization is not None else None)
        if self.budget_authorization is not None:
            budget_tools.verify_runtime(self.budget_authorization)

    def _result(self, status, reason, **fields):
        return {'schemaVersion': 'sermon-canonical-layer2-controller-result-v1',
                'mode': self.mode, 'scope': 'four_layer_release_layer2_preparation',
                'productionRunId': self.config.run_id, 'configurationSha256': self.config.sha256,
                'codeIdentitySha256': self.code_sha, 'status': status, 'reasonCode': reason,
                'maxConcurrentLocaleJobs': _locale_capacity(self.config),
                'maxInFlightApiCalls': api_concurrency.MAX_IN_FLIGHT_API_CALLS,
                'runtimeCodexTurns': 0, 'contentAcceptance': 'not_evaluated',
                'deviceAcceptance': 'not_run', **fields}

    def _fresh(self):
        current = load_configuration(self.config.path)
        require(current.sha256 == self.config.sha256 and code_identity() == self.code_sha, 'configuration_or_code_changed')
        if self.budget_authorization is not None:
            budget_tools.load_authorization(current, self.budget_authorization['path'], self.code_sha,
                                            self.budget_authorization['sha256'])
            budget_tools.verify_runtime(self.budget_authorization)
        return current, snapshot(current)

    def _capacity_full(self, view):
        # The canonical contract reserves one locale slot until completion or
        # reconciliation of an uncertain owner.
        active = [row for row in view['durableJobInspection']['jobs']
                  if row['workUnitId'].startswith('text.') and row['status'] in jobs.ACTIVE | {'uncertain'}]
        if any(row['status'] == 'uncertain' for row in active):
            return True  # preserve the existing run-wide unknown reconciliation barrier
        if any(row['workUnitId'].startswith('text.') and row['status'] == 'failed'
               and _unreconciled_paid_call(self.config, row['workUnitId'][len('text.'):])
               for row in view['durableJobInspection']['jobs']):
            return True  # a failed worker left a paid call with an unknown outcome
        return len(active) >= _locale_capacity(self.config)

    def _choose(self, view, requested_locale=None):
        if self._capacity_full(view):
            return None
        if requested_locale is not None:
            require(requested_locale in self.config.lanes, 'locale_not_registered')
        for locale in ([requested_locale] if requested_locale else sorted(self.config.lanes)):
            if view['nodes'].get('text.' + locale, {}).get('status') == 'ready':
                return locale
        return None

    def tick(self, *, requested_locale=None):
        try:
            config, observed = self._fresh()
        except (ValueError, OSError, KeyError, TypeError):
            return self._result('blocked', 'configuration_code_or_evidence_invalid', dispatched=False)
        locale = self._choose(observed, requested_locale)
        gate = _revision_gate(config, locale, observed) if locale else None
        if gate is not None:
            return self._result('blocked', gate['reasonCode'], proposedWorkUnit='text.' + locale,
                                groupRevision=gate, stateRevision=observed['stateRevision'], dispatched=False)
        if self.mode == 'deterministic_shadow':
            return self._result('ready' if locale else 'waiting',
                                'layer2_capacity_reached' if self._capacity_full(observed) else 'shadow_only',
                                proposedWorkUnit='text.' + locale if locale else None,
                                stateRevision=observed['stateRevision'], nodes=observed['nodes'], dispatched=False)
        with jobs._lock(config.job_root, ADMISSION_LOCK) as (_, _, held):
            if not held:
                return self._result('waiting', 'admission_busy', dispatched=False)
            dispatch_attempted = False
            try:
                config, fresh = self._fresh()
                require(fresh['stateRevision'] == observed['stateRevision'], 'stale_state_revision')
                locale = self._choose(fresh, requested_locale)
                if locale is None:
                    reason = 'layer2_capacity_reached' if self._capacity_full(fresh) else 'no_admitted_layer2_work'
                    return self._result('waiting', reason, nodes=fresh['nodes'], dispatched=False)
                _inputs(config, locale, fresh)
                require(_revision_gate(config, locale, fresh) is None, 'group_revision_gate_blocked')
                ident = durable.identity(fresh, config.run_id, 'text.' + locale)
                key = jobs._digest(ident)
                dispatch_attempted = True
                outcome = jobs.start_job(config.job_root, ident, _worker_command(config, locale, key, self.code_sha, self.budget_authorization),
                                         timeout_seconds=21600, liveness_policy=LIVENESS_POLICY)
            except (ValueError, OSError, KeyError, TypeError):
                # Any persisted job intent remains discoverable; never retry an
                # uncertain start merely because this controller got an error.
                return self._result('blocked', 'admission_or_dispatch_requires_inspection',
                                    dispatched=None if dispatch_attempted else False)
            return self._result('waiting', 'verify_durable_job_and_candidate_evidence',
                                workUnitId='text.' + locale, job=outcome, dispatched=True)


def execute(config_path, locale, expected_configuration, expected_code, expected_job, *, caller=None, api_key=None,
            budget_authorization=None, expected_budget=None, expected_payload_cache=None,
            expected_partial_recovery=None):
    """Fixed worker body. New jobs use the bound project API budget transport."""
    config = load_configuration(config_path)
    require(locale in config.lanes and config.sha256 == expected_configuration
            and code_identity() == expected_code, 'worker_configuration_or_code_changed')
    payload_cache_root, payload_cache_enabled, payload_cache_identity, payload_cache_required = _payload_cache_for(config, locale)
    require((expected_payload_cache is None and not payload_cache_enabled)
            or expected_payload_cache == payload_cache_identity,
            'worker_payload_cache_binding_changed')
    partial_recovery = _partial_recovery_for(config, locale)
    require((expected_partial_recovery is None and partial_recovery is None)
            or partial_recovery is not None
            and expected_partial_recovery == partial_recovery['identity'],
            'worker_partial_recovery_binding_changed')
    budget_binding = (budget_tools.load_authorization(config, budget_authorization, expected_code, expected_budget)
                      if budget_authorization is not None else None)
    require((budget_authorization is None) == (expected_budget is None), 'budget_worker_binding_required')
    if payload_cache_enabled and budget_binding is not None:
        require(budget_binding.get('runtimeIdentity') is not None,
                'payload_cache_requires_runtime_bound_budget')
    if partial_recovery is not None and budget_binding is not None:
        require(budget_binding.get('reuseBudgetRoots') is not None
                and partial_recovery['budgetRoot'] in
                    budget_binding['reuseBudgetRoots'][locale],
                'partial_recovery_budget_root_not_approved')
    lane = config.lanes[locale]
    with work_lock(lane['output']), accounting.accounting_session(
            lane['output'] / 'accounting', 'canonical_layer2_worker',
            {'targetLocale': locale, 'jobSha256': expected_job, 'productionRunId': config.run_id}, evidence_directory=lane['output']):
        with accounting.stage('layer2.worker_admission.' + locale, depends_on=[],
                executor_type='deterministic_program', work_unit_id='l2.' + locale + '.worker_admission') as admission_span:
            current = package_view(config)
            require(current['nodes']['text.' + locale]['status'] == 'ready', 'worker_node_not_ready')
            joined = join_jobs(config, current)
            require(joined['nodes']['source']['status'] == 'validated'
                    and joined['nodes']['text.' + locale]['status'] == 'waiting_job'
                    and joined['nodes']['text.' + locale].get('reasonCode') == 'durable_job_active',
                    'worker_durable_admission_changed')
            ident = durable.identity(current, config.run_id, 'text.' + locale)
            require(jobs._digest(ident) == expected_job, 'worker_inputs_changed')
            request_path = config.job_root / expected_job / 'request.json'
            request = jobs._read(request_path)
            require(jobs._request_valid(request, expected_job) and request['identity'] == ident
                    and request['command'] == _worker_command(config, locale, expected_job, expected_code, budget_binding)
                    and request.get('livenessPolicy') == LIVENESS_POLICY
                    and jobs.peek_job(config.job_root, expected_job)['status'] == 'running',
                    'worker_requires_active_bound_durable_job')
            source, anchor, policy = _inputs(config, locale, current)
        with liveness.report(request_path.parent, request) as progress:
            budgeted = None
            if caller is None:
                require(budget_binding is not None, 'bound_budget_authorization_required')
                # OpenAI API only: no Spark session (2026-10-13; only GPU stages occupy Spark).
                route = _text.current().provider.route.selected()
                require(route is not None, 'openai_layer2_requires_explicit_dev_or_prod_launcher')
                api_key = os.environ['OPENAI_API_KEY']
                # The policy's frozen Layer 2 backend picks the transport: the OpenAI API (Sol), or
                # the subscription Claude CLI for both roles (claude_cli_opus).
                backend = models.production_backend(policy)
                transports = claude_transports(policy, lane) if backend == 'claude_cli_opus' else None
                caller = budget_tools.BudgetedCaller(budget_binding, config, source, anchor, policy,
                                                     claude_transports=transports)
                budgeted = caller
                if transports is not None:
                    caller.execution_identity = {
                        'schemaVersion': 'claude-layer2-budget-transport-identity-v1', 'backend': 'claude_cli',
                        'layer2Backend': backend,
                        'transports': {role: t.execution_identity for role, t in sorted(transports.items())},
                        'budgetAuthorizationSha256': budget_binding['sha256']}
                elif budget_binding.get('runtimeIdentity') is None:
                    caller.execution_identity = {
                        'schemaVersion': 'openai-layer2-budget-transport-identity-v1',
                        'backend': 'openai_api', 'route': route,
                        'budgetAuthorizationSha256': budget_binding['sha256']}
                caller = _text.current().compute.session_bound_caller(caller, requires_spark=False, outcome_guarded=True)
            elif budget_binding is not None:
                _text.current().compute.reject_cli_transport(caller)
                caller = budget_tools.BudgetedCaller(budget_binding, config, source, anchor, policy, transport=caller)
                budgeted = caller
            def current_binding():
                fresh_config = load_configuration(config.path)
                require(fresh_config.sha256 == expected_configuration and code_identity() == expected_code,
                        'worker_configuration_or_code_changed_during_models')
                fresh = package_view(fresh_config)
                require(fresh['nodes']['text.' + locale]['status'] == 'ready'
                        and jobs._digest(durable.identity(fresh, config.run_id, 'text.' + locale)) == expected_job,
                        'worker_inputs_changed_during_models')
                return fresh_config
            def bound_call(key, payload):
                current_binding()
                with api_concurrency.request_slot(config.job_root):
                    current_binding()
                    progress.progress('model_request')
                    return caller(key, payload)
            # Preserve passive transport metadata. Cache-sensitive methods get
            # wrappers below so a hit rechecks config/code/package identity just
            # like a paid dispatch; otherwise prior bytes could change between
            # admission and copy without ever entering bound_call().
            for attribute in ('execution_identity', 'completed_content', 'admit_resource', 'billing'):
                if hasattr(caller, attribute):
                    setattr(bound_call, attribute, getattr(caller, attribute))
            if hasattr(caller, 'verify_execution'):
                def verify_execution(key):
                    current_binding()
                    result = caller.verify_execution(key)
                    current_binding()
                    return result
                bound_call.verify_execution = verify_execution
            for attribute in ('paid_response_provenance', 'record_reuse',
                              'validate_recovery_source', 'recover_returned_response'):
                if hasattr(caller, attribute):
                    operation = getattr(caller, attribute)
                    def guarded(*args, _operation=operation, **kwargs):
                        current_binding()
                        result = _operation(*args, **kwargs)
                        current_binding()
                        return result
                    setattr(bound_call, attribute, guarded)
            model_completion = []
            revision = None
            with (budget_tools.request_limits(budget_binding['limits']) if budget_binding else nullcontext()):
                if locale in (getattr(config, 'group_revision', None) or {}):
                    evidence, model_output, revision = _run_group_revision(
                        config, lane, source, anchor, policy, api_key, bound_call, progress.progress,
                        admission_span, model_completion,
                        revision_digest=current['packageIdentities']['groupRevision.' + locale],
                        remaining_cost_microusd=budgeted.remaining_cost_microusd() if budgeted is not None else None)
                elif config.auto_repair:
                    evidence, model_output = _run_auto_repair(
                        config, lane, source, anchor, policy, api_key, bound_call, progress.progress,
                        admission_span, model_completion,
                        qc_digest=current['packageIdentities'].get('backTranslationQc.' + locale))
                else:
                    model_output = lane['output']
                    evidence = models.run_accounted(source, anchor, policy, model_output, api_key,
                                                 bound_call, None, lane['plugin'], None, None,
                                                 progress_callback=progress.progress, predecessor_spans=[admission_span],
                                                 completion_spans=model_completion, candidate_mode=config.candidate_mode,
                                                 payload_cache_from=payload_cache_root,
                                                 emit_payload_cache_success=payload_cache_enabled,
                                                 payload_cache_required=payload_cache_required)
            # Paid results remain recoverable if approval/source/config/code drifted
            # while a request was outstanding. Never turn those results into approval.
            with accounting.stage('layer2.post_model_binding.' + locale, depends_on=model_completion,
                    executor_type='deterministic_program', work_unit_id='l2.' + locale + '.post_model_binding') as binding_span:
                progress.progress('models_validated')
                fresh_config = current_binding()
            with accounting.stage('layer2.language_and_candidate.' + locale, depends_on=[binding_span],
                    executor_type='deterministic_program', work_unit_id='l2.' + locale + '.candidate_admission') as candidate_span:
                original_request = producer._load(model_output / 'request.json')
                rule_receipt = producer._load(model_output / 'rule-preflight.json')
                plugin_sha = policy['languageReview']['pluginImplementationSha256']
                receipt = producer.run_language_plugin(source, anchor, policy, original_request, evidence,
                    lane['plugin'], plugin_sha, rule_preflight_receipt=rule_receipt)
                candidate = producer.admit_evidence(source, anchor, policy, original_request, evidence,
                    receipt, lane['plugin'], plugin_sha, rule_preflight_receipt=rule_receipt)
                revision_receipt = (group_revision.receipt(revision['prepared'], candidate, revision['repairReceipt'],
                                                           revision['allowance'], job_id=expected_job)
                                    if revision is not None else None)
                current_binding()
                progress.progress('candidate_validated')
                models.save_new(lane['output'] / 'language-review.json', receipt)
                models.save_new(lane['candidate'], candidate)
                if revision_receipt is not None:
                    models.save_new(lane['output'] / 'group-revision-receipt.json', revision_receipt)
                accounting.record_workload('layer2.candidate_identity', {'candidateSha256': jobs._digest(candidate),
                    'languageReviewSha256': jobs._digest(receipt)})
            with accounting.stage('layer2.final_package_validation.' + locale, depends_on=[candidate_span],
                    executor_type='deterministic_program', work_unit_id='l2.' + locale + '.final_package_validation'):
                checked = package_view(fresh_config)
                require(checked['nodes']['text.' + locale]['status'] == 'validated', 'worker_candidate_not_validated')
            recovery_receipt_sha = None
            if partial_recovery is not None:
                recovery_receipt = {
                    'schemaVersion': PARTIAL_RECOVERY_RECEIPT_SCHEMA,
                    'status': 'recovered_machine_review_pass_human_review_pending',
                    'targetLocale': locale,
                    'predecessorFailedJobId': partial_recovery['failedJobId'],
                    'predecessorSnapshotSha256': partial_recovery['identity'],
                    'successorJobId': expected_job,
                    'successorConfigurationSha256': expected_configuration,
                    'successorCodeIdentitySha256': expected_code,
                    'evidenceSha256': jobs._digest(evidence),
                    'candidateJsonSha256': jobs._digest(candidate),
                    'releaseEligible': False, 'humanApproval': False,
                }
                receipt_path = lane['output'] / 'partial-round-recovery-receipt.json'
                if receipt_path.exists():
                    require(producer._load(receipt_path) == recovery_receipt,
                            'partial_recovery_receipt_changed')
                else:
                    models.save_new(receipt_path, recovery_receipt)
                recovery_receipt_sha = jobs._digest(recovery_receipt)
            return {'status': 'machine_review_pass_human_review_pending',
                    'candidateJsonSha256': jobs._digest(candidate), 'releaseEligible': False,
                    **({'partialRecoveryReceiptSha256': recovery_receipt_sha}
                       if recovery_receipt_sha is not None else {}),
                    **({'groupRevisionReceiptSha256': jobs._digest(revision_receipt)}
                       if revision_receipt is not None else {})}


def _run_auto_repair(config, lane, source, anchor, policy, api_key, call, progress, admission_span,
                     completion_spans, *, qc_digest=None):
    """Run repair rounds inside this durable job, its budget and its lease.

    Every round is a separate runner output under the lane; repaired groups get a
    fresh translator and independent reviewer, the rest reuse the earlier round's
    caches under the same transport identity. Paid calls are reserved by the
    bound budget transport; the loop's 10% repair cap sits below it. A stopped
    loop leaves its receipt and fails the job: no candidate, no automatic retry.
    """
    request = producer.prepare_request(source, anchor, policy, candidate_mode=config.candidate_mode)
    total_groups = len(models.group_plan(request, anchor))
    rounds_root = lane['output'] / 'repair-rounds'

    def run_round(out, reuse_from, brief, collector):
        progress('repair_round')
        payload_cache_root, payload_cache_enabled, _, payload_cache_required = _payload_cache_for(
            config, policy['targetLocale'])
        partial = _partial_recovery_for(config, policy['targetLocale'])
        return models.run_accounted(source, anchor, policy, out, api_key, call, None, lane['plugin'],
                                    None, reuse_from, partial_repair_brief=brief,
                                    progress_callback=progress, predecessor_spans=[admission_span],
                                    completion_spans=completion_spans, failure_collector=collector,
                                    candidate_mode=config.candidate_mode,
                                    payload_cache_from=payload_cache_root if reuse_from is None else None,
                                    partial_recovery_from=(partial['roundRoot']
                                                           if partial is not None and reuse_from is None else None),
                                    partial_recovery_budget_root=(partial['budgetRoot']
                                                                 if partial is not None and reuse_from is None else None),
                                    emit_payload_cache_success=payload_cache_enabled,
                                    payload_cache_required=payload_cache_required if reuse_from is None else False)

    notes = None
    notes_artifact_sha256 = None
    if config.auto_repair.get('sourceMeaningNotes'):
        # Bound to this run's source and anchor and reproduced from their receipt, or refused before dispatch.
        notes_path = Path(config.auto_repair['sourceMeaningNotes'])
        notes_artifact_sha256 = jobs._digest(_json(notes_path))
        notes = source_meaning.load_meaning_notes(notes_path, source=source, anchor=anchor)
        require(jobs._digest(_json(notes_path)) == notes_artifact_sha256, 'meaning_notes_changed_during_load')
    qc_receipt = None
    qc_path = (config.auto_repair.get('backTranslationQc') or {}).get(policy['targetLocale'])
    if qc_path:
        # Exactly the receipt the admitted job identity bound (``qc_digest``), read once; the loop then
        # checks it against this lineage and the chain head's reviewer caches before any dispatch.
        qc_receipt = _json(Path(qc_path))
        require(qc_digest is not None and jobs._digest(qc_receipt) == qc_digest, 'back_translation_qc_changed_after_admission')
    receipt = auto_repair.drive(request, total_groups, run_round, rounds_root, repair_ledger_root(config),
                                group_workers=config.auto_repair['groupWorkers'], meaning_notes=notes,
                                meaning_notes_sha256=notes_artifact_sha256, back_translation_qc=qc_receipt)
    require(receipt['status'] == 'all_groups_passed', 'layer2_auto_repair_stopped')
    final = Path(receipt['finalRunDirectory'])
    require(_overlap(rounds_root.resolve(), final.resolve()) and final.resolve() != rounds_root.resolve(),
            'auto_repair_final_round_outside_lane')
    evidence = producer._load(final / 'evidence.json')
    require(auto_repair.json_sha256(evidence) == receipt['evidenceSha256'], 'auto_repair_evidence_changed')
    return evidence, final


def _run_group_revision(config, lane, source, anchor, policy, api_key, call, progress, admission_span,
                        completion_spans, *, revision_digest, remaining_cost_microusd):
    """Translate again only the groups the lane's revision request lists, inside this job.

    Before any paid call: the request must be the one the admitted job identity bound, the
    current plugin passes every unlisted prior group (or the job fails naming them), and the
    repair allowance is frozen from the listed groups and the budget's remaining USD cap.
    Listed groups then run in parallel through the bounded repair loop on a chain of their
    own; unlisted groups are carried from the prior candidate and make no model call."""
    locale = policy['targetLocale']
    loaded = config.group_revision[locale]
    require(group_revision.identity(loaded) == revision_digest, 'group_revision_changed_after_admission')
    request = producer.prepare_request(source, anchor, policy, candidate_mode=config.candidate_mode)
    plan = models.group_plan(request, anchor)
    rule_receipt = rule_preflight.preflight(request, policy, lane['plugin'], plan)
    prepared = group_revision.prepare(loaded, source, anchor, policy, lane['plugin'], rule_receipt,
                                      gate_report_path=lane['output'] / 'group-revision-plugin-gate.json')
    # Frozen at the first attempt: a resumed job keeps the caps its earlier rounds were chosen under.
    allowance_path = lane['output'] / 'group-revision-allowance.json'
    if allowance_path.exists():
        allowance = producer._load(allowance_path)
        require(allowance.get('listedGroups') == len(prepared['listed']), 'group_revision_allowance_changed')
    else:
        allowance = group_revision.allowance(len(prepared['listed']), policy, remaining_cost_microusd)
        models.save_new(allowance_path, allowance)
    rounds_root = lane['output'] / 'repair-rounds'

    def run_round(out, reuse_from, brief, collector):
        progress('repair_round')
        return models.run_accounted(source, anchor, policy, out, api_key, call, None, lane['plugin'],
                                    None, reuse_from, partial_repair_brief=brief,
                                    progress_callback=progress, predecessor_spans=[admission_span],
                                    completion_spans=completion_spans, failure_collector=collector,
                                    candidate_mode=config.candidate_mode, operator_revision=prepared['brief'])

    repair_receipt = auto_repair.drive(request, len(plan), run_round, rounds_root, repair_ledger_root(config),
                                       group_workers=config.auto_repair['groupWorkers'],
                                       lineage_extra=prepared['lineageExtra'], repair_allowance=allowance)
    require(repair_receipt['status'] == 'all_groups_passed', 'layer2_group_revision_stopped')
    final = Path(repair_receipt['finalRunDirectory'])
    require(_overlap(rounds_root.resolve(), final.resolve()) and final.resolve() != rounds_root.resolve(),
            'auto_repair_final_round_outside_lane')
    evidence = producer._load(final / 'evidence.json')
    require(auto_repair.json_sha256(evidence) == repair_receipt['evidenceSha256'], 'auto_repair_evidence_changed')
    return evidence, final, {'prepared': prepared, 'allowance': allowance, 'repairReceipt': repair_receipt}


REOPEN_RESULT_SCHEMA = 'sermon-canonical-layer2-reopen-result-v1'


def _reopen_plan(config, locale, view):
    """What `reopen-repair` would bind for this lane, or the reason it refuses.

    Exactly one failed text job blocks the lane, no owner or unknown paid call is
    outstanding, the node is the same node with new inputs (the meaning notes),
    and the lane's repair chain stopped with a source-review group the notes now
    settle and no earlier noted repair touched."""
    unit = 'text.' + locale
    rows = [row for row in view['durableJobInspection']['jobs'] if row['workUnitId'] == unit]
    require(not any(row['status'] in jobs.ACTIVE | {'uncertain'} for row in rows), 'job_owner_or_outcome_unsettled')
    failed = [row for row in rows if row['status'] == 'failed']
    require(len(failed) == 1, 'one_failed_text_job_required')
    require(not _unreconciled_paid_call(config, locale), 'unknown_paid_outcome_requires_reconciliation')
    key = failed[0]['jobId']
    request = jobs._read(_safe_path(config.job_root / key / 'request.json'))
    # The worker argv starts with the host's entry prefix; a job recorded under another
    # entry (the scripts/ facade before the D closure window) does not match it.
    prefix = _text.current().worker_command()
    require(jobs._request_valid(request, key) and jobs._digest(request) == failed[0]['requestSha256']
            and request['command'][:len(prefix)] == prefix
            and request['command'][len(prefix):len(prefix) + 5] == ['worker', '--config', str(config.path),
                                                                    '--locale', locale],
            'original_execution_binding_changed')
    _, cache_enabled, cache_identity, _ = _payload_cache_for(config, locale)
    require(_command_option(request['command'], '--expected-payload-cache')
            == (cache_identity if cache_enabled else None), 'reopen_payload_cache_binding_changed')
    recovery = _partial_recovery_for(config, locale)
    require(_command_option(request['command'], '--expected-partial-recovery')
            == (recovery['identity'] if recovery is not None else None),
            'reopen_partial_recovery_binding_changed')
    current = package_view(config)
    following = durable.identity(current, config.run_id, unit)
    require(request['identity']['nodeIdentity'] == following['nodeIdentity'] and request['identity'] != following,
            'reopen_requires_new_meaning_notes')
    source, anchor, policy = _inputs(config, locale, current)
    entries = auto_repair.load_ledger(repair_ledger_root(config),
                                      auto_repair.lineage(producer.prepare_request(source, anchor, policy, candidate_mode=config.candidate_mode)))
    require(bool(entries) and entries[-1]['outcome'] == 'stopped', 'reopen_requires_stopped_repair_chain')
    rounds = (config.lanes[locale]['output'] / 'repair-rounds').resolve()
    head = Path(entries[-1]['runDirectory']).resolve()
    require(_overlap(rounds, head) and head != rounds, 'repair_chain_outside_lane')
    notes = source_meaning.load_meaning_notes(Path(config.auto_repair['sourceMeaningNotes']), source=source, anchor=anchor)
    groups = auto_repair.reopenable_groups(entries, notes)
    require(bool(groups), 'meaning_notes_reopen_no_stopped_group')
    return {'jobId': key, 'request': request, 'stateSha256': failed[0]['stateSha256'], 'nextIdentity': following,
            'repairLedgerHeadSha256': auto_repair.json_sha256(entries[-1]), 'repairLedgerSequence': len(entries),
            'meaningNotesSha256': current['packageIdentities']['sourceMeaningNotes'], 'reopenedGroups': sorted(groups)}


def reopen_repair(config_path, locale, expected_revision):
    """Let a failed text job's stopped repair chain continue under new machine audio meaning notes.

    The failed job keeps its outcome and history. The receipt written beside it
    names the identity the text node has now that the notes are one of its
    inputs; the durable projection then treats the failed job as superseded and
    the next execute tick starts a job under that identity, whose worker reopens
    the same repair ledger for the noted groups only (layer2_auto_repair). This
    makes no model call, writes no candidate and creates no approval."""
    require(pipeline._sha(expected_revision), 'expected_revision_required')
    config = load_configuration(config_path)
    code = code_identity()
    require(locale in config.lanes, 'locale_not_registered')
    require(bool(config.auto_repair and config.auto_repair.get('sourceMeaningNotes')),
            'reopen_requires_source_meaning_notes')
    require(snapshot(config)['stateRevision'] == expected_revision, 'stale_reopen_revision')
    with jobs._lock(config.job_root, ADMISSION_LOCK) as (_, _, admitted):
        require(admitted, 'admission_busy')
        admitted_config = load_configuration(config.path)
        require(admitted_config.sha256 == config.sha256 and code_identity() == code, 'configuration_or_code_changed')
        admitted_view = snapshot(admitted_config)
        require(admitted_view['stateRevision'] == expected_revision, 'stale_reopen_revision')
        plan = _reopen_plan(admitted_config, locale, admitted_view)
        key = plan['jobId']
        with jobs._lock(config.job_root, key) as (folder, _, held):
            require(held, 'job_owner_still_active')
            with work_lock(config.lanes[locale]['output']):
                fresh_config = load_configuration(config.path)
                require(fresh_config.sha256 == config.sha256 and code_identity() == code,
                        'configuration_or_code_changed')
                request, state = jobs._read(folder / 'request.json'), jobs._state(folder, key)
                require(request == plan['request'] and state is not None and state['status'] == 'failed'
                        and state.get('requestSha256') == jobs._digest(request)
                        and jobs._digest(state) == plan['stateSha256'], 'original_execution_binding_changed')
                require(_reopen_plan(fresh_config, locale, snapshot(fresh_config)) == plan, 'reopen_inputs_changed')
                receipt = {'schemaVersion': durable.REOPEN_SCHEMA, 'jobId': key,
                           'requestSha256': jobs._digest(request), 'stateSha256': jobs._digest(state),
                           'identity': request['identity'], 'nextIdentity': plan['nextIdentity'],
                           'configurationSha256': config.sha256, 'codeIdentitySha256': code,
                           **{name: plan[name] for name in ('repairLedgerHeadSha256', 'repairLedgerSequence',
                                                            'meaningNotesSha256', 'reopenedGroups')},
                           'resolution': durable.REOPEN_RESOLUTION}
                path = _safe_path(folder / durable.reopen_file(plan['nextIdentity']))
                if path.exists():
                    require(jobs._read(path) == receipt, 'immutable_reopen_conflict')
                else:
                    # Atomic durable publication under the job lock; state.json, request.json, logs, an
                    # earlier receipt and the repair ledger are never rewritten.
                    jobs._persist(path, receipt)
                with path.open('rb') as stream:
                    jobs.os.fsync(stream.fileno())
                jobs._sync_directory_ancestry(folder)
                return {'schemaVersion': REOPEN_RESULT_SCHEMA, 'status': 'reopened', 'jobId': key,
                        'workUnitId': 'text.' + locale, 'receiptSha256': jobs._digest(receipt),
                        'originalJobStatus': 'failed', 'nextJobId': jobs._digest(plan['nextIdentity']),
                        'reopenedGroups': plan['reopenedGroups'], 'modelCalls': 0, 'runtimeCodexTurns': 0,
                        'humanApprovalCreated': False}


def claude_transports(policy, lane):
    """One subscription-login Claude CLI transport per role, at the policy's frozen model and effort.

    Receipts of every CLI call stay under the lane (``claude-calls/``). The transport refuses an
    API key, strips OpenAI and Anthropic credentials from the child environment and requires a
    subscription login, so these calls use subscription quota, not an API project."""
    caller = _text.current().transports.caller
    return {role: caller('claude-cli', model=policy[role]['model'], effort=policy[role]['reasoningEffort'],
                         receipts_dir=lane['output'] / 'claude-calls')
            for role in ('translator', 'reviewer')}


def drive(config_path, locale, *, budget_authorization=None):
    """One restart-safe unified tick; explicit bound budget is mandatory.

    Returns waiting for a durable owner, never calls execute directly. A later
    tick independently validates the candidate and durable outcome. Unknown
    original jobs require explicit reconciliation, never a fresh paid attempt.
    """
    if budget_authorization is None:
        return {'status': 'blocked', 'reason': 'bound_budget_authorization_required', 'dispatched': False}
    controller = Controller(config_path, mode='deterministic_execute', budget_authorization=budget_authorization)
    config = controller.config
    require(locale in config.lanes, 'locale_not_registered')
    view = snapshot(config)
    node = view['nodes']['text.' + locale]
    if node['status'] == 'validated':
        return {'status': 'succeeded', 'artifact': 'verified', 'review': 'human_pending',
                'productionEligible': False, 'dispatched': False,
                'candidateJsonSha256': view['packageIdentities']['candidate.' + locale]}
    if node['status'] in {'blocked', 'reconciliation_required'}:
        return {'status': 'blocked', 'reason': node.get('reasonCode', 'reconciliation_required'), 'dispatched': False}
    result = controller.tick(requested_locale=locale)
    return {'status': 'waiting' if result.get('status') != 'blocked' else 'blocked',
            'reason': result['reasonCode'], 'dispatched': result.get('dispatched'), 'evidence': result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    tick = commands.add_parser('tick')
    tick.add_argument('--config', required=True, type=Path)
    tick.add_argument('--mode', choices=MODES, default='deterministic_shadow')
    worker = commands.add_parser('worker')
    worker.add_argument('--config', required=True, type=Path)
    worker.add_argument('--locale', required=True, choices=pipeline.LOCALES)
    worker.add_argument('--expected-configuration', required=True)
    worker.add_argument('--expected-code', required=True)
    worker.add_argument('--expected-job', required=True)
    worker.add_argument('--expected-payload-cache')
    worker.add_argument('--expected-partial-recovery')
    worker.add_argument('--budget-authorization', type=Path)
    worker.add_argument('--expected-budget')
    reopen = commands.add_parser('reopen-repair', help='supersede a failed text job whose repair chain new '
                                 'machine audio meaning notes reopen; no model call')
    reopen.add_argument('--config', required=True, type=Path)
    reopen.add_argument('--locale', required=True, choices=pipeline.LOCALES)
    reopen.add_argument('--expected-state-revision', required=True)
    args = parser.parse_args()
    if args.command == 'tick':
        result = Controller(args.config, mode=args.mode).tick()
    elif args.command == 'reopen-repair':
        result = reopen_repair(args.config, args.locale, args.expected_state_revision)
    else:
        result = execute(args.config, args.locale, args.expected_configuration, args.expected_code, args.expected_job,
                         budget_authorization=args.budget_authorization, expected_budget=args.expected_budget,
                         expected_payload_cache=args.expected_payload_cache,
                         expected_partial_recovery=args.expected_partial_recovery)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
