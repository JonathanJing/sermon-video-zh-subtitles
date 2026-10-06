"""Offline budget, validation and crash-resume checks; no provider calls."""
import copy
from decimal import Decimal
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts.experiments import decision_api_weekly_ab as ab
from scripts.experiments.decision_api_cases_rules import build_rule_cases


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.case = next(c for c in build_rule_cases() if c['stageId'] == 'E03')
        self.bound = ab.authority(self.root, [self.case], Decimal('20'), 200, 'user test authority')
        self.ledger = ab.Ledger(self.root, self.bound)

    def response(self):
        answers = []
        for q in self.case['b']['questions']:
            chosen = self.case['expected']['labels'][q['name']]
            answers.append({'name': q['name'], 'type': 'choice', 'choice': chosen,
                            'confidence': .9, 'probabilities': [
                                {'value': o['value'], 'probability': 1 if o['value'] == chosen else 0}
                                for o in q['choices']]})
        return {'model': 'gpt-6-luna', 'answers': answers,
                'usage': {'input_tokens': 100, 'output_tokens': 0}}

    def test_case_identity_and_evidence_are_checked(self):
        ab.validate_cases([self.case])
        bad = copy.deepcopy(self.case)
        bad['caseId'] = '..'
        with self.assertRaises(ValueError): ab.validate_cases([bad])
        bad = copy.deepcopy(self.case)
        bad['b']['input'] = '{}'
        with self.assertRaises(ValueError): ab.validate_cases([bad])
        with self.assertRaises(ValueError): ab.validate_cases([self.case, self.case])

    def test_invalid_distribution_and_refusal(self):
        good = self.response()
        self.assertEqual(ab.normalize_b(self.case, good)['labels'], self.case['expected']['labels'])
        bad = copy.deepcopy(good)
        bad['answers'][0]['probabilities'][0]['probability'] = float('nan')
        with self.assertRaises(ValueError): ab.normalize_b(self.case, bad)
        bad = copy.deepcopy(good)
        bad['answers'][0]['probabilities'][0]['probability'] = .4
        with self.assertRaises(ValueError): ab.normalize_b(self.case, bad)
        bad = copy.deepcopy(good)
        bad['answers'][0] = {'name': bad['answers'][0]['name'], 'type': 'refusal'}
        self.assertEqual(ab.normalize_b(self.case, bad)['status'], 'refusal')

    def test_budget_reservation_and_unknown_are_not_retried(self):
        calls = []
        def unknown(*args):
            calls.append(args)
            return {'status': 'outcome_unknown'}
        first = ab.measured_attempt(self.case, 'B', mode='live', directory=self.root/'live',
                                    ledger=self.ledger, dispatcher=unknown)
        second = ab.measured_attempt(self.case, 'B', mode='live', directory=self.root/'live',
                                     ledger=self.ledger, dispatcher=unknown)
        self.assertEqual(len(calls), 1)
        self.assertEqual(first['status'], 'outcome_unknown')
        self.assertTrue(second['restored'])
        self.assertEqual(second['timings'], first['timings'])
        self.assertEqual(self.ledger.summary()['unsettledAttempts'], 1)
        # Simulate process loss after reservation and before a receipt.
        (self.root/'live'/self.case['stageId']/self.case['caseId']/'B'/'receipt.json').unlink()
        third = ab.measured_attempt(self.case, 'B', mode='live', directory=self.root/'live',
                                    ledger=self.ledger, dispatcher=unknown)
        self.assertEqual(third['status'], 'blocked_prior_operation')
        self.assertEqual(len(calls), 1)

    def test_budget_cannot_be_overbooked_or_changed(self):
        tiny = {**self.bound, 'maxCostMicrousd': 10}
        ledger = ab.Ledger(self.root, tiny)
        bounds = {'costMicrousd': 7, 'requests': 1}
        ledger.reserve('one', {'hash': 'same'}, bounds)
        with self.assertRaises(ValueError): ledger.reserve('two', {}, bounds)
        with self.assertRaises(ValueError): ledger.reserve('one', {'hash': 'changed'}, bounds)
        self.assertFalse(ledger.reserve('one', {'hash': 'same'}, bounds)[0])

    def test_usage_estimate_requires_known_model_and_tier(self):
        result = self.response()
        self.assertEqual(ab.measured_usage(result, 'decisions')[1], 11)
        chat = {'model': 'gpt-6.1-sol', 'service_tier': 'fast',
                'usage': {'prompt_tokens': 100, 'completion_tokens': 10}}
        self.assertIsNone(ab.measured_usage(chat, 'chat')[1])
        chat['service_tier'] = 'default'
        self.assertEqual(ab.measured_usage(chat, 'chat')[1], 385)

    def test_observed_bound_excess_stops_new_dispatch(self):
        response = self.response()
        response['usage']['input_tokens'] = 1000000
        row = ab.measured_attempt(self.case, 'B', mode='live', directory=self.root/'live',
                                  ledger=self.ledger, dispatcher=lambda *_: {'status': 'returned', 'response': response})
        self.assertEqual(row['status'], 'budget_bound_exceeded')
        with self.assertRaises(ValueError): self.ledger.reserve('next', {}, {'costMicrousd': 1})

    def test_offline_does_not_dispatch_and_cannot_claim_quality(self):
        with patch.object(ab, 'dispatch', side_effect=AssertionError('no network')):
            a = ab.measured_attempt(self.case, 'A', mode='offline', directory=self.root/'offline')
            b = ab.measured_attempt(self.case, 'B', mode='offline', directory=self.root/'offline')
        self.assertEqual(a['status'], 'validated')
        self.assertEqual(b['status'], 'network_not_run')
        s = ab.summarize([self.case], [a, b])['stages']['E03']
        self.assertEqual(s['validPairs'], 0)
        self.assertFalse(s['productionReplacementEligible'])

    def test_atomic_private_and_separate_output_identity(self):
        target = self.root/'private'/'receipt.json'
        ab.atomic(target, {'ok': True})
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(target.parent.stat().st_mode & 0o777, 0o700)
        changed = {**self.bound, 'root': str(self.root/'elsewhere')}
        with self.assertRaises(ValueError): ab.Ledger(self.root, changed)

    def test_dispatch_requires_dev_launcher_before_network(self):
        with patch.dict(ab.os.environ, {}, clear=True):
            with self.assertRaises(ValueError): ab.dispatch('decisions', {}, 1)


if __name__ == '__main__': unittest.main()
