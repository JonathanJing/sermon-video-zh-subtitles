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
hashes, truncation and redaction counts), ``INDEX.md`` (outcomes, stage
timings, failed stages and error lines) and a ``RETROSPECTIVE.md`` skeleton.

It is written to ignored ``artifacts/run-reports/<name>/``. To make it readable
by cloud sessions, ``scripts/publish_run_report.sh`` verifies it and opens a
docs-only PR that adds it as ``docs/reports/runs/<name>/``. The repository is
public, so that script re-checks the redaction before anything is pushed.

Usage (repo root):
  .venv/bin/python scripts/export_run_digest.py artifacts/dev-180s-page-test-20261004/<run-id>
  .venv/bin/python scripts/export_run_digest.py RUN_DIR [RUN_DIR ...] --name 20261008-8x8-round2
  scripts/publish_run_report.sh artifacts/run-reports/<name>
"""
from __future__ import annotations

import argparse
import csv
from collections import deque
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
# diagnose/refute/risk.json carry agent-trial rows the run report reviews case by case.
WHOLE_NAMES = {"outcome.json", "timings.tsv", "summary.json", "preflight.json", "diagnose.json", "refute.json", "risk.json"}
MAX_WHOLE_BYTES = 256 * 1024
# Agent-trial result files hold one row per case; one over the cap is exported as row chunks, each under the cap,
# so case-level evidence is not dropped. The whole-digest cap still bounds the total.
ROW_NAMES = {"preflight.json", "diagnose.json", "refute.json", "risk.json"}
MAX_DIGEST_BYTES = 2 * 1024 * 1024
NAME = re.compile(r"\d{8}-[A-Za-z0-9._-]+")  # Same set publish_run_report.sh accepts
RETROSPECTIVE_SECTIONS = [
    ("实际覆盖范围", "按 L1–L4 写本轮执行、复用和未执行的部分；模拟审核和诊断级结果原样写出。"),
    ("结果和结束信号", "各运行目录的 outcome.json；独占 Spark 的运行以 round: 行为准。"),
    ("耗时", "按 timings.tsv 列阶段并与上一轮比较，把等待和计算分开。"),
    ("错误", "现象、原因、处理、回归测试、对应提交或 PR。"),
    ("占用资源之后才暴露的错误", "哪些本可以在预检发现，要补哪项预检。"),
    ("遗留状态", "Dev 上无引用的文件、未结束的 job hold、已用构建号、待删除的本地产物。"),
    ("外部可见的变化", "Dev 发布、TestFlight、受保护分支推送各自的证据；没做的验收写 not_run。"),
    ("后续", "每条写负责人和跟踪的 PR 或 backlog 条目。"),
]
LOG_HEAD, LOG_TAIL, LOG_MAX_ERRORS, LOG_LINE_CHARS = 40, 200, 50, 2000
SECRET_KEY = re.compile(r"(?i)(?:api[_-]?key|token|secret|password|passwd|cookie|authorization)$")
PLACEHOLDERS = {"<redacted>", '"<redacted>"', "'<redacted>'"}
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
        r"(\"[^\"\n]*\"|'[^'\n]*'|[^\s,;}]+)"),
     lambda m: m[1] + ('"<redacted>"' if m[2][0] == '"' else "'<redacted>'" if m[2][0] == "'" else "<redacted>")),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"), "<email>"),
    ("private_ip", re.compile(
        r"\b(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}"
        r"|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])(?:\.\d{1,3}){2})\b"), "<private-ip>"),
    ("hostname", re.compile(r"\b[\w-]+(?:\.[\w-]+)*\.(?:ts\.net|local|lan|internal)\b"), "<host>"),
    ("home_dir", re.compile(r"/(?:Users|home)/[^/\s\"']+"), "~"),
]

REDACTIONS_BY_NAME = {name: pattern for name, pattern, _ in REDACTIONS}


def env_secret_values() -> list[str]:
    """Values of secret-like variables in this process (e.g. under the OpenAI launcher)."""
    marker = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|COOKIE", re.I)
    return sorted({v for k, v in os.environ.items() if marker.search(k) and len(v) >= 8}, key=len, reverse=True)


def redact_json(value, secrets: list[str], counts: dict[str, int]):
    """Redact a parsed JSON value field by field so the copy stays valid JSON."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if SECRET_KEY.search(str(key)) and item not in ("<redacted>", None):
                counts["secret_field"] = counts.get("secret_field", 0) + 1
                out[key] = "<redacted>"
            else:
                out[key] = redact_json(item, secrets, counts)
        return out
    if isinstance(value, list):
        return [redact_json(item, secrets, counts) for item in value]
    if isinstance(value, str):
        text, found = redact(value, secrets)
        for name, hits in found.items():
            counts[name] = counts.get(name, 0) + hits
        return text
    return value


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


def verify(dest: Path, secrets: list[str]) -> list[str]:
    """Return files that still hold a value the redaction rules would change."""
    leaks = []
    for path in sorted(p for p in dest.rglob("*") if p.is_file() and p.suffix != ".zip"):
        text = path.read_text(encoding="utf-8", errors="replace")
        hits = [name for name, pattern, _ in REDACTIONS if name != "secret_field" and pattern.search(text)]
        # A secret field counts unless its value is the placeholder or a plain count
        # (the manifest's own redaction counters, e.g. "env_secret": 1).
        hits += ["secret_field"] if any(m[2] not in PLACEHOLDERS and not m[2].isdigit()
                                        for m in REDACTIONS_BY_NAME["secret_field"].finditer(text)) else []
        hits += ["env_secret"] if any(value in text for value in secrets) else []
        if hits:
            leaks.append(f"{path.relative_to(dest)}: {', '.join(hits)}")
    return leaks


def read_log(path: Path, digest) -> tuple[str, bool]:
    """Stream a log: keep head, tail and the first error lines in between, hashing as it goes."""
    head: list[str] = []
    tail: deque[tuple[int, str]] = deque(maxlen=LOG_TAIL)
    errors: list[tuple[int, str]] = []  # Bounded: later tail lines may still be dropped from it.
    error_total, count = 0, 0
    with path.open("rb") as stream:
        for raw in stream:
            digest.update(raw)
            count += 1
            line = raw.decode("utf-8", errors="replace")
            line = line if len(line) <= LOG_LINE_CHARS else line[:LOG_LINE_CHARS] + " ...[line truncated]\n"
            line = line if line.endswith("\n") else line + "\n"
            if count <= LOG_HEAD:
                head.append(line)
                continue
            if len(tail) == tail.maxlen:
                number, dropped = tail[0]
                if ERROR_LINE.search(dropped):
                    error_total += 1
                    if len(errors) < LOG_MAX_ERRORS:
                        errors.append((number, dropped))
            tail.append((count, line))
    if count <= LOG_HEAD + LOG_TAIL:
        return "".join(head + [line for _, line in tail]), False
    omitted = count - LOG_HEAD - LOG_TAIL
    note = f"... {omitted} lines omitted; {error_total} error-like lines, {len(errors)} kept below ...\n"
    return "".join(head + [note] + [f"[line {n}] {line}" for n, line in errors] +
                   ["... end of omitted section ...\n"] + [line for _, line in tail]), True


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
        digest = hashlib.sha256()
        entry = {"run": label, "path": str(rel), "kind": kind, "bytes": path.stat().st_size, "truncated": False}
        if kind == "log":
            text, entry["truncated"] = read_log(path, digest)
        elif entry["bytes"] > MAX_WHOLE_BYTES and path.name in ROW_NAMES and entry["bytes"] <= MAX_DIGEST_BYTES:
            raw = path.read_bytes()
            digest.update(raw)
            entry["sha256"] = digest.hexdigest()
            if write_row_chunks(raw, dest / label / rel, secrets, entry):
                entries.append(entry)
                continue
            entry.update(omitted="over_size_cap")
            entries.append(entry)
            continue
        elif entry["bytes"] > MAX_WHOLE_BYTES:  # Hash in chunks; never load it.
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1 << 20), b""):
                    digest.update(chunk)
            entry.update(sha256=digest.hexdigest(), omitted="over_size_cap")
            entries.append(entry)
            continue
        else:
            raw = path.read_bytes()
            digest.update(raw)
            text = raw.decode("utf-8", errors="replace")
        entry["sha256"] = digest.hexdigest()
        parsed = None
        if path.suffix == ".json":
            try:
                parsed = json.loads(text)
            except ValueError:
                parsed = None
        if parsed is not None:
            entry["redactions"] = {}
            text = json.dumps(redact_json(parsed, secrets, entry["redactions"]), ensure_ascii=False, indent=2) + "\n"
        else:
            text, entry["redactions"] = redact(text, secrets)
        target = dest / label / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        entries.append(entry)
    return entries, skipped


def write_row_chunks(raw: bytes, target: Path, secrets: list[str], entry: dict) -> bool:
    """Write a redacted row file as <stem>.rows-NN.json chunks under the whole-file cap. False, with nothing
    written, when it has no rows or a single row (with the file's other fields) cannot fit under the cap."""
    try:
        value = json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError:
        return False
    if not isinstance(value, dict) or not isinstance(value.get("rows"), list):
        return False
    entry["redactions"] = {}
    value = redact_json(value, secrets, entry["redactions"])
    rest = {k: v for k, v in value.items() if k != "rows"}
    budget = MAX_WHOLE_BYTES - 4096
    chunks, current = [], []
    size = len(json.dumps(rest, ensure_ascii=False, indent=2).encode("utf-8"))  # Metadata rides in the first part.
    for row in value["rows"]:
        row_size = len(json.dumps(row, ensure_ascii=False, indent=2).encode("utf-8")) + 8
        if current and size + row_size > budget:
            chunks.append(current)
            current, size = [], 0
        current.append(row)
        size += row_size
    chunks.append(current)
    parts = {}
    for index, rows in enumerate(chunks, 1):
        part = {"source": target.name, "part": index, "parts": len(chunks), **(rest if index == 1 else {}),
                "rows": rows}
        text = json.dumps(part, ensure_ascii=False, indent=2) + "\n"
        if len(text.encode("utf-8")) > MAX_WHOLE_BYTES:
            return False  # One row alone is over the cap; the file is reported as omitted instead.
        parts[f"{target.stem}.rows-{index:02d}.json"] = text
    target.parent.mkdir(parents=True, exist_ok=True)
    for name, text in parts.items():
        (target.parent / name).write_text(text, encoding="utf-8")
    names = list(parts)
    entry["chunks"] = names
    return True


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
        for entry in (e for e in entries if e["run"] == label and Path(e["path"]).name == "summary.json"
                      and "omitted" not in e):
            record = read_json(dest / label / entry["path"]) or {}
            if "status" in record:
                out.append(f"- summary `{entry['path']}`: **{record['status']}**")
            locales = record.get("locales")
            for locale, row in (locales.items() if isinstance(locales, dict) else []):
                row = row if isinstance(row, dict) else {}
                detail = row.get("reason") or "; ".join(map(str, row.get("problems") or []))
                out.append(f"- summary `{entry['path']}` {locale}: **{row.get('status', '?')}**"
                           + (f" ({str(detail)[:200]})" if detail else ""))
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


def retrospective_markdown(name: str) -> str:
    out = [f"# 复盘：{name}", "", "数据见同目录 INDEX.md 和 manifest.json。未填写的小节删掉前请写明原因。", ""]
    for heading, hint in RETROSPECTIVE_SECTIONS:
        out += [f"## {heading}", "", f"<!-- {hint} -->", "待填写。", ""]
    return "\n".join(out)


def write_report(run_dirs: list[Path], label: str) -> Path | None:
    """Write a dated report for a driver that just finished; never raises.

    Drivers call this when they exit so every run leaves a report, pass or fail.
    """
    name = f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{label}"
    try:
        dirs = [d for d in run_dirs if Path(d).is_dir()]
        if not dirs or main([*map(str, dirs), "--name", name]) != 0:
            raise RuntimeError("no report written")
    except (Exception, SystemExit) as error:  # The run's own result must stand.
        print(f"Run report not written ({error}); export it by hand with scripts/export_run_digest.py",
              file=sys.stderr)
        return None
    print(f"Publish for cloud review: scripts/publish_run_report.sh artifacts/run-reports/{name}", file=sys.stderr)
    return ROOT / "artifacts/run-reports" / name


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run_dirs", nargs="+", type=Path, help="Run directories (usually under artifacts/)")
    parser.add_argument("--verify", action="store_true",
                        help="Only check that existing digest directories hold nothing the redaction rules would change")
    parser.add_argument("--name", help="YYYYMMDD-<label> (default: today UTC + first run directory name)")
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts/run-reports")
    parser.add_argument("--zip", action="store_true", help="Also write <name>.zip next to the digest")
    args = parser.parse_args(argv)

    for run_dir in args.run_dirs:
        if not run_dir.is_dir():
            parser.error(f"{run_dir} is not a directory")
    if args.verify:
        leaks = [f"{d}/{leak}" for d in args.run_dirs for leak in verify(d, env_secret_values())]
        print("\n".join(leaks) or "No unredacted values found.", file=sys.stderr if leaks else sys.stdout)
        return 1 if leaks else 0
    label = re.sub(r"[^A-Za-z0-9._-]+", "-", args.run_dirs[0].resolve().name).strip("-") or "run"
    name = args.name or f"{datetime.now(timezone.utc):%Y%m%d}-{label}"
    if not NAME.fullmatch(name):
        parser.error("--name must be YYYYMMDD-<label> using ASCII letters, digits, '.', '_' and '-'")
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
    (dest / "RETROSPECTIVE.md").write_text(retrospective_markdown(name), encoding="utf-8")
    size = sum(p.stat().st_size for p in dest.rglob("*") if p.is_file())
    if size > MAX_DIGEST_BYTES:
        shutil.rmtree(dest)
        print(f"Digest would be {size} bytes (cap {MAX_DIGEST_BYTES}); nothing written. "
              "Pass fewer run directories.", file=sys.stderr)
        return 1
    total = sum(sum(e.get("redactions", {}).values()) for e in entries)
    print(f"Digest: {dest} ({len(entries)} files, {total} redactions)")
    if args.zip:
        archive = shutil.make_archive(str(dest), "zip", root_dir=args.out, base_dir=name)
        print(f"Zip:    {archive}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
