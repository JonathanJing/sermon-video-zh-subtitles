"""Which stage implementations make up the prepared workflow.

The orchestration engine knows only stage names (``orchestration.unified.backend.STAGE_NAMES``)
and asks its host for each implementation; the host answers with ``load``. Stages that
have moved into the package are named by their package module; the rest still live in
the host checkout's ``scripts/`` and are imported by name until their batch moves them.
"""
from __future__ import annotations

import importlib
from types import ModuleType

STAGE_MODULES = {
    'accounting': 'tongxing_production.orchestration.unified.accounting',
    'app_delivery': 'tongxing_production.delivery.app_workflow',
    'audio': 'tongxing_production.audio.unified_stage',
    'canonical_binding': 'tongxing_production.workflows.prepared.canonical_binding',
    'capabilities': 'tongxing_production.workflows.prepared.capabilities',
    'continuation': 'tongxing_production.workflows.prepared.continuation',
    'delivery': 'tongxing_production.delivery.unified_stage',
    'layer2_binding': 'tongxing_production.text.unified_binding',
    'layer2_budget': 'tongxing_production.text.budget',
    'layer2_controller': 'tongxing_production.text.controller',
    'parallel': 'tongxing_production.orchestration.unified.parallel',
    'reviews': 'tongxing_production.review.unified_reviews',
    'runtime_identity': 'tongxing_production.compute.runtime_identity',
    'source': 'tongxing_production.source.unified_stage',
    'study': 'tongxing_production.workflows.prepared.study',
}


def load(name: str) -> ModuleType:
    """The implementation module of one stage of the prepared workflow."""
    return importlib.import_module(STAGE_MODULES[name])
