"""Mock-only capability, shared slot and complete machine-chain checks."""
import copy
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.production_concurrency_profile import profile_v1, validate_profile
from scripts import codex_layer2_resources as admission
from scripts import canonical_layer2_controller as controller
from scripts import run_target_language_models as runner
from scripts.sermon_unified import resources


class ProfileTests(unittest.TestCase):
    def test_exact_explicit_version_and_no_mutable_global(self):
        profile = profile_v1()
        self.assertEqual(profile['businessCodexSlots'] + profile['supervisorSlots'], profile['totalCodexSlots'])
        profile['businessCodexSlots'] = 24
        with self.assertRaises(ValueError):
            validate_profile(profile)
        self.assertEqual(profile_v1()['businessCodexSlots'], 23)

    def test_23_worker_executor_is_opt_in_and_preserves_source_order(self):
        with self.assertRaises(ValueError):
            runner.ordered_group_results(list(range(46)), lambda x: x, 23)
        lock = threading.Lock()
        live = peak = 0
        def worker(index):
            nonlocal live, peak
            with lock:
                live += 1
                peak = max(peak, live)
            time.sleep(.01)
            with lock:
                live -= 1
            return index
        result = runner.ordered_group_results(list(range(46)), worker, 23, maximum_workers=23)
        self.assertEqual(result, list(range(46)))
        self.assertGreater(peak, 16)
        self.assertLessEqual(peak, 23)

    def test_three_locales_only_with_capability_and_unknown_still_blocks(self):
        instance = controller.Controller.__new__(controller.Controller)
        instance.config = SimpleNamespace(concurrency_profile=None)
        view = {'durableJobInspection': {'jobs': [{'workUnitId': 'text.zh-Hans', 'status': 'running'}]}}
        self.assertTrue(instance._capacity_full(view))
        instance.config.concurrency_profile = profile_v1()
        self.assertFalse(instance._capacity_full(view))
        view['durableJobInspection']['jobs'] *= 3
        self.assertTrue(instance._capacity_full(view))
        view['durableJobInspection']['jobs'] = [{'workUnitId': 'text.ko', 'status': 'uncertain'}]
        self.assertTrue(instance._capacity_full(view))


class SharedPoolTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.profile = profile_v1()
        self.policy = {'schemaVersion': resources.POLICY_VERSION, 'brokerRoot': str(self.root / 'broker'),
                       'capacities': {name: (24 if name == 'codex_cli' else 1)
                                      for name in resources.RESOURCE_LIMITS}}
        resources.validate_policy(self.policy)

    def reserve(self, number, role='business'):
        owner = {'resourceClass': role, 'callId': str(number)}
        return admission.reserve_classified(self.policy, operation_id='test:' + str(number), owner=owner,
                                            resource_class=role, profile=self.profile)

    def test_business_23_reserves_supervisor_one_and_never_25(self):
        for index in range(23):
            self.assertTrue(self.reserve(index))
        self.assertFalse(self.reserve(23))
        self.assertTrue(self.reserve('supervisor', 'supervisor'))
        self.assertFalse(self.reserve('second-supervisor', 'supervisor'))
        resources.release(self.policy, operation_id='test:0', owner={'resourceClass': 'business', 'callId': '0'})
        self.assertTrue(self.reserve('next-business'))

    def test_legacy_or_unrecognized_owner_class_counts_as_business(self):
        self.assertTrue(resources.reserve(self.policy, operation_id='legacy', owner={'resourceClass': 'other'},
                                          resource='codex_cli', units=1))
        for index in range(22):
            self.assertTrue(self.reserve(index))
        self.assertFalse(self.reserve('business-full'))
        self.assertTrue(self.reserve('supervisor', 'supervisor'))

    def test_unknown_dispatch_retains_capacity_and_duplicate_cannot_replay(self):
        permit = admission.Admission(self.policy, call_id='unknown', identity={'fixture': True},
            receipt_directory=self.root / 'call', concurrency_profile=self.profile)
        permit.reserve()
        with self.assertRaises(TimeoutError):
            with permit.dispatch():
                raise TimeoutError('unknown')
        with self.assertRaisesRegex(Exception, 'already_reserved'):
            admission.Admission(self.policy, call_id='unknown', identity={'fixture': True},
                receipt_directory=self.root / 'call', concurrency_profile=self.profile).reserve()
        for index in range(22):
            self.assertTrue(self.reserve(index))
        self.assertFalse(self.reserve('full'))

    def test_busy_wait_expiration_does_not_create_model_started_marker(self):
        for index in range(23):
            self.assertTrue(self.reserve(index))
        permit = admission.Admission(self.policy, call_id='busy', identity={'fixture': True},
            receipt_directory=self.root / 'busy', concurrency_profile=self.profile)
        with patch('scripts.codex_layer2_resources.time.monotonic', side_effect=[0, 181]):
            with self.assertRaisesRegex(Exception, 'resource_broker_busy'):
                permit.reserve()
        self.assertFalse(permit.reserved)
        self.assertFalse(any(self.root.rglob('*.started.json')))


class DiagnosticCapabilityTests(unittest.TestCase):
    def test_config_capability_and_broker_are_bound_and_tampering_is_rejected(self):
        from tests.test_canonical_layer2_controller import CanonicalLayer2ControllerTests
        helper = CanonicalLayer2ControllerTests()
        helper.setUp()
        self.addCleanup(helper.doCleanups)
        legacy = controller.load_configuration(helper.path)
        (helper.root / 'profile.json').write_text(json.dumps(profile_v1()))
        policy = {'schemaVersion': resources.POLICY_VERSION, 'brokerRoot': str(helper.root / 'broker'),
                  'capacities': {name: (24 if name == 'codex_cli' else 1) for name in resources.RESOURCE_LIMITS}}
        (helper.root / 'resources.json').write_text(json.dumps(policy))
        helper.config_data.update(schemaVersion=controller.CONCURRENT_SCHEMA,concurrencyProfile='profile.json', resourcePolicy='resources.json')
        helper.save_config()
        helper.config_data['schemaVersion']=controller.SCHEMA
        helper.save_config()
        with self.assertRaisesRegex(ValueError,'invalid_execution_configuration'):
            controller.load_configuration(helper.path)
        helper.config_data['schemaVersion']=controller.CONCURRENT_SCHEMA
        helper.save_config()
        enabled = controller.load_configuration(helper.path)
        self.assertNotEqual(legacy.sha256, enabled.sha256)
        self.assertEqual(enabled.concurrency_profile['maxActiveLocales'], 3)
        self.assertEqual(enabled.resource_policy, policy)
        policy['capacities']['codex_cli'] = 23
        (helper.root / 'resources.json').write_text(json.dumps(policy))
        with self.assertRaisesRegex(ValueError, 'shared_24_slot'):
            controller.load_configuration(helper.path)

    def test_runner_busy_hook_never_records_started_or_dispatches(self):
        from tests.test_codex_layer2_diagnostic import DiagnosticChainTests
        from scripts import codex_layer2_diagnostic as diagnostic
        helper = DiagnosticChainTests()
        helper.setUp()
        self.addCleanup(helper.doCleanups)
        helper.freeze(concurrency_profile=profile_v1())
        inputs = diagnostic.load_fixture(helper.fixture)
        transport = helper.transport()
        transport.execution_identity['concurrencyProfile'] = profile_v1()
        with patch.object(transport, 'admit_resource', side_effect=ValueError('resource_broker_busy')), \
             patch('scripts.codex_layer2_transport.subprocess.run', side_effect=AssertionError('dispatch forbidden')):
            with self.assertRaisesRegex(ValueError, 'resource_broker_busy'):
                diagnostic.run_chain(inputs, helper.out, transport)
        self.assertFalse(any(helper.out.rglob('*.started.json')))

    def test_explicit_profile_runs_actual_machine_chain_and_resumes_without_calls(self):
        from tests.test_codex_layer2_diagnostic import DiagnosticChainTests
        from scripts import codex_layer2_diagnostic as diagnostic
        helper = DiagnosticChainTests()
        helper.setUp()
        self.addCleanup(helper.doCleanups)
        helper.freeze(concurrency_profile=profile_v1())
        transport = helper.transport()
        transport.execution_identity['concurrencyProfile'] = profile_v1()
        lock = threading.Lock()
        def process(*args, **kwargs):
            with lock:
                return helper.process(*args, **kwargs)
        resource_path=helper.root/'resource-policy.json'
        resource_path.write_text(json.dumps({'schemaVersion':resources.POLICY_VERSION,
            'brokerRoot':str(helper.root/'broker'),'capacities':{'cpu':4,'online_api':4,'codex_cli':24,'spark_tts':1,'publisher':1}}))
        with patch.object(runner, 'ordered_group_results', wraps=runner.ordered_group_results) as executor:
            result = helper.invoke(transport=transport, process=process,resource_policy_path=resource_path)
        self.assertEqual(executor.call_args.args[2], 23)
        self.assertEqual(executor.call_args.kwargs['maximum_workers'], 23)
        self.assertEqual(len(helper.calls), 4)
        candidate = json.loads((helper.out / 'diagnostic-candidate.json').read_text())
        self.assertFalse(candidate['productionEligible'] or candidate['releaseEligible'])
        self.assertEqual(candidate['candidate']['humanReview']['translation'], 'pending')
        self.assertEqual(helper.invoke(transport=transport, process=lambda *_a, **_k: self.fail('resume dispatched'),resource_policy_path=resource_path), result)
        inputs = diagnostic.load_fixture(helper.fixture)
        wrong = helper.transport()
        with self.assertRaisesRegex(ValueError, 'concurrency capability'):
            diagnostic.run_chain(inputs, helper.out, wrong)


if __name__ == '__main__':
    unittest.main()
