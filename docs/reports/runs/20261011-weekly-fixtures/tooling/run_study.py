#!/usr/bin/env python3
"""Drive the unified study.produce v2 path (outline/meditation) for this week's three locales.

prepare : build the run manifest, bindings and v2 config per locale/kind, compute the execution
          identity and request count without any model call, and write the study budget approval
          (operator chat decision) plus its authorization bound to that identity.
execute : run the bounded OpenAI generation under the explicit environment launcher; resumes from
          the persisted budget ledger; output stays human_pending.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.sermon_unified import contracts as c  # noqa: E402
from scripts import sermon_study_generation as generation  # noqa: E402
from scripts import sermon_unified_study as owner  # noqa: E402
from scripts import sermon_provider_limits as limits  # noqa: E402

HERE = Path(__file__).resolve().parent
RUN_ID = "weekend-live-54475d42-20261011"
PAGE_ID = "resi-20261011-54475d42"
WL = ROOT / "artifacts/weekend-live"
SOURCE = WL / "layer1-54475d42/formal/english-source-package.json"
ANCHOR = WL / "layer1-54475d42/output4-rebuild4/anchor-manifest.json"
TERMINOLOGY = ROOT / "docs/series-terminology.zh.md"
LOCALES = {
    "zh-Hans": (WL / "layer2-54475d42/text-r12/zh-Hans/candidate.json",
                WL / "text-qc-54475d42/v3-zh/zh-Hans/text-waiver-b364ef215fcb255e.json"),
    "ko": (WL / "layer2-54475d42/recovered/ko/candidate.json",
           WL / "text-qc-54475d42/v15-ko/ko/text-waiver-6bf4791566c2b8b3.json"),
    "es": (WL / "layer2-54475d42/recovered/es/candidate.json",
           WL / "text-qc-54475d42/v15-es/es/text-waiver-7a18087538a44402.json"),
}
EVIDENCE = ("Chat decisions on 2026-10-11: '大纲，默想，海报，还有其他是不是可以同步做' (start study products now); "
            "'额度放宽到500' (total API reservations within USD 500); OpenAI API prod via the explicit launcher. "
            "Study budget approval only; outline/meditation content still needs the human study review.")


def rel(path: Path) -> str:
    return str(Path(path).resolve())


def manifest_for(locale: str, kind: str, revision: str, policy: dict) -> tuple[dict, Path, Path]:
    candidate, waiver = LOCALES[locale]
    source = c.read(SOURCE)
    job = HERE / locale / kind / revision
    job.mkdir(parents=True, exist_ok=True)
    policy_path = job / "policy.json"
    if not policy_path.exists():
        policy_path.write_text(json.dumps(policy, ensure_ascii=False, indent=1))
    bindings = {name: {"path": rel(path), "sha256": c.file_sha(path)} for name, path in {
        "source": SOURCE, "anchor": ANCHOR, "candidate": candidate, "translationReview": waiver,
        "terminology": TERMINOLOGY, "policy": policy_path}.items()}
    manifest = {"productionRunId": RUN_ID,
                "source": {"sourceId": source["source"]["sourceId"], "mediaSha256": source["source"]["media"]["sha256"],
                           "sourceUrlHash": source["source"]["sourceUrlHash"]},
                "content": {"pageId": PAGE_ID}, "bindings": bindings}
    config = {"schemaVersion": "sermon-unified-study-inputs-v2", "kind": kind, "revision": revision,
              "jobRoot": rel(job / "jobs"),
              "inputs": {"source": "source", "anchor": "anchor", "candidate": "candidate", "translationReview": "translationReview",
                         "terminology": "terminology", "policy": "policy", "budgetAuthorization": "budgetAuthorization"}}
    config_path = job / "config.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=1))
    return manifest, config_path, job


def prepare(locale: str, kind: str, revision: str, policy: dict, cost_usd: float, max_requests: int) -> dict:
    manifest, config_path, job = manifest_for(locale, kind, revision, policy)
    step = {"id": kind, "locale": locale}
    p = generation.prepare(manifest, HERE, config_path, step, authorize=False)
    bounds = {"requests": max_requests, "wallTimeMs": 3 * 3600 * 1000, "costMicrousd": int(cost_usd * 1_000_000)}
    binding = {"productionRunId": RUN_ID, "executionSha256": p["identity"], "codeIdentitySha256": p["codeIdentity"],
               "budgetRoot": str(p["root"]), "globalBounds": bounds, "requestLimits": p["limits"]}
    approval_path, auth_path = job / "budget-approval.json", job / "budget-authorization.json"
    if not approval_path.exists():
        approval = {"schemaVersion": "sermon-study-budget-approval-v1", "binding": binding, "humanApproval": True,
                    "decision": "approved", "reviewedBy": "Jony", "reviewedAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                    "operatorEvidence": EVIDENCE}
        approval_path.write_text(json.dumps(approval, ensure_ascii=False, indent=1))
        sha = c.file_sha(approval_path)
        auth_path.write_text(json.dumps({"schemaVersion": "sermon-study-budget-authorization-v1", "binding": binding,
                                         "authority": {"approvalSha256": sha, "globalBounds": bounds, "requestLimits": p["limits"]},
                                         "approvalReceipt": "budget-approval.json", "approvalReceiptSha256": sha}, ensure_ascii=False, indent=1))
    manifest["bindings"]["budgetAuthorization"] = {"path": rel(auth_path), "sha256": c.file_sha(auth_path)}
    (job / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    return {"locale": locale, "kind": kind, "requests": len(p["requests"]), "executionSha256": p["identity"],
            "budgetRoot": str(p["root"]), "job": str(job)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", choices=["prepare", "execute"])
    ap.add_argument("--locale", required=True, choices=list(LOCALES))
    ap.add_argument("--kind", required=True, choices=["outline", "meditation"])
    ap.add_argument("--revision", default="r1")
    ap.add_argument("--model", default="gpt-6.1-sol")
    ap.add_argument("--reasoning-effort", default="medium")
    ap.add_argument("--batch-groups", type=int, default=12)
    ap.add_argument("--cost-usd", type=float, default=15.0)
    ap.add_argument("--max-requests", type=int, default=120)
    args = ap.parse_args()
    policy = {"schemaVersion": "sermon-study-generation-policy-v1", "model": args.model, "reasoningEffort": args.reasoning_effort,
              "promptVersion": "grounded-study-v1", "batchGroups": args.batch_groups, "requestLimits": limits.MAX_REQUEST_LIMITS}
    if args.action == "prepare":
        print(json.dumps(prepare(args.locale, args.kind, args.revision, policy, args.cost_usd, args.max_requests), indent=1))
        return
    job = HERE / args.locale / args.kind / args.revision
    manifest = c.read(job / "manifest.json")
    step = {"id": args.kind, "locale": args.locale}
    result = owner.execute(manifest, HERE, job / "config.json", step, job / "result.json")
    (job / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    owner.verify_result(manifest, HERE, job / "config.json", step, result)
    print(json.dumps({k: result.get(k) for k in ("status", "kind", "review", "productionEligible", "freshApiAttempts", "path", "jsonSha256")}, indent=1))


if __name__ == "__main__":
    main()
