"""Fault injection with local processes only; no model, SSH or publication calls."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from scripts.sermon_execution_harness import (
    Execution, RemoteOutcomeUnknown, WorkAlreadyRunning, bounded_process, work_lock,
)

ROOT = Path(__file__).resolve().parents[1]


def wait_for(predicate, *, timeout=6):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.03)
    raise AssertionError("Local process condition did not become true before deadline")


def alive(pid):
    result = subprocess.run(["ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True)
    # A reparented zombie cannot execute or retain a lock. Its reaping is OS-owned.
    state = result.stdout.strip()
    return result.returncode == 0 and bool(state) and not state.startswith("Z")


@unittest.skipUnless(os.name == "posix", "Harness process locks require POSIX")
class ExecutionHarnessProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.work = self.folder / "work"
        self.work.mkdir()
        self.processes = []
        self.groups = []
        self.addCleanup(self.cleanup_processes)

    def cleanup_processes(self):
        for group in self.groups:
            try:
                os.killpg(group, signal.SIGKILL)
            except ProcessLookupError:
                pass
        for process in self.processes:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)

    def script(self, name, code):
        path = self.folder / name
        path.write_text(code)
        return path

    def launch(self, script, *args):
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        process = subprocess.Popen([sys.executable, str(script), *map(str, args)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   env=env)
        self.processes.append(process)
        return process

    def test_symlink_and_canonical_paths_compete_for_same_lock(self):
        alias = self.folder / "alias"
        alias.symlink_to(self.work, target_is_directory=True)
        ready = self.folder / "ready"
        owner = self.script("owner.py", """
from pathlib import Path
import sys, time
from scripts.sermon_execution_harness import work_lock
with work_lock(sys.argv[1]):
    Path(sys.argv[2]).write_text('ready')
    time.sleep(30)
""")
        process = self.launch(owner, alias, ready)
        wait_for(ready.exists)
        for target in (self.work, alias, self.work / ".." / "work"):
            with self.subTest(path=str(target)):
                with self.assertRaises(WorkAlreadyRunning):
                    with work_lock(target):
                        self.fail("Second writer acquired a held canonical lock")
        process.terminate()
        process.wait(timeout=5)
        with work_lock(self.work):
            pass
        self.assertEqual(len(list((self.folder / ".harness-locks").glob("*.lock"))), 1)

    def test_killed_owner_keeps_inherited_child_lock_until_child_exits(self):
        child_pid, release = self.folder / "child.pid", self.folder / "release"
        child = self.script("child.py", """
from pathlib import Path
import os, sys, time
Path(sys.argv[1]).write_text(str(os.getpid()))
while not Path(sys.argv[2]).exists():
    time.sleep(.03)
""")
        owner = self.script("owner.py", """
import sys
from scripts.sermon_execution_harness import work_lock, bounded_process
with work_lock(sys.argv[1]):
    bounded_process([sys.executable, sys.argv[2], sys.argv[3], sys.argv[4]], timeout=30)
""")
        process = self.launch(owner, self.work, child, child_pid, release)
        wait_for(lambda: child_pid.exists() and child_pid.read_text().strip().isdigit())
        pid = int(child_pid.read_text())
        self.groups.append(pid)  # bounded_process creates this child's new session.
        process.kill()
        process.wait(timeout=5)
        self.assertTrue(alive(pid))
        with self.assertRaises(WorkAlreadyRunning):
            with work_lock(self.work):
                self.fail("Killed owner released a still-active child's lock")
        release.write_text("finish")
        wait_for(lambda: not alive(pid))
        with work_lock(self.work):
            pass

    def test_timeout_kills_process_group_including_term_ignoring_grandchild(self):
        child_pid = self.folder / "child.pid"
        grand_pid = self.folder / "grand.pid"
        grand = self.script("grand.py", """
from pathlib import Path
import os, signal, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
Path(sys.argv[1]).write_text(str(os.getpid()))
time.sleep(30)
""")
        child = self.script("child.py", """
from pathlib import Path
import os, subprocess, sys, time
Path(sys.argv[1]).write_text(str(os.getpid()))
subprocess.Popen([sys.executable, sys.argv[2], sys.argv[3]])
time.sleep(30)
""")
        started = time.monotonic()
        try:
            with self.assertRaises(subprocess.TimeoutExpired):
                bounded_process([sys.executable, str(child), str(child_pid), str(grand), str(grand_pid)],
                                timeout=1.5, capture_output=True, text=True)
        finally:
            if child_pid.exists() and child_pid.read_text().strip().isdigit():
                self.groups.append(int(child_pid.read_text()))
        self.assertTrue(grand_pid.exists(), "Grandchild did not reach fault-injection readiness")
        self.assertLess(time.monotonic() - started, 8)
        for file in (child_pid, grand_pid):
            pid = int(file.read_text())
            wait_for(lambda: not alive(pid))

    def test_escaped_pipe_holder_cannot_hide_timeout_or_block_cleanup_forever(self):
        escaped_pid = self.folder / "escaped.pid"
        escaped = self.script("escaped.py", """
from pathlib import Path
import os, sys, time
Path(sys.argv[1]).write_text(str(os.getpid()))
time.sleep(30)
""")
        parent = self.script("spawner.py", """
import subprocess, sys, time
subprocess.Popen([sys.executable, sys.argv[1], sys.argv[2]], start_new_session=True)
time.sleep(30)
""")
        started = time.monotonic()
        try:
            with self.assertRaises(subprocess.TimeoutExpired):
                bounded_process([sys.executable, str(parent), str(escaped), str(escaped_pid)],
                                timeout=.5, capture_output=True, text=True)
            self.assertLess(time.monotonic() - started, 7)
            self.assertTrue(escaped_pid.exists())
        finally:
            # Escaped daemon is deliberately outside the harness group contract.
            if escaped_pid.exists():
                pid = int(escaped_pid.read_text())
                os.kill(pid, signal.SIGKILL)
                wait_for(lambda: not alive(pid))

    def test_guarded_nested_groups_cascade_when_intermediate_owner_is_killed(self):
        node = self.script("nested.py", """
from pathlib import Path
import json, os, signal, sys, time
from scripts.sermon_execution_harness import bounded_process
depth = int(sys.argv[1])
if depth == 1:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
Path(sys.argv[2], str(depth) + '.json').write_text(json.dumps([os.getpid(), os.getpgrp()]))
if depth > 1:
    bounded_process([sys.executable, __file__, str(depth - 1), sys.argv[2]], timeout=30)
else:
    time.sleep(30)
""")
        owner = self.script("guarded-owner.py", """
import os, sys
from scripts.sermon_execution_harness import bounded_process, work_lock
os.environ['SERMON_HARNESS_GUARDED_CHILDREN'] = '1'
with work_lock(sys.argv[1]):
    bounded_process([sys.executable, sys.argv[2], '3', sys.argv[3]], timeout=30)
""")
        process = self.launch(owner, self.work, node, self.folder)
        wait_for(lambda: all((self.folder / f'{n}.json').exists() for n in (1, 2, 3)))
        records = [json.loads((self.folder / f'{n}.json').read_text()) for n in (1, 2, 3)]
        self.groups.extend(pgid for pid, pgid in records)
        self.assertEqual(len({pgid for pid, pgid in records}), 3)
        with self.assertRaises(WorkAlreadyRunning):
            with work_lock(self.work):
                self.fail("Guardian did not preserve the workload lock")
        # A delayed intermediate process cannot run a Python finally block.
        # Pipe EOF still cascades after its owner is killed by outer cleanup.
        os.kill(records[1][0], signal.SIGSTOP)
        process.terminate()
        process.wait(timeout=8)
        for pid, pgid in records:
            wait_for(lambda: not alive(pid))
        with work_lock(self.work):
            pass

    def test_guarded_command_preserves_stdin_output_return_code_and_clean_env(self):
        with patch.dict(os.environ, {"SERMON_HARNESS_GUARDED_CHILDREN": "1"}):
            with tempfile.TemporaryFile() as source:
                source.write(b"input-bytes")
                source.seek(0)
                command = [sys.executable, "-c", "import os,sys; print(sys.stdin.read()); print('err',file=sys.stderr); assert 'HOME' not in os.environ; sys.exit(7)"]
                result = bounded_process(command, timeout=5, stdin=source,
                                         capture_output=True, text=True, env={})
        self.assertEqual(result.args, command)
        self.assertEqual(result.returncode, 7)
        self.assertEqual(result.stdout.strip(), "input-bytes")
        self.assertEqual(result.stderr.strip(), "err")


class ExecutionHarnessReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.folder = self.work / "accounting" / "harness"

    def latest(self):
        return json.loads((self.folder / "latest.json").read_text())

    def test_interrupted_previous_attempt_preserved_without_granting_approval(self):
        # Simulate a hard stop after durable running status, without __exit__.
        prior = Execution(self.work, "a" * 64)
        prior.__enter__()
        prior_path = self.folder / "attempts" / (prior.attempt + ".json")
        original = prior_path.read_bytes()
        with Execution(self.work, "a" * 64) as current:
            with current.stage("resume_existing_artifacts", cache_hit=True):
                pass
        record = self.latest()
        self.assertEqual(prior_path.read_bytes(), original)
        self.assertNotEqual(record["attemptId"], prior.attempt)
        self.assertEqual(record["previousAttemptId"], prior.attempt)
        self.assertEqual(record["previousStatus"], "running")
        self.assertIs(record["previousAttemptInterrupted"], True)
        self.assertEqual(record["status"], "candidate_ready_for_review")
        self.assertIs(record["approvalGranted"], False)
        self.assertIs(record["published"], False)
        self.assertTrue(record["stages"][0]["cacheHit"])

    def test_fixed_deadline_does_not_restart_at_new_stage(self):
        with patch("scripts.sermon_execution_harness.time.monotonic", return_value=100) as clock:
            execution = Execution(self.work, "a" * 64, timeout=10)
            with self.assertRaises(subprocess.TimeoutExpired):
                with execution:
                    clock.return_value = 104
                    self.assertEqual(execution.remaining(30), 6)
                    with execution.stage("first"):
                        clock.return_value = 106
                    self.assertEqual(execution.deadline, 110)
                    self.assertEqual(execution.remaining(30), 4)
                    with execution.stage("second"):
                        clock.return_value = 111
            record = self.latest()
            self.assertEqual(record["status"], "failed")
            self.assertEqual([s["status"] for s in record["stages"]], ["completed", "failed"])
            self.assertEqual(record["errorType"], "TimeoutExpired")

    def test_failure_receipts_store_type_without_exception_secret(self):
        secret = "SECRET_TEST_ONLY_NEVER_PERSIST"
        with self.assertRaises(RuntimeError):
            with Execution(self.work, "a" * 64) as execution:
                with execution.stage("local_step"):
                    raise RuntimeError("Bearer " + secret + " https://example.invalid/?token=" + secret)
        for path in self.folder.rglob("*.json"):
            self.assertNotIn(secret, path.read_text())
        record = self.latest()
        self.assertEqual(record["errorType"], "RuntimeError")
        self.assertEqual(record["stages"][0]["errorType"], "RuntimeError")
        self.assertIs(record["approvalGranted"], False)
        self.assertIs(record["published"], False)

    def test_unknown_remote_outcome_remains_reconciliation_state(self):
        with self.assertRaises(RemoteOutcomeUnknown):
            with Execution(self.work, "a" * 64):
                raise RemoteOutcomeUnknown("Unknown result; local test only")
        record = self.latest()
        self.assertEqual(record["status"], "waiting_remote_reconciliation")
        self.assertIs(record["approvalGranted"], False)
        self.assertIs(record["published"], False)

    def test_unbounded_or_shell_commands_rejected_without_spawning(self):
        with patch("scripts.sermon_execution_harness.subprocess.Popen") as spawn:
            for timeout in (0, -1, float("nan"), float("inf"), "1"):
                with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                    bounded_process([sys.executable], timeout=timeout)
            with self.assertRaises(ValueError):
                bounded_process("python3 -c pass", timeout=1)
            with self.assertRaises(ValueError):
                bounded_process([sys.executable], timeout=1, shell=True)
            spawn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
