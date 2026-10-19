#!/usr/bin/env python3
"""Record an operator decision as one JSON line, replacing hand-written
``*.evidence.txt`` notes.

    python3 scripts/record_decision.py --run-dir <run> \
        --question "zh 片尾超出批准窗口 0.74 s，怎么处理" \
        --choice "允许片尾容差 ≤ 1 s" --decided-by "Jony (chat)" \
        --governs artifacts/weekend-live/layer3-54475d42/zh-Hans/schedule-c4.json \
        --evidence "用户原话：允许片尾容差≤1 s"
    python3 scripts/record_decision.py --run-dir <run> --check

Each line in ``decisions.ndjson`` records when, what was asked, what was chosen,
who decided and through which channel, the artifacts the decision governs and its
evidence. ``--governs`` names a file the decision applies to (a candidate, an
approved window, an audio package); it must exist and is bound by its SHA-256 at
the time of the decision. Such a row is ``artifact_bound``: it holds for exactly
those bytes, and ``--check`` reports it ``stale`` once any of them changes. A
row that governs nothing is an ``unbound_note``, a record of what was said and
never authority for any artifact. ``--evidence`` is free text as given, or a file
path that is also hash-bound. The file lives in the run's ignored artifacts
directory and is collected by export_run_digest.py.
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
AUTHORITIES = ("artifact_bound", "unbound_note")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _resolve(value: str, root: Path | None) -> Path:
    candidate = Path(value)
    return root / value if not candidate.is_absolute() and root is not None else candidate


def bound_file(value: str, root: Path | None = None) -> dict | None:
    """A regular file's path with its SHA-256 and size now; None when it is not one."""
    candidate = _resolve(value, root)
    if candidate.is_file() and not candidate.is_symlink():
        return {"path": value, "sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
                "bytes": candidate.stat().st_size}
    return None


def evidence_item(value: str, root: Path | None = None) -> dict:
    """A path that exists is bound by hash; anything else is kept as text."""
    return bound_file(value, root) or {"text": value.strip()[:2000]}


def record(run_dir: Path, *, question: str, choice: str, decided_by: str, evidence=(), governs=(), channel: str = "chat",
           applies_to: str | None = None, root: Path | None = None, now=utc_now) -> dict:
    for name, value in (("question", question), ("choice", choice), ("decided-by", decided_by)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"--{name} is required")
    if channel not in CHANNELS:
        raise ValueError(f"channel must be one of {', '.join(CHANNELS)}")
    governed = []
    for item in governs:
        bound = bound_file(item, root)
        if bound is None:
            raise ValueError(f"--governs must name an existing regular file: {item}")
        governed.append(bound)
    row = {"at": now(), "question": question.strip()[:2000], "choice": choice.strip()[:2000],
           "decidedBy": decided_by.strip(), "channel": channel,
           "authority": "artifact_bound" if governed else "unbound_note",
           "governs": governed, "evidence": [evidence_item(item, root) for item in evidence]}
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
            if (not isinstance(row, dict) or not all(isinstance(row.get(k), str) for k in ("at", "question", "choice", "decidedBy"))
                    or row.get("authority") not in AUTHORITIES or not isinstance(row.get("governs"), list)
                    or (row["authority"] == "artifact_bound") != bool(row["governs"])
                    or not all(isinstance(item, dict) and isinstance(item.get("path"), str)
                               and isinstance(item.get("sha256"), str) for item in row["governs"])):
                raise ValueError(f"{path}:{number}: not a decision record")
            rows.append(row)
    return rows


def check(run_dir: Path, root: Path | None = None) -> list[dict]:
    """Whether each decision still holds for the bytes it governs: applies, stale or unbound."""
    results = []
    for row in read(run_dir):
        changed = [item["path"] for item in row["governs"]
                   if (bound_file(item["path"], root) or {}).get("sha256") != item["sha256"]]
        status = "unbound" if row["authority"] == "unbound_note" else "stale" if changed else "applies"
        results.append({"at": row["at"], "question": row["question"][:200], "choice": row["choice"][:200],
                        "status": status, "changed": changed})
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--check", action="store_true",
                        help="Report whether each recorded decision still applies to the bytes it governs; exit 1 if any is stale")
    parser.add_argument("--question")
    parser.add_argument("--choice")
    parser.add_argument("--decided-by", help='Who decided, e.g. "Jony (chat)"')
    parser.add_argument("--channel", choices=CHANNELS, default="chat")
    parser.add_argument("--applies-to", help="Stage or locale the decision concerns (a label; binds nothing)")
    parser.add_argument("--governs", action="append", default=[],
                        help="A file the decision applies to, bound by its SHA-256; repeatable. Without one the row is an unbound note")
    parser.add_argument("--evidence", action="append", default=[],
                        help="Quoted words, or a file path that gets hash-bound; repeatable")
    args = parser.parse_args(argv)
    if args.check:
        results = check(args.run_dir, root=Path.cwd())
        print(json.dumps(results, ensure_ascii=False, indent=1))
        return 1 if any(result["status"] == "stale" for result in results) else 0
    missing = [name for name in ("question", "choice", "decided_by") if not getattr(args, name)]
    if missing:
        parser.error("recording a decision needs " + ", ".join("--" + name.replace("_", "-") for name in missing))
    row = record(args.run_dir, question=args.question, choice=args.choice, decided_by=args.decided_by,
                 evidence=args.evidence, governs=args.governs, channel=args.channel, applies_to=args.applies_to,
                 root=Path.cwd())
    print(json.dumps(row, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
