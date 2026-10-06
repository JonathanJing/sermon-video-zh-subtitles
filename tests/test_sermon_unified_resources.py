"""Resource admission survives owner exits and never buys a second dispatch."""
import copy
from concurrent.futures import ThreadPoolExecutor
import multiprocessing
from pathlib import Path
import tempfile
import threading
import unittest

from scripts.sermon_unified import contracts, resources
from scripts import sermon_workflow_jobs as jobs


def _reserve_and_exit(policy, output):
    output.put(resources.reserve(policy, operation_id='exited-run', owner={'epoch': 1}, resource='spark_tts'))


class UnifiedResourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'broker'
        self.policy = {'schemaVersion': resources.POLICY_VERSION, 'brokerRoot': str(self.root),
                       'capacities': {'cpu': 2, 'online_api': 24, 'codex_cli': 24,
                                      'spark_tts': 1, 'publisher': 1}}

    def reserve(self, op='run1', owner='owner1', resource='spark_tts', **kwargs):
        return resources.reserve(self.policy, operation_id=op, owner=owner, resource=resource, **kwargs)

    def release(self, op='run1', owner='owner1'):
        resources.release(self.policy, operation_id=op, owner=owner)

    def ledger(self):
        return contracts.read(self.root / resources.BROKER_LOCK_ID / 'resources.json')

    def test_validation_is_read_only_and_rejects_invalid_capacity_types(self):
        self.assertEqual(resources.validate_policy(self.policy), self.policy)
        self.assertFalse(self.root.exists())
        for name, value in [('cpu', True), ('cpu', 2.0), ('codex_cli', 25),
                            ('online_api', 25), ('spark_tts', 2), ('publisher', 2), ('cpu', -1)]:
            policy = copy.deepcopy(self.policy)
            policy['capacities'][name] = value
            with self.subTest(name=name, value=value), self.assertRaises(contracts.ContractError):
                resources.validate_policy(policy)
        self.assertFalse(self.root.exists())

    def test_capacity_is_shared_across_runs_and_resources_are_independent(self):
        self.assertTrue(self.reserve())
        self.assertFalse(self.reserve('run2'))
        self.assertTrue(self.reserve('publisher-run', resource='publisher'))
        self.release()
        self.assertTrue(self.reserve('run2'))

    def test_unknown_outcome_keeps_slot_after_process_exit(self):
        ctx = multiprocessing.get_context('spawn')
        output = ctx.Queue()
        process = ctx.Process(target=_reserve_and_exit, args=(self.policy, output))
        process.start()
        process.join(10)
        self.assertFalse(process.is_alive())
        self.assertEqual(process.exitcode, 0)
        self.assertTrue(output.get(timeout=2))
        output.close()
        self.assertFalse(self.reserve('another-run'))
        with self.assertRaisesRegex(contracts.ContractError, 'resource_owner_changed'):
            self.release('exited-run', {'epoch': 2})
        self.assertFalse(self.reserve('another-run'))

    def test_repeat_reservation_and_owner_takeover_cannot_redispatch(self):
        self.assertTrue(self.reserve())
        with self.assertRaisesRegex(contracts.ContractError, 'already_reserved'):
            self.reserve()
        with self.assertRaisesRegex(contracts.ContractError, 'identity_changed'):
            self.reserve(owner='owner2')
        self.release()
        self.release()  # Terminal acknowledgement is idempotent.
        with self.assertRaisesRegex(contracts.ContractError, 'already_reserved'):
            self.reserve()
        self.assertEqual(next(iter(self.ledger()['reservations'].values()))['status'], 'released')

    def test_whole_stage_reserves_entire_online_pool(self):
        self.assertTrue(self.reserve('online-stage', resource='online_api', units=24))
        self.assertFalse(self.reserve('online-stage2', resource='online_api'))
        row = next(iter(self.ledger()['reservations'].values()))
        self.assertEqual(row['units'], 24)
        self.release('online-stage')
        self.assertTrue(self.reserve('online-stage2', resource='online_api', units=24))

    def test_units_are_positive_integral_and_identity_bound(self):
        for value in (True, 0, -1, 1.0, 25):
            with self.subTest(value=value), self.assertRaises(contracts.ContractError):
                self.reserve('online', resource='online_api', units=value)
        self.assertTrue(self.reserve('online', resource='online_api', units=2))
        with self.assertRaisesRegex(contracts.ContractError, 'identity_changed'):
            self.reserve('online', resource='online_api', units=1)

    def test_zero_capacity_stops_and_still_freezes_policy(self):
        self.policy['capacities']['codex_cli'] = 0
        self.assertFalse(self.reserve('disabled', resource='codex_cli'))
        self.policy['capacities']['codex_cli'] = 1
        with self.assertRaisesRegex(contracts.ContractError, 'policy_changed'):
            self.reserve('disabled', resource='codex_cli')

    def test_capacity_drift_is_rejected_after_release(self):
        self.reserve()
        self.release()
        self.policy['capacities']['cpu'] = 3
        with self.assertRaisesRegex(contracts.ContractError, 'policy_changed'):
            self.reserve('run2')

    def test_concurrent_admission_never_exceeds_shared_cpu_capacity(self):
        barrier = threading.Barrier(8)
        def worker(index):
            barrier.wait(timeout=3)
            return self.reserve(f'run{index}', resource='cpu')
        with ThreadPoolExecutor(max_workers=8) as pool:
            admitted = list(pool.map(worker, range(8)))
        self.assertGreaterEqual(sum(admitted), 1)
        self.assertLessEqual(sum(admitted), 2)
        held = [r for r in self.ledger()['reservations'].values() if r['status'] == 'held']
        self.assertEqual(sum(r['units'] for r in held), sum(admitted))

    def test_lock_contention_is_nonblocking_and_release_waits(self):
        self.reserve()
        with jobs._lock(self.root, resources.BROKER_LOCK_ID) as (_, _, held):
            self.assertTrue(held)
            self.assertFalse(self.reserve('other'))
            done = threading.Event()
            errors = []
            def releaser():
                try:
                    self.release()
                except Exception as exc:
                    errors.append(exc)
                finally:
                    done.set()
            thread = threading.Thread(target=releaser)
            thread.start()
            self.assertFalse(done.wait(.04))
        self.assertTrue(done.wait(3))
        thread.join()
        self.assertEqual(errors, [])
        self.assertTrue(self.reserve('other'))

    def test_symlink_and_relative_broker_paths_rejected_without_writes(self):
        real = Path(self.tmp.name) / 'real'
        real.mkdir()
        self.root.symlink_to(real, target_is_directory=True)
        with self.assertRaises(contracts.ContractError):
            resources.validate_policy(self.policy)
        self.assertEqual(list(real.iterdir()), [])
        for path in ('relative', '/', str(real / '..' / 'other')):
            policy = {**self.policy, 'brokerRoot': path}
            with self.subTest(path=path), self.assertRaises(contracts.ContractError):
                resources.validate_policy(policy)

    def test_duplicate_json_or_redirected_ledger_fails_closed(self):
        self.reserve()
        path = self.root / resources.BROKER_LOCK_ID / 'resources.json'
        original = path.read_text()
        path.write_text('{"schemaVersion":"x","schemaVersion":"y"}')
        with self.assertRaisesRegex(contracts.ContractError, 'duplicate_json_key'):
            self.reserve('next')
        path.unlink()
        outside = Path(self.tmp.name) / 'outside.json'
        outside.write_text(original)
        path.symlink_to(outside)
        with self.assertRaises(ValueError):
            self.reserve('next')
        self.assertEqual(outside.read_text(), original)


if __name__ == '__main__':
    unittest.main()
