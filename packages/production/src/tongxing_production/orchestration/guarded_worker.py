"""POSIX guardian: parent-owned stdin pipe EOF terminates this entire child group."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading


def watch_owner():
    try:
        while os.read(0, 4096):
            pass
    except OSError:
        pass
    # The supervisor creates this dedicated process group before exec. Never
    # forward stdin to the workload: it must remain solely an owner-liveness FD.
    os.killpg(os.getpgrp(), signal.SIGKILL)


def main(argv=None):
    command = list(sys.argv[1:] if argv is None else argv)
    if command and command[0] == "--":
        command.pop(0)
    if not command or os.getpgrp() != os.getpid():
        print("guarded_worker_requires_command_and_dedicated_process_group", file=sys.stderr)
        return 2
    threading.Thread(target=watch_owner, name="supervisor-owner-sentinel", daemon=True).start()
    try:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL)
        code = process.wait()
    except OSError:
        print("guarded_worker_command_start_failed", file=sys.stderr)
        return 127
    if code < 0:
        sig = -code
        if sig not in {signal.SIGKILL, signal.SIGSTOP}:
            signal.signal(sig, signal.SIG_DFL)
        os.kill(os.getpid(), sig)
    return code


if __name__ == "__main__":
    sys.exit(main())
