"""Explicit stage identity extensions; never a code-change or deadline override."""
from copy import deepcopy
from pathlib import Path
import re

from scripts import sermon_review_contracts as c
from scripts import sermon_public_snapshot as public
from scripts import sermon_workflow_jobs as jobs
from scripts.sermon_release_workflow import _safe_path

SCHEMA = 'sermon-execution-identity-extension-v1'
IDENTITY_KEYS = {'gitCommit', 'trackedWorkingTreeDirty', 'loadedProjectCodeSha256',
                 'pythonVersion', 'platform', 'architecture', 'scope'}
BINDING_KEYS = {'runId', 'runConfigSha256', 'storeSha256', 'sourceIdentitySha256', 'inputSha256'}
DECLARATION_SCHEMA = 'sermon-stage-code-declaration-v1'


def validate_declaration(plan, declaration):
    c.require(type(declaration) is dict and set(declaration) == {
        'schemaVersion', 'originalPlanSha256', 'stageId', 'moduleAdditions', 'externalRuntimeSha256'}
        and declaration['schemaVersion'] == DECLARATION_SCHEMA
        and declaration['originalPlanSha256'] == c.canonical_sha256(plan),
        'diagnostic_stage_declaration_changed')
    c.require(type(declaration['stageId']) is str and
        re.fullmatch('[A-Za-z0-9_.:-]{1,100}', declaration['stageId']), 'invalid_extension_stage')
    additions = _modules(declaration['moduleAdditions'])
    _runtimes(declaration['externalRuntimeSha256'])
    c.require(not set(additions) & set(plan['executionIdentity']['loadedProjectCodeSha256']),
              'extension_cannot_redeclare_old_module')
    return deepcopy(declaration)


def declaration_path(plan, declaration):
    validate_declaration(plan, declaration)
    return _safe_path(Path(plan['runDirectory'])) / 'stage-declarations' / (declaration['stageId'] + '.json')


def freeze_stage_declaration(plan, current_identity, declaration):
    """Declare allowed additions before loading them; no credential or dispatch."""
    c.require(_identity(current_identity) == _identity(plan['executionIdentity']),
              'declaration_requires_original_execution_identity')
    root = _safe_path(Path(plan['runDirectory']))
    saved, _ = c.read_snapshot(root / 'run-plan.json')
    c.require(saved == plan, 'diagnostic_original_plan_changed')
    path = declaration_path(plan, declaration)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    public.save_once(path, declaration)
    jobs._sync_directory_ancestry(path.parent)
    return path


def _hash(value):
    c.require(type(value) is str and re.fullmatch('[a-f0-9]{64}', value), 'invalid_extension_hash')
    return value


def _modules(value):
    c.require(type(value) is dict and len(value) <= 1024, 'invalid_extension_modules')
    for path, digest in value.items():
        c.require(type(path) is str and len(path) <= 256 and
                  re.fullmatch(r'(scripts|backend|experiments)/[A-Za-z0-9_./-]+\.py', path)
                  and '..' not in Path(path).parts and '//' not in path, 'invalid_extension_module_path')
        _hash(digest)
    return deepcopy(value)


def _identity(value):
    c.require(type(value) is dict and set(value) == IDENTITY_KEYS and
              value['trackedWorkingTreeDirty'] is False and type(value['gitCommit']) is str
              and re.fullmatch('[a-f0-9]{40,64}', value['gitCommit']), 'invalid_extension_identity')
    _modules(value['loadedProjectCodeSha256'])
    for field in ('pythonVersion', 'platform', 'architecture', 'scope'):
        c.require(type(value[field]) is str and 0 < len(value[field]) <= 256, 'invalid_extension_identity')
    return deepcopy(value)


def _runtimes(value):
    c.require(type(value) is dict and len(value) <= 32, 'invalid_extension_runtime_manifest')
    for label, digest in value.items():
        c.require(type(label) is str and re.fullmatch('[A-Za-z0-9_.:-]{1,100}', label),
                  'invalid_extension_runtime_label')
        _hash(digest)
    return deepcopy(value)


def make_extension(base_identity, current_identity, *, stage_id, declared_additions,
                   external_runtime_sha256, binding, parent_receipt=None):
    """Validate a predeclared extension; the trusted caller supplies declarations.

    A digest does not establish authorization. The run's frozen stage plan must
    provide the allowed module and runtime digests; do not derive them from an
    unexpected current process and silently approve it.
    """
    base, current = _identity(base_identity), _identity(current_identity)
    c.require(type(stage_id) is str and re.fullmatch('[A-Za-z0-9_.:-]{1,100}', stage_id),
              'invalid_extension_stage')
    c.require(type(binding) is dict and set(binding) == BINDING_KEYS, 'invalid_extension_binding')
    for digest in binding.values(): _hash(digest)
    additions, runtimes = _modules(declared_additions), _runtimes(external_runtime_sha256)
    c.require(all(current[k] == base[k] for k in IDENTITY_KEYS - {'loadedProjectCodeSha256'}),
              'extension_runtime_or_commit_changed')
    old, new = base['loadedProjectCodeSha256'], current['loadedProjectCodeSha256']
    c.require(not set(old) & set(additions), 'extension_cannot_redeclare_old_module')
    c.require(new == {**old, **additions}, 'extension_undeclared_or_changed_module')
    parent_sha = None
    if parent_receipt is not None:
        c.require(type(parent_receipt) is dict and parent_receipt.get('schemaVersion') == SCHEMA
                  and parent_receipt.get('executionIdentity') == base
                  and parent_receipt.get('binding') == binding, 'extension_parent_binding_changed')
        prior = _runtimes(parent_receipt['externalRuntimeSha256'])
        c.require(all(runtimes.get(k) == v for k, v in prior.items()), 'extension_old_runtime_changed')
        parent_sha = c.canonical_sha256(parent_receipt)
    return {'schemaVersion': SCHEMA, 'stageId': stage_id,
            'parentIdentitySha256': c.canonical_sha256(base), 'parentReceiptSha256': parent_sha,
            'executionIdentity': current, 'declaredAdditions': additions,
            'externalRuntimeSha256': runtimes, 'binding': deepcopy(binding)}


def validate_extension(receipt, base_identity, current_identity, *, stage_id,
                       declared_additions, external_runtime_sha256, binding, parent_receipt=None):
    expected = make_extension(base_identity, current_identity, stage_id=stage_id,
        declared_additions=declared_additions, external_runtime_sha256=external_runtime_sha256,
        binding=binding, parent_receipt=parent_receipt)
    c.require(receipt == expected, 'extension_receipt_changed')
    return deepcopy(expected)


def persist_extension(root, receipt):
    """Append one immutable receipt; original plan/config/ledgers are untouched."""
    root = _safe_path(Path(root))
    c.require(receipt.get('schemaVersion') == SCHEMA, 'invalid_extension_receipt')
    path = root / 'execution-extensions' / (c.canonical_sha256(receipt) + '.json')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    public.save_once(path, receipt)
    jobs._sync_directory_ancestry(path.parent)
    return path
