"""Transition facade: the unified orchestration lives in tongxing_production.orchestration.unified.

This package binds the orchestration to this checkout — the durable job store,
filesystem helpers, the repository root, the execution closure, the worker and
Temporal commands and the stage implementations under ``scripts/`` — and
aliases ``scripts.sermon_unified.{contracts,adapters,resources,runtime}`` to
the package modules, so every existing import path and patch target keeps
naming one object. Remove once no caller imports the old path.
"""
from __future__ import annotations

import importlib
import os
from pathlib import Path
import subprocess
import sys

from tongxing_production.orchestration.unified import adapters, backend, contracts, resources, runtime
from scripts import sermon_workflow_jobs as _jobs
from scripts.sermon_execution_harness import atomic_json as _atomic_json, utc_now as _utc_now
from scripts.sermon_release_workflow import safe_path as _safe_path
from scripts import tongxing_host  # noqa: F401  binds the source and text layers, whose stage entries these stages load

ROOT = Path(__file__).resolve().parents[2]

_STAGE_MODULES = {
    'accounting': 'scripts.sermon_unified_accounting',
    'app_delivery': 'scripts.sermon_app_delivery_workflow',
    'audio': 'scripts.sermon_unified_audio',
    'canonical_binding': 'scripts.sermon_unified_canonical_binding',
    'capabilities': 'scripts.sermon_unified_capabilities',
    'continuation': 'scripts.sermon_unified_continuation',
    'delivery': 'scripts.sermon_unified_delivery',
    'layer2_binding': 'tongxing_production.text.unified_binding',
    'layer2_budget': 'tongxing_production.text.budget',
    'layer2_controller': 'tongxing_production.text.controller',
    'parallel': 'scripts.sermon_unified_parallel',
    'reviews': 'scripts.sermon_unified_reviews',
    'runtime_identity': 'scripts.sermon_unified_runtime_identity',
    'source': 'tongxing_production.source.unified_stage',
    'study': 'scripts.sermon_unified_study',
}
assert set(_STAGE_MODULES) == backend.STAGE_NAMES


def required_modules():
    # Includes existing validators and late imports. Docs unrelated to model
    # consumption are deliberately excluded. Term rules are an input dependency.
    modules = {str(p.relative_to(ROOT)) for folder, glob in [('scripts', '*.py'), ('schemas', '*.json')]
               for p in (ROOT / folder).rglob(glob)}
    # Producers late-load the legacy renderer/publisher and copy its web assets.
    # Enumerate tracked source files, never node_modules or ignored output trees.
    # packages/ holds the installable production and fingerprint code that moved out of scripts/.
    tracked = subprocess.run(['git', 'ls-files', '--', 'experiments/sermon-dubbing-poc', 'packages', 'apps/listening-web',
                              'apps/tracker-web', 'services', 'tools', 'infra'],
                             cwd=ROOT, capture_output=True, text=True, timeout=10)
    if tracked.returncode:
        raise contracts.ContractError('legacy_execution_closure_unavailable')
    modules.update(name for name in tracked.stdout.splitlines()
                   if Path(name).suffix in {'.py', '.mjs', '.js', '.html', '.css', '.json'})
    return sorted(modules | {'docs/series-terminology.zh.md'})


def worker_command(state_root, key):
    return [os.sys.executable, str(ROOT / 'scripts/sermon.py'), 'worker', 'run',
            '--state-root', str(state_root), '--run-id', key]


def temporal_wake(state_root, key, plan_hash):
    sdk = ROOT / 'artifacts/temporal/runtime/venv/bin/python'
    if not sdk.is_file():
        return
    try:
        subprocess.run([str(sdk), '-m', 'scripts.sermon_temporal', 'client', 'unified-submit',
                        '--state-root', str(state_root), '--run-key', key, '--plan-hash', plan_hash],
                       cwd=ROOT, capture_output=True, timeout=20, check=True)
    except (OSError, subprocess.SubprocessError):
        pass  # Accepted evidence remains stored; job.resume can wake later.


backend.configure(backend.Backend(
    repo_root=ROOT, artifact_root=ROOT / 'artifacts', jobs=_jobs,
    safe_path=_safe_path, atomic_json=_atomic_json, utc_now=_utc_now,
    required_modules=required_modules, worker_command=worker_command, temporal_wake=temporal_wake,
    stage=lambda name: importlib.import_module(_STAGE_MODULES[name]),
))

for _name, _module in (('contracts', contracts), ('adapters', adapters), ('resources', resources), ('runtime', runtime)):
    sys.modules[f'{__name__}.{_name}'] = _module
