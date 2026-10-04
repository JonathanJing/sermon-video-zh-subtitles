"""Pure in-memory checks for the success cache's exact keys and two bounds.

Budget tests replace only validation with a spy, so small deterministic payloads
can exercise eviction without depending on schema size. Public-path tests below
also validate real contract fixtures. No writer, transport, or model is used.
"""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import random
import threading
import unittest
from unittest.mock import patch

from scripts import sermon_log_contract as contract
from tests.test_accounting_log_contract import fixture


class CacheTestCase(unittest.TestCase):
    def setUp(self):
        self.clear_caches()
        self.schema = deepcopy(contract.validator().schema)
        self.enterContext(patch.object(contract.validator(), 'schema', self.schema))
        self.addCleanup(self.clear_caches)

    @staticmethod
    def clear_caches():
        with contract._schema_snapshot_lock:
            contract._validate_frozen_event.cache_clear()
            contract._schema_snapshots.clear()

    def assert_usage(self, payload_bytes, entries):
        self.assertEqual(contract._validate_frozen_event.cache_usage(), {
            'payloadBytes': payload_bytes,
            'maxPayloadBytes': contract.MAX_VALIDATION_CACHE_PAYLOAD_BYTES,
            'entries': entries,
            'maxEntries': contract.MAX_VALIDATION_CACHE_ENTRIES,
        })
        info = contract._validate_frozen_event.cache_info()
        self.assertEqual(info.currsize, entries)
        self.assertEqual(info.maxsize, contract.MAX_VALIDATION_CACHE_ENTRIES)

    def limits(self, *, entries, payload_bytes):
        self.enterContext(patch.object(contract, 'MAX_VALIDATION_CACHE_ENTRIES', entries))
        self.enterContext(patch.object(contract, 'MAX_VALIDATION_CACHE_PAYLOAD_BYTES', payload_bytes))


class ValidationCacheBudgetTests(CacheTestCase):
    def setUp(self):
        super().setUp()
        with contract._schema_snapshot_lock:
            self.schema_key, _ = contract._schema_snapshot()
        self.validate_spy = self.enterContext(
            patch.object(contract, '_validate_event_uncached', return_value=None))

    @staticmethod
    def payload(value, padding=0):
        return contract.canonical_bytes({'event': 'cache_test', 'value': value, 'padding': 'x' * padding})

    def validate(self, data, *, schema_key=None, version=None):
        return contract._validate_frozen_event(data,
            self.schema_key if schema_key is None else schema_key,
            contract.VERSION if version is None else version)

    def test_default_bounds_and_cache_info_compatibility(self):
        self.assertEqual(contract.MAX_VALIDATION_CACHE_ENTRIES, 8192)
        self.assertEqual(contract.MAX_VALIDATION_CACHE_PAYLOAD_BYTES, 16 * 1024 * 1024)
        self.assertEqual(contract.MAX_CACHED_EVENT_BYTES, 8 * 1024)
        info = contract._validate_frozen_event.cache_info()
        self.assertEqual(info._fields, ('hits', 'misses', 'maxsize', 'currsize'))
        self.assertEqual(tuple(info), (0, 0, 8192, 0))
        self.assert_usage(0, 0)

    def test_entry_bound_evicts_lru_and_a_hit_refreshes_recency(self):
        a, b, c = (self.payload(name) for name in 'abc')
        self.limits(entries=2, payload_bytes=sum(map(len, (a, b, c))))
        for data in (a, b, a, c):
            self.validate(data)
        self.assertEqual(self.validate_spy.call_count, 3)
        self.assert_usage(len(a) + len(c), 2)
        self.validate(a)
        self.assertEqual(self.validate_spy.call_count, 3)
        self.validate(b)
        self.assertEqual(self.validate_spy.call_count, 4)
        self.assert_usage(len(a) + len(b), 2)
        info = contract._validate_frozen_event.cache_info()
        self.assertEqual((info.hits, info.misses), (2, 4))

    def test_byte_bound_can_evict_multiple_lru_entries_for_one_success(self):
        a, b, c = (self.payload(name) for name in 'abc')
        d = self.payload('d', padding=len(a))
        self.assertEqual(len(d), 2 * len(a))
        self.limits(entries=10, payload_bytes=3 * len(a))
        for data in (a, b, c, a, d):
            self.validate(data)
        self.assert_usage(len(a) + len(d), 2)
        self.assertEqual(self.validate_spy.call_count, 4)
        for data in (a, d):
            self.validate(data)
        self.assertEqual(self.validate_spy.call_count, 4)
        self.validate(b)
        self.assertEqual(self.validate_spy.call_count, 5)
        self.assert_usage(len(d) + len(b), 2)

    def test_exact_budget_fits_and_one_byte_over_bypasses_without_eviction(self):
        exact = self.payload('a')
        larger = self.payload('a', padding=1)
        self.limits(entries=4, payload_bytes=len(exact))
        for data in (exact, exact, larger, larger, exact):
            self.validate(data)
        self.assertEqual(self.validate_spy.call_count, 3)
        self.assert_usage(len(exact), 1)

    def test_byte_accounting_uses_utf8_length_not_character_count(self):
        ascii_data = self.payload('a')
        unicode_data = self.payload('讲道')
        self.assertGreater(len(unicode_data), len(unicode_data.decode('utf-8')))
        self.limits(entries=10, payload_bytes=len(ascii_data) + len(unicode_data) - 1)
        self.validate(ascii_data)
        self.validate(unicode_data)
        self.assert_usage(len(unicode_data), 1)
        self.validate(unicode_data)
        self.assertEqual(self.validate_spy.call_count, 2)
        self.validate(ascii_data)
        self.assertEqual(self.validate_spy.call_count, 3)
        self.assert_usage(len(ascii_data), 1)

    def test_failed_validation_neither_consumes_budget_nor_evicts_successes(self):
        a, b, rejected = (self.payload(name) for name in ('a', 'b', 'rejected'))
        self.limits(entries=2, payload_bytes=len(a) + len(b))
        self.validate(a)
        self.validate(b)
        self.validate_spy.side_effect = contract.ContractError('invalid_contract_event')
        for _ in range(2):
            with self.assertRaisesRegex(contract.ContractError, '^invalid_contract_event$'):
                self.validate(rejected)
            self.assert_usage(len(a) + len(b), 2)
        self.validate_spy.side_effect = None
        self.validate(a)
        self.validate(b)
        self.assertEqual(self.validate_spy.call_count, 4)
        info = contract._validate_frozen_event.cache_info()
        self.assertEqual((info.hits, info.misses), (2, 4))

    def test_exact_payload_types_are_distinct_even_when_python_values_compare_equal(self):
        data = [self.payload(value) for value in (True, 1, 1.0)]
        self.assertEqual(len(set(data)), 3)
        for value in data + data:
            self.validate(value)
        self.assertEqual(self.validate_spy.call_count, 3)
        self.assert_usage(sum(map(len, data)), 3)

    def test_schema_and_version_keys_each_account_for_the_retained_payload(self):
        data = self.payload('a')
        self.validate(data)
        self.schema['$comment'] = 'second-cache-schema'
        with contract._schema_snapshot_lock:
            second_key, _ = contract._schema_snapshot()
        self.assertNotEqual(self.schema_key, second_key)
        self.validate(data, schema_key=second_key)
        self.validate(data, version='future-test-version')
        self.assert_usage(3 * len(data), 3)
        self.validate(data)
        self.validate(data, schema_key=second_key)
        self.validate(data, version='future-test-version')
        self.assertEqual(self.validate_spy.call_count, 3)

    def test_cache_clear_resets_bytes_entries_and_statistics(self):
        a, b = (self.payload(name) for name in 'ab')
        for data in (a, b, a):
            self.validate(data)
        self.assert_usage(len(a) + len(b), 2)
        contract._validate_frozen_event.cache_clear()
        self.assert_usage(0, 0)
        info = contract._validate_frozen_event.cache_info()
        self.assertEqual((info.hits, info.misses), (0, 0))
        self.validate(a)
        self.assertEqual(self.validate_spy.call_count, 3)
        self.assert_usage(len(a), 1)

    def test_usage_is_a_detached_snapshot_and_hits_do_not_add_payload_bytes(self):
        data = self.payload('a')
        self.validate(data)
        usage = contract._validate_frozen_event.cache_usage()
        usage.update(payloadBytes=-1, entries=-1)
        for _ in range(50):
            self.validate(bytes(bytearray(data)))
        self.assertEqual(self.validate_spy.call_count, 1)
        self.assertEqual(contract._validate_frozen_event.cache_info().hits, 50)
        self.assert_usage(len(data), 1)

    def test_zero_entry_or_byte_budget_disables_retention(self):
        data = self.payload('a')
        for entries, payload_bytes in ((0, len(data)), (3, 0)):
            with self.subTest(entries=entries, payload_bytes=payload_bytes), \
                    patch.object(contract, 'MAX_VALIDATION_CACHE_ENTRIES', entries), \
                    patch.object(contract, 'MAX_VALIDATION_CACHE_PAYLOAD_BYTES', payload_bytes):
                contract._validate_frozen_event.cache_clear()
                self.validate(data)
                self.validate(data)
                self.assert_usage(0, 0)
        self.assertEqual(self.validate_spy.call_count, 4)

    def test_mixed_accesses_match_reference_lru_under_both_bounds(self):
        values = [self.payload(index, padding=index * 13) for index in range(20)]
        max_entries, max_bytes = 5, 700
        self.limits(entries=max_entries, payload_bytes=max_bytes)
        expected = OrderedDict()
        hits = misses = 0
        rng = random.Random(20261002)
        for index in range(160):
            data = rng.choice(values)
            if data in expected:
                hits += 1
                expected.move_to_end(data)
            else:
                misses += 1
                while expected and (len(expected) >= max_entries or
                        sum(map(len, expected)) + len(data) > max_bytes):
                    expected.popitem(last=False)
                expected[data] = None
            self.validate(data)
            with self.subTest(access=index):
                self.assert_usage(sum(map(len, expected)), len(expected))
                info = contract._validate_frozen_event.cache_info()
                self.assertEqual((info.hits, info.misses), (hits, misses))
                self.assertEqual(self.validate_spy.call_count, misses)


class ValidationCachePublicPathTests(CacheTestCase):
    def test_real_positive_fixtures_reuse_exact_canonical_bytes(self):
        rows = [fixture(name) for name in ('stage-start', 'stage-finish', 'api-receipt')]
        with patch.object(contract, '_validate_event_uncached',
                wraps=contract._validate_event_uncached) as validate:
            for row in rows:
                self.assertIs(contract.validate_event(row), row)
                reordered = dict(reversed(list(deepcopy(row).items())))
                reordered['missingReasons'] = dict(reversed(list(reordered['missingReasons'].items())))
                self.assertIs(contract.validate_event(reordered), reordered)
            self.assertEqual(validate.call_count, len(rows))
        self.assert_usage(sum(len(contract.canonical_bytes(row)) for row in rows), len(rows))
        self.assertEqual(contract._validate_frozen_event.cache_info().hits, len(rows))

    def test_rejected_nested_mutation_leaves_success_bytes_unchanged(self):
        row = fixture('stage-start')
        contract.validate_event(row)
        retained_bytes = len(contract.canonical_bytes(row))
        changed = deepcopy(row)
        changed['missingReasons']['queuedAt'] = 'invalid_reason'
        with patch.object(contract, '_validate_event_uncached',
                wraps=contract._validate_event_uncached) as validate:
            for _ in range(2):
                with self.assertRaises(contract.ContractError):
                    contract.validate_event(changed)
                self.assert_usage(retained_bytes, 1)
            self.assertEqual(validate.call_count, 2)
        self.assertIs(contract.validate_event(row), row)
        self.assertEqual(contract._validate_frozen_event.cache_info().hits, 1)

    def test_schema_rotation_clears_payload_accounting_before_repopulation(self):
        row = fixture('stage-start')
        size = len(contract.canonical_bytes(row))
        self.limits(entries=20, payload_bytes=20 * size)
        for index in range(contract.MAX_SCHEMA_SNAPSHOT_ENTRIES + 1):
            self.schema['$comment'] = f'cache-accounting-schema-{index}'
            contract.validate_event(row)
            entries = index + 1 if index < contract.MAX_SCHEMA_SNAPSHOT_ENTRIES else 1
            self.assert_usage(entries * size, entries)
        self.assertEqual(len(contract._schema_snapshots), contract.MAX_SCHEMA_SNAPSHOT_ENTRIES)
        self.assertEqual(contract._validate_frozen_event.cache_info().misses, 1)

    def test_oversized_valid_events_bypass_cache_without_displacing_success(self):
        small = fixture('stage-start')
        contract.validate_event(small)
        large = deepcopy(small)
        large['dependsOn'] = [f'edge-{index:02d}-' + 'x' * 92 for index in range(64)]
        large['blockedBy'] = [f'wait-{index:02d}-' + 'x' * 92 for index in range(64)]
        self.assertGreater(len(contract.canonical_bytes(large)), contract.MAX_CACHED_EVENT_BYTES)
        before = contract._validate_frozen_event.cache_info()
        with patch.object(contract, '_validate_event_uncached',
                wraps=contract._validate_event_uncached) as validate:
            for _ in range(2):
                self.assertIs(contract.validate_event(large), large)
            self.assertEqual(validate.call_count, 2)
        self.assertEqual(contract._validate_frozen_event.cache_info(), before)
        self.assert_usage(len(contract.canonical_bytes(small)), 1)

    def test_exact_8kib_event_is_cached_but_next_byte_is_not(self):
        row = fixture('stage-start')
        row['dependsOn'] = [f'edge-{index:02d}-' + 'x' * 92 for index in range(64)]
        row['blockedBy'] = [f'wait-{index:02d}-' + 'x' * 92 for index in range(6)]
        excess = len(contract.canonical_bytes(row)) - contract.MAX_CACHED_EVENT_BYTES
        self.assertGreater(excess, 0)
        self.assertLess(excess, 92)
        row['blockedBy'][-1] = row['blockedBy'][-1][:-excess]
        self.assertEqual(len(contract.canonical_bytes(row)), contract.MAX_CACHED_EVENT_BYTES)
        larger = deepcopy(row)
        larger['blockedBy'][-1] += 'x'
        self.assertEqual(len(contract.canonical_bytes(larger)), contract.MAX_CACHED_EVENT_BYTES + 1)
        with patch.object(contract, '_validate_event_uncached',
                wraps=contract._validate_event_uncached) as validate:
            for _ in range(2):
                self.assertIs(contract.validate_event(row), row)
            self.assertEqual(validate.call_count, 1)
            before = contract._validate_frozen_event.cache_info()
            for _ in range(2):
                self.assertIs(contract.validate_event(larger), larger)
            self.assertEqual(validate.call_count, 3)
        self.assertEqual(contract._validate_frozen_event.cache_info(), before)
        self.assert_usage(contract.MAX_CACHED_EVENT_BYTES, 1)

    def test_rqc_routing_always_bypasses_success_cache(self):
        # This spy isolates routing, not the independent RQC evidence validator.
        row = dict(fixture('stage-start'), event='rqc_observation')
        with patch.object(contract, '_validate_event_uncached', return_value=None) as validate:
            for _ in range(2):
                self.assertIs(contract.validate_event(row), row)
            self.assertEqual(validate.call_count, 2)
        self.assert_usage(0, 0)
        info = contract._validate_frozen_event.cache_info()
        self.assertEqual((info.hits, info.misses), (0, 0))

    def test_concurrent_duplicate_validation_retains_one_complete_success(self):
        row = fixture('stage-start')
        workers = 8
        barrier = threading.Barrier(workers)

        def validate_copy(_):
            copied = deepcopy(row)
            barrier.wait(timeout=10)
            return contract.validate_event(copied) is copied

        with patch.object(contract, '_validate_event_uncached',
                wraps=contract._validate_event_uncached) as validate:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                self.assertTrue(all(executor.map(validate_copy, range(workers))))
            self.assertEqual(validate.call_count, 1)
        self.assert_usage(len(contract.canonical_bytes(row)), 1)
        info = contract._validate_frozen_event.cache_info()
        self.assertEqual((info.hits, info.misses), (workers - 1, 1))

    def test_direct_after_fork_hook_replaces_lock_and_resets_cache_state(self):
        row = fixture('stage-start')
        contract.validate_event(row)
        contract.validate_event(row)
        old_lock = contract._schema_snapshot_lock
        old_snapshots = contract._schema_snapshots
        self.assertTrue(old_snapshots)
        contract._reset_snapshot_lock_after_fork()
        self.assertIsNot(contract._schema_snapshot_lock, old_lock)
        self.assertIsNot(contract._schema_snapshots, old_snapshots)
        self.assertFalse(contract._schema_snapshots)
        self.assert_usage(0, 0)
        info = contract._validate_frozen_event.cache_info()
        self.assertEqual((info.hits, info.misses), (0, 0))
        self.assertIs(contract.validate_event(row), row)
        self.assert_usage(len(contract.canonical_bytes(row)), 1)
        self.assertEqual(contract._validate_frozen_event.cache_info().misses, 1)


if __name__ == '__main__':
    unittest.main()
