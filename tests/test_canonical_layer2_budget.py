import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import canonical_layer2_budget as budget
from scripts import canonical_layer2_controller as controller
from scripts import sermon_review_budget as ledger
from scripts import sermon_workflow_jobs as jobs
from tests import test_canonical_layer2_controller as fixtures


class CanonicalLayer2BudgetTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.CanonicalLayer2ControllerTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.config = controller.load_configuration(self.fixture.path)
        self.code = controller.code_identity()
        self.limits = dict(budget.limits.DEFAULT_REQUEST_LIMITS)
        amounts = dict(requests=10, inputTokens=200000, outputTokens=100000,
                       wallTimeMs=4000000, costMicrousd=10000000)
        root = self.config.job_root.parent / '.jobs.layer2-budget'
        binding = {'productionRunId': self.config.run_id, 'configurationSha256': self.config.sha256,
                   'codeIdentitySha256': self.code, 'budgetRoot': str(root), 'requestLimits': self.limits,
                   'globalBounds': amounts, 'unitBounds': amounts, 'limits': ledger.DEFAULT_LIMITS}
        self.receipt = self.fixture.root / 'approval.json'
        self.receipt.write_text(json.dumps({'schemaVersion': 'sermon-canonical-layer2-budget-approval-v1',
            'binding': binding, 'humanApproval': True, 'decision': 'approved',
            'reviewedBy': 'fixture operator', 'reviewedAt': '2026-10-04T00:00:00Z',
            'operatorEvidence': 'Synthetic authorization for injected transport only'}))
        self.auth_path = self.fixture.root / 'budget.json'
        self.auth_path.write_text(json.dumps({'schemaVersion': budget.SCHEMA,
            'productionRunId': self.config.run_id, 'configurationSha256': self.config.sha256,
            'codeIdentitySha256': self.code, 'requestLimits': self.limits,
            'authority': {'approvalSha256': budget.sha(self.receipt), 'globalBounds': amounts,
                          'unitBounds': amounts, 'limits': ledger.DEFAULT_LIMITS},
            'approvalReceipt': 'approval.json'}))
        self.auth = budget.load_authorization(self.config, self.auth_path, self.code)
        f = self.fixture.fixture.fixture
        self.source, self.anchor = f.source, f.anchor
        # Unit tests retain the frozen historical API budget contract. The
        # migrated production policy is tested separately for zero dispatch.
        self.policy = json.loads(json.dumps(f.policy))
        self.policy["translator"].update(model="gpt-6-astra", reasoningEffort="medium")
        self.policy["reviewer"].update(model="gpt-6-sol", reasoningEffort="medium")
        self.payload = budget.limits.bounded_payload({'model': 'gpt-6-astra', 'reasoning_effort': 'medium',
            'messages': [{'role': 'user', 'content': 'A full sentence.'}],
            'response_format': {'type': 'json_object'}}, self.limits)

    def test_missing_authority_blocks_drive_without_job_or_budget_writes(self):
        before = self.fixture.files()
        result = controller.drive(self.fixture.path, 'zh-Hans')
        self.assertEqual(result['reason'], 'bound_budget_authorization_required')
        self.assertEqual(self.fixture.files(), before)

    def test_authorized_drive_starts_existing_durable_worker_with_budget_binding(self):
        def start(root, ident, command, **kwargs):
            self.assertEqual(root, self.config.job_root)
            self.assertIn('--budget-authorization', command)
            self.assertIn(budget.sha(self.auth_path), command)
            return {'jobId': jobs._digest(ident), 'status': 'queued'}
        with patch.object(jobs, 'start_job', side_effect=start) as mocked:
            result = controller.drive(self.fixture.path, 'zh-Hans', budget_authorization=self.auth_path)
        self.assertEqual(result['status'], 'waiting')
        self.assertTrue(result['dispatched'])
        mocked.assert_called_once()

    def test_unknown_keeps_full_reservation_and_prevents_second_transport(self):
        calls = []
        def transport(*args):
            calls.append(1)
            raise TimeoutError('synthetic unknown')
        caller = budget.BudgetedCaller(self.auth, self.config, self.source, self.anchor,
                                       self.policy, transport=transport)
        with self.assertRaises(TimeoutError):
            caller('', self.payload)
        with self.assertRaisesRegex(ValueError, 'budget_reconciliation_required'):
            caller('', self.payload)
        self.assertEqual(calls, [1])
        data = jobs._read(self.auth['root'] / ledger.STORE_ID / 'state.json')
        row = next(iter(data['reservations'].values()))
        self.assertEqual(row['phase'], 'request')
        self.assertGreater(row['request']['bounds']['costMicrousd'], 0)

    def test_provider_payload_cap_is_enforced_before_transport(self):
        unbounded = dict(self.payload)
        unbounded.pop('max_completion_tokens')
        calls = []
        caller = budget.BudgetedCaller(self.auth, self.config, self.source, self.anchor,
                                       self.policy, transport=lambda *args: calls.append(1))
        with self.assertRaisesRegex(ValueError, 'bounded_before_cache_identity'):
            caller('', unbounded)
        self.assertEqual(calls, [])
        self.assertFalse(self.auth['root'].exists())

    def test_approval_drift_blocks_dispatch(self):
        self.receipt.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'budget_approval_not_bound'):
            budget.load_authorization(self.config, self.auth_path, self.code)

    def test_new_api_policy_blocks_without_spark_before_model_dispatch(self):
        from scripts import canonical_durable_jobs as durable
        view = controller.package_view(self.config)
        ident = durable.identity(view, self.config.run_id, 'text.zh-Hans')
        key = jobs._digest(ident)
        command = controller._worker_command(self.config, 'zh-Hans', key, self.code, self.auth)
        request = {'schemaVersion': jobs.SCHEMA, 'jobId': key, 'identity': ident,
                   'command': command, 'commandSha256': jobs._digest(command),
                   'timeoutSeconds': 21600.0, 'livenessPolicy': controller.LIVENESS_POLICY}
        with jobs._lock(self.config.job_root, key) as (folder, _, held):
            self.assertTrue(held)
            folder.mkdir()
            jobs._persist(folder / 'request.json', request)
            jobs._persist(folder / 'state.json', {'schemaVersion': jobs.SCHEMA, 'jobId': key,
                'status': 'running', 'requestSha256': jobs._digest(request)})
            with patch('scripts.codex_layer2_transport.CodexLayer2Transport', side_effect=AssertionError('CLI dispatch forbidden')) as cli:
                with self.assertRaisesRegex(Exception, 'spark_exclusive_session_required'):
                    controller.execute(self.config.path, 'zh-Hans', self.config.sha256,
                        self.code, key, budget_authorization=self.auth_path, expected_budget=self.auth['sha256'])
                cli.assert_not_called()
        self.assertFalse(self.auth['root'].exists())
        self.assertFalse(list(self.config.lanes['zh-Hans']['output'].glob('*-astra.started.json')))
