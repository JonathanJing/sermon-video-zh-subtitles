"""Real private producers and public plugin, synthetic transport only."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import sermon_strict_locale as subject
from scripts import sermon_review_budget as budget
from scripts import sermon_review_contracts as c
from scripts import sermon_strict_layer2 as strict
from tests import test_sermon_strict_layer2 as fixtures
from tests import test_sermon_strict_budget_adapter as budget_fixtures


class LocaleTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.StrictAdapterTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.groups = deepcopy(self.f.f.evidence['groups'])
        self.plan = [{key: row[key] for key in ('translationGroupId', 'sourceUnitIds')} for row in self.groups]
        self.graph = [{'workUnitId': strict.prepare(*self.f.args, row)['workUnitId'],
                       'layer': 2, 'targetLocale': 'zh-Hans', 'dependsOn': []} for row in self.plan]
        self.store = budget.BudgetStore(self.f.root / 'budget', budget_fixtures.authority())
        self.kw = dict(root=self.f.root / 'locale', store=self.store, job_root=self.f.root / 'jobs',
            production_run_id='b'*64, graph=self.graph, plugin_path=self.f.f.plugin_path,
            expected_plugin_sha256=self.f.f.plugin_sha, api_key='synthetic', caller=self.transport,
            bounds=budget_fixtures.bounds(), usage_resolver=budget_fixtures.measured,
            group_plan=self.plan, created_at='2026-09-30T00:00:00Z')

    def transport(self, key, payload, **options):
        inputs = json.loads(payload['messages'][1]['content'])
        group = next(row for row in self.groups if row['translationGroupId'] == inputs['translationGroupId'])
        self.f.f.evidence['groups'][0] = group
        return self.f.transport(key, payload, **options)

    def run_locale(self, **changes):
        return subject.run_locale(*self.f.args, **{**self.kw, **changes})

    def test_complete_locale_is_machine_pending_and_resume_makes_no_new_calls(self):
        with self.f.session():
            result = self.run_locale()
            self.assertEqual(result['status'], 'waiting_human')
            self.assertEqual(len(self.f.calls), 4)
            candidate = c.read_snapshot(Path(result['output']) / 'candidate.json')[0]
            self.assertEqual(candidate['humanReview']['translation'], 'pending')
            self.assertFalse(candidate['releaseEligible'])
            self.assertEqual([g['targetUtterances'] for g in candidate['groups']],
                             [g['targetUtterances'] for g in self.groups])
            again = self.run_locale()
            self.assertEqual(again['output'], result['output'])
            self.assertEqual(len(self.f.calls), 4)

    def test_invalid_late_group_and_plugin_fail_before_any_transport(self):
        changed = deepcopy(self.plan); changed[-1]['translationGroupId'] = 'x'*90
        with self.f.session():
            with self.assertRaises(ValueError): self.run_locale(group_plan=changed)
            with self.assertRaises(ValueError): self.run_locale(expected_plugin_sha256='0'*64)
        self.assertEqual(self.f.calls, [])

    def test_target_context_graph_requires_adapter_before_any_call(self):
        changed = deepcopy(self.graph); changed[1]['dependsOn'] = [changed[0]['workUnitId']]
        with self.f.session(), self.assertRaisesRegex(ValueError, 'target_context_dispatch_not_supported'):
            self.run_locale(graph=changed)
        self.assertEqual(self.f.calls, [])

    def test_missing_usage_blocks_assembly_and_does_not_fabricate_approval(self):
        with self.f.session():
            result = self.run_locale(usage_resolver=lambda _: None)
        self.assertEqual(result['status'], 'blocked'); self.assertIsNone(result['output'])
        self.assertFalse((self.kw['root'] / 'machine-candidates').exists())
        self.assertEqual(len(self.f.calls), 2)  # one generation per independent group

    def test_log_failure_propagates_and_resume_reuses_saved_response(self):
        with self.f.session():
            with patch.object(subject.accounting, 'record_api_attempt',
                    side_effect=subject.accounting.AccountingWriteError('synthetic')):
                with self.assertRaises(subject.accounting.AccountingWriteError): self.run_locale()
            self.assertEqual(len(self.f.calls), 1)
            result = self.run_locale()
            self.assertEqual(result['status'], 'waiting_human')
        self.assertEqual(len(self.f.calls), 4)

    def test_graph_change_cannot_reuse_pinned_locale(self):
        with self.f.session():
            self.run_locale()
            changed = deepcopy(self.graph)
            changed.append({'workUnitId': 'l3.zh-Hans.audio', 'layer': 3,
                            'targetLocale': 'zh-Hans', 'dependsOn': [row['workUnitId'] for row in changed]})
            with self.assertRaisesRegex(ValueError, 'immutable_strict_artifact_changed'):
                self.run_locale(graph=changed)
        self.assertEqual(len(self.f.calls), 4)

    def test_trace_binds_source_and_actual_serial_groups_without_extra_api_receipts(self):
        with self.f.session():
            result = self.run_locale()
        events, invalid = subject.accounting.read_events(self.f.root / 'logs')
        self.assertEqual(invalid, [])
        starts = {row['spanId']: row for row in events if row['event'] == 'stage_started'}
        first_tail = result['groups'][0]['completedSpans'][-1]
        second_first = result['groups'][1]['completedSpans'][0]
        # The returned completion is candidate-freeze, following the actual
        # generation span; assert the real two-edge path, not an invented edge.
        generation_span = starts[second_first]['dependsOn'][0]
        self.assertIn(first_tail, starts[generation_span]['dependsOn'])
        assembly = next(row for row in starts.values() if row['stage'] == 'rqc.locale_candidate_assembly')
        self.assertEqual(assembly['dependsOn'], result['groups'][-1]['completedSpans'][-1:])
        self.assertEqual(len([row for row in events if row['event'] == 'api_attempt']), 4)
        media_hash = json.loads(self.f.args[0])['source']['media']['sha256']
        self.assertTrue(any(media_hash in json.dumps(row) for row in events if row['event'] == 'workload'))

    def test_large_valid_aggregate_can_be_read_and_resumed(self):
        for group in self.groups:
            for index, text in enumerate(group['targetUtterances']):
                group['targetUtterances'][index] = text + '测' * (15500 - len(text))
            group['targetUtterances'].append('试' * 15500)
        with self.f.session():
            result = self.run_locale()
            self.assertEqual(result['status'], 'waiting_human')
            path = Path(result['output']) / 'candidate.json'
            self.assertGreater(path.stat().st_size, c.MAX_BYTES)
            value, raw = subject.public.read_snapshot(path)
            self.assertEqual(c.canonical_sha256(value), result['candidateSha256'])
            repeated = self.run_locale()
            self.assertEqual(repeated['output'], result['output'])
            self.assertEqual(subject.public.read_snapshot(path)[1], raw)
        self.assertEqual(len(self.f.calls), 4)

    def test_locale_outputs_feed_real_gate_with_separate_synthetic_human_receipt(self):
        from scripts import review_target_language_candidate as human
        from scripts import sermon_strict_gate_admission as admission
        with self.f.session():
            result = self.run_locale()
        source, anchor, policy, rubric = map(c.decode_json, self.f.args)
        pending = subject.public.read_snapshot(Path(result['output']) / 'candidate.json')[0]
        sheet = human.build_worksheet(source, anchor, pending, policy, strict_rubric=rubric)
        sheet = human.apply_batch_approval(sheet, reviewer='Synthetic integration fixture',
            reviewed_at=self.kw['created_at'], evidence='Developer fixture only, not human acceptance')
        approved, receipt = human.approve_worksheet(source, anchor, pending, policy, sheet, strict_rubric=rubric)
        paths = {}
        for key, value in zip(('source', 'anchor', 'policy', 'rubric', 'public_candidate', 'human_receipt'),
                             (source, anchor, policy, rubric, approved, receipt)):
            paths[key] = self.f.root / (key + '.json')
            subject.public.save_once(paths[key], value)
        boundary = admission.AdmissionBoundary(admission.Configuration(
            self.kw['production_run_id'], 'zh-Hans', self.kw['job_root'], self.kw['root'],
            tuple(Path(row['root']) for row in result['revisions']), **paths,
            plugin=self.kw['plugin_path'], plugin_sha256=self.kw['expected_plugin_sha256']), self.store)
        snapshot = boundary.snapshot()
        outcome = boundary.admit(expected_state_revision=snapshot.state_revision, created_at=self.kw['created_at'])
        self.assertEqual(outcome['status'], 'committed', outcome)
        self.assertEqual(outcome['intent']['action'], 'prepare_layer3')
        self.assertFalse(outcome['dispatched'])
        self.assertEqual(len(self.f.calls), 4)


if __name__ == '__main__': unittest.main()
