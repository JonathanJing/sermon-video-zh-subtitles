"""Export an allowlisted replayable accounting trace, excluding private payloads.

The export proves no execution beyond the supplied ledger. Source SHA and removed
fields/counts make this transformation explicit; hashes are not anonymization.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import sermon_accounting as accounting
from scripts import sermon_cache_observation as cache
from scripts import sermon_local_model_observation as local_model
from scripts import sermon_decision_accounting as decision
from scripts import sermon_workflow_evidence as evidence
from scripts import weekly_pipeline_report as weekly

LABELS = {'event', 'eventId', 'runId', 'workflow', 'workflowId', 'parentWorkflowId', 'spanId', 'parentSpanId',
          'stage', 'status', 'billing', 'executorType', 'workUnitId', 'attemptId', 'decisionId',
          'invocationId', 'clockDomainId', 'monotonicStartNs', 'monotonicEndNs', 'provider', 'model', 'requestedModel', 'measurementScope', 'phase', 'code', 'level'}
TIMES = {'recordedAt', 'startedAt', 'dependencyReadyAt', 'queuedAt'}


def safe_event(row):
    result = {'schemaVersion': row['schemaVersion']}
    for key in LABELS:
        if key in row: result[key] = accounting._label(row[key], None)
    for key in TIMES:
        if key in row:
            result[key] = datetime.fromisoformat(row[key]).isoformat() if row[key] is not None else None
    for key in ('dependsOn', 'blockedBy'):
        if key in row: result[key] = accounting._labels(row[key]) if row[key] is not None else None
    for key in ('elapsedSeconds',):
        if key in row: result[key] = accounting._number(row[key])
    if 'cacheHit' in row: result['cacheHit'] = row['cacheHit'] is True
    if 'metadata' in row: result['metadata'] = accounting._safe_metadata(row['metadata'])
    if 'executionIdentity' in row: result['executionIdentity'] = accounting.safe_execution_identity(row['executionIdentity'])
    if 'settings' in row: result['settings'] = accounting._safe_settings(row['settings'])
    if 'responseId' in row:
        # Consistent replacement preserves direct-receipt joins without public provider IDs.
        result['responseId'] = hashlib.sha256(row['responseId'].encode()).hexdigest() if row['responseId'] else None
    if row['event'] == 'api_attempt':
        result['usage'] = {k: accounting._number(v) for k, v in row['usage'].items() if k in accounting.normalize_usage(None)}
        result['cost'] = {'status': accounting._label(row['cost'].get('status')),
                          'estimatedUsd': accounting._number(row['cost'].get('estimatedUsd'))}
    if row['event'] == 'sdk_call_finished':
        result['usage'] = {k: accounting._number(row['usage'].get(k)) for k in ('requests', 'input_tokens', 'output_tokens', 'total_tokens')}
    if row['event'] == 'workload':
        result['metrics'] = {k: v for k, v in row['metrics'].items() if accounting._label(k, None) and (
            v is None or isinstance(v, bool) or accounting._number(v) is not None
            or k.endswith('Sha256') and isinstance(v, str) and evidence.HASH.fullmatch(v)
            or k == 'timingScope' and v in {'current_execution', 'after_model_load'})}
    if row['event'] == 'workflow_evidence':
        original = row['evidence']
        result['evidence'] = {'schemaVersion': evidence.SCHEMA, 'evidenceScope': 'existing_files_snapshot',
            'currentRunExecutionProven': False, 'artifacts': []}
        for item in original.get('artifacts', []):
            if not isinstance(item, dict) or item.get('category') not in evidence.PATHS: continue
            if not isinstance(item.get('sha256'), str) or not evidence.HASH.fullmatch(item['sha256']): continue
            result['evidence']['artifacts'].append({'category': item['category'], 'sha256': item['sha256'],
                'bytes': accounting._number(item.get('bytes')), 'summary': evidence._summary(item.get('summary', {}))})
        result['evidence']['missingCategories'] = [k for k in original.get('missingCategories', []) if k in evidence.PATHS]
    if row['event'] == 'log':
        if row.get('code') == cache.CODE: result['fields'] = cache.safe_observation(row.get('fields'))
        elif row.get('code') == decision.CODE: result['fields'] = decision.safe_observation(row.get('fields'))
        elif row.get('code') == local_model.CODE: result['fields'] = local_model.safe_observation(row.get('fields'))
        else:
            result['fields'] = {k: v for k, v in row.get('fields', {}).items()
                if k in {'status', 'reasonCode'} and isinstance(v, str) and evidence._code(v)}
    if isinstance(row.get('error'), dict):
        result['error'] = {'errorType': accounting._label(row['error'].get('errorType'))}
    if not accounting._valid_event(result): raise ValueError('export_would_drop_required_safe_identity')
    return result


def export(directory, output):
    events, damaged, source_hash = accounting.read_event_snapshot(directory)
    if damaged: raise ValueError('damaged_source_ledger_requires_inspection')
    safe = [safe_event(e) for e in events]
    before, after = accounting.receipt_integrity(events), accounting.receipt_integrity(safe)
    if (before['status'], len(before['conflicts']), before['equivalentDuplicatesIgnored']) != (after['status'], len(after['conflicts']), after['equivalentDuplicatesIgnored']):
        raise ValueError('export_changes_receipt_reconciliation')
    output.mkdir(parents=True, exist_ok=False)
    serialized = ''.join(json.dumps(e, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n' for e in safe)
    (output/'events.jsonl').write_text(serialized)
    report = weekly.project(output)
    (output/'report.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    (output/'report.md').write_text(weekly.markdown(report))
    manifest = {'schemaVersion': 'sermon-safe-observability-export-v1', 'sourceEventCount': len(events),
        'exportedEventCount': len(events), 'sourceLedgerSha256': source_hash,
        'exportedLedgerSha256': hashlib.sha256(serialized.encode()).hexdigest(),
        'excluded': ['pid', 'thread', 'error_payloads', 'resource_host_details', 'paths', 'unknown_log_fields', 'transcript_and_response_text'],
        'responseIdTransform': 'sha256_preserves_equality_not_original_provider_identifier',
        'scope': 'exported_ledger_only_not_independent_proof_of_execution',
        'reportSha256': hashlib.sha256((output/'report.json').read_bytes()).hexdigest()}
    (output/'export.json').write_text(json.dumps(manifest, indent=2)+'\n')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--accounting-dir', type=Path, required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export(args.accounting_dir, args.out_dir)))
