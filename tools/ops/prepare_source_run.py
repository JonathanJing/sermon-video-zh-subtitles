#!/usr/bin/env python3
"""Write a Layer 1 source configuration with every improvement switched on, and its budget papers.

    .venv/bin/python tools/ops/prepare_source_run.py draft --from <earlier config> --name <run name> --usd <cap>
        [--requests N] [--wall-hours H] [--cross-check <path>=<label>]...
    .venv/bin/python tools/ops/prepare_source_run.py approve --authorization <name>.authorization.json
        --reviewed-by "<who> (chat)" --evidence "<the person's words>"

`draft` copies the source identity, MFA, anchor and judge settings of an earlier configuration of the same
source and writes, next to it, a `sermon-unified-source-preparation-v4` configuration whose switches are
written out and on: one ASR worker per chunk, eight judge workers, a shared judge cache, the per-chunk
MFA cache, the one-confirmation review sheet, and `reuseBudgetRoots` naming every earlier budget root
of the same media and window whose transcription was paid directly and fully returned. It also writes a
`sermon-source-budget-authorization-v2` and an unsigned `approval-v2`; the stage refuses the run until
`approve` records the person's decision. Nothing here calls a model or spends money.
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import tongxing_host  # noqa: E402,F401  binds the production package ports
from tongxing_production.source import unified_stage as stage  # noqa: E402

REQUEST_LIMITS = {'schemaVersion': 'sermon-openai-chat-request-limits-v1', 'maxInputTokens': 16384,
                  'maxCompletionTokens': 4096, 'wallTimeMs': 300000, 'serviceTier': 'default'}
COPIED = ('productionRunId', 'sourceId', 'sourceUrlHash', 'serviceDate', 'media', 'mediaSha256',
          'sourceDurationSeconds', 'window', 'windowApproval', 'windowApprovalSha256', 'timelineReport',
          'timelineReportSha256', 'sourceDescriptor', 'sourceDescriptorSha256', 'mfa', 'anchorPolicy')


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _write_new(path, value):
    path = Path(path)
    if path.exists():
        raise SystemExit(f'refusing to overwrite {path}')
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')


def reusable_roots(directory, media_sha256, window, exclude):
    """Budget roots of earlier configurations of this media and window whose ASR was paid and returned."""
    roots = []
    for path in sorted(Path(directory).glob('*.json')):
        try:
            value = _read(path)
        except (OSError, json.JSONDecodeError):
            continue
        if not (isinstance(value, dict) and str(value.get('schemaVersion', '')).startswith('sermon-unified-source-preparation-v')
                and value.get('mediaSha256') == media_sha256 and value.get('window') == window
                and isinstance(value.get('jobRoot'), str)):
            continue
        job_root = (path.parent / value['jobRoot']).resolve()
        root = job_root.parent / f'.{job_root.name}.source-budget'
        if root.resolve() in exclude or root.resolve() in {r.resolve() for r in roots}:
            continue
        try:
            ledger = _read(root / 'source-budget.json')
        except (OSError, json.JSONDecodeError):
            continue
        asr = {k: row for k, row in (ledger.get('requests') or {}).items() if k.startswith('asr.')}
        if asr and all(row.get('status') == 'returned' and (row.get('settlement') or {}).get('costStatus') != 'reused'
                       for row in asr.values()):
            roots.append(root)
    return roots


def draft(args):
    source_path = Path(args.from_config).resolve()
    source = _read(source_path)
    directory = source_path.parent
    name = args.name
    config_path = directory / f'{name}.config.json'
    job_root = directory / f'{name}.jobs'
    budget_root = job_root.parent / f'.{job_root.name}.source-budget'
    chunks = math.ceil((source['window']['endSeconds'] - source['window']['startSeconds']) / 180)
    judge = {'backend': source['judge'].get('backend', 'claude_cli_opus'),
             'model': source['judge']['model'] if source['judge'].get('backend') else 'claude-opus-5-5',
             'reasoningEffort': source['judge']['reasoningEffort'],
             'batchSize': stage.V4_DEFAULTS['judgeBatchSize'], 'workers': stage.V4_DEFAULTS['judgeWorkers']}
    config = {'schemaVersion': stage.SCHEMA_V4, **{k: source[k] for k in COPIED},
              'jobRoot': job_root.name, 'outputDirectory': f'{name}.output',
              'budgetAuthorization': f'{name}.authorization.json', 'judge': judge,
              'asrWorkers': max(1, min(stage.MAX_ASR_WORKERS, chunks)),
              'judgeCacheRoot': stage.V4_DEFAULTS['judgeCacheRoot'],
              'mfaChunkCacheRoot': stage.V4_DEFAULTS['mfaChunkCacheRoot'],
              'reviewConfirmation': f'{name}.review-confirmation.json',
              'reuseBudgetRoots': [str(root.relative_to(directory)) if root.is_relative_to(directory) else str(root)
                                   for root in reusable_roots(directory, source['mediaSha256'], source['window'],
                                                              {budget_root.resolve()})]}
    if args.cross_check:
        rows = []
        for item in args.cross_check:
            path, _, label = item.partition('=')
            transcript = Path(path).resolve()
            rows.append({'path': str(transcript), 'sha256': stage._sha(transcript), 'label': label or transcript.name})
        config['crossCheckTranscripts'] = rows
    identity = stage.jobs._digest({k: v for k, v in config.items() if k != 'budgetAuthorization'})
    binding = {'productionRunId': config['productionRunId'], 'configurationSha256': identity, 'budgetRoot': str(budget_root)}
    bounds = {'requests': args.requests, 'wallTimeMs': int(args.wall_hours * 3600 * 1000),
              'costMicrousd': int(round(args.usd * 1_000_000))}
    approval_path = directory / f'{name}.approval.json'
    approval = {'schemaVersion': stage.APPROVAL_V2, 'binding': {**binding, 'globalBounds': bounds, 'requestLimits': REQUEST_LIMITS},
                'humanApproval': False, 'decision': 'pending', 'reviewedBy': None, 'reviewedAt': None, 'operatorEvidence': None}
    _write_new(config_path, config)
    _write_new(approval_path, approval)
    _write_new(directory / f'{name}.authorization.json', {
        'schemaVersion': stage.AUTHORIZATION_V2, 'binding': binding,
        'authority': {'approvalSha256': stage._sha(approval_path), 'globalBounds': bounds, 'requestLimits': REQUEST_LIMITS},
        'approvalReceipt': approval_path.name, 'evidence': {'codeIdentitySha256AtApproval': stage.code.code_identity()}})
    return {'config': str(config_path), 'approval': str(approval_path), 'budgetRoot': str(budget_root),
            'reuseBudgetRoots': config['reuseBudgetRoots'], 'asrWorkers': config['asrWorkers'],
            'judgeWorkers': judge['workers'], 'reviewConfirmation': config['reviewConfirmation'],
            'next': 'record the person\'s budget decision with: prepare_source_run.py approve'}


def approve(args):
    authorization_path = Path(args.authorization).resolve()
    authorization = _read(authorization_path)
    approval_path = authorization_path.parent / authorization['approvalReceipt']
    approval = _read(approval_path)
    if approval.get('decision') != 'pending' or stage._sha(approval_path) != authorization['authority']['approvalSha256']:
        raise SystemExit('approval is not an unsigned draft of this authorization')
    if not args.reviewed_by.strip() or not args.evidence.strip():
        raise SystemExit('the reviewer and the person\'s words are required')
    approval.update(humanApproval=True, decision='approved', reviewedBy=args.reviewed_by, operatorEvidence=args.evidence,
                    reviewedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'))
    approval_path.write_text(json.dumps(approval, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    authorization['authority']['approvalSha256'] = stage._sha(approval_path)
    authorization_path.write_text(json.dumps(authorization, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    return {'approval': str(approval_path), 'authorization': str(authorization_path),
            'approvalSha256': authorization['authority']['approvalSha256']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    d = commands.add_parser('draft')
    d.add_argument('--from', dest='from_config', required=True)
    d.add_argument('--name', required=True)
    d.add_argument('--usd', type=float, required=True, help='cost cap in USD the person approves')
    d.add_argument('--requests', type=int, default=300)
    d.add_argument('--wall-hours', type=float, default=14.0)
    d.add_argument('--cross-check', action='append', default=[], help='<path>=<label> of another transcript of the same window')
    a = commands.add_parser('approve')
    a.add_argument('--authorization', required=True)
    a.add_argument('--reviewed-by', required=True)
    a.add_argument('--evidence', required=True)
    args = parser.parse_args(argv)
    print(json.dumps(draft(args) if args.command == 'draft' else approve(args), ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
