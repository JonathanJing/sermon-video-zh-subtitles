"""One-operation report snapshots preserve diagnostics and summary side effects."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import sermon_accounting as accounting
from scripts import sermon_fresh_full_dag as full
from scripts import sermon_log_contract as contract
from scripts import sermon_log_profile as profile
from scripts import sermon_logs as logs


class ReportSnapshotTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)/'accounting'
        self.production = 'a'*64
        with profile.session(self.directory, 'report_fixture', work_kind='engineering',
                evidence_mode='synthetic', production_run_id=self.production) as run:
            with profile.context(workUnitId='text.zh-Hans'):
                with accounting.stage('text.zh-Hans'):
                    pass
        self.run_id = run['runId']
        self.dag = full.FullFreshDAG.__new__(full.FullFreshDAG)
        self.dag.stream = SimpleNamespace(directory=self.directory, run_id=self.run_id)
        self.dag.binding = {'logicalLayers': {'nodes': {'text.zh-Hans': 2}}}
        self.dag.units = ()
        self.dag.plan_sha256 = 'b'*64
        self.dag.invocation = 'test-invocation'
        self.dag.prior_api_events = set()
        self.dag._production_run_id = lambda: self.production
        self.enterContext(patch.object(accounting, 'now', return_value='2026-10-02T00:00:00Z'))

    def outputs(self):
        return {name: (self.directory/name).read_bytes() for name in
            ('summary.json', 'stages.csv', 'stage-attempts.csv', 'operations.log')}

    def test_bundle_matches_separate_reports_and_reads_and_replays_once(self):
        expected = {'layerEvidence': self.dag.layer_evidence(),
            'accountingProjection': self.dag.accounting_projection()}
        old_outputs = self.outputs()
        with patch.object(accounting, 'read_event_snapshot', wraps=accounting.read_event_snapshot) as read, \
                patch.object(accounting, 'profile_integrity', wraps=accounting.profile_integrity) as replay:
            actual = self.dag.report_bundle()
        self.assertEqual(actual, expected)
        self.assertEqual(read.call_count, 1)
        self.assertEqual(replay.call_count, 1)
        self.assertEqual(old_outputs, self.outputs())
        self.assertEqual(actual['accountingProjection']['sourceLedgerSha256'],
            hashlib.sha256((self.directory/'events.jsonl').read_bytes()).hexdigest())

    def test_shared_read_only_consumers_equal_public_outputs(self):
        summary = accounting.summarize(self.directory)
        inspection = logs.inspect_logs(self.directory, run_id=self.run_id)
        before = {p.name: p.read_bytes() for p in self.directory.iterdir() if p.is_file()}
        actual = accounting._with_report_snapshot(self.directory,
            lambda events, damaged, digest, replay: (
                accounting._summarize_events(events, damaged, digest, replay)[0],
                logs._inspect_events(events, damaged, replay, run_id=self.run_id)))
        self.assertEqual(actual, (summary, inspection))
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.directory.iterdir() if p.is_file()})

    def test_next_call_observes_append_and_returned_mutation_is_not_cached(self):
        original = self.dag.report_bundle()
        original['layerEvidence']['declaredNodes']['invented'] = 9
        with profile.session(self.directory, 'second_report', work_kind='engineering',
                evidence_mode='synthetic', production_run_id=self.production):
            pass
        with self.assertRaisesRegex(ValueError, 'fresh_full_log_scope_changed'):
            self.dag.report_bundle()
        inspection = logs.inspect_logs(self.directory, run_id='all')
        self.assertGreater(inspection['matchingEvents'], 4)

    def test_internal_row_mutation_is_rejected_before_summary_write(self):
        before = self.outputs()
        def mutate(events, damaged, digest, replay, summary):
            events[0]['runId'] = 'different'
            return summary
        with self.assertRaisesRegex(ValueError, 'report_snapshot_mutated'):
            accounting._with_summary_snapshot(self.directory, mutate)
        self.assertEqual(before, self.outputs())

    def test_schema_change_inside_operation_cannot_escape_as_verified(self):
        schema = contract.validator().schema
        old = deepcopy(schema)
        def mutate(events, damaged, digest, replay):
            schema['description'] = 'changed during report operation'
            return 'must not return'
        try:
            with self.assertRaisesRegex(ValueError, 'report_schema_changed'):
                accounting._with_report_snapshot(self.directory, mutate)
        finally:
            schema.clear(); schema.update(old)

    def test_damaged_bytes_are_reported_and_dag_rejects_them(self):
        with (self.directory/'events.jsonl').open('ab') as stream:
            stream.write(b'{broken\n')
        inspection = logs.inspect_logs(self.directory, run_id=self.run_id)
        self.assertEqual(inspection['status'], 'needs_attention')
        self.assertEqual(len(inspection['damagedEvents']), 1)
        with self.assertRaisesRegex(ValueError, 'fresh_full_log_damaged'):
            self.dag.report_bundle()

    def test_cross_run_conflicting_duplicate_is_not_filtered_out(self):
        rows = [json.loads(line) for line in (self.directory/'events.jsonl').read_text().splitlines()]
        conflict = deepcopy(rows[0]); conflict['runId'] = 'different-run'
        with (self.directory/'events.jsonl').open('ab') as stream:
            stream.write(json.dumps(conflict).encode()+b'\n')
        inspection = logs.inspect_logs(self.directory, run_id=self.run_id)
        self.assertEqual(inspection['status'], 'needs_attention')
        self.assertNotEqual(inspection['eventIntegrity']['status'], 'consistent')


if __name__ == '__main__':
    unittest.main()
