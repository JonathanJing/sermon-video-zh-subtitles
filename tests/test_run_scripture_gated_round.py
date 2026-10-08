"""One-command gated round: validate, freeze, load; refusals leave no output.

Receipts are synthetic test inputs built from the pinned CUV text. They are not
human approvals, and no model is called (run_models is never exercised here).
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

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

    def test_machine_authored_receipt_is_refused_and_writes_nothing(self):
        with self.assertRaisesRegex(ValueError, 'decided_by_not_human'):
            self.run_round(self.receipt(decidedByRole='machine'), name='machine')
        self.assertFalse((self.work / 'machine').exists())

    def test_receipt_bound_to_other_source_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'receipt_binding_changed'):
            self.run_round(self.receipt(bindings={**self.bindings, 'anchor.json': 'f' * 64}), name='bound')
        self.assertFalse((self.work / 'bound').exists())

    def test_run_models_requires_media_and_session_before_anything_starts(self):
        with self.assertRaisesRegex(SystemExit, 'needs --media'):
            round_tool.run_models(
                type('A', (), {'media': None, 'spark_session_id': 'x', 'spark_session_owner': 'y',
                               'remote_stage': 'z', 'translator_model': 'gpt-6.1-sol'})(),
                self.work, self.work)


if __name__ == '__main__':
    unittest.main()
