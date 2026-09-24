#!/usr/bin/env python3
"""Run the existing immutable Dev or Production Hosting release gates in order.

This operator entrypoint keeps code promotion separate from content deployment.
Without --execute it checks the live baseline and writes a deployment plan only.
"""

from __future__ import annotations

import argparse
import fcntl
import json
from pathlib import Path
import subprocess
import sys

try:
    from scripts import assemble_multilingual_hosting as hosting
except ImportError:
    import assemble_multilingual_hosting as hosting


ROOT = Path(__file__).resolve().parents[1]
MODES = {
    "dev": {"branch": "dev", "script": ROOT / "scripts/multilingual_dev_preview.py",
            "schema": {"sermon-multilingual-dev-preview-v1", "sermon-multilingual-dev-preview-v2",
                       "sermon-multilingual-dev-preview-v3"}},
    "production": {"branch": "main", "script": ROOT / "scripts/deploy_multilingual_hosting.py",
                   "schema": {"sermon-multilingual-hosting-candidate-v1"}},
}


def git_value(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def require_release_checkout(mode: str, expected_commit: str) -> str:
    actual = git_value("rev-parse", "HEAD")
    branch = git_value("branch", "--show-current")
    if (branch != MODES[mode]["branch"] or actual != expected_commit
            or git_value("status", "--porcelain", "--untracked-files=no")):
        raise ValueError(f"{mode} deployment requires a clean {MODES[mode]['branch']} checkout at the selected commit")
    remote = git_value("ls-remote", "--exit-code", "origin",
                       f"refs/heads/{MODES[mode]['branch']}").split()
    if not remote or remote[0] != actual:
        raise ValueError("Selected deployment commit differs from the remote protected branch")
    return actual


def run_command(*args: str) -> None:
    subprocess.run([sys.executable, *map(str, args)], cwd=ROOT, check=True)


def release(mode: str, candidate: Path, out: Path, *, execute: bool,
            expected_commit: str | None = None,
            expected_build_report_sha256: str | None = None,
            legacy_release: Path | None = None) -> dict:
    if mode not in MODES:
        raise ValueError("Unknown deployment environment")
    candidate, out = candidate.resolve(), out.resolve()
    legacy_release = legacy_release.resolve() if legacy_release is not None else None
    if out.exists() or out.is_symlink():
        raise ValueError("Use a new CD receipt directory")
    if candidate.resolve() == out.resolve() or out.resolve().is_relative_to(candidate.resolve()):
        raise ValueError("CD receipts must be outside the candidate")
    report_path = candidate / "build-report.json"
    report = hosting.load(report_path)
    if (report.get("schemaVersion") not in MODES[mode]["schema"]
            or report.get("status") != "validated_not_deployed"):
        raise ValueError("Candidate does not match the selected environment")
    build_sha = hosting.digest(report_path)
    if expected_build_report_sha256 and build_sha != expected_build_report_sha256:
        raise ValueError("Selected candidate build report changed")
    legacy_feedback = None
    if report.get("legacyWeeklyReleaseBuildReportSha256"):
        if mode != "production" or legacy_release is None:
            raise ValueError("Updated legacy week requires its bound release for feedback deployment")
        if hosting.digest(legacy_release / "build-report.json") != report[
                "legacyWeeklyReleaseBuildReportSha256"]:
            raise ValueError("Legacy weekly release differs from the Hosting candidate")
        if report.get("feedbackEnabled"):
            if (not (candidate / "feedback-catalog.json").is_file()
                    or hosting.digest(candidate / "feedback-catalog.json") != report.get(
                        "feedbackCatalogSha256")
                    or hosting.digest(legacy_release / "feedback-catalog.json") != report.get(
                        "feedbackCatalogSha256")):
                raise ValueError("Feedback catalog differs from the reviewed legacy release")
            legacy_feedback = legacy_release
    elif legacy_release is not None:
        raise ValueError("Candidate does not include the selected legacy weekly release")
    code_sha = git_value("rev-parse", "HEAD")
    if execute:
        if not expected_commit or not expected_build_report_sha256:
            raise ValueError("Execution requires explicit code and candidate hashes")
        code_sha = require_release_checkout(mode, expected_commit)
    out.mkdir(parents=True)
    lock_path = out.parent / f".sermon-multilingual-{mode}-deploy.lock"
    try:
        with lock_path.open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            preflight = out / "preflight.json"
            deployment = out / "deployment.json"
            verification = out / "http-verification.json"
            if mode == "dev":
                tool = str(MODES[mode]["script"])
                run_command(tool, "preflight", "--candidate", str(candidate), "--out", str(preflight))
                args = [tool, "deploy", "--candidate", str(candidate),
                        "--preflight", str(preflight), "--out", str(deployment)]
                verify_args = [tool, "verify", "--candidate", str(candidate),
                               "--out", str(verification)]
            else:
                tool = str(MODES[mode]["script"])
                run_command(str(ROOT / "scripts/verify_multilingual_hosting.py"),
                            "--candidate", str(candidate),
                            "--origin", "https://ai-for-god-sermon-audio.web.app",
                            "--preflight-baseline", "--out", str(preflight))
                args = [tool, "--candidate", str(candidate),
                        "--preflight", str(preflight), "--out", str(deployment)]
                verify_args = [str(ROOT / "scripts/verify_multilingual_hosting.py"),
                               "--candidate", str(candidate),
                               "--origin", "https://ai-for-god-sermon-audio.web.app",
                               "--out", str(verification)]
            if execute:
                args.append("--execute")
            if legacy_feedback is not None:
                feedback_args = [str(ROOT / "experiments/sermon-dubbing-poc/deploy_feedback.py"),
                                 "--release", str(legacy_feedback),
                                 "--out", str(out / "feedback-api")]
                if execute:
                    feedback_args.append("--execute")
                run_command(*feedback_args)
                feedback_receipt = hosting.load(out / "feedback-api/deployment-receipt.json")
                if feedback_receipt.get("status") != (
                        "deployed_verification_pending" if execute else "prepared_not_deployed"):
                    raise ValueError("Feedback API did not reach the expected deployment state")
            run_command(*args)
            preflight_receipt = hosting.load(preflight)
            deployment_receipt = hosting.load(deployment)
            if (preflight_receipt.get("status") != "pass"
                    or preflight_receipt.get("buildReportSha256") != build_sha
                    or deployment_receipt.get("status") != (
                        "deployed_http_verification_pending" if execute else "validated_not_deployed")
                    or deployment_receipt.get("buildReportSha256") != build_sha
                    or deployment_receipt.get("preflightSha256") != hosting.digest(preflight)):
                raise ValueError("Preflight or deployment receipt does not bind the candidate")
            if execute:
                run_command(*verify_args)
                verification_receipt = hosting.load(verification)
                if (verification_receipt.get("status") != "pass"
                        or verification_receipt.get("buildReportSha256") != build_sha):
                    raise ValueError("HTTP verification did not confirm the deployed candidate")
            result = {
                "schemaVersion": "sermon-multilingual-cd-receipt-v1",
                "environment": mode,
                "status": "published_http_verified" if execute else "validated_not_deployed",
                "codeCommitSha": code_sha,
                "buildReportSha256": build_sha,
                "preflightSha256": hosting.digest(preflight),
                "deploymentSha256": hosting.digest(deployment),
                "httpVerificationSha256": hosting.digest(verification) if execute else None,
                "feedbackDeploymentStatus": (
                    "deployed_verification_pending" if execute else "prepared_not_deployed"
                ) if legacy_feedback is not None else "unchanged",
                "deviceAcceptance": "not_run", "venueAcceptance": "not_run",
            }
            (out / "cd-receipt.json").write_text(
                json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                encoding="utf-8")
            return result
    except Exception:
        # Keep preflight/deployment receipts if publication or verification failed.
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=sorted(MODES), required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--expected-commit")
    parser.add_argument("--expected-build-report-sha256")
    parser.add_argument("--legacy-release", type=Path,
                        help="Required when the candidate incorporates a new legacy week")
    args = parser.parse_args()
    result = release(args.mode, args.candidate, args.out, execute=args.execute,
                     expected_commit=args.expected_commit,
                     expected_build_report_sha256=args.expected_build_report_sha256,
                     legacy_release=args.legacy_release)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
