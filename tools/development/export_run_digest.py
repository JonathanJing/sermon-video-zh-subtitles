#!/usr/bin/env python3
"""Pack the small text evidence of a local test run into a redacted digest.

Runs leave their evidence under ignored ``artifacts/`` on the Mac (and on
Spark), where a cloud review session cannot read it. This tool copies only the
files a retrospective needs from one or more run directories:

- ``outcome.json``, ``timings.tsv``, ``summary.json``, the run journal
  ``journal.ndjson``, the decision record ``decisions.ndjson`` and
  ``*receipt*.json`` (whole, when under the size cap);
- ``source-budget.json`` as a settlement summary only (requests, reserved and
  estimated cost, tokens, unknown-cost reasons), never the ledger itself;
- ``*.log`` (first and last lines, with every error line in between).

Media, model outputs and any other file are left out and only counted. Human
acceptances and approvals reach the report as hash-bound entries in the decision
record, not as copies: their files can hold sermon text. Every
copied file is redacted (API keys, tokens, cookies, private keys, emails,
private IPs, cloud-drive share links, home directories, and the values of
secret-like environment variables) before it is written. The digest gets ``manifest.json`` (source
hashes, truncation and redaction counts), ``INDEX.md`` (outcomes, stage
timings, failed stages and error lines) and a ``RETROSPECTIVE.md`` skeleton
pre-filled with the run's total time and the model identities, tokens and
speeds found in the copied receipts.

It is written to ignored ``artifacts/run-reports/<name>/``. To make it readable
by cloud sessions, ``tools/development/publish_run_report.sh`` verifies it and opens a
docs-only PR that adds it as ``docs/reports/runs/<name>/``. The repository is
public, so that script re-checks the redaction before anything is pushed.

Usage (repo root):
  .venv/bin/python tools/development/export_run_digest.py artifacts/dev-180s-page-test-20261004/<run-id>
  .venv/bin/python tools/development/export_run_digest.py RUN_DIR [RUN_DIR ...] --name 20261008-8x8-round2
  tools/development/publish_run_report.sh artifacts/run-reports/<name>
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter, deque
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCHEMA = "sermon-run-digest-v1"
# diagnose/refute/risk.json carry agent-trial rows the run report reviews case by case.
WHOLE_NAMES = {"outcome.json", "timings.tsv", "summary.json", "preflight.json", "diagnose.json", "refute.json", "risk.json",
               # The run journal and decision record (run_journal.py, record_decision.py) are the retrospective's spine.
               "journal.ndjson", "decisions.ndjson"}
BUDGET_LEDGER = "source-budget.json"
BUDGET_SUMMARY_NAME = "source-budget.settlement.json"
BUDGET_SUMMARY_SCHEMA_V1 = "sermon-run-digest-budget-settlement-v1"
BUDGET_SUMMARY_SCHEMA = "sermon-run-digest-budget-settlement-v2"
MAX_BUDGET_LEDGER_BYTES = 32 * 1024 * 1024
MAX_WHOLE_BYTES = 256 * 1024
# Agent-trial result files hold one row per case; one over the cap is exported as row chunks, each under the cap,
# so case-level evidence is not dropped. The whole-digest cap still bounds the total.
ROW_NAMES = {"preflight.json", "diagnose.json", "refute.json", "risk.json"}
MAX_DIGEST_BYTES = 2 * 1024 * 1024
NAME = re.compile(r"\d{8}-[A-Za-z0-9._-]+")  # Same set publish_run_report.sh accepts
# Fixed retrospective content (docs/test-run-retrospective.zh.md): total time, each layer's model,
# time and speed, errors, and improvements. The exporter pre-fills what the copied evidence shows.
LAYER_ROWS = ["L1 来源 ASR", "L1 词级对齐（MFA）", "L1 英文机器评审", "L2 初译", "L2 独立审核", "文本质检（回译）",
              "L3 配音（TTS）", "L3 回转写筛查（ASR）", "音频质检", "L4 构建与发布"]
RETROSPECTIVE_SECTIONS = [
    ("结论先行", "交付类型（dual_pdf／live_session／four_layer_release／测试）、最终状态和结束信号（outcome.json；"
                 "独占 Spark 以 round: 行为准）、证据边界。模拟审核和诊断级结果原样写出。"),
    ("总时间", "从开始到结束的墙钟时间，拆成计算、等待（人、服务、凭据）和返工；与上一轮同类运行比较。"),
    ("各层模型、耗时与速度", "每层写模型或后端、推理强度和 tier、调用次数、计算耗时、token 或音频秒数、"
                            "速度（输出 token/s 或 ×实时）、费用。没执行的层写 not_run，复用的写 reused 和来源。"),
    ("错误", "每个错误一行：发现时机分预检／占用资源后／发布后；占用资源后才发现的，写要补的预检。"),
    ("可以改进的地方", "按速度、成本、预检、质量、流程分类；每条写预期收益、负责人和跟踪的 PR 或 backlog 条目。"),
    ("实际覆盖范围", "按 L1–L4 写本轮执行、复用和未执行的部分。"),
    ("遗留状态", "Dev 上无引用的文件、未结束的 job hold、已用构建号、待删除的本地产物。"),
    ("外部可见的变化", "Dev 发布、TestFlight、受保护分支推送各自的证据；没做的验收写 not_run。"),
]
LOG_HEAD, LOG_TAIL, LOG_MAX_ERRORS, LOG_LINE_CHARS = 40, 200, 50, 2000
SECRET_KEY = re.compile(r"(?i)(?:api[_-]?key|token|secret|password|passwd|cookie|authorization)$")
PLACEHOLDERS = {"<redacted>", '"<redacted>"', "'<redacted>'"}
ERROR_LINE = re.compile(r"Traceback|Error\b|Exception|FAILED|\bfail(ed)?\b|refused|denied|timed? ?out", re.I)

# A share link ends at whitespace, quoting or markup, at CJK/fullwidth punctuation
# (Chinese prose follows a link without a space), and never on trailing ASCII punctuation.
LINK_CHAR = r"[^\s\"'<>()\[\]`|\\\u3000-\u303f\uff00-\uffef]"
LINK_TAIL = LINK_CHAR + r"*(?<![.,;:!?])"

REDACTIONS: list[tuple[str, re.Pattern[str], str]] = [
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
     "<private-key>"),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), "<openai-key>"),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"), "<github-token>"),
    ("google_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), "<google-key>"),
    ("bearer", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer <redacted>"),
    # Share links to private cloud folders: a Google Drive folder link in a Layer 1 summary's sourceUrl
    # reached run-report PR #1084 on 2026-10-18. Runs before secret_field so a query string goes with its URL.
    # OneDrive covers consumer hosts, organization <tenant>-my.sharepoint.com and SharePoint :x:/ share
    # links; Dropbox covers file (s, scl) and folder (sh) shares.
    ("private_drive_link", re.compile(
        r"(?i)(?:https?://)?(?<![\w.-])(?:(?:drive\.google\.com|onedrive\.live\.com|1drv\.ms)(?![\w.-])"
        r"|docs\.google\.com/(?:" + LINK_CHAR[:-1] + r"/]+/)*d/"
        r"|[\w-]+-my\.sharepoint\.com(?![\w.-])|[\w-]+\.sharepoint\.com/:[a-z]{1,2}:/"
        r"|(?:www\.)?dropbox\.com/(?:s|scl|sh)/"
        r"|(?:www\.)?icloud\.com/iclouddrive\b)" + LINK_TAIL), "<private-drive-link>"),
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
            # Keys are redacted like values: a host map keyed by "user@192.168.x.y"
            # leaked private addresses from Layer 1 summaries on 2026-10-11.
            safe_key, found = redact(str(key), secrets)
            for name, hits in found.items():
                counts[name] = counts.get(name, 0) + hits
            if safe_key in out:
                # Two keys can redact alike ("a@10.0.0.1" and "b@10.0.0.2" both become "<email>"); keep both entries.
                number = 2
                while f"{safe_key}#{number}" in out:
                    number += 1
                safe_key = f"{safe_key}#{number}"
                counts["key_collision"] = counts.get("key_collision", 0) + 1
            if SECRET_KEY.search(str(key)) and item not in ("<redacted>", None):
                counts["secret_field"] = counts.get("secret_field", 0) + 1
                out[safe_key] = "<redacted>"
            else:
                out[safe_key] = redact_json(item, secrets, counts)
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


PRIVATE_OUTCOME_PREFIX = 'sermon-api-cli-outcome-v'
PRIVATE_OUTCOME_FIELDS = {'response', 'rawBodyBase64', 'failure', 'executionBinding'}

def private_outcome(value, path):
    return (isinstance(value, dict) and (str(value.get('schemaVersion','')).startswith(PRIVATE_OUTCOME_PREFIX)
                                           or 'rawBodyBase64' in value)
            or 'api-cli-outcomes' in path.parts)

def outcome_metadata(value):
    allowed = {'schemaVersion','status','purpose','requestSha256','responseSha256',
               'rawBodySha256','httpStatus','failureType','notDispatchedReason',
               'executionBindingSha256','reconciliationEvidenceSha256','reconciledFromSchemaVersion'}
    return {**{key:value[key] for key in allowed if key in value},
            'privateResponseOmitted':True, 'exportSchemaVersion':'sermon-api-cli-outcome-metadata-v1'}


def private_response_nodes(value):
    if isinstance(value,dict):
        if private_outcome(value,Path()) and PRIVATE_OUTCOME_FIELDS & set(value): return True
        return any(private_response_nodes(child) for child in value.values())
    if isinstance(value,list):return any(private_response_nodes(child) for child in value)
    return False

def public_metadata_tree(value):
    if isinstance(value,dict):
        if private_outcome(value,Path()):return outcome_metadata(value)
        return {key:public_metadata_tree(child) for key,child in value.items()}
    if isinstance(value,list):return [public_metadata_tree(child) for child in value]
    return value


def verify(dest: Path, secrets: list[str]) -> list[str]:
    """Return files that still hold a value the redaction rules would change."""
    leaks = []
    for path in sorted(p for p in dest.rglob("*") if p.is_file() and p.suffix != ".zip"):
        text = path.read_text(encoding="utf-8", errors="replace")
        try: parsed = json.loads(text)
        except ValueError: parsed = None
        if (private_outcome(parsed,path) and (not isinstance(parsed,dict) or PRIVATE_OUTCOME_FIELDS & set(parsed))) or private_response_nodes(parsed):
            leaks.append(f"{path.relative_to(dest)}: private_model_response")
        hits = [name for name, pattern, _ in REDACTIONS if name != "secret_field" and pattern.search(text)]
        # A secret field counts unless its value is the placeholder or a plain count
        # (the manifest's own redaction counters, e.g. "env_secret": 1).
        hits += ["secret_field"] if any(m[2] not in PLACEHOLDERS and not m[2].isdigit()
                                        for m in REDACTIONS_BY_NAME["secret_field"].finditer(text)) else []
        hits += ["env_secret"] if any(value in text for value in secrets) else []
        if hits:
            leaks.append(f"{path.relative_to(dest)}: {', '.join(hits)}")
    return leaks


def tidy_whitespace(dest: Path) -> list[str]:
    """Strip trailing whitespace and blank lines at EOF from every text file, as `git diff --check` requires.

    Copied logs (torch warnings, xcodebuild output) and hand-edited Markdown often carry both, and the docs
    gate rejects the report PR for it. Binary or non-UTF-8 files are left untouched. Returns changed paths."""
    changed = []
    for path in sorted(p for p in dest.rglob("*") if p.is_file() and not p.is_symlink()):
        raw = path.read_bytes()
        if b"\0" in raw:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        lines = [line.rstrip(" \t\r\f\v") for line in text.split("\n")]
        while lines and not lines[-1]:
            lines.pop()
        tidy = "\n".join(lines) + "\n" if lines else ""
        if tidy != text:
            path.write_text(tidy, encoding="utf-8")
            changed.append(str(path.relative_to(dest)))
    return changed


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
    if path.name == BUDGET_LEDGER:
        return "budget"
    if path.suffix == ".log":
        return "log"
    return None


def budget_summary(ledger) -> dict:
    """Settlement totals from a source budget ledger, without its request identities or resource paths."""
    rows = ledger.get("requests") if isinstance(ledger, dict) else None
    if not isinstance(rows, dict):
        return {"schemaVersion": BUDGET_SUMMARY_SCHEMA, "status": "unreadable_ledger"}
    rows = [row for row in rows.values() if isinstance(row, dict)]
    returned = [row for row in rows if row.get("status") == "returned"]
    settled = [row["settlement"] for row in returned if isinstance(row.get("settlement"), dict)]
    # Reused responses were paid under another root: they reserve and cost nothing here.
    reused = [s for s in settled if s.get("costStatus") == "reused"]
    settled = [s for s in settled if s.get("costStatus") != "reused"]
    priced = [s for s in settled if s.get("costStatus") == "estimated_upper_bound" and type(s.get("costMicrousd")) is int]
    by_model: dict[str, dict] = {}
    for item in settled:
        model = by_model.setdefault(str(item.get("requestedModel")), {"returned": 0, "priced": 0, "estimatedMicrousd": 0})
        model["returned"] += 1
        if item in priced:
            model["priced"] += 1
            model["estimatedMicrousd"] += item["costMicrousd"]
    tokens = {key: sum((item.get("usage") or {}).get(key) or 0 for item in settled)
              for key in ("inputTokens", "outputTokens", "cachedInputTokens", "reasoningTokens")}
    return {"schemaVersion": BUDGET_SUMMARY_SCHEMA, "status": "summarized", "ledgerSchemaVersion": ledger.get("schemaVersion"),
            "requests": len(rows), "statuses": dict(Counter(str(row.get("status")) for row in rows)),
            "reservedMicrousd": sum((row.get("bounds") or {}).get("costMicrousd") or 0 for row in rows
                                    if ((row.get("settlement") or {}).get("costStatus")) != "reused"),
            "reused": len(reused),
            "returned": len(returned), "withoutSettlement": len(returned) - len(settled) - len(reused),
            "priced": len(priced), "estimatedMicrousd": sum(item["costMicrousd"] for item in priced),
            "unknownCost": dict(Counter(str(item.get("reasonCode")) for item in settled if item not in priced)),
            "tokens": tokens, "byModel": by_model, "invoiceVerified": False}


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
        if kind == "budget":
            entries.append(write_budget_summary(path, rel, dest / label, secrets, entry))
            continue
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
        if private_outcome(parsed,rel):
            if not isinstance(parsed,dict):
                entry.update(omitted='private_api_cli_outcome');entries.append(entry);continue
            parsed = outcome_metadata(parsed)
            entry['privateResponseOmitted'] = True
        if parsed is not None:
            if private_response_nodes(parsed): entry['privateResponseOmitted'] = True
            parsed = public_metadata_tree(parsed)
            entry["redactions"] = {}
            text = json.dumps(redact_json(parsed, secrets, entry["redactions"]), ensure_ascii=False, indent=2) + "\n"
        else:
            text, entry["redactions"] = redact(text, secrets)
        if path.name in ROW_NAMES and len(text.encode("utf-8")) > MAX_WHOLE_BYTES:
            # Compact source JSON can grow past the cap once indented; the written size decides chunking.
            if not write_row_chunks(raw, dest / label / rel, secrets, entry):
                entry.update(omitted="over_size_cap")
            entries.append(entry)
            continue
        target = dest / label / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        entries.append(entry)
    return entries, skipped


def write_budget_summary(path: Path, rel: Path, dest: Path, secrets: list[str], entry: dict) -> dict:
    """Write the ledger's settlement summary next to where the ledger sat; the entry names the ledger as its source."""
    entry.update(source=str(rel), path=str(rel.with_name(BUDGET_SUMMARY_NAME)))
    if entry["bytes"] > MAX_BUDGET_LEDGER_BYTES:
        entry.update(omitted="over_size_cap")
        return entry
    raw = path.read_bytes()
    entry["sha256"] = hashlib.sha256(raw).hexdigest()
    try:
        ledger = json.loads(raw.decode("utf-8"))
    except ValueError:
        ledger = None
    entry["redactions"] = {}
    summary = redact_json(budget_summary(ledger), secrets, entry["redactions"])
    target = dest / entry["path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return entry


EMPTY_ROWS = len(json.dumps({"rows": []}, indent=2))


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
        # Measured at its nesting depth inside "rows", where indentation adds bytes on every line, plus the comma.
        row_size = len(json.dumps({"rows": [row]}, ensure_ascii=False, indent=2).encode("utf-8")) - EMPTY_ROWS + 2
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
    # The manifest path still opens: it holds a small index naming the parts, so a v1 consumer that reads every
    # non-omitted path finds valid JSON that points to the rows instead of a missing file.
    index = {"source": target.name, "chunked": True, "rowCount": len(value["rows"]), "parts": names}
    target.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
        for entry in (e for e in entries if e["run"] == label and e["kind"] == "budget" and "omitted" not in e):
            record = read_json(dest / label / entry["path"]) or {}
            out.append(budget_line(entry["source"], record))
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


def budget_line(source: str, record: dict) -> str:
    usd = lambda micro: f"US${micro / 1_000_000:.2f}"
    version=record.get("schemaVersion")
    if version not in {BUDGET_SUMMARY_SCHEMA_V1,BUDGET_SUMMARY_SCHEMA}:
        return f"- source budget `{source}`: unsupported settlement summary schema"
    if record.get("status") != "summarized":
        return f"- source budget `{source}`: unreadable ledger"
    line = (f"- source budget `{source}`: {record['returned']} of {record['requests']} requests returned; "
            f"reserved {usd(record['reservedMicrousd'])}")
    if version==BUDGET_SUMMARY_SCHEMA and record.get("reused",0):
        line += f"; {record['reused']} reused without new reservation"
    if record["priced"]:
        line += f"; estimated {usd(record['estimatedMicrousd'])} over {record['priced']} priced"
    if record["unknownCost"]:
        line += "; cost unknown: " + ", ".join(f"{reason} ×{count}" for reason, count in sorted(record["unknownCost"].items()))
    if record["withoutSettlement"]:
        line += (f"; {record['withoutSettlement']} without settlement (ledger {record['ledgerSchemaVersion']}; "
                 "SourceBudget.migrate_to_v3 books it)")
    return line + "; invoice not verified"


def _duration(seconds: float) -> str:
    seconds = int(round(seconds))
    return f"{seconds // 3600}h{seconds // 60 % 60:02d}m{seconds % 60:02d}s" if seconds >= 3600 else f"{seconds // 60}m{seconds % 60:02d}s"


def time_lines(dest: Path, entries: list[dict], runs: list[dict]) -> list[str]:
    """Wall, compute, waiting and rework time per run, from the journal, else outcome, else timings.tsv."""
    from tools.development import run_journal
    lines = []
    for run in runs:
        label, files = run["label"], [e for e in entries if e["run"] == run["label"] and "omitted" not in e]
        journals = [e for e in files if Path(e["path"]).name == run_journal.FILE_NAME]
        outcomes = [read_json(dest / label / e["path"]) or {} for e in files if Path(e["path"]).name == "outcome.json"]
        timings = [e for e in files if Path(e["path"]).name == "timings.tsv"]
        if journals:
            try:
                summary = run_journal.summary((dest / label / journals[0]["path"]).parent)
            except ValueError:
                summary = None
            if summary and summary["events"]:
                totals = summary["totals"]
                lines.append(f"- `{label}`（journal）：墙钟 {_duration(summary['wallSeconds'])}；计算 "
                             f"{_duration(totals['computeSeconds'])}，等待 {_duration(totals['waitingSeconds'])}，返工 "
                             f"{_duration(totals['reworkSeconds'])}（{totals['rework']} 次重跑）"
                             + (f"；未结束阶段 {', '.join(summary['openStages'])}" if summary["openStages"] else ""))
                continue
        spans = []
        for record in outcomes:
            try:
                spans.append((datetime.fromisoformat(str(record["startedAt"]).replace("Z", "+00:00")),
                              datetime.fromisoformat(str(record["endedAt"]).replace("Z", "+00:00"))))
            except (KeyError, ValueError):
                pass
        if spans:
            wall = (max(end for _, end in spans) - min(start for start, _ in spans)).total_seconds()
            lines.append(f"- `{label}`（outcome.json）：墙钟 {_duration(wall)}；没有 journal，计算和等待未拆分")
            continue
        total = 0.0
        for entry in timings:
            with (dest / label / entry["path"]).open(encoding="utf-8") as handle:
                rows = [r for r in csv.reader(handle, delimiter="\t") if r]
            column = next((i for i, name in enumerate(rows[0] if rows else []) if "second" in name.lower()), None)
            for row in rows[1:] if column is not None else []:
                try:
                    total += float(row[column])
                except (IndexError, ValueError):
                    pass
        lines.append(f"- `{label}`（timings.tsv 各阶段相加）：{_duration(total)}；不含阶段之间的等待"
                     if timings and total else f"- `{label}`：没有 journal、outcome 起止时间或 timings.tsv，无法自动计算")
    return lines


MODEL_KEYS = ("model", "requestedModel", "modelId")
EFFORT_KEYS = ("reasoningEffort", "reasoning_effort", "effort")
TIER_KEYS = ("serviceTier", "service_tier", "requestedServiceTier")
ELAPSED_KEYS = ("elapsedSeconds", "inferenceSeconds", "durationSeconds")


def _first(record: dict, keys) -> object:
    return next((record[k] for k in keys if record.get(k) not in (None, "")), None)


def model_rows(dest: Path, entries: list[dict]) -> list[dict]:
    """Model identities in the copied receipts, with call records, tokens and elapsed seconds where present."""
    found: dict[tuple, dict] = {}

    def visit(node, path: str) -> None:
        if isinstance(node, list):
            for item in node:
                visit(item, path)
            return
        if not isinstance(node, dict):
            return
        model = _first(node, MODEL_KEYS)
        if isinstance(model, str) and model.strip() and "<" not in model:
            settings = node.get("settings") if isinstance(node.get("settings"), dict) else {}
            effort = _first(node, EFFORT_KEYS) or _first(settings, EFFORT_KEYS)
            tier = _first(node, TIER_KEYS) or _first(settings, TIER_KEYS)
            row = found.setdefault((model, str(effort or "?"), str(tier or "?")),
                                   {"model": model, "effort": str(effort or "?"), "tier": str(tier or "?"), "records": 0,
                                    "files": set(), "outputTokens": 0, "timedOutputTokens": 0, "seconds": 0.0})
            row["records"] += 1
            row["files"].add(path)
            usage = node.get("usage") if isinstance(node.get("usage"), dict) else node
            output = usage.get("outputTokens", usage.get("output_tokens"))
            elapsed = _first(node, ELAPSED_KEYS)
            if isinstance(output, int) and not isinstance(output, bool):
                row["outputTokens"] += output
                if isinstance(elapsed, (int, float)) and not isinstance(elapsed, bool) and elapsed > 0:
                    row["timedOutputTokens"] += output
                    row["seconds"] += float(elapsed)
        for key, value in node.items():
            if key not in MODEL_KEYS:
                visit(value, path)

    for entry in entries:
        if entry["kind"] == "whole" and "omitted" not in entry and entry["path"].endswith(".json"):
            record = read_json(dest / entry["run"] / entry["path"])
            if record is not None:
                visit(record, f"{entry['run']}/{entry['path']}")
    return sorted(found.values(), key=lambda r: (r["model"], r["effort"], r["tier"]))


def _files(paths: set[str]) -> str:
    shown = ", ".join(f"`{path}`" for path in sorted(paths)[:3])
    return shown + (f" 等 {len(paths)} 个" if len(paths) > 3 else "")


def model_table(rows: list[dict]) -> list[str]:
    if not rows:
        return ["已复制的收据里没有模型身份；按各层的预算账本或收据手工填写。"]
    out = ["| 模型 | 推理强度 | tier | 调用记录 | 输出 token | 计时 | 输出 token/s | 来源文件 |", "|---|---|---|---|---|---|---|---|"]
    for row in rows:
        speed = f"{row['timedOutputTokens'] / row['seconds']:.1f}" if row["seconds"] else "—"
        out.append(f"| `{row['model']}` | {row['effort']} | {row['tier']} | {row['records']} | {row['outputTokens'] or '—'} | "
                   f"{_duration(row['seconds']) if row['seconds'] else '—'} | {speed} | {_files(row['files'])} |")
    return out + ["", "同一次调用可能在请求和响应两处各记一次；速度只用同一记录里同时有输出 token 和耗时的部分。"]


def retrospective_markdown(name: str, dest: Path | None = None, entries: list[dict] | None = None,
                           runs: list[dict] | None = None) -> str:
    entries, runs = entries or [], runs or []
    auto = {
        "总时间": (["自动汇总（核对后保留）：", ""] + time_lines(dest, entries, runs)) if dest else [],
        "各层模型、耗时与速度": [
            "| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |",
            "|---|---|---|---|---|---|---|---|---|"] + [f"| {layer} | 待填写 | | | | | | | |" for layer in LAYER_ROWS]
            + (["", "已复制收据里出现的模型（自动汇总，按层归入上表）：", ""] + model_table(model_rows(dest, entries))
               if dest else []),
        "错误": ["| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |", "|---|---|---|---|---|---|---|",
                 "| 待填写 | | | 预检／占用资源后／发布后 | | | |"],
        "可以改进的地方": ["| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |", "|---|---|---|---|---|---|",
                           "| 速度／成本／预检／质量／流程 | 待填写 | | | | |"],
    }
    out = [f"# 复盘：{name}", "", "数据见同目录 INDEX.md 和 manifest.json。未填写的小节删掉前请写明原因。", ""]
    for heading, hint in RETROSPECTIVE_SECTIONS:
        out += [f"## {heading}", "", f"<!-- {hint} -->"] + (auto.get(heading) or ["待填写。"]) + [""]
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
        print(f"Run report not written ({error}); export it by hand with tools/development/export_run_digest.py",
              file=sys.stderr)
        return None
    print(f"Publish for cloud review: tools/development/publish_run_report.sh artifacts/run-reports/{name}", file=sys.stderr)
    return ROOT / "artifacts/run-reports" / name


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run_dirs", nargs="+", type=Path, help="Run directories (usually under artifacts/)")
    parser.add_argument("--verify", action="store_true",
                        help="Only check that existing digest directories hold nothing the redaction rules would change")
    parser.add_argument("--tidy-whitespace", action="store_true",
                        help="Only strip trailing whitespace and blank lines at EOF in existing digest directories")
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
    if args.tidy_whitespace:
        for run_dir in args.run_dirs:
            for path in tidy_whitespace(run_dir):
                print(f"Tidied whitespace: {run_dir}/{path}")
        return 0
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
    (dest / "RETROSPECTIVE.md").write_text(retrospective_markdown(name, dest, entries, runs), encoding="utf-8")
    tidy_whitespace(dest)
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
