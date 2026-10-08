#!/usr/bin/env python3
"""Pack the small text evidence of a local test run into a redacted digest.

Runs leave their evidence under ignored ``artifacts/`` on the Mac (and on
Spark), where a cloud review session cannot read it. This tool copies only the
files a retrospective needs from one or more run directories:

- ``outcome.json``, ``timings.tsv``, ``summary.json`` and ``*receipt*.json``
  (whole, when under the size cap);
- ``*.log`` (first and last lines, with every error line in between).

Media, model outputs and any other file are left out and only counted. Every
copied file is redacted (API keys, tokens, cookies, private keys, emails,
private IPs, home directories, and the values of secret-like environment
variables) before it is written. The digest gets ``manifest.json`` (source
hashes, truncation and redaction counts) and ``INDEX.md`` (outcomes, stage
timings, failed stages and error lines), and is zipped for attaching to the
project thread. Nothing is uploaded or committed by this tool.

Usage (repo root):
  .venv/bin/python scripts/export_run_digest.py artifacts/dev-180s-page-test-20261004/<run-id>
  .venv/bin/python scripts/export_run_digest.py RUN_DIR [RUN_DIR ...] --name 20261008-8x8-round2
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "sermon-run-digest-v1"
WHOLE_NAMES = {"outcome.json", "timings.tsv", "summary.json"}
MAX_WHOLE_BYTES = 256 * 1024
LOG_HEAD, LOG_TAIL, LOG_MAX_ERRORS = 40, 200, 50
ERROR_LINE = re.compile(r"Traceback|Error\b|Exception|FAILED|\bfail(ed)?\b|refused|denied|timed? ?out", re.I)

REDACTIONS: list[tuple[str, re.Pattern[str], str]] = [
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
     "<private-key>"),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), "<openai-key>"),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"), "<github-token>"),
    ("google_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), "<google-key>"),
    ("bearer", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer <redacted>"),
    ("secret_field", re.compile(
        r"(?i)(\"?[\w-]*(?:api[_-]?key|token|secret|password|passwd|cookie|authorization)\"?\s*[:=]\s*)"
        r"(\"[^\"\n]*\"|'[^'\n]*'|[^\s,;}]+)"), r"\1<redacted>"),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"), "<email>"),
    ("private_ip", re.compile(
        r"\b(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}"
        r"|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])(?:\.\d{1,3}){2})\b"), "<private-ip>"),
    ("home_dir", re.compile(r"/(?:Users|home)/[^/\s\"']+"), "~"),
]


def env_secret_values() -> list[str]:
    """Values of secret-like variables in this process (e.g. under the OpenAI launcher)."""
    marker = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|COOKIE", re.I)
    return sorted({v for k, v in os.environ.items() if marker.search(k) and len(v) >= 8}, key=len, reverse=True)


def redact(text: str, secrets: list[str]) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}
    for value in secrets:
        if value in text:
            counts["env_secret"] = counts.get("env_secret", 0) + text.count(value)
            text = text.replace(value, "<env-secret>")
    for name, pattern, replacement in REDACTIONS:
        text, hits = pattern.subn(replacement, text)
        if hits:
            counts[name] = counts.get(name, 0) + hits
    return text, counts


def condense_log(lines: list[str]) -> tuple[list[str], bool]:
    if len(lines) <= LOG_HEAD + LOG_TAIL:
        return lines, False
    middle = lines[LOG_HEAD:-LOG_TAIL]
    errors = [f"[line {LOG_HEAD + i + 1}] {line}" for i, line in enumerate(middle) if ERROR_LINE.search(line)]
    kept = errors[:LOG_MAX_ERRORS]
    note = f"... {len(middle)} lines omitted; {len(errors)} error-like lines, {len(kept)} kept below ...\n"
    return lines[:LOG_HEAD] + [note] + [l if l.endswith("\n") else l + "\n" for l in kept] + \
        ["... end of omitted section ...\n"] + lines[-LOG_TAIL:], True


def classify(path: Path) -> str | None:
    if path.name in WHOLE_NAMES or (path.suffix == ".json" and "receipt" in path.name):
        return "whole"
    if path.suffix == ".log":
        return "log"
    return None


def collect(run_dir: Path, label: str, dest: Path, secrets: list[str]) -> tuple[list[dict], dict[str, int]]:
    entries: list[dict] = []
    skipped: dict[str, int] = {}
    for path in sorted(run_dir.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        kind = classify(path)
        rel = path.relative_to(run_dir)
        if kind is None:
            key = path.suffix or "(none)"
            skipped[key] = skipped.get(key, 0) + 1
            continue
        raw = path.read_bytes()
        entry = {"run": label, "path": str(rel), "kind": kind, "bytes": len(raw),
                 "sha256": hashlib.sha256(raw).hexdigest(), "truncated": False}
        if kind == "whole" and len(raw) > MAX_WHOLE_BYTES:
            entry["omitted"] = "over_size_cap"
            entries.append(entry)
            continue
        text = raw.decode("utf-8", errors="replace")
        if kind == "log":
            lines, entry["truncated"] = condense_log(text.splitlines(keepends=True))
            text = "".join(lines)
        text, entry["redactions"] = redact(text, secrets)
        target = dest / label / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        entries.append(entry)
    return entries, skipped


def read_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def index_markdown(name: str, dest: Path, entries: list[dict], runs: list[dict]) -> str:
    out = [f"# Run digest {name}", "", f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}. "
           "Redacted copies only; source hashes are in manifest.json.", ""]
    for run in runs:
        label = run["label"]
        out += [f"## {label}", "", f"Source: `{run['source']}`", ""]
        for entry in (e for e in entries if e["run"] == label and Path(e["path"]).name == "outcome.json"):
            record = read_json(dest / label / entry["path"]) or {}
            out.append(f"- outcome `{entry['path']}`: **{record.get('status', '?')}** exit {record.get('exitCode', '?')} "
                       f"({record.get('startedAt', '?')} → {record.get('endedAt', '?')})"
                       + (f", error {record['error'].get('type')}: {record['error'].get('message')}"
                          if isinstance(record.get("error"), dict) else ""))
        for entry in (e for e in entries if e["run"] == label and Path(e["path"]).name == "timings.tsv"):
            with (dest / label / entry["path"]).open(encoding="utf-8") as handle:
                rows = [r for r in csv.reader(handle, delimiter="\t") if r]
            if rows:
                out += ["", f"Timings `{entry['path']}`:", "", "| " + " | ".join(rows[0]) + " |",
                        "|" + "---|" * len(rows[0])] + ["| " + " | ".join(r) + " |" for r in rows[1:]]
                failed = [r[0] for r in rows[1:] if len(r) > 1 and r[1] != "pass"]
                if failed:
                    out += ["", "Failed stages: " + ", ".join(f"`{s}`" for s in failed)]
        error_lines = []
        for entry in (e for e in entries if e["run"] == label and e["kind"] == "log" and "omitted" not in e):
            hits = [l.strip() for l in (dest / label / entry["path"]).read_text(encoding="utf-8").splitlines()
                    if ERROR_LINE.search(l)][:5]
            error_lines += [f"- `{entry['path']}`: {h[:200]}" for h in hits]
        if error_lines:
            out += ["", "Error-like log lines (first 5 per log):", ""] + error_lines
        if run["skipped"]:
            out += ["", "Not copied: " + ", ".join(f"{n} {ext}" for ext, n in sorted(run["skipped"].items()))]
        out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run_dirs", nargs="+", type=Path, help="Run directories (usually under artifacts/)")
    parser.add_argument("--name", help="Digest name (default: first run directory name)")
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts/run-digests")
    parser.add_argument("--no-zip", action="store_true")
    args = parser.parse_args(argv)

    for run_dir in args.run_dirs:
        if not run_dir.is_dir():
            parser.error(f"{run_dir} is not a directory")
    name = args.name or args.run_dirs[0].resolve().name
    if not re.fullmatch(r"[\w.-]+", name):
        parser.error("--name may only contain letters, digits, '.', '_' and '-'")
    dest = args.out / name
    if dest.exists():
        parser.error(f"{dest} already exists; pick another --name")
    dest.mkdir(parents=True)

    secrets = env_secret_values()
    entries: list[dict] = []
    runs: list[dict] = []
    labels: set[str] = set()
    for run_dir in args.run_dirs:
        label = run_dir.resolve().name
        while label in labels:
            label += "_"
        labels.add(label)
        found, skipped = collect(run_dir, label, dest, secrets)
        entries += found
        source, _ = redact(str(run_dir.resolve()), secrets)
        runs.append({"label": label, "source": source, "skipped": skipped})

    manifest = {"schemaVersion": SCHEMA, "name": name, "runs": runs, "files": entries,
                "limits": {"maxWholeBytes": MAX_WHOLE_BYTES, "logHead": LOG_HEAD, "logTail": LOG_TAIL}}
    (dest / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (dest / "INDEX.md").write_text(index_markdown(name, dest, entries, runs), encoding="utf-8")
    total = sum(sum(e.get("redactions", {}).values()) for e in entries)
    print(f"Digest: {dest} ({len(entries)} files, {total} redactions)")
    if not args.no_zip:
        archive = shutil.make_archive(str(dest), "zip", root_dir=args.out, base_dir=name)
        print(f"Zip:    {archive}  (attach this to the project thread)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
