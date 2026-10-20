"""Opt-in local command guardian: owner EOF kills this dedicated process group."""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import threading


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner-fd", type=int, required=True)
    parser.add_argument("--inherit-fd", type=int, action="append", default=[])
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command or os.getpgrp() != os.getpid() or args.owner_fd in args.inherit_fd:
        return 2

    # A group TERM reaches the workload too. Keep the EOF watcher alive while
    # that workload cleans up nested groups. A caught handler is reset on exec;
    # SIG_IGN would incorrectly make the workload inherit ignored termination.
    signal.signal(signal.SIGTERM, lambda *_: None)

    def watch_owner():
        try:
            while os.read(args.owner_fd, 4096):
                pass
        except OSError:
            pass
        os.killpg(os.getpgrp(), signal.SIGKILL)

    threading.Thread(target=watch_owner, daemon=True, name="command-owner-sentinel").start()
    try:
        # Keep normal stdin semantics; the liveness pipe is a distinct FD and
        # must not reach the workload. Work-lock FDs do reach the workload.
        child = subprocess.Popen(command, pass_fds=tuple(args.inherit_fd))
        code = child.wait()
    except OSError:
        print("guarded_command_start_failed", file=sys.stderr)
        return 127
    if code < 0:
        sig = -code
        if sig not in (signal.SIGKILL, signal.SIGSTOP):
            signal.signal(sig, signal.SIG_DFL)
        os.kill(os.getpid(), sig)
    return code


if __name__ == "__main__":
    sys.exit(main())
