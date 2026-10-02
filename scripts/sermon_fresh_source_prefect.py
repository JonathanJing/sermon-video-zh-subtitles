"""Bounded real Prefect ownership of five Fresh Source stages and locale freeze.

Synthetic transport and verified prior-alignment fixture only. This milestone
ends at frozen locale inputs: text/TTS/downstream ownership is explicitly absent.
"""
from copy import deepcopy
from importlib.metadata import version
import os
from pathlib import Path
import re
import tempfile
import uuid

from scripts import sermon_accounting as accounting
from scripts import sermon_completion as completion
from scripts import sermon_durable_accounting as durable
from scripts import sermon_fresh_diagnostic as fresh
from scripts import sermon_fresh_diagnostic_source as source
from scripts import sermon_fresh_source_stages as stages
from scripts import sermon_log_profile as profile
from scripts import sermon_mock_tts_dag as mock
from scripts import sermon_public_snapshot as public
from scripts import sermon_review_contracts as c
from scripts import sermon_source_failure as failure
from scripts.sermon_execution_harness import work_lock
from scripts.sermon_release_workflow import _safe_path

SCHEMA = 'sermon-fresh-source-prefect-plan-v1'
NAMES = {'intake': 'source.preflight', 'transcription': 'transcription.initial',
    'sourceCheck': 'source.initial', 'alignment': 'source.alignment', 'sourcePackage': 'source.package'}
QUALIFICATIONS = {'evidenceMode': 'synthetic', 'humanAcceptance': 'pending',
    'productionEligible': False, 'publicationAuthorized': False, 'downstreamEngineTakeover': False}


def _groups(recipe):
    aligned, _ = source._read_alignment(recipe['prior_aligned_path'])
    anchor = source.anchors.build_anchor_manifest(aligned, source_path=Path(recipe['prior_aligned_path']),
        unit_policy=source.anchors.UNIT_POLICY_V2)
    return [{'translationGroupId': f'fresh-g{i//3+1:03d}',
        'sourceUnitIds': [unit['sourceUnitId'] for unit in anchor['sourceUnits'][i:i+3]]}
        for i in range(0, len(anchor['sourceUnits']), 3)]


def source_declaration(session, stage_adapter, locale_drafts):
    """Plan all fixed Source/locale outputs without opening a stream or executing."""
    c.require(type(locale_drafts) is dict and bool(locale_drafts) and set(locale_drafts) <= fresh.flow.LOCALES,
        'fresh_engine_locales_invalid')
    locales = deepcopy(locale_drafts)
    for locale, files in locales.items():
        c.require(type(files) is dict and set(files) == {'policy', 'rubric', 'pluginPath'},
            'fresh_engine_locale_drafts_invalid')
        for key, value in files.items():
            files[key] = str(session._path(value, plugin=key == 'pluginPath'))
        c.require(public.read_snapshot(files['policy'])[0]['targetLocale'] == locale,
            'fresh_engine_locale_drift')
    expected_groups = _groups(stage_adapter.recipe)
    c.require(1 <= len(expected_groups) <= 64, 'fresh_engine_group_limit')
    nodes = []
    previous = None
    for stage in stages.ORDER:
        node = {'id': NAMES[stage], 'stage': stage, 'dependsOn': [] if previous is None else [previous]}
        nodes.append(node); previous = node['id']
    nodes.append({'id': 'locale.freeze', 'stage': 'localeFreeze', 'dependsOn': ['source.package']})
    outputs = {'source': str(session.root/'source.json'), 'anchor': str(session.root/'anchor-manifest.json'),
        'alignment': str(session.root/'aligned-segments.json'),
        'localeSpecs': {locale: str(session.root/'fresh-inputs'/locale/'spec.json') for locale in locales},
        'translationGroups': deepcopy(expected_groups), 'sourceHashes': 'resolved_only_from_actual_builder_output'}
    return locales, expected_groups, nodes, outputs


def freeze_locale_result(session, locales, expected_groups, outputs):
    specs = fresh.freeze_locale_inputs(session, locales)
    c.require(set(specs) == set(locales) and all(spec['groupPlan'] == expected_groups
        and spec['source'] == outputs['source']
        and spec['anchor'] == outputs['anchor'] for spec in specs.values()),
        'fresh_engine_declared_output_membership_changed')
    files = {path: source._sha(path) for spec in specs.values()
        for key, path in spec.items() if key in {'source', 'anchor', 'policy', 'rubric', 'pluginPath'}}
    return {'schemaVersion': 'sermon-fresh-locale-freeze-result-v1', 'specs': specs,
        'inputFiles': files, 'sourceContextSha256': c.canonical_sha256(session.context), **QUALIFICATIONS}


class FreshSourceDAG:
    def __init__(self, session, recipe, authorization, locale_drafts):
        self.stages = stages.FreshSourceStages(session, recipe, authorization)
        self.session = session
        self.locales, self.expected_groups, self.nodes, outputs = source_declaration(session, self.stages, locale_drafts)
        self.binding = {'schemaVersion': SCHEMA, 'sourceStageBinding': deepcopy(self.stages.binding),
            'sourcePlanSha256': c.canonical_sha256(session.plan),
            'productionRunId': session.subject.config['runId'], 'nodes': deepcopy(self.nodes),
            'recipe': deepcopy(self.stages.frozen_recipe), 'localeDrafts': deepcopy(self.locales),
            'inputFiles': {value: source._sha(value) for files in self.locales.values() for value in files.values()},
            'declaredOutputs': outputs,
            'codeFiles': accounting.execution_identity()['loadedProjectCodeSha256'],
            'engine': {'name': 'prefect', 'version': version('prefect'), 'maxWorkers': 1, 'retries': 0, 'cache': False},
            'permissions': {'syntheticProviderTransport': True, 'realProviderCalls': False, 'mfaExecution': False,
                'textOrTTSDispatch': False, 'humanApproval': False, 'productionWrites': False}, **QUALIFICATIONS}
        self.plan_sha256 = c.canonical_sha256(self.binding)
        self.root = _safe_path(session.root/'fresh-source-prefect'/self.plan_sha256, recursive=True)
        self.invocation = uuid.uuid4().hex
        self.observations, self.results, self.task_ids = {}, {}, {}
        self.prior_dispatches = len(session.transport.observations)
        self.stream = None

    def _check(self):
        c.require(c.canonical_sha256(self.binding) == self.plan_sha256 and self.nodes == self.binding['nodes']
            and self.stages.session is self.session and self.stages.binding == self.binding['sourceStageBinding']
            and self.root == _safe_path(self.session.root/'fresh-source-prefect'/self.plan_sha256, recursive=True)
            and self.locales == self.binding['localeDrafts'] and self.expected_groups == _groups(self.stages.recipe)
            and all(source._sha(path) == digest for path, digest in self.binding['inputFiles'].items())
            and all(source._sha(mock.diagnostic.pilot.REPO/path) == digest for path, digest in self.binding['codeFiles'].items()),
            'fresh_engine_frozen_plan_changed')
        if (self.root/'plan.json').exists():
            c.require(public.read_snapshot(self.root/'plan.json')[0] == self.binding, 'fresh_engine_saved_plan_changed')

    def freeze(self):
        self._check()
        mock._save(self.root/'plan.json', self.binding)
        self.stream = durable.open_stream(self.root/'accounting', scope_id='fresh-source-engine',
            plan_sha256=self.plan_sha256, production_run_id=self.session.subject.config['runId'],
            purpose='fresh_source_synthetic_stages', create=True)

    def _transition(self, node, state, reason):
        try:
            return self._write_transition(node, state, reason)
        except Exception as exc:
            raise accounting.AccountingWriteError('fresh_engine_transition_write_failed') from exc

    def _write_transition(self, node, state, reason):
        attempt = self.invocation+'.'+node['id']
        events, errors = accounting.read_events(self.stream.directory)
        c.require(not errors, 'fresh_engine_controller_log_damaged')
        rows = {r['eventId']: r for r in events if r.get('event') == 'step_state_changed'
            and r.get('runId') == self.stream.run_id and r.get('attemptId') == attempt}
        previous = max(rows.values(), key=lambda row: row['sequence']) if rows else None
        before = previous['toState'] if previous else None
        revision = c.canonical_sha256([self.plan_sha256, self.invocation, node['id'], before, state])
        return self.stream.write({'event': 'step_state_changed', 'stepId': node['id'],
            'fromState': before, 'toState': state, 'stateRevision': revision, 'reasonCode': reason},
            context={'workUnitId': node['id'], 'attemptId': attempt},
            delivery_key='state.'+c.canonical_sha256([attempt, state]), intent={'stateRevision': revision})

    def _locale(self):
        return freeze_locale_result(self.session, self.locales, self.expected_groups, self.binding['declaredOutputs'])

    def execute(self, node_id, upstream):
        node = next(row for row in self.nodes if row['id'] == node_id)
        result = {'nodeId': node_id, 'status': 'blocked', 'readyForDownstream': False,
            'completion': None, **QUALIFICATIONS}
        started = False
        try:
            self._check()
            c.require(type(upstream) is list and len(upstream) == len(node['dependsOn'])
                and all(value == self.observations[key] for key, value in zip(node['dependsOn'], upstream)),
                'fresh_engine_upstream_result_changed')
            if not all(value['readyForDownstream'] for value in upstream):
                result['reason'] = 'upstream_not_completed'
            else:
                dependencies = [value['completion']['spanId'] for value in upstream]
                _, events = completion.current_events()
                for value in upstream:
                    completion.validate_synthetic(value['completion'], events,
                        production_run_id=self.session.subject.config['runId'])
                self._transition(node, 'pending', 'engine_task_entered')
                self._transition(node, 'ready', 'upstream_verified')
                self._transition(node, 'running', 'fixed_stage_entered')
                started = True
                with profile.context(workKind='production'):
                    if node['stage'] == 'localeFreeze':
                        payload = self._locale()
                        actual = self.results['source.package']['causality']['handles']['sourcePackage']
                    else:
                        prior = self.results[node['dependsOn'][0]] if node['dependsOn'] else None
                        payload = self.stages.execute(node['stage'], prior)
                        actual = payload['causality']['handles'][node['stage']]
                digest = c.canonical_sha256(payload)
                job, revision = c.canonical_sha256([self.plan_sha256, node_id]), c.canonical_sha256([node_id, digest])
                with profile.context(jobId=job, revisionId=revision):
                    with accounting.stage_outcome('fresh_engine.result_validation', work_unit_id=node_id,
                            attempt_id=self.invocation+'.'+node_id,
                            depends_on=list(dict.fromkeys(dependencies+[actual['spanId']]))) as span:
                        mock._save(self.root/'results'/node_id/(digest+'.json'), payload)
                        accounting.record_workload('fresh_engine.validated_result', {'resultSha256': digest,
                            'sourceStageFactSha256': actual['terminalFactSha256'], 'productionEligible': False})
                        span.finish('completed', artifact_sha256=digest)
                    proof = completion.capture_synthetic(span.span_id, production_run_id=self.session.subject.config['runId'],
                        artifact_sha256=digest, artifact_kind='control_receipt', job_id=job, revision_id=revision)
                self.results[node_id] = payload
                result.update(status='completed', readyForDownstream=True, resultSha256=digest, completion=proof)
                self._transition(node, 'succeeded', 'validated_stage_complete')
        except Exception as exc:
            if isinstance(exc, accounting.AccountingWriteError) or getattr(exc, 'sermon_logging_failed', False):
                raise
            try: snapshot = self.session.subject.snapshot()
            except Exception: snapshot = None
            failed = failure.receipt(exc, plan=self.session.plan, provider_snapshot=snapshot)
            status = ('outcome_unknown' if failed['requiresReconciliation'] else 'failed') if started else 'blocked'
            result.pop('resultSha256', None)
            result.update(status=status, readyForDownstream=False, completion=None,
                reason=failed['reasonCode'], failureReceipt=failed)
            if started:
                self._transition(node, status, 'stage_requires_reconciliation' if status == 'outcome_unknown' else 'stage_failed')
        self.observations[node_id] = result
        mock._save(self.root/'observations'/self.invocation/(node_id+'.json'), result)
        return result


def run(session, recipe, authorization, locale_drafts):
    dag = FreshSourceDAG(session, recipe, authorization, locale_drafts)
    with work_lock(dag.root):
        dag.freeze()
        home, database = mock.diagnostic.pilot.isolated_prefect_environment(dag.root)
        os.chdir(tempfile.mkdtemp(prefix='.prefect-config-', dir=dag.root))
        from prefect import flow, task
        from prefect.cache_policies import NO_CACHE
        from prefect.client.orchestration import get_client
        from prefect.context import get_run_context
        from prefect.settings import get_current_settings
        from prefect.task_runners import ThreadPoolTaskRunner
        settings = get_current_settings()
        c.require(settings.api.url is None and settings.api.key is None and settings.home == home
            and settings.server.database.connection_url.get_secret_value() == database
            and settings.results.local_storage_path == home/'storage'
            and settings.server.memo_store_path == home/'memo_store.toml'
            and not settings.server.analytics_enabled and not settings.cloud.enable_orchestration_telemetry,
            'fresh_engine_prefect_not_isolated')

        @task(retries=0, cache_policy=NO_CACHE, persist_result=False)
        def dispatch(node_id, upstream):
            ctx = get_run_context()
            node = next(row for row in dag.nodes if row['id'] == node_id)
            record = {'flowRunId': str(ctx.task_run.flow_run_id), 'taskRunId': str(ctx.task_run.id),
                'taskInputs': mock._engine_inputs(ctx.task_run)}
            c.require(record['taskInputs'].get('upstream', []) == sorted(dag.task_ids[key] for key in node['dependsOn']),
                'fresh_engine_dependency_changed')
            dag.task_ids[node_id] = record['taskRunId']
            mock._save(dag.root/'engine'/dag.invocation/(node_id+'.json'), record)
            return dag.execute(node_id, upstream)

        @flow(name='sermon-fresh-source-stages', retries=0, persist_result=False,
            task_runner=ThreadPoolTaskRunner(max_workers=1))
        def orchestrate():
            futures = {}
            for node in dag.nodes:
                futures[node['id']] = dispatch.with_options(name=node['id']).submit(
                    node['id'], [futures[key] for key in node['dependsOn']])
            return {key: value.result() for key, value in futures.items()}

        with dag.stream.context(), accounting.accounting_session(dag.root/'accounting', 'fresh_source_engine_invocation',
                {'planSha256': dag.plan_sha256, 'invocationId': dag.invocation}):
            dag.stages.freeze()
            observations = orchestrate()
            engine = {}
            with get_client(sync_client=True) as client:
                for node in dag.nodes:
                    task_run = client.read_task_run(uuid.UUID(dag.task_ids[node['id']]))
                    record = public.read_snapshot(dag.root/'engine'/dag.invocation/(node['id']+'.json'))[0]
                    c.require(str(task_run.id) == record['taskRunId'] and str(task_run.flow_run_id) == record['flowRunId']
                        and mock._engine_inputs(task_run) == record['taskInputs'] and task_run.state.is_completed()
                        and task_run.run_count == 1 and task_run.empirical_policy.retries == 0,
                        'fresh_engine_persisted_evidence_changed')
                    engine[node['id']] = {**record, 'engineState': task_run.state.name,
                        'timestamps': mock._engine_timing(task_run, client.read_task_run_states(task_run.id))}
            final = {'schemaVersion': SCHEMA, 'planSha256': dag.plan_sha256, 'invocationId': dag.invocation,
                'status': 'synthetic_source_complete' if observations['locale.freeze']['readyForDownstream'] else 'incomplete',
                'nodes': observations, 'engineEvidence': engine,
                'syntheticProviderDispatches': len(session.transport.observations)-dag.prior_dispatches,
                'realProviderCalls': 0, 'newMFACalls': 0, 'textOrTTSDispatches': 0, **QUALIFICATIONS}
        mock._save(dag.root/'runs'/(dag.invocation+'.json'), final)
        return final
