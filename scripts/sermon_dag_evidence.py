"""Read-only terminal execution leaves; wrappers confer no completion authority."""
from scripts import sermon_accounting as accounting


def terminal_leaves(events, run_id, root_span_id):
    starts, ends = {}, {}
    for row in events:
        if row.get('runId') != run_id:
            continue
        if row.get('event') in ('stage_started', 'stage_finished'):
            target = starts if row['event'] == 'stage_started' else ends
            target.setdefault(row['spanId'], []).append(row)
    if root_span_id not in starts:
        raise ValueError('dag_completion_span_missing')
    scope = {root_span_id}
    while True:
        added = {key for key, rows in starts.items() if any(row.get('parentSpanId') in scope for row in rows)} - scope
        if not added:
            break
        scope.update(added)
    parents = {row.get('parentSpanId') for key in scope for row in starts[key]}
    leaves = scope - parents
    for key in scope:
        if len(starts[key]) != 1 or len(ends.get(key, [])) != 1 or ends[key][0]['status'] != 'completed':
            raise ValueError('dag_completion_evidence_incomplete')
        if any(starts[key][0].get(name) != ends[key][0].get(name) for name in
            ('runId', 'spanId', 'parentSpanId', 'stage', 'attemptId', 'dependsOn', 'executorType')):
            raise ValueError('dag_completion_identity_changed')
    for key in leaves:
        row = starts[key][0]
        if not isinstance(row.get('dependsOn'), list) or row.get('executorType') not in accounting.EXECUTOR_TYPES:
            raise ValueError('dag_completion_leaf_dependency_unknown')
    consumed = {dep for key in leaves for dep in starts[key][0]['dependsOn'] if dep in leaves}
    return sorted(leaves - consumed)


def current_terminal_leaves(root_span_id):
    identity = accounting._identity.get()
    if not identity:
        raise ValueError('dag_accounting_required')
    events, errors = accounting.read_events(identity[0])
    if errors:
        raise ValueError('dag_accounting_damaged')
    return terminal_leaves(events, identity[1], root_span_id)
