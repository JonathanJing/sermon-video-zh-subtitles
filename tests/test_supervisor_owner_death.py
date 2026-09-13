"""Real local-process owner-death checks; no remote work or model calls."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from backend.leases import LeaseGuard, acquire_lease
from scripts.sermon_production_supervisor import _SUBPROCESS_RUN, run_guarded_command

ROOT = Path(__file__).resolve().parents[1]


def wait_for(predicate, timeout=6):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.025)
    raise AssertionError("Local process did not reach the expected state")


def alive(pid):
    check = subprocess.run(["ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True)
    state = check.stdout.strip()
    return check.returncode == 0 and bool(state) and not state.startswith("Z")


@unittest.skipUnless(os.name == "posix", "Guardian requires POSIX process groups")
class SupervisorOwnerDeathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.owner = None
        self.addCleanup(self.cleanup)

    def cleanup(self):
        group_file = self.folder / "group.pid"
        if group_file.exists() and group_file.read_text().strip().isdigit():
            try:
                os.killpg(int(group_file.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass
        if self.owner is not None:
            if self.owner.poll() is None:
                self.owner.kill()
            self.owner.communicate(timeout=5)

    def run_command(self, command):
        lease = acquire_lease(str(self.folder / "lease.json"), ttl_seconds=3)
        with LeaseGuard(lease, ttl_seconds=3) as guard:
            return run_guarded_command(command, runner=_SUBPROCESS_RUN, guard=guard)

    def test_ordinary_completion_preserves_output_exit_code_and_closes_workload_stdin(self):
        result = self.run_command([sys.executable, "-c", "import sys; assert sys.stdin.read() == ''; print('saved output'); print('saved error',file=sys.stderr); sys.exit(7)"])
        self.assertEqual(result.returncode, 7)
        self.assertEqual(result.stdout, "saved output\n")
        self.assertEqual(result.stderr, "saved error\n")
        self.assertFalse((self.folder / "lease.json").exists())

    def test_child_signal_exit_is_preserved(self):
        for sig in (signal.SIGTERM, signal.SIGKILL):
            with self.subTest(signal=sig):
                result = self.run_command([sys.executable, "-c", f"import os; os.kill(os.getpid(), {int(sig)})"])
                self.assertEqual(result.returncode, -int(sig))

    def test_owner_sigkill_stops_child_and_grandchild_before_lease_expiry(self):
        grand = self.folder / "grand.py"
        grand.write_text("import os,signal,sys,time\nfrom pathlib import Path\nsignal.signal(signal.SIGTERM,signal.SIG_IGN)\np=Path(sys.argv[1]); (p/'grand.pid').write_text(str(os.getpid()))\nwhile True:\n (p/'heartbeat').write_text(str(time.monotonic()))\n time.sleep(.02)\n")
        child = self.folder / "child.py"
        child.write_text("import os,subprocess,sys,time\nfrom pathlib import Path\np=Path(sys.argv[1]); (p/'group.pid').write_text(str(os.getpgrp())); (p/'child.pid').write_text(str(os.getpid()))\nsubprocess.Popen([sys.executable,str(p/'grand.py'),str(p)])\ntime.sleep(60)\n")
        owner = self.folder / "owner.py"
        owner.write_text("import sys\nfrom pathlib import Path\nfrom backend.leases import acquire_lease,LeaseGuard\nfrom scripts.sermon_production_supervisor import _SUBPROCESS_RUN,run_guarded_command\np=Path(sys.argv[1]); lease=acquire_lease(str(p/'lease.json'),ttl_seconds=60)\nwith LeaseGuard(lease,ttl_seconds=60) as guard:\n run_guarded_command([sys.executable,str(p/'child.py'),str(p)],runner=_SUBPROCESS_RUN,guard=guard)\n")
        self.owner = subprocess.Popen([sys.executable, str(owner), str(self.folder)],
                                      env=dict(os.environ, PYTHONPATH=str(ROOT)),
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        files = [self.folder / name for name in ("group.pid", "child.pid", "grand.pid")]
        wait_for(lambda: all(path.exists() and path.read_text().strip().isdigit() for path in files))
        pids = [int(path.read_text()) for path in files]
        self.assertTrue(all(alive(pid) for pid in pids))
        self.owner.kill()
        self.owner.wait(timeout=5)
        wait_for(lambda: all(not alive(pid) for pid in pids))
        # The 60-second lease is still present: cleanup depended on pipe EOF,
        # not waiting for takeover or for the dead renewal thread to wake up.
        self.assertEqual(json.loads((self.folder / "lease.json").read_text())["status"], "active")
        heartbeat = (self.folder / "heartbeat").read_bytes()
        time.sleep(.08)
        self.assertEqual((self.folder / "heartbeat").read_bytes(), heartbeat)


if __name__ == "__main__":
    unittest.main()
