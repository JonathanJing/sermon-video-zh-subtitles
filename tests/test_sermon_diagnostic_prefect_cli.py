"""Explicit live CLI wiring only: no credential discovery or real dispatch."""
from copy import deepcopy
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import sermon_accounting as accounting
from scripts import sermon_diagnostic_prefect_flow as flow
from scripts import sermon_provider_http as http
from scripts import sermon_review_budget as budget
from tests.diagnostic_dag_fixture import DiagnosticDAGFixture


class DiagnosticCLITests(unittest.TestCase):
    def setUp(self):
        self.f = DiagnosticDAGFixture(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.enterContext(patch.object(accounting, 'execution_identity', return_value=self.f.execution_identity))
        self.config = {'schemaVersion': flow.SCHEMA, 'locales': {'zh-Hans': {
            'localeSpec': deepcopy(self.f.locale_specs['zh-Hans']),
            'previewSpec': deepcopy(self.f.preview_specs['zh-Hans'])}}}
        self.config['locales']['zh-Hans']['previewSpec']['execute'] = True
        self.spec = self.f.root/'flow.json'
        self.spec.write_text(json.dumps(self.config))
        self.args = ['--plan', str(self.f.root/'run-plan.json'), '--continuation',
                     str(self.f.root/'continuation.json'), '--spec', str(self.spec),
                     '--execute', '--key-fd', '9']

    def test_live_fixture_refusal_happens_before_credential_read(self):
        with patch.object(flow, '_read_key_fd') as read_key, self.assertRaisesRegex(
                ValueError, 'fixture_cannot_become_live'):
            flow.main(self.args)
        read_key.assert_not_called()
        self.assertEqual(len(self.f.transport.observations), 2)

    def test_expired_original_window_and_invalid_locale_preflight_precede_key(self):
        (self.f.root/'offline-business-scope.json').unlink()
        path = self.f.root/'budget'/budget.STORE_ID/'provider-run/state.json'
        before = path.read_bytes()
        state = json.loads(before)
        state['startedMonotonic'] -= state['config']['totalWallSeconds'] + 1
        path.write_text(json.dumps(state))
        with patch.object(flow, '_read_key_fd') as read_key, self.assertRaises(ValueError):
            flow.main(self.args)
        read_key.assert_not_called()
        path.write_bytes(before)
        policy = Path(self.config['locales']['zh-Hans']['localeSpec']['policy'])
        value = json.loads(policy.read_text()); value['sourceScope']['englishSourcePackageJsonSha256'] = '0'*64
        policy.write_text(json.dumps(value))
        with patch.object(flow, '_read_key_fd') as read_key, self.assertRaises(ValueError):
            flow.main(self.args)
        read_key.assert_not_called()
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(len(self.f.transport.observations), 2)

    def test_valid_live_wiring_uses_bounded_default_executor_and_does_not_log_key(self):
        # Test-only conversion of an entirely synthetic store, never real data.
        (self.f.root/'offline-business-scope.json').unlink()
        def inspect_only(session, config):
            self.assertFalse(session.offline_fixture)
            self.assertEqual(session.evidence_mode, 'current_execution')
            self.assertIs(session.subject.executor, http.execute)
            self.assertEqual(session.subject.store.store_sha256, self.f.store.store_sha256)
            self.assertEqual(session.deadline, self.f.state['startedMonotonic'] + self.f.config['totalWallSeconds'])
            self.assertNotIn('fixture-private-key', json.dumps(session.binding))
            return {'status': 'wiring_checked_without_execution'}
        with patch.object(flow, '_read_key_fd', return_value='fixture-private-key'), \
                patch.object(flow, 'run', side_effect=inspect_only) as execute, \
                patch('sys.stdout', new=io.StringIO()) as output:
            flow.main(self.args)
        execute.assert_called_once()
        self.assertNotIn('fixture-private-key', output.getvalue())
        self.assertEqual(len(self.f.transport.observations), 2)


if __name__ == '__main__':
    unittest.main()
