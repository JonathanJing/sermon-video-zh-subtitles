"""Original Source/context, shared quota and pending-gate continuation checks."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import sermon_accounting as accounting
from scripts import sermon_diagnostic_dag_session as session
from scripts import sermon_review_budget as budget
from scripts import sermon_review_contracts as c
from tests.diagnostic_dag_fixture import DiagnosticDAGFixture


class DiagnosticSessionTests(unittest.TestCase):
    def setUp(self):
        self.f = DiagnosticDAGFixture()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        # Development working trees may be dirty. Only the code-identity gate
        # is substituted in these unit checks; source/budget/receipts are real.
        self.identity = self.f.continuation['executionIdentity']
        self.enterContext(patch.object(accounting, 'execution_identity', return_value=self.identity))

    def make(self, transport=None, **kwargs):
        return session.DiagnosticSession(self.f.plan, self.f.continuation,
            offline_transport=transport or self.f.transport, request_limits=self.f.request_limits, **kwargs)

    def test_full_existing_source_locale_replay_keeps_original_calls_and_pending_gates(self):
        current = self.make()
        before = c.read_snapshot(self.f.root/'budget'/budget.STORE_ID/'provider-run/state.json')[0]
        with self.f.session():
            source = current.inspect_source()
            result = current.run_locale('zh-Hans', self.f.locale_specs['zh-Hans'])
            replay = self.make().run_locale('zh-Hans', self.f.locale_specs['zh-Hans'])
        self.assertEqual(source['newASRCalls'], 0)
        self.assertEqual(source['newSourceCheckCalls'], 0)
        self.assertEqual(result['status'], 'waiting_human')
        self.assertEqual(result['candidateSha256'], replay['candidateSha256'])
        self.assertEqual(len(self.f.transport.observations), 6)
        after = c.read_snapshot(self.f.root/'budget'/budget.STORE_ID/'provider-run/state.json')[0]
        self.assertEqual(before['startedMonotonic'], after['startedMonotonic'])
        self.assertEqual(before['config'], after['config'])
        for call, receipt in before['requests'].items():
            self.assertEqual(receipt, after['requests'][call])
        candidate = c.read_snapshot(Path(result['output'])/'candidate.json')[0]
        self.assertEqual(candidate['humanReview']['translation'], 'pending')
        self.assertFalse(candidate['releaseEligible'])

    def test_explicit_limits_are_frozen_across_continuation_restart(self):
        current = self.make()
        lower = {**self.f.request_limits, 'maxInputTokens': 8192}
        with self.assertRaisesRegex(ValueError, 'immutable_strict_artifact_changed'):
            session.DiagnosticSession(self.f.plan, self.f.continuation,
                offline_transport=self.f.transport, request_limits=lower)
        self.assertEqual(current.binding['requestLimits'], self.f.request_limits)
        self.assertEqual(len(self.f.transport.observations), 2)
        current.subject.limits = lower
        with self.f.session(), self.assertRaisesRegex(ValueError, 'diagnostic_dag_binding_changed'):
            current.inspect_source()
        self.assertEqual(len(self.f.transport.observations), 2)

    def test_real_credentials_or_missing_offline_marker_cannot_adopt_existing_run(self):
        state = self.f.root/'budget'/budget.STORE_ID/'provider-run/state.json'
        before = state.read_bytes()
        with self.assertRaisesRegex(ValueError, 'explicit_transport_required'):
            self.make(key='not-a-real-key')
        (self.f.root/'offline-business-scope.json').unlink()
        with self.assertRaises((ValueError, OSError)):
            self.make()
        self.assertEqual(state.read_bytes(), before)
        self.assertEqual(len(self.f.transport.observations), 2)

    def test_live_mode_requires_explicit_execute_and_cannot_use_fixture_store(self):
        with self.assertRaisesRegex(ValueError, 'explicit_transport_required'):
            session.DiagnosticSession(self.f.plan, self.f.continuation, key='fixture-not-a-key')
        with self.assertRaisesRegex(ValueError, 'fixture_cannot_become_live'):
            session.DiagnosticSession(self.f.plan, self.f.continuation,
                                      key='fixture-not-a-key', execute=True)
        self.assertEqual(len(self.f.transport.observations), 2)

    def test_unknown_or_expired_original_provider_blocks_without_renewal(self):
        path = self.f.root/'budget'/budget.STORE_ID/'provider-run/state.json'
        original = path.read_bytes()
        for mode in ('unknown', 'expired'):
            state = c.decode_json(original)
            if mode == 'unknown':
                next(iter(state['requests'].values()))['state'] = 'outcome_unknown'
            else:
                state['startedMonotonic'] -= state['config']['totalWallSeconds'] + 1
            path.write_bytes(c.canonical_bytes(state))
            before = path.read_bytes()
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.make()
            self.assertEqual(path.read_bytes(), before)
        self.assertEqual(len(self.f.transport.observations), 2)

    def test_changed_source_and_outside_locale_input_rejected_before_new_call(self):
        current = self.make()
        spec = deepcopy(self.f.locale_specs['zh-Hans'])
        outside = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()/'policy.json'
        outside.write_bytes(Path(spec['policy']).read_bytes())
        spec['policy'] = str(outside)
        with self.f.session(), self.assertRaisesRegex(ValueError, 'outside_scope'):
            current.run_locale('zh-Hans', spec)
        original = self.f.root/'source-review-request.json'
        value = json.loads(original.read_text())
        value['machineIssues'][0]['reviewStatus'] = 'approved'
        original.write_text(json.dumps(value))
        with self.f.session(), self.assertRaises(ValueError):
            current.inspect_source()
        self.assertEqual(len(self.f.transport.observations), 2)

    def test_preview_cannot_substitute_candidate_or_skip_failed_machine_review(self):
        current = self.make()
        with self.f.session(), self.assertRaisesRegex(ValueError, 'machine_candidate_required'):
            current.preview('zh-Hans', self.f.preview_specs['zh-Hans'])
        with self.f.session():
            current.run_locale('zh-Hans', self.f.locale_specs['zh-Hans'])
            spec = deepcopy(self.f.preview_specs['zh-Hans'])
            spec['paths']['candidate'] = str(self.f.root/'arbitrary.json')
            with self.assertRaisesRegex(ValueError, 'candidate_owned_by_locale'):
                current.preview('zh-Hans', spec)
        self.assertFalse((self.f.root/'diagnostic-previews').exists())


if __name__ == '__main__':
    unittest.main()
