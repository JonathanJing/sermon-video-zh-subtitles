"""Opt-in deterministic adapter for the existing legacy page-release workflow.

This is not the canonical multilingual four-layer controller. It delegates all
admission, content gates, durable jobs and publication checks to existing code.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import sermon_end_to_end as workflow
from scripts import sermon_workflow_jobs as jobs

DEFINITION_VERSION = 'sermon-legacy-page-controller-v1'
STATE_SCHEMA = 'sermon-deterministic-controller-state-v1'
MODES = ('legacy_agent', 'deterministic_shadow', 'deterministic_execute')


@dataclass(frozen=True)
class Action:
    name: str
    depends_on: tuple[str, ...]
    human_gates: tuple[str, ...]
    timeout_seconds: int


REGISTRY = (
    Action('generate_audio_candidate', (), ('source_window_and_voice',), 21600),
    Action('sync_audio', ('generate_audio_candidate',), ('timing_review',), 1800),
    Action('build_page', ('sync_audio',), ('audio_listening_and_sync_review',), 600),
    Action('prepare_release', ('build_page',), (), 300),
    Action('deploy_release', ('prepare_release',), ('exact_release_authorization',), 600),
    Action('verify_release', ('deploy_release',), (), 300),
    Action('record_published', ('verify_release',), (), 120),
)
ACTIONS = {a.name: a for a in REGISTRY}


def definition():
    return {'workflowDefinitionVersion': DEFINITION_VERSION, 'stateSchemaVersion': STATE_SCHEMA,
            'scope': 'legacy_page_release', 'terminalScopes': ['page_ready', 'delivery_complete'],
            'actions': [{'name': a.name, 'dependsOn': list(a.depends_on), 'humanGates': list(a.human_gates),
                         'timeoutSeconds': a.timeout_seconds, 'maxAttemptsPerIdentity': 1,
                         'admission': 'sermon_end_to_end.snapshot_and_locked_start_action'} for a in REGISTRY]}


def revision(snapshot):
    # Inspection wall-clock is not a production revision. Everything else,
    # including evidence identity and approval/lease changes, remains bound.
    return workflow.state_revision(snapshot)


def recommend(snapshot, terminal_scope='page_ready'):
    if terminal_scope not in {'page_ready', 'delivery_complete'}:
        raise ValueError('invalid_terminal_scope')
    rec = snapshot.get('recommendedAction') or {}
    name = rec.get('action')
    # The dual-PDF supervisor's complete state must never become page-ready.
    if snapshot.get('workflowScope') != 'page_release':
        return {'status': 'blocked', 'reasonCode': 'unsupported_workflow_scope', 'action': None}
    if name == 'complete':
        if snapshot.get('workflowComplete') is True and rec.get('humanActionRequired') is False:
            return {'status': 'stopped', 'reasonCode': 'delivery_complete', 'action': None}
        return {'status': 'blocked', 'reasonCode': 'completion_not_verified', 'action': None}
    # These downstream recommendations require a validated candidate/build
    # receipt in the existing snapshot. Stop before any publication activity.
    page_proven = {'prepare_release', 'waiting_release_authorization', 'deploy_release',
                   'verify_release', 'record_published'}
    if terminal_scope == 'page_ready' and name in page_proven:
        return {'status': 'stopped', 'reasonCode': 'page_ready', 'action': None}
    if rec.get('humanActionRequired') is not False:
        return {'status': 'blocked', 'reasonCode': 'human_or_unknown_gate', 'action': None}
    if name in workflow.WAIT_ACTIONS:
        return {'status': 'waiting', 'reasonCode': name, 'action': None}
    if name not in ACTIONS:
        return {'status': 'blocked', 'reasonCode': 'unknown_action', 'action': None}
    return {'status': 'ready', 'reasonCode': 'existing_evidence_admits_action', 'action': name}


class Controller:
    def __init__(self, config, *, mode='deterministic_shadow', terminal_scope='page_ready'):
        if mode not in MODES or terminal_scope not in {'page_ready', 'delivery_complete'}:
            raise ValueError('invalid_operator_policy')
        self.config, self.mode, self.terminal_scope = config, mode, terminal_scope
        path = workflow.configuration(config)
        if path is None:
            raise ValueError('explicit_release_configuration_required')
        self.config_path = path
        self.config_sha = workflow.config_hash(path)
        self.root = workflow.job_root(config, path)
        self.binding = {'workflowDefinitionVersion': DEFINITION_VERSION, 'stateSchemaVersion': STATE_SCHEMA,
                        'definitionSha256': jobs._digest(definition()), 'configurationSha256': self.config_sha,
                        'sunday': config.sunday, 'terminalScope': terminal_scope}

    def _result(self, decision, **fields):
        return {**self.binding, 'mode': self.mode, **decision, **fields,
                'runtimeCodexTurns': 0, 'contentAcceptance': 'not_evaluated',
                'deviceAcceptance': 'not_run', 'scope': 'legacy_page_release'}

    def tick(self):
        if self.mode == 'legacy_agent':
            return self._result({'status': 'legacy_handoff', 'reasonCode': 'existing_entry_unchanged', 'action': None})
        if workflow.config_hash(self.config_path) != self.config_sha:
            return self._result({'status': 'blocked', 'reasonCode': 'configuration_changed', 'action': None})
        observed = workflow.snapshot(self.config)
        decision = recommend(observed, self.terminal_scope)
        state_revision = revision(observed)
        if self.mode == 'deterministic_shadow':
            return self._result(decision, stateRevision=state_revision, dispatched=False)
        # Reuse the same durable filesystem lock/persistence primitives. This is
        # an admission/version receipt, not another worker or job queue.
        with jobs._lock(self.root, jobs._digest({'purpose': 'deterministic-controller'})) as (_, _, held):
            if not held:
                return self._result({'status': 'waiting', 'reasonCode': 'controller_busy', 'action': None})
            state_path = self.root / 'controller-state.json'
            if state_path.exists():
                saved = jobs._read(state_path)
                if saved.get('binding') != self.binding:
                    return self._result({'status': 'blocked', 'reasonCode': 'definition_or_scope_migration_required', 'action': None})
            else:
                saved = {'binding': self.binding, 'pendingIntent': None}
                jobs._persist(state_path, saved)
            fresh = workflow.snapshot(self.config)
            if workflow.config_hash(self.config_path) != self.config_sha or revision(fresh) != state_revision:
                return self._result({'status': 'blocked', 'reasonCode': 'stale_state_revision', 'action': None})
            decision = recommend(fresh, self.terminal_scope)
            if saved.get('terminalRevision'):
                if saved['terminalRevision'] != state_revision:
                    return self._result({'status': 'blocked', 'reasonCode': 'terminal_evidence_changed', 'action': None})
                return self._result(decision, stateRevision=state_revision, dispatched=False)
            if decision['status'] == 'stopped':
                saved['terminalRevision'] = state_revision
                jobs._persist(state_path, saved)
            if decision['status'] != 'ready':
                return self._result(decision, stateRevision=state_revision, dispatched=False)
            name = decision['action']
            intent = saved.get('pendingIntent')
            # A killed controller may have dispatched already. Let the existing
            # durable job reconciliation establish progress, never blindly retry.
            if intent and intent['action'] == name:
                return self._result({'status': 'blocked', 'reasonCode': 'intent_requires_reconciliation', 'action': None})
            intent = {'action': name, 'stateRevision': state_revision,
                      'idempotencyKey': jobs._digest({'binding': self.binding, 'action': name})}
            saved['pendingIntent'] = intent
            jobs._persist(state_path, saved)
            try:
                outcome = workflow.start_action(
                    self.config, name, timeout_seconds=ACTIONS[name].timeout_seconds,
                    expected_config_sha=self.config_sha, expected_state_revision=state_revision)
            except Exception:
                # No exception bodies or command output escape into packets.
                return self._result({'status': 'blocked', 'reasonCode': 'dispatch_outcome_unknown', 'action': name}, dispatched=None)
            if isinstance(outcome, dict) and outcome.get('status') == 'blocked':
                saved['pendingIntent'] = None
                jobs._persist(state_path, saved)
                return self._result({'status': 'blocked', 'reasonCode': 'dispatch_not_admitted', 'action': name}, dispatched=False)
            if not isinstance(outcome, dict) or outcome.get('status') not in jobs.STATUSES:
                return self._result({'status': 'blocked', 'reasonCode': 'dispatch_outcome_unknown', 'action': name}, dispatched=None)
            saved['lastJob'] = {k: outcome.get(k) for k in ('jobId', 'status')}
            jobs._persist(state_path, saved)
            if outcome['status'] in {'failed', 'uncertain'}:
                return self._result({'status': 'blocked', 'reasonCode': 'durable_job_requires_reconciliation', 'action': name}, dispatched=None)
            # Job success alone never establishes a completed stage. The next
            # snapshot must verify its receipt/artifacts and advance admission.
            return self._result({'status': 'waiting', 'reasonCode': 'verify_durable_job_evidence', 'action': name},
                                stateRevision=state_revision, dispatched=True)

    def run(self, max_ticks=8):
        if type(max_ticks) is not int or not 1 <= max_ticks <= 32:
            raise ValueError('invalid_tick_budget')
        # No busy poll: one dispatch/wait is a durable handoff. Future ticks are
        # invoked by the operator, never an unbounded model conversation.
        history = []
        for _ in range(max_ticks):
            result = self.tick()
            history.append(result)
            if result['status'] != 'ready' or self.mode != 'deterministic_execute':
                break
        return {'schemaVersion': STATE_SCHEMA, 'history': history, 'runtimeCodexTurns': 0}


def main():
    from scripts.sermon_production_supervisor import SupervisorConfig
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sunday', required=True)
    parser.add_argument('--state-file', required=True)
    parser.add_argument('--work-root', required=True, type=Path)
    parser.add_argument('--release-config', required=True, type=Path)
    parser.add_argument('--mode', choices=MODES, default='deterministic_shadow')
    parser.add_argument('--terminal-scope', choices=('page_ready', 'delivery_complete'), default='page_ready')
    args = parser.parse_args()
    config = SupervisorConfig(args.sunday, args.state_file, work_root=args.work_root,
                              gcs_bucket=None, release_workflow_config=args.release_config)
    result = Controller(config, mode=args.mode, terminal_scope=args.terminal_scope).run()
    print(json.dumps(result, sort_keys=True))
    return 1 if result['history'][-1]['status'] == 'blocked' else 0


if __name__ == '__main__':
    raise SystemExit(main())
