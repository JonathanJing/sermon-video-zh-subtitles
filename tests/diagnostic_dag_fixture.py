"""Synthetic paused diagnostic with genuine bounded-provider receipts.

No production validator is mocked. The only transport is OfflineHTTPTransport;
checkpoint bytes are inert and FakeSynth is the explicit preview test seam.
"""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from scripts import sermon_accounting as accounting
from scripts import sermon_bounded_business_callbacks as callbacks
from scripts import sermon_diagnostic_provider as provider
from scripts import sermon_diagnostic_source_evidence as evidence
from scripts import sermon_log_profile as profile
from scripts import sermon_review_budget as budget
from scripts import sermon_review_contracts as c
from scripts import sermon_provider_limits as limits
from tests import test_run_bounded_diagnostic as bounded_fixture
from tests import test_sermon_diagnostic_context as context_fixture
from tests import test_render_speculative_target_language_speech as preview_fixture


class DiagnosticDAGFixture(unittest.TestCase):
    request_limits = {**limits.DEFAULT_REQUEST_LIMITS,
        'maxInputTokens': limits.MAX_REQUEST_LIMITS['maxInputTokens']}
    expected_prior_calls = 2
    expected_new_locale_calls = 4
    expected_preview_calls = 2

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = c.canonical_bytes(value) + b'\n'
        path.write_bytes(raw)
        return path, raw

    def session(self):
        return profile.session(self.root / 'logs', 'diagnostic-dag-fixture',
            work_kind='engineering', evidence_mode='synthetic')

    def setUp(self):
        # Import the continuation closure before freezing loaded-module hashes.
        from scripts import sermon_diagnostic_dag_session, sermon_diagnostic_prefect_flow
        from scripts import sermon_diagnostic_preview_worker
        from scripts import sermon_diagnostic_delivery_preflight
        self.original = bounded_fixture.BoundedRunTests()
        self.original.setUp(); self.addCleanup(self.original.doCleanups)
        self.root = self.original.f.root.resolve()
        pending = context_fixture.DiagnosticContextTests()
        pending.setUp(); self.addCleanup(pending.doCleanups)
        self.source, self.anchor = deepcopy(pending.source), deepcopy(pending.anchor)
        self.policy, self.rubric = deepcopy(pending.policy), deepcopy(pending.rubric)
        # The pending-Source helper owns a sibling temporary directory. Copy
        # its real summary evidence into this run before freezing any identity;
        # the complete DAG deliberately refuses external fixture references.
        summary = self.source['evidence']['pipelineSummary']
        summary_bytes = Path(summary['path']).read_bytes()
        summary_path = self.root / 'source-pipeline-summary.json'
        summary_path.write_bytes(summary_bytes)
        summary['path'] = str(summary_path)
        summary['sha256'] = c.bytes_sha256(summary_bytes)
        if 'jsonSha256' in summary:
            summary['jsonSha256'] = c.canonical_sha256(c.decode_json(summary_bytes))
        self.execution_identity = accounting.execution_identity()
        # Unit checks may substitute this identity ONLY at the clean-code gate.
        # A committed SDK test naturally captures a clean identity unchanged.
        self.execution_identity['trackedWorkingTreeDirty'] = False
        config = dict(self.original.subject.config,
                      codeSha256=c.canonical_sha256(self.execution_identity))
        self.config = config
        # Frozen rule text raises the reviewer input bound; retain the output cap.
        self.request_limits = deepcopy(self.original.subject.limits)
        self.store = self.original.fixture.store
        words = ' '.join(u['english'] for u in self.anchor['sourceUnits']).split()
        chunks = [' '.join(words[len(words)*i//4:len(words)*(i+1)//4]) for i in range(4)]
        assert all(chunks), 'Synthetic anchor needs at least four words'
        self.aligned = [dict(id=i, start=float(i), end=float(i+1), text=text)
                        for i, text in enumerate(chunks)]
        self.transcript = ' '.join(chunks)
        _, aligned_raw = self.write('aligned-segments.json', self.aligned)
        self.write('reference-chunks.json', [dict(id='chunk', start=0, end=180, text=self.transcript)])
        self.anchor['input']['mfaSegmentsSha256'] = c.bytes_sha256(aligned_raw)
        _, anchor_raw = self.write('anchor-manifest.json', self.anchor)
        self.source['source']['media']['sha256'] = config['sourceMediaSha256']
        self.source['source']['approvedWindow'].update(startSeconds=60., endSeconds=240.)
        for key, name, value, raw in (
                ('transcript', 'aligned-segments.json', self.aligned, aligned_raw),
                ('anchors', 'anchor-manifest.json', self.anchor, anchor_raw)):
            self.source[key]['artifact'] = dict(path=str(self.root/name),
                sha256=c.bytes_sha256(raw), jsonSha256=c.canonical_sha256(value))
        self.source['alignment']['artifact'] = deepcopy(self.source['transcript']['artifact'])
        context_fixture.reidentify(self.source)
        source_path, _ = self.write('simulated-review-inputs/source.json', self.source)
        self.content = dict(sourceAudioSha256=config['sourceAudioSha256'],
            sourceWindowSeconds=config['sourceWindowSeconds'],
            issues=[dict(type=reason, text=chunks[i], issue='Synthetic review candidate',
                uncertainty='Unconfirmed text-only candidate') for i, reason in enumerate(evidence.REASONS)],
            uncertainty=dict(scope='Text-internal review only; factual claims were not evaluated.',
                audio_available=False, explicit_uncertainty_markers_present=False,
                confirmed_asr_errors=0, summary='Human review remains pending.'))
        self.transport = callbacks.OfflineHTTPTransport(self.capture, fixture_id='diagnostic-dag-fixture')
        # Default real monotonic clock/boot identity: same-process AND subprocess
        # continuation must consume the original deadline, never a fake reset.
        self.subject = provider.DiagnosticProvider(self.store, config, self.request_limits, executor=self.transport)
        self.callbacks = callbacks.BoundedBusinessCallbacks(self.subject, self.root,
            source_clip=self.original.clip, fixture_id='diagnostic-dag-fixture', offline=True)
        self.plan = dict(schemaVersion='sermon-bounded-diagnostic-plan-v1',
            runDirectory=str(self.root), providerConfig=config, authority=self.store.authority,
            executionIdentity=self.execution_identity, sourceClipPath=str(self.original.clip))
        self.write('run-plan.json', self.plan)
        with self.session():
            self.callbacks.transcribe(self.original.raw)
            self.callbacks.source_check()
        with self.subject._locked() as (_, state):
            self.state = deepcopy(state)
        review = next(r for r in self.state['requests'].values() if r['operationId']=='source.initial')
        self.request = dict(schemaVersion='sermon-english-source-review-request-v1', humanApproval=False,
            status='pending', alignedSegmentsSha256=c.bytes_sha256(aligned_raw),
            anchorManifestJsonSha256=c.canonical_sha256(self.anchor),
            sourceUnitIds=[u['sourceUnitId'] for u in self.anchor['sourceUnits']],
            requiredChecks=list(evidence.diagnostic.PENDING_CHECKS),
            machineIssues=[dict(issueId='source.issue.'+str(i+1), reasonCode=reason,
                confirmedError=False, reviewStatus='human_pending', matchedSegmentIds=[i],
                clipTimeRangesSeconds=[[float(i), float(i+1)]],
                matchingMethod='literal_normalized_text_substring_not_verified_audio',
                privateEvidenceSha256=c.canonical_sha256(self.content['issues'][i]))
                for i, reason in enumerate(evidence.REASONS)],
            sourceReviewReceiptSha256=review['receiptSha256'], sourceMediaSha256=config['sourceMediaSha256'],
            sourceWindowSeconds=config['sourceWindowSeconds'], scope='review_request_not_approval_receipt')
        self.write('source-review-request.json', self.request)
        authorization = dict(schemaVersion='isolated-diagnostic-simulation-authorization-v1',
            allowedScope='isolated_diagnostic_L2_machine_review_preview_TTS_delivery_preflight',
            humanAcceptance='pending', productionEligible=False,
            originalRunConfigSha256=c.canonical_sha256(config),
            sourceCanonicalSha256=c.canonical_sha256(self.source),
            sourceReviewRequestSha256=c.canonical_sha256(self.request), prohibited=sorted(evidence.PROHIBITED),
            userInstruction='Synthetic fixture authorization only.', userInstructionAt='2026-10-01T00:00:00Z')
        self.write('simulated-review-inputs/simulation-authorization.json', authorization)
        self.context = dict(schemaVersion=evidence.diagnostic.SCHEMA, runId=config['runId'],
            runConfigSha256=c.canonical_sha256(config), storeSha256=self.store.store_sha256,
            sourceCanonicalSha256=c.canonical_sha256(self.source), anchorCanonicalSha256=c.canonical_sha256(self.anchor),
            continuationCodeCommit=self.execution_identity['gitCommit'],
            simulationAuthorizationRef=c.canonical_sha256(authorization), humanAcceptance='pending', productionEligible=False)
        self.continuation = dict(schemaVersion='sermon-diagnostic-continuation-v1',
            originalPlanSha256=c.canonical_sha256(self.plan), executionIdentity=self.execution_identity,
            diagnosticContext=self.context)
        self.policy['sourceScope'].update(englishSourcePackageJsonSha256=c.canonical_sha256(self.source),
            anchorManifestSha256=c.canonical_sha256(self.anchor))
        self.policy['componentSha256']['sourceScope'] = c.canonical_sha256(self.policy['sourceScope'])
        policy_path, _ = self.write('simulated-review-inputs/policy.json', self.policy)
        rubric_path, _ = self.write('simulated-review-inputs/rubric.json', self.rubric)
        plugin = self.root / self.original.f.f.plugin_path.name
        plugin.write_bytes(self.original.f.f.plugin_path.read_bytes())
        self.locale_specs = {'zh-Hans': dict(source=str(source_path), anchor=str(self.root/'anchor-manifest.json'),
            policy=str(policy_path), rubric=str(rubric_path), graph=self.original.graph,
            pluginPath=str(plugin), pluginSha256=self.original.f.f.plugin_sha, groupPlan=self.original.plan)}
        self.source_evidence = evidence.validate_prior_source_evidence(self.root, self.state, self.context)
        self._preview_spec(source_path, policy_path)
        # Original plan/code hash remains immutable after its two requests.
        # Continuation records the complete code loaded while preparing fixtures.
        self.original_execution_identity = self.execution_identity
        self.execution_identity = accounting.execution_identity()
        self.execution_identity['trackedWorkingTreeDirty'] = False
        self.continuation['executionIdentity'] = self.execution_identity
        self.context['continuationCodeCommit'] = self.execution_identity['gitCommit']
        self.write('continuation.json', self.continuation)

    def capture(self, request, timeout, *, deadline):
        if request.full_url.endswith('/audio/transcriptions'):
            return dict(text=self.transcript, usage=dict(type='duration', seconds=180))
        payload = json.loads(request.data)
        inputs = json.loads(payload['messages'][1]['content'])
        if 'translationGroupId' not in inputs:
            return dict(id='fixture-source-review', model=payload['model'],
                choices=[dict(finish_reason='stop', message=dict(content=json.dumps(self.content)))],
                usage=dict(prompt_tokens=100, completion_tokens=20))
        return self.original.capture(request, timeout, deadline=deadline)

    def _preview_spec(self, source_path, policy_path):
        fixture = preview_fixture.SpeculativeRenderTests()
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        voice = fixture.fixture
        registry, adapter = deepcopy(voice.registry), deepcopy(voice.adapter)
        weights = b'inert synthetic checkpoint; FakeSynth only'
        registry['speakers'][0]['checkpoint']['checkpointSha256'] = c.bytes_sha256(weights)
        capability = next(r for r in registry['speakers'][0]['localeCapabilities'] if r['targetLocale']=='zh-Hans')
        adapter.update(targetLocale='zh-Hans', languageParameter=capability['modelLanguage'],
            capabilityEvidenceSha256=c.canonical_sha256(capability['reviewEvidence']),
            conditioningSha256=c.bytes_sha256(weights), registryJsonSha256=c.canonical_sha256(registry))
        registry_path, _ = self.write('preview-inputs/registry.json', registry)
        adapter_path, _ = self.write('preview-inputs/adapter.json', adapter)
        policies_path, _ = self.write('preview-inputs/policies.json', json.loads(fixture.policies.read_text()))
        checkpoint = self.root/'preview-inputs/checkpoint'; checkpoint.mkdir()
        (checkpoint/'model.safetensors').write_bytes(weights)
        self.write('preview-inputs/checkpoint/config.json', {'talker_config':{'spk_id':{adapter['speakerKey']:0}}})
        checkpoint_map, _ = self.write('preview-inputs/checkpoint-map.json', dict(
            schemaVersion='sermon-speaker-checkpoint-map-v1', checkpoints=[dict(speakerId=adapter['speakerId'],
                checkpointRef=adapter['conditioningRef'], path=str(checkpoint))]))
        self.preview_specs = {'zh-Hans': dict(paths={key: str(path) for key, path in dict(source=source_path,
            anchor=self.root/'anchor-manifest.json', policy=policy_path, adapter=adapter_path, registry=registry_path).items()},
            checkpoint_map_path=str(checkpoint_map), operation_policies_path=str(policies_path),
            strict_rubric_path=self.locale_specs['zh-Hans']['rubric'],
            out=str(self.root/'diagnostic-previews/zh-Hans/fixture-preview'), device='cpu', execute=False)}
        preview_fixture.FakeSynth.calls = []

    def tearDown(self):
        self.doCleanups()
