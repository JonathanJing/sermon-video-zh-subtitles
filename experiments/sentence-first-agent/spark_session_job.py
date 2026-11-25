#!/usr/bin/env python3
"""Run one spark_run.sh step as a registered job inside a Spark exclusive session (experiment only).

The exclusive-session tool (packages/.../compute/spark_exclusive_session.py) refuses to close while
an unregistered container runs, and a container started outside a job breaks the owner's session
(2026-10-21: ``unmanaged_running_container``). This wrapper, run on the Mac, does the protocol:

  1. job-start          reserve a job in the open session
  2. launch             start spark_run.sh on Spark, detached, with the session/owner/job labels
  3. job-bind           bind the container id spark_run.sh wrote (docker --cidfile)
  4. wait               poll the step's "<step> exit" line in its log (every --poll seconds)
  5. job-end            known_terminal once the container is gone

Pass spark_run.sh arguments after ``--``; they must name exactly one step. Example:

  spark_session_job.py --session sfa-podcast --owner sentence-first-agent --purpose sentence-tts \\
      --remote-tools /home/achillesjing/sentence-first-agent/tools \\
      -- --work /home/achillesjing/sentence-first-agent/<run> --locale zh-Hans --steps tts \\
         --speaker john_thomas --checkpoint <dir>

If the wait is interrupted the job stays active; rerun with --resume-job <id> to keep waiting and
end it, never start a second job for the same work.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[2]
SESSION_TOOL = REPO / "packages/production/src/tongxing_production/compute/spark_exclusive_session.py"
HOST = "achillesjing@192.168.1.152"


def session(*args) -> dict:
    out = subprocess.run([sys.executable, "-I", str(SESSION_TOOL), *args], capture_output=True, text=True, timeout=300)
    try:
        value = json.loads(out.stdout)
    except json.JSONDecodeError:
        raise SystemExit(f"session tool returned no JSON: {out.stdout[-400:]} {out.stderr[-400:]}")
    if out.returncode or "error" in value:
        raise SystemExit(f"session tool {args[0]} failed: {value.get('error', value)}")
    return value


def ssh(command: str, *, timeout: int = 120, raise_timeout: bool = False) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", HOST, command],
                              capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        if raise_timeout:
            raise
        # A slow poll is not an outcome: report nothing and let the caller poll again.
        return subprocess.CompletedProcess(command, 255, "", "ssh timed out")


PRE_CONTAINER_STOPS = ("failed", "missing", "must", "refused", "unmeasurable")


def own_exit_line(lines: list[str], steps: str, job_id: str) -> str | None:
    """The last "<step> exit" line written by this job.

    The step log is shared by every job in the work directory (a second speaker, a lag-loop
    re-render, a repair). spark_run.sh tags each exit line with ``job=<id>``; a line from another
    job must never end this one. Only when no line carries a tag at all (a spark_run.sh from before
    the tag existed) does the last exit line count, as it did before.
    """
    exits = [line for line in lines if line.startswith(f"{steps} exit")]
    tagged = [line for line in exits if " job=" in line]
    if tagged:
        own = [line for line in tagged if line.split()[-1] == f"job={job_id}"]
        return own[-1] if own else None
    return exits[-1] if exits else None


def option(args: list[str], name: str) -> str:
    if name not in args:
        raise SystemExit(f"spark_run.sh arguments need {name}")
    return args[args.index(name) + 1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--purpose", required=True, help="job purpose label, e.g. sentence-tts or sentence-asr")
    parser.add_argument("--remote-tools", required=True, help="Spark directory holding spark_run.sh and the helpers")
    parser.add_argument("--poll", type=int, default=30)
    parser.add_argument("--max-poll-failures", type=int, default=20,
                        help="consecutive failed ssh polls before giving up (default 20, about 10 minutes at --poll 30)")
    parser.add_argument("--resume-job", help="keep waiting on, and end, an already started job")
    parser.add_argument("run_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    run_args = args.run_args[1:] if args.run_args[:1] == ["--"] else args.run_args
    work, steps = option(run_args, "--work"), option(run_args, "--steps")
    if steps not in ("tts", "asr"):
        raise SystemExit("--steps must be exactly tts or asr")
    log = f"{work}/{steps}-run.log"
    ids = ["--session-id", args.session, "--owner", args.owner]

    if args.resume_job:
        job_id = args.resume_job
    else:
        job_id = session("job-start", *ids, "--purpose", args.purpose)["jobId"]
        print(json.dumps({"job": job_id, "event": "reserved"}), flush=True)
        prefix = f"{work}/.jobs/{job_id}"
        command = " ".join(shlex.quote(a) for a in [
            "bash", f"{args.remote_tools}/spark_run.sh", *run_args,
            "--label-session", args.session, "--label-owner", args.owner, "--label-job", job_id, "--cid-prefix", prefix])
        try:
            launched = ssh(f"mkdir -p {shlex.quote(work)}/.jobs && (setsid {command} </dev/null >{shlex.quote(prefix)}.out 2>&1 &) ; echo started", raise_timeout=True)
            started = "started" in launched.stdout
        except subprocess.TimeoutExpired:
            # 2026-10-22: one launch call hung although the run had started; look for its container instead.
            started, launched = True, None
        if not started:
            session("job-end", *ids, "--job-id", job_id, "--outcome", "known_terminal", "--process-exited")
            raise SystemExit(f"launch failed: {launched.stderr[-400:]}")
        cid = ""
        for _ in range(60):  # the container id appears once docker has created the container
            time.sleep(5)
            # docker writes the cidfile without a trailing newline; echo one so the id stays on its own line.
            got = ssh(f"cat {shlex.quote(prefix)}.cid 2>/dev/null; echo; tail -n 3 {shlex.quote(prefix)}.out 2>/dev/null")
            first = got.stdout.strip().splitlines()[:1]
            if first and len(first[0]) == 64:
                cid = first[0]
                break
            # "refused"/"unmeasurable": spark_run.sh's memory admission exits 3 before any container.
            if any(word in got.stdout for word in PRE_CONTAINER_STOPS):
                session("job-end", *ids, "--job-id", job_id, "--outcome", "known_terminal", "--process-exited")
                raise SystemExit(f"spark_run.sh stopped before its container started:\n{got.stdout}")
        if not cid:
            raise SystemExit(f"no container id after 5 minutes; job {job_id} left active, reconcile with --resume-job")
        session("job-bind", *ids, "--job-id", job_id, "--container-id", cid)
        print(json.dumps({"job": job_id, "event": "bound", "container": cid[:12]}), flush=True)

    failures = 0
    while True:
        got = ssh(f"grep '^{steps} exit' {shlex.quote(log)} | tail -n 50; "
                  f"docker ps -q --filter label=tongxing.spark.job={job_id}")
        if got.returncode == 255:
            # ssh itself failed (link down, host off, timeout). Say so, and stop after
            # --max-poll-failures in a row so the queue reports a failure instead of waiting forever.
            failures += 1
            print(json.dumps({"job": job_id, "event": "poll_failed", "consecutive": failures,
                              "error": got.stderr.strip()[-200:]}), flush=True)
            if failures >= args.max_poll_failures:
                raise SystemExit(f"Spark unreachable for {failures} polls; job {job_id} left active, "
                                 f"reconcile with --resume-job {job_id} once Spark is back")
            time.sleep(args.poll)
            continue
        failures = 0
        lines = got.stdout.strip().splitlines()
        exit_line = own_exit_line(lines, steps, job_id)
        running = [l for l in lines if l and not l.startswith(f"{steps} exit")]
        if exit_line and not running:
            break
        time.sleep(args.poll)
    session("job-end", *ids, "--job-id", job_id, "--outcome", "known_terminal", "--process-exited")
    status = exit_line.split()[3] if len(exit_line.split()) > 3 else "?"
    # The container ran without --rm so the session tool could inspect it until job-end; the
    # session keeps inspecting bound ids until it closes, so keep the stopped container until
    # finish and remove it afterwards (docker rm $(docker ps -aq --filter label=tongxing.spark.session=<id>)).
    print(json.dumps({"job": job_id, "event": "ended", "stepExit": status, "log": exit_line}), flush=True)
    return 0 if status == "0" else 1


if __name__ == "__main__":
    raise SystemExit(main())
