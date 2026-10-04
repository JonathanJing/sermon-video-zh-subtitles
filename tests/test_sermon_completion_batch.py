"""Batch validation changes work sharing, never the evidence acceptance rules."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from scripts import sermon_completion as completion
from scripts import sermon_review_contracts as c
from tests.test_sermon_completion import completion_fixture


class CompletionBatchTests(unittest.TestCase):
    def test_equivalent_replay_and_one_global_plus_one_per_run(self):
        for synthetic in (False, True):
            with self.subTest(synthetic=synthetic):
                handle, events = completion_fixture(synthetic=synthetic)
                method = completion.validate_synthetic_many if synthetic else completion.validate_many
                checks = [{'handle': handle, 'artifact_sha256': 'b'*64,
                           'dependencies': ['transcription-span']}] * 3
                with patch.object(completion.log, 'replay_integrity', wraps=completion.log.replay_integrity) as replay:
                    result = method(checks, events+deepcopy(events), production_run_id='a'*64)
                self.assertEqual(replay.call_count, 2)
                self.assertEqual(result, [handle]*3)
                self.assertIsNot(result[0], handle)
                result[0]['dependsOn'].append('changed')
                self.assertEqual(result[1], handle)

    def test_multiple_runs_each_checked_once(self):
        handle, events = completion_fixture(synthetic=False)
        second = deepcopy(events)
        for row in second:
            row.update(runId='second', producerId='9'*32, eventId=('7' if row['event']=='stage_started' else '8')*32)
        other = deepcopy(handle)
        other.update(runId='second', terminalEventId='8'*32, terminalFactSha256=completion.log.fact_hash(second[-1]))
        with patch.object(completion.log, 'replay_integrity', wraps=completion.log.replay_integrity) as replay:
            self.assertEqual(completion.validate_many([{'handle': handle}, {'handle': other}], events+second,
                production_run_id='a'*64), [handle, other])
        self.assertEqual(replay.call_count, 3)

    def test_every_binding_and_explicit_domain_remain_required(self):
        handle, events = completion_fixture(synthetic=True)
        for change in ({'job_id':'other'}, {'revision_id':'other'}, {'stage':'other'},
                       {'artifact_sha256':'f'*64}, {'dependencies':[]}):
            with self.subTest(change=change), self.assertRaises(c.ContractError):
                completion.validate_synthetic_many([{'handle': handle}, {'handle': handle, **change}],
                    events, production_run_id='a'*64)
        with self.assertRaises(c.ContractError):
            completion.validate_many([{'handle':handle}], events, production_run_id='a'*64)
        with self.assertRaises(c.ContractError):
            completion.validate_many([{'handle':handle, 'synthetic':True}], events, production_run_id='a'*64)
        production, rows = completion_fixture(synthetic=False)
        with self.assertRaises(c.ContractError):
            completion.validate_synthetic_many([{'handle':production}], rows, production_run_id='a'*64)

    def test_missing_failed_conflicting_and_container_terminals_are_rejected(self):
        handle, events = completion_fixture(synthetic=True)
        failed = deepcopy(events); failed[-1]['status'] = 'failed'
        conflict = deepcopy(events[-1]); conflict['artifactSha256'] = 'f'*64
        child = deepcopy(events)
        for row in child:
            row.update(eventId=('7' if row['event']=='stage_started' else '8')*32,
                       sequence=row['sequence']+2, spanId='child', parentSpanId=handle['spanId'], attemptId='child-attempt')
        for rows in (events[:-1], failed, events+[conflict], events+child):
            with self.subTest(rows=len(rows)), self.assertRaises(c.ContractError):
                completion.validate_synthetic_many([{'handle':handle}], rows, production_run_id='a'*64)

    def test_call_owns_snapshot_and_next_call_revalidates_changed_inputs(self):
        handle, events = completion_fixture(synthetic=True)
        checks = [{'handle':handle}]
        original = completion.log.replay_integrity
        changed = False
        def replay(rows):
            nonlocal changed
            if not changed:
                changed = True
                events[-1]['artifactSha256'] = 'f'*64
                handle['jobId'] = 'different'
            return original(rows)
        with patch.object(completion.log, 'replay_integrity', side_effect=replay):
            result = completion.validate_synthetic_many(checks, events, production_run_id='a'*64)
        self.assertEqual(result[0]['jobId'], 'job')
        with self.assertRaises(c.ContractError):
            completion.validate_synthetic_many(checks, events, production_run_id='a'*64)

    def test_unrelated_run_conflict_and_global_sequence_conflict_are_rejected(self):
        handle, events = completion_fixture(synthetic=False)
        other = deepcopy(events)
        for row in other:
            row.update(runId='unrelated', producerId='9'*32,
                eventId=('7' if row['event']=='stage_started' else '8')*32)
        conflicting = deepcopy(other[-1]); conflicting['status'] = 'failed'
        reused_sequence = deepcopy(other[0]); reused_sequence.update(eventId='6'*32)
        for rows in (events+other+[conflicting], events+other+[reused_sequence]):
            with self.subTest(count=len(rows)), self.assertRaisesRegex(c.ContractError, 'completion_log_integrity_failed'):
                completion.validate_many([{'handle':handle}], rows, production_run_id='a'*64)

    def test_version_change_during_batch_is_rejected(self):
        handle, events = completion_fixture(synthetic=False)
        original = completion.log.VERSION
        validate = completion._validate_in_rows
        def changed(*args, **kwargs):
            result = validate(*args, **kwargs)
            completion.log.VERSION = 'different-version'
            return result
        try:
            with patch.object(completion, '_validate_in_rows', side_effect=changed):
                with self.assertRaisesRegex(c.ContractError, 'completion_schema_changed'):
                    completion.validate_many([{'handle': handle}], events, production_run_id='a'*64)
        finally:
            completion.log.VERSION = original

    def test_schema_change_during_batch_is_rejected(self):
        handle, events = completion_fixture(synthetic=False)
        schema = completion.log.validator().schema
        original_schema = deepcopy(schema['properties']['runId'])
        original_hash = completion.log.fact_hash
        def change_after_replay(row):
            result = original_hash(row)
            schema['properties']['runId'] = {'type': 'string'}
            return result
        try:
            with patch.object(completion.log, 'fact_hash', side_effect=change_after_replay):
                with self.assertRaisesRegex(c.ContractError, 'completion_schema_changed'):
                    completion.validate_many([{'handle': handle}], events, production_run_id='a'*64)
        finally:
            schema['properties']['runId'] = original_schema

    def test_schema_mutation_is_not_hidden_by_a_prior_batch(self):
        handle, events = completion_fixture(synthetic=False)
        completion.validate_many([{'handle':handle}], events, production_run_id='a'*64)
        schema = completion.log.validator().schema
        original = deepcopy(schema['properties']['runId'])
        try:
            schema['properties']['runId'] = {'const': 'different-run'}
            with self.assertRaises(completion.log.ContractError):
                completion.validate_many([{'handle':handle}], events, production_run_id='a'*64)
        finally:
            schema['properties']['runId'] = original
        self.assertEqual(completion.validate_many([{'handle':handle}], events, production_run_id='a'*64), [handle])


if __name__ == '__main__':
    unittest.main()
