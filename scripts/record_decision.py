#!/usr/bin/env python3
"""Record an operator decision as one JSON line, replacing hand-written
``*.evidence.txt`` notes.

    python3 scripts/record_decision.py --run-dir <run> \
        --question "zh 片尾超出批准窗口 0.74 s，怎么处理" \
        --choice "允许片尾容差 ≤ 1 s" --decided-by "Jony (chat)" \
        --evidence "用户原话：允许片尾容差≤1 s" \
        --evidence artifacts/weekend-live/layer3-54475d42/zh-Hans/schedule-c4.json

Each line in ``decisions.ndjson`` records when, what was asked, what was chosen,
who decided and through which channel, and the evidence: free text as given, or a
file path with its SHA-256 at the time of the decision, so a later reader can
tell whether the artifact the decision bound has changed. The file lives in the
run's ignored artifacts directory and is collected by export_run_digest.py.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

FILE_NAME = "decisions.ndjson"
CHANNELS = ("chat", "voice", "in_person", "email", "ticket")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def evidence_item(value: str, root: Path | None = None) -> dict:
    """A path that exists is bound by hash; anything else is kept as text."""
    candidate = Path(value)
    if not candidate.is_absolute() and root is not None:
        candidate = root / value
    if candidate.is_file() and not candidate.is_symlink():
        return {"path": value, "sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
                "bytes": candidate.stat().st_size}
    return {"text": value.strip()[:2000]}


def record(run_dir: Path, *, question: str, choice: str, decided_by: str, evidence=(), channel: str = "chat",
           applies_to: str | None = None, root: Path | None = None, now=utc_now) -> dict:
    for name, value in (("question", question), ("choice", choice), ("decided-by", decided_by)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"--{name} is required")
    if channel not in CHANNELS:
        raise ValueError(f"channel must be one of {', '.join(CHANNELS)}")
    row = {"at": now(), "question": question.strip()[:2000], "choice": choice.strip()[:2000],
           "decidedBy": decided_by.strip(), "channel": channel,
           "evidence": [evidence_item(item, root) for item in evidence]}
    if applies_to:
        row["appliesTo"] = applies_to.strip()
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(run_dir / FILE_NAME, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(descriptor, (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))
    finally:
        os.close(descriptor)
    return row


def read(run_dir: Path) -> list[dict]:
    path = Path(run_dir) / FILE_NAME
    if not path.is_file():
        return []
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            row = json.loads(line)
            if not isinstance(row, dict) or not all(isinstance(row.get(k), str) for k in ("at", "question", "choice", "decidedBy")):
                raise ValueError(f"{path}:{number}: not a decision record")
            rows.append(row)
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--choice", required=True)
    parser.add_argument("--decided-by", required=True, help='Who decided, e.g. "Jony (chat)"')
    parser.add_argument("--channel", choices=CHANNELS, default="chat")
    parser.add_argument("--applies-to", help="Stage, locale or artifact the decision governs")
    parser.add_argument("--evidence", action="append", default=[],
                        help="Quoted words, or a file path that gets hash-bound; repeatable")
    args = parser.parse_args(argv)
    row = record(args.run_dir, question=args.question, choice=args.choice, decided_by=args.decided_by,
                 evidence=args.evidence, channel=args.channel, applies_to=args.applies_to, root=Path.cwd())
    print(json.dumps(row, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
