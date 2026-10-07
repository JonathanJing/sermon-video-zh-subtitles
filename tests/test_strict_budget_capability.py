"""Offline DEV-R242-026 admission. No keys, network, or model calls."""
import unittest

from scripts import sermon_provider_limits as limits
from scripts import strict_budget_capability as gate


def payload(model='gpt-6.1-sol'):
    raw = {'model': model, 'reasoning_effort': 'high',
           'messages': [{'role': 'system', 'content': 'Return JSON.'},
                        {'role': 'user', 'content': 'synthetic'}],
           'response_format': {'type': 'json_object'}}
    return limits.bounded_payload(raw, limits.DEFAULT_REQUEST_LIMITS)


class StrictBudgetCapabilityTests(unittest.TestCase):
    def test_default_tier_api_reserves_worst_case_completion_cap(self):
        request = payload()
        for surface in gate.RESERVING:
            decision = gate.admit(surface, payload=request, substitutes={'creditEstimate': 1})
            self.assertEqual(decision['decision'], 'reserved')
            self.assertEqual(decision['requests'], 1)
            self.assertEqual(decision['outputTokenCap'], 4096)
            self.assertGreater(decision['reservationMicrousd'], 0)
            self.assertFalse(decision['invoiceVerified'])
            self.assertFalse(decision['dispatched'])
            self.assertEqual(decision['ignoredSubstitutes'], ['creditEstimate'])

    def test_credit_timeout_and_average_do_not_change_the_reservation(self):
        request = payload()
        plain = gate.admit('canonical_api', payload=request)
        substituted = gate.admit('canonical_api', payload=request, substitutes={
            'timeoutSeconds': 1, 'averageCostMicrousd': 1,
            'creditEstimate': 1, 'historicalMeanOutputTokens': 1})
        self.assertEqual(plain['reservationMicrousd'], substituted['reservationMicrousd'])

    def test_unbounded_fast_and_non_strict_surfaces_send_nothing(self):
        unbounded = {'model': 'gpt-6.1-sol', 'reasoning_effort': 'high', 'service_tier': 'fast',
                     'messages': [{'role': 'user', 'content': 'synthetic'}],
                     'response_format': {'type': 'json_object'}}
        with self.assertRaisesRegex(ValueError, 'unsupported_budget_capability'):
            gate.admit('canonical_api', payload=unbounded)
        for surface, reason in gate.REFUSED.items():
            decision = gate.admit(surface, payload=unbounded, substitutes={'averageCostMicrousd': 0})
            self.assertEqual(decision['decision'], 'refused')
            self.assertEqual(decision['reason'], reason)
            self.assertEqual(decision['requests'], 0)
            self.assertIsNone(decision['reservationMicrousd'])
            self.assertFalse(decision['dispatched'])

    def test_unknown_usage_keeps_reservation_and_does_not_retry(self):
        reserved = gate.admit('study_api', payload=payload())['reservationMicrousd']
        unknown = gate.reconcile_unknown(reserved, None)
        self.assertEqual(unknown['status'], 'unknown')
        self.assertEqual(unknown['reservationMicrousd'], reserved)
        self.assertFalse(unknown['released'])
        self.assertFalse(unknown['retry'])
        self.assertIsNone(unknown['settledMicrousd'])

    def test_codex_cli_identity_is_rejected_before_dispatch(self):
        class CodexLayer2Transport:
            execution_identity = {'backend': 'codex_cli'}

            def __call__(self, *_args):
                raise AssertionError('cli dispatched')

        with self.assertRaisesRegex(ValueError, 'unsupported_budget_capability'):
            gate.reject_codex_cli_transport(CodexLayer2Transport())
        gate.reject_codex_cli_transport(lambda *_args: None)


if __name__ == '__main__':
    unittest.main()
