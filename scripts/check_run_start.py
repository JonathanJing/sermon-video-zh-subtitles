#!/usr/bin/env python3
"""Check a run's start conditions in one pass, before any paid or GPU work.

Every check reports pass, fail or skip with its evidence; the command exits 1 if any check fails.
It only reads: it never begins a Spark session, opens a budget root, dispatches a model or deploys.

Checks (each runs only when its inputs are given):
- code: the checkout is clean and at ``--expected-commit``; the machine-QC implementation hash,
  compared with ``--expected-implementation`` (a change voids every waiver of the run);
- openai: the dev/prod launcher resolves its key file (``run_with_openai_environment.py --check``);
- budget: a ``plan_run_budgets.py`` plan whose files are unchanged, whose authorizations bind their
  approvals, whose roots are new or belong to the same approval, and whose worst case fits;
- spark: the Spark host answers; with ``--spark-stages`` an exclusive session named in the
  environment is ready (API-only stages need none); ``--spark-code-dir`` holds the same
  implementation files as this checkout;
- outputs: each ``--fresh-dir`` does not exist yet or is empty;
- page: ``--page-id`` is not yet in the live Dev v3 or v4 catalog.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEV_ORIGIN = "https://ai-for-god-sermon-audio-dev.web.app"
SPARK_HOST = "achillesjing@192.168.1.152"
SPARK_STAGE = "/home/achillesjing/dgx-spark-benchmark/results"


def result(name, status, **evidence):
    return {"check": name, "status": status, **evidence}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], check=True, capture_output=True, text=True).stdout.strip()


def check_code(expected_commit, expected_implementation):
    from scripts import machine_quality_waiver as waiver
    head = git("rev-parse", "HEAD")
    dirty = [line for line in git("status", "--porcelain", "--untracked-files=no").splitlines() if line]
    implementation = waiver.implementation_sha256()
    problems = []
    if dirty:
        problems.append(f"{len(dirty)} tracked file(s) modified")
    if expected_commit and not head.startswith(expected_commit):
        problems.append(f"HEAD {head[:12]} is not {expected_commit}")
    if expected_implementation and implementation != expected_implementation:
        problems.append("QC implementation hash differs: existing waivers would not apply")
    return result("code", "fail" if problems else "pass", head=head, qcImplementationSha256=implementation,
                  problems=problems)


def check_openai(environment, env_file):
    command = [sys.executable, str(ROOT / "scripts/run_with_openai_environment.py"), "--environment", environment,
               *(["--env-file", str(env_file)] if env_file else []), "--check"]
    done = subprocess.run(command, capture_output=True, text=True, cwd=ROOT)
    # Report the launcher's verdict, never its output: it may name key aliases.
    return result("openai", "pass" if done.returncode == 0 else "fail", environment=environment,
                  exitCode=done.returncode)


def check_budget(plan_dir: Path):
    plan = json.loads((plan_dir / "plan.json").read_text())
    problems = []
    for stage in plan["stages"]:
        authorization = Path(stage["authorization"])
        value = json.loads(authorization.read_text())
        receipt = authorization.parent / value["approvalReceipt"]
        if not receipt.is_file():
            problems.append(f"{stage['stage']}: approval missing")
            continue
        if sha256(receipt) != value["authority"]["approvalSha256"]:
            problems.append(f"{stage['stage']}: approval changed since its authorization")
        root = Path(stage["budgetRoot"])
        ledger = root / "source-budget.json"
        if ledger.exists():
            authority = json.loads(ledger.read_text()).get("authority", {})
            if authority.get("approvalSha256") != value["authority"]["approvalSha256"]:
                problems.append(f"{stage['stage']}: budget root already belongs to another approval")
        for reuse in stage.get("reuseBudgetRoots") or []:
            if not (Path(reuse) / "source-budget.json").is_file():
                problems.append(f"{stage['stage']}: reuse root {reuse} has no ledger")
    if not plan["schedule"]["fits"]:
        problems.append("planned worst case exceeds the approved total")
    return result("budget", "fail" if problems else "pass", plan=str(plan_dir / "plan.json"),
                  schedule=plan["schedule"], stages=[(s["stage"], s["capUsd"]) for s in plan["stages"]], problems=problems)


def ssh(command: str, host: str) -> subprocess.CompletedProcess:
    return subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", host, command],
                          capture_output=True, text=True, timeout=60)


def check_spark(host, spark_stages, code_dir):
    reachable = ssh("hostname", host)
    if reachable.returncode != 0:
        return result("spark", "fail", host=host, problems=["Spark host does not answer over SSH"])
    problems, evidence = [], {"host": host}
    if spark_stages:
        if not (os.environ.get("SPARK_EXCLUSIVE_SESSION_ID") and os.environ.get("SPARK_EXCLUSIVE_SESSION_OWNER")):
            problems.append("Spark stages need SPARK_EXCLUSIVE_SESSION_ID/OWNER of a begun session")
        else:
            from scripts.spark_exclusive_session import Client
            try:
                Client.from_environment().require_ready()
                evidence["session"] = "ready"
            except Exception as error:  # noqa: BLE001 - reported, not handled
                problems.append(f"session not ready: {error}")
    else:
        evidence["session"] = "not_required_api_only"
    if code_dir:
        from scripts import machine_quality_waiver as waiver
        files = [str(path) for path in waiver.IMPLEMENTATION_FILES]
        remote = ssh("cd " + code_dir + " && sha256sum " + " ".join(files), host)
        local = {path: sha256(ROOT / path) for path in files}
        observed = dict(reversed(line.split(None, 1)) for line in remote.stdout.splitlines() if line.strip())
        differing = [path for path in files if observed.get(path) != local[path]]
        evidence["codeDir"] = code_dir
        if remote.returncode != 0 or differing:
            problems.append(f"Spark code dir differs from this checkout in {len(differing)} implementation file(s)")
    return result("spark", "fail" if problems else "pass", problems=problems, **evidence)


def check_fresh(paths):
    used = [str(path) for path in paths if path.exists() and (not path.is_dir() or any(path.iterdir()))]
    return result("outputs", "fail" if used else "pass", fresh=[str(p) for p in paths],
                  problems=[f"{path} is not new or empty" for path in used])


def check_page(page_id, origin):
    seen = []
    for name in ("multilingual-v3.json", "multilingual-v4.json"):
        with urlopen(Request(origin + "/" + name, headers={"Cache-Control": "no-cache"}), timeout=60) as response:
            pages = json.loads(response.read()).get("pages", [])
        if any(page.get("id") == page_id for page in pages):
            seen.append(name)
    return result("page", "fail" if seen else "pass", pageId=page_id, origin=origin,
                  problems=[f"{page_id} already in {name}" for name in seen])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--expected-commit")
    parser.add_argument("--expected-implementation", help="QC implementation hash the run's waivers bind")
    parser.add_argument("--openai-environment", choices=("dev", "prod"))
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--budget-plan", type=Path, help="Directory written by plan_run_budgets.py")
    parser.add_argument("--spark", action="store_true", help="Check the Spark host")
    parser.add_argument("--spark-host", default=SPARK_HOST)
    parser.add_argument("--spark-stages", action="store_true", help="The run is entering GPU stages now")
    parser.add_argument("--spark-code-dir", help="Staged code directory on Spark, e.g. <stage>/repo-<commit>")
    parser.add_argument("--fresh-dir", type=Path, action="append", default=[])
    parser.add_argument("--page-id")
    parser.add_argument("--origin", default=DEV_ORIGIN)
    parser.add_argument("--out", type=Path, help="Also write the report here")
    args = parser.parse_args(argv)
    checks = [check_code(args.expected_commit, args.expected_implementation)]
    checks.append(check_openai(args.openai_environment, args.env_file) if args.openai_environment
                  else result("openai", "skip"))
    checks.append(check_budget(args.budget_plan) if args.budget_plan else result("budget", "skip"))
    checks.append(check_spark(args.spark_host, args.spark_stages, args.spark_code_dir)
                  if args.spark or args.spark_stages or args.spark_code_dir else result("spark", "skip"))
    checks.append(check_fresh(args.fresh_dir) if args.fresh_dir else result("outputs", "skip"))
    checks.append(check_page(args.page_id, args.origin) if args.page_id else result("page", "skip"))
    failed = [check["check"] for check in checks if check["status"] == "fail"]
    report = {"schemaVersion": "sermon-run-start-check-v1", "status": "fail" if failed else "pass",
              "failed": failed, "checks": checks}
    text = json.dumps(report, ensure_ascii=False, indent=1)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n")
    print(text)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
