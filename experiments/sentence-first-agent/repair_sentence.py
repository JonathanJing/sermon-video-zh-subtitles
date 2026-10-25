#!/usr/bin/env python3
"""Repair one sentence by re-rendering its recorded batch window on Spark.

The 2026-10-23 full-episode run renders with ``--batch-size 8``. Batch>1 makes the sound
identity of the batch members shared, so changing one sentence means re-rendering the
whole window (or, with ``--single``, accepting a batch-1 exception for that sentence).

``tts_sentences.py`` records every window in ``tts/tts-batches.jsonl`` (pulled by
``finish_run.py``). This helper:

1. finds the window containing ``--id``;
2. deletes those WAVs on Spark (the existing files are otherwise skipped);
3. uploads the current ``speech.jsonl`` and the window ids;
4. runs ``spark_session_job.py`` with ``--only-ids-file`` and the window's batch size;
5. prints the ``finish_run.py`` / ``review_player.py`` commands to rerun afterwards.

Without ``--apply`` it only prints the plan (dry run). The Spark session must be open.

Usage:
  repair_sentence.py --run artifacts/sentence-first-agent/<run> --id s0123 \
      --remote achillesjing@192.168.1.152:/home/achillesjing/sentence-first-agent/<run> \
      --session sfa-... --locale es \
      --voice steve_bang_lee=/home/achillesjing/.../checkpoint-epoch-0 \
      --voice eric_pilot=/home/achillesjing/.../checkpoint-epoch-0 \
      [--single] [--apply]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def window_for(batches: list[dict], sid: str) -> dict:
    for batch in batches:
        if sid in batch.get("ids", []):
            return batch
    raise SystemExit(f"{sid} is not in tts/tts-batches.jsonl; run the original queue once and pull the tts directory "
                     f"(finish_run.py), or pass --single to repair one sentence without window identity")


def split_remote(value: str) -> tuple[str, str]:
    host, sep, path = value.partition(":")
    if not sep or not host or not path:
        raise SystemExit("--remote must be HOST:/absolute/path/to/run")
    return host, path


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--remote", required=True, help="HOST:/absolute/path/to/run on Spark")
    p.add_argument("--voice", action="append", required=True, metavar="SPEAKER_KEY=CHECKPOINT_DIR")
    p.add_argument("--session", required=True)
    p.add_argument("--owner", default="sentence-first-agent")
    p.add_argument("--remote-tools", default="/home/achillesjing/sentence-first-agent/tools")
    p.add_argument("--locale")
    p.add_argument("--single", action="store_true", help="re-render only this sentence with batch 1 (identity exception)")
    p.add_argument("--apply", action="store_true", help="perform the remote delete/upload/run (default: print the plan)")
    p.add_argument("--poll", type=int, default=30)
    a = p.parse_args(argv)
    run = a.run
    speech = [json.loads(line) for line in (run / "speech.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    row = next((r for r in speech if r["id"] == a.id), None)
    if row is None:
        raise SystemExit(f"{a.id} is not in {run / 'speech.jsonl'}")
    batches_path = run / "tts/tts-batches.jsonl"
    if a.single:
        ids, batch_size = [a.id], 1
        window = {"batchIndex": None, "batchSize": 1, "ids": ids}
    else:
        if not batches_path.exists():
            raise SystemExit(f"missing {batches_path}; pull the tts directory first (finish_run.py) or use --single")
        batches = [json.loads(line) for line in batches_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        window = window_for(batches, a.id)
        ids, batch_size = window["ids"], window.get("batchSize", 8)
    voices = {}
    for item in a.voice:
        key, sep, path = item.partition("=")
        if not sep or not key or not path:
            raise SystemExit("--voice must be SPEAKER_KEY=CHECKPOINT_DIR")
        voices[key] = path
    speaker = row["speaker"]
    if speaker not in voices:
        raise SystemExit(f"missing --voice {speaker}=<checkpoint> (row speaker is {speaker!r})")
    locale = a.locale or json.loads((run / "review.json").read_text(encoding="utf-8")).get("locale")
    host, remote_path = split_remote(a.remote)
    ids_name = f"repair-{a.id}.json"
    local_ids = run / ids_name
    plan = {"id": a.id, "speaker": speaker, "window": window, "ids": ids, "batchSize": batch_size,
            "locale": locale, "remote": a.remote, "idsFile": str(local_ids)}
    print(json.dumps(plan, ensure_ascii=False, indent=1))
    if not a.apply:
        print("\nplan only; rerun with --apply to delete the window WAVs, upload and run.")
        return 0
    local_ids.write_text(json.dumps(ids, ensure_ascii=False) + "\n", encoding="utf-8")
    wavs = " ".join(f"{remote_path}/tts/{sid}.wav" for sid in ids)
    subprocess.run(["ssh", host, f"rm -f {wavs}"], check=True)
    subprocess.run(["scp", "-q", str(run / "speech.jsonl"), f"{host}:{remote_path}/speech.jsonl"], check=True)
    subprocess.run(["scp", "-q", str(local_ids), f"{host}:{remote_path}/{ids_name}"], check=True)
    command = [sys.executable, str(HERE / "spark_session_job.py"),
               "--session", a.session, "--owner", a.owner, "--remote-tools", a.remote_tools,
               "--purpose", f"sentence-repair-{a.id}", "--poll", str(a.poll), "--",
               "--work", remote_path, "--locale", locale, "--steps", "tts",
               "--speaker", speaker, "--checkpoint", voices[speaker],
               "--batch-size", str(batch_size), "--only-ids-file", f"/work/{ids_name}"]
    print("running:", " ".join(command), file=sys.stderr)
    subprocess.run(command, check=True)
    print(json.dumps({"repaired": a.id, "window": ids, "next": [
        f"python3 {HERE / 'finish_run.py'} --run {run} --remote {a.remote} --no-video",
        f"python3 {HERE / 'review_player.py'} --run {run} --out <review dir>/review-player.html"]},
        ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
