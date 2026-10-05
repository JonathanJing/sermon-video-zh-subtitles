"""Bounded Codex CLI decisions over the existing guarded production tools.

The model sees only allowlisted state and emits one named operation. It never
executes shell tools or writes approvals. Unknown CLI outcomes are not retried.
"""
from __future__ import annotations
import fcntl
import json
import math
import os
from pathlib import Path
import time
import uuid
from scripts import sermon_agents_supervisor as guarded
from scripts import sermon_end_to_end as workflow
from scripts.sermon_agents_api import AgentsAPIError, _write_json


def session_report(args, config, instructions, decision_type, verify_decision, *, call_json=None):
    if call_json is None:
        from scripts.sermon_codex_transport import call_json
    timeout = getattr(args, 'agent_timeout_seconds', 21600)
    if not math.isfinite(timeout) or timeout <= 0 or not 1 <= args.max_turns <= 100:
        raise AgentsAPIError('invalid_supervisor_limits')
    identity = {'backend': 'codex-cli', 'model': args.model,
                'reasoning': getattr(args, 'reasoning_effort', 'medium'),
                'serviceTier': getattr(args, 'service_tier', 'fast'),
                'instructions': instructions, 'mode': args.mode,
                'config': guarded.bound_configuration(config)}
    binding = guarded.fingerprint(identity)
    root = Path(args.out).parent / 'agents-api-runs'
    if root.is_symlink():
        raise AgentsAPIError('invalid_run_root')
    root.mkdir(parents=True, exist_ok=True)
    lock = os.open(root / 'supervisor.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    directory = None
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise AgentsAPIError('supervisor_already_running') from None
        # The transport change must never abandon a live API/SDK tool outcome.
        for pointer in root.glob('active-*.json'):
            _, unresolved = guarded.pointer_run(root, pointer)
            if unresolved:
                raise AgentsAPIError('prior_configuration_session_unresolved_inspect_existing_run')
        explicit = getattr(args, 'agent_run_dir', None)
        resume = bool(getattr(args, 'resume_agent_session', False))
        if resume and not explicit:
            raise AgentsAPIError('resume_requires_agent_run_dir')
        if explicit and Path(explicit).is_symlink():
            raise AgentsAPIError('invalid_run_directory')
        directory = Path(explicit).expanduser().resolve() if explicit else root / ('codex-run-' + uuid.uuid4().hex)
        if resume:
            state = guarded.read_object(directory / 'codex-state.json')
            if state.get('binding') != binding:
                raise AgentsAPIError('production_configuration_changed')
        else:
            # A pending CLI call, or interrupted tool, needs explicit reconciliation.
            for pointer in root.glob('codex-active-*.json'):
                old = Path(guarded.read_object(pointer)['runDirectory']) / 'codex-state.json'
                if guarded.read_object(old).get('status') != 'completed':
                    raise AgentsAPIError('prior_codex_session_unresolved_inspect_existing_run')
            if directory.exists() and any(directory.iterdir()):
                raise AgentsAPIError('new_run_directory_must_be_empty')
            directory.mkdir(parents=True, mode=0o700, exist_ok=True)
            state = {'schemaVersion': 1, 'binding': binding, 'status': 'running', 'turns': 0, 'pending': False}
            _write_json(directory / 'codex-state.json', state)
            _write_json(root / ('codex-active-' + binding[:16] + '.json'), {'runDirectory': str(directory.resolve())})
        tools = guarded.ProductionTools(config, args.mode == 'execute', directory, decision_type)
        started = time.monotonic()
        if state['pending']:
            raise AgentsAPIError('codex_outcome_unknown_inspect_existing_receipt')
        definitions = guarded.tool_definitions(args.mode == 'execute', decision_type.model_json_schema(),
                                             bool(config.release_workflow_config))
        allowed = {definition['name'] for definition in definitions}
        schema = {'type': 'object', 'additionalProperties': False,
                  'properties': {'tool': {'type': 'string', 'enum': sorted(allowed)},
                                 'arguments': {'anyOf': [definition['parameters'] for definition in definitions]}},
                  'required': ['tool', 'arguments']}
        while tools.state['decision'] is None:
            if state['turns'] >= args.max_turns or time.monotonic() - started >= timeout:
                raise AgentsAPIError('codex_supervisor_budget_exhausted')
            snapshot = tools('inspect_production_state', {})
            prompt = instructions + '\nThe host already performed inspection. Return JSON with tool and arguments only; no shell tools.\n' + json.dumps({
                'state': snapshot, 'tools': definitions, 'attemptedStages': tools.state['attemptedStages'],
                'mode': args.mode}, ensure_ascii=False)
            state.update(pending=True, turns=state['turns'] + 1)
            _write_json(directory / 'codex-state.json', state)
            turn_dir = directory / ('turn-%03d' % state['turns'])
            result = call_json(prompt, model=args.model, reasoning=identity['reasoning'],
                               service_tier=identity['serviceTier'], output_schema=schema,
                               output_dir=turn_dir, timeout_seconds=max(0.001, timeout - (time.monotonic() - started)))
            if not isinstance(result, dict) or set(result) != {'tool', 'arguments'} or result['tool'] not in allowed:
                raise AgentsAPIError('invalid_codex_supervisor_operation')
            _write_json(directory / 'last-operation.json', result)
            # Persist attempted domain stages before mutations. If interrupted,
            # ProductionTools refuses a repeat even across model decisions.
            outcome = tools(result['tool'], result['arguments'])
            _write_json(directory / 'last-tool-result.json', outcome)
            state['pending'] = False
            _write_json(directory / 'codex-state.json', state)
        decision = tools.state['decision']
        snapshot = workflow.snapshot(config)
        verified = verify_decision(decision, snapshot, args.mode, attempted_stages=tools.state['attemptedStages'])
        state['status'] = 'completed'
        _write_json(directory / 'codex-state.json', state)
        return {'schemaVersion': 1, 'status': verified['status'], 'sunday': args.sunday,
                'mode': args.mode, 'model': args.model, 'agentBackend': 'codex-cli',
                'reasoningEffort': identity['reasoning'], 'serviceTier': identity['serviceTier'],
                'decision': verified, 'modelDecision': decision, 'finalSnapshot': snapshot,
                'agentSession': {'runDirectory': str(directory), 'status': state['status'],
                                 'costStatus': 'unknown', 'providerModel': None},
                'traceSensitiveDataIncluded': False}
    except Exception as exc:
        snapshot = workflow.snapshot(config)
        return {'schemaVersion': 1, 'status': 'failed', 'sunday': args.sunday, 'mode': args.mode,
                'model': args.model, 'agentBackend': 'codex-cli', 'finalSnapshot': snapshot,
                'decision': {'status': 'blocked', 'action': 'inspect_codex_cli_session',
                             'summary_zh': 'Codex CLI 监管未通过完成检查；保留调用与工具状态，不能自动重试。',
                             'human_action_required': False, 'modelDecisionAccepted': False,
                             'evidence': [getattr(exc, 'code', type(exc).__name__)]},
                'agentSession': {'runDirectory': str(directory) if directory else None, 'costStatus': 'unknown'},
                'traceSensitiveDataIncluded': False}
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        os.close(lock)
