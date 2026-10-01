import json
import unittest
from scripts import sermon_business_prefect_flow as flow
from scripts import sermon_business_progress as projection
from tests import test_sermon_business_prefect_flow as fixtures


class BusinessProgressTests(unittest.TestCase):
    def setup(self, **kwargs):
        f, transport, callbacks, nodes = fixtures.setup_business(self, **kwargs)
        return f, transport, flow.BusinessDAG(f.f.root / 'dag', callbacks, nodes)

    def test_actual_callbacks_project_processed_separately_from_human_and_eta(self):
        f, transport, dag = self.setup()
        with f.f.session():
            fixtures.execute_all(dag)
            snapshot = projection.update(dag)
            self.assertAlmostEqual(snapshot['plannedProcessedPercent'], 3 / 7 * 100, places=5)
            self.assertAlmostEqual(snapshot['gateCompletionPercent'], 3 / 7 * 100, places=5)
            for key in ('asr', 'source', 'text.zh-Hans'):
                self.assertTrue(next(row for row in snapshot['units'] if row['unitId'] == key)['complete'])
            self.assertEqual(snapshot['counts']['realHumanApproved'], 0)
            self.assertEqual(snapshot['counts']['simulatedHumanApproved'], 0)
            self.assertEqual(snapshot['eta']['status'], 'unknown')
            self.assertIsNone(snapshot['eta']['upperSeconds'])
            self.assertEqual(len(transport.observations), 6)
            before = len(list((dag.root / 'business-progress-observations').glob('*.json')))
            again = projection.update(dag)
            self.assertEqual(again['plannedProcessedPercent'], snapshot['plannedProcessedPercent'])
            self.assertEqual(len(list((dag.root / 'business-progress-observations').glob('*.json'))), before)

    def test_unknown_keeps_null_and_original_reservation_through_restart(self):
        f, transport, dag = self.setup(unknown=True)
        with f.f.session():
            fixtures.execute_all(dag)
            before = dag.callbacks.provider_evidence()
            result = projection.update(dag)
            self.assertIsNone(result['plannedProcessedPercent'])
            restarted = flow.BusinessDAG(dag.root, dag.callbacks, dag.nodes)
            fixtures.execute_all(restarted)
            again = projection.update(restarted)
            self.assertIsNone(again['plannedProcessedPercent'])
            self.assertEqual(before, dag.callbacks.provider_evidence())
        self.assertEqual(len(transport.observations), 1)

    def test_changed_candidate_becomes_unknown_without_touching_provider(self):
        f, transport, dag = self.setup()
        with f.f.session():
            fixtures.execute_all(dag)
            projection.update(dag)
            from pathlib import Path
            candidate = Path(dag._envelopes['text.zh-Hans']['result']['output']) / 'candidate.json'
            candidate.write_text('{}')
            result = projection.update(dag)
            self.assertLess(result['gateCompletionPercent'], 100)
            self.assertIn('text.zh-Hans', [r['unitId'] for r in result['units'] if r['unknownOutcome']])
            self.assertEqual(len(transport.observations), 6)

    def test_damaged_saved_history_refuses_projection(self):
        f, transport, dag = self.setup()
        with f.f.session():
            fixtures.execute_all(dag)
            projection.update(dag)
            path = next((dag.root / 'business-progress-observations').glob('*.json'))
            value = json.loads(path.read_text()); value['receipt']['executionStatus'] = 'succeeded'
            value['receipt']['eventId'] = 'forged'
            path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, 'business_progress_history_changed'):
                projection.update(dag)

    def test_history_directory_symlink_refused_before_write(self):
        import tempfile
        from pathlib import Path
        f, transport, dag = self.setup()
        with tempfile.TemporaryDirectory() as outside:
            (dag.root / 'business-progress-observations').symlink_to(outside, target_is_directory=True)
            with f.f.session(), self.assertRaises(ValueError):
                projection.update(dag)
            self.assertEqual(list(Path(outside).iterdir()), [])
