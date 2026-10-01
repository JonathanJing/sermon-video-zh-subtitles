"""Explicit continuation callbacks over an existing diagnostic ledger.

Fixtures require the existing matching marker and can never adopt a real store.
Live execution additionally requires explicit execute and an injected key. No
credential discovery, Source/ASR rerun, approval or production Audio Package is
provided. Original validators, deadlines and budgets own recovery.
"""
from copy import deepcopy
from contextlib import nullcontext
import os
from pathlib import Path

from scripts import run_bounded_diagnostic as bounded
from scripts import run_bounded_diagnostic_continuation as entry
from scripts import sermon_accounting as accounting
from scripts import sermon_bounded_business_callbacks as offline
from scripts import sermon_log_profile as profile
from scripts import sermon_public_snapshot as public
from scripts import sermon_review_contracts as c
from scripts import sermon_strict_layer2 as strict
from scripts.sermon_diagnostic_source_evidence import validate_prior_source_evidence
from scripts.sermon_release_workflow import _safe_path


class DiagnosticSession:
    """Trusted fixed callbacks; optional injected key never enters evidence."""
    def __init__(self, plan, continuation, *, key=None, offline_transport=None, execute=False):
        self.offline_fixture = offline_transport is not None
        c.require(type(execute) is bool and (
            (self.offline_fixture and key is None and execute is False and
             type(offline_transport) is offline.OfflineHTTPTransport) or
            (not self.offline_fixture and execute is True and type(key) is str and
             0 < len(key) <= 1024 and key.isascii())),
            'diagnostic_dag_explicit_transport_required')
        self.evidence_mode = 'synthetic' if self.offline_fixture else 'current_execution'
        c.require(Path(plan['runDirectory']).is_absolute(), 'diagnostic_absolute_directory_required')
        self.root = _safe_path(Path(plan['runDirectory']))
        marker = None
        if self.offline_fixture:
            marker, _ = c.read_snapshot(self.root / 'offline-business-scope.json')
            c.require(marker == {'schemaVersion': 'sermon-offline-business-scope-v1',
                'fixtureId': offline_transport.fixture_id,
                'providerConfigSha256': c.canonical_sha256(plan['providerConfig']),
                'storeSha256': continuation['diagnosticContext']['storeSha256'],
                'mode': 'offline_fixture', 'productionEligible': False},
                'diagnostic_dag_offline_scope_required')
        else:
            c.require(not (self.root / 'offline-business-scope.json').exists(),
                      'diagnostic_dag_fixture_cannot_become_live')
        self.plan, self.continuation = deepcopy(plan), deepcopy(continuation)
        self.root, self.subject, self.context, self.deadline, evidence = entry.prepare_continuation(
            self.plan, self.continuation)
        if self.offline_fixture:
            self.subject.executor = offline_transport
        self.transport, self.marker = self.subject.executor, marker
        self.runner = bounded.BoundedRun(self.subject, offline.OFFLINE_KEY if self.offline_fixture else key, self.root,
                                        source_clip=self.plan['sourceClipPath'])
        self.binding = {'schemaVersion': 'sermon-diagnostic-dag-session-v1',
            'originalPlanSha256': c.canonical_sha256(plan),
            'continuationSha256': c.canonical_sha256(continuation),
            'diagnosticContextSha256': c.canonical_sha256(self.context),
            'sourceEvidence': evidence,
            'fixtureId': self.transport.fixture_id if self.offline_fixture else None,
            'runId': self.context['runId'], 'storeSha256': self.subject.store.store_sha256,
            'deadlineMonotonic': self.deadline, 'evidenceMode': self.evidence_mode,
            'humanAcceptance': 'pending', 'productionEligible': False,
            'implementationSha256': c.bytes_sha256(Path(__file__).read_bytes())}
        self._locale_results = {}
        self._locale_specs = {}

    def _path(self, path, *, plugin=False):
        c.require(Path(path).is_absolute(), 'diagnostic_dag_absolute_path_required')
        path = _safe_path(Path(path))
        # The versioned language plugin is repository code, not fixture data.
        repository = Path(__file__).resolve().parent.parent
        c.require(not self.offline_fixture or self.root in path.parents or
                  (plugin and repository in path.parents and path.is_file()),
                  'diagnostic_dag_path_outside_scope')
        return path

    def _check(self):
        active = profile.current()
        c.require(active is not None and active['evidenceMode'] == self.evidence_mode,
                  'diagnostic_dag_accounting_mode_changed')
        identity = accounting._identity.get() or tuple(os.environ.get(k) for k in accounting.ENV_KEYS[:2])
        c.require(identity[0] is not None and identity[1] is not None,
                  'diagnostic_dag_accounting_required')
        c.require(self.root in self._path(identity[0]).parents, 'diagnostic_dag_accounting_outside_scope')
        current_code, started_code = accounting.execution_identity(), self.continuation['executionIdentity']
        c.require(all(current_code.get(k) == v for k, v in started_code.items()
                      if k != 'loadedProjectCodeSha256') and
                  all(current_code.get('loadedProjectCodeSha256', {}).get(k) == v for k, v in
                      started_code.get('loadedProjectCodeSha256', {}).items()),
                  'diagnostic_continuation_code_changed')
        c.require((not self.offline_fixture or
                  c.read_snapshot(self.root / 'offline-business-scope.json')[0] == self.marker)
                  and c.read_snapshot(self.root / 'run-plan.json')[0] == self.plan
                  and self.subject.executor is self.transport
                  and self.subject.config == self.plan['providerConfig']
                  and self.subject.store.store_sha256 == self.context['storeSha256'],
                  'diagnostic_dag_binding_changed')
        bounded.verify_source_clip(self.plan['sourceClipPath'], self.subject.config['sourceClipSha256'])
        with self.subject._locked() as (_, state):
            self.subject._remaining(state)
            c.require(all(row['state'] in ('returned', 'rejected') for row in state['requests'].values()),
                      'diagnostic_prior_outcome_requires_reconciliation')
            evidence = validate_prior_source_evidence(self.root, state, self.context)
            c.require(evidence == self.binding['sourceEvidence'] and
                      state['startedMonotonic'] + self.subject.config['totalWallSeconds'] == self.deadline,
                      'diagnostic_dag_source_or_clock_changed')
        return evidence

    def inspect_source(self):
        evidence = self._check()
        accounting.record_workload('diagnostic.existing_source', {
            **evidence, 'sourceMediaSha256': self.subject.config['sourceMediaSha256'],
            'simulatedHumanApproval': True, 'realHumanAcceptancePending': True,
            'productionEligible': False})
        return {'status': 'existing_evidence_validated', 'sourceEvidence': evidence,
                'newASRCalls': 0, 'newSourceCheckCalls': 0,
                'humanAcceptance': 'pending', 'productionEligible': False}

    def run_locale(self, locale, spec, *, depends_on=None, historical_reuse=None):
        self._check()
        for key in ('source', 'anchor', 'policy', 'rubric'):
            self._path(spec[key])
        self._path(spec['pluginPath'], plugin=True)
        artifacts, _ = entry.preflight_locale_inputs(self.subject, self.context, spec)
        c.require(c.decode_json(artifacts[2])['targetLocale'] == locale,
                  'diagnostic_dag_locale_changed')
        with profile.context(workKind='production', productionRunId=self.subject.config['runId']), \
                offline.no_transport() if self.offline_fixture else nullcontext():
            result = self.runner.run_locale(*artifacts, graph=spec['graph'],
                plugin_path=Path(spec['pluginPath']), plugin_sha256=spec['pluginSha256'],
                group_plan=spec['groupPlan'], diagnostic_context=self.context, depends_on=depends_on,
                **({'historical_reuse': historical_reuse} if historical_reuse is not None else {}))
        self._locale_specs[locale] = deepcopy(spec)
        self._locale_results[locale] = deepcopy(result)
        return result

    def preview(self, locale, spec, *, depends_on=None):
        from scripts import sermon_diagnostic_preview_worker as worker
        self._check()
        result = self._locale_results.get(locale)
        c.require(result is not None and result['status'] == 'waiting_human' and result.get('output'),
                  'diagnostic_dag_machine_candidate_required')
        spec = deepcopy(spec)
        c.require('candidate' not in spec['paths'], 'diagnostic_dag_candidate_owned_by_locale')
        candidate_path = self._path(Path(result['output']) / 'candidate.json')
        candidate, _ = public.read_snapshot(candidate_path)
        c.require(candidate_path.is_relative_to(self.root / 'locales' / locale / 'machine-candidates')
                  and c.canonical_sha256(candidate) == result['candidateSha256']
                  and candidate['targetLocale'] == locale and candidate['releaseEligible'] is False,
                  'diagnostic_dag_candidate_changed')
        spec['paths']['candidate'] = str(candidate_path)
        original = self._locale_specs[locale]
        for key in ('source', 'anchor', 'policy'):
            c.require(self._path(spec['paths'][key]) == self._path(original[key]),
                      'diagnostic_dag_preview_input_changed')
        c.require(self._path(spec['strict_rubric_path']) == self._path(original['rubric']),
                  'diagnostic_dag_preview_rubric_changed')
        for path in spec['paths'].values():
            self._path(path)
        for key in ('checkpoint_map_path', 'operation_policies_path', 'out'):
            self._path(spec[key])
        c.require(self._path(spec['out']).is_relative_to(self.root / 'diagnostic-previews' / locale),
                  'diagnostic_dag_preview_output_changed')
        with profile.context(workKind='production', productionRunId=self.subject.config['runId']):
            return worker.launch_preview(self.root, self.subject, self.context, spec,
                                         offline_fixture=self.offline_fixture, depends_on=depends_on)

    def inspect_delivery(self, previews, expected_locales):
        from scripts import sermon_diagnostic_delivery_preflight as delivery
        self._check()
        return delivery.inspect_delivery(self.root, self.subject, self.context, previews,
                                         expected_locales=expected_locales)
