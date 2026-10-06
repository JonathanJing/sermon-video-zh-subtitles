#!/usr/bin/env python3
"""Run a frozen comparison fixture only after its independent English judge passes."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from scripts import codex_layer2_diagnostic as diagnostic
from scripts.run_codex_layer2_test import run_diagnostic_test
from scripts import sermon_workflow_jobs as jobs


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(fixture,source_result,out_dir,resource_policy,*,cli_path=None,runner=run_diagnostic_test,
        test_adjudication=None,backend='codex',reuse_api_receipts=None):
    source,anchor,*_=diagnostic.load_fixture(fixture)
    result=json.loads(Path(source_result).read_text())
    source_valid=(result.get('mode')=='frozen_source_judge8'
        and result.get('sourceASR')=='reused_frozen_source'
        and result.get('productionEligible') is False and result.get('humanApproval') is False)
    diagnostic.require(source_valid,'frozen source diagnostic identity invalid')
    if result.get('machineJudgeStatus')!='approved_for_layer2_shadow':
        diagnostic.require(test_adjudication is not None,'frozen source machine judge not passed')
        receipt=jobs._read(test_adjudication)
        judge=jobs._read(Path(source_result).parent/'machine-judge.json')
        failed=[row['sourceSentenceId'] for row in judge['sentences'] if row['verdict']=='fail']
        diagnostic.require(receipt.get('schemaVersion')=='diagnostic-source-disagreement-v1'
            and receipt.get('simulationOnly') is True and receipt.get('productionEligible') is False
            and receipt.get('humanApproval') is False and receipt.get('publishEligible') is False
            and receipt.get('sourceResultSha256')==_sha(source_result)
            and receipt.get('machineJudgeSha256')==_sha(Path(source_result).parent/'machine-judge.json')
            and receipt.get('disputedSentenceIds')==failed==['0-s125'],
            'diagnostic_source_disagreement_receipt_invalid')
    bound_anchor=json.loads(Path(result['anchorPath']).read_text())
    diagnostic.require(diagnostic.policies.canonical_sha256(bound_anchor)==diagnostic.policies.canonical_sha256(anchor),
                       'source judge anchor differs from comparison fixture')
    # The comparison keeps the old frozen package, rather than replacing its
    # identity with the newly generated, still human-pending source package.
    return runner(fixture,out_dir,cli_path=cli_path or Path.home()/'.local/bin/codex',
                  resource_policy_path=resource_policy,translator_model='gpt-6.1-sol',backend=backend,
                  reuse_api_receipts=reuse_api_receipts)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('fixture','source-result','out-dir','resource-policy'):
        p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--codex-cli',type=Path)
    p.add_argument('--test-adjudication',type=Path)
    p.add_argument('--backend',choices=('codex','openai_api'),default='codex')
    p.add_argument('--reuse-api-receipts',type=Path)
    a=p.parse_args();run(a.fixture,a.source_result,a.out_dir,a.resource_policy,
        cli_path=a.codex_cli,test_adjudication=a.test_adjudication,backend=a.backend,
        reuse_api_receipts=a.reuse_api_receipts)
if __name__=='__main__':main()
