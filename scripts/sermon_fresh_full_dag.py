"""One frozen synthetic Fresh Source→strict text→durable mock-TTS Prefect graph.

All executable nodes and memberships are declared before Source intake. Existing
business ledgers own receipts, reuse and explicit bounded retry. Layer 4 is a
read-only synthetic projection, never publication or human acceptance.
"""
from copy import deepcopy
from importlib.metadata import version
import os
from pathlib import Path
import tempfile
import uuid

from scripts import sermon_accounting as accounting
from scripts import sermon_completion as completion
from scripts import sermon_durable_accounting as durable
from scripts import sermon_fresh_diagnostic as fresh
from scripts import sermon_fresh_source_prefect as source_engine
from scripts import sermon_fresh_source_stages as stages
from scripts import sermon_log_contract as log
from scripts import sermon_logs as logs
from scripts import sermon_mock_tts_contract as contract
from scripts import sermon_mock_tts_dag as mock
from scripts import sermon_public_snapshot as public
from scripts import sermon_review_contracts as c
from scripts import sermon_review_observation as _review_observation  # preload summary-consumer closure
from scripts import sermon_source_failure as failure
from scripts.sermon_execution_harness import work_lock
from scripts.sermon_release_workflow import _safe_path

SCHEMA = 'sermon-fresh-full-dag-v1'
QUALIFICATIONS = {**mock.QUALIFICATIONS, 'downstreamEngineTakeover': True,
    'engineScope': 'synthetic_fresh_source_strict_text_mock_audio_readonly_final'}
PERMISSIONS = {**mock.PERMISSIONS, 'sourceRerun': False, 'freshSourceSyntheticDispatch': True,
    'mfaExecution': False, 'syntheticProviderTransport': True}


def _units(locales, groups):
    units = {locale+'.'+group['translationGroupId']: {'unitId': locale+'.'+group['translationGroupId'],
        'targetLocale': locale, 'translationGroupId': group['translationGroupId'],
        'sourceUnitIds': deepcopy(group['sourceUnitIds']), 'groupPlanSha256': c.canonical_sha256(group)}
        for locale in sorted(locales) for group in groups}
    c.require(1 <= len(units) <= contract.MAX_TESTED_UNITS and all(contract.label(key) and len(key) <= 80 for key in units),
        'fresh_full_unit_limit')
    return units


def _graph(source_nodes, units):
    prefix = [{**deepcopy(node), 'operation': 'fresh_source' if node['stage'] != 'localeFreeze' else 'locale_freeze',
        'locale': None, 'unitId': None} for node in source_nodes]
    return prefix + mock._graph(units, source_node='locale.freeze')[1:]


def _layers(nodes):
    return {node['id']: (1 if node['operation'] == 'fresh_source' else
        2 if node['operation'] in {'locale_freeze', 'text'} else
        4 if node['operation'] in {'join', 'final'} else 3) for node in nodes}


class FullFreshDAG(mock.MockTTSDAG):
    """Reuse trusted single-node operations; never start a nested DAG or stream."""
    def __init__(self, session, recipe, authorization, locale_drafts, config, *, recovery=None):
        self.session = session
        self.stages = stages.FreshSourceStages(session, recipe, authorization)
        self.locales, self.expected_groups, self.source_nodes, outputs = source_engine.source_declaration(
            session, self.stages, locale_drafts)
        c.require(type(config) is dict and set(config) == {'schemaVersion', 'mockPolicy', 'faults'}
            and config['schemaVersion'] == SCHEMA and c._strict_json(config), 'fresh_full_config_invalid')
        self.units = _units(self.locales, self.expected_groups)
        self.policy, self.faults = mock.policy_and_faults(self.units, config)
        self.nodes = _graph(self.source_nodes, self.units)
        self.fixture_root = _safe_path(session.root)
        outputs.update(localeCandidates={locale: {
            'root': str(session.root/'locales'/locale/'machine-candidates'),
            'identity': 'strict_candidate_hash_from_actual_reviewed_groups',
            'artifact': 'candidate.json'} for locale in self.locales},
            mockJobs={'rootRelativeToPlan': 'mock-control', 'unitIds': list(self.units),
                'artifact': 'fixture.wav', 'format': 'PCM_S16LE_WAV', 'sampleRate': 16000,
                'channels': 1, 'frames': 2400, 'content': 'deterministic_synthetic_fixture_only'},
            readonlyFinal={'rootRelativeToPlan': 'results/final.readonly',
                'schemaVersion': 'sermon-fresh-full-final-v1', 'releasePackageCreated': False})
        self.binding = {'schemaVersion': SCHEMA, 'scope': 'fresh_source_to_synthetic_readonly_final',
            'sourceStageBinding': deepcopy(self.stages.binding), 'sourcePlanSha256': c.canonical_sha256(session.plan),
            'productionRunId': session.subject.config['runId'], 'recipe': deepcopy(self.stages.frozen_recipe),
            'localeDrafts': deepcopy(self.locales),
            'inputFiles': {path: source_engine.source._sha(path) for files in self.locales.values() for path in files.values()},
            'declaredOutputs': outputs, 'units': deepcopy(self.units), 'nodes': deepcopy(self.nodes),
            'logicalLayers': {'nodes': _layers(self.nodes), 'mappingMethod': 'canonical_span_work_unit_and_parent_ancestry',
                'sourceStages': deepcopy(source_engine.NAMES),
                'workerUnitIds': list(self.units), 'layer4Scope': 'synthetic_readonly_projection'},
            'permissions': deepcopy(PERMISSIONS), 'graphLimits': {'maxUnits': contract.MAX_TESTED_UNITS,
                'maxLocaleUnits': contract.MAX_TESTED_UNITS, 'maxDependencies': 64,
                'scalabilityQualification': 'two_unit_offline_acceptance_only'},
            'mockPolicy': deepcopy(self.policy), 'faults': deepcopy(self.faults),
            'codeFiles': mock._code_files(), 'mockImplementationSha256': contract.implementation_sha256(),
            'engine': {'name': 'prefect', 'version': version('prefect'), 'maxWorkers': 1,
                'retries': 0, 'cache': False, 'persistResult': False},
            'recovery': {'automaticRetry': False, 'explicitRetry': 'same_input_confirmed_worker_failed_only',
                'selection': 'unitId_to_exact_prior_request_sha256', 'retryFaultChange': 'mode_only_to_none',
                'bounds': 'frozen_mock_policy', 'normalResume': 'original_source_text_and_job_receipt_revalidation'},
            **QUALIFICATIONS}
        self.plan_sha256 = c.canonical_sha256(self.binding)
        self.root = _safe_path(session.root/'fresh-full-dag'/self.plan_sha256, recursive=True)
        self.invocation = uuid.uuid4().hex
        self.recovery = deepcopy({} if recovery is None else recovery)
        c.require(type(self.recovery) is dict and set(self.recovery) <= set(self.units)
            and all(contract.sha(value) for value in self.recovery.values()), 'mock_dag_recovery_selection_invalid')
        self.invocation_binding = {'schemaVersion': 'sermon-fresh-full-invocation-v1',
            'invocationId': self.invocation, 'planSha256': self.plan_sha256,
            'recoveryRequests': deepcopy(self.recovery), **QUALIFICATIONS}
        self.results, self.observations, self.task_ids = {}, {}, {}
        self.stream, self.client = None, None
        self._reliability_failure = None
        self.prior_synthetic_dispatches = len(session.transport.observations)
        self.prior_api_events = set()

    def _production_run_id(self):
        return self.session.subject.config['runId']

    def _check(self):
        c.require(c.canonical_sha256(self.binding) == self.plan_sha256
            and self.nodes == self.binding['nodes'] == _graph(self.source_nodes, self.units)
            and self.units == self.binding['units'] == _units(self.locales, self.expected_groups)
            and self.locales == self.binding['localeDrafts']
            and self.expected_groups == source_engine._groups(self.stages.recipe)
            and self.stages.session is self.session and self.stages.binding == self.binding['sourceStageBinding']
            and self.stages.frozen_recipe == self.binding['recipe']
            and c.canonical_sha256(self.stages.authorization) == self.binding['recipe']['authorizationSha256']
            and self.policy == self.binding['mockPolicy'] and self.faults == self.binding['faults']
            and self.binding['permissions'] == PERMISSIONS and self._production_run_id() == self.binding['productionRunId']
            and c.canonical_sha256(self.session.plan) == self.binding['sourcePlanSha256']
            and self.binding['logicalLayers']['nodes'] == _layers(self.nodes)
            and self.binding['mockImplementationSha256'] == contract.implementation_sha256(),
            'fresh_full_frozen_plan_changed')
        c.require(self.recovery == self.invocation_binding['recoveryRequests']
            and self.invocation_binding['invocationId'] == self.invocation
            and self.invocation_binding['planSha256'] == self.plan_sha256, 'mock_dag_invocation_changed')
        c.require(all(source_engine.source._sha(path) == digest for path, digest in self.binding['inputFiles'].items())
            and all(source_engine.source._sha(row['path']) == row['sha256'] for row in self.binding['recipe']['files'].values())
            and all(mock.diagnostic._hash_file(mock.diagnostic.pilot.REPO/name) == digest
                for name, digest in self.binding['codeFiles'].items()), 'fresh_full_input_or_code_changed')
        c.require(self.root == _safe_path(self.session.root/'fresh-full-dag'/self.plan_sha256, recursive=True)
            and self.fixture_root == _safe_path(self.session.root), 'fresh_full_scope_changed')
        for path, expected in ((self.root/'plan.json', self.binding),
            (self.root/'invocations'/(self.invocation+'.json'), self.invocation_binding),
            (self.root/'layer-map.json', self.layer_plan())):
            if path.exists(): c.require(public.read_snapshot(path)[0] == expected, 'fresh_full_saved_plan_changed')

        # Fresh identity/admission stays live at every downstream boundary,
        # including job submission and final byte/gate admission.
        if self.session.context is not None:
            self.session._check()

    def layer_plan(self):
        return {'schemaVersion': 'sermon-fresh-full-layer-map-v1', 'planSha256': self.plan_sha256,
            'productionRunId': self._production_run_id(), 'mapping': deepcopy(self.binding['logicalLayers']), **QUALIFICATIONS}

    def freeze(self):
        self._check()
        mock._save(self.root/'plan.json', self.binding)
        mock._save(self.root/'layer-map.json', self.layer_plan())
        mock._save(self.root/'invocations'/(self.invocation+'.json'), self.invocation_binding)
        self.stream = durable.open_stream(self.root/'accounting', scope_id='fresh-full-dag',
            plan_sha256=self.plan_sha256, production_run_id=self._production_run_id(),
            purpose='fresh_full_synthetic_graph', create=True)

    def activate(self):
        super().activate()
        self.stages.freeze()
        events, errors = accounting.read_events(self.stream.directory)
        c.require(not errors, 'fresh_full_log_damaged')
        self.prior_api_events = {row['eventId'] for row in events if row['event'] == 'api_attempt'}

    def _locale_spec(self, locale):
        self.session._check()
        result = self.results['locale.freeze']
        specs = result['specs']
        c.require(set(specs) == set(self.locales) and all(spec['groupPlan'] == self.expected_groups
            for spec in specs.values()) and result['sourceContextSha256'] == c.canonical_sha256(self.session.context)
            and all(source_engine.source._sha(path) == digest for path, digest in result['inputFiles'].items()),
            'fresh_full_locale_outputs_changed')
        spec = specs[locale]
        c.require(public.read_snapshot(self.binding['declaredOutputs']['localeSpecs'][locale])[0] == spec,
            'fresh_full_locale_spec_changed')
        return spec

    def _validate_callback(self, operation, locale, result):
        c.require(operation == 'locale', 'fresh_full_existing_source_forbidden')
        # This pure validator uses fixture_root/session only; no continuation DAG
        # is constructed, frozen or executed after Source has run.
        return mock.diagnostic.DiagnosticDAG._validate(self, operation, locale, result)

    _transition = source_engine.FreshSourceDAG._transition
    _write_transition = source_engine.FreshSourceDAG._write_transition

    def _execute_source(self, node, upstream):
        observed = {'nodeId': node['id'], 'operation': node['operation'], 'unitId': None,
            'executionStatus': 'blocked', 'readyForDownstream': False, 'completionHandles': [],
            'processed': False, **QUALIFICATIONS}
        started = False
        with mock.diagnostic._LOCK:
            if self._reliability_failure is not None: raise self._reliability_failure
            try:
                self._check()
                parents = self._parents(node, upstream)
                if any(not row['readyForDownstream'] for row in parents):
                    observed['reason'] = 'upstream_not_completed'
                else:
                    spans = [handle['spanId'] for row in parents for handle in row['completionHandles']]
                    self._transition(node, 'pending', 'engine_task_entered')
                    self._transition(node, 'ready', 'upstream_verified')
                    self._transition(node, 'running', 'fixed_stage_entered')
                    started = True
                    with accounting.stage('full_dag.source_operation', work_unit_id=node['id']+'.operation',
                            depends_on=spans, executor_type='deterministic_program'):
                        with mock.profile.context(workKind='production'):
                            if node['stage'] == 'localeFreeze':
                                result = {**source_engine.freeze_locale_result(self.session, self.locales,
                                    self.expected_groups, self.binding['declaredOutputs']), **QUALIFICATIONS}
                                actual = self.results['source.package']['causality']['handles']['sourcePackage']
                            else:
                                prior = self.results[node['dependsOn'][0]] if node['dependsOn'] else None
                                result = self.stages.execute(node['stage'], prior)
                                actual = result['causality']['handles'][node['stage']]
                    # Preserve the actual V1 Source leaf. The distinct V2 leaf
                    # proves only result validation/persistence at this boundary.
                    handle = self._control_leaf(node, result, spans+[actual['spanId']])
                    self._transition(node, 'succeeded', 'validated_stage_complete')
                    self.results[node['id']] = result
                    observed.update(executionStatus='completed', readyForDownstream=True,
                        processed=True, resultSha256=c.canonical_sha256(result), completionHandles=[handle],
                        sourceCompletion=actual)
            except Exception as exc:
                if isinstance(exc, accounting.AccountingWriteError) or getattr(exc, 'sermon_logging_failed', False):
                    self._reliability_failure = exc
                    raise
                try: snapshot = self.session.subject.snapshot()
                except Exception: snapshot = None
                failed = failure.receipt(exc, plan=self.session.plan, provider_snapshot=snapshot)
                status = ('outcome_unknown' if failed['requiresReconciliation'] else 'failed') if started else 'blocked'
                observed.update(executionStatus=status, readyForDownstream=False, completionHandles=[],
                    processed=None if status == 'outcome_unknown' else started,
                    reason=failed['reasonCode'], failureReceipt=failed)
                if started: self._transition(node, status, 'stage_requires_reconciliation' if
                    status == 'outcome_unknown' else 'stage_failed')
            self.observations[node['id']] = observed
            mock._save(self.root/'observations'/self.invocation/node['id'], observed)
            return observed

    def execute(self, node_id, upstream):
        node = next((row for row in self.nodes if row['id'] == node_id), None)
        c.require(node is not None, 'fresh_full_node_not_authorized')
        if node['operation'] in {'fresh_source', 'locale_freeze'}: return self._execute_source(node, upstream)
        return super().execute(node_id, upstream)

    def _before_operation(self, node, parents):
        if node['operation'] not in {'submit', 'verify', 'gate', 'join', 'final'}:
            return
        selected = ([node['unitId']] if node['unitId'] is not None else
            [key for key, row in self.units.items() if node['locale'] is None or row['targetLocale'] == node['locale']])
        candidates = {}
        for unit_id in selected:
            member = self.units[unit_id]
            locale = member['targetLocale']
            if locale not in candidates:
                candidates[locale] = self._candidate(locale)
            input_node = next(row for row in self.nodes if row['id'] == 'mock.input.'+unit_id)
            unit, binding = self._derive_input(input_node, candidate=candidates[locale])
            original = self.results[input_node['id']]
            request, _ = self._request(unit_id)
            c.require(unit == original['unit'] and binding == original['inputBinding']
                and all(request[key] == value for key, value in unit.items()),
                'fresh_full_current_text_input_changed')

    def _final_result(self, expected):
        return {'schemaVersion': 'sermon-fresh-full-final-v1', 'status': 'synthetic_complete',
            'planSha256': self.plan_sha256, 'expectedLocales': expected,
            'sourceResultSha256': c.canonical_sha256(self.results['source.package']),
            'localeFreezeSha256': c.canonical_sha256(self.results['locale.freeze']),
            'localeJoinSha256': {locale: c.canonical_sha256(self.results['join.'+locale]) for locale in expected},
            'formalAudioPackageCreated': False, 'releasePackageCreated': False,
            'realProviderCalls': 0, 'realModelCalls': 0, 'newMFACalls': 0, **QUALIFICATIONS}

    def layer_evidence(self):
        events, errors = accounting.read_events(self.stream.directory)
        c.require(not errors, 'fresh_full_log_damaged')
        c.require(bool(events) and all(row['runId'] == self.stream.run_id
            and row.get('productionRunId') == self._production_run_id()
            and row.get('evidenceMode') == 'synthetic' for row in events),
            'fresh_full_log_scope_changed')
        integrity = log.replay_integrity(events)
        c.require(integrity['status'] == 'consistent', 'fresh_full_log_inconsistent')
        starts = {row['spanId']: row for row in events if row['event'] == 'stage_started'}
        workflows = {row['workflowId']: row for row in events if row['event'] == 'workflow_started'}
        containers = {span: {'spanId': span, 'runId': row['runId'], 'workflowId': row['workflowId'],
            'workUnitId': None, 'stage': row['stage'], 'layer': None,
            'measurementScope': 'containing_workflow_all_layers_do_not_sum_with_children'}
            for span, row in starts.items() if row.get('workUnitId') is None
            and row.get('parentSpanId') is None and row.get('workflowId') in workflows
            and row['stage'] == workflows[row['workflowId']]['workflow']}
        mapping, unresolved = {}, []
        layers = self.binding['logicalLayers']['nodes']
        def owner(span, seen=()):
            if span in mapping: return mapping[span]
            if span in seen or span not in starts: return None
            row = starts[span]; work = row.get('workUnitId') or ''
            direct = next((key for key in layers if work in {key, key+'.callback', key+'.operation'}), None)
            if direct is None:
                unit = next((key for key in self.units if work == key or work.startswith(key+'.')), None)
                if unit is not None:
                    phase = {'input_verified': 'input', 'dispatch': 'submit', 'observe': 'observe',
                        'verify': 'verify', 'gate': 'gate'}.get(row['stage'].removeprefix('mock_tts.'), 'submit')
                    direct = 'mock.'+phase+'.'+unit
            if direct is None:
                inherited = owner(row.get('parentSpanId'), (*seen, span))
                if inherited is None: return None
                direct = inherited['ownerNodeId']
            mapping[span] = {'spanId': span, 'runId': row['runId'], 'workUnitId': row.get('workUnitId'),
                'stage': row['stage'], 'layer': layers[direct], 'ownerNodeId': direct}
            return mapping[span]
        for span in starts:
            if span not in containers and owner(span) is None: unresolved.append(span)
        c.require(not unresolved, 'fresh_full_layer_mapping_incomplete')
        result = {'schemaVersion': 'sermon-fresh-full-layer-evidence-v1', 'planSha256': self.plan_sha256,
            'invocationId': self.invocation, 'declaredNodes': deepcopy(layers),
            'spans': [mapping[key] for key in sorted(mapping)],
            'containerSpans': [containers[key] for key in sorted(containers)], 'unmappedSpanIds': unresolved,
            'mappingScope': 'cumulative_original_canonical_spans_once', **QUALIFICATIONS}
        return result

    def accounting_projection(self):
        events, errors = accounting.read_events(self.stream.directory)
        c.require(not errors, 'fresh_full_log_damaged')
        event_integrity = accounting.profile_integrity(events)
        receipt_integrity = accounting.receipt_integrity(events, event_integrity=event_integrity)
        c.require(event_integrity['status'] == 'consistent' and not receipt_integrity['conflicts'],
            'fresh_full_accounting_inconsistent')
        calls = [row for row in events if row['event'] == 'api_attempt' and id(row) in receipt_integrity['_selected']]
        summary = accounting.summarize(self.stream.directory)
        run = next(row for row in summary['runs'] if row['runId'] == self.stream.run_id)
        c.require(run['apiAttempts'] == len(calls), 'fresh_full_direct_call_double_count')
        layer = self.layer_evidence()
        span_layers = {row['spanId']: row['layer'] for row in layer['spans']}
        by_layer = {str(i): sum(span_layers.get(row['spanId']) == i for row in calls) for i in range(1, 5)}
        c.require(sum(by_layer.values()) == len(calls) and by_layer['3'] == by_layer['4'] == 0,
            'fresh_full_provider_layer_changed')
        inspected = logs.inspect_logs(self.stream.directory, run_id=self.stream.run_id, tail=1)
        return {'schemaVersion': 'sermon-fresh-full-accounting-projection-v1', 'planSha256': self.plan_sha256,
            'canonicalRunId': self.stream.run_id, 'replayIntegrity': event_integrity['status'],
            'receiptIntegrity': summary['receiptIntegrity']['status'],
            'canonicalDirectApiAttempts': len(calls),
            'invocationDirectApiAttempts': sum(row['eventId'] not in self.prior_api_events for row in calls),
            'directCallsByLayer': by_layer, 'realProviderCalls': 0, 'summaryApiAttempts': run['apiAttempts'],
            'logInspectionStatus': inspected['status'], 'sourceLedgerSha256': summary['sourceLedgerSha256'],
            'mockTTS': {'inputTokens': None, 'outputTokens': None, 'estimatedUsd': None,
                'usageStatus': 'not_applicable', 'costStatus': 'not_applicable'}, **QUALIFICATIONS}


def run(session, recipe, authorization, locale_drafts, config, *, recovery=None):
    dag = FullFreshDAG(session, recipe, authorization, locale_drafts, config, recovery=recovery)
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
            'fresh_full_prefect_not_isolated')

        @task(retries=0, cache_policy=NO_CACHE, persist_result=False)
        def dispatch(node_id, upstream):
            ctx = get_run_context(); node = next(row for row in dag.nodes if row['id'] == node_id)
            record = {'flowRunId': str(ctx.task_run.flow_run_id), 'taskRunId': str(ctx.task_run.id),
                'taskInputs': mock._engine_inputs(ctx.task_run)}
            c.require(record['taskInputs'].get('upstream', []) == sorted(dag.task_ids[key] for key in node['dependsOn']),
                'fresh_full_engine_dependency_changed')
            dag.task_ids[node_id] = record['taskRunId']
            mock._save(dag.root/'engine'/dag.invocation/(node_id+'.json'), record)
            return dag.execute(node_id, upstream)

        @flow(name='sermon-fresh-full-synthetic', retries=0, persist_result=False,
            task_runner=ThreadPoolTaskRunner(max_workers=1))
        def orchestrate():
            futures = {}
            for node in dag.nodes:
                futures[node['id']] = dispatch.with_options(name=node['id']).submit(
                    node['id'], [futures[key] for key in node['dependsOn']])
            return {key: value.result() for key, value in futures.items()}

        with dag.stream.context(), accounting.accounting_session(dag.root/'accounting', 'fresh_full_dag_invocation') as invocation:
            dag.activate()
            results = orchestrate()
            persisted = {}
            with get_client(sync_client=True) as client:
                for node in dag.nodes:
                    task_run = client.read_task_run(uuid.UUID(dag.task_ids[node['id']]))
                    record = public.read_snapshot(dag.root/'engine'/dag.invocation/(node['id']+'.json'))[0]
                    c.require(str(task_run.id) == record['taskRunId'] and str(task_run.flow_run_id) == record['flowRunId']
                        and mock._engine_inputs(task_run) == record['taskInputs'] and task_run.state.is_completed()
                        and task_run.run_count == 1 and task_run.empirical_policy.retries == 0,
                        'fresh_full_persisted_engine_evidence_changed')
                    persisted[node['id']] = {**record, 'engineState': task_run.state.name,
                        'timestamps': mock._engine_timing(task_run, client.read_task_run_states(task_run.id))}
            edges = dag.observed_edges()
        final = {'schemaVersion': SCHEMA, 'planSha256': dag.plan_sha256, 'invocationId': dag.invocation,
            'status': 'synthetic_complete' if results['final.readonly']['readyForDownstream'] else 'incomplete',
            'nodes': results, 'engineEvidence': persisted, 'engine': dag.binding['engine'],
            'observedEdges': edges, 'engineGraphVerified': True,
            'syntheticProviderDispatches': len(session.transport.observations)-dag.prior_synthetic_dispatches,
            'realProviderCalls': 0, 'realModelCalls': 0, 'newMFACalls': 0,
            'newMockDispatches': sum(dag.results.get(node['id'], {}).get('newDispatch') is True
                for node in dag.nodes if node['operation'] == 'submit'),
            'unknownDispatchAcknowledgements': sum(dag.results.get(node['id'], {}).get('newDispatch', False) is None
                for node in dag.nodes if node['operation'] == 'submit'),
            'finalProjection': dag.results.get('final.readonly'),
            'layerEvidence': dag.layer_evidence(), 'accountingProjection': dag.accounting_projection(),
            'invocationAccounting': {'workflowId': invocation['workflowId'],
                'timingSource': 'canonical_workflow_started_and_finished',
                'scope': 'complete_flow_after_frozen_plan_including_source_text_mock_and_validation'},
            'timingCoverage': mock.timing_coverage(), **QUALIFICATIONS}
        mock._save(dag.root/'layer-evidence'/(dag.invocation+'.json'), final['layerEvidence'])
        mock._save(dag.root/'accounting-projections'/(dag.invocation+'.json'), final['accountingProjection'])
        mock._save(dag.root/'runs'/(dag.invocation+'.json'), final)
        return final
