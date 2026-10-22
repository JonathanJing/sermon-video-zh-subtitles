import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import wave

from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.source import unified_stage as subject
from tongxing_production.source import budget
from tongxing_production.source import english_source_judge as judge
from tongxing_production.orchestration import jobs


class UnifiedSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.media = self.root / 'source.wav'
        with wave.open(str(self.media), 'wb') as stream:
            stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(16000)
            stream.writeframes(b'\0\0' * 16000 * 181)
        self.window = {'startSeconds': 0, 'endSeconds': 181}
        from tongxing_production.workflows.supervisor.production import stable_hash, json_digest
        url = 'https://example.invalid/synthetic-source'
        timeline = {'schemaVersion': 2, 'stage': 'source_media_verified', 'boundaryMethod': 'operator_supplied',
            'status': 'requires_operator_review', 'sourceUrl': url, 'sunday': '2026-10-04',
            'durationSeconds': 181, 'audioSha256': subject._sha(self.media), 'audioSizeBytes': self.media.stat().st_size}
        self.timeline = self.root / 'timeline.json'
        self.timeline.write_text(json.dumps(timeline))
        self.descriptor = self.root / 'descriptor.json'
        self.descriptor.write_text(json.dumps({'sourceUrl': url, 'sourceId': 'synthetic-source',
            'mediaSha256': subject._sha(self.media), 'sunday': '2026-10-04'}))
        self.approval = self.root / 'window.json'
        self.approval.write_text(json.dumps({'status': 'approved', 'humanApproval': True,
            'sunday': '2026-10-04', 'sourceUrlHash': stable_hash(url), 'startTime': '00:00:00',
            'endTime': '00:03:01', 'approvedBy': 'fixture', 'timelineReportSha256': json_digest(timeline)}))
        local = {key: None for key in subject.LOCAL_MFA_FIELDS}
        local['mfa_executable'] = 'mfa'
        self.config = {'schemaVersion': subject.SCHEMA, 'productionRunId': 'a'*64,
            'sourceId': 'synthetic-source', 'sourceUrlHash': __import__('hashlib').sha256(url.encode()).hexdigest(), 'serviceDate': '2026-10-04',
            'sourceDurationSeconds': 181, 'timelineReport': str(self.timeline),
            'timelineReportSha256': subject._sha(self.timeline), 'sourceDescriptor': str(self.descriptor),
            'sourceDescriptorSha256': subject._sha(self.descriptor),
            'media': str(self.media), 'mediaSha256': subject._sha(self.media), 'window': self.window,
            'windowApproval': str(self.approval), 'windowApprovalSha256': subject._sha(self.approval),
            'jobRoot': str(self.root / 'jobs'), 'outputDirectory': str(self.root / 'source'),
            'budgetAuthorization': str(self.root / 'budget.json'),
            'mfa': {'backend': 'macbook', 'allowSparkFallback': False, 'localOptions': local,
                    'sparkOptions': {key: local.get(key) for key in subject.SPARK_MFA_FIELDS}},
            'anchorPolicy': {'maxUnitSeconds': 8, 'boundaryOverrides': None},
            'judge': {'model': 'gpt-6-astra', 'reasoningEffort': 'medium', 'batchSize': 5, 'workers': 1}}
        self.path = self.root / 'config.json'
        self.path.write_text(json.dumps(self.config))
        # Test-only stable code witness; no source/runtime facts are bypassed.
        self.patch = patch.object(subject.code, 'code_identity', return_value='c'*64)
        self.patch.start(); self.addCleanup(self.patch.stop)
        binding = {'productionRunId': 'a'*64,
            'configurationSha256': jobs._digest({k:v for k,v in self.config.items() if k != 'budgetAuthorization'}),
            'codeIdentitySha256': 'c'*64, 'budgetRoot': str(self.root / '.jobs.source-budget')}
        bounds = {'requests': 20, 'wallTimeMs': 6000000, 'costMicrousd': 10000000}
        limits = dict(budget.text_limits.DEFAULT_REQUEST_LIMITS)
        budget_approval = self.root / 'budget-approval.json'
        budget_approval.write_text(json.dumps({'schemaVersion': 'sermon-source-budget-approval-v1',
            'binding': {**binding, 'globalBounds': bounds, 'requestLimits': limits},
            'humanApproval': True, 'decision': 'approved', 'operatorEvidence': 'Synthetic fixture, no paid calls',
            'reviewedBy': 'fixture', 'reviewedAt': '2026-10-04T00:00:00Z'}))
        (self.root / 'budget.json').write_text(json.dumps({'schemaVersion': 'sermon-source-budget-authorization-v1',
            'binding': binding, 'authority': {'approvalSha256': subject._sha(budget_approval),
                'globalBounds': bounds, 'requestLimits': limits}, 'approvalReceipt': str(budget_approval)}))
        self.calls = []

    def preflight(self, **kwargs):
        return {'schemaVersion': 1, 'backend': 'macbook-local', 'runtime': {'testOnly': True}}

    def align(self, references, clip, out, **kwargs):
        out.mkdir(parents=True, exist_ok=True)
        (out / 'backend.json').write_text(json.dumps(self.preflight()))
        result = []
        for index, ref in enumerate(references):
            words = ref['text'].split()
            width = min(.15, (ref['end'] - ref['start']) / len(words) / 2)
            times = [{'text': word, 'start': ref['start'] + i * width * 2,
                      'end': ref['start'] + i * width * 2 + width} for i, word in enumerate(words)]
            result.append({'id': index, 'referenceChunkId': ref['id'], 'text': ref['text'],
                'start': times[0]['start'], 'end': times[-1]['end'], 'wordTimes': times,
                'sentenceBoundarySource': 'frozen_reference_punctuation'})
        return result

    def transport(self, endpoint, body, content_type, key):
        self.calls.append(endpoint)
        if endpoint.endswith('/transcriptions'):
            return {'text': 'Jesus is worthy.'}
        payload = json.loads(body)
        self.assertIn('max_completion_tokens', payload)
        source = json.loads(payload['messages'][1]['content'])
        rows = [{'sourceSentenceId': row['sourceSentenceId'],
                 'sourceUnitIds': [unit['sourceUnitId'] for unit in row['units']],
                 'verdict': 'pass', 'risk': 'low', 'checks': {name: 'pass' for name in judge.CHECKS},
                 'evidence': 'Synthetic response preserves words and exact units.', 'unresolvedIssues': []}
                for row in source['sentences']]
        return {'id': 'synthetic-judge', 'created': 1790000000, 'model': 'gpt-6-astra',
                'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(
                    {'schemaVersion': judge.BATCH_SCHEMA, 'sentences': rows})}}]}

    def execute(self, transport=None, preflight=None):
        return subject.execute(self.path, api_key='', transport=transport or self.transport,
                               aligner=self.align, mfa_preflight=preflight or self.preflight)

    def test_inspect_is_read_only_and_has_bound_snapshot(self):
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result = subject.inspect(self.path)
        self.assertEqual(result['chunkCount'], 2)
        self.assertTrue(result['snapshotBound'])
        self.assertEqual(result['window'], self.window)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.assertFalse((self.root / '.jobs.source-budget').exists())

    def test_versioned_parallel_source_configuration_binds_four_asr_and_eight_judges(self):
        self.config.update(schemaVersion=subject.SCHEMA_V2, asrWorkers=4)
        self.config['judge']['workers'] = 8
        self.path.write_text(json.dumps(self.config))
        authorization_path = self.root / 'budget.json'
        authorization = json.loads(authorization_path.read_text())
        authorization['binding']['configurationSha256'] = jobs._digest(
            {k: v for k, v in self.config.items() if k != 'budgetAuthorization'})
        approval_path = self.root / 'budget-approval.json'
        approval = json.loads(approval_path.read_text())
        approval['binding'].update(authorization['binding'])
        approval_path.write_text(json.dumps(approval))
        authorization['authority']['approvalSha256'] = subject._sha(approval_path)
        authorization_path.write_text(json.dumps(authorization))
        config = subject.load_configuration(self.path)
        self.assertEqual(config.value['asrWorkers'], 4)
        self.assertEqual(config.value['judge']['workers'], 8)
        result = self.execute()
        self.assertFalse(result['productionEligible'])
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(jobs._read(config.budget_root / 'source-budget.json')['maxConcurrent'], 8)

    def rebind_budget(self, budget_root=None):
        self.path.write_text(json.dumps(self.config))
        authorization_path = self.root / 'budget.json'
        authorization = json.loads(authorization_path.read_text())
        authorization['binding']['configurationSha256'] = jobs._digest(
            {k: v for k, v in self.config.items() if k != 'budgetAuthorization'})
        if budget_root is not None:
            authorization['binding']['budgetRoot'] = str(budget_root)
        approval_path = self.root / 'budget-approval.json'
        approval = json.loads(approval_path.read_text())
        approval['binding'].update(authorization['binding'])
        approval_path.write_text(json.dumps(approval))
        authorization['authority']['approvalSha256'] = subject._sha(approval_path)
        authorization_path.write_text(json.dumps(authorization))

    def claude_judge(self, model='claude-opus-5-5', effort='high'):
        test = self

        class FakeClaudeJudge:
            def __init__(self):
                self.model, self.effort, self.payloads = model, effort, []

            def __call__(self, api_key, payload):
                test.assertIsNone(api_key)
                self.payloads.append(payload)
                envelope = test.transport('claude-cli', json.dumps(payload).encode(), 'application/json', '')
                return dict(envelope, model=model, usage={'prompt_tokens': 1000, 'completion_tokens': 200,
                                                          'total_tokens': 1200})
        return FakeClaudeJudge()

    def test_v3_judge_backend_fixes_the_model(self):
        self.config.update(schemaVersion=subject.SCHEMA_V3, asrWorkers=1)
        for judge_config, ok in [
                ({'backend': 'openai_api', 'model': 'gpt-6.1-sol'}, True),
                ({'backend': 'claude_cli_opus', 'model': 'claude-opus-5-5'}, True),
                ({'backend': 'openai_api', 'model': 'gpt-6-astra'}, False),
                ({'backend': 'openai_api', 'model': 'claude-opus-5-5'}, False),
                ({'backend': 'claude_cli_opus', 'model': 'gpt-6.1-sol'}, False),
                ({'backend': 'gemini', 'model': 'gpt-6.1-sol'}, False),
                ({'model': 'gpt-6.1-sol'}, False)]:
            with self.subTest(judge=judge_config):
                self.config['judge'] = {'reasoningEffort': 'high', 'batchSize': 5, 'workers': 2, **judge_config}
                self.rebind_budget()
                if ok:
                    self.assertEqual(subject.load_configuration(self.path).value['judge'], self.config['judge'])
                else:
                    with self.assertRaises(ValueError):
                        subject.load_configuration(self.path)

    def test_v1_and_v2_stay_openai_and_reject_a_backend_or_claude_model(self):
        for version, extra in [(subject.SCHEMA, {}), (subject.SCHEMA_V2, {'asrWorkers': 1})]:
            for judge_config in ({'backend': 'openai_api', 'model': 'gpt-6.1-sol'}, {'model': 'claude-opus-5-5'}):
                with self.subTest(version=version, judge=judge_config):
                    self.config = {k: v for k, v in self.config.items() if k != 'asrWorkers'}
                    self.config.update(schemaVersion=version, **extra)
                    self.config['judge'] = {'reasoningEffort': 'high', 'batchSize': 5, 'workers': 1, **judge_config}
                    self.rebind_budget()
                    with self.assertRaises(ValueError):
                        subject.load_configuration(self.path)

    def test_claude_judge_runs_through_the_cli_and_settles_as_list_price_equivalent(self):
        self.config.update(schemaVersion=subject.SCHEMA_V3, asrWorkers=1)
        self.config['judge'] = {'backend': 'claude_cli_opus', 'model': 'claude-opus-5-5',
                                'reasoningEffort': 'high', 'batchSize': 5, 'workers': 1}
        self.rebind_budget()
        fake = self.claude_judge()
        result = subject.execute(self.path, api_key='', transport=self.transport, aligner=self.align,
                                 mfa_preflight=self.preflight, claude_transport=fake)
        self.assertEqual(result['status'], 'succeeded')
        self.assertFalse(result['productionEligible'])
        # ASR still uses the OpenAI audio endpoint; no judge request reaches Chat Completions.
        self.assertNotIn('https://api.openai.com/v1/chat/completions', self.calls)
        self.assertEqual(len(fake.payloads), 1)
        self.assertEqual(fake.payloads[0]['model'], 'claude-opus-5-5')
        self.assertEqual(fake.payloads[0]['max_completion_tokens'], 4096)
        ledger = jobs._read(self.root / '.jobs.source-budget' / 'source-budget.json')
        judged = [row for operation, row in ledger['requests'].items() if operation.startswith('judge.')]
        self.assertEqual(len(judged), 1)
        self.assertEqual(judged[0]['status'], 'returned')
        receipt = json.loads((self.root / 'source' / 'machine-judge.json').read_text())
        self.assertEqual(receipt['model'], 'claude-opus-5-5')
        saved = [jobs._read(path) for path in (self.root / '.jobs.source-budget').rglob('*.json')
                 if path.name != 'source-budget.json' and 'settlement' in jobs._read(path)]
        claude_rows = [row for row in saved if row['requestIdentity'].get('model') == 'claude-opus-5-5']
        self.assertEqual([row['settlement']['priceBasis'] for row in claude_rows],
                         ['claude_subscription_list_price_equivalent'])
        # A mismatched transport is refused before any reservation.
        self.assertIsNone(budget.SourceBudget(self.root / 'other', subject.load_configuration(self.path).authority,
                                              verify=lambda: None).claude_transport)

    def test_claude_judge_payload_without_matching_transport_is_refused(self):
        from tongxing_production.compute import provider_limits as limits
        authority = subject.load_configuration(self.path).authority
        caller = budget.SourceBudget(self.root / 'claude-budget', authority, verify=lambda: None,
                                     claude_transport=self.claude_judge(effort='medium'))
        request = {'model': 'claude-opus-5-5', 'reasoning_effort': 'high',
                   'messages': [{'role': 'system', 'content': 'Judge.'}, {'role': 'user', 'content': 'source'}],
                   'response_format': {'type': 'json_schema', 'json_schema': {
                       'name': 'english_source_machine_judge', 'strict': True, 'schema': judge._response_schema()}}}
        bounded = budget.bounded_source_judge_payload(request, limits.DEFAULT_REQUEST_LIMITS)
        with self.assertRaisesRegex(ValueError, 'claude_transport_required'):
            caller.judge('', bounded)
        self.assertFalse((self.root / 'claude-budget' / 'source-budget.json').exists()
                         and jobs._read(self.root / 'claude-budget' / 'source-budget.json')['requests'])

    def test_operator_reviewed_text_stops_before_mfa_then_applies_without_new_asr(self):
        from tongxing_production.source import text_review as review_module
        self.config.update(schemaVersion=subject.SCHEMA_V2, asrWorkers=1, sourceTextReview='review.json')
        self.rebind_budget()
        aligned = []
        original_align = self.align
        self.align = lambda references, clip, out, **kw: aligned.append([r['text'] for r in references]) or original_align(references, clip, out, **kw)
        with self.assertRaisesRegex(ValueError, 'source_text_review_required'):
            self.execute()
        self.assertEqual(aligned, [])
        asr_calls = len(self.calls)
        out = self.root / 'source'
        references = json.loads((out / 'asr_reference_chunks.json').read_text())
        original = references[0]['text']
        corrected = original + ' Reviewed.'
        evidence = self.root / 'review-evidence.json'
        evidence.write_text(json.dumps({'confirmedBy': 'operator'}))
        (self.root / 'review.json').write_text(json.dumps({
            'schemaVersion': review_module.SCHEMA_V3, 'reviewType': 'human', 'humanApproval': True,
            'status': review_module.STATUS, 'authority': review_module.HUMAN_AUTHORITY,
            'reviewedBy': 'operator', 'reviewedAt': '2026-10-11T00:00:00Z',
            'sourceAudioSha256': subject._sha(out / 'source-clip.wav'),
            'asrSha256': subject._sha(out / 'asr_reference.json'),
            'evidence': [{'path': str(evidence), 'sha256': subject._sha(evidence)}],
            'patches': [{'segmentId': 0, 'originalTextSha256': review_module.text_sha256(original),
                         'correctedText': corrected, 'reason': 'operator confirmed',
                         'evidenceSha256': subject._sha(evidence)}]}))
        result = self.execute()
        self.assertEqual(len(self.calls) - asr_calls, 1)  # the judge only; ASR replays
        self.assertEqual(aligned[0][0], corrected)
        self.assertEqual(json.loads((out / 'asr_reference_chunks.json').read_text())[0]['text'], original)
        provenance = json.loads((out / 'source-text-review-provenance.json').read_text())
        self.assertEqual((provenance['reviewType'], provenance['humanApproval']), ('human', True))
        self.assertFalse(result['productionEligible'])

    def rebuild_inputs(self, aligned_sha):
        overrides = self.root / 'overrides.json'
        overrides.write_text(json.dumps({'schemaVersion': subject.REBUILD_OVERRIDES_SCHEMA,
                                         'alignedSegmentsSha256': aligned_sha, 'overrides': {}}))
        out = self.root / 'rebuilt'
        identity = jobs._digest({'baseConfiguration': jobs._digest({k: v for k, v in self.config.items() if k != 'budgetAuthorization'}),
            'alignedSha256': aligned_sha, 'boundaryOverrides': json.loads(overrides.read_text()),
            'judge': self.config['judge'], 'maxUnitSeconds': self.config['anchorPolicy']['maxUnitSeconds']})
        binding = {'productionRunId': 'a'*64, 'configurationSha256': identity, 'codeIdentitySha256': 'c'*64,
                   'budgetRoot': str(self.root / '.rebuilt.judge-budget')}
        bounds = {'requests': 20, 'wallTimeMs': 6000000, 'costMicrousd': 10000000}
        limits = dict(budget.text_limits.DEFAULT_REQUEST_LIMITS)
        approval = self.root / 'rebuild-approval.json'
        approval.write_text(json.dumps({'schemaVersion': 'sermon-source-budget-approval-v1',
            'binding': {**binding, 'globalBounds': bounds, 'requestLimits': limits}, 'humanApproval': True,
            'decision': 'approved', 'operatorEvidence': 'fixture', 'reviewedBy': 'fixture', 'reviewedAt': '2026-10-04T00:00:00Z'}))
        authorization = self.root / 'rebuild-budget.json'
        authorization.write_text(json.dumps({'schemaVersion': 'sermon-source-budget-authorization-v1', 'binding': binding,
            'authority': {'approvalSha256': subject._sha(approval), 'globalBounds': bounds, 'requestLimits': limits},
            'approvalReceipt': approval.name}))
        return overrides, out, authorization

    def test_rebuild_reanchors_and_rejudges_from_frozen_alignment_without_asr(self):
        self.execute()
        base = self.root / 'source'
        aligned_sha = json.loads((base / 'alignment-receipt.json').read_text())['alignedSha256']
        overrides, out, authorization = self.rebuild_inputs(aligned_sha)
        self.calls.clear()
        result = subject.rebuild(self.path, base, out, overrides, authorization, api_key='', transport=self.transport)
        self.assertTrue(self.calls and all(not c.endswith('/transcriptions') for c in self.calls))
        self.assertFalse(result['productionEligible'])
        self.assertTrue((out / 'english-source-candidate.json').is_file())
        self.assertFalse(json.loads((out / 'rebuild-receipt.json').read_text())['asrOrMfaRerun'])

    def test_shared_judge_cache_root_replays_an_unchanged_rebuild_without_judge_calls(self):
        self.config.update(schemaVersion=subject.SCHEMA_V2, asrWorkers=1, judgeCacheRoot='judge-cache')
        self.rebind_budget()
        self.execute()
        self.assertTrue(any(not c.endswith('/transcriptions') for c in self.calls))
        self.assertTrue(list((self.root / 'judge-cache' / 'cache').glob('english-source-judge-*.json')))
        base = self.root / 'source'
        self.assertFalse((base / 'judge-requests' / 'cache').exists())
        aligned_sha = json.loads((base / 'alignment-receipt.json').read_text())['alignedSha256']
        overrides, out, authorization = self.rebuild_inputs(aligned_sha)
        self.calls.clear()
        result = subject.rebuild(self.path, base, out, overrides, authorization, api_key='', transport=self.transport)
        # Same sentences, units and policy: every batch replays from the shared cache, nothing is paid.
        self.assertEqual(self.calls, [])
        self.assertEqual(result['machineJudgeStatus'], 'approved_for_layer2_shadow')
        self.assertTrue((out / 'english-source-candidate.json').is_file())

    def test_asr_concurrency_allows_one_worker_per_chunk(self):
        self.config.update(schemaVersion=subject.SCHEMA_V2, asrWorkers=14)
        self.rebind_budget()
        self.assertEqual(subject.load_configuration(self.path).value['asrWorkers'], 14)
        self.config['asrWorkers'] = subject.MAX_ASR_WORKERS + 1
        self.rebind_budget()
        with self.assertRaisesRegex(ValueError, 'invalid_source_asr_concurrency'):
            subject.load_configuration(self.path)

    def test_ambiguous_numeral_is_reported_right_after_asr_and_stops_before_mfa(self):
        def transport(endpoint, body, content_type, key):
            if endpoint.endswith('/transcriptions'):
                self.calls.append(endpoint)
                return {'text': 'It cost $1.5 million in 2nd place.'}
            return self.transport(endpoint, body, content_type, key)
        aligned = []
        def align(references, clip, out, **kwargs):
            aligned.append(references)
            return self.align(references, clip, out, **kwargs)
        with self.assertRaisesRegex(ValueError, 'source_ambiguous_numeric_reference_configure_spoken_forms'):
            subject.execute(self.path, api_key='', transport=transport, aligner=align, mfa_preflight=self.preflight)
        report = json.loads((self.root / 'source' / 'numeric-references.json').read_text())
        # Two 180 s chunks transcribe the same fixture text, so each token is reported per chunk.
        self.assertEqual([row['token'] for row in report['ambiguousTokens']], ['$1.5', '2nd'] * 2)
        self.assertEqual(len({row['referenceChunkId'] for row in report['ambiguousTokens']}), 2)
        self.assertEqual(report['status'], 'ambiguous_tokens_need_spoken_forms')
        self.assertEqual(aligned, [])
        self.assertFalse((self.root / 'source' / 'mfa-started.json').exists())
        # ASR was paid once and is not repeated by the stop.
        self.assertEqual(len(self.calls), 2)

    def test_preflight_drift_between_attempts_is_recorded_not_fatal(self):
        out = self.root / 'source'
        out.mkdir()
        (out / 'mfa-preflight.json').write_text(json.dumps({'schemaVersion': 1, 'backend': 'macbook-local',
                                                              'runtime': {'testOnly': True, 'stale': 'environment'}}))
        result = self.execute()
        self.assertEqual(result['reason'], 'human_source_review_required')
        self.assertEqual(json.loads((out / 'mfa-preflight.json').read_text()), self.preflight())
        history = (out / 'mfa-preflight-history.ndjson').read_text().splitlines()
        self.assertEqual(len(history), 1)
        self.assertIn('stale', history[0])

    def test_pcm_start_shortfall_within_ten_milliseconds_is_tolerated(self):
        for frames, ok in ((16000 - 64, True), (16000 - 160, True), (16000 - 161, False), (16000 + 2, False)):
            with self.subTest(frames=frames):
                output = self.root / f'pcm-{frames}.wav'
                with wave.open(str(output), 'wb') as stream:
                    stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(16000)
                    stream.writeframes(b'\0\0' * frames)
                if ok:
                    subject._validate_pcm(output, 1)
                else:
                    with self.assertRaisesRegex(ValueError, 'duration_changed'):
                        subject._validate_pcm(output, 1)

    def test_reuse_budget_roots_replay_returned_asr_for_the_same_audio_and_refuse_other_audio(self):
        self.config.update(schemaVersion=subject.SCHEMA_V2, asrWorkers=1)
        self.rebind_budget()
        self.execute()
        paid_asr = sum(c.endswith('/transcriptions') for c in self.calls)
        self.assertEqual(paid_asr, 2)
        # A second configuration of the same source and window names the first root.
        self.config.update(jobRoot=str(self.root / 'jobs-2'), outputDirectory=str(self.root / 'source-2'),
                           reuseBudgetRoots=['.jobs.source-budget'])
        self.rebind_budget(budget_root=self.root / '.jobs-2.source-budget')
        inspection = subject.inspect(self.path)
        self.assertEqual(inspection['reuseBudgetRoots'], [str(self.root / '.jobs.source-budget')])
        self.calls.clear()
        result = self.execute()
        self.assertEqual(result['reason'], 'human_source_review_required')
        self.assertEqual([c for c in self.calls if c.endswith('/transcriptions')], [])
        # The judge is not replayed across roots: it ran again under this root's own cap.
        self.assertTrue(any(not c.endswith('/transcriptions') for c in self.calls))
        ledger = json.loads((self.root / '.jobs-2.source-budget' / 'source-budget.json').read_text())
        asr_rows = {k: v for k, v in ledger['requests'].items() if k.startswith('asr.')}
        judge_rows = {k: v for k, v in ledger['requests'].items() if k.startswith('judge.')}
        self.assertEqual(len(asr_rows), 2)
        self.assertTrue(all(row['settlement']['costStatus'] == 'reused' and row['settlement']['costMicrousd'] == 0
                            for row in asr_rows.values()))
        self.assertTrue(judge_rows and all(row['settlement']['costStatus'] != 'reused' for row in judge_rows.values()))
        self.assertEqual(ledger['reuseBudgetRoots'], [str(self.root / '.jobs.source-budget')])
        # A third configuration with another window has other audio behind the same operation: refused, not re-bought.
        self.config.update(jobRoot=str(self.root / 'jobs-3'), outputDirectory=str(self.root / 'source-3'),
                           window={'startSeconds': 0, 'endSeconds': 180.5})
        self.approval.write_text(json.dumps({**json.loads(self.approval.read_text()), 'endTime': '00:03:00.500'}))
        self.config['windowApprovalSha256'] = subject._sha(self.approval)
        self.rebind_budget(budget_root=self.root / '.jobs-3.source-budget')
        self.calls.clear()
        with self.assertRaisesRegex(ValueError, 'source_reuse_identity_changed'):
            self.execute()
        self.assertEqual([c for c in self.calls if c.endswith('/transcriptions')], [])

    def use_v2_authorization(self):
        """Rewrite the fixture's v1 authorization as v2: code identity becomes evidence, not binding."""
        authorization_path = self.root / 'budget.json'
        authorization = json.loads(authorization_path.read_text())
        code_identity = authorization['binding'].pop('codeIdentitySha256')
        authorization['schemaVersion'] = subject.AUTHORIZATION_V2
        authorization['evidence'] = {'codeIdentitySha256AtApproval': code_identity}
        approval_path = self.root / 'budget-approval.json'
        approval = json.loads(approval_path.read_text())
        approval['schemaVersion'] = subject.APPROVAL_V2
        approval['binding'].pop('codeIdentitySha256')
        approval_path.write_text(json.dumps(approval))
        authorization['authority']['approvalSha256'] = subject._sha(approval_path)
        authorization_path.write_text(json.dumps(authorization))

    def attempts(self):
        path = self.root / 'source' / 'source-run-attempts.ndjson'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_v2_authorization_binds_run_and_bounds_and_keeps_code_identity_as_evidence(self):
        self.use_v2_authorization()
        config = subject.load_configuration(self.path)
        self.assertEqual(config.authorization_version, subject.AUTHORIZATION_V2)
        self.assertEqual(subject.inspect(self.path)['authorizationVersion'], subject.AUTHORIZATION_V2)
        self.assertEqual(self.execute()['reason'], 'human_source_review_required')
        self.assertEqual([row['event'] for row in self.attempts()], ['attempt_started'])
        self.assertEqual(self.attempts()[0]['codeIdentitySha256'], 'c' * 64)
        # A later attempt with other code resumes the same output under the same authorization.
        self.patch.stop()
        self.patch = patch.object(subject.code, 'code_identity', return_value='d' * 64)
        self.patch.start()
        self.calls.clear()
        self.assertEqual(self.execute()['reason'], 'human_source_review_required')
        self.assertEqual(self.calls, [])
        self.assertEqual([row['codeIdentitySha256'] for row in self.attempts()], ['c' * 64, 'd' * 64])
        self.assertEqual(json.loads((self.root / 'source' / 'source-run.json').read_text())['codeIdentitySha256'], 'c' * 64)

    def drifting_transport(self, flip_at):
        state = {'count': 0}
        def transport(endpoint, body, content_type, key):
            state['count'] += 1
            if state['count'] == flip_at:
                self.patch.stop()
                self.patch = patch.object(subject.code, 'code_identity', return_value='e' * 64)
                self.patch.start()
            return self.transport(endpoint, body, content_type, key)
        return transport

    def test_code_drift_during_a_v2_run_is_recorded_and_the_judge_completes(self):
        self.use_v2_authorization()
        result = self.execute(transport=self.drifting_transport(flip_at=2))
        self.assertEqual(result['reason'], 'human_source_review_required')
        self.assertEqual(len(self.calls), 3)
        events = [row['event'] for row in self.attempts()]
        self.assertEqual(events, ['attempt_started', 'code_identity_drift_observed'])
        drift = self.attempts()[1]
        self.assertEqual((drift['startedWith'], drift['onDisk']), ('c' * 64, 'e' * 64))

    def test_v1_authorization_still_aborts_on_code_drift_during_the_run(self):
        with self.assertRaisesRegex(ValueError, 'binding_changed'):
            self.execute(transport=self.drifting_transport(flip_at=2))
        self.assertLess(len(self.calls), 3)

    def review_flow_config(self):
        second = self.root / 'second-transcript.txt'
        second.write_text('Jesus is worthy. Jesus is mighty.')
        self.config.update(schemaVersion=subject.SCHEMA_V2, asrWorkers=1, reviewConfirmation='confirmation.json',
                           crossCheckTranscripts=[{'path': str(second), 'sha256': subject._sha(second), 'label': 'second'}])
        self.rebind_budget()

    def confirm(self, *, simulation, decision, checks='approved', sheet_sha=None):
        from tongxing_production.source import review_sheet
        sheet_path = self.root / 'source' / 'review-sheet.json'
        sheet = json.loads(sheet_path.read_text())
        value = review_sheet.confirmation_template(sheet, sheet_sha or subject._sha(sheet_path))
        value.update(simulation=simulation, humanApproval=not simulation, confirmedBy='fixture operator',
                     confirmedAt='2026-10-22T00:00:00+00:00', checks={k: checks for k in review_sheet.CHECKS})
        text = [i for i in sheet['items'] if i['kind'] == 'text_correction']
        value['decisions'][text[0]['id']] = decision
        (self.root / 'confirmation.json').write_text(json.dumps(value))
        return text[0]

    def test_review_flow_writes_one_sheet_then_recomputes_only_the_confirmed_row(self):
        self.review_flow_config()
        first = self.execute()
        self.assertEqual(first['status'], 'awaiting_confirmation')
        self.assertEqual(first['counts']['textContent'], 1)
        for name in ('review-sheet.json', 'review-sheet.md', 'review-confirmation.template.json'):
            self.assertTrue((self.root / 'source' / name).is_file(), name)
        speculative_judge = sum(not c.endswith('/transcriptions') for c in self.calls)
        self.assertGreater(speculative_judge, 0)
        item = self.confirm(simulation=False, decision={'action': 'take_alternative'})
        self.assertEqual((item['asr'], item['alternative']), ('worthy.', 'mighty.'))
        self.calls.clear()
        final = self.execute()
        self.assertEqual(final['status'], 'succeeded', final)
        self.assertTrue(final['productionEligible'])
        self.assertEqual(final['changedRows'], [item['row']])
        # ASR replays from the ledger; only the changed row's judge batch is new.
        self.assertEqual([c for c in self.calls if c.endswith('/transcriptions')], [])
        self.assertEqual(len(self.calls), 1)
        review = json.loads((self.root / 'source' / 'english-source-review.json').read_text())
        self.assertTrue(review['humanApproval'])
        self.assertEqual(review['reviewedBy'], 'fixture operator')
        derivation = json.loads((self.root / 'source' / 'review-derivation.json').read_text())
        self.assertTrue(derivation['check']['withinConfirmation'])
        package = json.loads((self.root / 'source' / 'english-source-package.json').read_text())
        self.assertEqual(package['status'], 'ready_for_translation')
        provenance = json.loads((self.root / 'source' / 'source-text-review-provenance.json').read_text())
        self.assertEqual(provenance['patchCount'], 1)

    def test_simulated_confirmation_recomputes_but_writes_no_approval(self):
        self.review_flow_config()
        self.execute()
        self.confirm(simulation=True, decision={'action': 'take_alternative'})
        result = self.execute()
        self.assertEqual((result['status'], result['reason']), ('blocked', 'simulated_confirmation_applied'))
        self.assertFalse(result['humanApprovalCreated'])
        self.assertFalse((self.root / 'source' / 'english-source-review.json').exists())
        corrections = json.loads((self.root / 'source' / 'derived' / 'source-text-corrections.json').read_text())
        self.assertFalse(corrections['humanApproval'])
        derivation = json.loads((self.root / 'source' / 'review-derivation-simulated.json').read_text())
        self.assertEqual((derivation['humanApproval'], derivation['englishReview']), (False, None))
        # The same decisions, now confirmed by a person, complete in the same output directory.
        self.confirm(simulation=False, decision={'action': 'take_alternative'})
        self.calls.clear()
        confirmed = self.execute()
        self.assertEqual(confirmed['status'], 'succeeded', confirmed)
        self.assertEqual(self.calls, [])

    def test_confirmation_must_name_this_sheet_decide_every_item_and_every_check(self):
        self.review_flow_config()
        self.execute()
        self.confirm(simulation=False, decision={'action': 'keep'}, sheet_sha='0' * 64)
        with self.assertRaisesRegex(ValueError, 'for_another_sheet'):
            self.execute()
        self.confirm(simulation=False, decision={'action': 'keep'}, checks='pending')
        with self.assertRaisesRegex(ValueError, 'checks_undecided'):
            self.execute()
        self.confirm(simulation=False, decision={'action': 'rewrite'})
        with self.assertRaisesRegex(ValueError, 'decision_invalid'):
            self.execute()
        self.confirm(simulation=True, decision={'action': 'keep'})
        value = json.loads((self.root / 'confirmation.json').read_text())
        value['humanApproval'] = True
        (self.root / 'confirmation.json').write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'label_invalid'):
            self.execute()

    def test_recomputation_outside_the_confirmed_rows_writes_no_approval(self):
        from tongxing_production.source import review_sheet
        self.review_flow_config()
        self.execute()
        self.confirm(simulation=False, decision={'action': 'take_alternative'})
        original = review_sheet.derive
        def narrowed(*args, **kwargs):
            derived = original(*args, **kwargs)
            return {**derived, 'rowsWithChangedText': []}
        with patch.object(review_sheet, 'derive', side_effect=narrowed):
            result = self.execute()
        self.assertEqual(result['reason'], 'source_review_derivation_outside_confirmation')
        self.assertFalse((self.root / 'source' / 'english-source-review.json').exists())

    def test_rebuild_rejects_overrides_for_another_alignment(self):
        self.execute()
        overrides, out, authorization = self.rebuild_inputs('b' * 64)
        with self.assertRaisesRegex(ValueError, 'invalid_boundary_overrides'):
            subject.rebuild(self.path, self.root / 'source', out, overrides, authorization, api_key='', transport=self.transport)

    def test_legacy_source_configuration_cannot_silently_expand_judge_concurrency(self):
        self.config['judge']['workers'] = 8
        self.path.write_text(json.dumps(self.config))
        with self.assertRaisesRegex(ValueError, 'invalid_source_judge_configuration'):
            subject.load_configuration(self.path)
        self.assertEqual(self.calls, [])

    def test_actual_producers_create_only_human_pending_source_and_resume_without_api(self):
        result = self.execute()
        self.assertEqual(result['reason'], 'human_source_review_required')
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(result['kind'], 'english_source_candidate')
        self.assertFalse(result['productionEligible'])
        self.assertEqual(result['chunkCount'], 2)
        self.assertEqual(len(self.calls), 3)
        candidate = json.loads(Path(result['candidatePath']).read_text())
        self.assertFalse(candidate['translationEligible'])
        self.assertFalse(candidate['review']['humanApproval'])
        before = [(p, p.read_bytes()) for p in (self.root / 'source/chunks').glob('*.asr-final.json')]
        self.calls.clear()
        self.assertEqual(self.execute(), result)
        self.assertEqual(self.calls, [])
        self.assertTrue(all(p.read_bytes() == raw for p, raw in before))

    def test_second_chunk_unknown_preserves_first_and_never_blindly_retries(self):
        calls = []
        def fail_second(endpoint, body, content_type, key):
            calls.append(endpoint)
            if len(calls) == 2:
                raise TimeoutError('synthetic unknown')
            return {'text': 'Jesus is worthy.'}
        with self.assertRaises(TimeoutError):
            self.execute(fail_second)
        first = self.root / 'source/chunks/0000.asr-final.json'
        self.assertTrue(first.is_file())
        with self.assertRaisesRegex(ValueError, 'source_provider_outcome_unknown'):
            self.execute(fail_second)
        self.assertEqual(len(calls), 2)
        self.assertFalse((self.root / 'source/english-source-candidate.json').exists())

    def test_sol_source_judge_budget_is_bounded_for_api(self):
        from tongxing_production.source import budget
        from tongxing_production.compute import provider_limits as limits
        from tongxing_production.source import english_source_judge as judge
        request = {'model': 'gpt-6.1-sol', 'reasoning_effort': 'high',
            'messages': [{'role': 'user', 'content': 'synthetic source'}],
            'response_format': {'type': 'json_schema', 'json_schema': {
                'name': 'english_source_machine_judge', 'strict': True, 'schema': judge._response_schema()}}}
        with budget.judge_limits(limits.DEFAULT_REQUEST_LIMITS):
            bounded = budget.bound_judge_payload(request)
        self.assertEqual(bounded['max_completion_tokens'], 4096)
        self.assertEqual(bounded['service_tier'], 'default')

    def test_mfa_preflight_failure_makes_zero_provider_calls(self):
        def failed(**kwargs):
            raise RuntimeError('No MFA runtime')
        with self.assertRaisesRegex(RuntimeError, 'No MFA'):
            self.execute(preflight=failed)
        self.assertEqual(self.calls, [])
        self.assertFalse((self.root / '.jobs.source-budget').exists())

    def test_diarized_turns_remain_anonymous_and_in_order(self):
        response = {'text': 'Hello. Welcome.', 'segments': [
            {'start': 0, 'end': 1, 'text': 'Hello.', 'speaker': 'Eric'},
            {'start': 1, 'end': 2, 'text': 'Welcome.', 'speaker': 'Steve'}]}
        rows = subject._reference_rows(response, 0, 0, 180)
        self.assertEqual([r['speakerId'] for r in rows], ['chunk-0000-anonymous-001', 'chunk-0000-anonymous-002'])
        self.assertNotIn('Eric', json.dumps(rows))
        self.assertNotIn('Steve', json.dumps(rows))
        self.assertEqual([r['text'] for r in rows], ['Hello.', 'Welcome.'])

    def test_returned_raw_requires_explicit_reconciliation_then_resumes_partial_chunks(self):
        original = budget.SourceBudget._locked
        # Simulate a crash in verify after preserving the second raw response.
        seen = {'responses': 0, 'failed': False}
        real_load = subject.load_configuration
        def drift(path):
            response_root = self.root / '.jobs.source-budget/responses'
            count = len(list(response_root.glob('*.json'))) if response_root.exists() else 0
            if count == 2 and not seen['failed']:
                seen['failed'] = True
                raise ValueError('synthetic crash after raw return')
            return real_load(path)
        with patch.object(subject, 'load_configuration', side_effect=drift):
            with self.assertRaisesRegex(ValueError, 'synthetic crash'):
                self.execute()
        self.assertEqual(len(self.calls), 2)
        config = subject.load_configuration(self.path)
        ledger_path = config.budget_root / 'source-budget.json'
        ledger = jobs._read(ledger_path)
        row = ledger['requests']['asr.0001']
        self.assertEqual(row['status'], 'started_response_unconfirmed')
        with self.assertRaisesRegex(ValueError, 'source_provider_outcome_unknown'):
            self.execute()
        resolver = budget.SourceBudget(config.budget_root, config.authority, verify=lambda: None)
        result = resolver.reconcile_returned('asr.0001', row['identitySha256'])
        self.assertFalse(result['reservationReleased'])
        completed = self.execute()
        self.assertEqual(completed['reason'], 'human_source_review_required')
        # Only the missing judge call is new; both ASR chunks are reused.
        self.assertEqual(len(self.calls), 3)

    def test_timeline_or_original_approval_drift_prevents_any_work(self):
        self.timeline.write_text('{}')
        with self.assertRaises(ValueError):
            self.execute()
        self.assertEqual(self.calls, [])
        self.assertFalse((self.root / 'source').exists())

    def test_pcm_nonzero_fractional_window_resampling_and_cached_validation(self):
        from types import SimpleNamespace
        media = self.root / '44100.wav'
        with wave.open(str(media), 'wb') as stream:
            stream.setnchannels(2); stream.setsampwidth(2); stream.setframerate(44100)
            stream.writeframes(b'\0' * 4 * 44100 * 3)
        config = SimpleNamespace(media=media, value={'mediaSha256': subject._sha(media)})
        for i, (start, duration) in enumerate([(0.123456, 1.234567), (1.9999, 0.9999), (0.5, 1/16000)]):
            output = self.root / f'pcm-{i}.wav'
            subject._audio(config, output, start, duration)
            subject._validate_pcm(output, duration)
            subject._audio(config, output, start, duration)
        output = self.root / 'bad-pcm.wav'
        with wave.open(str(output), 'wb') as stream:
            stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(16000)
            stream.writeframes(b'\0\0' * 16002)
        identity = {'mediaSha256': config.value['mediaSha256'], 'startSeconds': 0,
                    'durationSeconds': 1, 'sampleRate': 16000, 'channels': 1, 'sampleWidth': 2}
        output.with_suffix('.identity.json').write_text(json.dumps({'identity': identity, 'sha256': subject._sha(output)}))
        with self.assertRaisesRegex(ValueError, 'duration_changed'):
            subject._audio(config, output, 0, 1)
