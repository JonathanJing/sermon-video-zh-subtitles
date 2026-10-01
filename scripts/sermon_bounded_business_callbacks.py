"""Existing bounded ASR/source/L2 callbacks for an OFFLINE fixture DAG.

This module has no credential input or production-enable flag. A trusted test
responder is injected; every invocation denies sockets and process creation.
Provider/strict business ledgers remain the only authority for attempts, budget,
unknown outcomes and cache recovery. The scope marker is a fixture declaration,
not a source/human approval. No approval receipt is generated here.
"""
from contextlib import contextmanager
from pathlib import Path
import os
import socket
import subprocess
import threading
from unittest.mock import patch

from scripts import run_bounded_diagnostic as bounded
from scripts import sermon_diagnostic_provider as provider
from scripts import sermon_accounting as accounting
from scripts import sermon_log_profile as profile
from scripts import sermon_review_contracts as c
from scripts import sermon_strict_layer2 as strict
from scripts import build_english_source_package as source_builder
from scripts.sermon_release_workflow import _safe_path

OFFLINE_KEY = 'offline-fixture'
# Network guards patch process globals. Serialize these callbacks, including
# independent locales; a later safe process adapter can widen concurrency.
_TRANSPORT_LOCK = threading.Lock()


@contextmanager
def no_transport():
    def denied(*args, **kwargs):
        raise RuntimeError('offline_business_transport_forbidden')
    with patch.object(socket.socket, 'connect', denied), patch.object(socket.socket, 'connect_ex', denied), \
         patch.object(socket, 'create_connection', denied), patch.object(socket, 'getaddrinfo', denied), \
         patch.object(subprocess, 'Popen', denied):
        yield


class OfflineHTTPTransport:
    """Trusted fixture seam, not a sandbox for adversarial Python responders."""
    def __init__(self, responder, *, fixture_id):
        strict.label(fixture_id)
        c.require(callable(responder), 'offline_fixture_responder_required')
        self.responder, self.fixture_id = responder, fixture_id
        self.observations = []

    def __call__(self, request, timeout, *, deadline):
        c.require(request.get_header('Authorization') == 'Bearer '+OFFLINE_KEY,
                  'offline_credential_required')
        self.observations.append({'requestPayloadBytesSha256': c.bytes_sha256(request.data),
                                  'timeoutSeconds': timeout, 'deadlineMonotonic': deadline})
        with no_transport():
            return self.responder(request, timeout, deadline=deadline)


class BoundedBusinessCallbacks:
    def __init__(self, subject, root, *, source_clip, fixture_id, offline=False):
        c.require(offline is True and type(subject) is provider.DiagnosticProvider
                  and type(subject.executor) is OfflineHTTPTransport
                  and subject.executor.fixture_id == fixture_id, 'offline_provider_fixture_required')
        self.root = _safe_path(Path(root))
        self.subject, self.transport = subject, subject.executor
        self.fixture_id = strict.label(fixture_id)
        marker = self.root/'offline-business-scope.json'
        binding = {'schemaVersion': 'sermon-offline-business-scope-v1', 'fixtureId': fixture_id,
            'providerConfigSha256': c.canonical_sha256(subject.config), 'storeSha256': subject.store.store_sha256,
            'mode': 'offline_fixture', 'productionEligible': False}
        # In particular, never adopt the paused real diagnostic's existing store.
        c.require(marker.exists() or not subject.store.root.exists(), 'existing_provider_requires_offline_scope')
        strict.save_once(marker, binding)
        self.binding = binding
        self.runner = bounded.BoundedRun(subject, OFFLINE_KEY, self.root, source_clip=source_clip)

    def _check(self):
        c.require(profile.current() is not None and profile.current()['evidenceMode'] == 'synthetic',
                  'offline_synthetic_accounting_required')
        identity = accounting._identity.get() or tuple(os.environ.get(k) for k in accounting.ENV_KEYS[:2])
        c.require(identity[0] is not None and identity[1] is not None,
                  'offline_accounting_session_required')
        ledger = _safe_path(Path(identity[0]))
        c.require(ledger == self.root or self.root in ledger.parents, 'offline_accounting_outside_scope')
        c.require(self.subject.executor is self.transport
                  and c.read_snapshot(self.root/'offline-business-scope.json')[0] == self.binding
                  and self.binding['providerConfigSha256'] == c.canonical_sha256(self.subject.config)
                  and self.binding['storeSha256'] == self.subject.store.store_sha256,
                  'offline_callback_identity_changed')

    def _invoke(self, kind, callback, *, depends_on=(), work_unit_id=None):
        with _TRANSPORT_LOCK:
            self._check()
            with profile.context(workUnitId=work_unit_id or kind):
                with accounting.stage('business.'+kind, executor_type='deterministic_program',
                        depends_on=list(depends_on), work_unit_id=work_unit_id or kind) as span:
                    with no_transport():
                        result = callback()
                    digest = c.canonical_sha256(result)
                    accounting.record_workload('business.callback_result', {
                        'resultSha256': digest, 'fixtureId': self.fixture_id, 'productionEligible': False})
            return {'result': result, 'resultSha256': digest, 'completionSpans': [span],
                    'evidenceMode': 'synthetic', 'productionEligible': False, 'executionAuthority': 'none',
                    'fixtureId': self.fixture_id}

    def transcribe(self, wav_bytes, *, depends_on=()):
        return self._invoke('asr', lambda: self.runner.transcribe(wav_bytes), depends_on=depends_on)

    def source_check(self, *, operation_id='source.initial', depends_on=()):
        return self._invoke('source_check', lambda: self.runner.source_check(operation_id=operation_id),
                            depends_on=depends_on)

    def source_package(self, aligned_segments_path, anchor_manifest_path, *, depends_on=(), **kwargs):
        """Deterministic existing builder. Requires frozen alignment/review inputs.

        This does not run alignment, convert raw ASR to word timestamps or
        assert alignment originated from this run. Caller must bind/validate that
        causal input before admitting this package into a full fresh-run DAG.
        """
        def build():
            value = source_builder.build_package(aligned_segments_path, anchor_manifest_path, **kwargs)
            source = value['source']
            c.require(source.get('media') is not None and
                source['media']['sha256'] == self.subject.config['sourceMediaSha256'] and
                [source['approvedWindow']['startSeconds'], source['approvedWindow']['endSeconds']] ==
                    self.subject.config['sourceWindowSeconds'], 'offline_source_package_scope_changed')
            return value
        return self._invoke('source_package', build, depends_on=depends_on)

    def locale(self, source_bytes, anchor_bytes, policy_bytes, rubric_bytes, *, graph,
               plugin_path, plugin_sha256, group_plan=None, depends_on=()):
        source = c.decode_json(source_bytes)
        source_builder.validate_ready_package(source)
        target = c.decode_json(policy_bytes)['targetLocale']
        return self._invoke('locale', lambda: self.runner.run_locale(
            source_bytes, anchor_bytes, policy_bytes, rubric_bytes, graph=graph,
            plugin_path=plugin_path, plugin_sha256=plugin_sha256, group_plan=group_plan),
            depends_on=depends_on, work_unit_id='text.'+target)

    def provider_evidence(self):
        """Read existing state only, without initializing/renewing provider time."""
        self._check()
        path = self.subject.store.root/provider.budget.STORE_ID/'provider-run/state.json'
        state, raw = c.read_snapshot(path)
        c.require(state.get('config') == self.subject.config, 'offline_provider_evidence_changed')
        return {'fileBytesSha256': c.bytes_sha256(raw), 'requests': [
            {'modelCallId': key, 'state': row['state'], 'receiptSha256': row['receiptSha256'],
             'requestSha256': row['requestSha256']} for key, row in sorted(state['requests'].items())],
            'scope': 'synthetic_fixture_usage_not_actual_spend'}
