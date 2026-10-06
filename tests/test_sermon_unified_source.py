import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import wave

from scripts import sermon_unified_source as subject
from scripts import sermon_source_budget as budget
from scripts import judge_english_source_for_translation as judge
from scripts import sermon_workflow_jobs as jobs


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
        from scripts.sermon_production_supervisor import stable_hash, json_digest
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
        from scripts import sermon_source_budget as budget
        from scripts import sermon_provider_limits as limits
        from scripts import judge_english_source_for_translation as judge
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
