#!/usr/bin/env python3
"""Write every budget approval and authorization a run needs from the weekly run profile.

One command replaces the hand-written approval/authorization JSON of each stage:

- one machine QC root per locale, shared by text QC, calibration and audio QC (its ledger is the
  judge's response cache), optionally naming earlier roots whose paid responses it may reuse;
- one Layer 2 approval and authorization for an existing canonical execution config, bound to that
  config's hash, the current code identity and the profile's request limits;
- ``plan.json``: every cap and whether the worst case fits the approved total.

The caller states who approved the spend and the evidence (``--approved-by``, ``--evidence``); the
tool never invents an approval. It refuses to overwrite files and writes nothing when the worst
case of even one stage does not fit. It does not dispatch anything or open a budget root.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PROFILE = ROOT / "config/weekly-run-profile.json"
PROFILE_SCHEMA = "sermon-weekly-run-profile-v1"
PLAN_SCHEMA = "sermon-run-budget-plan-v1"
LOCALES = ("zh-Hans", "ko", "es")


def micro(usd: float) -> int:
    return int(round(usd * 1_000_000))


def write_new(path: Path, value: dict) -> Path:
    if path.exists():
        raise SystemExit(f"{path} exists; plans never overwrite an approval")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n")
    return path


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def qc_files(out: Path, locale: str, profile: dict, scale: str, *, approved_by: str, evidence: str,
             reviewed_at: str, reuse: list[str]) -> dict:
    qc = profile["qc"]
    directory = out / f"qc-{locale}"
    root = str((directory / ".api-budget").resolve())
    bounds = {"requests": qc["requests"][scale], "wallTimeMs": qc["wallTimeMs"],
              "costMicrousd": micro(qc["capUsdPerLocale"][scale])}
    limits = qc["requestLimits"]
    binding = {"budgetRoot": root, "globalBounds": bounds, "requestLimits": limits,
               **({"reuseBudgetRoots": reuse} if reuse else {})}
    approval = write_new(directory / "api-budget-approval.json", {
        "schemaVersion": "sermon-machine-qc-api-budget-approval-v1", "binding": binding,
        "humanApproval": True, "decision": "approved", "reviewedBy": approved_by, "reviewedAt": reviewed_at,
        "operatorEvidence": evidence})
    write_new(directory / "api-budget-authorization.json", {
        "schemaVersion": "sermon-machine-qc-api-budget-authorization-v1", "budgetRoot": root,
        "authority": {"approvalSha256": file_sha256(approval),
                      "bounds": {"globalBounds": bounds, "requestLimits": limits}, "requestLimits": limits},
        "approvalReceipt": approval.name, **({"reuseBudgetRoots": reuse} if reuse else {})})
    return {"stage": f"qc.{locale}", "authorization": str(directory / "api-budget-authorization.json"),
            "budgetRoot": root, "capUsd": qc["capUsdPerLocale"][scale], "reuseBudgetRoots": reuse}


def layer2_files(out: Path, execution: Path, locales: list[str], profile: dict, scale: str, *,
                 approved_by: str, evidence: str, reviewed_at: str) -> dict:
    from scripts import canonical_layer2_budget as budget_tools
    from scripts import canonical_layer2_controller as controller
    layer2 = profile["layer2"]
    config = controller.load_configuration(execution)
    configured = sorted(config.lanes)
    if configured != sorted(locales):
        raise SystemExit(f"Layer 2 execution covers {configured}, not the planned locales {sorted(locales)}")
    code = controller.code_identity()
    cap = layer2["capUsdPerLocale"][scale] * len(locales)
    per_locale = layer2["boundsPerLocale"]
    bounds = {key: value * len(locales) for key, value in per_locale.items()}
    bounds["costMicrousd"] = micro(cap)
    limits, rules = layer2["requestLimits"], layer2["limits"]
    root = config.job_root.parent / f".{config.job_root.name}.layer2-budget"
    directory = out / "layer2"
    approval = write_new(directory / "budget-approval.json", {
        "schemaVersion": "sermon-canonical-layer2-budget-approval-v1",
        "binding": {"productionRunId": config.run_id, "configurationSha256": config.sha256, "codeIdentitySha256": code,
                    "budgetRoot": str(root), "requestLimits": limits, "globalBounds": bounds, "unitBounds": bounds,
                    "limits": rules},
        "humanApproval": True, "decision": "approved", "reviewedBy": approved_by, "reviewedAt": reviewed_at,
        "operatorEvidence": evidence})
    authorization = write_new(directory / "budget-authorization.json", {
        "schemaVersion": "sermon-canonical-layer2-budget-authorization-v1", "productionRunId": config.run_id,
        "configurationSha256": config.sha256, "codeIdentitySha256": code, "requestLimits": limits,
        "authority": {"approvalSha256": file_sha256(approval), "globalBounds": bounds, "unitBounds": bounds,
                      "limits": rules},
        "approvalReceipt": approval.name})
    budget_tools.load_authorization(config, authorization, code)
    return {"stage": "layer2", "authorization": str(authorization), "budgetRoot": str(root), "capUsd": cap,
            "execution": str(execution),
            "maxActiveLocales": json.loads(execution.read_text()).get("layer2AutoRepair", {}).get("maxActiveLocales")}


def schedule(stages: list[dict], *, total: float, settled: float) -> dict:
    caps = [stage["capUsd"] for stage in stages]
    worst = round(settled + sum(caps), 6)
    if worst <= total:
        return {"mode": "all_stages_may_run_together", "worstCaseUsd": worst, "fits": True}
    largest = max(caps) if caps else 0.0
    if settled + largest <= total:
        return {"mode": "one_stage_at_a_time", "worstCaseUsd": worst, "fits": True,
                "note": "Every cap together exceeds the total. Open one stage at a time and re-run this plan with "
                        "--settled-usd from the ledgers after each stage, so later caps start from actual spend."}
    return {"mode": "does_not_fit", "worstCaseUsd": worst, "fits": False,
            "note": f"Even the largest single stage cap ({largest} USD) plus settled spend exceeds the total."}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True, help="New directory for this run's budget files")
    parser.add_argument("--scale", choices=("clip", "week"), required=True)
    parser.add_argument("--locales", default=",".join(LOCALES))
    parser.add_argument("--total-usd", type=float, required=True, help="Approved total for this run or test budget")
    parser.add_argument("--settled-usd", type=float, default=0.0, help="Already settled spend against that total")
    parser.add_argument("--approved-by", required=True, help="Who approved the spend")
    parser.add_argument("--evidence", required=True, help="Where the approval was given (quote or link)")
    parser.add_argument("--layer2-execution", type=Path, help="Canonical Layer 2 execution config to bind a budget to")
    parser.add_argument("--reuse-from", type=Path, action="append", default=[],
                        help="An earlier plan directory of this run; its QC roots become reuse roots")
    parser.add_argument("--profile", type=Path, default=PROFILE)
    args = parser.parse_args(argv)
    profile = json.loads(args.profile.read_text())
    if profile.get("schemaVersion") != PROFILE_SCHEMA:
        raise SystemExit("Unsupported run profile")
    locales = [locale for locale in args.locales.split(",") if locale]
    if not locales or any(locale not in LOCALES for locale in locales) or len(set(locales)) != len(locales):
        raise SystemExit(f"Locales must be distinct values of {LOCALES}")
    if not args.approved_by.strip() or not args.evidence.strip():
        raise SystemExit("--approved-by and --evidence must name the actual approval")
    if args.out.exists() and any(args.out.iterdir()):
        raise SystemExit(f"{args.out} is not empty")
    # Check the schedule before writing anything.
    caps = ([{"capUsd": profile["layer2"]["capUsdPerLocale"][args.scale] * len(locales)}] if args.layer2_execution else []) + \
        [{"capUsd": profile["qc"]["capUsdPerLocale"][args.scale]} for _ in locales]
    planned = schedule(caps, total=args.total_usd, settled=args.settled_usd)
    if not planned["fits"]:
        print(json.dumps(planned, ensure_ascii=False))
        return 1
    reviewed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    common = dict(approved_by=args.approved_by, evidence=args.evidence, reviewed_at=reviewed_at)
    stages = []
    if args.layer2_execution:
        stages.append(layer2_files(args.out, args.layer2_execution.resolve(), locales, profile, args.scale, **common))
    for locale in locales:
        reuse = [str((prior / f"qc-{locale}" / ".api-budget").resolve()) for prior in args.reuse_from
                 if (prior / f"qc-{locale}").is_dir()]
        stages.append(qc_files(args.out, locale, profile, args.scale, reuse=reuse, **common))
    plan = {"schemaVersion": PLAN_SCHEMA, "createdAt": reviewed_at, "scale": args.scale, "locales": locales,
            "profileSha256": file_sha256(args.profile), "totalUsd": args.total_usd, "settledUsd": args.settled_usd,
            "approvedBy": args.approved_by, "evidence": args.evidence, "stages": stages,
            "schedule": schedule(stages, total=args.total_usd, settled=args.settled_usd)}
    write_new(args.out / "plan.json", plan)
    print(json.dumps({"plan": str(args.out / "plan.json"), "schedule": plan["schedule"],
                      "stages": [(stage["stage"], stage["capUsd"]) for stage in stages]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
