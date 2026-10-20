"""Executable per-group orchestration: status, run (T/R/P) and merge (DEV-GRP-006/007).

docs/design/per-group-independent-pipeline.zh.md: a locale's groups are independent
Layer 2 tasks and are merged once before Layer 3. This module is the operator entry:

* ``status`` reports every group's stage state from the record store and the current
  inputs, without dispatching or writing anything but its own report;
* ``run`` executes T, R and P for the groups that are stale or missing, one group at a
  time, through ``group_worker`` (a paid command: it requires a per-group budget
  document and stops on an unknown paid outcome);
* ``merge`` assembles the candidate from the group records with the unchanged
  ``text.candidate`` admission, checks whole-text length outliers, and writes the
  merge manifest. It does not run Layer 3: steps 4-10 are named as pending with the
  exact command that continues them.

No function here grants human approval or publishes anything. ``merge`` output is a
machine-review candidate plus a merge manifest; Layer 3 still needs its own receipts.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from . import group_assembly
from . import group_budget
from . import group_legacy as legacy
from . import group_plan
from . import group_records as records
from . import group_worker

STATUS_SCHEMA = "sermon-group-status-v1"
RUN_SCHEMA = "sermon-group-run-report-v1"
MERGE_SCHEMA = "sermon-group-merge-manifest-v1"
DIRECTIVE_SCHEMA = "sermon-group-directive-v1"
DIRECTIVE_DIRECTORY = "_directives"
PENDING_STEPS = (
    "calibration", "text_release_basis", "speech_job_v3", "formal_render",
    "schedule_and_subtitles", "track_package", "screening_and_audio_qc", "listening_waiver",
)
L3_HANDOFF = ("python tools/ops/run.py audio.speech_job --text-release-basis <text-release-basis> "
              "--out <speech-job>")
# Stages the per-group worker currently executes. Q/C/S/A/U are not dispatched here yet.
WORKER_STAGES = ("T", "R", "P")
UNSETTLED = {"stale", "missing", "conflict", "failed", "stopped"}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def stage_identities(config: dict) -> dict:
    """Current implementation identities for every stage, from this checkout's code."""
    from ..audio import renderer, screening
    from ..review import audio_qc, waiver
    from ..text import candidate as producer
    from ..text import models
    from ..text import policy as policy_tools
    policy = legacy.load_json(config["policy"])
    return {
        "runnerImplementationSha256": models.RUNNER_PRODUCTION_IDENTITY_SHA256,
        "machineQcImplementationSha256": waiver.implementation_sha256(),
        "rendererSoundIdentitySha256": renderer.RENDERER_SOUND_IDENTITY_SHA256,
        "asrImplementationSha256": screening.implementation_sha256(),
        "audioQcThresholdsSha256": records.json_sha256(audio_qc.THRESHOLDS),
        "pluginImplementationSha256": producer.plugin_implementation_sha256(config["plugin"]),
        "languageReviewPolicySha256": policy_tools.validate_policy(policy)["languageReviewPolicySha256"],
    }


def _implementation(stage: str, identities: dict) -> str | None:
    return {"T": identities["runnerImplementationSha256"], "R": identities["runnerImplementationSha256"],
            "P": identities["pluginImplementationSha256"], "Q": identities["machineQcImplementationSha256"],
            "C": identities["machineQcImplementationSha256"], "S": identities["rendererSoundIdentitySha256"],
            "A": identities["asrImplementationSha256"], "U": identities["machineQcImplementationSha256"]}[stage]


def _report_group(store, payloads, group: dict, anchor: dict, policy: dict, context: dict, layer1: dict,
                  identities: dict, notes: dict | None = None) -> dict:
    """Status of every stage of one group, compared with the current inputs."""
    locale_identity = identities
    selected: dict[str, dict] = {}
    stages = {}
    conflicts = []
    view = group
    for stage in records.STAGES:
        found = store.records(policy["targetLocale"], group["translationGroupId"], stage)
        if stage == "C" and not found:
            stages[stage] = {"status": "not_applicable", "reasons": ["no_spoken_condensation_record"]}
            continue
        if not found:
            stages[stage] = {"status": "missing", "reasons": ["no_record"]}
            continue
        record = found[0]
        view = group
        if stage not in {"T", "R"}:
            if "R" not in selected:
                # Every stage after R reads its reviewed text; without it they cannot be judged.
                stages[stage] = {"status": "missing", "reasons": ["reviewed_text_missing"]}
                continue
            try:
                view = _reviewed_view(group, selected["R"], payloads)
            except ValueError:
                stages[stage] = {"status": "conflict", "reasons": ["reviewed_payload_missing"]}
                continue
        current = group_plan.current_inputs(stage, view, context, anchor, policy, locale_identity, selected, notes)
        if stage == "U":
            current["thresholdsSha256"] = identities["audioQcThresholdsSha256"]
        evaluated = []
        for candidate_record in found:
            result = group_plan.evaluate(candidate_record, layer1, current,
                                         _implementation(stage, identities))
            if stage in {"Q", "U"} and not candidate_record["provenance"].get("ledger"):
                result = dict(result, status="stale",
                              reasons=list(result["reasons"]) + ["repair_ledger_not_supplied"])
            evaluated.append((result, candidate_record))
        current_records = [item for item in evaluated if item[0]["status"] in {"fresh", "expected_reusable"}]
        if len(current_records) > 1:
            # Two records claim the current inputs; a redo must supersede, not compete.
            stages[stage] = {"status": "conflict", "reasons": ["multiple_current_records"],
                             "inputKeys": sorted(item[1]["inputKey"] for item in current_records)}
            conflicts.append(stage)
            continue
        result, record = (current_records[0] if current_records else
                          min(evaluated, key=lambda item: (item[0]["status"] != "stale",
                                                           item[0]["status"] != "failed")))
        stages[stage] = result
        if result["status"] in {"fresh", "expected_reusable"}:
            selected[stage] = record
    for stage in records.STAGES:
        if stages[stage]["status"] == "not_applicable":
            continue
        upstream = [up for up in records.UPSTREAM[stage] if up in records.PRODUCES
                    and stages[up]["status"] in UNSETTLED | {"unknown"} | {"conflict"}]
        if upstream and stages[stage]["status"] not in {"missing", "conflict"}:
            stages[stage] = dict(stages[stage], status="stale",
                                 reasons=list(stages[stage].get("reasons", []))
                                 + [f"upstream_will_change:{up}" for up in upstream])
    blockers = []
    for stage in WORKER_STAGES:
        if stages[stage]["status"] not in {"fresh", "expected_reusable"}:
            blockers.append({"stage": stage, "status": stages[stage]["status"]})
    return {"translationGroupId": group["translationGroupId"], "sourceUnitIds": group["sourceUnitIds"],
            "stages": stages, "conflicts": conflicts, "readyToMerge": not blockers, "blockers": blockers}


def _reviewed_view(group: dict, review: dict | None, payloads) -> dict:
    """The group with the reviewed text its R record names, for the stages after R."""
    if not review:
        return group
    sha = (review.get("outputs") or {}).get("evidenceRowSha256")
    if not sha:
        return group
    row = payloads.get(sha)
    return {**group, "targetUtterances": row["targetUtterances"],
            "targetText": "".join(row["targetUtterances"])}


L3_PREPARATION_SCHEMA = "sermon-group-l3-preparation-v1"


def prepare_l3(config: dict, *, text_basis: Path, adapter: Path, registry: Path,
               voice_authorization: Path | None = None, clip_authorization: bool = False,
               out: Path) -> dict:
    """Prepare the Layer 3 speech job for the current merge (merge steps 5-6).

    The text release basis and the voice authorization are operator-supplied receipts;
    this function does not create or upgrade either. The existing speech-job producer
    validates the candidate, policy, adapter and registry and writes an immutable job.
    Rendering, scheduling, screening and the listening waiver stay pending (steps 7-9).
    """
    from ..audio import speech_job
    directory = _current_merge_dir(config)
    candidate_path = directory / "candidate.json"
    _require(candidate_path.is_file(), "prepare_l3_needs_a_merged_candidate")
    out = Path(out)
    _require(not out.exists(), "prepare_l3_needs_a_new_output_directory")
    job = speech_job.prepare_job(
        config["source"], config["anchor"], candidate_path, config["policy"], Path(text_basis),
        Path(adapter), Path(registry), out,
        clip_voice_authorization_path=Path(voice_authorization) if voice_authorization and clip_authorization else None,
        source_voice_authorization_path=Path(voice_authorization) if voice_authorization and not clip_authorization else None,
    )
    job_path = out / "job.json"
    receipt = {
        "schemaVersion": L3_PREPARATION_SCHEMA, "targetLocale": config["locale"],
        "candidateSha256": legacy.file_sha256(candidate_path),
        "textReleaseBasisSha256": legacy.file_sha256(Path(text_basis)),
        "adapterSha256": legacy.file_sha256(Path(adapter)),
        "speechJobSha256": legacy.file_sha256(job_path),
        "speechJobPath": str(job_path), "speechJobStatus": job.get("status"),
        "pendingSteps": ["formal_render", "schedule_and_subtitles", "track_package",
                         "screening_and_audio_qc", "listening_waiver"],
        "releaseEligible": False, "humanApproval": False,
    }
    _write_once(out / "l3-preparation.json", (json.dumps(receipt, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    return receipt


def _directive_path(config: dict) -> Path:
    return Path(config["records"]) / DIRECTIVE_DIRECTORY / f"{config['locale']}.jsonl"


def load_directives(config: dict) -> dict[str, dict]:
    """The latest operator directive per group, as the T/R prompt receives it."""
    path = _directive_path(config)
    if not path.is_file():
        return {}
    latest: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        _require(row.get("schemaVersion") == DIRECTIVE_SCHEMA
                 and row.get("targetLocale") == config["locale"], "invalid_group_directive")
        _require(isinstance(row.get("translationGroupId"), str) and row["translationGroupId"]
                 and isinstance(row.get("priorTargetText"), str) and row["priorTargetText"]
                 and row.get("priorTargetTextSha256") == records.text_sha256(row["priorTargetText"])
                 and isinstance(row.get("note"), str) and row["note"].strip(), "invalid_group_directive")
        latest[row["translationGroupId"]] = {"priorTargetText": row["priorTargetText"],
                                             "priorTargetTextSha256": row["priorTargetTextSha256"],
                                             "note": row["note"]}
    return latest


def record_directive(config: dict, translation_group_id: str, prior_target_text: str, note: str) -> Path:
    """Append one operator directive; it is a revision instruction, never content approval."""
    _require(records.GROUP_ID.fullmatch(translation_group_id) is not None, "invalid_translation_group_id")
    _require(isinstance(note, str) and note.strip() and len(note) <= 2000, "invalid_directive_note")
    row = {"schemaVersion": DIRECTIVE_SCHEMA, "targetLocale": config["locale"],
           "translationGroupId": translation_group_id,
           "priorTargetText": prior_target_text,
           "priorTargetTextSha256": records.text_sha256(prior_target_text),
           "note": note.strip(), "createdAt": _now(), "operator": "cli",
           "humanApproval": False}
    path = _directive_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return path


def redo(config: dict, groups: list[str], reason: str, *, budget: dict | None,
         budget_sha256: str | None = None, caller=None, api_key: str = "") -> dict:
    """Record an operator reason for the named groups and run exactly those groups again."""
    _require(bool(groups), "redo_needs_group_ids")
    _require(isinstance(reason, str) and reason.strip(), "redo_needs_a_reason")
    candidate_path = _current_merge_dir(config) / "candidate.json"
    _require(candidate_path.is_file(), "redo_needs_a_merged_candidate")
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    by_id = {row["translationGroupId"]: row for row in candidate["groups"]}
    _require(set(groups) <= set(by_id), f"redo_names_unknown_group:{sorted(set(groups) - set(by_id))[:3]}")
    for group_id in groups:
        record_directive(config, group_id, "".join(by_id[group_id]["targetUtterances"]), reason)
    report = run(config, groups, budget=budget, budget_sha256=budget_sha256,
                 caller=caller, api_key=api_key)
    report["operatorDirective"] = {"groupIds": groups, "reason": reason.strip()}
    return report


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def status(config: dict) -> dict:
    """Read-only per-group stage status; no dispatch, no model call, no record write."""
    from ..text import candidate as producer
    from ..text import models
    source = legacy.load_json(config["source"])
    anchor = legacy.load_json(config["anchor"])
    policy = legacy.load_json(config["policy"])
    request = producer.prepare_request(source, anchor, policy)
    layer1 = records.layer1_identity(request["englishSourcePackageJsonSha256"], request["anchorManifestSha256"])
    groups = models.group_plan(request, anchor)
    contexts = legacy.group_contexts(anchor, groups)
    identities = stage_identities(config)
    store = records.RecordStore(config["records"])
    payloads = group_assembly.PayloadStore(config["records"])
    notes = load_directives(config)
    rows = [_report_group(store, payloads, group, anchor, policy, contexts[group["translationGroupId"]],
                          layer1, identities, notes) for group in groups]
    summary = {}
    for stage in records.STAGES:
        counts: dict[str, int] = {}
        for row in rows:
            value = row["stages"][stage]["status"]
            counts[value] = counts.get(value, 0) + 1
        summary[stage] = counts
    locale = policy["targetLocale"]
    return {"schemaVersion": STATUS_SCHEMA, "mode": "read_only", "dispatched": False, "modelCalls": 0,
            "targetLocale": locale, "layer1": layer1, "groupCount": len(rows), "summary": summary,
            "readyToMerge": all(row["readyToMerge"] for row in rows),
            "groups": rows, "releaseEligible": False, "humanApproval": False}


def run(config: dict, groups: list[str], *, budget: dict | None, budget_sha256: str | None = None,
        caller=None, api_key: str = "") -> dict:
    """Execute T, R and P for the named groups (or every group not ready to merge)."""
    from ..text import candidate as producer
    from ..text import models
    _require(caller is not None, "run_requires_a_model_caller")
    if budget is not None:
        _require(isinstance(budget, dict) and budget.get("schemaVersion") == group_budget.SCHEMA,
                 "invalid_group_budget")
    source = legacy.load_json(config["source"])
    anchor = legacy.load_json(config["anchor"])
    policy = legacy.load_json(config["policy"])
    request = producer.prepare_request(source, anchor, policy)
    layer1 = records.layer1_identity(request["englishSourcePackageJsonSha256"], request["anchorManifestSha256"])
    plan = models.group_plan(request, anchor)
    report = status(config)
    by_id = {row["translationGroupId"]: row for row in report["groups"]}
    _require(set(groups) <= set(by_id), f"unknown_group_id:{sorted(set(groups) - set(by_id))[:3]}")
    targets = groups or [row["translationGroupId"] for row in report["groups"] if not row["readyToMerge"]]
    results, stopped = [], None
    for group_id in targets:
        group = next(item for item in plan if item["translationGroupId"] == group_id)
        reservation = None
        if budget is not None:
            try:
                reservation = group_budget.admit(budget, group_id)
            except ValueError as exc:
                results.append({"group": group_id, "outcome": "refused", "reason": str(exc)})
                continue
        try:
            outcome = group_worker.run_group(config, group, source=source, anchor=anchor, policy=policy,
                                             request=request, caller=caller, api_key=api_key,
                                             note=load_directives(config).get(group_id))
            results.append({"group": group_id, "outcome": "pass", **outcome, "reservation": reservation})
        except group_worker.GroupWorkerError as exc:
            results.append({"group": group_id, "outcome": exc.kind, "detail": exc.detail,
                            "dispatched": exc.dispatched, "reservation": reservation})
            if exc.kind in {"unknown", "group_busy"}:
                stopped = exc.kind
                break
    final = status(config)
    return {"schemaVersion": RUN_SCHEMA, "mode": "execute", "targetLocale": policy["targetLocale"],
            "layer1": layer1, "requestedGroups": targets, "results": results, "stopped": stopped,
            "budgetSha256": budget_sha256, "status": final, "releaseEligible": False, "humanApproval": False}


def merge(config: dict, *, affected=()) -> dict:
    """Assemble the locale candidate from its group records and write the merge manifest.

    ``affected`` are the group IDs this revision was allowed to change (the operator's
    list plus groups the merge sent back). When a previous merge manifest exists, the
    set of groups whose records changed must equal it exactly: an unexpected change
    refuses the merge and names the extra groups (DEV-GRP-008).
    """
    from ..review import qc_text_run, text_qc
    from ..text import candidate as producer
    source = legacy.load_json(config["source"])
    anchor = legacy.load_json(config["anchor"])
    policy = legacy.load_json(config["policy"])
    request = producer.prepare_request(source, anchor, policy)
    locale = policy["targetLocale"]
    store = records.RecordStore(config["records"])
    payloads = group_assembly.PayloadStore(config["records"])
    resolutions = group_assembly.ResolutionStore(config["records"])
    try:
        assembled = group_assembly.assemble(source, anchor, policy, request, None, config["plugin"],
                                            store, payloads, resolutions=resolutions,
                                            notes=load_directives(config))
    except group_assembly.AssemblyRefused as exc:
        return {"schemaVersion": MERGE_SCHEMA, "targetLocale": locale, "outcome": "refused",
                "reasons": exc.reasons, "releaseEligible": False, "humanApproval": False}
    previous = _previous_manifest(config)
    # The first merge has nothing to compare with: every group is new, not "changed".
    changed = set() if previous is None else _changed_groups(previous, assembled["manifest"])
    if previous is not None and changed != set(affected):
        unexpected = sorted(changed - set(affected))
        missing = sorted(set(affected) - changed)
        return {"schemaVersion": MERGE_SCHEMA, "targetLocale": locale, "outcome": "refused",
                "reasons": {"changed_groups_not_affected": (unexpected or missing)},
                "changedGroupIds": sorted(changed), "affectedGroupIds": sorted(set(affected)),
                "unexpectedGroupIds": unexpected, "missingChangedGroupIds": missing,
                "releaseEligible": False, "humanApproval": False}
    candidate = assembled["candidate"]
    outliers = []
    rows = qc_text_run.qc_groups(candidate, anchor)
    median = text_qc.candidate_length_median(rows)
    for group in rows:
        problem = text_qc.length_problem(group, median)
        if problem:
            outliers.append({"translationGroupId": group["groupId"], "problem": problem})
    if outliers:
        return {"schemaVersion": MERGE_SCHEMA, "targetLocale": locale, "outcome": "refused",
                "reasons": {"text_length_outlier": [row["translationGroupId"] for row in outliers]},
                "outliers": outliers, "releaseEligible": False, "humanApproval": False}
    from ..audio import speech_job
    try:
        # Shape, locale and source-coverage check with the L3 producer's own validator.
        # It cannot approve: the candidate is still machine-review-pending.
        speech_job.validate_target_candidate(source, anchor, candidate, require_human_approval=False)
    except ValueError as exc:
        return {"schemaVersion": MERGE_SCHEMA, "targetLocale": locale, "outcome": "refused",
                "reasons": {"layer3_candidate_incompatible": [str(exc)]},
                "releaseEligible": False, "humanApproval": False}
    preflight = {"candidateShape": "pass", "textApproval": "pending_or_machine_waiver_required",
                 "speechJob": "not_prepared", "admissible": False,
                 "note": "shape check only; L3 still needs a text release basis and a prepared speech job"}
    directory = Path(config["merge"]) / locale / assembled["manifest"]["candidateSha256"][:16]
    _write_once(directory / "candidate.json", group_assembly.file_bytes(candidate))
    _write_once(directory / "evidence.json", group_assembly.file_bytes(assembled["evidence"]))
    _write_once(directory / "language-review.json", group_assembly.file_bytes(assembled["languageReview"]))
    manifest = {
        "schemaVersion": MERGE_SCHEMA, "targetLocale": locale, "layer1": assembled["manifest"]["layer1"],
        "translationPolicySha256": assembled["manifest"]["translationPolicySha256"],
        "groupCount": len(candidate["groups"]), "assembly": assembled["manifest"],
        "completedSteps": ["readiness", "candidate_assembly", "whole_text_checks"],
        "pendingSteps": list(PENDING_STEPS), "pendingReason": "Layer 3 merge steps are not wired in this adapter yet",
        "textLengthOutliers": [], "candidateSha256": assembled["manifest"]["candidateSha256"],
        "l3Handoff": L3_HANDOFF, "layer3Preflight": preflight,
        "changedGroupIds": sorted(changed), "affectedGroupIds": sorted(set(affected)),
        "releaseEligible": False, "humanApproval": False,
    }
    _validate_merge_manifest(manifest)
    data = (json.dumps(manifest, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    _write_once(directory / "merge-manifest.json", data)
    _write_pointer(directory.parent, directory)
    return {**manifest, "outcome": "candidate_ready_layer3_pending", "directory": str(directory)}


def _current_merge_dir(config: dict) -> Path:
    """The directory of the latest merge, from its content-addressed pointer."""
    root = Path(config["merge"]) / config["locale"]
    pointer = root / "current.json"
    if not pointer.is_file():
        return root / "unmerged"
    document = json.loads(pointer.read_text(encoding="utf-8"))
    _require(isinstance(document, dict) and isinstance(document.get("directory"), str),
             "invalid_merge_pointer")
    return root / document["directory"]


def _previous_manifest(config: dict) -> dict | None:
    path = _current_merge_dir(config) / "merge-manifest.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _group_record_hashes(assembly_manifest: dict) -> dict[str, str]:
    """One hash per group over the records the assembly actually used."""
    return {row["translationGroupId"]: records.json_sha256(row["records"])
            for row in (assembly_manifest or {}).get("groups") or []}


def _changed_groups(previous: dict | None, current: dict) -> set[str]:
    """Groups whose selected-record hashes differ from the previous merge (all on first)."""
    current_hashes = _group_record_hashes(current)
    if previous is None:
        return set(current_hashes)
    previous_hashes = _group_record_hashes((previous or {}).get("assembly") or {})
    return {group_id for group_id, sha in current_hashes.items() if previous_hashes.get(group_id) != sha}


def _write_pointer(root: Path, directory: Path) -> None:
    """Atomically point the locale at its latest content-addressed merge."""
    root.mkdir(parents=True, exist_ok=True)
    payload = {"schemaVersion": "sermon-group-merge-pointer-v1", "directory": directory.name}
    temporary = root / f".current.{os.getpid()}.tmp"
    temporary.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, root / "current.json")
    handle = os.open(root, os.O_RDONLY)
    try:
        os.fsync(handle)
    finally:
        os.close(handle)


def _validate_merge_manifest(manifest: dict) -> None:
    from jsonschema import Draft202012Validator
    from ..text import backend as _text
    schema = json.loads(_text.current().schemas.path(f"{MERGE_SCHEMA}.schema.json").read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(manifest))
    _require(not errors, f"invalid_merge_manifest:{errors[0].message if errors else ''}")


def _write_once(path: Path, data: bytes) -> None:
    group_assembly._write_once(path, data, f"merge_output_changed:{path}")


def _write_report(path: Path, report: dict) -> None:
    text = json.dumps(report, ensure_ascii=False, indent=1) + "\n"
    group_plan._write_new(path, text)


def text_summary(report: dict) -> str:
    locale = report.get("targetLocale")
    if report.get("schemaVersion") == STATUS_SCHEMA:
        lines = [f"Group status {locale}: {report['groupCount']} groups; ready to merge: {report['readyToMerge']}"]
        for stage in records.STAGES:
            counts = ", ".join(f"{status} {count}" for status, count in sorted(report["summary"][stage].items()))
            lines.append(f"  {stage} {records.STAGE_NAMES[stage]:<20} {counts}")
        for row in report["groups"]:
            if not row["readyToMerge"]:
                blockers = ", ".join(f"{item['stage']}={item['status']}" for item in row["blockers"])
                lines.append(f"  needs work: {row['translationGroupId']}  {blockers}")
        return "\n".join(lines)
    if report.get("schemaVersion") == RUN_SCHEMA:
        lines = [f"Group run {locale}: {len(report['results'])} attempted; stopped={report['stopped']}"]
        for row in report["results"]:
            lines.append(f"  {row['group']}: {row['outcome']}"
                         + (f" ({row.get('detail')})" if row.get("detail") else ""))
        lines.append(f"  after: ready to merge = {report['status']['readyToMerge']}")
        return "\n".join(lines)
    if report.get("schemaVersion") == MERGE_SCHEMA:
        if report.get("outcome") == "refused":
            return f"Merge {locale}: refused; {json.dumps(report.get('reasons'), ensure_ascii=False)}"
        return (f"Merge {locale}: candidate written for {report['groupCount']} groups\n"
                f"  pending Layer 3 steps: {', '.join(report['pendingSteps'])}\n"
                f"  handoff: {report['l3Handoff']}")
    return json.dumps(report, ensure_ascii=False)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    plan_command = sub.add_parser("plan", help="read-only per-group plan from run products (DEV-GRP-001)")
    plan_command.add_argument("rest", nargs=argparse.REMAINDER)
    status_command = sub.add_parser("status", help="per-group stage status from the record store")
    status_command.add_argument("--config", type=Path, required=True)
    status_command.add_argument("--output", type=Path)
    run_command = sub.add_parser("run", help="execute T, R and P for stale or listed groups")
    run_command.add_argument("--config", type=Path, required=True)
    run_command.add_argument("--group-id", nargs="+", default=[])
    run_command.add_argument("--budget", type=Path, help="sermon-group-budget-v1 document from plan --budget-profile")
    run_command.add_argument("--confirm-unbudgeted", action="store_true",
                             help="accept model spend without a per-group budget document (explicit operator decision)")
    run_command.add_argument("--output", type=Path)
    prepare_command = sub.add_parser("prepare-l3", help="prepare the Layer 3 speech job for the current merge")
    prepare_command.add_argument("--config", type=Path, required=True)
    prepare_command.add_argument("--text-release-basis", type=Path, required=True)
    prepare_command.add_argument("--adapter", type=Path, required=True)
    prepare_command.add_argument("--speaker-registry", type=Path, required=True)
    prepare_command.add_argument("--voice-authorization", type=Path)
    prepare_command.add_argument("--clip-authorization", action="store_true")
    prepare_command.add_argument("--out", type=Path, required=True)
    prepare_command.add_argument("--output", type=Path)
    redo_command = sub.add_parser("redo", help="record an operator reason and rerun exactly those groups")
    redo_command.add_argument("--config", type=Path, required=True)
    redo_command.add_argument("--group-id", nargs="+", required=True)
    redo_command.add_argument("--reason", required=True)
    redo_command.add_argument("--budget", type=Path)
    redo_command.add_argument("--confirm-unbudgeted", action="store_true")
    redo_command.add_argument("--output", type=Path)
    merge_command = sub.add_parser("merge", help="assemble the locale candidate from group records")
    merge_command.add_argument("--config", type=Path, required=True)
    merge_command.add_argument("--affected", nargs="+", default=[],
                               help="group IDs this revision may change; must equal the changed set")
    merge_command.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.command == "plan":
        return group_plan.main(args.rest)
    config = group_worker.load_configuration(args.config)
    if args.command == "status":
        report = status(config)
    elif args.command == "prepare-l3":
        report = prepare_l3(config, text_basis=args.text_release_basis, adapter=args.adapter,
                            registry=args.speaker_registry,
                            voice_authorization=args.voice_authorization,
                            clip_authorization=args.clip_authorization, out=args.out)
    elif args.command == "redo":
        if args.budget is None and not args.confirm_unbudgeted:
            parser.error("redo needs --budget <group budget> or --confirm-unbudgeted")
        budget = _read_budget(args.budget, config["locale"]) if args.budget else None
        budget_sha = legacy.file_sha256(args.budget) if args.budget else None
        caller, api_key = _openai_transport()
        report = redo(config, args.group_id, args.reason, budget=budget, budget_sha256=budget_sha,
                      caller=caller, api_key=api_key)
    elif args.command == "run":
        if args.budget is None and not args.confirm_unbudgeted:
            parser.error("run needs --budget <group budget> or --confirm-unbudgeted")
        budget = _read_budget(args.budget, config["locale"]) if args.budget else None
        budget_sha = legacy.file_sha256(args.budget) if args.budget else None
        caller, api_key = _openai_transport()
        report = run(config, args.group_id, budget=budget, budget_sha256=budget_sha,
                     caller=caller, api_key=api_key)
    else:
        report = merge(config, affected=args.affected)
    if args.output:
        _write_report(args.output, report)
    print(text_summary(report))
    return 0 if report.get("outcome") != "refused" else 4


def _read_budget(path: Path, locale: str) -> dict:
    """A group budget document, or the budget block of a ``plan`` report."""
    document = legacy.load_json(path)
    if document.get("schemaVersion") == group_budget.SCHEMA:
        return document
    budget = ((document.get("locales") or {}).get(locale) or {}).get("budget")
    _require(isinstance(budget, dict), f"budget_document_has_no_locale:{locale}")
    return budget


def _openai_transport() -> tuple:
    from ..text import backend as _text
    from ..text import models
    transport = _text.current().transports.caller("openai-api")
    return models._session_bound_caller()(transport, requires_spark=False), transport.key


if __name__ == "__main__":
    sys.exit(main())
