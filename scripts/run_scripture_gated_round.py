"""One command after a signed adjudication receipt: validate, freeze, verify.

Steps, in order, each refusing before the next:
1. Validate the receipt against the frozen source fixture (human or machine
   role, approved, bindings, exact CUV text, coverage of every flagged unit).
   A machine receipt is machine evidence: the report records it as such and
   carries no human approval.
2. Freeze the admitted-quote plugin and a new fixture that carries the receipt.
3. Load the fixture back through the same gate used before any dispatch.
4. Optionally (--run-models) open an exclusive Spark session, run the diagnostic
   Layer 2 CLI and the Spark TTS/ASR, then close the session in the same
   background command. Models run only with this flag.

It never creates or edits a receipt, and it does not publish. Dev publication is
not wired to diagnostic candidates and stays a separate, explicitly authorized step.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import codex_layer2_diagnostic as diagnostic  # noqa: E402
from scripts import scripture_adjudication as adjudication  # noqa: E402
from scripts.language_review_plugins import diagnostic_admitted_quotes as admitted  # noqa: E402

TARGET_LOCALE = 'zh-Hans'


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def run(args: argparse.Namespace) -> dict[str, Any]:
    source_dir = Path(args.source_fixture).resolve()
    out = Path(args.out_root).resolve()
    if out.exists():
        raise SystemExit('out-root exists; choose a new directory')
    manifest = _load(source_dir / 'fixture-manifest.json')
    flagged = list(manifest.get('sourceQuotationUnits') or [])
    if manifest.get('scriptureClassification') != 'contains_direct_quotations' or not flagged:
        raise SystemExit('source fixture does not flag direct quotations; nothing to adjudicate')
    source, anchor, plan = (_load(source_dir / name) for name in ('source.json', 'anchor.json', 'group-plan.json'))
    bindings = {name: manifest['files'][name] for name in adjudication.BINDING_KEYS}
    receipt = _load(Path(args.receipt))
    summary = adjudication.validate_receipt(receipt, target_locale=TARGET_LOCALE,
                                            bindings=bindings, flagged_units=flagged)
    out.mkdir(parents=True)
    baseline = _load(Path(args.baseline_policy))
    policy = admitted.freeze_admitted_plugin(summary, source, anchor, plan, baseline, out / 'plugin.py')
    commit = args.code_commit or subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True,
                                                text=True, check=True).stdout.strip()
    fixture = out / 'fixture'
    diagnostic.freeze_fixture(source, anchor, policy, plan, out / 'plugin.py', fixture,
        authorization_ref=args.authorization_ref, code_commit=commit, translator_model=args.translator_model,
        scripture_classification='contains_direct_quotations', source_quotation_units=flagged,
        scripture_adjudication=receipt)
    diagnostic.load_fixture(fixture)
    report = {'schemaVersion': 'sermon-scripture-gated-round-v1', 'status': 'frozen_and_loaded',
              'receiptSha256': summary['receiptSha256'], 'coveredUnits': summary['coveredUnits'],
              'admittedQuotes': [{'candidateId': q['candidateId'], 'classification': q['classification'],
                                  'canonicalRef': q['canonicalRef'], 'editionId': q['editionId'],
                                  'editionVerification': q['editionVerification']} for q in summary['quotes']],
              'fixture': str(fixture), 'modelCalls': 0,
              'adjudicationKind': summary['adjudicationKind'],
              'humanApproval': 'from_receipt_only' if summary['humanApproval'] else False,
              'productionEligible': False}
    if args.run_models:
        report.update(run_models(args, fixture, out))
    (out / 'round.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


def run_models(args: argparse.Namespace, fixture: Path, out: Path) -> dict[str, Any]:
    """Run the L2 CLI and Spark TTS/ASR inside one exclusive session, closed afterwards."""
    if not (args.spark_session_id and args.spark_session_owner and args.remote_stage and args.media):
        raise SystemExit('--run-models needs --media, --spark-session-id, --spark-session-owner and --remote-stage')
    python = ROOT / '.venv' / 'bin' / 'python'
    rel = lambda path: str(Path(path).relative_to(ROOT))  # noqa: E731
    layer2 = out / 'layer2'
    audio = out / 'audio'
    chain = (f'{python} scripts/run_codex_layer2_test.py --fixture-dir {rel(fixture)} --diagnostic-fixture '
             f'--out-dir {rel(layer2)} --translator-model {args.translator_model} --reviewer-tier fast && '
             f'{python} scripts/experiments/run_spark_diagnostic_audio.py execute --fixture {rel(fixture)} '
             f'--layer2-out {rel(layer2)} --media {args.media} --out {rel(audio)} '
             f'--remote-stage {args.remote_stage} --spark-session-id {args.spark_session_id} '
             f'--spark-session-owner {args.spark_session_owner}')
    begin = subprocess.run([str(python), 'scripts/spark_exclusive_session.py', 'begin',
                            '--session-id', args.spark_session_id, '--owner', args.spark_session_owner,
                            '--minimum-available-gib', '64', '--preempt', '--allow-interrupted-restart'],
                           cwd=ROOT, capture_output=True, text=True)
    if begin.returncode:
        raise SystemExit('exclusive session did not start; nothing was run: ' + begin.stderr.strip()[:300])
    # The L2 CLI and the Spark runner both require the session identity in the environment.
    environment = dict(os.environ, SPARK_EXCLUSIVE_SESSION_ID=args.spark_session_id,
                       SPARK_EXCLUSIVE_SESSION_OWNER=args.spark_session_owner)
    run_result = subprocess.run(['scripts/experiments/spark_session_round.sh', args.spark_session_id,
                                 args.spark_session_owner, '--', 'sh', '-c', chain], cwd=ROOT, env=environment)
    return {'modelRun': 'completed' if run_result.returncode == 0 else 'failed',
            'modelRunExitCode': run_result.returncode, 'publication': 'not_run'}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--receipt', type=Path, required=True,
                        help='Adjudication receipt signed by a human reviewer or by scripture_machine_adjudication')
    parser.add_argument('--source-fixture', type=Path, required=True, help='Frozen zh-Hans 605 fixture (source of inputs)')
    parser.add_argument('--baseline-policy', type=Path, required=True, help='Pre-adjudication baseline policy')
    parser.add_argument('--out-root', type=Path, required=True, help='New directory for this round')
    parser.add_argument('--authorization-ref', required=True, help='Authorization label recorded in the fixture')
    parser.add_argument('--code-commit', default=None, help='Defaults to HEAD')
    parser.add_argument('--translator-model', default='gpt-6.1-sol', choices=['gpt-6.1-sol'])
    parser.add_argument('--run-models', action='store_true', help='Also run L2 and Spark TTS/ASR (costs real calls)')
    parser.add_argument('--media', default=None, help='Parent source video (required with --run-models)')
    parser.add_argument('--remote-stage', default=None)
    parser.add_argument('--spark-session-id', default=None)
    parser.add_argument('--spark-session-owner', default=None)
    args = parser.parse_args(argv)
    report = run(args)
    print(json.dumps({'status': report['status'], 'fixture': report['fixture'],
                      'modelRun': report.get('modelRun', 'not_requested')}, ensure_ascii=False))
    return 1 if report.get('modelRun') == 'failed' else 0


if __name__ == '__main__':
    raise SystemExit(main())
