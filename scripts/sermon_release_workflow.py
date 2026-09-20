"""Evidence-driven continuation from Saturday production to verified web release.

Configuration is operator-owned JSON, never a model-supplied command. All model
and deployment execution uses existing validators and fixed repository CLIs.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import date
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.sermon_execution_harness import atomic_json, bounded_process, work_lock, utc_now

ROOT = Path(__file__).resolve().parents[1]
POC = ROOT / "experiments/sermon-dubbing-poc"
SCHEMA = "sermon-release-workflow-v1"
ACTIONS = frozenset({"generate_audio_candidate", "sync_audio", "build_page", "prepare_release", "deploy_release", "verify_release", "record_published"})
PATHS = ("bridgeConfig", "work", "candidate", "release", "registry", "stateDir", "authorization")


def read(path):
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _module(name):
    if str(POC) not in sys.path:
        sys.path.insert(0, str(POC))
    return importlib.import_module(name)


def _week(value):
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value or parsed.weekday() != 6:
        raise ValueError("sunday must be an ISO Sunday date")
    return value


def _safe_path(path, *, recursive=False):
    """Reject redirected config/output paths, allowing macOS system aliases."""
    path = Path(os.path.abspath(Path(path).expanduser()))
    aliases = {Path('/var'): Path('/private/var'), Path('/tmp'): Path('/private/tmp'), Path('/etc'): Path('/private/etc')}
    for item in (path, *path.parents):
        if item.is_symlink() and not (item in aliases and item.resolve() == aliases[item]):
            raise ValueError("Symlink configuration/output paths are not supported")
    if recursive and path.is_dir() and any(item.is_symlink() for item in path.rglob('*')):
        raise ValueError("Symlink entries in workflow outputs are not supported")
    return path.resolve()


def load_config(path):
    path = _safe_path(path)
    config = read(path)
    if set(config) != {"schemaVersion", "weeks"} or config["schemaVersion"] != SCHEMA or not isinstance(config["weeks"], dict):
        raise ValueError("Invalid release workflow configuration")
    result = {"schemaVersion": SCHEMA, "configPath": str(path), "configSha256": digest(path), "weeks": {}}
    for week, original in config["weeks"].items():
        _week(week)
        if not isinstance(original, dict) or set(original) - set(PATHS) - {"project", "site", "origin", "replacePages", "series"}:
            raise ValueError("Unknown weekly configuration fields")
        row = dict(original)
        for key in PATHS:
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError(f"Missing explicit {key} path")
            target = Path(row[key]).expanduser()
            row[key] = str(_safe_path(target if target.is_absolute() else path.parent / target, recursive=key in {"work", "candidate", "release", "registry", "stateDir"}))
        outputs = [Path(row[k]) for k in ("work", "candidate", "release", "registry", "stateDir")]
        if any(a == b or a.is_relative_to(b) or b.is_relative_to(a) for i, a in enumerate(outputs) for b in outputs[i + 1:]):
            raise ValueError("Work, build, release, registry and state paths must be separate")
        for key in ("project", "site"):
            if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", str(row.get(key, ""))):
                raise ValueError(f"Invalid Firebase {key}")
        if row["project"] == row["site"]:
            raise ValueError("A dedicated Firebase site is required")
        origin = urlsplit(row.get("origin", ""))
        if origin.scheme != "https" or not origin.hostname or origin.username or origin.password or origin.path or origin.query or origin.fragment or origin.port:
            raise ValueError("origin must be a canonical HTTPS origin")
        # A custom domain requires an independently verified mapping, which this
        # first adapter does not yet support.
        if row["origin"] != f'https://{row["site"]}.web.app':
            raise ValueError("origin must match the dedicated Firebase site")
        if not isinstance(row.get("replacePages", []), list) or any(not isinstance(x, str) or not x for x in row.get("replacePages", [])):
            raise ValueError("replacePages must be explicit page IDs")
        if "series" in row and (not isinstance(row["series"], str) or not row["series"].strip()):
            raise ValueError("series must be nonempty text")
        result["weeks"][week] = row
    return result


def _settings(config, sunday):
    _week(sunday)
    if sunday not in config["weeks"]:
        raise ValueError("Sunday is not explicitly configured")
    return config["weeks"][sunday]


def _binding(config, sunday, settings):
    return {"configSha256": config["configSha256"], "sunday": sunday,
            "bridgeConfigSha256": digest(settings["bridgeConfig"])}


def _command(settings, sunday, action):
    work, candidate, release, registry = (settings[k] for k in ("work", "candidate", "release", "registry"))
    commands = {
        "generate_audio_candidate": ["continue_saturday_dubbing.py", "--config", settings["bridgeConfig"], "--week", sunday, "--execute"],
        "sync_audio": ["check_weekly_timing.py", "--work", work, "--assemble"],
        "build_page": ["build_weekly_app.py", "--weekly-job", work, "--out", candidate],
        "prepare_release": ["weekly_release.py", "prepare", "--registry", registry, "--candidate", candidate, "--out", release],
        "deploy_release": ["deploy_firebase.py", "--release", release, "--project", settings["project"], "--site", settings["site"], "--execute"],
        "verify_release": ["verify_weekly_release.py", "--release", release, "--origin", settings["origin"], "--out", str(Path(release) / "http-verification.json")],
        "record_published": ["weekly_release.py", "record-published", "--registry", registry, "--release", release, "--verification", str(Path(release) / "http-verification.json")],
    }
    command = commands[action]
    if action == "build_page" and settings.get("series"):
        command += ["--series", settings["series"]]
    if action == "prepare_release":
        for page in settings.get("replacePages", []):
            command += ["--replace-page", page]
    return [sys.executable, str(POC / command[0]), *command[1:]]


def _review(work, job):
    path = work / "audio-review-synced.json"
    if not path.exists():
        return False
    receipt = read(path)
    checks = {"speakerIdentity", "voiceSimilarity", "chineseFluency", "pronunciation", "noOmissionOrRepetition", "sameVideoSynchronization"}
    return (receipt.get("humanApproval") is True and bool(receipt.get("reviewedBy")) and bool(receipt.get("reviewedAt"))
            and receipt.get("jobSha256") == digest(work / "job.json")
            and receipt.get("mp3Sha256") == digest(work / "synchronization/zh-synced.mp3")
            and receipt.get("checkpointSha256") == job["voice"]["checkpointSha256"]
            and set(receipt.get("checks", {})) == checks and all(v == "pass" for v in receipt["checks"].values()))


def _audio_binding(work, job):
    return {"jobSha256": digest(work / "job.json"), "reviewSha256": digest(work / "audio-review-synced.json"),
            "audioSha256": digest(work / "synchronization/zh-synced.mp3"),
            "assemblySha256": digest(work / "synchronization/assembly.json"),
            "timingSha256": digest(work / "synchronization/report.json")}


def _authorization(config, sunday, settings, state, plan):
    expected = {"schemaVersion": "sermon-release-authorization-v1", "decision": "approved", "sunday": sunday,
                "configSha256": config["configSha256"], "project": settings["project"], "site": settings["site"],
                "origin": settings["origin"], "buildReportSha256": digest(Path(settings["release"]) / "build-report.json"),
                "parentReleaseId": plan["parentReleaseId"], "parentGeneration": plan["parentGeneration"]}
    path = Path(settings["authorization"])
    if not path.exists():
        return False, expected
    actual = read(path)
    return (all(actual.get(k) == v for k, v in expected.items()) and bool(actual.get("approvedBy")) and bool(actual.get("approvedAt"))), expected


def _snapshot(config, sunday):
    settings = _settings(config, sunday)
    result = {"schemaVersion": "sermon-release-workflow-state-v1", "sunday": sunday, "configSha256": config["configSha256"],
              "status": "pending", "evidence": {}, "blockers": [], "humanActionRequired": False}
    def stop(action, reason, human=False):
        result.update(status=action, humanActionRequired=human, recommendedAction={"action": action, "reason": reason, "humanActionRequired": human})
        if human:
            result["blockers"].append(reason)
        return result
    binding = _binding(config, sunday, settings)
    state_dir, work = Path(settings["stateDir"]), Path(settings["work"])
    for action in ACTIONS:
        receipt_path = state_dir / f"{action}.json"
        if receipt_path.exists():
            receipt = read(receipt_path)
            if receipt.get("binding") != binding:
                raise ValueError("Existing workflow receipt belongs to changed inputs/configuration")
            if receipt.get("status") != "succeeded":
                return stop("waiting_outcome_reconciliation", f"{action} has an uncertain or failed previous attempt; inspect its log and artifacts", True)
    bridge, plan = _module("continue_saturday_dubbing").inspect_bridge(settings["bridgeConfig"], sunday)
    result["evidence"]["bridgeStatus"] = bridge["status"]
    if plan is None:
        return stop("waiting_source_or_voice", "Restore the bridge's required source, metadata, or voice evidence", True)
    result["evidence"].update(sourceRunRoot=str(Path(plan["run"]).resolve()), sourceId=plan["sourceId"], work=str(work))
    if Path(plan["work"]).resolve() != work:
        raise ValueError("Configured work does not match the current bridge source plan")
    if bridge["status"] in {"ready_to_prepare", "ready_to_resume"}:
        return stop("generate_audio_candidate", "Generate or resume the current source-bound audio candidate")
    if bridge["status"] != "waiting_conversation_review":
        return stop("waiting_evidence_repair", "Bridge candidate evidence is not ready", True)
    job = read(work / "job.json")
    if job.get("week") != sunday:
        raise ValueError("Audio job week differs from configured Sunday")
    _module("weekly_dubbing").validate_frozen(job)
    _module("run_weekly_dubbing").validate_candidate(work)
    if not (work / "synchronization/assembly.json").exists():
        timing = read(work / "synchronization/report.json")
        if timing.get("status") != "natural_timing_fits" or timing.get("failures") != []:
            return stop("waiting_timing_review", "Review anchors and repair timing before synchronized assembly", True)
        return stop("sync_audio", "Assemble synchronized audio from validated anchors and timing")
    _module("build_weekly_app").synchronized_candidate(work, job)
    if not _review(work, job):
        return stop("waiting_audio_review", "A current human listening and same-video synchronization review is required", True)
    _module("weekly_dubbing").validate_review(work, write_receipt=False)
    audio_binding = _audio_binding(work, job)
    candidate, release, registry = (Path(settings[k]) for k in ("candidate", "release", "registry"))
    if not candidate.exists():
        return stop("build_page", "Build the reviewed weekly page with existing complete review validators")
    build_receipt = read(state_dir / "build_page.json")
    if build_receipt.get("audioBinding") != audio_binding or build_receipt.get("outputSha256") != digest(candidate / "build-report.json"):
        raise ValueError("Page build inputs or output changed; use a fresh candidate and state directory")
    releases = _module("weekly_release")
    releases.read_release(candidate)
    state, _, _, _ = releases.load_registry(registry)
    if state["origin"] != settings["origin"]:
        raise ValueError("Registry origin differs from configured deployment")
    if not release.exists():
        return stop("prepare_release", "Merge the candidate into the current registered page history")
    report, _ = releases.read_release(release)
    plan = read(release / "release-plan.json")
    if plan.get("releaseId") != releases.release_id(report) or plan.get("buildReportSha256") != digest(release / "build-report.json") or plan.get("origin") != settings["origin"]:
        raise ValueError("Release plan does not match release content/origin")
    if report.get("releaseRegistry", {}).get("candidateBuildReportSha256") != digest(candidate / "build-report.json"):
        raise ValueError("Release no longer binds this candidate")
    verification_path = release / "http-verification.json"
    if state["head"] == plan["releaseId"]:
        releases.check_verification(release, read(verification_path), settings["origin"])
        if state["history"][-1]["status"] != "published_http_verified":
            raise ValueError("Registry head is not a verified publication")
        return stop("complete", "Published release is registered with matching HTTP verification; device acceptance remains separate")
    if state["head"] != plan["parentReleaseId"] or state["generation"] != plan["parentGeneration"]:
        raise ValueError("Registry advanced; prepare a fresh release against its current head")
    deployment = release / "deployment-receipt.json"
    deployed = read(deployment) if deployment.exists() else None
    if deployed is not None:
        expected_target = {"projectId": settings["project"], "siteId": settings["site"],
                           "buildReportSha256": digest(release / "build-report.json")}
        if (any(deployed.get(k) != v for k, v in expected_target.items())
                or deployed.get("status") not in {"validated_not_deployed", "deployed_http_verification_pending"}):
            raise ValueError("Deployment receipt does not bind this release and target")
    # The Firebase CLI writes a receipt for preflight too. It is evidence of
    # validation only; require the same exact authorization before deployment.
    if deployed is None or deployed["status"] == "validated_not_deployed":
        authorized, expected = _authorization(config, sunday, settings, state, plan)
        result["evidence"]["requiredReleaseAuthorization"] = expected
        if not authorized:
            return stop("waiting_release_authorization", "Approve the exact prepared release and dedicated Firebase target", True)
        return stop("deploy_release", "Deploy the explicitly authorized immutable release")
    if not verification_path.exists() or read(verification_path).get("passed") is not True:
        return stop("verify_release", "Verify all public files and audio ranges against the release manifest")
    releases.check_verification(release, read(verification_path), settings["origin"])
    return stop("record_published", "Record the HTTP-verified release in the publication registry")


def snapshot(config_path, sunday):
    config = load_config(config_path)
    _settings(config, sunday)
    try:
        return _snapshot(config, sunday)
    except (ValueError, KeyError, OSError, TypeError) as exc:
        # No CLI output, secret material, or unbounded subprocess diagnostics.
        return {"schemaVersion": "sermon-release-workflow-state-v1", "sunday": sunday, "status": "waiting_evidence_repair",
                "humanActionRequired": True, "blockers": [str(exc)], "evidence": {},
                "recommendedAction": {"action": "waiting_evidence_repair", "humanActionRequired": True, "reason": str(exc)}}


def execute(config_path, sunday, action, *, expected_source_run_root=None, expected_config_sha=None):
    if action not in ACTIONS:
        raise ValueError("Unsupported release action")
    config = load_config(config_path)
    if expected_config_sha and config["configSha256"] != expected_config_sha:
        raise ValueError("Workflow configuration changed since dispatch")
    settings = _settings(config, sunday)
    state_dir = Path(settings["stateDir"])
    with ExitStack() as stack:
        stack.enter_context(work_lock(state_dir))
        if action in {"build_page", "prepare_release", "sync_audio", "deploy_release", "verify_release", "record_published"}:
            target = {"build_page": "candidate", "sync_audio": "work"}.get(action, "release")
            stack.enter_context(work_lock(Path(settings[target])))
        if action == "deploy_release":
            stack.enter_context(_module("weekly_release").registry_lock(Path(settings["registry"])))
        fresh_config = load_config(config_path)
        if fresh_config != config:
            raise ValueError("Workflow configuration changed while acquiring locks")
        current = _snapshot(config, sunday)
        if expected_source_run_root:
            observed = current.get("evidence", {}).get("sourceRunRoot")
            if not observed or Path(observed).resolve() != Path(expected_source_run_root).resolve():
                raise ValueError("Release source differs from dispatched production source")
        if current["recommendedAction"]["action"] != action:
            return {"executed": False, "snapshot": current}
        receipt_path = state_dir / f"{action}.json"
        receipt = {"schemaVersion": "sermon-release-action-v1", "action": action, "binding": _binding(config, sunday, settings),
                   "status": "running", "startedAt": utc_now()}
        if action == "build_page":
            receipt["audioBinding"] = _audio_binding(Path(settings["work"]), read(Path(settings["work"]) / "job.json"))
        atomic_json(receipt_path, receipt)
        try:
            with (state_dir / f"{action}.log").open("w") as log:
                bounded_process(_command(settings, sunday, action), timeout=21600 if action == "generate_audio_candidate" else 3600,
                                cwd=ROOT, check=True, stdout=log, stderr=-2)
            if action == "build_page":
                _module("weekly_release").read_release(Path(settings["candidate"]))
                receipt["outputSha256"] = digest(Path(settings["candidate"]) / "build-report.json")
            receipt.update(status="succeeded", completedAt=utc_now())
            atomic_json(receipt_path, receipt)
            after = _snapshot(config, sunday)
            if after["recommendedAction"]["action"] == action:
                raise ValueError("Command returned without advancing validated evidence")
            return {"executed": True, "action": action, "snapshot": after}
        except BaseException:
            receipt.update(status="outcome_unknown", completedAt=utc_now())
            atomic_json(receipt_path, receipt)
            raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--sunday", required=True)
    parser.add_argument("--action", choices=sorted(ACTIONS))
    parser.add_argument("--expected-config-sha")
    parser.add_argument("--expected-source-run-root")
    args = parser.parse_args(argv)
    if args.expected_config_sha and digest(Path(args.config)) != args.expected_config_sha:
        raise ValueError("Workflow configuration changed since dispatch")
    result = (execute(args.config, args.sunday, args.action,
                      expected_source_run_root=args.expected_source_run_root,
                      expected_config_sha=args.expected_config_sha)
              if args.action else snapshot(args.config, args.sunday))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
