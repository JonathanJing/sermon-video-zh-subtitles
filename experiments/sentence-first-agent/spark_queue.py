#!/usr/bin/env python3
"""Queue every TTS step of several locales as registered jobs in one Spark exclusive session.

The session accepts one running job at a time, so locales run one after another: for each
--locale, one TTS job per --voice. Each job goes through spark_session_job.py.
The queue stops at the first failed job and prints the command to resume it; spark_run.sh skips
finished sentences, so rerunning the queue only redoes what is missing. Run it as a
background task on the Mac and run finish_run.py for each locale as its "locale done" line appears.

  spark_queue.py --session sfa-<run> --owner sentence-first-agent \\
      --remote-tools /home/achillesjing/sentence-first-agent/tools \\
      --locale zh-Hans=/home/achillesjing/sentence-first-agent/<zh-run> \\
      --locale ko=/home/achillesjing/sentence-first-agent/<ko-run> \\
      --voice john_thomas=<checkpoint-dir> --voice steve_bang_lee=<checkpoint-dir>

Single-speaker runs pass one --voice; spark_run.sh then gets --speaker for that key as well.

Status observation is fail-open and off the critical path: when the run is registered in
the status index, each job writes ``l3.tts.<speaker>.<locale>`` started/progress/finished
(or failed) and a heartbeat every 30 s while the Spark subprocess runs. ``--no-status``
disables it; ``--status-run LOCALE=LOCAL_RUN`` overrides the index lookup.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
import time

try:  # status is an observer; a missing/broken sidecar must not stop TTS
    import run_status  # type: ignore
except Exception:  # noqa: BLE001 - optional observation dependency
    run_status = None

JOB = Path(__file__).resolve().parent / "spark_session_job.py"
HEARTBEAT_SECONDS = 30.0


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_run_map(values: list[str] | None) -> dict[str, Path]:
    runs: dict[str, Path] = {}
    for value in values or []:
        if "=" not in value:
            raise SystemExit(f"--status-run needs LOCALE=LOCAL_RUN, got {value!r}")
        locale, path = value.split("=", 1)
        runs[locale] = Path(path).expanduser()
    return runs


def _status_run(locale: str, explicit: dict[str, Path], index: Path | None) -> Path | None:
    if run_status is None:
        return None
    if locale in explicit:
        return explicit[locale]
    try:
        return run_status.find_run_for_locale(locale, index)
    except Exception:  # noqa: BLE001
        return None


def run_job(command: list[str], *, run: Path | None, stages: list[str], purpose: str,
            done: int, total: int) -> int:
    """Run one Spark job while emitting liveness; return its exit code."""
    if run is None or run_status is None:
        return subprocess.run(command).returncode
    attempts: dict[str, int | None] = {}
    for stage in stages:
        event = run_status.safe_mark(run, stage, "started", source="spark_queue",
                                     message=purpose)
        attempts[stage] = (event or {}).get("attempt")
    try:
        process = subprocess.Popen(command)
    except OSError as exc:
        for stage in stages:
            run_status.safe_mark(run, stage, "failed", source="spark_queue",
                                 attempt=attempts.get(stage), error_class="process",
                                 message=f"could not start job: {exc}",
                                 resume="rerun spark_queue")
        return 127
    next_heartbeat = time.monotonic() + HEARTBEAT_SECONDS
    try:
        while process.poll() is None:
            if time.monotonic() >= next_heartbeat:
                for stage in stages:
                    run_status.safe_mark(run, stage, "heartbeat", source="spark_queue",
                                         attempt=attempts.get(stage), message=purpose)
                next_heartbeat = time.monotonic() + HEARTBEAT_SECONDS
            time.sleep(0.5)
    except KeyboardInterrupt:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        for stage in stages:
            run_status.safe_mark(run, stage, "failed", source="spark_queue",
                                 attempt=attempts.get(stage), error_class="interrupted",
                                 message="interrupted", resume="rerun spark_queue")
        return 130
    code = int(process.returncode)
    if code == 0:
        for stage in stages:
            run_status.safe_mark(run, stage, "progress", source="spark_queue",
                                 attempt=attempts.get(stage), unit="jobs",
                                 done=done, total=total, message=purpose)
            run_status.safe_mark(run, stage, "finished", source="spark_queue",
                                 attempt=attempts.get(stage), evidence_level="E1",
                                 message=purpose)
    else:
        for stage in stages:
            run_status.safe_mark(run, stage, "failed", source="spark_queue",
                                 attempt=attempts.get(stage), error_class="process",
                                 message=f"exit {code}", resume="rerun spark_queue")
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--remote-tools", required=True)
    parser.add_argument("--locale", action="append", required=True, metavar="LOCALE=SPARK_WORK_DIR")
    parser.add_argument("--voice", action="append", required=True, metavar="SPEAKER_KEY=CHECKPOINT_DIR")
    parser.add_argument("--batch-size", type=int, default=1, help="sentences per TTS model call (batch>1 changes sound identity)")
    parser.add_argument("--pool-replicas", type=int, default=0, help="one two-speaker TTS pool per locale with this many model replicas (0 = one job per speaker)")
    parser.add_argument("--status-index", type=Path, help="status index path (default: artifacts/sentence-first-agent/.status-index.json)")
    parser.add_argument("--status-run", action="append", metavar="LOCALE=LOCAL_RUN",
                        help="local run directory for a locale; overrides the status index lookup")
    parser.add_argument("--no-status", action="store_true", help="do not write status events")
    args = parser.parse_args()
    if args.no_status:
        global run_status
        run_status = None
    explicit_runs = _parse_run_map(args.status_run)
    base = [sys.executable, str(JOB), "--session", args.session, "--owner", args.owner, "--remote-tools", args.remote_tools]
    print(f"start {now()}", flush=True)
    for item in args.locale:
        locale, work = item.split("=", 1)
        voices = [v.split("=", 1) for v in args.voice]
        if args.pool_replicas:
            pool = ["--steps", "tts-pool"]
            for key, checkpoint in voices:
                pool += ["--voice", f"{key}={checkpoint}"]
            pool += ["--replicas", str(args.pool_replicas), "--batch-size", str(args.batch_size)]
            steps = [(f"sentence-tts-pool-{locale}", pool, [key for key, _ in voices])]
        else:
            steps = [(f"sentence-tts-{key}-{locale}",
                      ["--steps", "tts", "--speaker", key, "--checkpoint", checkpoint,
                       "--batch-size", str(args.batch_size)], [key])
                     for key, checkpoint in voices]
        local_run = _status_run(locale, explicit_runs, args.status_index)
        for index, (purpose, step, speakers) in enumerate(steps, 1):
            command = [*base, "--purpose", purpose, "--", "--work", work, "--locale", locale, *step]
            stages = [f"l3.tts.{speaker}.{locale}" for speaker in speakers]
            print(f"job {purpose} {now()}", flush=True)
            if run_job(command, run=local_run, stages=stages, purpose=purpose,
                       done=index, total=len(steps)) != 0:
                print(f"FAILED {purpose} {now()}\n  if its job is still active, resume it with: "
                      f"{' '.join(command[:2])} ... --resume-job <job id printed above>; otherwise rerun this queue",
                      flush=True)
                return 1
        print(f"locale done {locale} {now()}", flush=True)
    print(f"all done {now()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
