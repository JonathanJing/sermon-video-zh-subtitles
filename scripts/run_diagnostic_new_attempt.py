"""Prepare a separately authorized new attempt; no API or old deadline reset."""
import argparse
import json
from pathlib import Path

from scripts import sermon_accounting as accounting, sermon_diagnostic_attempts as attempts
from scripts import sermon_review_contracts as c
from scripts import sermon_public_snapshot as public


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent-plan',type=Path,required=True)
    parser.add_argument('--ancestor-plan',type=Path,action='append',default=[])
    parser.add_argument('--authorization',type=Path,required=True)
    parser.add_argument('--new-root',type=Path,required=True)
    parser.add_argument('--legacy-baseline',type=Path)
    args=parser.parse_args(argv)
    parent=c.read_snapshot(args.parent_plan)[0];ancestors=[c.read_snapshot(p)[0] for p in args.ancestor_plan]
    authorization=c.read_snapshot(args.authorization)[0]
    c.require(authorization.get('schemaVersion')==attempts.AUTH_SCHEMA_V2,
        'new_execution_requires_attempt_authorization_v2')
    c.require(args.legacy_baseline is not None and not ancestors,'v2_fixed_legacy_baseline_required')
    baseline=public.read_snapshot(args.legacy_baseline)[0]
    plan,linkage=attempts.prepare_new_attempt_v2(args.parent_plan,new_root=args.new_root,
        authorization=authorization,execution_identity=accounting.execution_identity(),baseline=baseline)
    attempts.persist_new_attempt_v2(plan,linkage,authorization)
    print(json.dumps({'status':'prepared','newCalls':0,'oldLedgerAndDeadlineModified':False,
        'planSha256':linkage['newPlanSha256'],'priorRequestCount':linkage['priorRequestCount'],
        'priorReservedMicrousd':linkage['priorReservedMicrousd'],'productionEligible':False}))


if __name__=='__main__':main()
