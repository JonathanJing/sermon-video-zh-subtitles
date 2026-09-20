import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from scripts.sermon_execution_harness import Execution, ExecutionTerminated, bounded_process
from scripts.sermon_model_resources import local_model_slot


class ParallelExecutionTests(unittest.TestCase):
    def test_worker_cancel_reaps_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            pidfile = Path(tmp) / 'pid'
            cancel = threading.Event()
            with ThreadPoolExecutor() as executor:
                future = executor.submit(bounded_process, [sys.executable, '-c',
                    'import os,time,pathlib;pathlib.Path(' + repr(str(pidfile)) + ').write_text(str(os.getpid()));time.sleep(60)'], timeout=10, cancel_event=cancel)
                deadline = time.monotonic() + 5
                while not pidfile.exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(pidfile.exists())
                pid = int(pidfile.read_text())
                cancel.set()
                with self.assertRaises(ExecutionTerminated): future.result(timeout=5)
                with self.assertRaises(ProcessLookupError): os.kill(pid, 0)

    def test_parallel_stage_receipts_preserve_both(self):
        with tempfile.TemporaryDirectory() as tmp:
            barrier = threading.Barrier(2)
            with Execution(tmp, 'abc') as execution:
                def branch(name):
                    with execution.stage(name): barrier.wait(timeout=3)
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [pool.submit(branch, name) for name in ('tts', 'align')]
                    for f in futures: f.result()
            report = json.loads((Path(tmp) / 'accounting/harness/latest.json').read_text())
            self.assertEqual({s['name'] for s in report['stages']}, {'tts', 'align'})
            self.assertTrue(all(s['status'] == 'completed' for s in report['stages']))

    def test_two_slots_third_waiter_cancels(self):
        snapshot = {'totalBytes':64*1024**3,'availableBytes':32*1024**3}
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'SERMON_LOCAL_MODEL_LOCK_ROOT':tmp,'SERMON_LOCAL_MODEL_SLOTS':'2'}), patch('scripts.sermon_model_resources.memory_snapshot', return_value=snapshot):
            cancel = threading.Event()
            with local_model_slot() as first, local_model_slot() as second:
                self.assertNotEqual(first['slot'], second['slot'])
                with ThreadPoolExecutor() as pool:
                    def wait():
                        with local_model_slot(cancel_event=cancel, timeout=5):
                            self.fail('Third model must not start')
                    future = pool.submit(wait)
                    cancel.set()
                    with self.assertRaises(ExecutionTerminated): future.result(timeout=2)
            with local_model_slot() as reused: self.assertEqual(reused['slot'], 0)

    def test_low_memory_does_not_admit_or_dispatch_remote(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'SERMON_LOCAL_MODEL_LOCK_ROOT':tmp}), patch('scripts.sermon_model_resources.memory_snapshot', return_value={'totalBytes':64*1024**3,'availableBytes':1}):
            with self.assertRaises(ExecutionTerminated):
                with local_model_slot(timeout=.02): self.fail('Low memory must queue')
