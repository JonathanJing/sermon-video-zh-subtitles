"""Inert local side effects test the durable crash boundaries, without models."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from scripts import sermon_deterministic_controller as ctrl
from scripts import sermon_workflow_jobs as jobs
from scripts.sermon_production_supervisor import SupervisorConfig


class CrashWindowTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.marker = self.root / 'local-effect.txt'
        self.command = [sys.executable, '-c',
            "from pathlib import Path; import sys; p=Path(sys.argv[1]); p.write_text(p.read_text()+'x' if p.exists() else 'x')",
            str(self.marker)]

    def test_process_death_on_both_sides_of_success_receipt_never_replays_effect(self):
        program = '''
import json, os, sys
from pathlib import Path
from scripts import sermon_workflow_jobs as j
root, phase, command = Path(sys.argv[1]), sys.argv[2], json.loads(sys.argv[3])
identity = {'stage': phase}
job_id = j._digest(identity)
request = {'schemaVersion': j.SCHEMA, 'jobId': job_id, 'identity': identity,
           'command': command, 'commandSha256': j._digest(command), 'timeoutSeconds': 5.0}
with j._lock(root, job_id) as (folder, fd, held):
    assert held
    folder.mkdir()
    j._persist(folder / 'request.json', request)
    j._write_state(folder, job_id, 'queued', requestSha256=j._digest(request))
    original = j._write_state
    def receipt(folder, ident, status, **fields):
        if status == 'succeeded':
            if phase == 'after_receipt': original(folder, ident, status, **fields)
            os._exit(77)
        return original(folder, ident, status, **fields)
    j._write_state = receipt
    j._worker(root, job_id, os.dup(fd))
'''
        for phase, expected in (('before_receipt', 'uncertain'), ('after_receipt', 'succeeded')):
            with self.subTest(phase=phase):
                self.marker.unlink(missing_ok=True)
                root = self.root / phase
                result = subprocess.run([sys.executable, '-c', program, str(root), phase, json.dumps(self.command)],
                                        cwd=jobs.REPO_ROOT, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 77, result.stderr)
                self.assertEqual(self.marker.read_text(), 'x')
                ident = jobs._digest({'stage': phase})
                before = (root / ident / 'state.json').read_bytes()
                self.assertEqual(jobs.peek_job(root, ident)['status'], expected)
                self.assertEqual((root / ident / 'state.json').read_bytes(), before)
                with patch.object(jobs.subprocess, 'Popen') as spawn:
                    self.assertEqual(jobs.start_job(root, {'stage': phase}, self.command, 5)['status'], expected)
                spawn.assert_not_called()
                self.assertEqual(self.marker.read_text(), 'x')

    def test_controller_death_before_dispatch_and_after_worker_receipt_requires_reconciliation(self):
        for phase in ('before_dispatch', 'after_job_receipt'):
            with self.subTest(phase=phase):
                work = self.root / phase
                work.mkdir()
                config_path = work / 'release.json'; config_path.write_text('{}')
                config = SupervisorConfig('2026-09-20', 'fixture', work_root=work,
                                          release_workflow_config=config_path, gcs_bucket=None)
                controller = ctrl.Controller(config, mode='deterministic_execute')
                snapshot = {'workflowScope': 'page_release', 'workflowComplete': False,
                            'recommendedAction': {'action': 'build_page', 'humanActionRequired': False}}
                original = jobs._persist
                def persist(path, value):
                    if phase == 'after_job_receipt' and path.name == 'controller-state.json' and value.get('lastJob'):
                        raise KeyboardInterrupt('controller died before commit')
                    return original(path, value)
                def dispatch(*args, **kwargs):
                    if phase == 'before_dispatch': raise KeyboardInterrupt('controller died before launch')
                    receipt = jobs.start_job(controller.root, {'stage': phase}, self.command, 5)
                    deadline = time.monotonic() + 8
                    while time.monotonic() < deadline:
                        state = jobs.inspect_job(controller.root, receipt['jobId'])
                        if state['status'] == 'succeeded': return state
                        if state['status'] in {'failed', 'uncertain'}: self.fail(str(state))
                        time.sleep(.025)
                    self.fail('inert worker did not finish')
                with patch.object(ctrl.workflow, 'snapshot', return_value=snapshot), \
                     patch.object(ctrl.workflow, 'start_action', side_effect=dispatch), \
                     patch.object(jobs, '_persist', side_effect=persist):
                    with self.assertRaises(KeyboardInterrupt): controller.tick()
                restarted = ctrl.Controller(config, mode='deterministic_execute')
                with patch.object(ctrl.workflow, 'snapshot', return_value=snapshot), \
                     patch.object(ctrl.workflow, 'start_action') as dispatch_again:
                    result = restarted.tick()
                self.assertEqual(result['reasonCode'], 'intent_requires_reconciliation')
                dispatch_again.assert_not_called()
                if phase == 'before_dispatch': self.assertFalse(self.marker.exists())
                else: self.assertEqual(self.marker.read_text(), 'x')
