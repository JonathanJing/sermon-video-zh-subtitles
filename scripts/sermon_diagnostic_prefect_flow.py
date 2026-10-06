"""Local Prefect continuation of an existing diagnostic's original store.

Fixed graph: inspect saved source -> strict locale -> speculative preview ->
read-only delivery inspection. No ASR/source rerun, approvals, new budget, or
production release switch. Existing business ledgers own recovery.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace

from scripts import sermon_accounting as accounting
from scripts import sermon_historical_identity as historical_identity
from scripts import sermon_dag_evidence as dag_evidence
from scripts import sermon_bounded_business_callbacks as offline
from scripts import sermon_diagnostic_preview_worker as preview_worker
from scripts import sermon_log_profile as profile
from scripts import sermon_prefect_dag as pilot
from scripts import sermon_public_snapshot as public
from scripts import sermon_review_contracts as c
from scripts import sermon_strict_layer2 as strict
from scripts.sermon_execution_harness import work_lock
from scripts.sermon_release_workflow import _safe_path

SCHEMA = 'sermon-diagnostic-prefect-flow-v1'
LOCALES = frozenset({'zh-Hans', 'ko', 'es'})
_LOCK = threading.Lock()  # Callback guards affect process-global sockets.


def _session_class():
    from scripts.sermon_diagnostic_dag_session import DiagnosticSession
    return DiagnosticSession


def _path(value):
    c.require(type(value) is str and Path(value).is_absolute(), 'diagnostic_flow_absolute_path_required')
    return _safe_path(value)


def _hash_file(path):
    path = _path(str(path))
    c.require(path.is_file(), 'diagnostic_flow_input_missing')
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _input_path(session, value, *, plugin=False):
    _path(value)  # Reject relative paths before the session canonicalizes them.
    return session._path(value, plugin=plugin)


def _references(session, value):
    paths = []
    if type(value) is list:
        for item in value: paths.extend(_references(session, item))
    elif type(value) is dict:
        for key, item in value.items():
            if key in {'path', 'checkpointPath'} and isinstance(item, str):
                path = _input_path(session, item)
                if path.is_file(): paths.append(path)
            else:
                paths.extend(_references(session, item))
    return paths


def _inventory(config, session):
    """Freeze named static inputs; candidate is owned by the locale producer."""
    paths = set()
    historical=session.binding.get('historicalLayer2Inputs')
    if historical is not None:
        paths.add(_input_path(session,historical['path']))
    native=session.binding.get('historicalNativeInputs')
    if native is not None:
        paths.add(_input_path(session,native['path']))
    for lane in config['locales'].values():
        spec, preview = lane['localeSpec'], lane['previewSpec']
        paths.update(_input_path(session, spec[key]) for key in ('source', 'anchor', 'policy', 'rubric'))
        paths.add(_input_path(session, spec['pluginPath'], plugin=True))
        paths.update(_input_path(session, value) for value in preview['paths'].values())
        paths.update(_input_path(session, preview[key]) for key in
                     ('checkpoint_map_path', 'operation_policies_path', 'strict_rubric_path'))
        for key in ('runtime_manifest_path','checkpoint_manifest_path','checkpoint_stage_declaration_path'):
            if key in preview:
                paths.add(_input_path(session, preview[key]))
        mapping = public.read_snapshot(_input_path(session, preview['checkpoint_map_path']))[0]
        for checkpoint in mapping.get('checkpoints', []):
            root = _input_path(session, checkpoint['path'])
            paths.update((root / 'model.safetensors', root / 'config.json'))
    # Validate nested original evidence paths before opening or hashing them.
    inspected = set()
    while paths - inspected:
        path = next(iter(paths - inspected)); inspected.add(path)
        if path.suffix == '.json':
            paths.update(_references(session, public.read_snapshot(path)[0]))
    return {str(path): _hash_file(path) for path in sorted(paths)}


def _config(config, session):
    root = _safe_path(session.root)
    c.require(type(config) is dict and set(config) == {'schemaVersion', 'locales'} and
              config['schemaVersion'] == SCHEMA and type(config['locales']) is dict and
              bool(config['locales']) and set(config['locales']) <= LOCALES,
              'diagnostic_flow_config_invalid')
    c.require(c._strict_json(config), 'diagnostic_flow_json_inputs_required')
    for locale, lane in config['locales'].items():
        c.require(type(lane) is dict and set(lane) == {'localeSpec', 'previewSpec'},
                  'diagnostic_flow_lane_invalid')
        spec, preview = lane['localeSpec'], lane['previewSpec']
        c.require(type(spec) is dict and set(spec) == {'source', 'anchor', 'policy', 'rubric',
            'graph', 'pluginPath', 'pluginSha256', 'groupPlan'}, 'diagnostic_flow_locale_spec_invalid')
        c.require(type(preview) is dict and preview_worker.REQUIRED <= set(preview) and
                  set(preview) <= preview_worker.REQUIRED | preview_worker.OPTIONS |
                  {'fixture_behavior', 'runtime_manifest_path', 'checkpoint_manifest_path', 'checkpoint_stage_declaration_path'} and
                  type(preview['execute']) is bool and preview['execute'] is (not session.offline_fixture), 'diagnostic_flow_preview_mode_changed')
        c.require(session.offline_fixture or 'runtime_manifest_path' in preview,
                  'diagnostic_flow_preview_runtime_manifest_required')
        c.require(not session.offline_fixture or 'runtime_manifest_path' not in preview,
                  'diagnostic_flow_fixture_cannot_claim_native_runtime')
        checkpoint_keys={'checkpoint_manifest_path','checkpoint_stage_declaration_path'}
        c.require(session.offline_fixture or checkpoint_keys <= set(preview),
                  'diagnostic_flow_preview_checkpoint_manifest_required')
        c.require(not session.offline_fixture or not checkpoint_keys & set(preview),
                  'diagnostic_flow_fixture_cannot_claim_checkpoint_manifest')
        for key in ('runtime_manifest_path',*sorted(checkpoint_keys)):
            if key in preview:
                _input_path(session, preview[key])
        c.require(type(preview['paths']) is dict and set(preview['paths']) ==
                  set(preview_worker.PATH_KEYS) - {'candidate'}, 'diagnostic_flow_candidate_owned_by_session')
        for key in ('source', 'anchor', 'policy', 'rubric'):
            _input_path(session, spec[key])
        _input_path(session, spec['pluginPath'], plugin=True)
        for value in preview['paths'].values(): _input_path(session, value)
        for key in ('checkpoint_map_path', 'operation_policies_path', 'strict_rubric_path'):
            _input_path(session, preview[key])
        out = _input_path(session, preview['out'])
        c.require(out.is_relative_to(root / 'diagnostic-previews' / locale),
                  'diagnostic_flow_preview_output_outside_run')
        for key in ('source', 'anchor', 'policy'):
            c.require(_path(spec[key]) == _path(preview['paths'][key]), 'diagnostic_flow_preview_inputs_changed')
        c.require(_path(spec['rubric']) == _path(preview['strict_rubric_path']),
                  'diagnostic_flow_preview_inputs_changed')
    for locale, lane in config['locales'].items():
        policy = public.read_snapshot(_input_path(session, lane['localeSpec']['policy']))[0]
        c.require(policy.get('targetLocale') == locale, 'diagnostic_flow_locale_mismatch')
    return json.loads(json.dumps(config))


class DiagnosticDAG:
    def __init__(self, session, config, *, resume_plan=None):
        from scripts.sermon_fresh_diagnostic import FreshDiagnosticSession
        c.require(type(session) in (_session_class(), FreshDiagnosticSession) and
                  (not session.offline_fixture or type(session.subject.executor) is offline.OfflineHTTPTransport),
                  'diagnostic_flow_offline_session_required')
        self.session = session
        self.fixture_root = _safe_path(session.root)
        self.config = _config(config, session)
        self.locales = tuple(sorted(self.config['locales']))
        self.binding = {'schemaVersion': SCHEMA, 'sessionBinding': session.binding,
            'config': self.config, 'inputFiles': _inventory(self.config, session),
            'codeSha256': _hash_file(Path(__file__).resolve()),
            'maxWorkers': 1, 'retries': 0, 'prefectCache': False,
            'evidenceMode': session.evidence_mode, 'humanAcceptance': 'pending', 'productionEligible': False}
        self._migration = None
        if resume_plan is not None:
            resume_plan = _path(str(resume_plan))
            old, _ = public.read_snapshot(resume_plan)
            c.require(type(old) is dict and type(old.get('sessionBinding')) is dict,
                      'diagnostic_flow_resume_plan_invalid')
            old_sha256 = c.canonical_sha256(old)
            c.require(resume_plan.name == 'plan.json' and resume_plan.parent ==
                      self.fixture_root / 'diagnostic-prefect' / old_sha256,
                      'diagnostic_flow_resume_plan_path_invalid')
            previous = old.get('sessionBinding', {})
            current = self.binding['sessionBinding']
            c.require(previous.get('schemaVersion') == 'sermon-diagnostic-dag-session-v1'
                      and current.get('schemaVersion') == 'sermon-diagnostic-dag-session-v2',
                      'diagnostic_flow_session_migration_version_invalid')
            # Only the version, newly explicit limits and implementation hashes
            # can change. All business identities and input bytes stay frozen.
            ignored = {'schemaVersion', 'requestLimits', 'implementationSha256'}
            c.require({k: v for k, v in previous.items() if k not in ignored} ==
                      {k: v for k, v in current.items() if k not in ignored}
                      and set(previous) in (set(current), set(current) - {'requestLimits'})
                      and ('requestLimits' not in previous or
                           previous['requestLimits'] == current['requestLimits'])
                      and all(type(previous.get(k)) is str and
                              len(previous[k]) == 64 and
                              all(ch in '0123456789abcdef' for ch in previous[k])
                              for k in ('implementationSha256',)),
                      'diagnostic_flow_session_migration_identity_changed')
            excluded = {'sessionBinding', 'codeSha256'}
            c.require({k: v for k, v in old.items() if k not in excluded} ==
                      {k: v for k, v in self.binding.items() if k not in excluded}
                      and set(old) == set(self.binding) and
                      type(old.get('codeSha256')) is str and len(old['codeSha256']) == 64
                      and all(ch in '0123456789abcdef' for ch in old['codeSha256']),
                      'diagnostic_flow_session_migration_inputs_changed')
            self._migration = {
                'schemaVersion': 'sermon-diagnostic-dag-session-migration-v1',
                'originalPlanSha256': old_sha256,
                'executionBinding': self.binding,
                'requestLimitsOrigin': 'legacy_binding' if 'requestLimits' in previous
                                       else 'explicit_or_frozen_continuation_snapshot',
                'providerRetry': False, 'productionEligible': False}
            self.binding = old
        self._migration_sha256 = c.canonical_sha256(self._migration) if self._migration is not None else None
        self._migration_frozen = False
        self.plan_sha256 = c.canonical_sha256(self.binding)
        _safe_path(self.fixture_root / 'diagnostic-prefect', recursive=True)
        self.root = _safe_path(self.fixture_root / 'diagnostic-prefect' / self.plan_sha256, recursive=True)
        _safe_path(self.root.parent / '.harness-locks', recursive=True)
        self.nodes = [('source.existing', 'source', None, ())]
        for locale in self.locales:
            self.nodes += [(f'text.{locale}', 'locale', locale, ('source.existing',)),
                           (f'preview.{locale}', 'preview', locale, (f'text.{locale}',))]
        self.nodes.append(('delivery.readonly', 'delivery', None, tuple(f'preview.{x}' for x in self.locales)))
        self.results, self.observations = {}, {}
        self._reliability_failure = None

    def freeze(self):
        self._check()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        _safe_path(self.root, recursive=True)
        public.save_once(self.root / 'plan.json', self.binding)
        if self._migration is not None:
            public.save_once(self.root / 'session-binding-migration.json', self._migration)
            self._migration_frozen = True

    def _check(self):
        c.require(_safe_path(self.session.root) == self.fixture_root and
                  _safe_path(self.root, recursive=True).is_relative_to(self.fixture_root / 'diagnostic-prefect'),
                  'diagnostic_flow_root_changed')
        _safe_path(self.root.parent / '.harness-locks', recursive=True)
        c.require(c.canonical_sha256(self.binding) == self.plan_sha256 and
                  self.session.binding == (self._migration['executionBinding']['sessionBinding']
                      if self._migration is not None else self.binding['sessionBinding']) and
                  _inventory(self.config, self.session) == self.binding['inputFiles'], 'diagnostic_flow_frozen_inputs_changed')
        path = self.root / 'plan.json'
        c.require(self._migration is None or path.exists(),
                  'diagnostic_flow_resume_plan_missing')
        if path.exists():
            c.require(public.read_snapshot(path)[0] == self.binding, 'diagnostic_flow_plan_changed')
        if self._migration is not None:
            c.require(c.canonical_sha256(self._migration) == self._migration_sha256,
                      'diagnostic_flow_session_migration_changed')
            c.require(self._migration['executionBinding']['codeSha256'] ==
                      _hash_file(Path(__file__).resolve()), 'diagnostic_flow_migration_code_changed')
            migration_path = self.root / 'session-binding-migration.json'
            c.require(not self._migration_frozen or migration_path.exists(),
                      'diagnostic_flow_session_migration_missing')
            if migration_path.exists():
                c.require(public.read_snapshot(migration_path)[0] == self._migration,
                          'diagnostic_flow_session_migration_changed')

    def _validate(self, operation, locale, result):
        c.require(type(result) is dict, 'diagnostic_flow_result_required')
        if operation == 'source':
            c.require(result.get('productionEligible') is False and result.get('humanAcceptance') == 'pending',
                      'diagnostic_flow_source_evidence_invalid')
            return True, 'existing_source_verified_human_pending', c.canonical_sha256(result)
        if operation == 'locale':
            if result.get('status') == 'blocked':
                return False, 'machine_review_blocked', None
            c.require(result.get('status') == 'waiting_human', 'diagnostic_flow_locale_not_reviewed')
            path = _path(str(Path(result['output']) / 'candidate.json'))
            c.require(path.is_relative_to(self.fixture_root / 'locales' / locale),
                      'diagnostic_flow_candidate_outside_locale')
            candidate = public.read_snapshot(path)[0]
            digest = c.canonical_sha256(candidate)
            c.require(digest == result['candidateSha256'] and candidate['targetLocale'] == locale and
                      candidate['releaseEligible'] is False and candidate['humanReview']['translation'] == 'pending',
                      'diagnostic_flow_candidate_changed')
            return True, 'machine_pass_real_human_pending', digest
        c.require(result.get('productionEligible') is False and result.get('humanAcceptance') == 'pending',
                  'diagnostic_flow_nonproduction_result_required')
        if operation == 'preview':
            c.require(result.get('status') == 'preview_only' and result.get('offlineFixture') is self.session.offline_fixture,
                      'diagnostic_flow_preview_not_fixture')
            preview_worker.validate_preview_receipt(self.fixture_root, self.session.subject,
                                                    self.session.context, result)
            return True, 'preview_only_real_listening_pending', result['receiptFileSha256']
        c.require(result.get('status') == 'diagnostic_traversal_complete' and
                  result.get('publicationAuthorized') is False and result.get('formalAudioPackageCreated') is False,
                  'diagnostic_flow_delivery_not_readonly')
        c.require(result['resultSha256'] == c.canonical_sha256({k: v for k, v in result.items() if k != 'resultSha256'}),
                  'diagnostic_flow_delivery_result_changed')
        return True, 'diagnostic_traversal_complete', result['resultSha256']

    def execute(self, node_id):
        node_id, operation, locale, dependencies = next(node for node in self.nodes if node[0] == node_id)
        queued_at = accounting.now()
        observation = {'nodeId': node_id, 'operation': operation, 'locale': locale,
            'executionStatus': 'blocked', 'processed': False, 'readyForDownstream': False,
            'humanAcceptance': 'pending', 'productionEligible': False, 'evidenceMode': self.session.evidence_mode,
            'completionSpans': [], 'publicationAuthorized': False}
        dispatched = False
        with _LOCK:
            if self._reliability_failure is not None:
                raise self._reliability_failure
            try:
                self._check()
                parents = [self.observations[key] for key in dependencies]
                if any(not parent['readyForDownstream'] for parent in parents):
                    observation['reason'] = 'upstream_not_completed'
                else:
                    spans = [span for parent in parents for span in parent['completionSpans']]
                    if operation == 'source':
                        spans.extend(getattr(self, 'initial_source_spans', []))
                    ready_at = max((parent['completedAt'] for parent in parents), default=queued_at)
                    with accounting.stage('diagnostic.dag.' + operation, depends_on=spans,
                                          work_unit_id=node_id, executor_type='deterministic_program',
                                          dependency_ready_at=ready_at, queued_at=queued_at) as span:
                        dispatched = operation in {'locale', 'preview'}
                        if operation == 'source':
                            result = self.session.inspect_source()
                        elif operation == 'locale':
                            result = self.session.run_locale(locale, self.config['locales'][locale]['localeSpec'], depends_on=spans)
                        elif operation == 'preview':
                            result = self.session.preview(locale, self.config['locales'][locale]['previewSpec'], depends_on=spans)
                        else:
                            previews = {name: self.results[f'preview.{name}'] for name in self.locales}
                            result = self.session.inspect_delivery(previews, expected_locales=self.locales)
                        ready, status, artifact = self._validate(operation, locale, result)
                        digest = c.canonical_sha256(result)
                        strict.save_once(self.root / 'results' / node_id / (digest + '.json'), result)
                        accounting.record_workload('diagnostic.dag.result', {'resultSha256': digest,
                            'productionEligible': False, 'realHumanAcceptancePending': True})
                    self.results[node_id] = result
                    unknown = operation == 'locale' and any(group.get('status') == 'reconciliation_required'
                        for group in result.get('groups', []))
                    observation.update(executionStatus='outcome_unknown' if unknown else 'completed',
                        processed=None if unknown else True, readyForDownstream=ready and not unknown,
                        resultSha256=digest, artifactSha256=artifact, businessStatus=status,
                        completionSpans=dag_evidence.current_terminal_leaves(span) if ready and not unknown else [],
                        completedAt=accounting.now())
            except Exception as exc:
                if isinstance(exc,accounting.AccountingWriteError) or getattr(exc,'sermon_logging_failed',False):
                    self._reliability_failure=exc
                    raise  # Stop all later callbacks; preserve the original failure.
                typed_local=(type(exc) is historical_identity.HistoricalIdentityPreDispatchRejected)
                known_local=(typed_local and exc.reason_code in historical_identity.PRE_PROVIDER_CODES)
                reason=(exc.reason_code if known_local else str(exc) if not typed_local and isinstance(exc, ValueError) and
                    re.fullmatch(r'[a-z][a-z0-9_]{0,119}', str(exc)) else 'callback_or_evidence_not_confirmed')
                observation.update(executionStatus='outcome_unknown' if dispatched and not known_local else 'blocked',
                    processed=None if dispatched and not known_local else False, reason=reason,
                    errorType=type(exc).__name__)
                if known_local:
                    observation.update(failurePhase=exc.phase,providerDispatchOccurred=False)
            self.observations[node_id] = observation
            _safe_path(self.root, recursive=True)
            strict.save_once(self.root / 'observations' / node_id /
                             (c.canonical_sha256(observation) + '.json'), observation)
            return observation


def run(session, config, *, resume_plan=None):
    """One fresh SDK process; no engine retries/caches replace business ledgers."""
    dag = DiagnosticDAG(session, config, resume_plan=resume_plan)
    with work_lock(dag.root):
        dag.freeze()
        home, database = pilot.isolated_prefect_environment(dag.root)
        os.chdir(tempfile.mkdtemp(prefix='.prefect-config-', dir=dag.root))
        from prefect import flow, task
        from prefect.cache_policies import NO_CACHE
        from prefect.context import get_run_context
        from prefect.settings import get_current_settings
        from prefect.task_runners import ThreadPoolTaskRunner
        settings = get_current_settings()
        c.require(settings.api.url is None and settings.api.key is None and settings.home == home and
                  settings.server.database.connection_url.get_secret_value() == database and
                  settings.results.local_storage_path == home / 'storage' and
                  settings.server.memo_store_path == home / 'memo_store.toml' and
                  not settings.server.analytics_enabled and not settings.cloud.enable_orchestration_telemetry,
                  'diagnostic_flow_prefect_settings_not_isolated')

        @task(retries=0, cache_policy=NO_CACHE, persist_result=False)
        def dispatch(node_id, upstream):
            # Futures provide scheduling edges only. Private runner observations
            # are the sole dependency evidence; arbitrary JSON grants nothing.
            result = dag.execute(node_id)
            ctx = get_run_context()
            return {**result, 'flowRunId': str(ctx.task_run.flow_run_id), 'taskRunId': str(ctx.task_run.id)}

        @flow(name='sermon-offline-diagnostic-continuation', retries=0, persist_result=False,
              task_runner=ThreadPoolTaskRunner(max_workers=1))
        def orchestrate():
            futures = {}
            for node_id, _, _, dependencies in dag.nodes:
                futures[node_id] = dispatch.submit(node_id, [futures[key] for key in dependencies])
            return {key: future.result() for key, future in futures.items()}

        with profile.session(dag.root / 'accounting', 'diagnostic_prefect_continuation',
            work_kind='control', evidence_mode=session.evidence_mode, production_run_id=session.subject.config['runId']):
            results = orchestrate()
        result = {'schemaVersion': SCHEMA, 'planSha256': dag.plan_sha256, 'nodes': results,
            'status': 'diagnostic_traversal_complete' if results['delivery.readonly']['readyForDownstream'] else 'incomplete',
            'humanAcceptance': 'pending', 'productionEligible': False, 'publicationAuthorized': False,
            'evidenceMode': session.evidence_mode, 'maxWorkers': 1}
        strict.save_once(dag.root / 'runs' / (c.canonical_sha256(result) + '.json'), result)
        return result


def fixture_transport(path):
    """Static request-hash lookup; never load caller-authored Python callbacks."""
    value = public.read_snapshot(_path(str(path)))[0]
    c.require(type(value) is dict and set(value) == {'fixtureId', 'responses'} and
              type(value['responses']) is dict, 'diagnostic_flow_fixture_invalid')
    def responder(request, timeout, *, deadline):
        key = c.bytes_sha256(request.data)
        c.require(key in value['responses'], 'diagnostic_flow_fixture_response_missing')
        return json.loads(json.dumps(value['responses'][key]))
    return offline.OfflineHTTPTransport(responder, fixture_id=value['fixtureId'])


def preflight_live(plan, continuation, config, *, request_limits=None):
    """Check original state and all locale bounds before a credential FD read.

    This read-only scope has no executor and cannot enter run(). The real
    constructor repeats original state/code/source checks after key injection.
    """
    from scripts import run_bounded_diagnostic_continuation as entry
    root, subject, context, _, _ = entry.prepare_continuation(plan, continuation, request_limits=request_limits)
    c.require(not (root / 'offline-business-scope.json').exists(),
              'diagnostic_dag_fixture_cannot_become_live')
    scope = SimpleNamespace(root=root, offline_fixture=False, binding={},
                            _path=lambda value, plugin=False: _path(str(value)))
    config = _config(config, scope)
    for lane in config['locales'].values():
        entry.preflight_locale_inputs(subject, context, lane['localeSpec'])
        c.require('fixture_behavior' not in lane['previewSpec'],
                  'preview_fixture_behavior_forbidden')
    _inventory(config, scope)
    return config


def _read_key_fd(fd):
    with os.fdopen(fd, 'rb') as stream:
        raw = stream.read(1025)
    c.require(0 < len(raw) <= 1024 and raw.isascii(), 'invalid_diagnostic_credential_length')
    return raw.decode('ascii').strip()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--continuation', type=Path, required=True)
    parser.add_argument('--spec', type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--offline-fixture', action='store_true')
    mode.add_argument('--execute', action='store_true')
    parser.add_argument('--fixture-responses', type=Path)
    parser.add_argument('--key-fd', type=int)
    parser.add_argument('--request-limits', type=Path, help='Initial request limits; resumes reuse the frozen snapshot')
    parser.add_argument('--resume-plan', type=Path, help='Explicit v1 plan.json to migrate in place without changing its directory')
    args = parser.parse_args(argv)
    plan = public.read_snapshot(_path(str(args.plan)))[0]
    continuation = public.read_snapshot(_path(str(args.continuation)))[0]
    config = public.read_snapshot(_path(str(args.spec)))[0]
    request_limits = public.read_snapshot(_path(str(args.request_limits)))[0] if args.request_limits else None
    if args.offline_fixture:
        c.require(args.fixture_responses is not None and args.key_fd is None,
                  'diagnostic_flow_offline_inputs_required')
        session = _session_class()(plan, continuation, offline_transport=fixture_transport(args.fixture_responses), request_limits=request_limits)
    else:
        c.require(args.fixture_responses is None and args.key_fd is not None and args.key_fd >= 3,
                  'diagnostic_flow_explicit_private_key_fd_required')
        config = preflight_live(plan, continuation, config, request_limits=request_limits)
        session = _session_class()(plan, continuation, key=_read_key_fd(args.key_fd), execute=True, request_limits=request_limits)
    print(json.dumps(run(session, config, **({'resume_plan': args.resume_plan} if args.resume_plan else {})), sort_keys=True))


if __name__ == '__main__':
    main()
