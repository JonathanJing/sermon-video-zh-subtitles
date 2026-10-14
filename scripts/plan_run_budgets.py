#!/usr/bin/env python3
"""Write artifact-bound stage approvals without exceeding the approved total.

Only selected stages receive authority. Serial recommendations never authorize
all stages at once. New QC approvals bind one frozen source/anchor/policy,
locale and OpenAI environment, and include the secondary-ASR reservation cap.
"""
from __future__ import annotations
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PROFILE = ROOT / "config/weekly-run-profile.json"
PROFILE_SCHEMA = "sermon-weekly-run-profile-v3"
PLAN_SCHEMA = "sermon-run-budget-plan-v3"
LOCALES = ("zh-Hans", "ko", "es")


def micro(usd):
    if type(usd) not in (int, float) or not math.isfinite(usd) or usd < 0:
        raise ValueError("Budget amounts must be finite and nonnegative")
    return int(round(usd * 1_000_000))


def write_new(path, value):
    if path.exists():
        raise ValueError(f"{path} exists; plans never overwrite an approval")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=1, allow_nan=False) + "\n")
    return path


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def qc_files(out, locale, profile, scale, *, approved_by, evidence, reviewed_at, reuse, context, reuse_sources=()):
    from scripts import machine_qc_budget_authorization as auth
    qc = profile["qc"]
    directory = out / f"qc-{locale}"
    root = str((directory / ".api-budget").resolve())
    secondary = qc["secondaryAsr"]
    cap = qc["capUsdPerLocale"][scale] + secondary["capUsdPerLocale"][scale]
    bounds = {"requests": qc["requests"][scale] + secondary["requests"][scale],
              "wallTimeMs": qc["wallTimeMs"] + secondary["requests"][scale] * secondary["wallTimeMs"],
              "costMicrousd": micro(cap)}
    limits = qc["requestLimits"]
    binding = {"budgetRoot": root, "globalBounds": bounds, "requestLimits": limits,
               "qcContext": context, **({"reuseBudgetRoots": reuse} if reuse else {})}
    approval = write_new(directory / "api-budget-approval.json", {
        "schemaVersion": auth.APPROVAL_V4, "binding": binding,
        "humanApproval": True, "decision": "approved", "reviewedBy": approved_by,
        "reviewedAt": reviewed_at, "operatorEvidence": evidence})
    authorization = write_new(directory / "api-budget-authorization.json", {
        "schemaVersion": auth.AUTH_V4, "budgetRoot": root, "qcContext": context,
        "authority": {"approvalSha256": file_sha256(approval), "bounds": {
            "globalBounds": bounds, "requestLimits": limits}, "requestLimits": limits},
        "approvalReceipt": approval.name, **({"reuseBudgetRoots": reuse} if reuse else {})})
    auth.validate(authorization, context=context, require_scope=True)
    return {"stage": f"qc.{locale}", "authorization": str(authorization),
            "authorizationSha256": file_sha256(authorization), "approvalSha256": file_sha256(approval),
            "budgetRoot": root, "capUsd": cap, "reuseBudgetRoots": reuse, "qcContext": context,
            "executionMode": "replay_only" if reuse else "new_authority",
            **({"reuseSources": list(reuse_sources)} if reuse else {}),
            "secondaryAsr": {"requests": secondary["requests"][scale],
                             "capUsd": secondary["capUsdPerLocale"][scale]}}


def inspect_reuse_source_reference(reference, context):
    """Read-only plan evidence: recheck the exact selected prior authority."""
    from scripts import machine_qc_budget_authorization as auth
    from scripts.check_run_start import inspect_source_root
    if set(reference) != {'plan', 'planSha256', 'authorization', 'authorizationSha256', 'budgetRoot', 'authority'}:
        raise ValueError('Invalid selected reuse source reference')
    if (file_sha256(reference['plan']) != reference['planSha256']
            or file_sha256(reference['authorization']) != reference['authorizationSha256']):
        raise ValueError('Selected reuse source plan or authorization changed')
    value = auth.validate(reference['authorization'], context=context, require_scope=True)
    expected = {'approvalSha256': value['authority']['approvalSha256'],
                'globalBounds': value['authority']['bounds']['globalBounds'],
                'requestLimits': value['authority']['requestLimits']}
    if reference['authority'] != expected or reference['budgetRoot'] != value['budgetRoot']:
        raise ValueError('Selected reuse source authority changed')
    inspect_source_root(Path(reference['budgetRoot']), required=True, as_reuse_source=True,
                        expected=expected, reuse_roots=value.get('reuseBudgetRoots', []))


def resume_qc_stage(path, context):
    """Reference an unchanged prior authority; never grant missing replay-root calls."""
    from scripts import machine_qc_budget_authorization as auth
    from scripts import canonical_layer2_budget as l2
    from scripts.check_run_start import inspect_source_root
    value = auth.validate(path, context=context, require_scope=True)
    if value.get('reuseBudgetRoots'):
        raise ValueError('Replay-only QC roots cannot resume unfinished paid work; use the original paid authority')
    actual = l2.selected_runtime_identity()
    if actual != {'openaiRoute': context['openaiRoute'], 'credentialSha256': context['credentialSha256']}:
        raise ValueError('QC resume launcher identity changed')
    root = Path(value['budgetRoot'])
    authority = {'approvalSha256': value['authority']['approvalSha256'],
                 'globalBounds': value['authority']['bounds']['globalBounds'],
                 'requestLimits': value['authority']['requestLimits']}
    inspect_source_root(root, required=True, expected=authority, reuse_roots=[])
    ledger = json.loads((root / 'source-budget.json').read_text())
    remaining = {key: bound - sum(row['bounds'][key] for row in ledger['requests'].values())
                 for key, bound in authority['globalBounds'].items()}
    if any(value <= 0 for value in remaining.values()):
        raise ValueError('QC prior authority exhausted; cannot approve unfinished paid work')
    return {'stage': 'qc.' + context['targetLocale'], 'authorization': str(Path(path).resolve()),
            'authorizationSha256': file_sha256(path), 'approvalSha256': authority['approvalSha256'],
            'budgetRoot': str(root), 'capUsd': authority['globalBounds']['costMicrousd'] / 1_000_000,
            'reuseBudgetRoots': [], 'qcContext': context,
            'executionMode': 'resume_prior_authority', 'remainingReservationBounds': remaining}


def layer2_backend_of(execution):
    """The one Layer 2 backend every lane policy of this execution freezes."""
    from scripts import canonical_layer2_controller as controller
    from scripts import run_target_language_models as models
    config = controller.load_configuration(execution)
    backends = {models.production_backend(controller._json(lane["policy"])) for lane in config.lanes.values()}
    if len(backends) != 1:
        raise ValueError("Layer 2 lanes of one execution must share a backend")
    return backends.pop()


def layer2_cap_per_locale(profile, scale, backend):
    """``(cap USD per locale, counts toward the approved total)`` for this backend.

    claude_cli_opus runs on the Claude subscription: its ledger cap is a list-price equivalent
    that bounds use, not money, so it never counts toward the approved USD total."""
    layer2 = profile["layer2"]
    if backend == "claude_cli_opus":
        return layer2["claudeCliListPriceCapUsdPerLocale"][scale], False
    return layer2["capUsdPerLocale"][scale], True


def with_clip_claude_cap(profile, *, scale, backend, cap):
    """Apply one explicitly approved clip-run subscription cap without changing the weekly profile."""
    if cap is None:
        return profile
    if scale != 'clip' or backend != 'claude_cli_opus':
        raise ValueError('A Claude list-price override requires a clip Layer 2 Claude execution')
    micro(cap)
    if cap <= 0 or cap > 100:
        raise ValueError('Clip Claude list-price cap must be in (0, 100] USD-equivalent per locale')
    result = copy.deepcopy(profile)
    result['layer2']['claudeCliListPriceCapUsdPerLocale']['clip'] = cap
    return result


def layer2_spec(execution, locales, profile, scale):
    from scripts import canonical_layer2_controller as controller
    from scripts import sermon_provider_limits as limits
    config = controller.load_configuration(execution)
    if sorted(config.lanes) != sorted(locales):
        raise ValueError("Layer 2 execution locales differ from the plan")
    layer2 = profile["layer2"]
    bounds = dict(layer2["boundsPerLocale"][scale])
    bounds["costMicrousd"] = micro(layer2_cap_per_locale(profile, scale, layer2_backend_of(execution))[0])
    anchor = controller._json(controller._path(config.inspection_root, config.inspection["anchor"]))
    source = controller._json(controller._path(config.inspection_root, config.inspection["source"]))
    # The canonical group plan, not a historical calls-per-week estimate.
    sizing = {}
    for locale, lane in config.lanes.items():
        policy = controller._json(lane["policy"])
        if policy.get('targetLocale')!=locale:
            raise ValueError('Layer 2 policy locale differs from its execution lane')
        request = controller.producer.prepare_request(source, anchor, policy, candidate_mode=config.candidate_mode)
        groups = len(controller.models.group_plan(request, anchor))
        # The runner bounds *each* translator and reviewer payload, including
        # serialized source/context/rules and the reviewer's generated draft.
        # The draft is not known at planning time: reserve the full admitted
        # input ceiling rather than assuming zero inputs or guessing bytes from
        # completion tokens. Oversize payloads still fail the runner's gate.
        selected = limits.validate_request_limits(layer2["requestLimits"])
        initial = {"requests": 2 * groups,
                   "inputTokens": 2 * groups * selected["maxInputTokens"],
                   "outputTokens": 2 * groups * selected["maxCompletionTokens"],
                   "wallTimeMs": 2 * groups * selected["wallTimeMs"],
                   "costMicrousd": groups * sum(limits._cost(policy[role]["model"],
                       selected["maxInputTokens"], selected["maxCompletionTokens"])
                       for role in ("translator", "reviewer"))}
        for dimension, required in initial.items():
            available = bounds.get(dimension)
            if type(available) is not int or not 0 < available <= limits.MAX_METRIC or available < required:
                raise ValueError(f"Layer 2 {locale} {dimension} cap cannot cover even the initial "
                                 f"{initial['requests']} calls; use an explicitly approved profile, "
                                 "do not inflate authority implicitly")
        sizing[locale] = {"groups": groups, "initialRequests": initial["requests"],
                          "initialOutputReservationMicrousd": groups * sum(
                              limits._cost(policy[role]["model"], 0, selected["maxCompletionTokens"])
                              for role in ("translator", "reviewer")),
                          "initialReservation": initial,
                          "inputReservationBasis": "full-bounded-payload-ceiling-per-role"}
    return config, bounds, sizing


def layer2_files(out, execution, locales, profile, scale, *, approved_by, evidence, reviewed_at, prepared=None):
    from scripts import canonical_layer2_budget as budget_tools
    from scripts import canonical_layer2_controller as controller
    config, per_locale, sizing = prepared or layer2_spec(execution, locales, profile, scale)
    layer2 = profile["layer2"]
    runtime_identity = budget_tools.selected_runtime_identity()
    sharded = scale == "week"
    bounds = per_locale if sharded else {k: v * len(locales) for k, v in per_locale.items()}
    limits, rules = layer2["requestLimits"], layer2["limits"]
    root = budget_tools.budget_root(config)
    directory = out / "layer2"
    binding = {"productionRunId": config.run_id, "configurationSha256": config.sha256,
               "codeIdentitySha256": controller.code_identity(), "budgetRoot": str(root),
               "requestLimits": limits, "globalBounds": bounds, "unitBounds": bounds, "limits": rules,
               "ledgerScope": "locale" if sharded else "run", "runtimeIdentity": runtime_identity}
    approval = write_new(directory / "budget-approval.json", {
        "schemaVersion": budget_tools.RUNTIME_APPROVAL_SCHEMA, "binding": binding,
        "humanApproval": True, "decision": "approved", "reviewedBy": approved_by,
        "reviewedAt": reviewed_at, "operatorEvidence": evidence})
    authorization = write_new(directory / "budget-authorization.json", {
        "schemaVersion": budget_tools.RUNTIME_SCHEMA,
        "productionRunId": config.run_id, "configurationSha256": config.sha256,
        "codeIdentitySha256": binding["codeIdentitySha256"], "requestLimits": limits,
        "authority": {"approvalSha256": file_sha256(approval), "globalBounds": bounds,
                      "unitBounds": bounds, "limits": rules}, "approvalReceipt": approval.name,
        "ledgerScope": "locale" if sharded else "run", "runtimeIdentity": runtime_identity})
    budget_tools.load_authorization(config, authorization, binding["codeIdentitySha256"])
    backend = layer2_backend_of(execution)
    cap, counts = layer2_cap_per_locale(profile, scale, backend)
    return {"stage": "layer2", "authorization": str(authorization),
            "authorizationSha256": file_sha256(authorization), "approvalSha256": file_sha256(approval),
            "budgetRoot": str(root), "runtimeIdentity": runtime_identity, "capUsd": cap * len(locales),
            "layer2Backend": backend, "countsTowardTotal": counts,
            "execution": str(execution), "executionSha256": file_sha256(execution), "locales": locales,
            "sizing": sizing, "inputFiles": [
                {"path":str(path),"sha256":file_sha256(path)} for path in [
                    controller._path(config.inspection_root,config.inspection['source']),
                    controller._path(config.inspection_root,config.inspection['anchor']),
                    *[lane['policy'] for lane in config.lanes.values()]]], "ledgerScope": "locale" if sharded else "run"}


def schedule(stages, *, total, settled):
    total_micro, settled_micro = micro(total), micro(settled)
    # A Claude subscription stage's cap is a list-price equivalent, not money (countsTowardTotal false).
    caps = [micro(stage["capUsd"]) for stage in stages if stage.get("countsTowardTotal", True)]
    worst = settled_micro + sum(caps)
    if worst <= total_micro:
        return {"mode": "all_stages_may_run_together", "worstCaseUsd": worst / 1_000_000, "fits": True}
    serial = settled_micro + max(caps, default=0) <= total_micro
    return {"mode": "one_stage_at_a_time" if serial else "does_not_fit", "fits": False,
            "worstCaseUsd": worst / 1_000_000, "requiresStageSelection": serial,
            "note": "No authority issued. Select one --stage and re-plan only after reconciling earlier spend."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--scale", choices=("clip", "week"), required=True)
    parser.add_argument("--locales", default=",".join(LOCALES))
    parser.add_argument("--stage", action="append", default=[], help="Only these stages receive approval (layer2 or qc.LOCALE)")
    parser.add_argument("--total-usd", type=float, required=True)
    parser.add_argument("--settled-usd", type=float, default=0)
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--layer2-execution", type=Path)
    parser.add_argument("--claude-list-price-cap-usd-per-locale", type=float,
                        help="Explicitly approved cap for this clip Claude Layer 2 plan only")
    parser.add_argument("--qc-inputs", type=Path, help="Frozen source, anchor and per-locale policy manifest")
    parser.add_argument("--reuse-from", type=Path, action="append", default=[],
                        help="QC replay-only roots: missing operations refuse payment; not partial-run continuation")
    parser.add_argument("--resume-qc-authorization", type=Path, action="append", default=[],
                        help="Resume unfinished QC under unchanged original v4 authority/root; repeat per locale. Mutually exclusive with --reuse-from")
    parser.add_argument("--profile", type=Path, default=PROFILE)
    args = parser.parse_args(argv)
    from scripts import machine_qc_budget_authorization as auth
    if args.reuse_from and args.resume_qc_authorization:
        parser.error("Choose replay-only --reuse-from or --resume-qc-authorization, not both")
    from scripts.sermon_provider_limits import validate_request_limits
    profile = json.loads(args.profile.read_text())
    if profile.get("schemaVersion") != PROFILE_SCHEMA:
        parser.error("New plans require profile v2; old plans retain their original files, re-plan explicitly")
    locales = args.locales.split(",")
    if not locales or len(set(locales)) != len(locales) or set(locales) - set(LOCALES):
        parser.error("Locales must be distinct supported values")
    if not args.approved_by.strip() or not args.evidence.strip():
        parser.error("Approval needs an actual approver and evidence")
    if args.claude_list_price_cap_usd_per_locale is not None:
        if not args.layer2_execution or 'layer2' not in args.stage:
            parser.error('Claude list-price override requires a selected Layer 2 execution')
        profile = with_clip_claude_cap(profile, scale=args.scale,
            backend=layer2_backend_of(args.layer2_execution.resolve()),
            cap=args.claude_list_price_cap_usd_per_locale)
    if args.out.exists() and (not args.out.is_dir() or any(args.out.iterdir())):
        parser.error("Output must be new or empty")
    validate_request_limits(profile["layer2"]["requestLimits"])
    validate_request_limits(profile["qc"]["requestLimits"])
    for kind in ('layer2', 'qc'):
        micro(profile[kind]['capUsdPerLocale'][args.scale])
    micro(profile['qc']['secondaryAsr']['capUsdPerLocale'][args.scale])
    layer2_cap = (layer2_cap_per_locale(profile, args.scale, layer2_backend_of(args.layer2_execution.resolve()))
                  if args.layer2_execution else None)
    available = ([{"stage": "layer2", "capUsd": layer2_cap[0] * len(locales), "countsTowardTotal": layer2_cap[1]}]
                 if args.layer2_execution else []) + [{"stage": f"qc.{locale}", "capUsd":
                    profile["qc"]["capUsdPerLocale"][args.scale] + profile["qc"]["secondaryAsr"]["capUsdPerLocale"][args.scale]}
                    for locale in locales]
    if args.stage and (len(set(args.stage)) != len(args.stage) or set(args.stage) - {s["stage"] for s in available}):
        parser.error("Selected stage is not in this plan")
    selected = [s for s in available if not args.stage or s["stage"] in args.stage]
    planned = schedule(selected, total=args.total_usd, settled=args.settled_usd)
    if not planned["fits"] and not args.resume_qc_authorization:
        print(json.dumps(planned)); return 1
    qc_locales = [s["stage"].split(".")[1] for s in selected if s["stage"].startswith("qc.")]
    if qc_locales and not args.qc_inputs:
        parser.error("QC stages require --qc-inputs binding the frozen source and locale policies")
    for locale in qc_locales:
        qc=profile['qc'];secondary=qc['secondaryAsr']
        dimensions=(qc['requests'][args.scale],secondary['requests'][args.scale],qc['wallTimeMs'],secondary['wallTimeMs'])
        if any(type(value) is not int or not 0<value<=10**15 for value in dimensions):
            parser.error('Invalid QC request or time bounds')
    contexts = auth.contexts_from_manifest(args.qc_inputs, qc_locales) if qc_locales else {}
    prepared = (layer2_spec(args.layer2_execution.resolve(), locales, profile, args.scale)
                if any(s["stage"] == "layer2" for s in selected) else None)
    resumes = {}
    for path in args.resume_qc_authorization:
        previous = auth.validate(path, require_scope=True)
        locale = previous['qcContext']['targetLocale']
        if locale not in contexts or locale in resumes:
            parser.error('Resume authority must name one distinct selected QC locale')
        resumes[locale] = resume_qc_stage(path, contexts[locale])
    if args.resume_qc_authorization and set(resumes) != set(qc_locales):
        parser.error('Resume mode requires an original authority for every selected QC locale')
    for stage in selected:
        if stage['stage'].startswith('qc.') and stage['stage'].split('.')[1] in resumes:
            stage['capUsd'] = resumes[stage['stage'].split('.')[1]]['capUsd']
    planned = schedule(selected, total=args.total_usd, settled=args.settled_usd)
    if not planned['fits']:
        print(json.dumps(planned)); return 1
    reuse = {locale: [] for locale in qc_locales}
    reuse_sources = {locale: [] for locale in qc_locales}
    for prior in args.reuse_from:
        prior_plan = json.loads((prior / "plan.json").read_text())
        prior_receipt = prior / prior_plan['approvalReceipt']
        approved = json.loads(prior_receipt.read_text())
        frozen = {key: value for key, value in prior_plan.items() if key not in {'approvalReceipt', 'approvalSha256'}}
        if (prior_plan.get('schemaVersion') != PLAN_SCHEMA
                or file_sha256(prior_receipt) != prior_plan['approvalSha256']
                or approved.get('schemaVersion') != 'sermon-run-budget-plan-approval-v1'
                or approved.get('binding') != frozen or approved.get('humanApproval') is not True
                or approved.get('decision') != 'approved' or not approved.get('reviewedBy')
                or not approved.get('operatorEvidence')):
            raise ValueError('Reuse prior plan or approval changed')
        for locale in qc_locales:
            matches = [s for s in prior_plan["stages"] if s["stage"] == f"qc.{locale}"]
            if len(matches) != 1:
                parser.error("Reuse plan lacks the exact locale stage")
            previous = auth.validate(matches[0]["authorization"], context=contexts[locale], require_scope=True)
            stage = matches[0]
            if (file_sha256(stage['authorization']) != stage['authorizationSha256']
                    or previous['authority']['approvalSha256'] != stage['approvalSha256']
                    or stage['budgetRoot'] != previous['budgetRoot']
                    or stage['qcContext'] != previous['qcContext']
                    or stage.get('reuseBudgetRoots', []) != previous.get('reuseBudgetRoots', [])
                    or micro(stage['capUsd']) != previous['authority']['bounds']['globalBounds']['costMicrousd']):
                raise ValueError('Reuse prior stage differs from its authorization')
            root = str(Path(previous["budgetRoot"]).resolve())
            if not (Path(root) / "source-budget.json").is_file():
                parser.error("Reuse root has no paid ledger to reconcile")
            from scripts.check_run_start import inspect_source_root
            expected = {'approvalSha256': previous['authority']['approvalSha256'],
                        'globalBounds': previous['authority']['bounds']['globalBounds'],
                        'requestLimits': previous['authority']['requestLimits']}
            inspect_source_root(Path(root), required=True, as_reuse_source=True,
                                expected=expected, reuse_roots=previous.get('reuseBudgetRoots', []))
            if root in reuse[locale]:
                parser.error("Duplicate reuse root; list each approved source only once")
            reuse[locale].append(root)
            reuse_sources[locale].append({'plan': str((prior / 'plan.json').resolve()),
                'planSha256': file_sha256(prior / 'plan.json'),
                'authorization': str(Path(stage['authorization']).resolve()),
                'authorizationSha256': stage['authorizationSha256'],
                'budgetRoot': previous['budgetRoot'], 'authority': expected})
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    common = {"approved_by": args.approved_by, "evidence": args.evidence, "reviewed_at": now}
    stages = []
    for stage in selected:
        if stage["stage"] == "layer2":
            stages.append(layer2_files(args.out, args.layer2_execution.resolve(), locales, profile, args.scale,
                                       prepared=prepared, **common))
        else:
            locale = stage["stage"].split(".")[1]
            stages.append(resumes[locale] if locale in resumes else qc_files(
                args.out, locale, profile, args.scale, reuse=reuse[locale], context=contexts[locale],
                reuse_sources=reuse_sources[locale], **common))
    from scripts import machine_quality_waiver as waiver
    plan = {"schemaVersion": PLAN_SCHEMA, "createdAt": now, "scale": args.scale, "locales": locales,
            "profileSha256": file_sha256(args.profile), "profile": str(args.profile.resolve()),
            "clipClaudeListPriceCapUsdPerLocale": args.claude_list_price_cap_usd_per_locale,
            "totalUsd": args.total_usd, "settledUsd": args.settled_usd, "approvedBy": args.approved_by,
            "evidence": args.evidence, "stages": stages, "schedule": schedule(stages, total=args.total_usd, settled=args.settled_usd),
            "qcInputs": {"path": str(args.qc_inputs.resolve()), "sha256": file_sha256(args.qc_inputs)} if qc_locales else None,
            "expectedCommit": __import__('subprocess').check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip(),
            "expectedImplementation": waiver.implementation_sha256()}
    approval = write_new(args.out / "plan-approval.json", {
        "schemaVersion": "sermon-run-budget-plan-approval-v1", "binding": plan,
        "humanApproval": True, "decision": "approved", "reviewedBy": args.approved_by,
        "reviewedAt": now, "operatorEvidence": args.evidence})
    plan = {**plan, "approvalReceipt": approval.name, "approvalSha256": file_sha256(approval)}
    write_new(args.out / "plan.json", plan)
    print(json.dumps({"plan": str(args.out / 'plan.json'), "schedule": plan['schedule']}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
