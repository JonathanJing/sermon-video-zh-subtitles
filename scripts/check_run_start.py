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
import re
import shlex
from urllib.error import HTTPError
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
    if not expected_commit or not re.fullmatch(r"[a-f0-9]{40}", expected_commit) or head != expected_commit:
        problems.append(f"HEAD {head[:12]} is not {expected_commit}")
    if not expected_implementation or implementation != expected_implementation:
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



def selected_launcher_identity(environment, env_file):
    """Resolve the real launcher file read-only; retain only non-secret identity."""
    from scripts import run_with_openai_environment as launcher
    from scripts.machine_qc_budget_authorization import credential_fingerprint
    from scripts.sermon_openai_runtime import safe_route
    selected = launcher.child_environment(Path(env_file) if env_file else ROOT / '.env.openai',
                                          environment, inherited={})
    route = safe_route({'schemaVersion': 'sermon-openai-runtime-route-v1',
                       'environment': selected['SERMON_OPENAI_ENVIRONMENT'],
                       'projectId': selected['OPENAI_PROJECT_ID'],
                       'credentialAlias': selected['SERMON_OPENAI_CREDENTIAL_ALIAS'],
                       'identitySource': 'configured_runtime'})
    if route is None:
        raise ValueError('invalid_selected_openai_runtime')
    return {'openaiRoute': route, 'credentialSha256': credential_fingerprint(selected['OPENAI_API_KEY'])}


def check_launcher_binding(plan_dir, environment, env_file):
    from scripts import machine_qc_budget_authorization as auth
    try:
        planned = json.loads((plan_dir / 'plan.json').read_text())
        stages = [stage for stage in planned['stages'] if stage['stage'].startswith('qc.') or stage['stage'] == 'layer2']
        if not stages:
            return result('environment_binding', 'pass', qcStages=0, layer2Stages=0, problems=[])
        selected = selected_launcher_identity(environment, env_file)
        qc_count = l2_count = 0
        for stage in stages:
            if stage['stage'] == 'layer2':
                from scripts import canonical_layer2_budget as l2, canonical_layer2_controller as controller
                config = controller.load_configuration(Path(stage['execution']))
                admitted = l2.load_authorization(config, Path(stage['authorization']), controller.code_identity(), stage['authorizationSha256'])
                if admitted.get('runtimeIdentity') != selected or stage.get('runtimeIdentity') != selected:
                    raise ValueError('launcher_identity_changed')
                l2_count += 1
            else:
                admitted = auth.validate(Path(stage['authorization']), require_scope=True)
                context = admitted['qcContext']
                if (context['environment'] != environment or
                        context['openaiRoute'] != selected['openaiRoute'] or
                        context['credentialSha256'] != selected['credentialSha256']):
                    raise ValueError('launcher_identity_changed')
                qc_count += 1
        return result('environment_binding', 'pass', qcStages=qc_count, layer2Stages=l2_count, problems=[])
    except (OSError, ValueError, KeyError, TypeError, AttributeError, UnicodeError):
        # No key material or parser exception text enters the public preflight.
        return result('environment_binding', 'fail',
                      problems=['Selected launcher route or credential differs from QC approval, or binding cannot be verified'])

def inspect_source_root(root, *, expected=None, reuse_roots=None, required=False, as_reuse_source=False):
    """Read-only counterpart of durable source admission; never opens/migrates a ledger."""
    from scripts import sermon_source_budget as source, sermon_workflow_jobs as jobs
    root = Path(root)
    path = root / 'source-budget.json'
    if not path.exists():
        if required or root.exists() and any(root.iterdir()):
            raise ValueError('source budget evidence missing; reconcile existing root')
        return
    value = json.loads(path.read_text())
    version = value.get('schemaVersion')
    if version not in {'sermon-source-budget-ledger-v1', *source.CONCURRENT_LEDGERS} or not isinstance(value.get('requests'),dict):
        raise ValueError('source budget ledger corrupt')
    keys={'schemaVersion','authority','requests'}
    if version in source.CONCURRENT_LEDGERS:
        keys|={'maxConcurrent','resourcePolicySha256'}
    if version==source.LEDGER_V4:
        keys.add('reuseBudgetRoots')
    if set(value)!=keys:
        raise ValueError('source ledger metadata changed')
    concurrency=value.get('maxConcurrent',1)
    roots=value.get('reuseBudgetRoots',[])
    source.SourceBudget(root,value['authority'],verify=lambda:None,max_concurrent=concurrency,reuse_roots=roots)
    if (not re.fullmatch('[a-f0-9]{64}',value['authority'].get('approvalSha256',''))
            or any(not isinstance(name,str) or not Path(name).is_absolute() for name in roots)):
        raise ValueError('invalid source ledger authority or reuse roots')
    if expected is not None:
        if version not in source.CONCURRENT_LEDGERS or concurrency!=16 or value.get('resourcePolicySha256') is not None:
            raise ValueError('QC ledger runtime metadata changed; explicit migration required')
        if reuse_roots and version!=source.LEDGER_V4:
            raise ValueError('source_budget_v4_explicit_migration_required')
    elif value.get('resourcePolicySha256') is not None:
        # This planner has no resource-policy input with which to verify a broker-bound root.
        raise ValueError('resource-bound reuse root requires explicit reconciliation')
    if expected is not None and value.get('authority') != expected:
        raise ValueError('budget root already belongs to another approval')
    if version == source.LEDGER_V4 and reuse_roots is not None and value.get('reuseBudgetRoots') != reuse_roots:
        raise ValueError('source reuse identity changed')
    for operation,row in value['requests'].items():
        if not isinstance(operation,str) or not re.fullmatch(r'(asr\.[0-9]{4}|judge\.[a-f0-9]{64})',operation):
            raise ValueError('invalid source operation')
        if row.get('status') != 'returned':
            raise ValueError('source provider outcome unknown; reconcile before dispatch')
        row_keys={'identitySha256','bounds','status','responseSha256'}
        if version in source.SETTLED_LEDGERS:row_keys.add('settlement')
        bounds=row.get('bounds',{})
        if (set(row)!=row_keys or set(bounds)!=set(source.METRICS) or bounds.get('requests')!=1
                or any(type(n) is not int or not 0<n<=10**15 for n in bounds.values())
                or not re.fullmatch('[a-f0-9]{64}',row.get('identitySha256',''))):
            raise ValueError('invalid source returned row')
        fingerprint=row['identitySha256']
        response=root/'responses'/(jobs._digest(operation)+'-'+fingerprint+'.json')
        if not response.exists():response=root/'responses'/(fingerprint+'.json')
        saved=json.loads(response.read_text())
        if (jobs._digest(saved)!=row.get('responseSha256') or saved.get('identitySha256')!=fingerprint
                or jobs._digest(saved.get('requestIdentity'))!=fingerprint
                or saved.get('reservationBounds')!=row.get('bounds')):
            raise ValueError('damaged paid receipt; reconcile before dispatch')
        if version in source.SETTLED_LEDGERS and not source._valid_settlement(row.get('settlement'),version=version):
            raise ValueError('invalid paid settlement')
        reused=row.get('settlement',{}).get('costStatus')=='reused'
        if as_reuse_source and (reused or 'reusedFrom' in saved):
            raise ValueError('reuse requires a direct paid source root')
        if reused:
            provenance=saved.get('reusedFrom',{})
            if (version!=source.LEDGER_V4 or saved.get('settlement')!=row['settlement']
                    or provenance.get('budgetRoot') not in roots or provenance.get('operation')!=operation
                    or provenance.get('sourceLedgerVersion') not in {'sermon-source-budget-ledger-v1',*source.CONCURRENT_LEDGERS}
                    or not source._valid_settlement(provenance.get('originalSettlement'),version=source.LEDGER_V3)
                    or any(not re.fullmatch('[a-f0-9]{64}',provenance.get(key,''))
                           for key in ('responseSha256','sourceAuthoritySha256'))):
                raise ValueError('source_reused_provenance_changed')


def inspect_layer2_root(root, authority, *, locale_scope):
    from scripts import sermon_review_budget as ledger, sermon_workflow_jobs as jobs
    store=ledger.BudgetStore(root,authority,max_ledger_bytes=8*1024*1024 if locale_scope else None)
    _,folder,_=jobs._paths(store.root,ledger.STORE_ID)
    path=folder/'state.json'
    if not folder.exists():return
    value,_=ledger.read_snapshot(path,max_bytes=store.max_ledger_bytes)
    if (set(value)!={'schemaVersion','authority','storeSha256','reservations'}
            or value['schemaVersion']!=ledger.SCHEMA or value['authority']!=store.authority
            or value['storeSha256']!=store.store_sha256 or not isinstance(value['reservations'],dict)):
        raise ValueError('Layer 2 budget identity changed')
    for key,row in value['reservations'].items():
        store._validate_row(key,row)
        if row['phase']!='result' or row['result']['executionStatus']=='outcome_unknown':
            raise ValueError('Layer 2 budget has unresolved reservations; reconcile before dispatch')



def inspect_layer2_calls(config):
    """Do not infer runner recovery from a settled budget row; inspect lane files."""
    for locale, lane in config.lanes.items():
        output = Path(lane['output'])
        if not output.is_dir():
            continue
        policy = json.loads(Path(lane['policy']).read_text())
        for marker in output.rglob('group-*.started.json'):
            try:
                started = json.loads(marker.read_text())
                role, fingerprint = started['role'], started['payloadSha256']
                if (role not in {'translator', 'reviewer'} or
                        started['status'] != 'started_response_unconfirmed' or
                        not isinstance(fingerprint, str) or not re.fullmatch('[a-f0-9]{64}', fingerprint)):
                    raise ValueError('invalid marker')
                stem = marker.name.removesuffix('.started.json')
                cache, raw = marker.with_name(stem + '.json'), marker.with_name(stem + '.raw.json')
                if cache.is_file():
                    saved = json.loads(cache.read_text())
                    valid = (saved.get('payloadSha256') == fingerprint and
                             saved.get('model') == policy[role]['model'] and
                             isinstance(saved.get('requestId'), str) and bool(saved['requestId']) and
                             isinstance(saved.get('result'), dict))
                elif raw.is_file():
                    saved = json.loads(raw.read_text())
                    valid = saved.get('payloadSha256') == fingerprint and isinstance(saved.get('response'), dict)
                else:
                    valid = False
                if not valid:
                    raise ValueError('unrecovered or mismatched return')
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                raise ValueError(f'Layer 2 {locale} call marker requires reconciliation before dispatch: {marker.name}') from error

def check_budget(plan_dir: Path):
    from scripts import machine_qc_budget_authorization as qc_auth
    from scripts import plan_run_budgets as planner
    from scripts import canonical_layer2_budget as l2_budget, canonical_layer2_controller as controller
    problems = []
    try:
        plan = json.loads((plan_dir / "plan.json").read_text())
        if plan.get("schemaVersion") != planner.PLAN_SCHEMA:
            raise ValueError("Unsupported old plan: re-plan explicitly under the current contract")
        approval_path = plan_dir / plan['approvalReceipt']
        approval = json.loads(approval_path.read_text())
        binding = {key:value for key,value in plan.items() if key not in {'approvalReceipt','approvalSha256'}}
        if (sha256(approval_path)!=plan['approvalSha256']
                or approval.get('schemaVersion')!='sermon-run-budget-plan-approval-v1'
                or approval.get('humanApproval') is not True or approval.get('decision')!='approved'
                or not approval.get('reviewedBy') or not approval.get('operatorEvidence')
                or approval.get('binding')!=binding):
            raise ValueError('Aggregate total, prior spend or stage plan changed since approval')
        if not plan.get('stages') or len({stage['stage'] for stage in plan['stages']})!=len(plan['stages']):
            raise ValueError('Empty or duplicate planned stages')
        if sha256(Path(plan["profile"])) != plan["profileSha256"]:
            raise ValueError("profile changed since approval planning")
        observed = planner.schedule(plan["stages"], total=plan["totalUsd"], settled=plan["settledUsd"])
        if observed != plan["schedule"] or not observed["fits"]:
            raise ValueError("stage caps do not fit or schedule changed")
        for stage in plan["stages"]:
            authorization = Path(stage["authorization"])
            if sha256(authorization) != stage["authorizationSha256"]:
                raise ValueError(f"{stage['stage']}: authorization changed since planning")
            value = json.loads(authorization.read_text())
            receipt = authorization.parent / value["approvalReceipt"]
            if sha256(receipt) != stage["approvalSha256"] or stage["approvalSha256"] != value["authority"]["approvalSha256"]:
                raise ValueError(f"{stage['stage']}: approval changed since planning")
            if stage["stage"].startswith("qc."):
                locale = stage["stage"].split(".")[1]
                if locale not in plan["locales"]:
                    raise ValueError("QC locale is not planned")
                manifest = Path(plan["qcInputs"]["path"])
                if sha256(manifest) != plan["qcInputs"]["sha256"]:
                    raise ValueError("QC input manifest changed")
                context = qc_auth.contexts_from_manifest(manifest, [locale])[locale]
                admitted = qc_auth.validate(authorization, context=context, require_scope=True)
                if (stage["budgetRoot"] != admitted["budgetRoot"] or stage["qcContext"] != context
                        or stage.get("reuseBudgetRoots", []) != admitted.get("reuseBudgetRoots", [])
                        or planner.micro(stage["capUsd"]) != admitted["authority"]["bounds"]["globalBounds"]["costMicrousd"]):
                    raise ValueError("QC stage and approval differ")
                ledger = Path(stage["budgetRoot"]) / "source-budget.json"
                expected = {"approvalSha256": admitted["authority"]["approvalSha256"],
                            "globalBounds": admitted["authority"]["bounds"]["globalBounds"],
                            "requestLimits": admitted["authority"]["requestLimits"]}
                inspect_source_root(Path(stage['budgetRoot']),expected=expected,
                                    reuse_roots=admitted.get('reuseBudgetRoots',[]))
                for root in admitted.get('reuseBudgetRoots',[]):
                    inspect_source_root(Path(root),required=True,as_reuse_source=True)
            elif stage["stage"] == "layer2":
                execution = Path(stage["execution"])
                if sha256(execution) != stage["executionSha256"]:
                    raise ValueError("Layer 2 execution changed")
                config = controller.load_configuration(execution)
                for row in stage['inputFiles']:
                    if sha256(Path(row['path']))!=row['sha256']:
                        raise ValueError('Layer 2 frozen input changed')
                _,_,sizing=planner.layer2_spec(execution,stage['locales'],json.loads(Path(plan['profile']).read_text()),plan['scale'])
                if sizing!=stage['sizing']:
                    raise ValueError('Layer 2 group sizing changed')
                checked = l2_budget.load_authorization(config, authorization, controller.code_identity(), stage["authorizationSha256"])
                if checked.get('runtimeIdentity') is None or stage.get('runtimeIdentity') != checked['runtimeIdentity']:
                    raise ValueError('Layer 2 runtime binding requires explicit v3 re-plan')
                inspect_layer2_calls(config)
                roots=([l2_budget.ledger_root(checked,locale) for locale in config.lanes]
                       if checked['scope']=='locale' else [checked['root']])
                for root in roots:
                    inspect_layer2_root(root,checked['value']['authority'],locale_scope=checked['scope']=='locale')
                cap = checked["value"]["authority"]["globalBounds"]["costMicrousd"]
                if checked["scope"] == "locale":
                    cap *= len(config.lanes)
                if planner.micro(stage["capUsd"]) != cap or str(checked["root"]) != stage["budgetRoot"]:
                    raise ValueError("Layer 2 stage and approval differ")
            else:
                raise ValueError("Unknown stage")
        return result("budget", "pass", plan=str(plan_dir / "plan.json"), schedule=observed,
                      stages=[(s["stage"], s["capUsd"]) for s in plan["stages"]], problems=[])
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        problems.append(f"Invalid budget plan: {error}")
        return result("budget", "fail", plan=str(plan_dir / "plan.json"), problems=problems)


def ssh(command: str, host: str) -> subprocess.CompletedProcess:
    return subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", host, command],
                          capture_output=True, text=True, timeout=60)


def check_spark(host, spark_stages, code_dir):
    if spark_stages:
        from scripts.spark_exclusive_session import DEFAULT_HOST
        session_host = os.environ.get('SPARK_EXCLUSIVE_HOST', DEFAULT_HOST)
        if host != session_host:
            return result('spark', 'fail', host=host,
                          problems=['Selected Spark host differs from the exclusive session host'])
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
        remote = ssh("cd " + shlex.quote(code_dir) + " && sha256sum " + " ".join(shlex.quote(path) for path in files), host)
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
    try:
        for name in ("multilingual-v3.json", "multilingual-v4.json"):
            try:
                with urlopen(Request(origin + "/" + name, headers={"Cache-Control": "no-cache"}), timeout=60) as response:
                    pages = json.loads(response.read())["pages"]
            except HTTPError as error:
                if name == "multilingual-v4.json" and error.code == 404:
                    continue
                raise
            if not isinstance(pages, list) or any(not isinstance(page, dict) for page in pages):
                raise ValueError("Invalid catalog pages")
            if any(page.get("id") == page_id for page in pages):
                seen.append(name)
        return result("page", "fail" if seen else "pass", pageId=page_id, origin=origin,
                      problems=[f"{page_id} already in {name}" for name in seen])
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        return result("page", "fail", pageId=page_id, origin=origin,
                      problems=[f"Catalog check failed: {type(error).__name__}"])


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
    parser.add_argument("--origin", help="Explicit Hosting origin required with --page-id (dev or prod).")
    parser.add_argument("--out", type=Path, help="Also write the report here")
    args = parser.parse_args(argv)
    identity_problems=[]
    if args.budget_plan:
        try:
            frozen = json.loads((args.budget_plan / "plan.json").read_text())
            if ((args.expected_commit and args.expected_commit!=frozen['expectedCommit'])
                    or (args.expected_implementation and args.expected_implementation!=frozen['expectedImplementation'])):
                identity_problems.append('Explicit expected identities differ from the frozen plan')
            args.expected_commit = args.expected_commit or frozen["expectedCommit"]
            args.expected_implementation = args.expected_implementation or frozen["expectedImplementation"]
        except (OSError, ValueError, KeyError, TypeError):
            pass  # Missing identities fail the code check and are included in the report.
    def checked(name,function):
        try:return function()
        except Exception as error:
            return result(name,'fail',problems=[type(error).__name__])
    checks = [checked('code',lambda:check_code(args.expected_commit, args.expected_implementation))]
    if identity_problems:checks.append(result('identity_binding','fail',problems=identity_problems))
    if args.env_file and not args.openai_environment:
        checks.append(result('environment_binding', 'fail',
                             problems=['--env-file requires --openai-environment']))
    checks.append(checked('openai',lambda:check_openai(args.openai_environment, args.env_file)) if args.openai_environment
                  else result("openai", "skip"))
    checks.append(checked('budget',lambda:check_budget(args.budget_plan)) if args.budget_plan else result("budget", "skip"))
    checks.append(checked('spark',lambda:check_spark(args.spark_host, args.spark_stages, args.spark_code_dir))
                  if args.spark or args.spark_stages or args.spark_code_dir else result("spark", "skip"))
    checks.append(checked('outputs',lambda:check_fresh(args.fresh_dir)) if args.fresh_dir else result("outputs", "skip"))
    if args.page_id and not args.origin:
        checks.append(result('page', 'fail', pageId=args.page_id,
                             problems=['--page-id requires an explicit --origin for the target Hosting environment']))
    else:
        checks.append(checked('page',lambda:check_page(args.page_id, args.origin)) if args.page_id else result("page", "skip"))
    if args.openai_environment and args.budget_plan:
        checks.append(check_launcher_binding(args.budget_plan, args.openai_environment, args.env_file))
    elif args.budget_plan and not args.env_file:
        def require_planned_launcher():
            stages = json.loads((args.budget_plan / 'plan.json').read_text())['stages']
            if any(stage['stage'] == 'layer2' or stage['stage'].startswith('qc.') for stage in stages):
                return result('environment_binding', 'fail', problems=['Layer 2 or QC plan requires --openai-environment'])
            return result('environment_binding', 'skip')
        checks.append(checked('environment_binding', require_planned_launcher))
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
