"""Read-only dependency DAG and weekly accounting projection; no model or network calls."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.sermon_accounting import EXECUTOR_TYPES, READABLE_SCHEMAS, _label, _number, _safe_metadata, safe_execution_identity, read_events, read_event_snapshot, receipt_integrity, profile_integrity

from scripts.sermon_clock_evidence import monotonic_interval

from scripts import sermon_cache_observation as cache_observation
from scripts import sermon_local_model_observation as local_model
from scripts.sermon_workflow_evidence import _summary, PATHS

from scripts.sermon_decision_accounting import CODE as DECISION_CODE, safe_observation

TOKENS = ('inputTokens', 'cachedInputTokens', 'outputTokens', 'reasoningTokens')
ACTIVE = {'deterministic_program', 'production_model', 'decision_agent'}
TIMESTAMP_TOLERANCE_SECONDS = 0.01


def seconds(value):
    return datetime.fromisoformat(value).timestamp()


def digest(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


def usage_report(events, nodes, integrity=None):
    """Use the same all-run receipt equivalence as summary/log validation."""
    integrity = receipt_integrity(events) if integrity is None else integrity
    run_ids = {e['runId'] for e in events}
    conflicts = [c for c in integrity['conflicts'] if run_ids & set(c['runIds'])]
    rows, sdk = [], []
    for event in events:
        if id(event) not in integrity['_selected']:
            continue
        node = nodes.get(event.get('spanId'), {})
        common = {'executorType': node.get('executorType'), 'status': _label(event['status']),
                  'model': _label(event.get('model'), None),
                  'elapsedSeconds': _number(event.get('elapsedSeconds'))}
        if event['event'] == 'api_attempt':
            usage = {k: _number(event['usage'].get(k)) for k in TOKENS}
            inp, cached = usage['inputTokens'], usage['cachedInputTokens']
            usage['nonCachedInputTokens'] = inp - cached if inp is not None and cached is not None and inp >= cached else None
            rows.append({**common, 'receiptSha256': digest((event.get('provider'),
                event.get('responseId') or event.get('attemptId') or event['eventId'])),
                'responseIdSha256': digest(event['responseId']) if event.get('responseId') else None,
                'requestedModel': _label(event.get('requestedModel'), None),
                'spanSha256': digest(event['spanId']) if event.get('spanId') else None,
                'attemptSha256': digest(event['attemptId']) if event.get('attemptId') else None,
                'usage': usage, 'cost': {'status': _label(event['cost'].get('status'), None),
                    'estimatedUsd': _number(event['cost'].get('estimatedUsd')), 'invoiceVerified': False}})
        elif event['event'] == 'sdk_call_finished':
            sdk.append({**common, 'invocationSha256': digest(event['invocationId']), 'usage': {
                k: v if type(v) is int and v >= 0 else None for k, v in
                ((k, event['usage'].get(k)) for k in ('requests', 'input_tokens', 'output_tokens', 'total_tokens'))}})
    rows.sort(key=lambda r: r['receiptSha256']); sdk.sort(key=lambda r: r['invocationSha256'])
    totals = {}
    for executor in sorted(EXECUTOR_TYPES | {'unknown'}):
        selected = [r for r in rows if (r['executorType'] or 'unknown') == executor]
        totals[executor] = {'calls': None if conflicts else len(selected), 'knownSubtotal': {
            k: sum(r['usage'][k] for r in selected if r['usage'][k] is not None)
            if not conflicts and any(r['usage'][k] is not None for r in selected) else None
            for k in (*TOKENS, 'nonCachedInputTokens')},
            'missingFields': {k: sum(r['usage'][k] is None for r in selected)
                              for k in (*TOKENS, 'nonCachedInputTokens')}}
    started = {e['attemptId'] for e in events if e['event'] == 'api_attempt_started'}
    ended = {e.get('attemptId') for e in events if e['event'] == 'api_attempt'}
    return {'directReceipts': rows, 'byExecutor': totals, 'sdkAggregates': sdk,
            'conflicts': conflicts, 'status': 'conflicted' if conflicts else 'consistent',
            'unresolvedAttempts': len(started - ended), 'combinedTokenTotal': None,
            'scope': 'globally_deduplicated_direct_receipts_and_sdk_aggregates_separate',
            'equivalence': 'shared_with_accounting_summary_including_model_cost_latency_and_executor',
            'countMeaning': 'observed_receipt_count_not_proof_of_no_uninstrumented_calls'}


def project_run(run_id, events, integrity=None, receipt_events=None):
    diagnostics, pairs = [], defaultdict(lambda: {'start': [], 'end': []})
    def issue(code):
        if code not in diagnostics:
            diagnostics.append(code)
    for e in events:
        if e['event'] in {'stage_started', 'stage_finished'}:
            pairs[e['spanId']]['start' if e['event'] == 'stage_started' else 'end'].append(e)
    nodes = {}
    for ident, pair in pairs.items():
        if len(pair['start']) != 1 or len(pair['end']) != 1:
            issue('unfinished_or_ambiguous_span'); continue
        start, end = pair['start'][0], pair['end'][0]
        fields = ('stage', 'workflowId', 'parentSpanId', 'executorType', 'dependsOn',
                  'workUnitId', 'attemptId', 'decisionId', 'dependencyReadyAt', 'queuedAt')
        if any(start.get(k) != end.get(k) for k in fields):
            issue('span_identity_mismatch'); continue
        if end['status'] not in {'completed', 'failed', 'cancelled', 'outcome_unknown'}:
            issue('unknown_span_status'); continue
        if end['status'] in {'cancelled','outcome_unknown'}: issue('incomplete_execution_outcome')
        try:
            begin, finish = seconds(start['startedAt']), seconds(end['recordedAt'])
            ready = seconds(start['dependencyReadyAt']) if start.get('dependencyReadyAt') else None
            queued = seconds(start['queuedAt']) if start.get('queuedAt') else None
            ordered = [v for v in (ready, queued, begin, finish) if v is not None]
            timing = monotonic_interval(start, end)
            utc_trusted = timing is None or abs((finish-begin)-end['elapsedSeconds']) <= TIMESTAMP_TOLERANCE_SECONDS
            if timing is None and (ordered != sorted(ordered) or end['elapsedSeconds'] < 0 or
                    end['elapsedSeconds'] > finish - begin + 0.01):
                raise ValueError()
            if timing and not utc_trusted:
                issue('utc_clock_discontinuity_local_duration_preserved')
                ready = queued = None
            elif ordered != sorted(ordered):
                raise ValueError()
        except (ValueError, TypeError, OverflowError):
            issue('invalid_interval'); continue
        executor = start.get('executorType')
        nodes[ident] = {'spanSha256': digest(ident), 'stage': _label(start['stage']),
            'workUnitId': start.get('workUnitId'), 'executorType': executor,
            'attemptSha256': digest(start['attemptId']) if start.get('attemptId') else None,
            'workflowSha256': digest(start['workflowId']) if start.get('workflowId') else None,
            'startedAt': start['startedAt'], 'finishedAt': end['recordedAt'], 'cacheHit': start.get('cacheHit'),
            'queuedAt': start.get('queuedAt'),
            'status': end['status'], 'dependsOn': start.get('dependsOn') or [],
            'dependencyRecorded': isinstance(start.get('dependsOn'), list),
            'parent': start.get('parentSpanId'), 'begin': begin, 'finish': finish,
            'dependencyReadyAt': start.get('dependencyReadyAt'), 'ready': ready,
            'elapsedSeconds': end['elapsedSeconds'],
            'queueWaitSeconds': begin - queued if queued is not None else None,
            'dependencyReadyToQueueSeconds': queued - ready if ready is not None and queued is not None else None}
        if timing:
            nodes[ident].update(timing, utcTimingTrusted=utc_trusted)
    # A wall clock may jump BETWEEN individually sound intervals. Compare the
    # UTC/monotonic offset across all observations in each process clock domain.
    offsets = defaultdict(list)
    for node in nodes.values():
        if node.get('clockDomainId'):
            offsets[node['clockDomainId']].extend([
                node['begin'] - int(node['monotonicStartNs']) / 1e9,
                node['finish'] - int(node['monotonicEndNs']) / 1e9])
    unstable_domains = {domain for domain, values in offsets.items()
                        if max(values) - min(values) > TIMESTAMP_TOLERANCE_SECONDS}
    if unstable_domains:
        issue('utc_clock_discontinuity_between_spans')
        for node in nodes.values():
            if node.get('clockDomainId') in unstable_domains:
                node.update(utcTimingTrusted=False, ready=None, queueWaitSeconds=None,
                            dependencyReadyToQueueSeconds=None)
    # Parent/container spans overlap children. Only executable leaves participate
    # in the active DAG; dependencies on containers need explicit leaf receipts.
    for ident, node in nodes.items():
        cursor, visited = node['parent'], {ident}
        while cursor is not None:
            if cursor in visited:
                issue('parent_cycle'); break
            if cursor not in nodes:
                issue('missing_parent'); break
            parent = nodes[cursor]
            same_clock = node.get('clockDomainId') and node.get('clockDomainId') == parent.get('clockDomainId')
            if same_clock:
                if int(parent['monotonicStartNs']) > int(node['monotonicStartNs']) or int(parent['monotonicEndNs']) < int(node['monotonicEndNs']):
                    issue('parent_interval_mismatch')
            elif node.get('clockDomainId') or parent.get('clockDomainId'):
                issue('cross_clock_parent_timing_unknown')
            elif node.get('utcTimingTrusted', True) and parent.get('utcTimingTrusted', True):
                if parent['begin'] > node['begin'] or parent['finish'] < node['finish']:
                    issue('parent_interval_mismatch')
            else:
                issue('cross_clock_parent_timing_unknown')
            visited.add(cursor); cursor = parent['parent']
    parents = {e.get('parentSpanId') for pair in pairs.values() for e in pair['start'] + pair['end'] if e.get('parentSpanId')}
    leaves = {key: n for key, n in nodes.items() if key not in parents}
    if not leaves:
        issue('no_complete_execution_spans')
    for key, n in leaves.items():
        if n['executorType'] is None or not n['dependencyRecorded']:
            issue('legacy_dependency_or_executor_unknown')
        for dep in n['dependsOn']:
            if dep not in leaves:
                issue('missing_or_container_dependency')
            else:
                parent = leaves[dep]
                same_clock = n.get('clockDomainId') and n.get('clockDomainId') == parent.get('clockDomainId')
                if same_clock:
                    if int(parent['monotonicEndNs']) > int(n['monotonicStartNs']):
                        issue('dependency_interval_overlap')
                elif n.get('clockDomainId') or parent.get('clockDomainId'):
                    issue('cross_clock_dependency_timing_unknown')
                elif n.get('utcTimingTrusted', True) and parent.get('utcTimingTrusted', True):
                    if parent['finish'] > n['begin'] + TIMESTAMP_TOLERANCE_SECONDS:
                        issue('dependency_interval_overlap')
                else:
                    issue('cross_clock_dependency_timing_unknown')
                if n['ready'] is not None and not parent.get('utcTimingTrusted', True):
                    issue('dependency_ready_clock_untrusted')
                    n['queueWaitSeconds'] = None
                    n['dependencyReadyToQueueSeconds'] = None
                elif n['ready'] is not None and parent['finish'] > n['ready'] + TIMESTAMP_TOLERANCE_SECONDS:
                    issue('dependency_not_finished_at_ready')
                    n['queueWaitSeconds'] = None
                    n['dependencyReadyToQueueSeconds'] = None
    pending, order = set(leaves), []
    while pending:
        ready = sorted(k for k in pending if not (set(leaves[k]['dependsOn']) & pending))
        if not ready:
            issue('dependency_cycle'); break
        order.extend(ready); pending.difference_update(ready)
    critical = None
    if not diagnostics:
        earliest, previous = {}, {}
        weights = {k: n['elapsedSeconds'] if n['executorType'] in ACTIVE else 0 for k, n in leaves.items()}
        for key in order:
            deps = leaves[key]['dependsOn']
            prev = max(deps, key=lambda k: (earliest[k], k)) if deps else None
            previous[key] = prev
            earliest[key] = (earliest[prev] if prev else 0) + weights[key]
        terminal = max(order, key=lambda k: (earliest[k], k))
        duration = earliest[terminal]
        children = defaultdict(list)
        for key in order:
            for dep in leaves[key]['dependsOn']:
                children[dep].append(key)
        latest = {}
        for key in reversed(order):
            latest[key] = min((latest[c] - weights[c] for c in children[key]), default=duration)
        path, cursor = [], terminal
        while cursor is not None:
            path.append(leaves[cursor]['spanSha256']); cursor = previous[cursor]
        critical = {'activeSeconds': round(duration, 6), 'spanPath': list(reversed(path)),
                    'branchSlackSeconds': {leaves[k]['spanSha256']: round(latest[k] - earliest[k], 6) for k in order},
                    'scope': 'active_leaf_compute_excludes_human_external_and_engineering'}
    starts = [e for e in events if e['event'] == 'run_started']
    ends = [e for e in events if e['event'] == 'run_finished']
    wall = None
    if len(starts) == len(ends) == 1:
        wall = seconds(ends[0]['recordedAt']) - seconds(starts[0]['recordedAt'])
        if wall < 0:
            wall = None; issue('invalid_run_interval')
        elif any(n['begin'] < seconds(starts[0]['recordedAt']) or
                 n['finish'] > seconds(ends[0]['recordedAt']) for n in nodes.values()):
            issue('span_outside_run_interval')
    else:
        issue('run_wall_unknown')
    if any(not n.get('utcTimingTrusted', True) for n in nodes.values()):
        wall = None
        issue('run_utc_wall_untrusted')
    decision_observations, decision_facts = [], defaultdict(dict)
    for event in events:
        if event.get('event') == 'log' and event.get('code') == DECISION_CODE:
            try:
                fact = safe_observation(event.get('fields'))
                identity = (fact['observationId'], fact['phase'])
                decision_facts[identity][json.dumps(fact, sort_keys=True)] = fact
            except (ValueError, TypeError):
                issue('invalid_decision_observation')
    for identity in sorted(decision_facts):
        facts = decision_facts[identity]
        if len(facts) != 1:
            issue('conflicting_decision_observations')
        else:
            decision_observations.append(next(iter(facts.values())))
    local_observations = []
    for event in events:
        if event.get('event') == 'log' and event.get('code') == local_model.CODE:
            try:
                fact = local_model.safe_observation(event.get('fields'))
                local_observations.append({**fact, 'spanSha256': digest(event['spanId']) if event.get('spanId') else None})
            except (TypeError, ValueError):
                issue('invalid_local_model_observation')
    cached = []
    for event in events:
        if event.get('event') == 'log' and event.get('code') == cache_observation.CODE:
            try:
                fact = cache_observation.safe_observation(event.get('fields'))
                cached.append({**fact, 'spanSha256': digest(event['spanId']) if event.get('spanId') else None,
                    'workflowSha256': digest(event['workflowId']) if event.get('workflowId') else None,
                    'recordedAt': event['recordedAt']})
            except (TypeError, ValueError):
                issue('invalid_model_cache_observation')
    history = defaultdict(dict)
    for fact in cached:
        # Reuse may validate a response repeatedly; count historical usage once.
        payload = {k: fact[k] for k in ('provider', 'model', 'requestedModel', 'usage', 'usageProvenance', 'payloadSha256')}
        history[fact['responseIdSha256']][json.dumps(payload, sort_keys=True)] = payload
    history_conflicts = sorted(k for k, v in history.items() if len(v) != 1)
    if history_conflicts:
        issue('conflicting_historical_cache_receipts')
    historical = [next(iter(v.values())) for v in history.values() if len(v) == 1]
    cache_summary = {'observations': len(cached), 'distinctHistoricalResponses': len(history),
        'conflicts': history_conflicts, 'historicalCostUsd': None,
        'currentSpendMeaning': 'cache_observations_are_not_current_transport_or_spend_receipts',
        'knownHistoricalTokenSubtotal': {k: sum(f['usage'][k] for f in historical if f['usage'][k] is not None)
            if not history_conflicts and any(f['usage'][k] is not None for f in historical) else None
            for k in TOKENS},
        'missingHistoricalFields': {k: sum(f['usage'][k] is None for f in historical) for k in TOKENS}}
    usage = usage_report(events if receipt_events is None else receipt_events, nodes, integrity)
    if usage['conflicts']:
        issue('conflicting_usage_receipts')
    if diagnostics:
        critical = None
    totals = {executor: round(sum(n['elapsedSeconds'] for n in leaves.values() if n['executorType'] == executor), 6)
              for executor in sorted(EXECUTOR_TYPES)}
    safe_nodes = [{**{k: v for k, v in n.items() if k not in {'dependsOn', 'parent', 'begin', 'finish', 'ready'}},
                   'dependsOnSha256': [digest(dep) for dep in n['dependsOn']],
                   'parentSpanSha256': digest(n['parent']) if n['parent'] else None,
                   'models': sorted({_label(e.get('model')) for e in events
                                    if e.get('spanId') == key and e['event'] in {'api_attempt_started', 'api_attempt', 'sdk_call_finished'}}
                                    | {f['requestedModel'] for f in cached if f['spanSha256'] == digest(key) and f['requestedModel']}
                                    | {f['model'] for f in local_observations if f['spanSha256'] == digest(key)}),
                   'queueTimingStatus': 'measured' if n['queueWaitSeconds'] is not None else 'missing_instrumentation'}
                  for key, n in leaves.items()]
    unfinished = [{'spanSha256': digest(key), 'stage': _label(e['stage']),
                   'executorType': e.get('executorType'), 'startedAt': e.get('startedAt'),
                   'elapsedSeconds': None, 'status': 'unfinished_or_ambiguous'}
                  for key, pair in pairs.items() if key not in nodes
                  for e in (pair['start'] or pair['end'])[:1]]
    coverage = {}
    for executor in sorted(EXECUTOR_TYPES):
        count = sum(n['executorType'] == executor for n in leaves.values())
        missing = sum(n['executorType'] == executor for n in unfinished)
        coverage[executor] = {'completedSpanCount': count, 'unfinishedSpanCount': missing,
            'completedSpanSubtotalSeconds': totals[executor],
            'status': 'incomplete' if missing else 'measured_completed_spans' if count else 'not_observed',
            'totalExecutionSeconds': None}
    source_durations = {e['metrics']['sourceDurationSeconds'] for e in events
                        if e['event'] == 'workload' and _number(e['metrics'].get('sourceDurationSeconds')) is not None}
    locales = sorted({e.get('metadata', {}).get('targetLocale') for e in events
                      if e['event'] == 'workflow_started' and _label(e.get('metadata', {}).get('targetLocale'), None)})
    source_duration = next(iter(source_durations)) if len(source_durations) == 1 else None
    provenance = [{'workflowSha256': digest(e['workflowId']) if e.get('workflowId') else None,
                   'metadata': _safe_metadata(e.get('metadata', {})),
                   'parentWorkflowSha256': digest(e['parentWorkflowId']) if e.get('parentWorkflowId') else None,
                   'executionIdentity': safe_execution_identity(e.get('executionIdentity'))}
                  for e in events if e['event'] == 'workflow_started']
    workload = [{'stage': _label(e.get('stage')), 'spanSha256': digest(e['spanId']) if e.get('spanId') else None,
                 'metrics': {k: v for k, v in e['metrics'].items()
                             if (k.endswith('Sha256') and isinstance(v, str) and len(v) == 64
                                 and all(c in '0123456789abcdef' for c in v))
                             or _number(v) is not None or isinstance(v, bool)}}
                for e in events if e['event'] == 'workload']
    from scripts.sermon_review_observation import observations
    rqc = observations(events)
    return {**({'reviewObservations': rqc} if rqc else {}), 'runSha256': digest(run_id), 'status': 'partial' if diagnostics else 'projected',
            'endToEndWallSeconds': wall, 'criticalPath': critical, 'diagnostics': diagnostics,
            'leafElapsedByExecutor': totals, 'leafElapsedMeaning': 'completed_leaf_subtotals_not_proof_of_absent_work',
            'executorCoverage': coverage, 'unfinishedSpans': unfinished,
            'usage': usage, 'decisionObservations': decision_observations,
            'localModelObservations': local_observations, 'cacheObservations': cached, 'historicalCacheUsage': cache_summary,
            'artifactSnapshots': [{
                'workflowSha256': digest(e['workflowId']) if e.get('workflowId') else None,
                'phase': _label(e.get('phase')), 'scope': 'existing_files_not_execution_proof',
                'artifacts': [{k: a[k] for k in ('category', 'sha256', 'bytes') if k in a} | {'summary': _summary(a.get('summary', {}))}
                    for a in e['evidence'].get('artifacts', []) if isinstance(a, dict)
                    and a.get('category') in PATHS and isinstance(a.get('sha256'), str)
                    and len(a['sha256']) == 64 and all(c in '0123456789abcdef' for c in a['sha256'])]}
                for e in events if e['event'] == 'workflow_evidence'],
            'workflowProvenance': provenance, 'workloadEvidence': workload,
            'workUnits': sorted(safe_nodes, key=lambda n: (-n['elapsedSeconds'], n['spanSha256'])),
            'sourceDurationSeconds': source_duration, 'locales': locales or None, 'pageReadyAt': None,
            'orchestrationOverheadSeconds': None,
            'observabilityCoverage': {
                'sourceDuration': 'recorded' if source_duration is not None else 'missing_or_conflicting',
                'locales': 'recorded' if locales else 'not_observed',
                'queueTiming': 'measured' if leaves and all(n['queueWaitSeconds'] is not None for n in leaves.values()) else 'missing_instrumentation',
                'pageReady': 'not_observed', 'orchestrationOverhead': 'missing_instrumentation',
                'crossProcessCriticalPath': 'not_established',
                'logCompleteness': 'not_established',
                'statusMeaning': 'projected_means_computable_recorded_DAG_not_complete_telemetry'},
            'acceptance': 'not_evaluated', 'notes': [
                'Executor subtotals overlap across parallel branches; never sum as end-to-end wall.',
                'dependsOn contains exact same-run span IDs, not stage names or parent span IDs.',
                'Human/external elapsed is wait; engineering is separate from production runtime.',
                'Missing source/locale/page-ready telemetry stays unknown; no sign-off is inferred.']}


def project(directory):
    events, damaged, ledger_hash = read_event_snapshot(directory)
    replay = profile_integrity(events)
    runs, receipt_events, seen, diagnostics = defaultdict(list), defaultdict(list), {}, []
    if replay['status'] != 'consistent': diagnostics.append('incomplete_or_conflicting_profile_events')
    duplicates = 0
    for event in events:
        if event.get('schemaVersion') not in READABLE_SCHEMAS:
            diagnostics.append('unsupported_schema'); continue
        # Conflicting copies of the same event identity are still receipt facts.
        # Reconcile them before selecting representatives for DAG projection.
        receipt_events[event['runId']].append(event)
        if id(event) in replay['_excluded']: continue
        key = (event['runId'], event['eventId'])
        if key in seen:
            if event != seen[key]:
                diagnostics.append('conflicting_event_identity')
            else:
                duplicates += 1
            continue
        seen[key] = event; runs[event['runId']].append(event)
    if damaged:
        diagnostics.append('damaged_events')
    integrity = receipt_integrity([event for rows in receipt_events.values() for event in rows])
    result = [project_run(k, v, integrity, receipt_events[k]) for k, v in sorted(runs.items())]
    if diagnostics:
        # A damaged record can hide a dependency: never claim a complete DAG.
        for run in result:
            run['criticalPath'] = None; run['status'] = 'partial'
    return {'schemaVersion': 'sermon-weekly-pipeline-report-v1', **({'sourceLedgerSha256': ledger_hash} if replay['profileEventCount'] else {}), 'runs': result,
            'status': 'partial' if diagnostics or not result or any(r['status'] == 'partial' for r in result) else 'projected',
            'diagnostics': diagnostics, 'duplicateEventsIgnored': duplicates,
            'receiptIntegrity': {k: v for k, v in integrity.items() if not k.startswith('_')},
            **({'eventIntegrity': {k: v for k, v in replay.items() if not k.startswith('_')}} if replay['profileEventCount'] else {}), 'networkCalls': 0, 'acceptance': 'not_evaluated'}


def markdown(report):
    lines = ['# Weekly Pipeline Report', '', 'Status: ' + report['status'], '',
             'Projected means a computable recorded DAG, not complete telemetry. Content/device/venue/release acceptance: not evaluated.', '']
    for run in report['runs']:
        lines += ['## Run ' + run['runSha256'][:12], '',
                  'End-to-end wall seconds: ' + str(run['endToEndWallSeconds']),
                  'Active critical-path seconds: ' + str((run['criticalPath'] or {}).get('activeSeconds')), '',
                  '| Executor | Leaf elapsed seconds (parallel subtotal) |', '|---|---:|']
        lines += [f"| {k} | {v} ({run['executorCoverage'][k]['status']}; completed spans only) |" for k, v in run['leafElapsedByExecutor'].items()]
        lines += ['', 'Coverage: ' + json.dumps(run['observabilityCoverage'], sort_keys=True),
                  '', '| Stage / attempt | Executor / models | Cache | Start → finish | Dependencies | Queue |',
                  '|---|---|---|---|---|---|']
        for row in run['workUnits']:
            lines.append('| ' + ' | '.join(map(str, [row['stage'] + ' / ' + str(row['attemptSha256'])[:12],
                str(row['executorType']) + ' / ' + ','.join(row['models']), row['cacheHit'],
                row['startedAt'] + ' → ' + row['finishedAt'], ','.join(x[:12] for x in row['dependsOnSha256']),
                row['queueWaitSeconds'] if row['queueWaitSeconds'] is not None else row['queueTimingStatus']])) + ' |')
        lines += ['', 'Direct receipt usage (SDK aggregates remain separate):', '',
                  '| Executor | Calls | Input | Cached | Non-cached | Output | Reasoning |', '|---|---:|---:|---:|---:|---:|---:|']
        for executor, row in run['usage']['byExecutor'].items():
            values = [row['knownSubtotal'][k] for k in ('inputTokens', 'cachedInputTokens', 'nonCachedInputTokens', 'outputTokens', 'reasoningTokens')]
            lines.append('| ' + ' | '.join(map(str, [executor, row['calls'], *values])) + ' |')
        if run['cacheObservations']:
            lines += ['', 'Historical cache receipts (excluded from current API usage/spend):', '',
                      '| Role | Requested / receipt model | Span | Cache hash | Original response hash | Usage provenance | Historical input / output |',
                      '|---|---|---|---|---|---|---|']
            for fact in run['cacheObservations']:
                lines.append('| ' + ' | '.join(map(str, [fact['role'], str(fact['requestedModel']) + ' / ' + str(fact['model']),
                    str(fact['spanSha256'])[:12], str(fact['cacheSha256'])[:12], str(fact['responseIdSha256'])[:12],
                    fact['usageProvenance'], str(fact['usage']['inputTokens']) + ' / ' + str(fact['usage']['outputTokens'])])) + ' |')
        if run.get('decisionObservations'):
            lines += ['', 'Decision observations (commit is separate; missing usage remains unknown):', '',
                      '| Phase | Status | Packet bytes | Responder ms | Validation ms | Commit ms |',
                      '|---|---|---:|---:|---:|---:|']
            for observation in run['decisionObservations']:
                timing = observation['timings']
                values = [observation['phase'], observation['status'], observation['statePacketBytes'],
                          timing['modelLatencyMs'], timing['decisionValidationMs'], timing['stateCommitMs']]
                lines.append('| ' + ' | '.join(map(str, values)) + ' |')
        if run.get('reviewObservations'):
            lines += ['', 'Private RQC evidence (execution, verdict and admission are separate; no authority inferred):',
                      '', '| Unit / revision | Role | Execution | Verdict | Admission | Reasons | Receipt hash |', '|---|---|---|---|---|---|---|']
            for observation in run['reviewObservations']:
                value=observation['evidence']
                lines.append('| ' + ' | '.join(map(str,[observation['workUnitId'] + ' / ' + value['revisionId'],
                    observation['role'],value['executionStatus'],value['reviewVerdict'],value['admissionStatus'],
                    ','.join(value['reasonCodes']),value['receiptCanonicalJsonSha256']])) + ' |')
        lines += ['', 'Diagnostics: ' + ', '.join(run['diagnostics']), '']
    return '\n'.join(line.rstrip() for line in lines).rstrip() + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--accounting-dir', required=True, type=Path)
    parser.add_argument('--out-dir', required=True, type=Path)
    args = parser.parse_args()
    # Keep projections away from the append-only source and existing outputs.
    from scripts import sermon_trace_artifacts as artifacts
    artifacts.new_directory(args.out_dir)
    report = project(args.accounting_dir)
    for name, content in [('report.json', json.dumps(report, indent=2, allow_nan=False) + '\n'),
                          ('report.md', markdown(report))]:
        path = args.out_dir / name
        artifacts.write(path,content)
    return 0 if report['status'] == 'projected' else 1


if __name__ == '__main__':
    sys.exit(main())
