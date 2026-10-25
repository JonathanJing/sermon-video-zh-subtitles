#!/usr/bin/env python3
"""Turn prepared term decisions into source-scoped v4 policy drafts and term receipts.

The Saturday 4:00 pm preparation (docs/design/saturday-first-service-preparation.zh.md, P9)
records the operator's term decisions before the formal source exists. Once the formal
English Source Package and anchor manifest are frozen, this module binds those decisions to
them, one locale at a time:

* every decided term whose English appears in a source unit becomes a ``properNames`` entry
  and a ``termApprovalReceipt`` row naming that unit;
* every name the policy scanner (``policy.source_scoped_proper_names``) requires must be
  covered by a decided term or a predicted ordinary-phrase exclusion; names left over are
  listed with their units and that locale gets no draft until someone decides them;
* used series names take the decision's target, or the base policy's when it already has one.

It writes drafts only. Freezing stays the existing ``text.policy freeze`` step, where the
operator picks the Layer 2 backend and plugin binding. The receipt states the human approval
the operator passes in (``--reviewed-by``, ``--user-statement``); this module never infers one.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from . import backend as _text
from . import policy as _policy

DECISIONS_SCHEMA = "sat400-prep-term-decisions-v1"
REPORT_SCHEMA = "sermon-term-scope-report-v1"
RECEIPT_SCHEMA = "sermon-source-scoped-term-approval-v1"
LOCALES = ("zh-Hans", "ko", "es")


def _repo_root() -> Path:
    return _text.current().core.repo_root


def default_base_policy(locale: str) -> Path:
    return _repo_root() / "config" / "target-language-policies" / f"{locale}.json"


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_decisions(decisions: dict[str, Any]) -> None:
    """Refuse a decisions file this module cannot bind exactly."""
    if not isinstance(decisions, dict) or decisions.get("schemaVersion") != DECISIONS_SCHEMA:
        raise ValueError(f"Term decisions must use {DECISIONS_SCHEMA}")
    for kind in ("properNames", "seriesNames"):
        rows = decisions.get(kind)
        if not isinstance(rows, list):
            raise ValueError(f"Term decisions need a {kind} list")
        sources = [row.get("source") for row in rows if isinstance(row, dict)]
        if len(sources) != len(rows) or not all(_nonempty(s) for s in sources):
            raise ValueError(f"Every {kind} decision needs an English source")
        if len({s.casefold() for s in sources}) != len(sources):
            raise ValueError(f"Duplicate {kind} decision source")
        for row in rows:
            if not isinstance(row.get("target"), dict) or not all(
                    _nonempty(value) for value in row["target"].values()):
                raise ValueError(f"{kind} decision {row['source']!r} needs non-empty targets")
    exclusions = decisions.get("predictedOrdinaryPhraseExclusions", [])
    if not isinstance(exclusions, list) or not all(_nonempty(item) for item in exclusions):
        raise ValueError("predictedOrdinaryPhraseExclusions must be a list of phrases")


def _units(anchor: dict[str, Any]) -> list[dict[str, Any]]:
    rows = anchor.get("sourceUnits")
    if not isinstance(rows, list) or not rows:
        raise ValueError("Anchor manifest has no sourceUnits")
    for row in rows:
        if not _nonempty(row.get("sourceUnitId")) or not isinstance(row.get("english"), str):
            raise ValueError("Every source unit needs a sourceUnitId and English text")
    return rows


def _first_unit(rows: list[dict[str, Any]], phrase: str) -> str | None:
    needle = phrase.casefold()
    return next((row["sourceUnitId"] for row in rows if needle in row["english"].casefold()), None)


def _units_with(rows: list[dict[str, Any]], phrase: str) -> list[str]:
    return [row["sourceUnitId"] for row in rows if phrase in row["english"]]


def _series_entries(base: dict[str, Any], locale: str, catalog: list[dict[str, Any]],
                    used: set[str], decided: dict[str, dict[str, str]]) -> tuple[list[dict], list[str]]:
    """The table's full series list; used series need a reviewed target."""
    prior = {row["source"]: row for row in base.get("terminology", {}).get("seriesNames", [])}
    entries, missing = [], []
    for row in catalog:
        english, chinese = row["english"], row["chinese"]
        entry = copy.deepcopy(prior.get(english) or {"source": english, "target": None, "reviewStatus": "pending"})
        if locale == "zh-Hans":
            entry.update(target=chinese, reviewStatus="project_established")
        if english in used:
            target = decided.get(english, {}).get(locale)
            if target is not None:
                if locale == "zh-Hans" and target != chinese:
                    raise ValueError(f"zh-Hans series decision for {english!r} differs from the series table")
                if locale != "zh-Hans" or entry["reviewStatus"] == "pending":
                    entry.update(target=target, reviewStatus="human_reviewed")
            if entry["reviewStatus"] == "pending" or not _nonempty(entry.get("target")):
                missing.append(english)
        entries.append(entry)
    return entries, missing


def scope_locale(decisions: dict[str, Any], source: dict[str, Any], anchor: dict[str, Any],
                 locale: str, base: dict[str, Any], *, series_table: Path, reviewed_by: str,
                 reviewed_at: str, user_statement: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Return (draft or None, report) for one locale."""
    validate_decisions(decisions)
    if base.get("targetLocale") != locale:
        raise ValueError(f"Base policy is for {base.get('targetLocale')!r}, not {locale!r}")
    rows = _units(anchor)
    english = " ".join(row["english"] for row in rows)
    catalog = _text.current().terminology.parse_table(series_table.read_text(encoding="utf-8"))
    used_series = {row["english"] for row in catalog if row["english"].casefold() in english.casefold()}
    scanner = _policy.source_scoped_proper_names(rows, used_series)

    names, receipt_rows, absent, no_target = [], [], [], []
    for row in decisions["properNames"]:
        target = row["target"].get(locale)
        unit = _first_unit(rows, row["source"])
        if unit is None:
            absent.append(row["source"])
        elif target is None:
            no_target.append(row["source"])
        else:
            names.append({"source": row["source"], "target": target, "reviewStatus": "human_reviewed"})
            receipt_rows.append({"source": row["source"], "target": target, "sourceUnitId": unit})
    named = {row["source"] for row in names}
    predicted = set(decisions.get("predictedOrdinaryPhraseExclusions", []))
    exclusions = sorted(predicted & scanner)
    uncovered = sorted(scanner - named - set(exclusions))
    decided_series = {row["source"]: row["target"] for row in decisions["seriesNames"]}
    series, series_missing = _series_entries(base, locale, catalog, used_series, decided_series)

    report = {
        "schemaVersion": REPORT_SCHEMA, "targetLocale": locale,
        "englishSourcePackageJsonSha256": _policy.canonical_sha256(source),
        "anchorManifestSha256": _policy.canonical_sha256(anchor),
        "usedSeriesNames": sorted(used_series), "scannerNames": sorted(scanner),
        "approvedTerms": len(receipt_rows), "ordinaryPhraseExclusions": exclusions,
        "uncoveredScannerNames": [{"name": name, "sourceUnitIds": _units_with(rows, name)} for name in uncovered],
        "seriesNamesWithoutTarget": series_missing,
        "decisionsAbsentFromSource": absent, "decisionsWithoutLocaleTarget": no_target,
        "predictedExclusionsNotProduced": sorted(predicted - scanner),
    }
    if uncovered or series_missing or not receipt_rows:
        report["status"] = "needs_decision"
        return None, report

    draft = copy.deepcopy(base)
    draft.pop("componentSha256", None)
    draft["schemaVersion"] = _policy.POLICY_V4
    draft["terminology"] = {**draft.get("terminology", {}),
                            "seriesTableSha256": _policy.file_sha256(series_table),
                            "seriesNames": series, "properNames": names}
    draft["sourceScope"] = {
        "englishSourcePackageJsonSha256": report["englishSourcePackageJsonSha256"],
        "anchorManifestSha256": report["anchorManifestSha256"],
        "usedSeriesNames": sorted(used_series),
        "usedProperNames": sorted(scanner - set(exclusions)),
        "ordinaryPhraseExclusions": exclusions,
        "termApprovalEvidence": [],
        "termApprovalReceipt": {
            "schemaVersion": RECEIPT_SCHEMA, "targetLocale": locale,
            "englishSourcePackageJsonSha256": report["englishSourcePackageJsonSha256"],
            "anchorManifestSha256": report["anchorManifestSha256"],
            "decision": "approved", "humanApproval": True,
            "reviewedBy": reviewed_by, "reviewedAt": reviewed_at, "userStatement": user_statement,
            "approvedTerms": receipt_rows, "excludedScannerPhrases": exclusions,
        },
    }
    report["status"] = "draft_ready"
    report["freezeCheck"] = trial_freeze(draft, source, anchor, series_table)
    report["pluginPin"] = plugin_pin_check(draft)
    return draft, report


def _plugin_ids() -> dict[str, Path]:
    """PLUGIN_ID literal of every language plugin in the checkout."""
    import ast
    found = {}
    for path in sorted(_text.current().plugins.root().glob("*.py")):
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "PLUGIN_ID"
                    and isinstance(node.value, ast.Constant)):
                found[node.value.value] = path
    return found


def plugin_pin_check(draft: dict[str, Any]) -> dict[str, Any]:
    """Compare the draft's pinned plugin with the checkout; the freeze does not, dispatch does."""
    from . import candidate as producer  # the candidate imports policy, not this module
    review = draft.get("languageReview", {})
    plugin_id, pinned = review.get("pluginId"), review.get("pluginImplementationSha256")
    if plugin_id is None:
        return {"status": "unbound", "remedy": "freeze ko/es with --language-review machine_qc; "
                                                "zh-Hans needs a pluginId and its hash"}
    path = _plugin_ids().get(plugin_id)
    if path is None:
        return {"status": "missing", "pluginId": plugin_id,
                "remedy": "the pinned plugin is not in this checkout; choose a current plugin"}
    current = producer.plugin_implementation_sha256(path)
    return {"status": "current" if current == pinned else "stale", "pluginId": plugin_id,
            "pinned": pinned, "current": current, "plugin": path.name,
            **({} if current == pinned else {"remedy": "re-pin to the current hash, or freeze ko/es with "
                                                        "--language-review machine_qc"})}


def trial_freeze(draft: dict[str, Any], source: dict[str, Any], anchor: dict[str, Any],
                 series_table: Path) -> dict[str, Any]:
    """Freeze a copy in memory and check it against the source; nothing is written."""
    try:
        frozen = _policy.freeze_policy(copy.deepcopy(draft), series_table=series_table)
        _policy.validate_source_scope(frozen, source, anchor)
        verdict = _policy.validate_policy(frozen, series_table=series_table)
    except ValueError as error:
        return {"status": "refused", "error": str(error)}
    return {"status": "pass", "productionPolicyReady": verdict.get("productionPolicyReady"),
            "unresolved": verdict.get("unresolved", [])}


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_new(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--source-package", type=Path, required=True)
    parser.add_argument("--anchor-manifest", type=Path, required=True)
    parser.add_argument("--locale", action="append", choices=LOCALES,
                        help="Repeat per locale; default zh-Hans, ko and es")
    parser.add_argument("--base", action="append", default=[], metavar="LOCALE=PATH",
                        help="Base policy draft per locale (default config/target-language-policies/<locale>.json)")
    parser.add_argument("--series-terminology", type=Path)
    parser.add_argument("--reviewed-by", required=True)
    parser.add_argument("--reviewed-at", required=True)
    parser.add_argument("--user-statement", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    bases = {}
    for item in args.base:
        locale, sep, path = item.partition("=")
        if not sep or locale not in LOCALES:
            parser.error(f"--base needs LOCALE=PATH with LOCALE in {LOCALES}")
        bases[locale] = Path(path)
    for value in (args.reviewed_by, args.reviewed_at, args.user_statement):
        if not value.strip():
            parser.error("--reviewed-by, --reviewed-at and --user-statement must not be empty")
    series_table = args.series_terminology or _text.current().terminology.table_path()
    decisions, source, anchor = _read(args.decisions), _read(args.source_package), _read(args.anchor_manifest)
    summary = {"schemaVersion": REPORT_SCHEMA, "decisionsSha256": _policy.file_sha256(args.decisions),
               "locales": {}}
    for locale in args.locale or LOCALES:
        base = _read(bases.get(locale, default_base_policy(locale)))
        draft, report = scope_locale(decisions, source, anchor, locale, base, series_table=series_table,
                                     reviewed_by=args.reviewed_by, reviewed_at=args.reviewed_at,
                                     user_statement=args.user_statement)
        report["decisionsSha256"] = summary["decisionsSha256"]
        _write_new(args.out_dir / f"{locale}-term-scope-report.json", report)
        if draft is not None:
            _write_new(args.out_dir / f"{locale}-policy-draft.json", draft)
        summary["locales"][locale] = {"status": report["status"],
                                      "freezeCheck": report.get("freezeCheck", {}).get("status"),
                                      "pluginPin": report.get("pluginPin", {}).get("status"),
                                      "uncovered": [row["name"] for row in report["uncoveredScannerNames"]],
                                      "seriesWithoutTarget": report["seriesNamesWithoutTarget"]}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    # 0: every draft freezes and pins a current plugin; 2: a decision is missing or the freeze
    # refuses; 3: drafts freeze but a plugin pin must be fixed before dispatch.
    rows = summary["locales"].values()
    if not all(row["status"] == "draft_ready" and row["freezeCheck"] == "pass" for row in rows):
        return 2
    return 0 if all(row["pluginPin"] == "current" for row in rows) else 3


if __name__ == "__main__":
    raise SystemExit(main())
