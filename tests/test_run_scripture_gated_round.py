"""One-command gated round: validate, freeze, load; refusals leave no output.

Receipts are synthetic test inputs built from the pinned CUV text. They are not
human approvals. No model is called: subprocess is replaced where run_models is
exercised.
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import cuv_scripture
from scripts import run_scripture_gated_round as round_tool
from scripts import scripture_adjudication as adjudication

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'artifacts' / 'next-concurrency-605s-20261005-r3' / 'zh-Hans' / 'fixture'
BASELINE = ROOT / 'artifacts' / 'next-iteration-repair-20261005' / 'baseline-605s-policy.json'
HAVE = SOURCE.is_dir() and BASELINE.is_file()


@unittest.skipUnless(HAVE, '605 zh-Hans fixture or baseline policy not present')
class GatedRoundTests(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp(dir=ROOT / 'artifacts', prefix='test-gated-round-'))
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        manifest = json.loads((SOURCE / 'fixture-manifest.json').read_text(encoding='utf-8'))
        self.bindings = {name: manifest['files'][name] for name in adjudication.BINDING_KEYS}
        self.text = cuv_scripture.CuvLibrary.from_path().lookup('REV 4:2-3')['text']

    def receipt(self, **overrides):
        value = {'schemaVersion': adjudication.SCHEMA, 'targetLocale': 'zh-Hans', 'bindings': self.bindings,
                 'decision': 'approved', 'decidedBy': 'synthetic test reviewer', 'decidedByRole': 'human_reviewer',
                 'reviewedAt': '2026-10-09T00:00:00+00:00',
                 'candidates': [{'candidateId': 't1', 'sourceUnitIds': ['0-u067', '0-u068'],
                                 'classification': 'direct_quote', 'reference': 'REV 4:2-3',
                                 'editionId': 'CUV', 'exactSentence': self.text}]}
        value.update(overrides)
        return value

    def run_round(self, receipt, name='round'):
        path = self.work / f'{name}-receipt.json'
        path.write_text(json.dumps(receipt, ensure_ascii=False), encoding='utf-8')
        out = self.work / name
        code = round_tool.main(['--receipt', str(path), '--source-fixture', str(SOURCE),
                                '--baseline-policy', str(BASELINE), '--out-root', str(out),
                                '--authorization-ref', 'synthetic test round'])
        return code, out

    def test_valid_receipt_freezes_and_loads_without_model_calls(self):
        code, out = self.run_round(self.receipt())
        self.assertEqual(code, 0)
        report = json.loads((out / 'round.json').read_text(encoding='utf-8'))
        self.assertEqual(report['status'], 'frozen_and_loaded')
        self.assertEqual(report['modelCalls'], 0)
        self.assertEqual(report['coveredUnits'], ['0-u067', '0-u068'])
        self.assertEqual(report['admittedQuotes'][0]['editionId'], 'CUV')
        self.assertFalse(report['productionEligible'])

    def test_pending_decision_is_refused_and_writes_nothing(self):
        with self.assertRaisesRegex(ValueError, 'decision_not_approved'):
            self.run_round(self.receipt(decision='pending'), name='pending')
        self.assertFalse((self.work / 'pending').exists())

    def test_unknown_role_is_refused_and_writes_nothing(self):
        with self.assertRaisesRegex(ValueError, 'decided_by_role_invalid'):
            self.run_round(self.receipt(decidedByRole='machine'), name='machine')
        self.assertFalse((self.work / 'machine').exists())

    def test_machine_adjudicator_receipt_runs_without_human_approval(self):
        report = self.run_round(self.receipt(decidedByRole='machine_adjudicator',
                                             decidedBy='scripture_machine_adjudication v x'), name='by-machine')
        self.assertEqual((report['adjudicationKind'], report['humanApproval']), ('machine', False))
        self.assertFalse(report['productionEligible'])

    def test_receipt_bound_to_other_source_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'receipt_binding_changed'):
            self.run_round(self.receipt(bindings={**self.bindings, 'anchor.json': 'f' * 64}), name='bound')
        self.assertFalse((self.work / 'bound').exists())

    def test_run_models_passes_session_identity_to_the_chain_and_reports_failure(self):
        calls = []

        class Done:
            returncode = 0
            stderr = ''

        class Failed(Done):
            returncode = 1

        def fake_run(argv, **kwargs):
            calls.append((argv, kwargs))
            if 'spark_session_round.sh' in ' '.join(map(str, argv)):
                return Failed() if fake_run.fail else Done()
            return Done()
        fake_run.fail = False
        args = SimpleNamespace(media='media.mp4', spark_session_id='sid-1', spark_session_owner='owner-1',
                               remote_stage='/home/achillesjing/dgx-spark-benchmark/results/next-concurrency-t',
                               translator_model='gpt-6.1-sol')
        with patch.object(round_tool.subprocess, 'run', side_effect=fake_run):
            out = round_tool.run_models(args, self.work, self.work)
            wrapper = [c for c in calls if 'spark_session_round.sh' in ' '.join(map(str, c[0]))][0]
            self.assertEqual(wrapper[1]['env']['SPARK_EXCLUSIVE_SESSION_ID'], 'sid-1')
            self.assertEqual(wrapper[1]['env']['SPARK_EXCLUSIVE_SESSION_OWNER'], 'owner-1')
            self.assertEqual(out['modelRun'], 'completed')
            fake_run.fail = True
            self.assertEqual(round_tool.run_models(args, self.work, self.work)['modelRun'], 'failed')

    def test_run_models_requires_media_and_session_before_anything_starts(self):
        with self.assertRaisesRegex(SystemExit, 'needs --media'):
            round_tool.run_models(
                type('A', (), {'media': None, 'spark_session_id': 'x', 'spark_session_owner': 'y',
                               'remote_stage': 'z', 'translator_model': 'gpt-6.1-sol'})(),
                self.work, self.work)


if __name__ == '__main__':
    unittest.main()
