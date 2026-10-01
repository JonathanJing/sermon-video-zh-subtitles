"""Trusted, offline-only local Prefect DAG over existing business callbacks.

Callers construct Node objects in Python; this is not a JSON command/callback
registry. No credential, production switch, budget or dispatch ledger is added.
Use run() once in a fresh process. Existing callback stores own restart/unknown.
Frozen alignment may be reused only when its words match verified ASR exactly;
this adapter does not produce alignment, human approval, or a release.
"""
from dataclasses import asdict, dataclass, field
import inspect
import json
import os
from pathlib import Path
import re
import tempfile
import threading

from scripts import build_english_source_package as source_builder
from scripts import prepare_target_language_speech_job as handoff
from scripts import sermon_accounting as accounting
from scripts import sermon_bounded_business_callbacks as bounded
from scripts import sermon_local_business_callbacks as local
from scripts import sermon_log_profile as profile
from scripts import sermon_prefect_dag as pilot
from scripts import sermon_public_snapshot as public
from scripts import sermon_review_contracts as c
from scripts import sermon_strict_gate_admission as admission
from scripts import sermon_strict_layer2 as strict
from scripts.sermon_execution_harness import work_lock
from scripts.sermon_release_workflow import _safe_path

OPERATIONS = frozenset({'transcribe', 'source_check', 'locale', 'prepare_speech',
                        'render_speech', 'delivery_preflight', 'admit_locale'})
_LOCAL = {'prepare_speech': local.prepare_speech, 'render_speech': local.render_speech,
          'delivery_preflight': local.delivery_preflight}
# All callbacks patch process-global transports. Never widen without isolation.
_EXECUTION_LOCK = threading.Lock()


@dataclass(frozen=True)
class Node:
    id: str
    operation: str
    kwargs: dict = field(default_factory=dict)
    depends_on: tuple = ()
    input_files: tuple = ()


def _identity(value):
    """Freeze values, not Python object reprs or serialized executable objects."""
    if isinstance(value, Path):
        return {'path': str(value.resolve())}
    if type(value) is bytes:
        return {'bytesSha256': c.bytes_sha256(value)}
    if type(value) is admission.AdmissionBoundary:
        return {'admissionConfig': _identity(asdict(value.config)),
                'storeSha256': value.store.store_sha256, 'binding': value.binding,
                'originalInputs': {key: _file_hash(getattr(value.config, key)) for key in
                    ('source', 'anchor', 'policy', 'rubric', 'public_candidate', 'human_receipt', 'plugin')}}
    if isinstance(value, (tuple, list)):
        return [_identity(item) for item in value]
    if type(value) is dict:
        c.require(all(type(key) is str for key in value), 'business_input_key_invalid')
        return {key: _identity(item) for key, item in value.items()}
    if inspect.isclass(value) or inspect.isfunction(value):
        # Only the renderer's explicit trusted fixture seam accepts a factory.
        path = Path(inspect.getfile(value))
        return {'fixtureSymbol': value.__module__ + '.' + value.__qualname__,
                'implementationSha256': c.bytes_sha256(path.read_bytes())}
    c.require(value is None or type(value) in (str, int, bool, float),
              'business_unsupported_input_type')
    return value


def _file_hash(path):
    path = Path(path)
    return c.bytes_sha256(path.read_bytes()) if path.is_file() else None


def _files(node):
    paths = set(map(Path, node.input_files))
    # Fixed callback input roles. Output folders/jobs are bound by their actual
    # predecessor result, so their later materialization does not change a plan.
    keys = ('plugin_path', 'adapter_path', 'registry_path', 'checkpoint_map_path',
            'operation_policies_path', 'speaker_approval_path', 'clip_voice_authorization_path',
            'quality_receipt_path', 'voice_authorization_path')
    paths.update(Path(node.kwargs[key]) for key in keys if node.kwargs.get(key) is not None)
    if node.operation == 'render_speech':
        paths.update(Path(path) for key, path in node.kwargs.get('paths', {}).items() if key != 'job')
    if node.operation == 'delivery_preflight' and 'configuration' in node.kwargs:
        root = Path(node.kwargs['root']); config = node.kwargs['configuration']
        paths.update(root / config[key] for key in ('source', 'anchor'))
        paths.update(root / path for lane in config['locales'].values() for path in lane.values())
    return {str(path.resolve()): _file_hash(path) for path in sorted(paths)}


def _node_identity(node):
    return {'id': node.id, 'operation': node.operation, 'dependsOn': list(node.depends_on),
            'inputs': _identity(node.kwargs), 'inputFiles': _files(node)}


def _words(value):
    # Exact words modulo case, spacing and punctuation; no paraphrase acceptance.
    return re.findall(r"\w+(?:['’]\w+)*", value.casefold())


def _orchestration_root(root, callbacks):
    """Check confinement before even the harness lock can create a directory."""
    c.require(type(callbacks) is bounded.BoundedBusinessCallbacks, 'business_offline_callbacks_required')
    scope = _safe_path(callbacks.root)
    selected = _safe_path(root)
    c.require(selected != scope and scope in selected.parents, 'business_root_outside_fixture_scope')
    for reserved in (callbacks.subject.store.root, scope / 'jobs', scope / 'locales'):
        reserved = _safe_path(reserved)
        c.require(selected != reserved and reserved not in selected.parents and selected not in reserved.parents,
                  'business_root_overlaps_business_state')
    c.require(not selected.exists() or selected.is_dir(), 'business_root_directory_required')
    if selected.exists() and not (selected / 'business-plan.json').exists():
        c.require(not any(selected.iterdir()), 'business_root_requires_dedicated_directory')
    # work_lock writes here before BusinessDAG construction.
    _safe_path(selected.parent / '.harness-locks', recursive=True)
    return selected


class BusinessDAG:
    """Fixed callbacks plus trusted input bindings; observations grant no authority."""
    def __init__(self, root, callbacks, nodes):
        c.require(type(callbacks) is bounded.BoundedBusinessCallbacks, 'business_offline_callbacks_required')
        self.root = _orchestration_root(root, callbacks)
        self.callbacks = callbacks
        self._fixture_root = _safe_path(callbacks.root)
        self.nodes = tuple(nodes)
        self.by_id = {}
        self._outcomes = {}
        self._envelopes = {}
        for node in self.nodes:
            c.require(type(node) is Node and node.operation in OPERATIONS, 'business_operation_not_allowed')
            strict.label(node.id)
            c.require(node.id not in self.by_id and set(node.depends_on) <= set(self.by_id),
                      'business_topological_nodes_required')
            c.require('depends_on' not in node.kwargs, 'business_dependencies_owned_by_dag')
            # Factories only enter through the existing explicit offline renderer seam.
            c.require(all(not callable(value) or (node.operation == 'render_speech' and key == 'synth_factory')
                          for key, value in node.kwargs.items()), 'business_callback_registry_forbidden')
            self.by_id[node.id] = node
            ancestors = self._ancestors(node)
            if node.operation == 'source_check':
                c.require(any(n.operation == 'transcribe' for n in ancestors), 'business_asr_dependency_required')
            if node.operation == 'locale':
                c.require(any(n.operation == 'source_check' for n in ancestors), 'business_source_dependency_required')
            required = {'admit_locale': 'locale', 'prepare_speech': 'admit_locale',
                        'render_speech': 'prepare_speech', 'delivery_preflight': 'render_speech'}
            if node.operation in required:
                c.require(any(n.operation == required[node.operation] for n in ancestors),
                          'business_phase_dependency_required')
            self._boundaries(node.kwargs)
        c.require(bool(self.nodes), 'business_nodes_required')
        self.binding = {'schemaVersion': 'sermon-offline-business-dag-v1',
            'callbackBinding': callbacks.binding, 'nodes': [_node_identity(n) for n in self.nodes],
            'maxWorkers': 1, 'retries': 0, 'prefectCache': False,
            'evidenceMode': 'synthetic', 'productionEligible': False,
            'codeSha256': c.bytes_sha256(Path(__file__).read_bytes())}
        self.plan_sha256 = c.canonical_sha256(self.binding)
        strict.save_once(self.root / 'business-plan.json', self.binding)

    def _boundaries(self, value):
        if type(value) is admission.AdmissionBoundary:
            c.require(value.store is self.callbacks.subject.store and
                      value.config.production_run_id == self.callbacks.subject.config['runId'],
                      'business_admission_store_or_run_changed')
            local._boundary_paths(self._fixture_root, value)
        elif type(value) is dict:
            for item in value.values(): self._boundaries(item)
        elif isinstance(value, (tuple, list)):
            for item in value: self._boundaries(item)

    def _ancestors(self, node):
        result = []
        for key in node.depends_on:
            parent = self.by_id[key]
            result.extend([parent, *self._ancestors(parent)])
        return result

    def _check(self):
        c.require(_orchestration_root(self.root, self.callbacks) == self.root and
                  _safe_path(self.callbacks.root) == self._fixture_root, 'business_fixture_root_changed')
        for node in self.nodes: self._boundaries(node.kwargs)
        c.require(c.read_snapshot(self.root / 'business-plan.json')[0] == self.binding and
                  self.binding['nodes'] == [_node_identity(n) for n in self.nodes] and
                  self.binding['callbackBinding'] == self.callbacks.binding,
                  'business_frozen_inputs_changed')
        self.callbacks._check()

    def _alignment(self, node):
        source, anchor = map(c.decode_json, (node.kwargs['source_bytes'], node.kwargs['anchor_bytes']))
        source_builder.validate_ready_package(source)
        c.require(source['anchors']['artifact']['jsonSha256'] == c.canonical_sha256(anchor),
                  'awaiting_alignment_binding')
        transcript = json.loads(self.callbacks.subject.source_check_payload()['messages'][1]['content'])['transcript']
        words = _words(' '.join(unit['english'] for unit in anchor['sourceUnits']))
        c.require(bool(words) and _words(transcript) == words, 'awaiting_alignment_binding')
        return {'status': 'verified_word_equivalence', 'timingProvenance': 'frozen_fixture_alignment_not_generated',
                'sourcePackageSha256': c.canonical_sha256(source),
                'anchorSha256': c.canonical_sha256(anchor), 'asrTextSha256': c.bytes_sha256(transcript.encode())}

    def _validate(self, node, envelope):
        c.require(envelope['evidenceMode'] == 'synthetic' and envelope['productionEligible'] is False and
                  envelope['executionAuthority'] == 'none' and
                  envelope['resultSha256'] == c.canonical_sha256(envelope['result']), 'business_invalid_result')
        result = envelope['result']
        state = {'processed': True, 'machineStatus': 'not_applicable', 'humanStatus': 'not_applicable',
                 'admissionStatus': 'offline_only', 'readyForDownstream': True,
                 'artifactSha256': envelope['resultSha256']}
        if node.operation == 'transcribe':
            transcript = json.loads(self.callbacks.subject.source_check_payload()['messages'][1]['content'])['transcript']
            c.require(result['text'] == transcript, 'business_asr_receipt_changed')
            state['admissionStatus'] = 'raw_asr_only'
        elif node.operation == 'source_check':
            value = c.decode_json(result['choices'][0]['message']['content'].encode())
            c.require(set(value) == {'issues', 'uncertainty'} and
                      type(value['issues']) is list and type(value['uncertainty']) is list,
                      'business_source_check_invalid')
            clear = not value['issues'] and not value['uncertainty']
            state.update(machineStatus='pass' if clear else 'needs_review', humanStatus='pending',
                         admissionStatus='machine_source_check_only', readyForDownstream=clear)
        elif node.operation == 'locale':
            if result['status'] == 'blocked':
                unknown = any(row.get('status') == 'reconciliation_required' for row in result.get('groups', []))
                state.update(machineStatus='unknown' if unknown else 'blocked', humanStatus='pending',
                             admissionStatus='reconciliation_required' if unknown else 'blocked',
                             readyForDownstream=False, processed=None if unknown else True)
                if unknown: state['executionStatus'] = 'outcome_unknown'
            else:
                c.require(result['status'] == 'waiting_human', 'business_locale_status_invalid')
                candidate = public.read_snapshot(Path(result['output']) / 'candidate.json')[0]
                c.require(c.canonical_sha256(candidate) == result['candidateSha256'] and
                          candidate['humanReview']['translation'] == 'pending' and
                          candidate['releaseEligible'] is False, 'business_candidate_changed')
                source, anchor = map(c.decode_json, (node.kwargs['source_bytes'], node.kwargs['anchor_bytes']))
                handoff._validate_schema(candidate, 'sermon-target-language-candidate-v2.schema.json', 'candidate')
                handoff.validate_target_candidate(source, anchor, candidate, require_human_approval=False)
                state.update(machineStatus='pass', humanStatus='pending', artifactSha256=result['candidateSha256'],
                             admissionStatus='waiting_human_translation_review', readyForDownstream=False)
        elif node.operation == 'admit_locale':
            admitted = result['status'] in {'committed', 'existing'}
            if result['status'] == 'outcome_unknown':
                state.update(executionStatus='outcome_unknown', processed=None)
            state.update(machineStatus='pass' if admitted else 'blocked',
                         humanStatus='original_receipt_validated' if admitted else 'pending',
                         admissionStatus='prepare_layer3_intent' if admitted else result['status'],
                         readyForDownstream=admitted)
        elif node.operation == 'prepare_speech':
            job = public.read_snapshot(Path(node.kwargs['out']) / 'job.json')[0]
            c.require(result['status'] == 'prepared' and result['scope'] == 'speech_job_preparation_only' and
                      result['jobSha256'] == c.canonical_sha256(job) and result['dispatched'] is False,
                      'business_preparation_result_invalid')
            state.update(humanStatus='original_receipts_validated_by_callback', artifactSha256=result['jobSha256'],
                         admissionStatus='prepared' if result['synthesisEligible'] else 'awaiting_voice_authorization',
                         readyForDownstream=result['synthesisEligible'])
        elif node.operation == 'render_speech':
            manifest = public.read_snapshot(Path(node.kwargs['paths']['job']).parent / 'render-manifest.json')[0]
            c.require(manifest == result, 'business_render_manifest_changed')
            state.update(machineStatus=result['machineScreening']['status'], humanStatus='pending',
                         admissionStatus='awaiting_audio_alignment_and_human_review', readyForDownstream=False)
        elif node.operation == 'delivery_preflight':
            c.require(result['status'] == 'bindings_verified' and result['publicationAuthorized'] is False and
                      result['bindingSha256'] == envelope['binding']['bindingSha256'],
                      'business_preflight_result_invalid')
            state.update(humanStatus='original_receipts_validated_by_callback', artifactSha256=result['bindingSha256'],
                         admissionStatus='bindings_verified_not_publication', readyForDownstream=False)
        for artifact in envelope.get('artifacts', []):
            c.require(c.bytes_sha256(Path(artifact['path']).read_bytes()) == artifact['fileBytesSha256'],
                      'business_result_artifact_changed')
        spans = envelope.get('completionSpans', [envelope.get('spanId')])
        identity = accounting._identity.get()
        c.require(identity is not None, 'business_accounting_session_required')
        events, errors = accounting.read_events(Path(identity[0]))
        c.require(not errors, 'business_accounting_damaged')
        ends = [row for row in events if row.get('spanId') in spans and row['event'] == 'stage_finished'
                and row.get('status') == 'completed' and row.get('evidenceMode') == 'synthetic']
        c.require(len(ends) == len(spans) and all(spans), 'business_completion_span_missing')
        state.update(completionSpans=spans, elapsedSeconds=sum(row['elapsedSeconds'] for row in ends),
                     resultSha256=envelope['resultSha256'])
        return state

    def _admit(self, node):
        boundary = node.kwargs['boundary']
        self._boundaries(boundary)
        parents = [n for n in self._ancestors(node) if n.operation == 'locale' and
                   c.decode_json(n.kwargs['policy_bytes'])['targetLocale'] == boundary.config.target_locale]
        c.require(len(parents) == 1, 'business_matching_locale_required')
        parent = parents[0]
        evidence = self._envelopes[parent.id]['result']
        c.require({Path(r['root']).resolve() for r in evidence['revisions']} ==
                  {Path(p).resolve() for p in boundary.config.revision_roots},
                  'business_admission_revision_chain_changed')
        for name, key in [('source', 'source_bytes'), ('anchor', 'anchor_bytes'),
                          ('policy', 'policy_bytes'), ('rubric', 'rubric_bytes')]:
            c.require(c.canonical_sha256(c.decode_json(Path(getattr(boundary.config, name)).read_bytes())) ==
                      c.canonical_sha256(c.decode_json(parent.kwargs[key])), 'business_admission_inputs_changed')
        snapshot = boundary.snapshot()
        return boundary.admit(expected_state_revision=snapshot.state_revision,
                              created_at=node.kwargs['created_at'])

    def _local_binding(self, node):
        ancestors = self._ancestors(node)
        if node.operation == 'prepare_speech':
            boundary = node.kwargs['boundary']
            parents = [n for n in ancestors if n.operation == 'admit_locale' and
                       n.kwargs.get('boundary') is boundary]
            c.require(len(parents) == 1, 'business_preparation_intent_changed')
            intent_id = self._envelopes[parents[0].id]['result']['intent']['intentId']
            c.require(node.kwargs.get('intent_id', intent_id) == intent_id, 'business_preparation_intent_changed')
            return {'intent_id': intent_id}
        elif node.operation == 'render_speech':
            job = Path(node.kwargs['paths']['job']).resolve()
            parents = [n for n in ancestors if n.operation == 'prepare_speech' and
                       Path(n.kwargs['out']).resolve() / 'job.json' == job]
            c.require(len(parents) == 1 and c.canonical_sha256(public.read_snapshot(job)[0]) ==
                      self._envelopes[parents[0].id]['result']['jobSha256'], 'business_render_job_changed')
        elif node.operation == 'delivery_preflight':
            self._delivery_audio_chain(node, ancestors)
        return {}

    def _delivery_audio_chain(self, node, ancestors):
        config = node.kwargs.get('configuration') or {}
        lanes = config.get('locales') or {}
        c.require(bool(lanes), 'business_delivery_audio_chain_required')
        for locale, lane in lanes.items():
            parents = [n for n in ancestors if n.operation == 'render_speech' and
                       n.id in self._envelopes and self._outcomes.get(n.id, {}).get('executionStatus') == 'completed' and
                       self._envelopes[n.id]['result'].get('targetLocale') == locale]
            c.require(len(parents) == 1, 'business_delivery_audio_chain_required')
            parent = parents[0]
            self._validate(parent, self._envelopes[parent.id])
            rendered = self._envelopes[parent.id]['result']
            audio = public.read_snapshot(_safe_path(Path(node.kwargs['root']) / lane['audioPackage']))[0]
            c.require(audio.get('status') != 'audio_unavailable',
                      'business_delivery_text_only_continuation_unsupported')
            for key in ('targetLocale', 'englishSourcePackageJsonSha256',
                        'targetLanguageCandidateJsonSha256', 'targetLanguageSpeechJobJsonSha256'):
                c.require(audio.get(key) == rendered.get(key), 'business_delivery_audio_artifacts_changed')
            for key in ('track', 'captions', 'schedule'):
                c.require(audio.get(key, {}).get('sha256') == rendered[key]['sha256'],
                          'business_delivery_audio_artifacts_changed')
            identity = lambda rows: [(row['textGroupId'], row['targetTextSha256'], row['audio']['sha256']) for row in rows]
            c.require(identity(audio.get('units', [])) == identity(rendered['units']),
                      'business_delivery_audio_artifacts_changed')
        # A render is still unscreened/unreviewed. No fixed operation currently
        # imports the subsequent original alignment/screening/human receipts;
        # unrelated reviewed package files cannot stand in for that causal step.
        raise c.ContractError('business_delivery_audio_review_continuation_unsupported')

    def execute(self, node_id, upstream=()):
        """Execute using only this runner's observed parent outcomes."""
        node = self.by_id[node_id]
        base = {'nodeId': node.id, 'operation': node.operation, 'processed': False,
                'machineStatus': 'not_run', 'humanStatus': 'not_assessed', 'admissionStatus': 'blocked',
                'readyForDownstream': False, 'completionSpans': [], 'evidenceMode': 'synthetic',
                'productionEligible': False, 'executionAuthority': 'none'}
        with _EXECUTION_LOCK:
            dispatched = False
            try:
                self._check()
                expected = [self._outcomes[key] for key in node.depends_on]
                received = [{k: v for k, v in row.items() if k not in {'flowRunId', 'taskRunId'}} for row in upstream]
                c.require(received == expected, 'business_dependency_binding_changed')
                allowed_pending = node.operation == 'admit_locale'
                if any(not row['readyForDownstream'] and not (allowed_pending and
                           row['operation'] == 'locale' and row['processed'] and row['machineStatus'] == 'pass')
                       for row in expected):
                    observation = {**base, 'executionStatus': 'blocked', 'reason': 'upstream_not_admitted'}
                else:
                    alignment = self._alignment(node) if node.operation == 'locale' else None
                    spans = [span for row in expected for span in row['completionSpans']]
                    if node.operation == 'admit_locale':
                        c.require(type(node.kwargs.get('boundary')) is admission.AdmissionBoundary and
                                  type(node.kwargs.get('created_at')) is str,
                                  'business_original_admission_evidence_required')
                    if node.operation in _LOCAL or node.operation == 'admit_locale':
                        with accounting.stage('business.dag.' + node.operation, depends_on=spans,
                                              work_unit_id=node.id, executor_type='deterministic_program') as span:
                            if node.operation == 'admit_locale':
                                dispatched = True
                                with bounded.no_transport(): result = self._admit(node)
                                envelope = {'result': result, 'resultSha256': c.canonical_sha256(result),
                                            'evidenceMode': 'synthetic', 'productionEligible': False,
                                            'executionAuthority': 'none'}
                            else:
                                kwargs = dict(node.kwargs)
                                c.require(kwargs.get('offline') is True, 'business_local_offline_scope_required')
                                kwargs.update(self._local_binding(node))
                                inspect.signature(_LOCAL[node.operation]).bind(**kwargs)
                                dispatched = True
                                envelope = _LOCAL[node.operation](**kwargs)
                        envelope = {**envelope, 'completionSpans': [span]}
                    else:
                        callback = getattr(self.callbacks, node.operation)
                        inspect.signature(callback).bind(**node.kwargs, depends_on=spans)
                        dispatched = True
                        envelope = callback(**node.kwargs, depends_on=spans)
                    state = self._validate(node, envelope)
                    self._envelopes[node.id] = envelope
                    observation = {**base, 'executionStatus': 'completed', **state,
                                   **({'alignmentBinding': alignment} if alignment is not None else {})}
            except Exception as exc:
                safe_reasons = {'awaiting_alignment_binding', 'business_delivery_audio_chain_required',
                                'business_delivery_text_only_continuation_unsupported',
                                'business_delivery_audio_review_continuation_unsupported',
                                'business_delivery_audio_artifacts_changed'}
                reason = str(exc) if str(exc) in safe_reasons else 'business_callback_or_evidence_blocked'
                observation = {**base, 'executionStatus': 'outcome_unknown' if dispatched else 'blocked',
                               'processed': None if dispatched else False,
                               'admissionStatus': 'reconciliation_required' if dispatched else 'blocked',
                               'reason': reason, 'errorType': type(exc).__name__}
            # Copy so callers cannot mutate an observation into dispatch permission.
            self._outcomes[node.id] = json.loads(json.dumps(observation))
            return observation


def run(root, callbacks, nodes):
    """One fresh-process, local-only SDK run. Existing business caches handle replay."""
    root = _orchestration_root(root, callbacks)
    with work_lock(root):
        dag = BusinessDAG(root, callbacks, nodes)
        home, database = pilot.isolated_prefect_environment(root)
        os.chdir(tempfile.mkdtemp(prefix='.prefect-config-', dir=root))
        from prefect import flow, task
        from prefect.cache_policies import NO_CACHE
        from prefect.context import get_run_context
        from prefect.task_runners import ThreadPoolTaskRunner
        from prefect.settings import get_current_settings
        settings = get_current_settings()
        c.require(settings.api.url is None and settings.api.key is None and settings.home == home and
                  settings.server.database.connection_url.get_secret_value() == database and
                  settings.results.local_storage_path == home / 'storage' and
                  settings.server.memo_store_path == home / 'memo_store.toml' and
                  not settings.server.analytics_enabled and not settings.cloud.enable_orchestration_telemetry,
                  'business_prefect_settings_not_isolated')

        from scripts import sermon_business_progress as progress

        @task(retries=0, cache_policy=NO_CACHE, persist_result=False)
        def dispatch(node_id, upstream):
            ctx = get_run_context()
            result = dag.execute(node_id, upstream)
            progress.update(dag)
            return {**result, 'flowRunId': str(ctx.task_run.flow_run_id),
                    'taskRunId': str(ctx.task_run.id)}

        @flow(name='sermon-offline-business-dag', retries=0, persist_result=False,
              task_runner=ThreadPoolTaskRunner(max_workers=1))
        def orchestrate():
            futures = {}
            for node in dag.nodes:
                futures[node.id] = dispatch.submit(node.id, [futures[key] for key in node.depends_on])
            return {key: future.result() for key, future in futures.items()}

        with profile.session(root / 'accounting', 'offline_business_prefect', work_kind='control',
                             evidence_mode='synthetic'):
            progress.update(dag)
            result = orchestrate()
            snapshot = progress.update(dag)
        return {'planSha256': dag.plan_sha256, 'nodes': result, 'maxWorkers': 1,
                'evidenceMode': 'synthetic', 'productionEligible': False, 'executionAuthority': 'none',
                'freshAlignmentProduced': False, 'published': False, 'progress': snapshot}
