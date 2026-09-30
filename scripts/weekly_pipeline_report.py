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
from scripts.sermon_accounting import EXECUTOR_TYPES, READABLE_SCHEMAS, _label, read_events

TOKENS = ('inputTokens', 'cachedInputTokens', 'outputTokens', 'reasoningTokens')
ACTIVE = {'deterministic_program', 'production_model', 'decision_agent'}


def seconds(value):
    return datetime.fromisoformat(value).timestamp()


def digest(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


def usage_report(events, nodes):
    """Provider receipts are facts; SDK aggregates are separate, never added."""
    seen, sdk_seen, rows, sdk = set(), set(), [], []
    for event in events:
        if event['event'] == 'sdk_call_finished':
            key = event['invocationId']
            if key not in sdk_seen:
                sdk_seen.add(key)
                sdk.append({'invocationSha256': digest(key), 'usage': {
                    k: v if type(v) is int and v >= 0 else None
                    for k, v in ((k, event['usage'].get(k)) for k in
                                 ('requests', 'input_tokens', 'output_tokens', 'total_tokens'))}})
        if event['event'] != 'api_attempt':
            continue
        # A provider response reimport is not a new billable attempt. Scope by
        # provider when present; absent provider remains explicitly unknown.
        key = (_label(event.get('provider'), None), event.get('responseId') or event.get('attemptId') or event['eventId'])
        if key in seen:
            continue
        seen.add(key)
        usage = {k: event['usage'].get(k) for k in TOKENS}
        inp, cached = usage['inputTokens'], usage['cachedInputTokens']
        usage['nonCachedInputTokens'] = inp - cached if inp is not None and cached is not None and inp >= cached else None
        node = nodes.get(event.get('spanId'), {})
        rows.append({'receiptSha256': digest(key), 'executorType': node.get('executorType'),
                     'status': _label(event['status']), 'usage': usage})
    totals = {}
    for executor in sorted(EXECUTOR_TYPES | {'unknown'}):
        selected = [r for r in rows if (r['executorType'] or 'unknown') == executor]
        totals[executor] = {'calls': len(selected), 'knownSubtotal': {
            k: sum(r['usage'][k] for r in selected if r['usage'][k] is not None)
            if any(r['usage'][k] is not None for r in selected) else None
            for k in (*TOKENS, 'nonCachedInputTokens')},
            'missingFields': {k: sum(r['usage'][k] is None for r in selected)
                              for k in (*TOKENS, 'nonCachedInputTokens')}}
    started = {e['attemptId'] for e in events if e['event'] == 'api_attempt_started'}
    ended = {e.get('attemptId') for e in events if e['event'] == 'api_attempt'}
    return {'directReceipts': rows, 'byExecutor': totals, 'sdkAggregates': sdk,
            'unresolvedAttempts': len(started - ended), 'combinedTokenTotal': None,
            'scope': 'direct_receipts_and_sdk_aggregates_separate_no_cross_scope_sum'}


def project_run(run_id, events):
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
        if end['status'] not in {'completed', 'failed'}:
            issue('unknown_span_status'); continue
        try:
            begin, finish = seconds(start['startedAt']), seconds(end['recordedAt'])
            ready = seconds(start['dependencyReadyAt']) if start.get('dependencyReadyAt') else None
            queued = seconds(start['queuedAt']) if start.get('queuedAt') else None
            ordered = [v for v in (ready, queued, begin, finish) if v is not None]
            if (ordered != sorted(ordered) or end['elapsedSeconds'] < 0 or
                    end['elapsedSeconds'] > finish - begin + 0.01):
                raise ValueError()
        except (ValueError, TypeError, OverflowError):
            issue('invalid_interval'); continue
        executor = start.get('executorType')
        nodes[ident] = {'spanSha256': digest(ident), 'stage': _label(start['stage']),
            'workUnitId': start.get('workUnitId'), 'executorType': executor,
            'status': end['status'], 'dependsOn': start.get('dependsOn') or [],
            'dependencyRecorded': isinstance(start.get('dependsOn'), list),
            'parent': start.get('parentSpanId'), 'begin': begin, 'finish': finish,
            'elapsedSeconds': end['elapsedSeconds'],
            'queueWaitSeconds': begin - queued if queued is not None else None,
            'dependencyReadyToQueueSeconds': queued - ready if ready is not None and queued is not None else None}
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
            if parent['begin'] > node['begin'] or parent['finish'] < node['finish']:
                issue('parent_interval_mismatch')
            visited.add(cursor); cursor = parent['parent']
    parents = {n['parent'] for n in nodes.values() if n['parent']}
    leaves = {key: n for key, n in nodes.items() if key not in parents}
    if not leaves:
        issue('no_complete_execution_spans')
    for key, n in leaves.items():
        if n['executorType'] is None or not n['dependencyRecorded']:
            issue('legacy_dependency_or_executor_unknown')
        for dep in n['dependsOn']:
            if dep not in leaves:
                issue('missing_or_container_dependency')
            elif leaves[dep]['finish'] > n['begin']:
                issue('dependency_interval_overlap')
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
    if diagnostics:
        critical = None
    totals = {executor: round(sum(n['elapsedSeconds'] for n in leaves.values() if n['executorType'] == executor), 6)
              for executor in sorted(EXECUTOR_TYPES)}
    safe_nodes = [{k: v for k, v in n.items() if k not in {'dependsOn', 'parent', 'begin', 'finish'}} for n in leaves.values()]
    return {'runSha256': digest(run_id), 'status': 'partial' if diagnostics else 'projected',
            'endToEndWallSeconds': wall, 'criticalPath': critical, 'diagnostics': diagnostics,
            'leafElapsedByExecutor': totals, 'usage': usage_report(events, nodes),
            'workUnits': sorted(safe_nodes, key=lambda n: (-n['elapsedSeconds'], n['spanSha256'])),
            'sourceDurationSeconds': None, 'locales': None, 'pageReadyAt': None,
            'acceptance': 'not_evaluated', 'notes': [
                'Executor subtotals overlap across parallel branches; never sum as end-to-end wall.',
                'dependsOn contains exact same-run span IDs, not stage names or parent span IDs.',
                'Human/external elapsed is wait; engineering is separate from production runtime.',
                'Missing source/locale/page-ready telemetry stays unknown; no sign-off is inferred.']}


def project(directory):
    events, damaged = read_events(directory)
    runs, seen, diagnostics = defaultdict(list), {}, []
    duplicates = 0
    for event in events:
        if event.get('schemaVersion') not in READABLE_SCHEMAS:
            diagnostics.append('unsupported_schema'); continue
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
    result = [project_run(k, v) for k, v in sorted(runs.items())]
    if diagnostics:
        # A damaged record can hide a dependency: never claim a complete DAG.
        for run in result:
            run['criticalPath'] = None; run['status'] = 'partial'
    return {'schemaVersion': 'sermon-weekly-pipeline-report-v1', 'runs': result,
            'status': 'partial' if diagnostics or not result or any(r['status'] == 'partial' for r in result) else 'projected',
            'diagnostics': diagnostics, 'duplicateEventsIgnored': duplicates, 'networkCalls': 0, 'acceptance': 'not_evaluated'}


def markdown(report):
    lines = ['# Weekly Pipeline Report', '', 'Status: ' + report['status'], '',
             'Local accounting projection. Content, device, venue and release acceptance: not evaluated.', '']
    for run in report['runs']:
        lines += ['## Run ' + run['runSha256'][:12], '',
                  'End-to-end wall seconds: ' + str(run['endToEndWallSeconds']),
                  'Active critical-path seconds: ' + str((run['criticalPath'] or {}).get('activeSeconds')), '',
                  '| Executor | Leaf elapsed seconds (parallel subtotal) |', '|---|---:|']
        lines += [f'| {k} | {v} |' for k, v in run['leafElapsedByExecutor'].items()]
        lines += ['', 'Direct receipt usage (SDK aggregates remain separate):', '',
                  '| Executor | Calls | Input | Cached | Non-cached | Output | Reasoning |', '|---|---:|---:|---:|---:|---:|---:|']
        for executor, row in run['usage']['byExecutor'].items():
            values = [row['knownSubtotal'][k] for k in ('inputTokens', 'cachedInputTokens', 'nonCachedInputTokens', 'outputTokens', 'reasoningTokens')]
            lines.append('| ' + ' | '.join(map(str, [executor, row['calls'], *values])) + ' |')
        lines += ['', 'Diagnostics: ' + ', '.join(run['diagnostics']), '']
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--accounting-dir', required=True, type=Path)
    parser.add_argument('--out-dir', required=True, type=Path)
    args = parser.parse_args()
    # Keep projections away from the append-only source and existing outputs.
    args.out_dir.mkdir(parents=True, exist_ok=False)
    report = project(args.accounting_dir)
    for name, content in [('report.json', json.dumps(report, indent=2, allow_nan=False) + '\n'),
                          ('report.md', markdown(report))]:
        path = args.out_dir / name
        with path.open('x') as stream:
            stream.write(content)
        path.chmod(0o600)
    return 0 if report['status'] == 'projected' else 1


if __name__ == '__main__':
    sys.exit(main())
