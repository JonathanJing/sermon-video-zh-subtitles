import os
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import sermon_bounded_decision as decision
from scripts import sermon_decision_budget as subject
from scripts import sermon_workflow_jobs as jobs


def packet(remaining=2, revision='b' * 64):
    return decision.build_packet(productionRunId='a' * 64, stateRevision=revision, currentStage='L3',
        triggeringFailureCode='timing_repair_scope_ambiguous', affectedWorkUnits=['audio.ko'],
        allowedActions=['request_human_review'], evidenceRefs=['c' * 64], evidenceIdentitySha256='d' * 64,
        retryBudget={'remainingDecisionAttempts': remaining, 'maxTurns': 1},
        qualityGateSummary='pending_human', priorDecisionSummary=[])


def response(p):
    return dict(schemaVersion=decision.DECISION_SCHEMA, decisionId=p['decisionId'],
        stateRevision=p['stateRevision'], packetSha256=jobs._digest(p), selectedAction='request_human_review',
        affectedWorkUnits=['audio.ko'], reasonCode='human_evidence_needed', evidenceRefs=['c' * 64])


class DecisionBudgetTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'jobs'
        self.budget = subject.Budget(self.root, 'a' * 64)

    def propose(self, p, responder=response, **kwargs):
        return subject.propose(p, budget=self.budget, responder=responder,
                               fresh_packet=kwargs.get('fresh_packet', lambda: p))

    def test_read_only_budget_and_two_calls_survive_restart_without_replay(self):
        self.assertEqual(self.budget.remaining(), 2)
        self.assertFalse(self.root.exists())
        calls = []
        def respond(p):
            self.assertEqual(jobs._read(self.budget.folder / 'state.json')['attempts'][-1]['status'], 'reserved')
            calls.append(p['decisionId']); return response(p)
        first = packet()
        self.assertEqual(self.propose(first, respond)['status'], 'proposal_requires_locked_admission')
        self.budget = subject.Budget(self.root, 'a' * 64)
        self.assertEqual(self.budget.remaining(), 1)
        self.assertEqual(self.propose(first, respond)['reasonCode'], 'decision_budget_unavailable')
        self.assertEqual(self.propose(packet(1), respond)['status'], 'proposal_requires_locked_admission')
        self.assertEqual(self.budget.remaining(), 0)
        self.assertEqual(self.propose(packet(1, 'e' * 64), respond)['reasonCode'], 'decision_budget_unavailable')
        self.assertEqual(len(calls), 2)

    def test_unknown_outcome_blocks_new_revision_as_well_as_replay(self):
        calls = []
        def crash(p):
            calls.append(p); raise RuntimeError('PRIVATE ERROR')
        self.assertEqual(self.propose(packet(), crash)['reasonCode'], 'decision_outcome_unknown')
        self.budget = subject.Budget(self.root, 'a' * 64)
        self.assertEqual(self.budget.remaining(), 0)
        self.assertEqual(self.propose(packet(1, 'e' * 64), crash)['reasonCode'], 'decision_budget_unavailable')
        self.assertEqual(len(calls), 1)
        self.assertNotIn('PRIVATE', (self.budget.folder / 'state.json').read_text())

    def test_process_death_after_reservation_never_reopens_budget(self):
        program = '''
import json, os, sys
from scripts.sermon_decision_budget import Budget
p=json.loads(sys.argv[2]); assert Budget(sys.argv[1],p['productionRunId']).reserve(p)
os._exit(77)
'''
        result = subprocess.run([sys.executable, '-c', program, str(self.root), json.dumps(packet())],
                                cwd=jobs.REPO_ROOT, check=False)
        self.assertEqual(result.returncode, 77)
        self.assertEqual(self.budget.remaining(), 0)
        with patch('tests.test_sermon_decision_budget.response') as respond:
            self.assertFalse(self.budget.reserve(packet(1, 'e' * 64)))
            respond.assert_not_called()

    def test_concurrent_reservations_allow_only_one_worker(self):
        program = '''
import json,sys,time
from pathlib import Path
from scripts.sermon_decision_budget import Budget
p=json.loads(sys.argv[2]); deadline=time.monotonic()+5
while not Path(sys.argv[3]).exists():
    if time.monotonic()>deadline: raise RuntimeError('barrier timeout')
    time.sleep(.005)
print(json.dumps(Budget(sys.argv[1],p['productionRunId']).reserve(p)))
'''
        barrier = self.root.parent / 'go'
        children = [subprocess.Popen([sys.executable, '-c', program, str(self.root), json.dumps(packet()), str(barrier)],
                    cwd=jobs.REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
        try:
            barrier.write_text('start')
            results = []
            for child in children:
                out, err = child.communicate(timeout=10)
                self.assertEqual(child.returncode, 0, err); results.append(json.loads(out))
            self.assertEqual(sorted(results), [False, True])
        finally:
            for child in children:
                if child.poll() is None: child.kill(); child.wait()

    def test_corrupt_missing_or_migrated_state_is_never_reset(self):
        self.assertTrue(self.budget.reserve(packet()))
        path = self.budget.folder / 'state.json'; original = path.read_bytes()
        path.unlink()
        with self.assertRaises(OSError): self.budget.reserve(packet())
        path.write_text('{}')
        with self.assertRaises(ValueError): self.budget.reserve(packet())
        path.write_bytes(original)
        state = jobs._read(path); state['binding']['workflowDefinitionVersion'] = 'other-version'
        path.write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError, 'binding_changed'): self.budget.remaining()
        path.unlink(); self.budget.folder.rmdir()
        with self.assertRaisesRegex(ValueError, 'initialization_uncertain'): self.budget.remaining()

    def test_stale_evidence_does_not_call_or_create_budget_and_failed_receipt_never_retries(self):
        with patch('tests.test_sermon_decision_budget.response') as respond:
            result = self.propose(packet(), respond, fresh_packet=lambda: packet(2, 'e' * 64))
            self.assertEqual(result['reasonCode'], 'stale_state_before_reservation')
            respond.assert_not_called()
        self.assertFalse(self.root.exists())
        original = jobs._persist
        def persist(path, value):
            if value['attempts'][-1]['status'] == 'returned': raise OSError('disk full')
            return original(path, value)
        with patch.object(jobs, '_persist', side_effect=persist):
            result = self.propose(packet())
        self.assertEqual(result['reasonCode'], 'decision_return_not_durably_recorded')
        self.assertEqual(self.budget.remaining(), 0)
        self.assertFalse(result['dispatchEnabled'])

    def test_reservation_write_failure_happens_before_call_and_cannot_reset(self):
        with patch.object(jobs, '_persist', side_effect=OSError('disk full')), \
             patch('tests.test_sermon_decision_budget.response') as respond:
            with self.assertRaises(OSError): self.propose(packet(), respond)
            respond.assert_not_called()
        self.assertTrue(self.budget.folder.exists())
        with self.assertRaises(OSError): self.budget.reserve(packet())

    def test_directory_entries_are_durable_before_reservation_and_responder(self):
        self.root = self.root.parent / 'new-parent' / 'nested' / 'jobs'
        self.budget = subject.Budget(self.root, 'a' * 64)
        self.root = self.budget.root
        events = []
        original_sync, original_persist, original_fsync = jobs._sync_directory, jobs._persist, os.fsync
        required = [self.budget.lock_path.parent, self.root, self.root.parent,
                    self.root.parent.parent, self.root.parent.parent.parent]
        def sync(path):
            original_sync(path)
            events.append(('directory', path))
        def fsync(fd):
            original_fsync(fd)
            actual, lock = os.fstat(fd), self.budget.lock_path.stat()
            if (actual.st_dev, actual.st_ino) == (lock.st_dev, lock.st_ino):
                events.append(('lock', self.budget.lock_path))
        def persist(path, value):
            self.assertIn(('lock', self.budget.lock_path), events)
            for directory in required:
                self.assertIn(('directory', directory), events)
            original_persist(path, value)
            events.append(('state', value['attempts'][-1]['status']))
        def respond(p):
            self.assertIn(('state', 'reserved'), events)
            self.assertEqual(self.budget.remaining(), 0)
            events.append(('responder', None))
            return response(p)
        with patch.object(jobs, '_sync_directory', side_effect=sync), \
             patch.object(jobs, '_persist', side_effect=persist), \
             patch.object(os, 'fsync', side_effect=fsync):
            result = self.propose(packet(), respond)
        self.assertEqual(result['status'], 'proposal_requires_locked_admission')
        self.assertLess(events.index(('state', 'reserved')), events.index(('responder', None)))
        self.assertEqual(events[:6], [('lock', self.budget.lock_path)] + [('directory', p) for p in required])

    def test_preexisting_ancestors_are_synced_before_responder(self):
        self.root = (self.root.parent / 'concurrent-parent' / 'nested' / 'jobs').resolve()
        self.root.mkdir(parents=True)  # Another creator may not have synced yet.
        self.budget = subject.Budget(self.root, 'a' * 64)
        synced = []
        original = jobs._sync_directory
        def sync(path):
            original(path)
            synced.append(path)
        def respond(p):
            for directory in (self.root, self.root.parent, self.root.parent.parent,
                              self.root.parent.parent.parent):
                self.assertIn(directory, synced)
            return response(p)
        with patch.object(jobs, '_sync_directory', side_effect=sync):
            result = self.propose(packet(), respond)
        self.assertEqual(result['status'], 'proposal_requires_locked_admission')

    def test_each_directory_sync_failure_blocks_call_and_never_resets_evidence(self):
        for boundary in ('lock', 'locks-directory', 'root', 'parent'):
            with self.subTest(boundary=boundary):
                self.root = self.root.parent / boundary / 'jobs'
                self.budget = subject.Budget(self.root, 'a' * 64)
                self.root = self.budget.root
                original_sync, original_fsync = jobs._sync_directory, os.fsync
                fail_path = {'locks-directory': self.budget.lock_path.parent,
                             'root': self.root, 'parent': self.root.parent}.get(boundary)
                def sync(path):
                    if path == fail_path: raise OSError('injected metadata persistence failure')
                    original_sync(path)
                def fsync(fd):
                    if boundary == 'lock': raise OSError('injected lock persistence failure')
                    original_fsync(fd)
                with patch.object(jobs, '_sync_directory', side_effect=sync), \
                     patch.object(os, 'fsync', side_effect=fsync), \
                     patch('tests.test_sermon_decision_budget.response') as respond:
                    with self.assertRaises(OSError): self.propose(packet(), respond)
                    respond.assert_not_called()
                self.assertTrue(self.budget.folder.is_dir())
                self.assertTrue(self.budget.lock_path.is_file())
                with self.assertRaises(OSError): self.budget.reserve(packet())

    def test_run_binding_and_symlink_evidence_fail_closed(self):
        other = subject.Budget(self.root, 'e' * 64)
        with self.assertRaisesRegex(ValueError, 'run_mismatch'): other.reserve(packet())
        self.assertFalse(self.root.exists())
        self.assertTrue(self.budget.reserve(packet()))
        path = self.budget.folder / 'state.json'
        target = self.root.parent / 'state-copy.json'; target.write_bytes(path.read_bytes())
        path.unlink(); path.symlink_to(target)
        with self.assertRaises((OSError, ValueError)): self.budget.remaining()


if __name__ == '__main__':
    unittest.main()
