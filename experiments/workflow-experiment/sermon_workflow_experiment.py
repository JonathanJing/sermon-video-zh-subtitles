"""Offline validation/comparison of matched workflow experiments; never dispatches."""
import math
from scripts.sermon_unified import contracts as c

ARMS = {'durable_workflow', 'bounded_packet', 'full_context'}
METRICS = {'inputTokens', 'cachedInputTokens', 'outputTokens', 'apiCostMicrousd',
           'codexContextTokens', 'invoiceCostMicrousd', 'gpuSeconds', 'wallSeconds'}
IDENTITIES = {'sourceSha256', 'policySha256', 'qualityProtocolSha256'}


def validate_protocol(protocol):
    if (protocol.get('schemaVersion') != 'sermon-workflow-experiment-v1'
            or set(protocol.get('arms', [])) != ARMS
            or protocol.get('cacheModes') != ['cold', 'hot']
            or not all(isinstance(protocol.get(k), str) and len(protocol[k]) == 64
                       and all(ch in '0123456789abcdef' for ch in protocol[k]) for k in IDENTITIES)
            or not isinstance(protocol.get('blindAssignments'), dict)
            or set(protocol['blindAssignments'].values()) != ARMS
            or len(protocol['blindAssignments']) != 3):
        raise c.ContractError('invalid_workflow_experiment_protocol')
    return c.digest(protocol)


def compare(protocol, receipts):
    """Report matched measurements; absent counters remain null, never zero."""
    identity = validate_protocol(protocol)
    indexed = {}
    for row in receipts:
        key = (row.get('blindId'), row.get('cacheMode'))
        if (row.get('schemaVersion') != 'sermon-workflow-experiment-receipt-v1'
                or row.get('protocolSha256') != identity
                or any(row.get(k) != protocol[k] for k in IDENTITIES)
                or key[0] not in protocol['blindAssignments'] or key[1] not in ['cold', 'hot']
                or key in indexed or row.get('quality', {}).get('status') not in ['passed', 'failed', 'unknown']
                or not isinstance(row.get('evidenceSha256'), str) or len(row['evidenceSha256']) != 64
                or set(row.get('metrics', {})) != METRICS):
            raise c.ContractError('invalid_workflow_experiment_receipt')
        for value in row['metrics'].values():
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
                raise c.ContractError('invalid_workflow_experiment_measurement')
        indexed[key] = row
    expected = {(blind, mode) for blind in protocol['blindAssignments'] for mode in ['cold', 'hot']}
    complete = set(indexed) == expected
    quality = complete and all(row['quality']['status'] == 'passed' for row in indexed.values())
    tables = {}
    for mode in ['cold', 'hot']:
        rows = {blind: indexed[(blind, mode)]['metrics'] for blind in protocol['blindAssignments'] if (blind, mode) in indexed}
        tables[mode] = rows
    return {'schemaVersion': 'sermon-workflow-experiment-comparison-v1', 'protocolSha256': identity,
            'complete': complete, 'qualityComparable': quality, 'blindMeasurements': tables,
            'missingReceipts': [{'blindId': a, 'cacheMode': b} for a,b in sorted(expected - set(indexed))],
            'costDomains': ['apiCostMicrousd', 'codexContextTokens', 'invoiceCostMicrousd'],
            'conclusion': 'matched_measurements_available' if quality else 'incomplete_or_quality_not_passed',
            'productionAcceptance': 'not_established'}


def main():
    import argparse
    import json
    from pathlib import Path
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--protocol',type=Path,required=True)
    parser.add_argument('--receipt',type=Path,action='append',default=[])
    args=parser.parse_args()
    print(json.dumps(compare(c.read(args.protocol),[c.read(path) for path in args.receipt]),ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
