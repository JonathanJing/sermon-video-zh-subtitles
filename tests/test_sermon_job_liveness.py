"""Real process cleanup plus deterministic deadline/receipt fault injection."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from scripts import sermon_job_liveness as subject
from scripts import sermon_workflow_jobs as jobs
from tests import test_canonical_layer2_controller as fixtures

POLICY = {'schemaVersion': subject.SCHEMA, 'startTimeoutSeconds': .5,
          'heartbeatIntervalSeconds': .05, 'heartbeatTimeoutSeconds': .3,
          'noProgressTimeoutSeconds': .6}


class LivenessTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name); self.folder = self.root / 'job'; self.folder.mkdir()
        self.request = {'jobId': 'a'*64, 'livenessPolicy': POLICY}
        self.now = 0
        self.monitor = subject.Monitor(self.folder, self.request, clock=lambda: self.now)

    def save(self, sequence=1, progress=1, **fields):
        value = {'schemaVersion': subject.SCHEMA, 'jobId': self.request['jobId'],
                 'requestSha256': jobs._digest(self.request), 'sequence': sequence,
                 'progressSequence': progress, 'stage': 'model_request', 'phase': 'running', **fields}
        jobs._persist(self.folder / subject.FILE, value)

    def test_start_deadline_and_missing_completion_fail_closed(self):
        self.now = .51; self.monitor.poll()
        self.assertEqual(self.monitor.reason, 'liveness_start_timeout')
        monitor = subject.Monitor(self.folder, self.request)
        self.assertFalse(monitor.completed())
        self.assertEqual(monitor.reason, 'liveness_completion_receipt_missing')

    def test_live_heartbeats_cannot_hide_no_progress(self):
        self.save(); self.monitor.poll()
        for sequence in range(2, 5):
            self.now = .21 * (sequence - 1)
            self.save(sequence); self.monitor.poll()
        self.assertEqual(self.monitor.reason, 'liveness_no_progress_timeout')
        self.assertTrue(self.monitor.cancel.is_set())

    def test_touching_file_or_changing_wall_clock_cannot_extend_heartbeat(self):
        self.save(); self.monitor.poll()
        os.utime(self.folder / subject.FILE, (10**9, 10**9))
        self.now = .31; self.monitor.poll()
        self.assertEqual(self.monitor.reason, 'liveness_heartbeat_timeout')

    def test_progress_advances_while_heartbeat_is_only_liveness(self):
        self.save(); self.monitor.poll()
        self.now = .2; self.save(2); self.monitor.poll()
        self.now = .4; self.save(3, 2); self.monitor.poll()
        self.now = .6; self.save(4, 3, phase='finished'); self.monitor.poll()
        self.assertTrue(self.monitor.completed())
        self.assertIsNone(self.monitor.reason)

    def test_regression_conflicting_sequence_binding_and_nonfinite_values_block(self):
        for changes in ({'sequence': True}, {'sequence': 2**54}, {'progressSequence': 2},
                        {'requestSha256': 'b'*64}, {'jobId': 'b'*64}, {'phase': 'approved'},
                        {'stage': '../private'}, {'sequence': float('inf')}):
            with self.subTest(changes=changes):
                self.save()
                value = jobs._read(self.folder / subject.FILE); value.update(changes)
                (self.folder / subject.FILE).write_text(json.dumps(value))
                monitor = subject.Monitor(self.folder, self.request)
                monitor.poll()
                self.assertEqual(monitor.reason, 'liveness_invalid_receipt')
        self.save(3, 2); self.monitor = subject.Monitor(self.folder, self.request); self.monitor.poll()
        self.save(3, 2, stage='changed'); self.monitor.poll()
        self.assertEqual(self.monitor.reason, 'liveness_invalid_receipt')
        self.save(3, 2); self.monitor = subject.Monitor(self.folder, self.request); self.monitor.poll()
        self.save(2); self.monitor.poll()
        self.assertEqual(self.monitor.reason, 'liveness_invalid_receipt')

    def test_symlink_and_oversized_receipt_cannot_be_read(self):
        target = self.root / 'outside'; target.write_text('{}')
        path = self.folder / subject.FILE; path.symlink_to(target)
        self.monitor.poll(); self.assertEqual(self.monitor.reason, 'liveness_invalid_receipt')
        path.unlink(); path.write_text(' '* (subject.MAX_BYTES+1))
        monitor = subject.Monitor(self.folder, self.request)
        with patch.object(jobs, '_read') as read:
            monitor.poll()
        read.assert_not_called(); self.assertEqual(monitor.reason, 'liveness_invalid_receipt')

    def test_policy_is_finite_ordered_and_part_of_immutable_request(self):
        for changes in ({'heartbeatIntervalSeconds': True}, {'startTimeoutSeconds': float('nan')},
                        {'noProgressTimeoutSeconds': .1}, {'heartbeatTimeoutSeconds': 0},
                        {'unknown': 1}, {'schemaVersion': 'new'}):
            with self.subTest(changes=changes), patch.object(jobs.subprocess, 'Popen') as spawn:
                with self.assertRaises(ValueError):
                    jobs.start_job(self.root / 'jobs', {'stage':'bad'}, [sys.executable,'-c','pass'],
                                   1, liveness_policy={**POLICY, **changes})
                spawn.assert_not_called()
        self.assertFalse((self.root / 'jobs').exists())

    def test_reporter_persists_before_side_effect_and_write_failure_stops_checkpoints(self):
        with patch.object(jobs, '_persist', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError), subject.report(self.folder, self.request):
                self.fail('side effect before durable heartbeat')
        reporter = subject.Reporter(self.folder, self.request).start()
        reporter.error = OSError('heartbeat lost')
        try:
            with self.assertRaises(subject.LivenessError): reporter.progress('model_request')
            with self.assertRaises(subject.LivenessError): reporter.close(completed=True)
        finally:
            reporter.stop.set(); reporter.thread.join(timeout=1)
        self.assertEqual(jobs._read(self.folder / subject.FILE)['phase'], 'running')

    def test_background_persistence_failure_cannot_be_reported_finished(self):
        original = jobs._persist
        def disk_failure(path, value):
            if value['sequence'] > 1:
                raise OSError('heartbeat fsync failed')
            return original(path, value)
        with patch.object(jobs, '_persist', side_effect=disk_failure):
            reporter = subject.Reporter(self.folder, self.request).start()
            self.assertTrue(reporter.stop.wait(1))
            with self.assertRaises(subject.LivenessError):
                reporter.close(completed=True)
        self.assertEqual(jobs._read(self.folder / subject.FILE)['phase'], 'running')

    def test_deeply_nested_invalid_json_stops_monitor_instead_of_losing_watchdog(self):
        path = self.folder / subject.FILE
        path.write_text('[' * 2000 + '0' + ']' * 2000)
        self.monitor.poll()
        self.assertEqual(self.monitor.reason, 'liveness_invalid_receipt')

    def run_job(self, mode):
        policy = {**POLICY, 'startTimeoutSeconds': 1.5,
                  'heartbeatTimeoutSeconds': .7, 'noProgressTimeoutSeconds': 1.2}
        identity = {'stage': 'liveness_' + mode}
        job_id = jobs._digest(identity)
        root = self.root / mode
        late = self.root / (mode + '-late')
        program = '''
import sys,time
from pathlib import Path
from scripts import sermon_workflow_jobs as jobs
from scripts import sermon_job_liveness as liveness
folder,mode,late=Path(sys.argv[1]),sys.argv[2],Path(sys.argv[3])
if mode == 'no_start':
    time.sleep(5)
elif mode == 'no_finish':
    reporter=liveness.Reporter(folder,jobs._read(folder/'request.json')).start()
    reporter.close(completed=False)
else:
    with liveness.report(folder,jobs._read(folder/'request.json')) as reporter:
        if mode == 'no_progress':
            from scripts.sermon_execution_harness import bounded_process
            bounded_process([sys.executable,'-c',
                'import sys,time;from pathlib import Path;time.sleep(2);Path(sys.argv[1]).write_text("escaped")',
                str(late)], timeout=4)
        elif mode == 'no_heartbeat':
            reporter.stop.set(); reporter.thread.join()
            time.sleep(5)
        elif mode == 'invalid':
            reporter.stop.set(); reporter.thread.join()
            (folder/liveness.FILE).write_text('{}');time.sleep(5)
        else:
            for _ in range(4):
                time.sleep(.15);reporter.progress('returned_response')
late.write_text('finished')
'''
        command = [sys.executable, '-c', program, str(root/job_id), mode, str(late)]
        result = jobs.start_job(root, identity, command, 4, liveness_policy=policy)
        deadline = time.monotonic()+8
        while time.monotonic() < deadline:
            result = jobs.peek_job(root, job_id)
            if result['status'] not in jobs.ACTIVE: break
            time.sleep(.025)
        self.assertNotIn(result['status'], jobs.ACTIVE)
        self.assertEqual(jobs.start_job(root, identity, command, 4, liveness_policy=policy), result)
        with self.assertRaisesRegex(ValueError, 'different or invalid'):
            jobs.start_job(root, identity, command, 4, liveness_policy={**policy,'startTimeoutSeconds':1.7})
        return jobs._read(root/job_id/'state.json'), late

    def test_real_monitor_cancels_stalls_and_never_restarts_unknown_work(self):
        for mode, reason in (('no_start','liveness_start_timeout'),
                             ('no_progress','liveness_no_progress_timeout'),
                             ('no_heartbeat','liveness_heartbeat_timeout'),
                             ('invalid','liveness_invalid_receipt')):
            with self.subTest(mode=mode):
                state, late = self.run_job(mode)
                self.assertEqual(state['status'], 'uncertain')
                self.assertEqual(state['reason'], reason)
                if mode == 'no_progress':
                    time.sleep(2.1)  # A surviving descendant must not publish late.
                self.assertFalse(late.exists())

    def test_real_progress_completes_but_exit_zero_without_finished_receipt_does_not(self):
        state, late = self.run_job('progress')
        self.assertEqual(state['status'], 'succeeded'); self.assertTrue(late.exists())
        state, _ = self.run_job('no_finish')
        self.assertEqual(state['status'], 'uncertain')
        self.assertEqual(state['reason'], 'liveness_completion_receipt_missing')

    def test_fixed_l2_records_actual_progress_without_human_approval(self):
        fixture = fixtures.CanonicalLayer2ControllerTests('test_real_producer_and_plugin_create_only_human_pending_candidate')
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        with fixture.active() as (config, code, key, folder):
            stages = []
            original = subject.Reporter.progress
            def record(reporter, stage):
                stages.append(stage); return original(reporter, stage)
            with patch.object(subject.Reporter, 'progress', new=record):
                result = fixture.execute(config, code, key)
            saved = jobs._read(folder / subject.FILE)
            self.assertEqual(saved['phase'], 'finished')
            self.assertEqual(stages.count('model_request'), 4)
            self.assertEqual(stages.count('translator_response_saved'), 2)
            self.assertEqual(stages.count('reviewer_response_saved'), 2)
            self.assertIn('models_validated', stages); self.assertIn('candidate_validated', stages)
            self.assertFalse(result['releaseEligible'])
            self.assertEqual(saved['requestSha256'], jobs._digest(jobs._read(folder/'request.json')))

    def test_checkpoint_write_failure_preserves_returned_paid_response_before_raising(self):
        fixture = fixtures.CanonicalLayer2ControllerTests('test_real_producer_and_plugin_create_only_human_pending_candidate')
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        original = subject.Reporter.progress
        def fail_after_response(reporter, stage):
            if stage == 'translator_response_saved':
                raise OSError('checkpoint disk failure')
            return original(reporter, stage)
        with fixture.active() as (config, code, key, folder):
            with patch.object(subject.Reporter, 'progress', new=fail_after_response):
                with self.assertRaisesRegex(OSError, 'checkpoint disk failure'):
                    fixture.execute(config, code, key)
            self.assertEqual(len(fixture.calls), 1)
            raw = fixture.output / 'group-0001-astra.raw.json'
            parsed = fixture.output / 'group-0001-astra.json'
            self.assertEqual(jobs._read(raw)['response']['id'], jobs._read(parsed)['requestId'])
            self.assertFalse((fixture.output / 'candidate.json').exists())
            self.assertEqual(jobs._read(folder / subject.FILE)['phase'], 'running')


if __name__ == '__main__': unittest.main()
