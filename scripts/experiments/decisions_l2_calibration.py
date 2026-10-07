#!/usr/bin/env python3
"""Non-production calibration of the OpenAI Decisions API as a Layer 2 text gate.

Run with ``python -m scripts.experiments.decisions_l2_calibration --help``.
The tool reads one frozen anchor manifest plus approved Target-Language
Candidates, keeps each group as a clean example, injects known errors into
copies (seeded errors), asks ``POST /v1/decisions`` the same question set for
every item, and reports detection and false-positive rates per threshold.

Outputs contain sermon text and belong in ignored artifacts, never in Git.
This tool creates no candidate, review receipt, waiver, or human approval.
Credentials come only from the environment (``OPENAI_API_KEY`` and optional
``OPENAI_PROJECT_ID``); run it through ``scripts/run_with_openai_environment.py
--environment dev``. ``--dry-run`` builds the dataset and a token estimate
without any network call. Repeat the same command to resume: answers are
cached per item content hash in the output directory.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import re
import time
from typing import Any, Callable
import urllib.error
import urllib.request


ENDPOINT = "https://api.openai.com/v1/decisions"
MODEL = "gpt-6-luna"
PRICE_PER_MILLION_INPUT = 0.10
QUESTION_SET_VERSION = "l2-text-gate-v1"
THRESHOLDS = (0.2, 0.3, 0.5, 0.7, 0.85)
MAX_ITEMS_DEFAULT = 400
# Clean items at or above this risk are exported for judgment: are they false alarms or real issues?
FLAGGED_CLEAN_THRESHOLD = 0.3

RISK_PREDICATES = {
    "omission": "The target-language translation leaves out information, a clause, a qualifier, or an emphasis that the English source states. Ignore harmless restructuring and natural idiom.",
    "addition": "The translation adds content the English source does not state, such as an extra claim, an example, a name, a number, or a scripture reference or verse number the speaker did not say.",
    "meaning_change": "The translation changes the meaning of the English source: reversed negation or polarity, a different subject or object, a different tense or certainty, or a statement that contradicts the source.",
    "name_or_number_error": "A person, place, book of the Bible, series term, number, or chapter/verse in the translation differs from the English source or from the given terminology.",
    "truncated_or_garbled": "The translation is cut off mid-sentence, repeats itself, mixes in another language's script where it should not, or is otherwise not a complete well-formed text.",
}
REFERENCE_PREDICATE = (
    "meaning_vs_reference",
    "Compared with the approved reference translation of the same English source, the target-language translation conveys a clearly different meaning. Differences in wording or style alone do not count.",
)
FLUENCY_LEVELS = [
    {"label": "unusable", "description": "A native listener could not follow it or would be misled."},
    {"label": "awkward", "description": "Understandable but clearly translated, with unnatural grammar or word choice."},
    {"label": "acceptable", "description": "Natural enough for a live interpretation listener, with minor stiffness."},
    {"label": "natural", "description": "Reads like something a native preacher would say."},
]
ISSUE_CHOICES = [
    {"value": "none", "description": "The translation faithfully and completely conveys the English source."},
    {"value": "omission", "description": "Something the English says is missing."},
    {"value": "addition", "description": "Something the English does not say was added."},
    {"value": "meaning_change", "description": "The meaning, polarity, or relationship was changed."},
    {"value": "name_number_scripture", "description": "A name, number, term, or scripture reference is wrong."},
    {"value": "fluency", "description": "Faithful but unnatural or hard to follow."},
    {"value": "other", "description": "Some other problem not listed here."},
]

# Language-specific material for seeded errors. Kept small and explicit.
LOCALE_SEEDS = {
    "ko": {"scripture": " (요한복음 3장 16절)", "names": [("예수", "모세"), ("하나님", "천사"), ("바울", "베드로")], "negate": [("습니다.", "지 않습니다."), ("입니다.", "이 아닙니다.")]},
    "es": {"scripture": " (Juan 3:16)", "names": [("Jesús", "Moisés"), ("Dios", "el ángel"), ("Pablo", "Pedro")], "negate": [(" es ", " no es "), (" está ", " no está "), (" tiene ", " no tiene "), (" puede ", " no puede ")]},
    "zh-Hans": {"scripture": "（约翰福音3章16节）", "names": [("耶稣", "摩西"), ("神", "天使"), ("保罗", "彼得")], "negate": [("是", "不是"), ("会", "不会"), ("能", "不能"), ("有", "没有")]},
}
SENTENCE_SPLIT = re.compile(r"(?<=[.!?。！？])\s*")
DIGITS = re.compile(r"\d+")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def english_by_unit(manifest: dict[str, Any]) -> dict[str, str]:
    units = manifest.get("sourceUnits")
    if not isinstance(units, list) or not units:
        raise ValueError("anchor manifest has no sourceUnits")
    return {unit["sourceUnitId"]: unit["english"] for unit in units}


def candidate_groups(candidate: dict[str, Any], english: dict[str, str]) -> list[dict[str, Any]]:
    groups = []
    for group in candidate.get("groups", []):
        unit_ids = group.get("sourceUnitIds") or []
        missing = [unit for unit in unit_ids if unit not in english]
        if missing:
            raise ValueError(f"candidate group {group.get('translationGroupId')} references unknown units {missing[:3]}")
        target = group.get("targetText") or " ".join(group.get("targetUtterances") or [])
        if not unit_ids or not target.strip():
            continue
        groups.append({
            "groupId": group["translationGroupId"],
            "english": " ".join(english[unit] for unit in unit_ids),
            "target": target.strip(),
            "utterances": list(group.get("targetUtterances") or []),
        })
    return groups


# Each mutator returns the mutated text, or None when the group cannot carry that error.
def drop_sentence(item: dict[str, Any], seeds: dict[str, Any], rng: random.Random) -> str | None:
    parts = [part for part in SENTENCE_SPLIT.split(item["target"]) if part.strip()]
    if len(parts) < 2:
        return None
    drop = rng.randrange(len(parts))
    joiner = "" if item["locale"] == "zh-Hans" else " "
    return joiner.join(part for index, part in enumerate(parts) if index != drop)


def truncate(item: dict[str, Any], seeds: dict[str, Any], rng: random.Random) -> str | None:
    text = item["target"]
    if len(text) < 24:
        return None
    return text[: int(len(text) * rng.uniform(0.35, 0.6))]


def add_scripture(item: dict[str, Any], seeds: dict[str, Any], rng: random.Random) -> str | None:
    if re.search(r"\d+\s*[:장章]", item["english"] + item["target"]):
        return None
    parts = [part for part in SENTENCE_SPLIT.split(item["target"]) if part.strip()]
    index = rng.randrange(len(parts))
    head = parts[index]
    stripped = head.rstrip(".!?。！？")
    parts[index] = stripped + seeds["scripture"] + head[len(stripped):]
    return ("" if item["locale"] == "zh-Hans" else " ").join(parts)


def swap_name(item: dict[str, Any], seeds: dict[str, Any], rng: random.Random) -> str | None:
    options = [(old, new) for old, new in seeds["names"] if old in item["target"]]
    if not options:
        return None
    old, new = rng.choice(options)
    return item["target"].replace(old, new, 1)


def change_number(item: dict[str, Any], seeds: dict[str, Any], rng: random.Random) -> str | None:
    match = DIGITS.search(item["target"])
    if not match:
        return None
    value = int(match.group())
    replacement = str(value + rng.choice([1, 2, 3, 7]))
    return item["target"][: match.start()] + replacement + item["target"][match.end():]


def negate(item: dict[str, Any], seeds: dict[str, Any], rng: random.Random) -> str | None:
    options = [(old, new) for old, new in seeds["negate"] if old in item["target"] and new not in item["target"]]
    if not options:
        return None
    old, new = rng.choice(options)
    return item["target"].replace(old, new, 1)


def wrong_group(item: dict[str, Any], seeds: dict[str, Any], rng: random.Random, pool: list[dict[str, Any]]) -> str | None:
    others = [other for other in pool if other["locale"] == item["locale"] and other["groupId"] != item["groupId"]]
    return rng.choice(others)["target"] if others else None


MUTATORS: dict[str, Callable[..., str | None]] = {
    "drop_sentence": drop_sentence,
    "truncate": truncate,
    "add_scripture": add_scripture,
    "swap_name": swap_name,
    "change_number": change_number,
    "negate": negate,
}


def build_dataset(groups_by_locale: dict[str, list[dict[str, Any]]], reference: dict[str, str],
                  seed: int, max_items: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    clean = []
    for locale, groups in sorted(groups_by_locale.items()):
        for group in groups:
            clean.append({**group, "locale": locale, "reference": reference.get(group["groupId"])})
    items = []
    for base in clean:
        items.append({**base, "kind": "clean", "expected": "none"})
        seeds = LOCALE_SEEDS.get(base["locale"])
        if not seeds:
            continue
        # One seeded error per clean group keeps clean and corrupted items balanced.
        names = list(MUTATORS) + ["wrong_group"]
        rng.shuffle(names)
        for name in names:
            mutated = wrong_group(base, seeds, rng, clean) if name == "wrong_group" else MUTATORS[name](base, seeds, rng)
            if mutated and mutated.strip() and mutated != base["target"]:
                items.append({**base, "target": mutated, "kind": name, "expected": "error"})
                break
    rng.shuffle(items)
    items = items[:max_items]
    for item in items:
        item["itemId"] = sha256_text(json.dumps([QUESTION_SET_VERSION, item["locale"], item["english"], item["target"], item["reference"]], ensure_ascii=False))[:20]
    return items


def decision_request(item: dict[str, Any], terminology: str | None) -> dict[str, Any]:
    lines = [f"English source:\n{item['english']}", f"Target language: {item['locale']}", f"Translation:\n{item['target']}"]
    if item.get("reference"):
        lines.append(f"Approved reference translation (zh-Hans), for meaning comparison only:\n{item['reference']}")
    if terminology:
        lines.append(f"Terminology:\n{terminology}")
    questions: list[dict[str, Any]] = [
        {"type": "predicate", "name": name, "instructions": text} for name, text in RISK_PREDICATES.items()
    ]
    if item.get("reference"):
        questions.append({"type": "predicate", "name": REFERENCE_PREDICATE[0], "instructions": REFERENCE_PREDICATE[1]})
    questions.append({"type": "score", "name": "fluency", "instructions": "Rate how natural the translation sounds to a native listener of the target language.", "levels": FLUENCY_LEVELS})
    questions.append({"type": "choice", "name": "issue_type", "instructions": "Pick the most serious problem of the translation relative to the English source.", "choices": ISSUE_CHOICES})
    return {"model": MODEL, "input": "\n\n".join(lines), "questions": questions}


def post_decision(body: dict[str, Any], *, timeout: float = 60.0, retries: int = 3) -> dict[str, Any]:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set; run through scripts/run_with_openai_environment.py")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if os.environ.get("OPENAI_PROJECT_ID"):
        headers["OpenAI-Project"] = os.environ["OPENAI_PROJECT_ID"]
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    for attempt in range(retries + 1):
        request = urllib.request.Request(ENDPOINT, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
                payload["_requestId"] = response.headers.get("x-request-id")
                return payload
        except urllib.error.HTTPError as exc:
            # Never echo request headers; the body of an error response carries no secret.
            detail = exc.read().decode("utf-8", "replace")[:500]
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(2 ** (attempt + 1))
                continue
            raise RuntimeError(f"decisions_http_{exc.code}: {detail}") from None
        except urllib.error.URLError as exc:
            if attempt < retries:
                time.sleep(2 ** (attempt + 1))
                continue
            raise RuntimeError(f"decisions_network_error: {exc.reason}") from None
    raise AssertionError("unreachable")


def summarize_answers(payload: dict[str, Any]) -> dict[str, Any]:
    answers = {answer["name"]: answer for answer in payload.get("answers", [])}
    risk_names = list(RISK_PREDICATES) + [REFERENCE_PREDICATE[0]]
    risks = {name: answers[name]["probability"] for name in risk_names
             if name in answers and isinstance(answers[name].get("probability"), (int, float))
             and not isinstance(answers[name]["probability"], bool)
             and 0 <= answers[name]["probability"] <= 1}
    return {
        "risks": risks,
        "maxRisk": max(risks.values()) if risks else None,
        "refusals": [name for name, answer in answers.items() if answer.get("type") == "refusal"],
        "missingProbabilities": [name for name in risk_names if name in answers and name not in risks],
        "fluency": answers.get("fluency", {}).get("score"),
        "issueType": answers.get("issue_type", {}).get("choice"),
        "issueConfidence": answers.get("issue_type", {}).get("confidence"),
        "usage": payload.get("usage"),
        "requestId": payload.get("_requestId"),
    }


def estimate_tokens(body: dict[str, Any]) -> int:
    # Rough planning estimate only: ~4 bytes per token for mixed CJK/Latin UTF-8 text.
    return max(1, len(json.dumps(body, ensure_ascii=False).encode("utf-8")) // 4)


def rates(results: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
    evaluated = [row for row in results if not row.get("unavailablePredicates")
                 and not row.get("missingProbabilities") and row["maxRisk"] is not None]
    flagged = lambda row: row["maxRisk"] is not None and row["maxRisk"] >= threshold
    clean = [row for row in evaluated if row["kind"] == "clean"]
    errors = [row for row in evaluated if row["kind"] != "clean"]
    by_kind: dict[str, list[int]] = {}
    for row in errors:
        hit = by_kind.setdefault(row["kind"], [0, 0])
        hit[0] += flagged(row)
        hit[1] += 1
    return {
        "threshold": threshold,
        "evaluatedItems": len(evaluated),
        "unscoredItems": len(results) - len(evaluated),
        "detectionRate": round(sum(flagged(row) for row in errors) / len(errors), 4) if errors else None,
        "cleanFlagRate": round(sum(flagged(row) for row in clean) / len(clean), 4) if clean else None,
        "byKind": {kind: {"detected": hit, "total": total} for kind, (hit, total) in sorted(by_kind.items())},
    }


def report(results: list[dict[str, Any]], meta: dict[str, Any]) -> dict[str, Any]:
    usage_tokens = [row["usage"].get("input_tokens") for row in results if isinstance(row.get("usage"), dict) and row["usage"].get("input_tokens")]
    tokens = sum(usage_tokens) if len(usage_tokens) == len(results) else sum(row["estimatedTokens"] for row in results)
    latencies = sorted(row["latencySeconds"] for row in results if row.get("latencySeconds") is not None)
    by_locale: dict[str, dict[str, Any]] = {}
    for locale in sorted({row["locale"] for row in results}):
        subset = [row for row in results if row["locale"] == locale]
        by_locale[locale] = {"items": len(subset), "thresholds": [rates(subset, t) for t in THRESHOLDS]}
    return {
        **meta,
        "items": len(results),
        "cleanItems": sum(row["kind"] == "clean" for row in results),
        "seededItems": sum(row["kind"] != "clean" for row in results),
        "refusedItems": sum(bool(row.get("refusals")) for row in results),
        "unscoredItems": rates(results, 0.5)["unscoredItems"],
        "fullyScoredItems": rates(results, 0.5)["evaluatedItems"],
        "thresholds": [rates(results, t) for t in THRESHOLDS],
        "byLocale": by_locale,
        "issueTypeOnSeeded": _issue_table(results),
        "inputTokens": tokens,
        "inputTokensMeasured": len(usage_tokens) == len(results),
        "estimatedCostUsd": round(tokens / 1_000_000 * PRICE_PER_MILLION_INPUT, 4),
        "latencySeconds": {"p50": latencies[len(latencies) // 2], "p95": latencies[int(len(latencies) * 0.95) - 1 if len(latencies) > 1 else 0]} if latencies else None,
    }


def flagged_clean(items: list[dict[str, Any]], results: list[dict[str, Any]], threshold: float) -> list[dict[str, Any]]:
    """Clean items at or above threshold, highest risk first, for a person or Sol to judge."""
    by_id = {item["itemId"]: item for item in items}
    rows = [row for row in results if row["kind"] == "clean" and row["maxRisk"] is not None and row["maxRisk"] >= threshold]
    return [{
        "locale": row["locale"], "groupId": row["groupId"], "maxRisk": row["maxRisk"], "risks": row["risks"],
        "issueType": row.get("issueType"), "english": by_id[row["itemId"]]["english"],
        "target": by_id[row["itemId"]]["target"], "reference": by_id[row["itemId"]].get("reference"),
    } for row in sorted(rows, key=lambda row: -row["maxRisk"])]


def _issue_table(results: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    table: dict[str, dict[str, int]] = {}
    for row in results:
        cell = table.setdefault(row["kind"], {})
        cell[str(row.get("issueType"))] = cell.get(str(row.get("issueType")), 0) + 1
    return table


def run(items: list[dict[str, Any]], out: Path, terminology: str | None, workers: int,
        transport: Callable[[dict[str, Any]], dict[str, Any]] = post_decision) -> list[dict[str, Any]]:
    cache_dir = out / "answers"
    cache_dir.mkdir(parents=True, exist_ok=True)

    def one(item: dict[str, Any]) -> dict[str, Any]:
        body = decision_request(item, terminology)
        cached = cache_dir / f"{item['itemId']}.json"
        if cached.exists():
            row = json.loads(cached.read_text(encoding="utf-8"))
            row.setdefault("unavailablePredicates", [question["name"] for question in body["questions"]
                           if question["type"] == "predicate" and question["name"] not in row["risks"]])
            return row
        started = time.monotonic()
        payload = transport(body)
        summary = summarize_answers(payload)
        row = {
            "itemId": item["itemId"], "groupId": item["groupId"], "locale": item["locale"], "kind": item["kind"],
            "requestSha256": sha256_text(json.dumps(body, ensure_ascii=False, sort_keys=True)),
            "estimatedTokens": estimate_tokens(body), "latencySeconds": round(time.monotonic() - started, 3),
            **summary,
            "unavailablePredicates": [question["name"] for question in body["questions"]
                                      if question["type"] == "predicate" and question["name"] not in summary["risks"]],
        }
        temp = cached.with_suffix(".tmp")
        temp.write_text(json.dumps(row, ensure_ascii=False, indent=1), encoding="utf-8")
        temp.replace(cached)
        return row

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        return list(pool.map(one, items))


def markdown(summary: dict[str, Any]) -> str:
    lines = [
        f"# Decisions API L2 calibration ({summary['generatedAt']})", "",
        f"Model `{summary['model']}`, question set `{summary['questionSetVersion']}`. "
        f"{summary['items']} items: {summary['cleanItems']} clean, {summary['seededItems']} seeded errors. "
        f"Input tokens {summary['inputTokens']} ({'measured' if summary['inputTokensMeasured'] else 'estimated'}), "
        f"about ${summary['estimatedCostUsd']}.", "",
        "Clean items are approved translations treated as correct; seeded items carry one known error each.", "",
        f"{summary.get('refusedItems', 0)} items contain refused answers; "
        f"{summary.get('unscoredItems', 0)} items lack complete risk scores and are excluded from threshold rates. "
        f"{summary.get('fullyScoredItems', summary['items'])} items are fully risk-scored.", "",
        "| Threshold on max risk | Seeded errors caught | Clean items flagged |", "|---|---|---|",
    ]
    for row in summary["thresholds"]:
        lines.append(f"| {row['threshold']} | {row['detectionRate']} | {row['cleanFlagRate']} |")
    lines += ["", "## Detection by error kind at 0.5", "", "| Kind | Caught / total |", "|---|---|"]
    for row in summary["thresholds"]:
        if row["threshold"] == 0.5:
            for kind, cell in row["byKind"].items():
                lines.append(f"| {kind} | {cell['detected']} / {cell['total']} |")
    lines += ["", "## Clean items flagged, by locale", "", "| Locale | 0.3 | 0.5 | 0.7 | 0.85 |", "|---|---|---|---|---|"]
    for locale, cell in summary.get("byLocale", {}).items():
        values = {row["threshold"]: row["cleanFlagRate"] for row in cell["thresholds"]}
        lines.append(f"| {locale} | " + " | ".join(str(values.get(t)) for t in (0.3, 0.5, 0.7, 0.85)) + " |")
    if summary.get("latencySeconds"):
        lines += ["", f"Latency p50 {summary['latencySeconds']['p50']}s, p95 {summary['latencySeconds']['p95']}s."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--anchor-manifest", type=Path, required=True, help="sermon-sentence-anchor-manifest-v2 JSON")
    parser.add_argument("--candidate", type=Path, action="append", required=True, help="Approved Target-Language Candidate v2 JSON; repeat per locale")
    parser.add_argument("--terminology", type=Path, help="Optional plain-text terminology excerpt passed to every request")
    parser.add_argument("--out", type=Path, required=True, help="Ignored output directory, for example artifacts/decisions-calibration/<run>")
    parser.add_argument("--seed", type=int, default=20261007)
    parser.add_argument("--max-items", type=int, default=MAX_ITEMS_DEFAULT)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true", help="Build the dataset and token estimate; make no API call")
    args = parser.parse_args(argv)

    english = english_by_unit(load_json(args.anchor_manifest))
    candidates = {}
    for path in args.candidate:
        candidate = load_json(path)
        locale = candidate.get("targetLocale")
        if locale in candidates:
            parser.error(f"two candidates for locale {locale}")
        candidates[locale] = candidate
    groups_by_locale = {locale: candidate_groups(candidate, english) for locale, candidate in candidates.items()}
    # The zh-Hans reference is matched to other locales by source units, since group ids carry the locale.
    zh_by_units = {tuple(group.get("sourceUnitIds") or []): group.get("targetText") or " ".join(group.get("targetUtterances") or [])
                   for group in candidates.get("zh-Hans", {}).get("groups", [])}
    reference = {}
    for locale, candidate in candidates.items():
        for group in candidate.get("groups", []):
            text = zh_by_units.get(tuple(group.get("sourceUnitIds") or []))
            if locale != "zh-Hans" and text:
                reference[group["translationGroupId"]] = text
    terminology = args.terminology.read_text(encoding="utf-8") if args.terminology else None
    items = build_dataset(groups_by_locale, reference, args.seed, args.max_items)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "dataset.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    meta = {
        "schemaVersion": "decisions-l2-calibration-v1", "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": MODEL, "questionSetVersion": QUESTION_SET_VERSION, "seed": args.seed,
        "inputs": {"anchorManifestSha256": hashlib.sha256(args.anchor_manifest.read_bytes()).hexdigest(),
                   "candidates": {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in args.candidate}},
        "scope": "non_production_calibration_no_approval",
    }
    if args.dry_run:
        tokens = sum(estimate_tokens(decision_request(item, terminology)) for item in items)
        kinds: dict[str, int] = {}
        for item in items:
            kinds[item["kind"]] = kinds.get(item["kind"], 0) + 1
        plan = {**meta, "items": len(items), "kinds": kinds, "estimatedInputTokens": tokens,
                "estimatedCostUsd": round(tokens / 1_000_000 * PRICE_PER_MILLION_INPUT, 4)}
        (args.out / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(plan, ensure_ascii=False, indent=1))
        return 0
    results = run(items, args.out, terminology, args.workers)
    (args.out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    summary = report(results, meta)
    (args.out / "report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    (args.out / "report.md").write_text(markdown(summary), encoding="utf-8")
    (args.out / "flagged-clean.json").write_text(json.dumps(flagged_clean(items, results, FLAGGED_CLEAN_THRESHOLD), ensure_ascii=False, indent=1), encoding="utf-8")
    print(markdown(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
