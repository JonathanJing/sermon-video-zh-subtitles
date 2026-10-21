"""Local mock DAG only. Does not load media, credentials, models or publishers.

Run it as ``tools/ops/run.py orchestration.prefect.run``."""
from pathlib import Path
import argparse
import json

from tongxing_production.orchestration.prefect import contract
from tongxing_production.orchestration.prefect import dag as pilot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('mock','worker'))
    parser.add_argument('--root',required=True,type=Path)
    parser.add_argument('--plan',type=Path)
    parser.add_argument('--node')
    parser.add_argument('--request-sha')
    args = parser.parse_args()
    if args.action=='worker':
        return pilot.worker(args.root,args.node,args.request_sha)
    if args.plan is None:
        parser.error('--plan is required for mock')
    plan = contract.validate_plan(pilot.read(args.plan))
    result = pilot.run(args.root,plan)
    print(json.dumps({'runId':plan['runId'],'mode':'mock_only','nodes':result},sort_keys=True))
    return 0 if all(v['executionStatus']=='completed' for v in result.values()) else 2

if __name__=='__main__':
    raise SystemExit(main())
