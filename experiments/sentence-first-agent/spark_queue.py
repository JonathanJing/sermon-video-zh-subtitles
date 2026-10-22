#!/usr/bin/env python3
"""Queue every TTS and ASR step of several locales as registered jobs in one Spark exclusive session.

The session accepts one running job at a time, so locales run one after another: for each
--locale, one TTS job per --voice, then one ASR job. Each job goes through spark_session_job.py.
The queue stops at the first failed job and prints the command to resume it; spark_run.sh skips
finished sentences and ASR rows, so rerunning the queue only redoes what is missing. Run it as a
background task on the Mac and run finish_run.py for each locale as its "locale done" line appears.

  spark_queue.py --session sfa-<run> --owner sentence-first-agent \\
      --remote-tools /home/achillesjing/sentence-first-agent/tools \\
      --locale zh-Hans=/home/achillesjing/sentence-first-agent/<zh-run> \\
      --locale ko=/home/achillesjing/sentence-first-agent/<ko-run> \\
      --voice john_thomas=<checkpoint-dir> --voice steve_bang_lee=<checkpoint-dir>

Single-speaker runs pass one --voice; spark_run.sh then gets --speaker for that key as well.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys

JOB = Path(__file__).resolve().parent / "spark_session_job.py"


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--remote-tools", required=True)
    parser.add_argument("--locale", action="append", required=True, metavar="LOCALE=SPARK_WORK_DIR")
    parser.add_argument("--voice", action="append", required=True, metavar="SPEAKER_KEY=CHECKPOINT_DIR")
    parser.add_argument("--skip-asr", action="store_true")
    args = parser.parse_args()
    base = [sys.executable, str(JOB), "--session", args.session, "--owner", args.owner, "--remote-tools", args.remote_tools]
    print(f"start {now()}", flush=True)
    for item in args.locale:
        locale, work = item.split("=", 1)
        steps = [(f"sentence-tts-{key}-{locale}", ["--steps", "tts", "--speaker", key, "--checkpoint", checkpoint])
                 for key, checkpoint in (v.split("=", 1) for v in args.voice)]
        if not args.skip_asr:
            steps.append((f"sentence-asr-{locale}", ["--steps", "asr"]))
        for purpose, step in steps:
            command = [*base, "--purpose", purpose, "--", "--work", work, "--locale", locale, *step]
            print(f"job {purpose} {now()}", flush=True)
            if subprocess.run(command).returncode != 0:
                print(f"FAILED {purpose} {now()}\n  if its job is still active, resume it with: "
                      f"{' '.join(command[:2])} ... --resume-job <job id printed above>; otherwise rerun this queue",
                      flush=True)
                return 1
        print(f"locale done {locale} {now()}", flush=True)
    print(f"all done {now()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
