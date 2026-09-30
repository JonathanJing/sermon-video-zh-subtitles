"""Versioned four-layer planning contract, without production dispatch authority.

Observations are supplied by local package validators, never the progress ledger.
This planner only proposes work: existing producers/gates must revalidate evidence
under their durable admission locks before any future executable adapter uses it.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from scripts.sermon_workflow_jobs import _digest

VERSION = 'sermon-canonical-pipeline-v1'
LOCALES = ('zh-Hans', 'ko', 'es')


@dataclass(frozen=True)
class Node:
    id: str
    layer: int
    locale: str | None
    depends_on: tuple[str, ...]
    human_gates: tuple[str, ...]
    executor_type: str
    timeout_seconds: int
    side_effect_policy: str


def definition(locales=LOCALES, *, text_only=(), terminal_scope='page_ready'):
    locales, text_only = tuple(locales), tuple(text_only)
    if (not locales or len(set(locales)) != len(locales) or not set(locales) <= set(LOCALES)
            or len(set(text_only)) != len(text_only) or not set(text_only) <= set(locales)
            or terminal_scope not in {'page_ready', 'delivery_complete'}):
        raise ValueError('invalid_workflow_policy')
    nodes = [Node('source', 1, None, (), ('source_review',), 'deterministic_program', 600, 'immutable_artifact')]
    terminals = []
    for locale in sorted(locales):
        text, audio, page = (f'{stage}.{locale}' for stage in ('text', 'audio', 'page'))
        nodes += [Node(text, 2, locale, ('source',), (), 'production_model', 21600, 'reconcile_before_retry'),
                  Node(audio, 3, locale, (text,), ('translation_review', 'text_only_plan') if locale in text_only
                       else ('translation_review', 'voice_authorization'),
                       'deterministic_program' if locale in text_only else 'production_model',
                       600 if locale in text_only else 21600, 'reconcile_before_retry'),
                  Node(page, 4, locale, (text, audio), () if locale in text_only else ('audio_listening_review',),
                       'deterministic_program', 600, 'immutable_artifact')]
        terminal = page
        if terminal_scope == 'delivery_complete':
            publish, verify, record = (f'{stage}.{locale}' for stage in ('publish', 'verify', 'record'))
            nodes += [Node(publish, 4, locale, (page,), ('exact_release_authorization',), 'external_service', 600, 'reconcile_before_retry'),
                      Node(verify, 4, locale, (publish,), (), 'external_service', 300, 'idempotent_read'),
                      Node(record, 4, locale, (verify,), (), 'deterministic_program', 120, 'compare_and_swap')]
            terminal = record
        terminals.append(terminal)
    return {'workflowDefinitionVersion': VERSION, 'workflowScope': 'four_layer_release',
            'targetLocales': sorted(locales), 'textOnlyLocales': sorted(text_only),
            'terminalScope': terminal_scope, 'terminalDependencies': terminals,
            'nodes': [{**asdict(node), 'depends_on': list(node.depends_on),
                       'human_gates': list(node.human_gates)} for node in nodes],
            'dispatchEnabled': False, 'admission': 'requires_validated_package_adapter_and_existing_durable_locks'}


def plan(spec, *, input_identity, observations, approvals):
    """Project validated local observations; no receipt is created or promoted.

    Each observation binds the exact node identity and its dependency outputs.
    Missing or stale evidence invalidates only descendants. Gate receipts are
    opaque hashes bound to that same identity, not prose claiming approval.
    This utility is not a package validator or executable controller adapter.
    """
    expected = definition(spec['targetLocales'], text_only=spec['textOnlyLocales'],
                          terminal_scope=spec['terminalScope'])
    if spec != expected or not _sha(input_identity) or not isinstance(observations, dict) or not isinstance(approvals, dict):
        raise ValueError('invalid_planning_inputs')
    known = {n['id'] for n in spec['nodes']}
    if set(observations) - known or set(approvals) - known:
        raise ValueError('unknown_work_unit')
    states, outputs = {}, {}
    for node in spec['nodes']:
        ident = node['id']
        if any(dep not in outputs for dep in node['depends_on']):
            states[ident] = {'status': 'waiting_dependency'}
            continue
        binding = _digest({'definition': _digest(spec), 'node': ident,
                           'input': input_identity if not node['depends_on'] else None,
                           'dependencies': {dep: outputs[dep] for dep in node['depends_on']}})
        gate = approvals.get(ident, {})
        missing = [g for g in node['human_gates'] if not isinstance(gate, dict)
                   or not isinstance(gate.get(g), dict) or gate[g].get('identity') != binding
                   or not _sha(gate[g].get('receiptSha256'))]
        observed = observations.get(ident, {})
        state = {'identity': binding, 'status': 'human_gate' if missing else 'ready', 'missingGates': missing}
        if not missing and isinstance(observed, dict) and observed.get('identity') == binding:
            if observed.get('status') == 'validated' and _sha(observed.get('outputSha256')):
                outputs[ident] = observed['outputSha256']
                state['status'] = 'validated'
            elif observed.get('status') in {'running', 'uncertain', 'failed'}:
                state['status'] = {'running': 'waiting_job', 'uncertain': 'reconciliation_required', 'failed': 'blocked'}[observed['status']]
        states[ident] = state
    return {'schemaVersion': 'sermon-canonical-shadow-plan-v1', 'workflowDefinitionVersion': VERSION,
            'stateRevision': _digest({'spec': spec, 'input': input_identity, 'observations': observations, 'approvals': approvals}),
            'status': 'terminal_evidence_observed' if all(k in outputs for k in spec['terminalDependencies']) else 'in_progress',
            'nodes': states, 'dispatchEnabled': False, 'runtimeCodexTurns': 0,
            'productionAcceptance': 'not_evaluated', 'deviceAcceptance': 'not_run'}


def _sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)
