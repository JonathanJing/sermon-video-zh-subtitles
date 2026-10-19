"""Read-only per-group plan: which stage of which group is stale, and why (DEV-GRP-001).

``plan`` takes the current inputs (the frozen Layer 1 package, each locale's current
candidate, policy and plugin, and the current stage implementation identities) and
the records a run already has (derived from its products, or from a record store),
and reports for every ``(locale, group, stage)``:

* ``fresh``: the record's inputs and implementation match the current ones;
* ``stale``: something it reads changed, or an upstream stage it reads will produce
  new bytes, or the operator named the group; the reasons say which;
* ``failed`` / ``stopped`` / ``unknown``: current, but the recorded verdict is not a pass;
* ``missing``: no record; ``not_applicable``: the stage does not run for this group.

It dispatches nothing, writes nothing but its own report, and makes no model call.
For T and R it compares the inputs the request is built from; the exact request hash
includes the credential route and is matched again at dispatch by the payload cache.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from typing import Any

from . import group_legacy as legacy
from . import group_records as records

PLAN_SCHEMA = "sermon-group-plan-v1"
MANIFEST_SCHEMA = "sermon-group-plan-inputs-v1"
STATUS_ORDER = ("fresh", "failed", "stopped", "unknown", "stale", "missing")
VERDICT_STATUS = {"pass": "fresh", "fail": "failed", "stopped": "stopped", "unknown": "unknown"}
# Statuses whose stage will produce new bytes, or whose bytes are in doubt.
UNSETTLED = {"stale", "missing", "conflict"}
# A byte-producing stage in these states has no valid output for its consumers either.
UNUSABLE_OUTPUT = UNSETTLED | {"failed", "stopped", "unknown"}
# Of those, the ones a redo may dispatch again; an unknown paid outcome is reconciled first.
REDO = UNSETTLED | {"failed", "stopped"}
PAID_STAGES = ("T", "R", "Q", "C")
LIMITS = (
    "T and R freshness compares the inputs the request is built from (English, English context, "
    "policy terminology/scripture/formatting, model settings, runner identity); the exact request hash "
    "is matched again at dispatch.",
    "Per-group model rules, revision instructions and the text QC semantic identity are recorded but not "
    "recomputed here.",
    "Synthesis identity beyond the renderer sound identity is recorded but not recomputed; batch "
    "membership is outside the key (open decision 1).",
    "Records derived from a whole-sermon run carry what its products recorded; a missing value is "
    "reported, never filled from current code.",
    "No budget figure: per-group budgets are DEV-GRP-003.",
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def group_plan_rows(anchor: dict) -> list[dict]:
    """The Layer 1 group boundaries, as the Layer 2 runner derives them."""
    requests = anchor.get("translationRequests")
    if isinstance(requests, list) and requests:
        return [{"translationGroupId": row["translationGroupId"], "sourceUnitIds": list(row["sourceUnitIds"])}
                for row in requests]
    return [{"translationGroupId": f"translation-{unit['sourceUnitId']}", "sourceUnitIds": [unit["sourceUnitId"]]}
            for unit in anchor["sourceUnits"]]


def current_identities(manifest: dict, base: Path) -> dict:
    """Current stage implementation identities, read from this checkout's code.

    Needs the configured host (tools/ops/group_tasks.py imports it); tests pass these
    values directly instead.
    """
    from ..text import candidate, models
    from ..text import policy as policy_tools
    from ..audio import renderer, screening
    from ..review import audio_qc, waiver
    locales = {}
    for locale, entry in manifest["locales"].items():
        policy = legacy.load_json(_path(entry["policy"], base))
        identity = policy_tools.validate_policy(policy)
        locales[locale] = {
            "pluginImplementationSha256": (candidate.plugin_implementation_sha256(_path(entry["plugin"], base))
                                           if entry.get("plugin") else None),
            # The ASR settings the next screening would run with; the screening hashes them the same way.
            "asrSettingsSha256": (records.json_sha256(legacy.load_json(_path(entry["asrSettings"], base)))
                                  if entry.get("asrSettings") else None),
            "languageReviewPolicySha256": identity["languageReviewPolicySha256"],
        }
    return {"runnerImplementationSha256": models.RUNNER_PRODUCTION_IDENTITY_SHA256,
            "machineQcImplementationSha256": waiver.implementation_sha256(),
            "rendererSoundIdentitySha256": renderer.RENDERER_SOUND_IDENTITY_SHA256,
            "asrImplementationSha256": screening.implementation_sha256(),
            "audioQcThresholdsSha256": records.json_sha256(audio_qc.THRESHOLDS),
            "locales": locales}


def _path(value: Any, base: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else base / path


def derive_records(manifest: dict, base: Path, layer1: dict, anchor: dict) -> dict:
    """Records per locale and group, derived from the run products the manifest names."""
    out = {}
    for locale, entry in manifest["locales"].items():
        candidate = legacy.load_json(_path(entry["candidate"], base))
        groups = candidate["groups"]
        by_group: dict[str, dict] = {group["translationGroupId"]: {} for group in groups}
        candidate_layer1 = records.layer1_identity(candidate["englishSourcePackageJsonSha256"],
                                                   candidate["anchorManifestSha256"])
        if entry.get("layer2Rounds"):
            for group_id, stages in legacy.layer2_records(
                    locale, groups, [_path(p, base) for p in entry["layer2Rounds"]]).items():
                by_group[group_id].update(stages)
        if entry.get("languageReview"):
            for group_id, record in legacy.plugin_records(
                    layer1, locale, anchor, legacy.load_json(_path(entry["languageReview"], base))).items():
                by_group.setdefault(group_id, {})["P"] = record
        if entry.get("textQcReceipt"):
            for group_id, record in legacy.text_qc_records(
                    locale, legacy.load_json(_path(entry["textQcReceipt"], base))).items():
                by_group.setdefault(group_id, {})["Q"] = record
        if entry.get("speechJob"):
            screening = legacy.load_json(_path(entry["asrScreening"], base)) if entry.get("asrScreening") else None
            for group_id, stages in legacy.speech_records(locale, _path(entry["speechJob"], base), screening).items():
                by_group.setdefault(group_id, {}).update(stages)
        if entry.get("audioQcReceipt"):
            for group_id, record in legacy.audio_qc_records(
                    locale, legacy.load_json(_path(entry["audioQcReceipt"], base)), by_group).items():
                by_group.setdefault(group_id, {})["U"] = record
        out[locale] = {"candidate": candidate, "candidateLayer1": candidate_layer1, "records": by_group}
    return out


def _current_inputs(stage: str, group: dict, context: dict, anchor: dict, policy: dict,
                    locale_identity: dict, records_for_group: dict) -> dict:
    """Current values for the inputs this plan can recompute; the rest are not compared.

    ``records_for_group`` holds the record already selected for each upstream stage, so
    a downstream input is compared with the upstream bytes the plan actually reuses.
    """
    rows = legacy.english_rows(anchor, group["sourceUnitIds"])
    target = records.text_sha256(legacy.joined_text(group["targetUtterances"]))
    if stage in {"T", "R"}:
        role = "translator" if stage == "T" else "reviewer"
        values = {"englishUnitsSha256": legacy.english_units_sha256(rows),
                  "englishContextSha256": records.json_sha256(context),
                  "modelFacingPolicySha256": legacy.model_facing_policy_sha256(policy),
                  "modelSettingsSha256": legacy.model_settings_sha256(policy[role]["model"],
                                                                      policy[role].get("reasoningEffort"))}
        if stage == "R" and "T" in records_for_group:
            values["draftTextSha256"] = records_for_group["T"]["outputs"]["draftTextSha256"]
        return values
    if stage == "P":
        return {"languageReviewPolicySha256": locale_identity.get("languageReviewPolicySha256"),
                "englishUnitsSha256": legacy.english_units_sha256(rows), "targetTextSha256": target}
    if stage in {"Q", "C"}:
        # C's request hash is not recomputed here; its English, text and QC closure are.
        return {"englishSha256": legacy.qc_english_sha256(rows), "targetTextSha256": target}
    if stage == "S":
        # A shortened group is synthesized from C's spoken text, not the full translation.
        condensed = (records_for_group.get("C") or {}).get("outputs", {}).get("spokenTextSha256")
        return {"textSha256": condensed or target}
    if stage == "A":
        spoken = (records_for_group.get("S") or {}).get("inputs", {}).get("textSha256")
        values = {"targetTextSha256": spoken or target,
                  "asrSettingsSha256": locale_identity.get("asrSettingsSha256")}
        if "S" in records_for_group:
            values["audioSha256"] = records_for_group["S"]["outputs"]["audioSha256"]
        return values
    if stage == "U":
        values = {}
        if "S" in records_for_group:
            values["audioSha256"] = records_for_group["S"]["outputs"]["audioSha256"]
        return values
    return {}


def _current_implementation(stage: str, identities: dict, locale_identity: dict) -> str | None:
    return {"T": identities.get("runnerImplementationSha256"), "R": identities.get("runnerImplementationSha256"),
            "P": locale_identity.get("pluginImplementationSha256"),
            "Q": identities.get("machineQcImplementationSha256"), "C": identities.get("machineQcImplementationSha256"),
            "S": identities.get("rendererSoundIdentitySha256"), "A": identities.get("asrImplementationSha256"),
            "U": identities.get("machineQcImplementationSha256")}[stage]


def evaluate(record: dict, layer1: dict, current: dict, implementation: str | None) -> dict:
    """Compare one record with the current inputs; no upstream or directive rules here."""
    reasons, compared, not_compared = [], [], []
    if record["layer1"] != layer1:
        reasons.append("layer1_identity_changed")
    not_recorded = set(record["provenance"].get("notRecorded") or [])
    if "stageImplementation" in not_recorded or implementation is None:
        not_compared.append("stageImplementation")
    elif record["stageImplementationSha256"] != implementation:
        reasons.append("stage_implementation_changed")
    else:
        compared.append("stageImplementation")
    for name in records.STAGE_INPUTS[record["stage"]]:
        if name in current and current[name] is not None and name not in not_recorded:
            compared.append(name)
            if record["inputs"].get(name) != current[name]:
                reasons.append(f"input_changed:{name}")
        else:
            not_compared.append(name)
    status = "stale" if reasons else VERDICT_STATUS[record["verdict"]["status"]]
    return {"status": status, "reasons": reasons, "codes": record["verdict"]["codes"],
            "inputKey": record["inputKey"], "compared": compared, "notCompared": not_compared}


def _conflicting_keys(candidates: list[dict]) -> list[str]:
    """Input keys that more than one different record claims."""
    by_key: dict[str, set[bytes]] = {}
    for record in candidates:
        by_key.setdefault(record["inputKey"], set()).add(records.canonical_bytes(record))
    return sorted(key for key, versions in by_key.items() if len(versions) > 1)


def plan(manifest: dict, base: Path, identities: dict, *, directives: dict | None = None,
         store: records.RecordStore | None = None) -> dict:
    """Build the plan report. ``directives`` maps locale -> group IDs the operator names."""
    _require(manifest.get("schemaVersion") == MANIFEST_SCHEMA, "invalid_plan_manifest")
    source = legacy.load_json(_path(manifest["source"], base))
    anchor = legacy.load_json(_path(manifest["anchor"], base))
    layer1 = records.layer1_identity(records.json_sha256(source), records.json_sha256(anchor))
    _require(source.get("anchors", {}).get("artifact", {}).get("jsonSha256") == layer1["anchorManifestSha256"],
             "source_package_and_anchor_differ")
    plan_rows = group_plan_rows(anchor)
    contexts = legacy.group_contexts(anchor, plan_rows)
    derived = derive_records(manifest, base, layer1, anchor)
    directives = directives or {}
    report = {"schemaVersion": PLAN_SCHEMA, "mode": "read_only", "dispatched": False, "modelCalls": 0,
              "layer1": layer1, "locales": {}, "limits": list(LIMITS),
              "releaseEligible": False, "humanApproval": False}
    for locale, entry in manifest["locales"].items():
        policy = legacy.load_json(_path(entry["policy"], base))
        locale_identity = identities.get("locales", {}).get(locale, {})
        listed = set(directives.get(locale, ()))
        candidate = derived[locale]["candidate"]
        groups = candidate["groups"]
        known = {group["translationGroupId"] for group in groups}
        _require(listed <= known, f"directive_names_unknown_group:{sorted(listed - known)[:3]}")
        _require([group["translationGroupId"] for group in groups] == [row["translationGroupId"] for row in plan_rows],
                 f"candidate_groups_differ_from_layer1:{locale}")
        rows = []
        for group in groups:
            group_id = group["translationGroupId"]
            derived_records = derived[locale]["records"].get(group_id, {})
            selected: dict[str, dict] = {}
            stages = {}
            for stage in records.STAGES:
                candidates = ([derived_records[stage]] if stage in derived_records else []) + (
                    store.records(locale, group_id, stage) if store is not None else [])
                if stage == "C":
                    # C runs only for groups the text QC sends to shortening; full text bypasses it.
                    mode = (selected.get("Q") or {}).get("provenance", {}).get("mode")
                    if mode == "full":  # every other mode shortens and needs a C result
                        stages[stage] = {"status": "not_applicable", "reasons": [f"text_qc_mode:{mode}"]}
                        continue
                if not candidates:
                    stages[stage] = {"status": "missing", "reasons": ["no_record"]}
                    continue
                wrong_units = sorted({record["inputKey"] for record in candidates
                                      if record["sourceUnitIds"] != group["sourceUnitIds"]})
                if wrong_units:
                    stages[stage] = {"status": "conflict", "reasons": ["record_source_units_mismatch"],
                                     "inputKeys": wrong_units}
                    continue
                conflicting = _conflicting_keys(candidates)
                if conflicting:
                    # One input key admits one result; two different results stay visible.
                    stages[stage] = {"status": "conflict", "reasons": ["conflicting_records_same_input_key"],
                                     "inputKeys": conflicting}
                    continue
                current = _current_inputs(stage, group, contexts[group_id], anchor, policy, locale_identity, selected)
                if stage == "U":
                    current["thresholdsSha256"] = identities.get("audioQcThresholdsSha256")
                implementation = _current_implementation(stage, identities, locale_identity)
                results = []
                for record in candidates:
                    result = evaluate(record, layer1, current, implementation)
                    if stage == "A" and current.get("asrSettingsSha256") is None:
                        # Without the desired settings, an ASR pass cannot be shown to still apply.
                        result["status"] = "stale"
                        result["reasons"].append("asr_settings_not_supplied")
                    if stage == "R" and record["outputs"].get("targetTextSha256") != records.text_sha256(
                            legacy.joined_text(group["targetUtterances"])):
                        # The candidate holds R's reviewed text unless something replaced it later.
                        result["status"] = "stale"
                        result["reasons"].append("output_differs_from_candidate")
                    results.append((result, record))
                compatible = sorted({result["inputKey"] for result, _ in results if result["status"] != "stale"})
                if len(compatible) > 1:
                    # Keys that differ only in inputs not compared here cannot be told apart.
                    stages[stage] = {"status": "conflict", "reasons": ["multiple_compatible_input_keys"],
                                     "inputKeys": compatible}
                    continue
                best, record = min(results, key=lambda item: STATUS_ORDER.index(item[0]["status"]))
                stages[stage], selected[stage] = best, record
            if derived[locale]["candidateLayer1"] != layer1:
                # A candidate made from another Layer 1 is not current, whatever its records say.
                for stage, value in stages.items():
                    if value["status"] not in {"not_applicable", "missing"}:
                        stages[stage] = dict(value, status="stale",
                                             reasons=list(value.get("reasons", [])) + ["candidate_layer1_changed"])
            if group_id in listed:
                stages["T"] = dict(stages["T"], status="stale",
                                   reasons=list(stages["T"].get("reasons", [])) + ["operator_directive"])
            for stage in records.STAGES:
                if stages[stage]["status"] in {"not_applicable"}:
                    continue
                upstream = [up for up in records.UPSTREAM[stage] if up in records.PRODUCES
                            and stages[up]["status"] in UNUSABLE_OUTPUT]
                if upstream and stages[stage]["status"] not in {"missing", "conflict"}:
                    stages[stage] = dict(stages[stage], status="stale",
                                         reasons=list(stages[stage].get("reasons", []))
                                         + [f"upstream_will_change:{up}" for up in upstream])
            rows.append({"translationGroupId": group_id, "sourceUnitIds": group["sourceUnitIds"], "stages": stages})
        summary = {stage: dict(Counter(row["stages"][stage]["status"] for row in rows)) for stage in records.STAGES}
        redo = {stage: [row["translationGroupId"] for row in rows
                        if row["stages"][stage]["status"] in UNSETTLED
                        or (stage in records.PRODUCES and row["stages"][stage]["status"] in REDO)]
                for stage in records.STAGES}
        report["locales"][locale] = {
            "groupCount": len(rows), "directiveGroupIds": sorted(listed),
            "candidateLayer1Current": derived[locale]["candidateLayer1"] == layer1, "summary": summary,
            "redoCounts": {stage: len(ids) for stage, ids in redo.items()},
            "paidStageRedoCount": sum(len(redo[stage]) for stage in PAID_STAGES),
            "reasonCounts": {stage: dict(Counter(_reason_kind(reason) for row in rows
                                                 for reason in row["stages"][stage].get("reasons", [])))
                             for stage in records.STAGES},
            "groups": rows}
    return report


def _reason_kind(reason: str) -> str:
    """Count changed inputs by name; other reasons by their kind."""
    return reason if reason.startswith("input_changed:") else reason.split(":", 1)[0]


def text_summary(report: dict) -> str:
    lines = [f"Group plan (read only, {report['modelCalls']} model calls, nothing dispatched)"]
    for locale, value in report["locales"].items():
        lines.append(f"\n{locale}: {value['groupCount']} groups; operator-listed {len(value['directiveGroupIds'])}"
                     + ("" if value["candidateLayer1Current"] else "; CANDIDATE IS BOUND TO ANOTHER LAYER 1"))
        for stage in records.STAGES:
            counts = ", ".join(f"{status} {count}" for status, count in sorted(value["summary"][stage].items()))
            reasons = ", ".join(f"{reason} {count}" for reason, count in sorted(value["reasonCounts"][stage].items()))
            lines.append(f"  {stage} {records.STAGE_NAMES[stage]:<20} {counts}" + (f"  [{reasons}]" if reasons else ""))
        lines.append(f"  stale or missing paid-stage group steps: {value['paidStageRedoCount']}")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("plan", help="list stale steps per group; dispatch nothing")
    command.add_argument("--manifest", type=Path, required=True,
                         help=f"{MANIFEST_SCHEMA} JSON naming the run's source, anchor and per-locale products")
    command.add_argument("--locale", action="append", help="limit to these locales")
    command.add_argument("--group-id", nargs="+", default=[],
                         help="groups the operator names for redo (needs exactly one --locale)")
    command.add_argument("--records", type=Path, help="a per-group record store to consult as well")
    command.add_argument("--output", type=Path, help="write the full JSON plan here")
    args = parser.parse_args(argv)
    manifest = legacy.load_json(args.manifest)
    if args.locale:
        unknown = set(args.locale) - set(manifest["locales"])
        _require(not unknown, f"unknown_locale:{sorted(unknown)}")
        manifest = dict(manifest, locales={key: value for key, value in manifest["locales"].items()
                                           if key in args.locale})
    _require(not args.group_id or (args.locale and len(args.locale) == 1), "group_id_needs_one_locale")
    directives = {args.locale[0]: args.group_id} if args.group_id else {}
    base = args.manifest.resolve().parent
    report = plan(manifest, base, current_identities(manifest, base), directives=directives,
                  store=records.RecordStore(args.records) if args.records else None)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(text_summary(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
