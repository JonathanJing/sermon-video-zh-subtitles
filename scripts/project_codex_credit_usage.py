"""Read-only credit projection of bound historical CLI receipts; no model calls.

Original ledgers/receipts remain byte-identical. A separate derived ledger keeps
original call timestamps and identities; projection.json binds source hashes.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import sermon_accounting as accounting
from scripts import sermon_model_call_observation as observation
from scripts.codex_credit_usage import estimate_credit_usage


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def project(accounting_dir, receipts_dir, out_dir):
    source, receipts, out = Path(accounting_dir).resolve(), Path(receipts_dir).resolve(), Path(out_dir).resolve()
    if out.exists() or out.is_relative_to(source) or out.is_relative_to(receipts):
        raise ValueError('credit_projection_requires_new_separate_output')
    ledger = source/'events.jsonl'
    original_sha = _sha(ledger)
    events, damaged = accounting.read_events(source)
    if damaged:
        raise ValueError('credit_projection_damaged_source_ledger')
    bound, source_hashes = {}, {'events.jsonl': original_sha}
    for path in sorted(receipts.glob('*/response.json')):
        prefix, _, call_id = path.parent.name.partition('-')
        if prefix not in ('translator', 'reviewer') or not call_id:
            raise ValueError('invalid_credit_receipt_identity')
        binding_path = path.parent/'resource-binding.json'
        binding = json.loads(binding_path.read_text()) if binding_path.exists() else None
        if binding is not None:
            call_id = binding.get('owner', {}).get('callId')
            if not isinstance(call_id, str) or binding.get('operationId') != 'codex-layer2:'+call_id:
                raise ValueError('invalid_credit_resource_binding')
            source_hashes[str(binding_path.relative_to(receipts))] = _sha(binding_path)
        if not call_id or call_id in bound:
            raise ValueError('invalid_credit_receipt_identity')
        value = json.loads(path.read_text())
        if value.get('completed') is not True or value.get('exitCode') != 0:
            raise ValueError('credit_receipt_not_terminal')
        outcome = path.parent/'resource-outcome.json'
        if outcome.exists():
            digest = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            outcome_value = json.loads(outcome.read_text())
            if (outcome_value.get('responseSha256') != digest or binding is not None and
                    (outcome_value.get('status') != 'terminal' or outcome_value.get('owner') != binding['owner'] or
                     outcome_value.get('operationId') != binding['operationId'])):
                raise ValueError('credit_receipt_outcome_mismatch')
            source_hashes[str(outcome.relative_to(receipts))] = _sha(outcome)
        bound[call_id] = value
        source_hashes[str(path.relative_to(receipts))] = _sha(path)
    projected, converted, matched = copy.deepcopy(events), 0, set()
    for event in projected:
        if event.get('code') != observation.CODE:
            continue
        fields = event['fields']
        if fields['provider'] != 'codex' or fields['backend'] != 'agent_session':
            continue
        response = bound.get(fields['callId'])
        if response is None:
            continue  # No bound tier: existing report correctly records unknown.
        if fields['model'] != response.get('requestedModel'):
            raise ValueError('credit_receipt_model_mismatch')
        if fields['phase'] == 'finished':
            if fields['status'] != 'completed' or fields['usage'] != observation.normalize_usage(response.get('usage')):
                raise ValueError('credit_receipt_usage_mismatch')
            matched.add(fields['callId'])
        if fields['schemaVersion'] == observation.SCHEMA:
            fields.update(schemaVersion=observation.CREDIT_SCHEMA, creditUsage=estimate_credit_usage(
                fields['model'], fields['usage'], requested_service_tier=response.get('requestedServiceTier'),
                server_model=response.get('serverModel'), server_service_tier=response.get('serverServiceTier'),
                status=fields['status'], cache_hit=fields['cacheHit']))
            observation.safe_observation(fields)
            converted += 1
    if matched != set(bound):
        raise ValueError('credit_receipt_unmatched_call')
    if _sha(ledger) != original_sha or any(_sha(receipts/path) != digest for path,digest in source_hashes.items() if path != 'events.jsonl'):
        raise ValueError('credit_source_changed_during_projection')
    out.mkdir(parents=True, mode=0o700)
    derived_ledger = out/'events.jsonl'
    derived_ledger.touch(mode=0o600)
    derived_ledger.write_text(''.join(json.dumps(e, ensure_ascii=False, sort_keys=True)+'\n' for e in projected))
    summary = accounting.summarize(out)
    manifest = dict(schemaVersion='codex-credit-projection-v1', diagnosticOnly=True,
        sourceLedgerSha256=original_sha, sourceEvidenceSha256=source_hashes,
        derivedLedgerSha256=_sha(out/'events.jsonl'), convertedObservationEvents=converted,
        matchedCalls=len(matched), newModelCalls=0, originalLedgerUnchanged=_sha(ledger)==original_sha,
        modelCallReport=summary['modelCallReport'])
    projection_path = out/'projection.json'
    projection_path.touch(mode=0o600)
    projection_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--accounting-dir', type=Path, required=True)
    parser.add_argument('--cli-receipts-dir', type=Path, required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    result = project(args.accounting_dir, args.cli_receipts_dir, args.out_dir)
    print(json.dumps({k:result[k] for k in ('matchedCalls','convertedObservationEvents','newModelCalls','originalLedgerUnchanged')}))


if __name__ == '__main__':
    main()
