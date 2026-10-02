"""Durable client failures/reconciliation over the actual synthetic worker."""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import sermon_accounting as accounting
from scripts import sermon_log_contract as logs
from scripts import sermon_mock_tts_control as control
from scripts import sermon_public_snapshot as public
from scripts import sermon_review_contracts as c
from tests import test_sermon_mock_tts_worker as fixtures


class MockTTSControlTests(fixtures.WorkerFixture):
    def setUp(self):
        super().setUp()
        self.policy = {'schemaVersion': control.POLICY,
            'units': {'zh-Hans.unit.001': 'zh-Hans', 'zh-Hans.unit.002': 'zh-Hans'},
            'maxJobs': 4, 'maxAttemptsPerUnit': 2, 'maxConcurrentJobs': 1,
            'workerTimeoutSeconds': 60, 'observationTimeoutSeconds': 45}
        self.client = control.MockTTSClient(self.scope, self.stream, self.policy, create=True)

    def test_actual_submit_observe_verify_and_repeated_key_no_new_dispatch(self):
        request, path = self.make_request()
        submitted = self.client.submit(path)
        self.assertTrue(submitted['newDispatch'])
        self.assertTrue(submitted['launchEntered'])
        observed = self.client.observe(path)
        self.assertEqual(observed['status'], 'succeeded')
        admitted = self.client.verify(path)
        self.assertEqual(admitted['admissionStatus'], 'verified_synthetic')
        before = (self.stream.directory/'events.jsonl').read_bytes()
        with patch.object(control.subprocess, 'run', side_effect=AssertionError('redispatch forbidden')):
            repeated = self.client.submit(path)
            self.assertFalse(repeated['newDispatch'])
            self.assertFalse(repeated['launchEntered'])
            self.assertEqual(self.client.observe(path), observed)
            self.assertEqual(self.client.verify(path), admitted)
        self.assertEqual(before, (self.stream.directory/'events.jsonl').read_bytes())
        events, errors = accounting.read_events(self.stream.directory); self.assertFalse(errors)
        self.assertEqual(logs.replay_integrity(events)['status'], 'consistent')
        states = [e['toState'] for e in events if e['event'] == 'step_state_changed']
        self.assertEqual(states, ['pending', 'ready', 'queued', 'running', 'succeeded'])

    def test_unqualified_larger_plan_is_rejected_before_any_launch(self):
        selected = deepcopy(self.policy)
        selected['units']['zh-Hans.unit.003'] = 'zh-Hans'
        selected['maxJobs'] = 6
        with patch.object(control.subprocess, 'run', side_effect=AssertionError('policy must prevent launch')) as launch:
            with self.assertRaisesRegex(c.ContractError, 'mock_tts_control_policy_invalid'):
                control.validate_policy(selected)
        launch.assert_not_called()
        self.assertFalse((self.scope/'jobs').exists())

    def test_capacity_rejection_is_known_before_launch(self):
        first, first_path = self.make_request(unit_id='zh-Hans.unit.002')
        self.client.submit(first_path)
        second, second_path = self.make_request()
        with patch.object(control.jobs, 'peek_job', return_value={'jobId': first['jobId'], 'status': 'running'}), \
                patch.object(control.subprocess, 'run', side_effect=AssertionError('capacity must prevent launch')) as launch:
            with self.assertRaisesRegex(control.SubmissionError, 'mock_tts_capacity_blocked') as caught:
                self.client.submit(second_path)
        self.assertFalse(caught.exception.launch_entered)
        launch.assert_not_called()
        self.assertFalse(self.client._intent_path(second).exists())
        self.assertEqual(self.wait(first)['status'], 'succeeded')

    def test_verified_gate_preserves_pending_human_and_reuses_original_proof(self):
        request, path = self.make_request()
        self.client.submit(path); self.client.observe(path)
        verified = self.client.verify_for_admission(path)
        gated = self.client.gate(path, verified)
        self.assertEqual(gated['gate']['admissionStatus'], 'admitted_synthetic')
        self.assertEqual(gated['gate']['reviewScope'], 'synthetic_fixture_bytes_only')
        self.assertEqual(gated['gate']['humanAcceptance'], 'pending')
        self.assertEqual(gated['gate']['listeningAcceptance'], 'not_performed')
        self.assertFalse(gated['gate']['productionEligible'])
        self.assertFalse(gated['gate']['formalAudioEligible'])
        self.assertFalse(gated['gate']['publicationAuthorized'])
        self.assertEqual(gated['completion']['dependsOn'], [verified['completion']['spanId']])
        before = (self.stream.directory/'events.jsonl').read_bytes()
        with patch.object(control.subprocess, 'run', side_effect=AssertionError('gate cannot dispatch')):
            self.assertEqual(self.client.gate(path, verified), gated)
        self.assertEqual(before, (self.stream.directory/'events.jsonl').read_bytes())

    def test_timeout_retains_original_job_then_reconciles_without_retry(self):
        request, path = self.make_request(delay=3)
        self.client.submit(path)
        unknown = self.client.observe(path, timeout_seconds=.01)
        self.assertEqual(unknown['status'], 'outcome_unknown')
        original = self.client._observation_path(request).read_bytes()
        retry, retry_path = self.make_request(attempt_number=2, retry_of=c.canonical_sha256(request))
        with self.assertRaises((c.ContractError, OSError)):
            self.client.submit(retry_path)
        self.assertEqual(self.wait(request)['status'], 'succeeded')
        with patch.object(control.subprocess, 'run', side_effect=AssertionError('reconciliation cannot dispatch')):
            result = self.client.reconcile(path)
            self.assertEqual(result['status'], 'succeeded')
            self.assertFalse(result['newDispatch'])
            self.assertEqual(self.client.reconcile(path), result)
            self.assertFalse(self.client.submit(path)['newDispatch'])
        self.assertEqual(self.client._observation_path(request).read_bytes(), original)
        self.assertFalse(self.client._intent_path(retry).exists())
        events, errors = accounting.read_events(self.stream.directory); self.assertFalse(errors)
        self.assertEqual(logs.replay_integrity(events)['status'], 'consistent')
        unknown_ends = [e for e in events if e['event'] == 'stage_finished'
            and e.get('attemptId') == unknown['observerAttemptId']]
        self.assertEqual([e['status'] for e in unknown_ends], ['outcome_unknown'])
        self.assertNotEqual(unknown['observerAttemptId'], request['attemptId'])

    def test_confirmed_failed_unit_retries_while_successful_neighbor_reuses(self):
        first, first_path = self.make_request(unit_id='zh-Hans.unit.002')
        self.client.submit(first_path); self.assertEqual(self.client.observe(first_path)['status'], 'succeeded')
        successful = self.client.verify(first_path)
        failed, failed_path = self.make_request(fault='fail_after_render')
        self.client.submit(failed_path); self.assertEqual(self.client.observe(failed_path)['status'], 'failed')
        with self.assertRaises(c.ContractError): self.client.verify(failed_path)
        retry, retry_path = self.make_request(attempt_number=2, retry_of=c.canonical_sha256(failed))
        self.client.submit(retry_path); self.assertEqual(self.client.observe(retry_path)['status'], 'succeeded')
        self.client.verify(retry_path)
        with patch.object(control.subprocess, 'run', side_effect=AssertionError('successful neighbor redispatch')):
            self.assertFalse(self.client.submit(first_path)['newDispatch'])
            self.assertEqual(self.client.verify(first_path), successful)
        self.assertEqual(len(list((self.scope/'jobs').glob('*/request.json'))), 3)
        self.assertEqual(public.read_snapshot(self.client._observation_path(failed))[0]['status'], 'failed')

    def test_idempotency_conflict_and_tampered_observation_fail_closed(self):
        request, path = self.make_request()
        self.client.submit(path); self.client.observe(path)
        changed = deepcopy(request); changed['fault']['queueDelaySeconds'] = .04
        original = path.read_bytes(); path.write_bytes(c.canonical_bytes(changed))
        with patch.object(control.subprocess, 'run', side_effect=AssertionError('conflicting dispatch')):
            with self.assertRaisesRegex(c.ContractError, 'idempotency_conflict'):
                self.client.submit(path)
        path.write_bytes(original)
        observation_path = self.client._observation_path(request)
        changed = public.read_snapshot(observation_path)[0]; changed['status'] = 'outcome_unknown'
        observation_path.write_bytes(c.canonical_bytes(changed))
        with self.assertRaisesRegex(c.ContractError, 'observer_terminal_required'):
            self.client.observe(path)


if __name__ == '__main__':
    unittest.main()
