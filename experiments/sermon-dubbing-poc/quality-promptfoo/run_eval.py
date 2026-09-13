"""Execute the pinned local Promptfoo provider/assertion under a network deny sandbox."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

HERE = Path(__file__).resolve().parent
POC = HERE.parent
ROOT = POC.parents[1]
sys.path.insert(0, str(POC))
from quality_harness import compare


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    path.chmod(0o600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("suite", "baseline", "candidate"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--media-work", type=Path, help="Also decode and recheck existing production audio/timing; never synthesize")
    args = parser.parse_args()
    # Resolve the installed bin through package metadata rather than assume its layout.
    package = json.loads((HERE / "node_modules" / "promptfoo" / "package.json").read_text())
    locked = json.loads((HERE / "package.json").read_text())["dependencies"]["promptfoo"]
    if package["version"] != locked:
        parser.error("Installed Promptfoo differs from package.json; run npm ci in quality-promptfoo")
    binary = package["bin"]
    binary = binary["promptfoo"] if isinstance(binary, dict) else binary
    cli = HERE / "node_modules" / "promptfoo" / binary
    sandbox = Path("/usr/bin/sandbox-exec")
    if sys.platform != "darwin" or not sandbox.is_file():
        parser.error("This verified launcher requires macOS sandbox-exec to deny network access")
    node = shutil.which("node")
    if not node:
        parser.error("Node.js is required")
    out = args.out_dir or ROOT / "artifacts" / "saturday-quality" / "runs" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
    out = out.resolve()
    if args.media_work:
        candidate = json.loads(args.candidate.read_text())
        expected_job = candidate.get("jobEvidence") or candidate.get("evidence", {}).get("job", {})
        if expected_job.get("sha256") != sha(args.media_work / "job.json"):
            parser.error("Media job must be hash-bound to the candidate being evaluated")
        if out.is_relative_to(args.media_work.resolve()):
            parser.error("Write evaluation output outside the original production job")
    if out.exists() and any(out.iterdir()):
        parser.error("Use a new or empty output directory; existing evidence is preserved")
    # Compute before writing anything; malformed or differently bound inputs fail closed.
    comparison = compare(args.suite.resolve(), args.baseline.resolve(), args.candidate.resolve())
    out.mkdir(parents=True, exist_ok=True)
    write(out / "comparison.json", comparison)
    config = {"description": "Saturday local saved-output quality regression", "sharing": False,
              "prompts": ["Evaluate the frozen local comparison report; no model inference"],
              "providers": [{"id": "file://" + str(HERE / "saved-report-provider.cjs"),
                             "config": {"reportPath": str(out / "comparison.json"), "reportSha256": sha(out / "comparison.json")}}],
              "tests": [{"description": "Frozen baseline and candidate satisfy deterministic constraints",
                         "assert": [{"type": "javascript", "value": "file://" + str(HERE / "report-assertion.cjs")}]}]}
    write(out / "promptfoo-config.json", config)
    # Do not inherit provider credentials or cloud settings. Leave the user's HOME unchanged.
    env = {key: value for key, value in os.environ.items() if key in {"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "SYSTEMROOT"}}
    env.update(PROMPTFOO_DISABLE_TELEMETRY="1", PROMPTFOO_DISABLE_UPDATE="1", PROMPTFOO_CONFIG_DIR=str(out / "promptfoo-state"),
               PROMPTFOO_CACHE_ENABLED="false", PROMPTFOO_NO_SAVE="1", CI="1")
    command = [str(sandbox), "-p", "(version 1) (allow default) (deny network*)", node, str(cli), "eval",
               "--config", str(out / "promptfoo-config.json"), "--output", str(out / "promptfoo-results.json"),
               "--no-cache", "--no-write", "--no-share", "--no-progress-bar", "--no-table", "--max-concurrency", "1"]
    completed = subprocess.run(command, cwd=out, env=env, capture_output=True, text=True, timeout=120)
    (out / "promptfoo.log").write_text(completed.stdout + completed.stderr, encoding="utf-8")
    media = None
    if args.media_work:
        from media_check import check_media
        media = check_media(args.media_work.resolve())
        write(out / "media-check.json", media)
    result_file = out / "promptfoo-results.json"
    result = json.loads(result_file.read_text()) if result_file.exists() else {}
    rows = result.get("results", {}).get("results", [])
    stats = result.get("results", {}).get("stats", {})
    executed = (len(rows) == 1 and rows[0].get("provider", {}).get("id") == "sermon-local-saved-report-v1"
                and rows[0].get("response", {}).get("metadata", {}).get("localProviderExecuted") is True
                and len(rows[0].get("gradingResult", {}).get("componentResults", [])) == 1
                and stats.get("errors") == 0 and stats.get("successes", 0) + stats.get("failures", 0) == 1)
    report = {"schemaVersion": "sermon-promptfoo-local-run-v1", "promptfooVersion": package["version"],
              "packageLockSha256": sha(HERE / "package-lock.json"), "comparisonSha256": sha(out / "comparison.json"),
              "promptfooExitCode": completed.returncode, "promptfooStats": stats, "localProviderAndAssertionExecuted": executed,
              "networkPolicy": "macos_sandbox_deny_network", "telemetryEnabled": False, "cloudSharingEnabled": False,
              "mediaStatus": None if media is None else media["status"], "humanAcceptance": "not_evaluated"}
    passed = executed and stats.get("successes") == 1 and completed.returncode == 0 and comparison["passed"] and (media is None or media["status"] == "pass")
    report["passed"] = passed
    write(out / "run-receipt.json", report)
    print(json.dumps({"passed": passed, "promptfooExitCode": completed.returncode, "outDir": str(out)}, ensure_ascii=False))
    if completed.returncode not in (0, 100) or not executed:
        return 2
    return 0 if passed else 1


if __name__ == "__main__":
    try:
        code = main()
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"passed": False, "inputErrorType": type(exc).__name__}))
        code = 2
    sys.exit(code)
