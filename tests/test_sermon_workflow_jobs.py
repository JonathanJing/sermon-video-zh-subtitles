"""Real short processes exercise durable job admission and uncertain recovery."""
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

from scripts import sermon_workflow_jobs as jobs


class WorkflowJobsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "jobs"

    def wait(self, job_id, statuses=("succeeded", "failed", "uncertain"), timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = jobs.inspect_job(self.root, job_id)
            if state["status"] in statuses:
                return state
            time.sleep(.025)
        self.fail("Durable child did not reach expected status")

    def test_success_and_repeat_never_execute_twice(self):
        marker = Path(self.temp.name) / "calls.txt"
        command = [sys.executable, "-c", "from pathlib import Path; import sys; p=Path(sys.argv[1]); p.write_text(p.read_text()+'x' if p.exists() else 'x')", str(marker)]
        first = jobs.start_job(self.root, {"stage": "test"}, command, 5)
        done = self.wait(first["jobId"])
        self.assertEqual(done["status"], "succeeded")
        self.assertEqual(set(done), {"jobId", "status"})
        self.assertEqual(jobs.start_job(self.root, {"stage": "test"}, command, 5), done)
        self.assertEqual(marker.read_text(), "x")
        self.assertEqual(oct((self.root / first["jobId"] / "request.json").stat().st_mode & 0o777), "0o600")

    def test_cross_process_duplicate_launch_executes_once(self):
        marker = Path(self.temp.name) / "calls.txt"
        command = [sys.executable, "-c", "import sys,time; from pathlib import Path; time.sleep(.15); p=Path(sys.argv[1]); p.write_text(p.read_text()+'x' if p.exists() else 'x')", str(marker)]
        program = "from scripts.sermon_workflow_jobs import start_job; import sys,json; from pathlib import Path; print(json.dumps(start_job(Path(sys.argv[1]), {'stage':'duplicate'}, json.loads(sys.argv[2]),5)))"
        children, outputs = [], []
        try:
            for _ in range(4):
                children.append(subprocess.Popen(
                    [sys.executable, "-c", program, str(self.root), json.dumps(command)], cwd=jobs.REPO_ROOT,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
            # Collect every creator before asserting: a failed child must not
            # cause temporary-directory cleanup underneath its still-running peers.
            for child in children:
                outputs.append((child, *child.communicate(timeout=5)))
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                child.communicate(timeout=5)
            # A creator may fail after spawning its durable worker. Let that
            # bounded test workload finish before removing its evidence folder.
            job_id = jobs._digest({"stage": "duplicate"})
            if (self.root / job_id).is_dir():
                self.wait(job_id)
        diagnostics = "\n".join(stderr for child, stdout, stderr in outputs if child.returncode != 0)
        self.assertTrue(all(child.returncode == 0 for child, stdout, stderr in outputs), diagnostics)
        receipts = [json.loads(stdout) for child, stdout, stderr in outputs]
        self.assertEqual(len({item["jobId"] for item in receipts}), 1)
        self.assertTrue(all(item["status"] in {"queued", "running", "succeeded"} for item in receipts))
        self.assertEqual(self.wait(receipts[0]["jobId"])["status"], "succeeded")
        self.assertEqual(marker.read_text(), "x")

    def test_nonzero_and_timeout_are_retained_failures(self):
        for identity, command, limit in (
            ({"stage": "nonzero"}, [sys.executable, "-c", "raise SystemExit(7)"], 3),
            ({"stage": "timeout"}, [sys.executable, "-c", "import time;time.sleep(20)"], .1),
        ):
            result = jobs.start_job(self.root, identity, command, limit)
            self.assertEqual(self.wait(result["jobId"])["status"], "failed")
            self.assertEqual(jobs.start_job(self.root, identity, command, limit)["status"], "failed")

    def test_stale_owner_is_uncertain_and_child_stops(self):
        marker = Path(self.temp.name) / "started"
        late = Path(self.temp.name) / "should-not-exist"
        command = [sys.executable, "-c", "import sys,time;from pathlib import Path;Path(sys.argv[1]).write_text('started');time.sleep(2);Path(sys.argv[2]).write_text('late')", str(marker), str(late)]
        receipt = jobs.start_job(self.root, {"stage": "crash"}, command, 5)
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(.025)
        self.assertTrue(marker.exists())
        state = json.loads((self.root / receipt["jobId"] / "state.json").read_text())
        os.kill(state["workerPid"], signal.SIGKILL)
        self.assertEqual(self.wait(receipt["jobId"])["status"], "uncertain")
        self.assertEqual(jobs.start_job(self.root, {"stage": "crash"}, command, 5)["status"], "uncertain")
        time.sleep(2.1)
        self.assertFalse(late.exists())

    def test_crash_before_spawn_never_reexecutes_unknown_job(self):
        identity = {"stage": "spawn-gap"}
        command = [sys.executable, "-c", "raise SystemExit(0)"]
        with patch.object(jobs.subprocess, "Popen", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                jobs.start_job(self.root, identity, command, 5)
        job_id = jobs._digest(identity)
        self.assertEqual(jobs.inspect_job(self.root, job_id)["status"], "uncertain")
        with patch.object(jobs.subprocess, "Popen") as spawn:
            self.assertEqual(jobs.start_job(self.root, identity, command, 5)["status"], "uncertain")
        spawn.assert_not_called()

    def test_same_identity_cannot_change_command_or_timeout(self):
        identity, command = {"stage": "fixed"}, [sys.executable, "-c", "pass"]
        result = jobs.start_job(self.root, identity, command, 5)
        self.wait(result["jobId"])
        for changed, timeout in (([sys.executable, "-c", "print('changed')"], 5), (command, 6)):
            with self.assertRaisesRegex(ValueError, "execution parameters"):
                jobs.start_job(self.root, identity, changed, timeout)

    def test_corrupt_request_cannot_keep_success_status_or_respawn(self):
        identity, command = {"stage": "corrupt"}, [sys.executable, "-c", "pass"]
        receipt = jobs.start_job(self.root, identity, command, 5)
        self.assertEqual(self.wait(receipt["jobId"])["status"], "succeeded")
        request_path = self.root / receipt["jobId"] / "request.json"
        request = json.loads(request_path.read_text())
        request["timeoutSeconds"] = 10
        request_path.write_text(json.dumps(request))
        self.assertEqual(jobs.inspect_job(self.root, receipt["jobId"])["status"], "uncertain")
        with self.assertRaises(ValueError):
            jobs.start_job(self.root, identity, command, 5)

    def test_transient_lock_creation_enoent_retries_admission_only(self):
        locks = Path(self.temp.name) / "locks"
        locks.mkdir()
        fd = jobs._directory_fd(locks)
        original_open = os.open
        attempts = []
        def transient_open(path, *args, **kwargs):
            if path == "job.lock":
                attempts.append(path)
                if len(attempts) == 1:
                    raise FileNotFoundError("transient concurrent creation")
            return original_open(path, *args, **kwargs)
        try:
            with patch.object(jobs.os, "open", side_effect=transient_open):
                lock_fd = jobs._open_lock_file(locks / "job.lock", fd)
            os.close(lock_fd)
            self.assertEqual(len(attempts), 2)
        finally:
            os.close(fd)

    def test_lock_retry_rejects_replaced_parent_directory(self):
        locks = Path(self.temp.name) / "locks"
        locks.mkdir()
        fd = jobs._directory_fd(locks)
        locks.rename(locks.with_name("old-locks"))
        locks.mkdir()
        try:
            with patch.object(jobs.os, "open", side_effect=FileNotFoundError("changed directory")) as opened:
                with self.assertRaisesRegex(ValueError, "directory changed"):
                    jobs._open_lock_file(locks / "job.lock", fd)
            self.assertEqual(opened.call_count, 1)
        finally:
            os.close(fd)

    def test_rejects_symlink_descendants_without_touching_targets(self):
        identity = {"stage": "link"}
        job_id = jobs._digest(identity)
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        sentinel = outside / "sentinel"
        sentinel.write_text("unchanged")
        for name in (".locks", job_id, ".locks/" + job_id + ".lock",
                     job_id + "/request.json", job_id + "/state.json", job_id + "/worker.log"):
            with self.subTest(name=name), tempfile.TemporaryDirectory(dir=self.temp.name) as case:
                root = Path(case) / "jobs"
                root.mkdir()
                link = root / name
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(outside if name in (".locks", job_id) else sentinel)
                with self.assertRaisesRegex(ValueError, "symlinks"):
                    jobs.start_job(root, identity, [sys.executable, "-c", "pass"], 5)
                with self.assertRaisesRegex(ValueError, "symlinks"):
                    jobs.inspect_job(root, job_id)
                self.assertEqual(sentinel.read_text(), "unchanged")
                self.assertEqual(sorted(path.name for path in outside.iterdir()), ["sentinel"])

    def test_rejects_non_regular_evidence_without_blocking_on_fifo(self):
        job_id = jobs._digest({"stage": "fifo"})
        folder = self.root / job_id
        folder.mkdir(parents=True)
        os.mkfifo(folder / "state.json")
        with self.assertRaisesRegex(ValueError, "ordinary"):
            jobs.inspect_job(self.root, job_id)

    def test_rejects_path_traversal_shell_strings_and_invalid_timeout(self):
        with self.assertRaises(ValueError):
            jobs.inspect_job(self.root, "../other")
        with self.assertRaises(ValueError):
            jobs.start_job(self.root, {"stage": "invalid"}, "echo nope", 5)
        for timeout in (0, -1, float("nan"), float("inf"), True):
            with self.assertRaises(ValueError):
                jobs.start_job(self.root, {"stage": "invalid"}, ["echo", "nope"], timeout)


if __name__ == "__main__":
    unittest.main()
