"""Real detached synthetic workers, valid WAV bytes, no provider/model calls."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from scripts import sermon_accounting as accounting
from scripts import sermon_completion as completion
from scripts import sermon_durable_accounting as durable
from scripts import sermon_log_contract as logs
from scripts import sermon_log_profile as profile
from scripts import sermon_mock_tts_contract as contract
from scripts import sermon_mock_tts_worker as worker
from scripts import sermon_public_snapshot as public
from scripts import sermon_review_contracts as c
from scripts import sermon_workflow_jobs as jobs


class WorkerFixture(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.scope = self.root/'control'; self.scope.mkdir()
        self.plan_sha = 'a'*64; self.run_id = 'b'*64
        self.stream = durable.open_stream(self.root/'accounting', scope_id='mock-worker-fixture',
            plan_sha256=self.plan_sha, production_run_id=self.run_id, purpose='mock_tts_test', create=True)
        self.enterContext(self.stream.context())
        self.policy = {'schemaVersion': 'sermon-mock-tts-control-policy-v1',
            'units': {'zh-Hans.unit.001': 'zh-Hans', 'zh-Hans.unit.002': 'zh-Hans'},
            'maxJobs': 4, 'maxAttemptsPerUnit': 2, 'maxConcurrentJobs': 1,
            'workerTimeoutSeconds': 60, 'observationTimeoutSeconds': 45}
        public.save_once(self.scope/'policy.json', self.policy)
        self.scope_value = {'schemaVersion': 'sermon-mock-tts-scope-v1', 'runId': self.run_id,
            'planSha256': self.plan_sha, 'implementationSha256': contract.implementation_sha256(),
            'policySha256': c.canonical_sha256(self.policy),
            'evidenceMode': 'synthetic', 'productionEligible': False}
        public.save_once(self.scope/'scope.json', self.scope_value)

    def make_request(self, *, fault='none', key=None, delay=0, unit_id='zh-Hans.unit.001',
                     attempt_number=1, retry_of=None):
        key = key or c.canonical_sha256({'fault': fault, 'delay': delay, 'unit': unit_id, 'attempt': attempt_number})
        request = {'schemaVersion': contract.REQUEST, 'evidenceMode': 'synthetic',
            'controlBatchSemantics': contract.BATCH, 'runId': self.run_id, 'planSha256': self.plan_sha,
            'unitId': unit_id, 'targetLocale': 'zh-Hans', 'inputSha256': 'c'*64,
            'revisionId': 'd'*64, 'attemptId': 'worker.'+key[:20], 'idempotencyKey': key,
            'implementationSha256': self.scope_value['implementationSha256'],
            'waveform': {'sampleRate': 16000, 'frames': 2400, 'seed': 7},
            'fault': {'mode': fault, 'queueDelaySeconds': .02, 'runDelaySeconds': delay},
            'workerTimeoutSeconds': self.policy['workerTimeoutSeconds'], 'attemptNumber': attempt_number, 'retryOfRequestSha256': retry_of, 'productionEligible': False, 'humanAcceptance': 'pending'}
        input_binding = {'schemaVersion': 'sermon-mock-tts-unit-input-v1', 'unitId': unit_id,
            'targetLocale': 'zh-Hans', 'sourceCanonicalSha256': 'e'*64, 'anchorCanonicalSha256': 'f'*64,
            'policySha256': 'a'*64, 'groupPlanSha256': 'a'*64, 'rubricSha256': 'b'*64,
            'pluginSha256': 'c'*64, 'reviewedGroupSha256': 'd'*64,
            'sourceUnitIds': ['source.unit.1'], 'utteranceSha256': 'b'*64}
        request['inputSha256'] = c.canonical_sha256(input_binding)
        request['jobId'] = contract.job_id(request)
        path = self.scope/'requests'/key/'mock-tts-request/request.json'
        path.parent.mkdir(parents=True, mode=0o700)
        public.save_once(path.parent.parent/'unit-input.json', input_binding)
        with profile.context(jobId=request['jobId'], revisionId=request['revisionId']):
            with accounting.stage_outcome('mock_tts.input_verified', work_unit_id='fixture.input',
                    attempt_id='input.'+key[:20], depends_on=[]) as attempt:
                attempt.finish('completed', artifact_sha256=request['inputSha256'])
            request['parentCompletion'] = completion.capture_synthetic(attempt.span_id,
                production_run_id=self.run_id, artifact_sha256=request['inputSha256'],
                artifact_kind='control_receipt', job_id=request['jobId'], revision_id=request['revisionId'])
        public.save_once(path, contract.validate_request(request))
        return request, path

    def submit(self, path):
        request = contract.read_request(path)
        (self.scope/'intents').mkdir(exist_ok=True)
        public.save_once(self.scope/'intents'/(request['idempotencyKey']+'.json'), contract.intent_for_request(request))
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'synthetic-do-not-inherit',
                'HTTP_PROXY': 'synthetic-do-not-inherit', 'UNAPPROVED_VARIABLE': 'synthetic'}):
            env = worker.environment(self.scope/'launcher')
        self.assertFalse({'OPENAI_API_KEY', 'HTTP_PROXY', 'UNAPPROVED_VARIABLE'} & set(env))
        result = subprocess.run([sys.executable, '-I', worker.__file__, 'submit', '--request', str(path),
            '--request-sha256', c.canonical_sha256(public.read_snapshot(path)[0])],
            env=env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def wait(self, request):
        end = time.monotonic() + request['workerTimeoutSeconds'] + 5
        while time.monotonic() < end:
            result = jobs.inspect_job(self.scope/'jobs', request['jobId'])
            if result['status'] not in {'queued', 'running'}:
                return result
            time.sleep(.03)
        self.fail('synthetic worker did not reach a terminal job state')


class MockTTSWorkerTests(WorkerFixture):
    def test_real_job_lifecycle_artifact_and_duplicate_submit(self):
        request, path = self.make_request()
        submitted = self.submit(path); self.assertEqual(submitted['jobId'], request['jobId'])
        final = self.wait(request); self.assertEqual(final['status'], 'succeeded')
        root = path.parent.parent/'worker'
        receipt = contract.validate_receipt(public.read_snapshot(root/'receipt.json')[0], request)
        self.assertEqual(contract.verify_wav(root/'fixture.wav', request, receipt['artifact']), receipt['artifact'])
        proof = public.read_snapshot(root/'completion.json')[0]
        events, errors = accounting.read_events(self.stream.directory); self.assertFalse(errors)
        previous = request['parentCompletion']['spanId']
        for phase in ('received', 'queued', 'worker'):
            handle = proof['handles'][phase]
            completion.validate_synthetic(handle, events, production_run_id=self.run_id,
                job_id=request['jobId'], revision_id=request['revisionId'], dependencies=[previous])
            previous = handle['spanId']
        self.assertEqual(logs.replay_integrity(events)['status'], 'consistent')
        self.assertFalse([e for e in events if e['event'].startswith('api_attempt')])
        self.assertTrue(all(e['evidenceMode'] == 'synthetic' for e in events))
        before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
        events_before = (self.stream.directory/'events.jsonl').read_bytes()
        self.assertEqual(self.submit(path), final)
        self.assertEqual(before, {p: p.read_bytes() for p in root.rglob('*') if p.is_file()})
        self.assertEqual(events_before, (self.stream.directory/'events.jsonl').read_bytes())

    def test_confirmed_failure_preserves_receipt_and_never_admits_output(self):
        for fault in ('fail_before_render', 'fail_after_render'):
            with self.subTest(fault=fault):
                request, path = self.make_request(fault=fault)
                self.submit(path); self.assertEqual(self.wait(request)['status'], 'failed')
                root = path.parent.parent/'worker'
                receipt = contract.validate_receipt(public.read_snapshot(root/'receipt.json')[0], request)
                self.assertEqual(receipt['status'], 'worker_failed')
                self.assertFalse((root/'completion.json').exists())
                before = (root/'receipt.json').read_bytes()
                self.assertEqual(self.submit(path)['status'], 'failed')
                self.assertEqual(before, (root/'receipt.json').read_bytes())

    def test_missing_invalid_and_hash_mismatched_wav_fail_verification(self):
        for fault in ('missing_artifact', 'invalid_wav', 'hash_mismatch'):
            with self.subTest(fault=fault):
                request, path = self.make_request(fault=fault)
                self.submit(path); self.assertEqual(self.wait(request)['status'], 'succeeded')
                root = path.parent.parent/'worker'
                receipt = contract.validate_receipt(public.read_snapshot(root/'receipt.json')[0], request)
                with self.assertRaises((c.ContractError, OSError)):
                    contract.verify_wav(root/'fixture.wav', request, receipt['artifact'])

    def test_request_and_parent_tamper_rejected_before_job(self):
        request, path = self.make_request()
        for field, value in (('evidenceMode', 'current_execution'), ('productionEligible', True),
                             ('jobId', 'f'*64), ('unexpected', 'private-value')):
            altered = deepcopy(request); altered[field] = value
            with self.subTest(field=field), self.assertRaises(c.ContractError):
                contract.validate_request(altered)
        changed = deepcopy(request); changed['parentCompletion']['privatePath'] = '/private/unapproved'
        with self.assertRaises(c.ContractError): contract.validate_request(changed)
        self.assertFalse((self.scope/'jobs').exists())


if __name__ == '__main__':
    unittest.main()
