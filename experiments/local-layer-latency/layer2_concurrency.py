#!/usr/bin/env python3
"""Freeze workers=1/2/3 Layer 2 experiments; never dispatch model requests.

Run ``python -m scripts.experiments.layer2_concurrency freeze --help``.
Only batching and its component hash change between arms. The worker=1 copy
may deliberately retain the baseline policy hash. Each arm has a separate
output directory; completed/unknown requests are never shared across policies.
Use ``inspect`` to check frozen identities and read existing accounting.
Generated commands require separate execution authorization and API budget.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from scripts import produce_target_language_candidate as producer
from scripts import run_target_language_models as runner
from scripts import target_language_policy as policies
from scripts import weekly_pipeline_report as weekly

SCHEMA = "sermon-layer2-concurrency-experiment-v1"


def freeze(source_path: Path, anchor_path: Path, policy_path: Path,
           plugin_path: Path, out: Path, plan_path: Path | None = None) -> dict:
    """Write a new isolated snapshot, without changing any approved input."""
    source, anchor, base = (producer._load(path) for path in
                            (source_path, anchor_path, policy_path))
    request = producer.prepare_request(source, anchor, base)
    runner.require_plugin_identity(plugin_path, base["languageReview"]["pluginImplementationSha256"])
    runner.require(all(base[role]["model"] == model for role, model in runner.MODEL_ROLES.items()),
                   "Concurrency experiment preserves production Astra/Sol roles")
    runner.require(base["batching"]["batchSize"] == 1, "Concurrency experiment requires batchSize=1")
    runner.require(not out.exists(), "Experiment output must be a new directory")
    plan = runner.group_plan(request, anchor,
        json.loads(plan_path.read_text(encoding="utf-8")) if plan_path is not None else None)
    arms = []
    for workers in (1, 2, 3):
        policy = copy.deepcopy(base)
        policy["batching"]["workers"] = workers
        policy["componentSha256"]["batching"] = policies.canonical_sha256(policy["batching"])
        arm_request = producer.prepare_request(source, anchor, policy)
        arms.append((workers, policy, arm_request))
    manifest = {
        "schemaVersion": SCHEMA, "experimentOnly": True, "dispatchEnabled": False,
        "targetLocale": request["targetLocale"],
        "englishSourcePackageJsonSha256": request["englishSourcePackageJsonSha256"],
        "anchorManifestSha256": request["anchorManifestSha256"],
        "baselinePolicySha256": policies.canonical_sha256(base),
        "groupPlanSha256": policies.canonical_sha256(plan), "translationGroups": len(plan),
        "plugin": {"path": str(plugin_path.resolve()),
                   "implementationSha256": producer.plugin_implementation_sha256(plugin_path)},
        "humanApproval": False, "releaseEligible": False,
        "notes": ["Only batching workers and its component hash vary; baseline may have the same policy hash.",
                  "Same frozen groups, source, roles, prompts and review gates; every arm is isolated.",
                  "Commands are preparation only; paid execution requires a separately authorized budget.",
                  "Unknown requests require inspection; never delete markers to resume."],
        "arms": [],
    }
    # Validate every arm before writing anything. Exclusive writes reject racing
    # generators; an interrupted snapshot can be inspected but not overwritten.
    out.mkdir(parents=True, exist_ok=False)
    for name, value in (("source.json", source), ("anchor.json", anchor),
                        ("baseline-policy.json", base), ("group-plan.json", plan)):
        runner.save_new(out / name, value, private=True)
    for workers, policy, arm_request in arms:
        arm = f"workers-{workers}"
        policy_file = f"{arm}/policy.json"
        runner.save_new(out / policy_file, policy, private=True)
        argv = ["python", "-m", "scripts.run_target_language_models",
                "--english-source-package", str((out / "source.json").resolve()),
                "--anchor", str((out / "anchor.json").resolve()),
                "--policy", str((out / policy_file).resolve()),
                "--group-plan", str((out / "group-plan.json").resolve()),
                "--plugin", str(plugin_path.resolve()),
                "--out-dir", str((out / arm / "models").resolve())]
        manifest["arms"].append({"workers": workers, "policy": policy_file,
            "translationPolicySha256": arm_request["translationPolicySha256"],
            "outputDirectory": f"{arm}/models", "plannedFreshModelCalls": 2 * len(plan),
            "executionArgv": argv})
    runner.save_new(out / "experiment.json", manifest, private=True)
    return manifest


def inspect(root: Path) -> dict:
    """Read/validate snapshots and existing results, without dispatch or approval."""
    manifest = producer._load(root / "experiment.json")
    runner.require(manifest.get("schemaVersion") == SCHEMA
                   and manifest.get("dispatchEnabled") is False
                   and [arm["workers"] for arm in manifest["arms"]] == [1, 2, 3],
                   "Invalid concurrency experiment")
    source, anchor, base = (producer._load(root / name) for name in
        ("source.json", "anchor.json", "baseline-policy.json"))
    plan = json.loads((root / "group-plan.json").read_text(encoding="utf-8"))
    runner.require(policies.canonical_sha256(base) == manifest["baselinePolicySha256"],
                   "Baseline policy changed")
    request = producer.prepare_request(source, anchor, base)
    runner.require(request["englishSourcePackageJsonSha256"] == manifest["englishSourcePackageJsonSha256"]
                   and request["anchorManifestSha256"] == manifest["anchorManifestSha256"]
                   and policies.canonical_sha256(runner.group_plan(request, anchor, plan))
                       == manifest["groupPlanSha256"], "Experiment source or plan changed")
    runner.require(manifest["plugin"]["implementationSha256"]
                   == base["languageReview"]["pluginImplementationSha256"], "Plugin binding changed")
    runner.require_plugin_identity(Path(manifest["plugin"]["path"]),
                                   base["languageReview"]["pluginImplementationSha256"])
    result = {"schemaVersion": SCHEMA, "dispatchEnabled": False, "arms": []}
    for arm in manifest["arms"]:
        expected = copy.deepcopy(base)
        expected["batching"]["workers"] = arm["workers"]
        expected["componentSha256"]["batching"] = policies.canonical_sha256(expected["batching"])
        policy = producer._load(root / arm["policy"])
        runner.require(policy == expected and policies.canonical_sha256(policy)
                       == arm["translationPolicySha256"], "Arm differs beyond frozen worker budget")
        arm_request = producer.prepare_request(source, anchor, policy)
        output = root / arm["outputDirectory"]
        unknown = [marker.name for marker in sorted(output.glob("group-*.started.json"))
                   if not (output / marker.name.replace(".started.json", ".json")).is_file()
                   and not (output / marker.name.replace(".started.json", ".raw.json")).is_file()]
        row = {"workers": arm["workers"], "unknownRequests": unknown,
               "status": "requires_reconciliation" if unknown else
                         "partial_evidence" if output.exists() and any(output.iterdir()) else "not_run",
               "humanApproval": False, "releaseEligible": False}
        if (output / "evidence.json").is_file():
            evidence = producer._load(output / "evidence.json")
            runner.require(all(evidence.get(key) == value for key, value in arm_request.items()
                               if key not in {"generation", "groups"})
                           and [(g["translationGroupId"], g["sourceUnitIds"]) for g in evidence["groups"]]
                           == [(g["translationGroupId"], g["sourceUnitIds"]) for g in plan],
                           "Completed arm evidence identity or aggregation order changed")
            row["status"] = "requires_reconciliation" if unknown else "model_evidence_returned"
        if (output / "accounting").exists():
            row["accounting"] = weekly.project(output / "accounting")
        result["arms"].append(row)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("freeze", help="Prepare new frozen snapshots; never call APIs")
    for option in ("english-source-package", "anchor", "policy", "plugin", "out-dir"):
        create.add_argument("--" + option, type=Path, required=True)
    create.add_argument("--group-plan", type=Path,
                        help="Optional existing frozen plan; preserve reviewed group boundaries")
    check = commands.add_parser("inspect", help="Read identities, unknown markers and accounting")
    check.add_argument("--experiment-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "freeze":
        value = freeze(args.english_source_package, args.anchor, args.policy, args.plugin, args.out_dir,
                       args.group_plan)
        print(json.dumps({"dispatchEnabled": False, "translationGroups": value["translationGroups"],
                          "workers": [arm["workers"] for arm in value["arms"]]}))
    else:
        print(json.dumps(inspect(args.experiment_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
