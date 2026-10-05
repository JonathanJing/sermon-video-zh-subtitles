"""Pure provider-neutral call projection; unknown tokens and timing remain unknown.

Request throughput includes transport and prefill. Generation throughput requires
an explicit generation duration. SDK session throughput includes tool execution.
"""
from collections import defaultdict
import json
import math
import re

TOKEN_FIELDS = ('inputTokens', 'outputTokens', 'totalTokens', 'cachedInputTokens',
                'cacheWriteTokens', 'reasoningTokens')


def _number(value):
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def _label(value):
    return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,199}', value) else None


def _usage(value):
    value = value if isinstance(value, dict) else {}
    aliases = {'inputTokens': 'input_tokens', 'outputTokens': 'output_tokens',
               'totalTokens': 'total_tokens'}
    return {key: _number(value.get(key, value.get(aliases.get(key)))) for key in TOKEN_FIELDS}


def _rate(tokens, seconds):
    return tokens / seconds if tokens is not None and seconds is not None and seconds > 0 else None


def _fingerprint(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), default=str)


def _fact(event):
    # Reimporting the same receipt may change envelope attribution/timestamps.
    ignored = {'eventId', 'recordedAt', 'runId', 'workflowId', 'stage', 'spanId',
               'producerId', 'sequence', 'traceId', 'pid', 'threadId'}
    return {k: v for k, v in event.items() if k not in ignored}


def _row(start, finish, *, call_id, backend, role, provider='not_recorded',
         scope='request_including_transport', conflict=False):
    from scripts.sermon_openai_runtime import safe_route
    evidence = finish or start or {}
    fields = evidence.get('fields', {})
    data = fields if evidence.get('code') == 'model_call_observation' else evidence
    usage = _usage(data.get('usage'))
    elapsed = _number(data.get('elapsedSeconds')) if finish else None
    generation = _number(data.get('generationSeconds')) if finish else None
    if conflict:
        usage = _usage(None); elapsed = None; generation = None
    declared = tuple(k for k in TOKEN_FIELDS if k != 'cacheWriteTokens') if fields else ('inputTokens', 'outputTokens', 'totalTokens') if backend == 'agent_session' else TOKEN_FIELDS
    known = sum(usage[k] is not None for k in declared)
    return {'runId': _label(evidence.get('runId')), 'callId': _label(call_id),
            'openaiRoute': None if conflict else safe_route(evidence.get('openaiRoute') or (start or {}).get('openaiRoute')),
            'backend': _label(backend), 'role': _label(role), 'provider': _label(provider),
            'requestedModel': _label(data.get('requestedModel') or ((start or {}).get('fields', {}).get('model') if fields else None) or (start or {}).get('requestedModel') or (start or {}).get('model')),
            'model': _label(data.get('model')) if finish else None, 'stage': _label(evidence.get('stage')), 'spanId': _label(evidence.get('spanId')),
            'startedAt': data.get('startedAt') if fields else (start or {}).get('recordedAt'),
            'finishedAt': data.get('finishedAt') if fields else (finish or {}).get('recordedAt'),
            'status': 'conflict' if conflict else _label(data.get('status', 'completed')) if finish else 'interrupted_or_running',
            'usageStatus': 'conflict' if conflict else 'not_reported' if known == 0 else 'reported' if known == len(declared) else 'partial',
            'usage': usage, 'elapsedSeconds': elapsed, 'generationSeconds': generation,
            'timingScope': scope, 'usageSource': _label(data.get('usageSource')) or ('not_reported' if backend == 'local' else 'provider_receipt' if backend == 'api' else 'host_telemetry'),
            'firstTokenSeconds': _number(data.get('firstTokenSeconds')) if finish and not conflict else None,
            'effectiveRequestTokensPerSecond': _rate(usage['outputTokens'], elapsed) if scope in {'request', 'request_including_transport'} else None,
            'generationTokensPerSecond': _rate(usage['outputTokens'], generation),
            'sessionOutputTokensPerSecond': _rate(usage['outputTokens'], elapsed) if scope == 'agent_session_including_tools' else None}


def report(events):
    """Project validated accounting rows without mutating them or executing work."""
    events = list(events)
    stages = defaultdict(set)
    for e in events:
        if e.get('event') in {'stage_started', 'stage_finished'}:
            stages[(e.get('runId'), e.get('spanId'))].add(e.get('executorType'))
    groups = defaultdict(list)
    api_receipts = {}
    local = defaultdict(list)
    for e in events:
        kind = e.get('event')
        if kind in {'api_attempt_started', 'api_attempt'}:
            groups[('api', e.get('runId'), e.get('attemptId', e.get('eventId')))].append(e)
            if kind == 'api_attempt':
                api_receipts.setdefault((e.get('runId'), e.get('attemptId')), e)
        elif kind in {'sdk_call_started', 'sdk_call_finished'}:
            groups[('sdk', e.get('runId'), e.get('invocationId'))].append(e)
        elif kind == 'log' and e.get('code') == 'model_call_observation':
            f = e.get('fields', {})
            groups[('generic', e.get('runId'), f.get('callId'))].append(e)
        elif kind == 'log' and e.get('code') == 'local_model_observation':
            f = e.get('fields', {})
            local[(e.get('runId'), e.get('spanId'), f.get('model'))].append(e)
    calls, duplicates = [], 0
    generic_ids = {(key[1], key[2]) for key, rows in groups.items() if key[0] == 'generic' and any(e.get('fields', {}).get('backend') == 'api' for e in rows)}
    for (kind, run, call_id), rows in sorted(groups.items(), key=lambda p: str(p[0])):
        if kind == 'api' and (run, call_id) in generic_ids:
            # Generic receipts carry the richer versioned correlation facts.
            continue
        unique = {}
        for e in rows:
            phase = e.get('fields', {}).get('phase') if kind == 'generic' else ('started' if e['event'].endswith('_started') else 'finished')
            key = (phase, _fingerprint(_fact(e)))
            if key in unique: duplicates += 1
            unique.setdefault(key, e)
        starts = [e for (phase, _), e in unique.items() if phase == 'started']
        ends = [e for (phase, _), e in unique.items() if phase != 'started']
        start, end = (starts[0] if starts else None), (ends[0] if ends else None)
        evidence = end or start
        f = evidence.get('fields', {}) if kind == 'generic' else evidence
        executor = stages.get((run, evidence.get('spanId')), set())
        conflict = len(starts) > 1 or len(ends) > 1 or len(executor) > 1
        if start and end and start.get('openaiRoute') != end.get('openaiRoute'):
            conflict = True
        if kind == 'generic':
            if start and end:
                first = start.get('fields', {})
                if any(first.get(k) != f.get(k) for k in ('model', 'backend', 'provider', 'role', 'timingScope', 'startedAt')):
                    conflict = True
            # A mirrored legacy attempt is correlation evidence, not another call.
            for legacy in groups.get(('api', run, call_id), []) if f.get('backend') == 'api' else []:
                if legacy['event'] != 'api_attempt':
                    continue
                if legacy.get('model') is not None and f.get('model') is not None and legacy['model'] != f['model']:
                    conflict = True
                old = _usage(legacy.get('usage')); new = _usage(f.get('usage'))
                if any(old[k] is not None and new[k] is not None and old[k] != new[k] for k in TOKEN_FIELDS):
                    conflict = True
                if legacy.get('elapsedSeconds') is not None and f.get('elapsedSeconds') is not None and legacy['elapsedSeconds'] != f['elapsedSeconds']:
                    conflict = True
        backend = f.get('backend', 'api' if kind == 'api' else 'agent_session')
        role = f.get('role', 'supervisor' if kind == 'sdk' or 'decision_agent' in executor else 'production')
        scope = f.get('timingScope', 'agent_session_including_tools' if kind == 'sdk' else 'request_including_transport')
        call = _row(start, end, call_id=call_id, backend=backend, role=role,
                    provider=f.get('provider') or 'not_recorded', scope=scope, conflict=conflict)
        if kind == 'sdk':
            call['agentBackend'] = _label(evidence.get('agentBackend'))
            call['generationTokensPerSecond'] = None
            call['generationSeconds'] = None
        calls.append(call)
    # Local v1 has no invocation identity: only an unambiguous span/model pair
    # can be joined. Repeated calls in one span remain separate observations.
    for (run, span, model), rows in sorted(local.items(), key=lambda p: str(p[0])):
        unique = {_fingerprint(e): e for e in rows}; duplicates += len(rows) - len(unique)
        starts = [e for e in unique.values() if e['fields']['status'] == 'started']
        ends = [e for e in unique.values() if e['fields']['status'] != 'started']
        pairs = [(starts[0], ends[0])] if span and len(starts) == len(ends) == 1 else [(e if e['fields']['status'] == 'started' else None, e if e['fields']['status'] != 'started' else None) for e in unique.values()]
        for start, end in pairs:
            e = end or start
            flat = {**e, **e['fields']}
            row = _row(start, flat if end else None, call_id=e.get('eventId'), backend='local', role='supervisor' if 'decision_agent' in stages[(run, span)] else 'production', scope='local_execution')
            row['model'] = _label(model)
            row['pairingStatus'] = 'paired' if start and end else 'individual_observation'
            calls.append(row)
    # Same provider response imported by another run counts once; conflicts
    # remove the entire response's numeric evidence rather than pick a winner.
    response_groups = defaultdict(list)
    for call in calls:
        receipt = api_receipts.get((call['runId'], call['callId']), {})
        identity = receipt.get('providerResponseId') or receipt.get('responseId')
        scope = receipt.get('providerScopeKey')
        if receipt.get('contractVersion') and scope is None:
            scope = ['unknown_scope', call['runId'], call['callId']]
        if identity and call['backend'] == 'api':
            response_groups[(call['provider'], _fingerprint(scope), identity)].append(call)
    removed = set()
    for rows in response_groups.values():
        if len(rows) < 2:
            continue
        comparable = lambda r: {k: r[k] for k in ('model', 'requestedModel', 'role', 'status', 'usage', 'elapsedSeconds', 'generationSeconds', 'timingScope')}
        variants = {_fingerprint(comparable(r)) for r in rows}
        keeper = rows[0]
        if len(variants) > 1:
            keeper.update(status='conflict', usageStatus='conflict', usage=_usage(None), elapsedSeconds=None, generationSeconds=None, effectiveRequestTokensPerSecond=None, generationTokensPerSecond=None, sessionOutputTokensPerSecond=None)
        else:
            duplicates += len(rows) - 1
        removed.update(id(r) for r in rows[1:])
    calls = [r for r in calls if id(r) not in removed]
    for row in calls:
        row['requestOutputTokensPerSecond'] = row['effectiveRequestTokensPerSecond']
        row['generationOutputTokensPerSecond'] = row['generationTokensPerSecond']
    totals = defaultdict(list)
    for call in calls:
        totals[(call['backend'], call['role'], call['model'])].append(call)
    aggregated = []
    for (backend, role, model), rows in sorted(totals.items(), key=lambda p: str(p[0])):
        coverage = {field: {'knownSubtotal': sum(r['usage'][field] for r in rows if r['usage'][field] is not None), 'knownCallCount': sum(r['usage'][field] is not None for r in rows), 'missingCallCount': sum(r['usage'][field] is None for r in rows), 'complete': all(r['usage'][field] is not None for r in rows)} for field in TOKEN_FIELDS}
        rates = {}
        for rate, duration in [('effectiveRequestTokensPerSecond', 'elapsedSeconds'), ('generationTokensPerSecond', 'generationSeconds'), ('sessionOutputTokensPerSecond', 'elapsedSeconds')]:
            matched = [r for r in rows if r[rate] is not None]
            tokens = sum(r['usage']['outputTokens'] for r in matched)
            seconds = sum(r[duration] for r in matched)
            rates[rate] = {'value': _rate(tokens, seconds), 'matchedCallCount': len(matched), 'missingCallCount': len(rows) - len(matched), 'matchedOutputTokens': tokens, 'matchedSeconds': seconds}
        aggregated.append({'backend': backend, 'role': role, 'model': model, 'callCount': len(rows), 'usage': coverage, 'rates': rates})
    return {'schemaVersion': 'sermon-model-call-report-v1', 'calls': calls, 'totals': aggregated, 'groups': aggregated, 'equivalentDuplicatesIgnored': duplicates,
            'coverage': {'callCount': len(calls), 'conflictCallCount': sum(c['status'] == 'conflict' for c in calls), 'missingOutputTokenCalls': sum(c['usage']['outputTokens'] is None for c in calls)}}
