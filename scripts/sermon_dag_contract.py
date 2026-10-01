"""Execution-plan boundary for the local mock Prefect pilot.

Progress and diagnostic projections consume evidence; neither is execution
authority. Existing canonical definitions, durable jobs and budget locks remain
authoritative. This version intentionally has no production adapter or publish.
"""
from copy import deepcopy
import math

from scripts import canonical_pipeline_definition as canonical
from scripts import sermon_review_contracts as c

PLAN_SCHEMA = 'sermon-dag-plan-v1'
SNAPSHOT_SCHEMA = 'sermon-dag-snapshot-v1'
RECEIPT_SCHEMA = 'sermon-dag-node-receipt-v1'
STATUSES = frozenset({'pending', 'waiting_dependency', 'queued', 'running', 'retry_wait',
    'blocked', 'completed', 'failed', 'cancelled', 'outcome_unknown'})
POOLS = frozenset({'fixed', 'api', 'local_model'})
SCENARIOS = frozenset({'pass', 'known_failure', 'outcome_unknown'})


def make_plan(*, run_id, input_identity_sha256, locales=canonical.LOCALES, text_only=(),
              resource_limits=None, scenarios=None, simulated_human=True, delay_seconds=.05,
              mock_request_limit=3):
    c.require(canonical._sha(run_id) and canonical._sha(input_identity_sha256), 'invalid_dag_identity')
    c.require(type(simulated_human) is bool and type(delay_seconds) in (int, float)
              and math.isfinite(delay_seconds) and 0 <= delay_seconds <= 5, 'invalid_mock_options')
    spec = canonical.definition(locales, text_only=text_only, terminal_scope='page_ready')
    resources = dict(resource_limits or {'fixed': 4, 'api': 2, 'local_model': 1})
    c.require(set(resources) == POOLS and all(type(n) is int and 1 <= n <= 4
              for n in resources.values()) and resources['local_model'] <= 2, 'invalid_dag_resource_limits')
    scenarios = dict(scenarios or {})
    known = {n['id'] for n in spec['nodes']}
    c.require(type(mock_request_limit) is int and 1 <= mock_request_limit <= 3, 'invalid_mock_budget')
    c.require(not set(scenarios)-known and all(type(v) is str and v in SCENARIOS for v in scenarios.values()),
              'invalid_mock_scenario')
    nodes = []
    for node in spec['nodes']:
        pool = ('api' if node['layer'] == 2 else 'local_model'
                if node['layer'] == 3 and node['locale'] not in text_only else 'fixed')
        nodes.append({'id': node['id'], 'layer': node['layer'], 'locale': node['locale'],
            'dependsOn': node['depends_on'], 'humanGates': node['human_gates'],
            'executorType': node['executor_type'], 'resourcePool': pool,
            'timeoutSeconds': 30, 'weight': 1, 'maxSchedulerRetries': 0,
            'mockScenario': scenarios.get(node['id'], 'pass')})
    plan = {'schemaVersion': PLAN_SCHEMA, 'runId': run_id,
        'inputIdentitySha256': input_identity_sha256, 'definition': spec,
        'mode': 'mock_only', 'evidenceMode': 'synthetic', 'productionEligible': False,
        'simulatedHuman': simulated_human, 'weightVersion': 'equal_nodes_v1',
        'resourceLimits': resources, 'mockDelaySeconds': delay_seconds,
        'mockRequestLimit': mock_request_limit, 'nodes': nodes}
    return {**plan, 'planSha256': c.canonical_sha256(plan)}


def validate_plan(plan):
    c.require(type(plan) is dict and type(plan.get('definition')) is dict
              and type(plan.get('nodes')) is list, 'invalid_dag_plan')
    try:
        expected = make_plan(run_id=plan['runId'], input_identity_sha256=plan['inputIdentitySha256'],
            locales=plan['definition']['targetLocales'], text_only=plan['definition']['textOnlyLocales'],
            resource_limits=plan['resourceLimits'], scenarios={n['id']: n['mockScenario'] for n in plan['nodes']},
            simulated_human=plan['simulatedHuman'], delay_seconds=plan['mockDelaySeconds'],
            mock_request_limit=plan['mockRequestLimit'])
    except (KeyError, TypeError) as exc:
        raise c.ContractError('invalid_dag_plan') from exc
    c.require(expected == plan and c.canonical_sha256({k:v for k,v in plan.items() if k != 'planSha256'})
              == expected['planSha256'], 'dag_plan_identity_changed')
    return deepcopy(plan)


def node_identity(plan, node, dependencies):
    """Exact dependency outputs bind admission; a scheduler state cannot do so."""
    validate_plan(plan)
    c.require(node in plan['nodes'] and type(dependencies) is dict
              and set(dependencies) == set(node['dependsOn'])
              and all(canonical._sha(v) for v in dependencies.values()), 'invalid_dag_dependencies')
    return c.canonical_sha256({'planSha256': plan['planSha256'], 'workUnitId': node['id'],
                              'inputIdentitySha256': plan['inputIdentitySha256'], 'dependencies': dependencies})
