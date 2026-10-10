"""Positive replay batches and exact, bounded schema-snapshot caching."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from scripts import sermon_log_contract as contract
from tests.test_accounting_log_contract import fixture


def positive_rows(pairs=8):
    rows = []
    for index in range(pairs):
        for terminal, name in enumerate(('stage-start', 'stage-finish')):
            row = fixture(name)
            sequence = index * 2 + terminal + 1
            row.update(eventId=f'{sequence:032x}', sequence=sequence,
                spanId=f'positive-span-{index}', attemptId=f'positive-attempt-{index}')
            rows.append(row)
    return rows


class SchemaSnapshotTests(unittest.TestCase):
    def setUp(self):
        with contract._schema_snapshot_lock:
            contract._schema_snapshots.clear()
            contract._validate_frozen_event.cache_clear()
        self.schema = deepcopy(contract.validator().schema)
        self.enterContext(patch.object(contract.validator(), 'schema', self.schema))

    def test_positive_batch_captures_schema_once_and_reuses_success_across_batches(self):
        rows = positive_rows(16)
        with patch.object(contract, '_schema_snapshot', wraps=contract._schema_snapshot) as snapshot:
            self.assertEqual(contract.replay_integrity(rows)['status'], 'consistent')
            self.assertEqual(snapshot.call_count, 1)
            self.assertEqual(contract.replay_integrity(deepcopy(rows))['status'], 'consistent')
            self.assertEqual(snapshot.call_count, 2)
        info = contract._validate_frozen_event.cache_info()
        self.assertEqual(info.misses, len(rows))
        self.assertEqual(info.hits, len(rows))

    def test_public_and_replay_checks_see_schema_edits(self):
        rows = positive_rows(1)
        self.assertEqual(contract.replay_integrity(rows)['status'], 'consistent')
        self.schema['properties']['sequence'] = {'type': 'integer', 'minimum': 2}
        with self.assertRaises(contract.ContractError):
            contract.validate_event(rows[0])
        with self.assertRaises(contract.ContractError):
            contract.replay_integrity(rows)

    def test_private_checker_is_independent_of_later_live_schema_edits(self):
        row = fixture('stage-start')
        with contract._schema_snapshot_lock:
            key, checker = contract._schema_snapshot()
            self.schema['properties']['sequence'] = {'type': 'integer', 'minimum': 2}
            self.assertTrue(checker.is_valid(row))
            self.assertEqual(contract._schema_snapshots[key][1], checker)
        with self.assertRaises(contract.ContractError):
            contract.validate_event(row)

    def test_scalar_types_have_distinct_snapshot_keys(self):
        keys = []
        for value in (True, 1, 1.0):
            self.schema['default'] = value
            row = fixture('stage-start')
            self.assertIs(contract.validate_event(row), row)
            with contract._schema_snapshot_lock:
                keys.append(contract._schema_snapshot()[0])
        self.assertEqual(len(set(keys)), 3)

    def test_list_to_tuple_change_never_reuses_a_valid_snapshot(self):
        row = fixture('stage-start')
        self.schema['properties']['sequence']['enum'] = [1]
        contract.validate_event(row)
        self.schema['properties']['sequence']['enum'] = (1,)
        with self.assertRaisesRegex(contract.ContractError, 'invalid_schema_snapshot'):
            contract.validate_event(row)
        self.assertEqual(contract._validate_frozen_event.cache_info().hits, 0)

    def test_bool_schema_constraint_does_not_reuse_integer_constraint(self):
        row = fixture('stage-start')
        self.schema['properties']['sequence']['const'] = 1
        contract.validate_event(row)
        self.schema['properties']['sequence']['const'] = True
        with self.assertRaises(contract.ContractError):
            contract.validate_event(row)

    def test_nested_list_edit_invalidates_public_and_batch_success(self):
        rows = positive_rows(1)
        self.schema['properties']['sequence']['enum'] = [1, 2]
        self.assertEqual(contract.replay_integrity(rows)['status'], 'consistent')
        self.schema['properties']['sequence']['enum'][0] = 3
        with self.assertRaises(contract.ContractError):
            contract.validate_event(rows[0])
        with self.assertRaises(contract.ContractError):
            contract.replay_integrity(rows)

    def test_snapshot_rotation_clears_success_keys_before_eviction(self):
        row = fixture('stage-start')
        for index in range(contract.MAX_SCHEMA_SNAPSHOT_ENTRIES + 1):
            self.schema['$comment'] = f'ordinary-schema-revision-{index}'
            contract.validate_event(row)
            self.assertLessEqual(len(contract._schema_snapshots), contract.MAX_SCHEMA_SNAPSHOT_ENTRIES)
        self.assertEqual(contract._validate_frozen_event.cache_info().currsize, 1)
        for key, snapshot in contract._schema_snapshots.items():
            self.assertIs(snapshot[0], key)
            self.assertLessEqual(len(key), contract.MAX_SCHEMA_SNAPSHOT_BYTES)

    def test_batch_captures_schema_once_and_later_batches_see_edits(self):
        rows = positive_rows(4)
        with patch.object(contract, '_schema_snapshot', wraps=contract._schema_snapshot) as snapshot:
            with contract.schema_batch():
                for row in rows:
                    contract.validate_event(row)
                with contract.schema_batch():
                    self.assertEqual(contract.replay_integrity(rows)['status'], 'consistent')
            self.assertEqual(snapshot.call_count, 1)
        self.schema['properties']['sequence'] = {'type': 'integer', 'minimum': 2}
        with contract.schema_batch(), self.assertRaises(contract.ContractError):
            contract.validate_event(rows[0])

    def test_batch_without_profile_rows_takes_no_snapshot(self):
        with patch.object(contract, '_schema_snapshot', wraps=contract._schema_snapshot) as snapshot:
            with contract.schema_batch():
                pass
            self.assertEqual(snapshot.call_count, 0)

    def test_invalid_schema_still_rejects_each_row_in_a_batch(self):
        rows = positive_rows(2)
        self.schema['default'] = float('nan')
        with contract.schema_batch():
            self.assertEqual([contract.valid_event(row) for row in rows], [False] * len(rows))
        del self.schema['default']
        with contract.schema_batch():
            self.assertTrue(all(contract.valid_event(row) for row in rows))

    def test_rejected_row_in_a_batch_does_not_hide_later_rows(self):
        rows = positive_rows(2)
        bad = deepcopy(rows[0]); bad['sequence'] = True
        with contract.schema_batch():
            results = [contract.valid_event(row) for row in (rows[0], bad, rows[1])]
        self.assertEqual(results, [True, False, True])

    def test_oversized_or_non_json_schemas_fail_closed(self):
        row = fixture('stage-start')
        self.schema['$comment'] = 'x' * contract.MAX_SCHEMA_SNAPSHOT_BYTES
        with self.assertRaisesRegex(contract.ContractError, 'schema_snapshot_size_limit'):
            contract.validate_event(row)
        del self.schema['$comment']
        for value in (b'unsupported', {'unsupported'}, float('nan')):
            self.schema['default'] = value
            with self.subTest(kind=type(value).__name__), self.assertRaises(contract.ContractError):
                contract.validate_event(row)
        self.assertFalse(contract._schema_snapshots)
        self.assertEqual(contract._validate_frozen_event.cache_info().currsize, 0)


if __name__ == '__main__':
    unittest.main()
