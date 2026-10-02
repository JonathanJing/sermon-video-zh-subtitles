"""Conservative commit-bound Web/iOS compatibility evidence; never a human sign-off."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

# Freeze complete consumer/contract trees, not just a handpicked schema version.
# An unclassified production change requires review rather than assuming safety.
PROTECTED = ('apps/tongxing-ios/', 'schemas/', 'firebase/', 'web/',
             'experiments/sermon-dubbing-poc/web/', 'experiments/sermon-dubbing-poc/feedback-api/')
PRODUCERS = ('scripts/build_multilingual_catalog.py', 'scripts/stage_formal_multilingual_dev.py',
             'scripts/build_target_language_release_package.py',
             'scripts/build_formal_multilingual_dev.py', '.github/workflows/tongxing-ios.yml')
# Only these audited observability files are known to leave client content alone.
BACKEND_ONLY = frozenset(('scripts/sermon_accounting.py', 'scripts/export_sermon_trace.py',
                         'scripts/weekly_pipeline_report.py', 'scripts/pipeline_compatibility_gate.py'))
POLICY = 'sermon-backend-compatibility-policy-v1'


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args])


def commit(repo, ref):
    return git(repo, 'rev-parse', '--verify', '--end-of-options', ref + '^{commit}').decode().strip()


def protected(path):
    return path.startswith(PROTECTED) or path in PRODUCERS or path.endswith(('.ipa', '.app', '.entitlements', '.xcprivacy'))


def snapshot(repo, revision):
    entries = {}
    for record in git(repo, 'ls-tree', '-r', '-z', revision).split(b'\0'):
        if not record:
            continue
        meta, raw_path = record.split(b'\t', 1)
        path = raw_path.decode('utf-8')
        if protected(path):
            mode, kind, oid = meta.decode().split()
            entries[path] = {'mode': mode, 'kind': kind, 'object': oid}
    encoded = json.dumps(entries, sort_keys=True, separators=(',', ':')).encode()
    return {'commit': revision, 'files': entries, 'sha256': hashlib.sha256(encoded).hexdigest()}


def evaluate(repo, base, head):
    base, head = commit(repo, base), commit(repo, head)
    before, after = snapshot(repo, base), snapshot(repo, head)
    changed = [p.decode('utf-8') for p in git(repo, 'diff', '--no-renames', '--name-only', '-z', base, head).split(b'\0') if p]
    client_changes = sorted(p for p in changed if protected(p))
    unknown = sorted(p for p in changed if not protected(p) and p not in BACKEND_ONLY
                     and not p.startswith(('docs/', 'tests/')))
    missing = [prefix for prefix in ('apps/tongxing-ios/', 'schemas/', 'experiments/sermon-dubbing-poc/web/')
               if not any(p.startswith(prefix) for p in before['files']) or not any(p.startswith(prefix) for p in after['files'])]
    unchanged = not client_changes and not unknown and not missing and before['sha256'] == after['sha256']
    return {'schemaVersion': 'sermon-pipeline-compatibility-receipt-v1', 'policyVersion': POLICY,
            'baseCommit': base, 'headCommit': head, 'baseSnapshot': before, 'headSnapshot': after,
            'changedClientFiles': client_changes, 'unclassifiedChanges': unknown, 'missingSurfaces': missing,
            'status': 'backend_only_unchanged' if unchanged else 'review_required',
            'ios_review_required': False if unchanged else None,
            'compatibilitySignoff': 'not_evaluated', 'deviceAcceptance': 'not_run',
            'deployedBundleEvidence': 'not_evaluated',
            'scope': 'tracked_source_contract_and_bundle_inputs_only',
            'notes': ['Exact commit trees, not commit count or merge-base diff.',
                      'Any consumer/contract change requires decoder/semantic review and a new decision receipt.',
                      'Untracked artifacts, deployment state and human acceptance are outside this receipt.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path('.'))
    parser.add_argument('--base', required=True)
    parser.add_argument('--head', required=True)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    report = evaluate(args.repo, args.base, args.head)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    # A receipt for an earlier head must not silently be replaced.
    with args.out.open('x') as stream:
        stream.write(json.dumps(report, indent=2, sort_keys=True) + '\n')
    args.out.chmod(0o600)
    return 0 if report['status'] == 'backend_only_unchanged' else 1


if __name__ == '__main__':
    raise SystemExit(main())
