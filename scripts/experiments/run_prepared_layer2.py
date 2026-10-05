#!/usr/bin/env python3
"""Run a frozen comparison fixture only after its independent English judge passes."""
import argparse
import json
from pathlib import Path
import sys
if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from scripts import codex_layer2_diagnostic as diagnostic
from scripts.run_codex_layer2_test import run_diagnostic_test


def run(fixture,source_result,out_dir,resource_policy,*,cli_path=None,runner=run_diagnostic_test):
    source,anchor,*_=diagnostic.load_fixture(fixture)
    result=json.loads(Path(source_result).read_text())
    diagnostic.require(result.get('mode')=='frozen_source_judge8'
        and result.get('sourceASR')=='reused_frozen_source'
        and result.get('machineJudgeStatus')=='approved_for_layer2_shadow'
        and result.get('productionEligible') is False and result.get('humanApproval') is False,
        'frozen source machine judge not passed')
    bound_anchor=json.loads(Path(result['anchorPath']).read_text())
    diagnostic.require(diagnostic.policies.canonical_sha256(bound_anchor)==diagnostic.policies.canonical_sha256(anchor),
                       'source judge anchor differs from comparison fixture')
    # The comparison keeps the old frozen package, rather than replacing its
    # identity with the newly generated, still human-pending source package.
    return runner(fixture,out_dir,cli_path=cli_path or Path.home()/'.local/bin/codex',
                  resource_policy_path=resource_policy,translator_model='gpt-6.1-sol')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('fixture','source-result','out-dir','resource-policy'):
        p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--codex-cli',type=Path)
    a=p.parse_args();run(a.fixture,a.source_result,a.out_dir,a.resource_policy,cli_path=a.codex_cli)
if __name__=='__main__':main()
