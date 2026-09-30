"""Collect repeatable Stage 0 component evidence, never human sign-off.

Only the fixed local/synthetic suites below run. Fixed Layer 2 admission exists,
but the full canonical workflow remains incomplete: green cannot promote Stage 1.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import evaluate_backend_four_layer_dry_run as backend
from scripts import pipeline_compatibility_gate as compatibility

ROOT = Path(__file__).resolve().parents[1]
SUITES = {
    'canonical_packages': ('tests.test_inspect_canonical_packages', 'tests.test_inspect_canonical_audio',
                           'tests.test_inspect_canonical_release', 'tests.test_canonical_pipeline_definition',
                           'tests.test_canonical_durable_jobs', 'tests.test_canonical_layer2_controller',
                           'tests.test_canonical_layer2_reconciliation', 'tests.test_canonical_layer2_cache_recovery'),
    'bounded_decision': ('tests.test_sermon_bounded_decision', 'tests.test_sermon_decision_budget',
                         'tests.test_sermon_decision_accounting'),
    'legacy_controller_reliability': ('tests.test_sermon_deterministic_controller', 'tests.test_controller_crash_windows',
                                      'tests.test_sermon_workflow_jobs', 'tests.test_sermon_job_liveness'),
    'accounting': ('tests.test_sermon_accounting', 'tests.test_accounting_retry_safety',
                   'tests.test_accounting_observability', 'tests.test_weekly_pipeline_report'),
    'release_asset_assembly': ('tests.test_release_asset_io', 'tests.test_backend_four_layer_dry_run',
                               'tests.test_firebase_dev_weekly_dry_run', 'tests.test_build_full_video_app_release',
                               'tests.test_stage_formal_multilingual_dev', 'tests.test_assemble_multilingual_v3_update'),
    'producer_accounting': ('tests.test_run_target_language_models', 'tests.test_render_formal_target_language_speech',
                            'tests.test_paid_model_cache_durability', 'tests.test_layer2_leaf_accounting'),
}
UNIMPLEMENTED = (
    'canonical_durable_dispatch_and_cross_process_dag',
    'canonical_group_and_unit_recovery_without_unaffected_paid_calls',
    'canonical_deploy_http_failure_recovery_without_upstream_calls',
    'production_decision_runner_and_atomic_admission',
    'stage_specific_retry_heartbeat_and_resource_backpressure',
)


def repository_identity(repo):
    head = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    dirty = subprocess.check_output(['git', '-C', str(repo), 'status', '--porcelain', '--untracked-files=normal'])
    return {'headCommit': head, 'workingTreeClean': not dirty,
            'workingTreeStatusSha256': hashlib.sha256(dirty).hexdigest()}


def run_suite(name, modules, output, *, timeout=300, runner=subprocess.run):
    """A zero exit with zero tests or skipped tests is not a passing receipt."""
    if name not in SUITES or tuple(modules) != SUITES[name]:
        raise ValueError('suite_not_allowlisted')
    log = output / (name + '.log')
    began = time.monotonic()
    timed_out = False
    with log.open('xb') as stream:
        try:
            completed = runner([sys.executable, '-m', 'unittest', *modules], cwd=ROOT,
                               stdout=stream, stderr=subprocess.STDOUT, timeout=timeout, check=False)
            code = completed.returncode
        except subprocess.TimeoutExpired:
            timed_out, code = True, None
    raw = log.read_bytes()
    text = raw.decode('utf-8', errors='replace')
    counts = re.findall(r'^Ran (\d+) tests? in ', text, re.MULTILINE)
    count = int(counts[-1]) if len(counts) == 1 else 0
    ok = re.search(r'^OK\s*$', text, re.MULTILINE) is not None
    status = 'passed' if code == 0 and count > 0 and ok and not timed_out else 'failed'
    return {'status': status, 'testCount': count, 'exitCode': code, 'timedOut': timed_out,
            'elapsedSeconds': round(time.monotonic() - began, 3),
            'logSha256': hashlib.sha256(raw).hexdigest(), 'logFile': log.name,
            'modules': list(modules)}


def evaluate(output, *, base):
    base = compatibility.commit(ROOT, base)
    output = Path(output).absolute()
    # Do not overwrite an earlier head's report or partially reuse its logs.
    output.mkdir(parents=True, exist_ok=False)
    before = repository_identity(ROOT)
    suites = {name: run_suite(name, modules, output) for name, modules in SUITES.items()}
    try:
        simulated = backend.evaluate()
    except Exception as exc:
        simulated = {'status': 'failed', 'errorType': type(exc).__name__, 'simulationOnly': True}
    compatibility_receipt = compatibility.evaluate(ROOT, base, before['headCommit'])
    after = repository_identity(ROOT)
    stable = before == after and before['workingTreeClean']
    passed = all(row['status'] == 'passed' for row in suites.values()) and simulated['status'] == 'pass' and stable
    report = {'schemaVersion': 'sermon-canonical-stage0-report-v1',
              'generatedAt': datetime.now(timezone.utc).isoformat(),
              'status': 'component_checks_passed_stage_incomplete' if passed else 'component_checks_failed',
              'repositoryBefore': before, 'repositoryAfter': after, 'cleanStableHead': stable,
              'scope': 'synthetic_component_tests_not_canonical_end_to_end_execution',
              'simulationOnly': True, 'suites': suites, 'backendSimulation': simulated,
              'compatibility': compatibility_receipt, 'unimplementedRequirements': list(UNIMPLEMENTED),
              'runtimeCodexTurnEvidence': 'asserted_zero_in_legacy_controller_and_canonical_shadow_tests',
              'productionModelUsage': 'not_measured_by_component_harness',
              'stage1PromotionAllowed': False}
    encoded = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + '\n'
    (output / 'stage0-report.json').write_text(encoded)
    signoff = {'schemaVersion': 'sermon-canonical-stage0-signoff-v1',
               'headCommit': before['headCommit'], 'reportSha256': hashlib.sha256(encoded.encode()).hexdigest(),
               'status': 'pending', 'automaticApproval': False, 'stage1PromotionAllowed': False,
               'engineering': {'status': 'pending', 'reviewer': None},
               'content': {'status': 'not_evaluated', 'reviewer': None},
               'release': {'status': 'not_evaluated', 'reviewer': None},
               'compatibility': {'status': 'pending', 'reviewer': None},
               'performance': {'status': 'not_evaluated', 'reviewer': None},
               'blockers': list(UNIMPLEMENTED) + ([] if passed else ['component_checks_failed'])
                           + ([] if stable else ['clean_stable_head_required'])
                           + ([] if compatibility_receipt['status'] == 'backend_only_unchanged'
                              else ['compatibility_review_required'])}
    (output / 'stage0-signoff.json').write_text(json.dumps(signoff, indent=2, sort_keys=True) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--base', required=True, help='Exact baseline commit/ref for compatibility snapshot')
    args = parser.parse_args()
    report = evaluate(args.out, base=args.base)
    print(json.dumps({'status': report['status'], 'headCommit': report['repositoryBefore']['headCommit'],
                      'stage1PromotionAllowed': False}))
    return 0 if report['status'] == 'component_checks_passed_stage_incomplete' else 1


if __name__ == '__main__':
    raise SystemExit(main())
