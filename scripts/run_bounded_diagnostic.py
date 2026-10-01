"""One explicit diagnostic entry for ASR, source checks and strict L2.

Use one immutable run-plan.json and directory for every phase/restart. This is
not a source-approval generator, credential loader, TTS launcher or release tool.
The externally approved key enters only an inherited private FD. Source/locale
inputs remain private files, and existing source/human validators still apply.
No generic callback, alternative transport, model fallback or legacy CLI is
accepted by the command. The only network child is the bounded HTTP worker.
"""
from contextlib import contextmanager
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from unittest.mock import patch

from scripts import sermon_accounting as accounting
from scripts import sermon_diagnostic_provider as provider
from scripts import sermon_log_profile as profile
from scripts import sermon_provider_http as http
from scripts import sermon_provider_limits as limits
from scripts import sermon_review_budget as budget
from scripts import sermon_review_contracts as c
from scripts import sermon_strict_layer2 as strict
from scripts import sermon_strict_locale as locale
from scripts import sermon_execution_extensions as extensions
from scripts.sermon_release_workflow import _safe_path


@contextmanager
def bounded_network_only():
    """Single-process diagnostic guard; the HTTP worker has its own allowlist.

    Parent networking is always denied. Child launches must be the exact isolated
    HTTP worker; no legacy CLI/curl/model subprocess can escape the run ledger.
    This is a regression/scope guard, not an adversarial Python sandbox.
    """
    popen = subprocess.Popen
    expected = [sys.executable, '-I', str(Path(http.__file__).resolve()), '--worker']
    def denied(*args, **kwargs):
        raise RuntimeError('diagnostic_legacy_network_forbidden')
    def spawn(command, *args, **kwargs):
        c.require(command == expected and not args and kwargs.get('env') == {} and
                  kwargs.get('close_fds') is True and not kwargs.get('shell'),
                  'diagnostic_unbounded_subprocess_forbidden')
        return popen(command, **kwargs)
    with patch.object(socket.socket, 'connect', denied), \
            patch.object(socket.socket, 'connect_ex', denied), \
            patch.object(socket, 'create_connection', denied), \
            patch.object(subprocess, 'Popen', spawn):
        yield


def verify_source_clip(path, expected_sha256):
    """Read the approved clip before credentials, reservations or transport."""
    path = _safe_path(Path(path))
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        c.require(path.is_file(), 'diagnostic_source_clip_required')
        before = os.fstat(stream.fileno())
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
        after = os.fstat(stream.fileno())
    c.require((before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns) and
              digest.hexdigest() == expected_sha256, 'diagnostic_source_clip_changed')
    return path


class BoundedRun:
    """Pinned provider/store; phase arguments cannot replace either or the key."""
    def __init__(self, subject, api_key, root, *, source_clip):
        c.require(type(subject) is provider.DiagnosticProvider, 'diagnostic_provider_required')
        self.provider, self.key, self.root = subject, api_key, _safe_path(Path(root))
        c.require(subject.store.root == self.root / 'budget', 'diagnostic_pinned_store_required')
        self.source_clip = verify_source_clip(source_clip, subject.config['sourceClipSha256'])
        self.provider.domain()  # Resolve boot identity before subprocess guard.

    def transcribe(self, wav_bytes):
        verify_source_clip(self.source_clip, self.provider.config['sourceClipSha256'])
        with bounded_network_only():
            return self.provider.transcribe(self.key, wav_bytes)

    def source_check(self, *, operation_id):
        verify_source_clip(self.source_clip, self.provider.config['sourceClipSha256'])
        selected = limits.MAX_REQUEST_LIMITS
        payload = self.provider.source_check_payload()
        with bounded_network_only():
            return self.provider.chat(self.key, payload, request_limits=selected,
                                      operation_id=operation_id)

    def run_locale(self, source_bytes, anchor_bytes, policy_bytes, rubric_bytes, *,
                   graph, plugin_path, plugin_sha256, group_plan=None, diagnostic_context=None,
                   depends_on=None):
        verify_source_clip(self.source_clip, self.provider.config['sourceClipSha256'])
        source, policy = map(c.decode_json, (source_bytes, policy_bytes))
        target = policy['targetLocale']
        c.require(target in ('zh-Hans', 'ko', 'es'), 'invalid_diagnostic_locale')
        c.require(source['source']['media']['sha256'] == self.provider.config['sourceMediaSha256'],
                  'diagnostic_source_media_changed')
        if diagnostic_context is not None:
            from scripts import sermon_diagnostic_context as diagnostic
            diagnostic.validate_context(diagnostic_context)
            c.require(diagnostic_context['runId'] == self.provider.config['runId'] and
                      diagnostic_context['runConfigSha256'] == c.canonical_sha256(self.provider.config) and
                      diagnostic_context['storeSha256'] == self.provider.store.store_sha256,
                      'diagnostic_continuation_provider_changed')
        with bounded_network_only():
            return locale.run_locale(source_bytes, anchor_bytes, policy_bytes, rubric_bytes,
                root=self.root / 'locales' / target, store=self.provider.store,
                job_root=self.root / 'jobs', production_run_id=self.provider.config['runId'],
                graph=graph, plugin_path=plugin_path, expected_plugin_sha256=plugin_sha256,
                api_key=self.key, caller=self.provider, usage_resolver=self.provider.usage_resolver,
                bounds={'requests':1, 'inputTokens':self.provider.limits['maxInputTokens'],
                        'outputTokens':self.provider.limits['maxCompletionTokens'],
                        'wallTimeMs':self.provider.limits['wallTimeMs'],
                        'costMicrousd':max(limits._cost(model,self.provider.limits['maxInputTokens'],
                            self.provider.limits['maxCompletionTokens']) for model in limits.SUPPORTED_MODELS)},
                group_plan=group_plan, request_limits=self.provider.limits, depends_on=depends_on,
                **({'diagnostic_context': diagnostic_context} if diagnostic_context is not None else {}))


def prepare_plan(plan, *, stage_declaration=None, extension_receipt=None):
    c.require(type(plan) is dict and set(plan) == {'schemaVersion', 'runDirectory',
        'providerConfig', 'authority', 'executionIdentity', 'sourceClipPath'}, 'invalid_diagnostic_plan')
    c.require(plan['schemaVersion'] == 'sermon-bounded-diagnostic-plan-v1', 'invalid_diagnostic_plan')
    config = provider.validate_config(plan['providerConfig'])
    identity = accounting.execution_identity()
    c.require(identity['trackedWorkingTreeDirty'] is False and identity['gitCommit'] is not None,
              'diagnostic_requires_clean_fixed_code')
    c.require(c.canonical_sha256(plan['executionIdentity']) == config['codeSha256'],
              'diagnostic_code_identity_changed')
    root = _safe_path(Path(plan['runDirectory']))
    c.require(root.is_absolute(), 'diagnostic_absolute_directory_required')
    verify_source_clip(plan['sourceClipPath'], config['sourceClipSha256'])
    store = budget.BudgetStore(root / 'budget', plan['authority'])
    c.require((stage_declaration is None) == (extension_receipt is None),
              'diagnostic_extension_and_declaration_required')
    if stage_declaration is None:
        c.require(identity == plan['executionIdentity'], 'diagnostic_code_identity_changed')
    else:
        extensions.validate_declaration(plan, stage_declaration)
        frozen, _ = c.read_snapshot(extensions.declaration_path(plan, stage_declaration))
        c.require(frozen == stage_declaration, 'diagnostic_stage_declaration_not_frozen')
        saved, _ = c.read_snapshot(root / 'run-plan.json')
        c.require(saved == plan, 'diagnostic_original_plan_changed')
        binding = {'runId': config['runId'], 'runConfigSha256': c.canonical_sha256(config),
            'storeSha256': store.store_sha256, 'sourceIdentitySha256': c.canonical_sha256({
                key: config[key] for key in ('sourceMediaSha256', 'sourceClipSha256',
                                            'sourceAudioSha256', 'sourceWindowSeconds')}),
            'inputSha256': c.canonical_sha256(plan)}
        extensions.validate_extension(extension_receipt, plan['executionIdentity'], identity,
            stage_id=stage_declaration['stageId'], declared_additions=stage_declaration['moduleAdditions'],
            external_runtime_sha256=stage_declaration['externalRuntimeSha256'], binding=binding)
        extensions.persist_extension(root, extension_receipt)
    subject = provider.DiagnosticProvider(store, config)
    # Constructor/preflight does not initialize ledger or start its deadline.
    return root, subject


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--phase', choices=('preflight', 'declare-stage', 'transcribe', 'source-check', 'locale'), required=True)
    parser.add_argument('--input', type=Path)
    parser.add_argument('--key-fd', type=int)
    parser.add_argument('--operation-id', default='source.initial')
    parser.add_argument('--stage-declaration', type=Path)
    parser.add_argument('--identity-extension', type=Path)
    args = parser.parse_args(argv)
    plan, _ = c.read_snapshot(args.plan)
    declaration = c.read_snapshot(args.stage_declaration)[0] if args.stage_declaration else None
    extension = c.read_snapshot(args.identity_extension)[0] if args.identity_extension else None
    if args.phase == 'declare-stage':
        c.require(declaration is not None and extension is None, 'diagnostic_stage_declaration_required')
        prepare_plan(plan)
        extensions.freeze_stage_declaration(plan, accounting.execution_identity(), declaration)
        print(json.dumps({'status':'stage_declared', 'declarationSha256':c.canonical_sha256(declaration),
                          'newCalls':0, 'credentialRead':False}))
        return
    root, subject = prepare_plan(plan, stage_declaration=declaration, extension_receipt=extension)
    if args.phase == 'preflight':
        print(json.dumps({'status':'prepared', 'configSha256':c.canonical_sha256(subject.config),
                          'newCalls':0, 'credentialRead':False}))
        return
    c.require((args.input is not None or args.phase == 'source-check') and args.key_fd is not None and args.key_fd >= 3,
              'diagnostic_private_input_and_key_fd_required')
    with os.fdopen(args.key_fd, 'rb') as stream:
        raw = stream.read(1025)
    c.require(0 < len(raw) <= 1024, 'invalid_diagnostic_credential_length')
    key = raw.decode('ascii').strip()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    strict.save_once(root / 'run-plan.json', plan)
    runner = BoundedRun(subject, key, root, source_clip=plan['sourceClipPath'])
    with profile.session(root / 'logs', 'bounded-diagnostic', work_kind='production',
            evidence_mode='current_execution', production_run_id=subject.config['runId']):
        if args.phase == 'transcribe':
            c.require(args.input.stat().st_size <= http.MAX_REQUEST_BYTES, 'diagnostic_audio_size_limit')
            result = runner.transcribe(args.input.read_bytes())
        elif args.phase == 'source-check':
            result = runner.source_check(operation_id=args.operation_id)
        else:
            spec, _ = c.read_snapshot(args.input)
            c.require(set(spec) == {'source','anchor','policy','rubric','graph','pluginPath',
                                    'pluginSha256','groupPlan'}, 'invalid_diagnostic_locale_spec')
            artifacts = [c.read_snapshot(Path(spec[name]))[1] for name in ('source','anchor','policy','rubric')]
            result = runner.run_locale(*artifacts, graph=spec['graph'], plugin_path=Path(spec['pluginPath']),
                plugin_sha256=spec['pluginSha256'], group_plan=spec['groupPlan'])
        # Private response export is immutable. Console contains no transcript.
        result_hash = c.canonical_sha256(result)
        strict.save_once(root / 'results' / (args.phase + '.' + result_hash + '.json'), result)
        print(json.dumps({'phase':args.phase, 'resultSha256':result_hash, 'budget':subject.snapshot()}))


if __name__ == '__main__':
    main()
