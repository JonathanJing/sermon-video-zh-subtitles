"""Shared helpers for the sentence-first DeepSeek coherence pipeline (experiment only).

No production imports: this line deliberately stays inside
``experiments/sentence-first-agent`` and writes only under the run directory.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.error
import urllib.request

GLOSSARY_SCHEMA = "sentence-first-glossary-v1"
WINDOW_SCHEMA = "sentence-first-window-v1"
COHERENCE_SCHEMA = "sentence-first-coherence-v1"
AUDIT_SCHEMA = "sentence-first-audit-v1"
GLOSSARY_SLICE_CHARS = 4000
MAX_GLOSSARY_CHARS = 6000
GLOSSARY_LISTS = ("people", "relations", "recurringPhrases", "culturalReferences")
GLOSSARY_TRIM = ("culturalReferences", "recurringPhrases", "relations", "people")
TERMINAL = re.compile(r"[.!?。！？][\"'”’)]?$")
CONNECTIVE_START = re.compile(r"^(and|but|so|because|which|that|when|while|if|or|then|yet|for)\b", re.I)
NUMBER_WORDS = {
    0: "零", 1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八", 9: "九",
    10: "十", 11: "十一", 12: "十二", 20: "二十", 30: "三十", 40: "四十", 50: "五十",
    60: "六十", 70: "七十", 80: "八十", 90: "九十", 100: "一百",
}


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def continues(previous: dict, unit: dict) -> bool:
    """Whether ``unit`` finishes the sentence started by ``previous``."""
    left = str(previous.get("english", "")).strip()
    right = str(unit.get("english", "")).strip()
    if not left or not right:
        return False
    if not TERMINAL.search(left):
        return True
    if left.endswith((",", ";", ":", "—", "-")):
        return True
    return bool(right[:1].islower() or CONNECTIVE_START.match(right))


def continuation_flags(units: list[dict]) -> dict[str, dict[str, bool]]:
    flags = {u["id"]: {"continuesPrevious": False, "continuedByNext": False} for u in units}
    for previous, unit in zip(units, units[1:]):
        if continues(previous, unit):
            flags[unit["id"]]["continuesPrevious"] = True
            flags[previous["id"]]["continuedByNext"] = True
    return flags


def chain_plan(units: list[dict], chains: int) -> tuple[list[list[int]], list[dict]]:
    """Contiguous 1-based chains, preferring a boundary before a non-continuing sentence."""
    count = len(units)
    chains = max(1, min(chains, count))
    targets = [round(count * k / chains) for k in range(1, chains)]
    boundaries, notes = [], []
    used = set()
    for target in targets:
        window = max(4, count // (chains * 3))
        candidates = [i for i in range(max(2, target - window), min(count, target + window + 1))
                      if i not in used and not continues(units[i - 2], units[i - 1])]
        if candidates:
            boundary = min(candidates, key=lambda i: (abs(i - target), i))
            notes.append({"index": boundary, "target": target, "fallback": False})
        else:
            boundary = target
            notes.append({"index": boundary, "target": target, "fallback": True})
        used.add(boundary)
        boundaries.append(boundary)
    boundaries = sorted(set(boundaries))
    starts = [1] + [b + 1 for b in boundaries]
    ends = boundaries + [count]
    plan = [list(range(start, end + 1)) for start, end in zip(starts, ends) if start <= end]
    return plan, notes


def glossary_slices(units: list[dict], max_chars: int = GLOSSARY_SLICE_CHARS) -> list[list[dict]]:
    slices, current, size = [], [], 0
    for unit in units:
        line = len(unit["id"]) + len(unit["english"]) + 3
        if current and size + line > max_chars:
            slices.append(current)
            current, size = [], 0
        current.append(unit)
        size += line
    return slices + ([current] if current else [])


def empty_glossary() -> dict:
    return {"schemaVersion": GLOSSARY_SCHEMA, **{name: [] for name in GLOSSARY_LISTS},
            "scripture": [], "pronouns": {}}


def _entry_key(name: str, entry) -> str | None:
    if not isinstance(entry, dict):
        return None
    value = entry.get("reference" if name == "scripture" else "source")
    return value.strip().casefold() if isinstance(value, str) and value.strip() else None


def merge_glossary(known: dict, result) -> dict:
    merged = json.loads(json.dumps(known, ensure_ascii=False))
    if not isinstance(result, dict):
        return merged
    for name in (*GLOSSARY_LISTS, "scripture"):
        rows = result.get(name)
        if not isinstance(rows, list):
            continue
        seen = {_entry_key(name, row) for row in merged[name]}
        for row in rows:
            key = _entry_key(name, row)
            if key is not None and key not in seen:
                merged[name].append(row)
                seen.add(key)
    pronouns = result.get("pronouns")
    if isinstance(pronouns, dict):
        for name, value in pronouns.items():
            if isinstance(name, str) and isinstance(value, str) and value.strip():
                merged["pronouns"].setdefault(name, value.strip())
    return merged


def bounded_glossary(glossary: dict, max_chars: int = MAX_GLOSSARY_CHARS) -> tuple[dict, int]:
    bounded = json.loads(json.dumps(glossary, ensure_ascii=False))
    dropped = 0
    for name in GLOSSARY_TRIM:
        while bounded[name] and len(json.dumps(bounded, ensure_ascii=False)) > max_chars:
            bounded[name].pop()
            dropped += 1
    if len(json.dumps(bounded, ensure_ascii=False)) > max_chars:
        raise ValueError("glossary exceeds the character bound")
    return bounded, dropped


def prior_target(rows: list[dict], limit: int) -> list[dict]:
    return [{"id": row["id"], "target": row["target"]} for row in rows[-limit:]] if limit else []


def chinese_chars(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text))


def validate_sentences(rows, expected: list[dict], origin: str,
                       max_chars: dict[str, int] | None = None) -> list[str]:
    """Return failure strings for one window/repair reply."""
    if not isinstance(rows, list) or len(rows) != len(expected):
        return [f"{origin}: expected {len(expected)} sentences, got {len(rows) if isinstance(rows, list) else type(rows).__name__}"]
    failures = []
    expected_ids = [unit["id"] for unit in expected]
    if [row.get("id") for row in rows if isinstance(row, dict)] != expected_ids:
        return [f"{origin}: sentence ids/order changed"]
    for row, unit in zip(rows, expected):
        target = row.get("target")
        if not isinstance(target, str) or not target.strip():
            failures.append(f"{unit['id']}: empty target")
            continue
        if re.search(r"[A-Za-z]{4,}", target) and len(re.findall(r"[A-Za-z]", target)) > len(target) * 0.3:
            failures.append(f"{unit['id']}: target still looks English")
        if max_chars and chinese_chars(target) > max_chars.get(unit["id"], 10**9) * 2.5:
            failures.append(f"{unit['id']}: {chinese_chars(target)} chars exceed budget {max_chars.get(unit['id'])}")
        coverage = row.get("coverage")
        if not isinstance(coverage, list) or len(coverage) != 1:
            failures.append(f"{unit['id']}: coverage is not exactly one row")
            continue
        cover = coverage[0]
        if not isinstance(cover, dict) or cover.get("sourceUnitId") != unit.get("sourceUnitId"):
            failures.append(f"{unit['id']}: coverage names another unit")
        elif not isinstance(cover.get("targetText"), str) or cover["targetText"] not in target:
            failures.append(f"{unit['id']}: coverage text is not a target substring")
    return failures


def number_tokens(text: str) -> list[str]:
    return re.findall(r"\d+(?:\.\d+)?", text)


def target_has_number(target: str, token: str) -> bool:
    if token in target:
        return True
    if token.isdigit():
        value = int(token)
        return NUMBER_WORDS.get(value, "\0") in target
    return False


def english_number_tokens(text: str) -> list[str]:
    words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
             "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "twenty": 20,
             "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
             "eighty": 80, "ninety": 90, "hundred": 100}
    tokens = number_tokens(text)
    for word, value in words.items():
        if re.search(rf"\b{word}\b", text, re.I):
            tokens.append(str(value))
    return tokens


class DeepSeek:
    """Cached DeepSeek JSON calls with a cost ledger; no production dependency."""

    def __init__(self, cache_dir: Path, model: str = "deepseek-flash", effort: str = "low",
                 execute: bool = False, timeout: int = 300):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.model = model
        self.effort = effort
        self.execute = execute
        self.timeout = timeout
        self.key = os.environ.get("DEEPSEEK_API_KEY", "")
        self.calls = 0
        self.hits = 0
        self.cost = 0.0
        self.input_tokens = 0
        self.output_tokens = 0
        self.max_chars = 0

    def __call__(self, system: str, user: dict) -> dict:
        payload_user = json.dumps(user, ensure_ascii=False)
        self.max_chars = max(self.max_chars, len(system) + len(payload_user))
        if len(system) + len(payload_user) > 14000:
            raise ValueError(f"request exceeds the 14000-character guard ({len(system) + len(payload_user)})")
        key = hashlib.sha256(json.dumps(
            ["deepseek", self.model, self.effort, system, payload_user]).encode()).hexdigest()
        path = self.cache_dir / f"{key}.json"
        if path.is_file():
            self.hits += 1
            return json.loads(path.read_text())["result"]
        if not self.execute:
            raise SystemExit("DeepSeek call required but --execute was not passed")
        if not self.key:
            raise SystemExit("DEEPSEEK_API_KEY is not set")
        body = {"model": self.model, "reasoning_effort": self.effort, "max_tokens": 32768,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": payload_user}]}
        error = None
        for attempt in range(3):
            request = urllib.request.Request(
                "https://api.deepseek.com/chat/completions",
                data=json.dumps(body).encode(), method="POST",
                headers={"Authorization": "Bearer " + self.key, "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    value = json.loads(response.read())
                content = value["choices"][0]["message"]["content"]
                try:
                    result = json.loads(content)
                except json.JSONDecodeError:
                    start, end = content.find("{"), content.rfind("}")
                    if start < 0 or end <= start:
                        raise
                    result = json.loads(content[start:end + 1])
                if not isinstance(result, dict):
                    raise ValueError("reply is not an object")
            except urllib.error.HTTPError as exc:
                error = f"HTTP {exc.code}: {exc.read()[-300:]!r}"
                if exc.code in (401, 402, 403):
                    raise RuntimeError(error) from exc
                time.sleep(2 * (attempt + 1))
                continue
            except Exception as exc:  # noqa: BLE001
                error = f"{type(exc).__name__}: {exc}"
                time.sleep(2 * (attempt + 1))
                continue
            usage = value.get("usage") or {}
            self.calls += 1
            self.input_tokens += int(usage.get("prompt_tokens") or 0)
            self.output_tokens += int(usage.get("completion_tokens") or 0)
            self.cost += (0.3 * int(usage.get("prompt_tokens") or 0)
                          + 1.2 * int(usage.get("completion_tokens") or 0)) / 1_000_000
            path.write_text(json.dumps({"result": result, "usage": usage}, ensure_ascii=False))
            return result
        raise RuntimeError(f"DeepSeek call failed: {error}")

    def ledger(self) -> dict:
        return {"model": self.model, "effort": self.effort, "calls": self.calls, "hits": self.hits,
                "costUsd": round(self.cost, 4), "inputTokens": self.input_tokens,
                "outputTokens": self.output_tokens, "maxRequestChars": self.max_chars}


class ClaudeCLI:
    """Cached Claude CLI calls for the first-pass translator (subscription login)."""

    billing = "subscription"

    def __init__(self, cache_dir: Path, model: str = "opus", execute: bool = False, timeout: int = 900):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.model = model
        self.execute = execute
        self.timeout = timeout
        self.calls = 0
        self.hits = 0
        self.cost = 0.0
        self.input_tokens = 0
        self.output_tokens = 0
        self.max_chars = 0

    def __call__(self, system: str, user: dict) -> dict:
        payload_user = json.dumps(user, ensure_ascii=False)
        self.max_chars = max(self.max_chars, len(system) + len(payload_user))
        if len(system) + len(payload_user) > 14000:
            raise ValueError(f"request exceeds the 14000-character guard ({len(system) + len(payload_user)})")
        key = hashlib.sha256(json.dumps(["claude", self.model, system, payload_user]).encode()).hexdigest()
        path = self.cache_dir / f"{key}.json"
        if path.is_file():
            self.hits += 1
            return json.loads(path.read_text())["result"]
        if not self.execute:
            raise SystemExit("Claude call required but --execute was not passed")
        command = ["claude", "-p", "--model", self.model, "--no-session-persistence",
                   "--tools", "", "--setting-sources", "", "--output-format", "json",
                   "--system-prompt", system]
        done = subprocess.run(command, input=payload_user, capture_output=True, text=True,
                              timeout=self.timeout)
        try:
            reply = json.loads(done.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Claude CLI returned non-JSON: {done.stdout[-300:]} {done.stderr[-300:]}") from exc
        if reply.get("is_error"):
            raise RuntimeError(f"Claude CLI failed: {reply.get('result')} status={reply.get('api_error_status')}")
        content = reply["result"]
        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            start, end = content.find("{"), content.rfind("}")
            if start < 0 or end <= start:
                raise
            result = json.loads(content[start:end + 1])
        if not isinstance(result, dict):
            raise ValueError("Claude reply is not an object")
        usage = reply.get("usage") or {}
        self.calls += 1
        self.input_tokens += int(usage.get("input_tokens") or 0)
        self.output_tokens += int(usage.get("output_tokens") or 0)
        self.cost += float(reply.get("total_cost_usd") or 0)
        path.write_text(json.dumps({"result": result, "usage": usage,
                                    "costUsd": reply.get("total_cost_usd")}, ensure_ascii=False))
        return result

    def ledger(self) -> dict:
        return {"model": self.model, "effort": None, "calls": self.calls, "hits": self.hits,
                "costUsd": round(self.cost, 4), "inputTokens": self.input_tokens,
                "outputTokens": self.output_tokens, "maxRequestChars": self.max_chars}
