"""Candidate queue: superset of signalled units, never a classification or approval."""
import json
import tempfile
import unittest
from pathlib import Path

from scripts import scripture_candidate_queue as queue_module


def units():
    return [
        {'sourceUnitId': 'u1', 'english': 'Then the church reads, "Write to the angel of Laodicea".', 'start': 0.0, 'end': 4.0},
        {'sourceUnitId': 'u2', 'english': 'We keep going through the story today.', 'start': 4.0, 'end': 7.0},
        {'sourceUnitId': 'u3', 'english': 'In Revelation 3:16 he says the lukewarm are spat out.', 'start': 7.0, 'end': 11.0},
        {'sourceUnitId': 'u4', 'english': 'Let us pray for the people in the room.', 'start': 11.0, 'end': 13.0},
        {'sourceUnitId': 'u5', 'english': 'Thank you for coming tonight.', 'start': 13.0, 'end': 15.0},
        {'sourceUnitId': 'u6', 'english': 'Let us close in silence.', 'start': 15.0, 'end': 17.0},
    ]


def plan():
    return [{'translationGroupId': 'g1', 'sourceUnitIds': ['u1', 'u2']},
            {'translationGroupId': 'g2', 'sourceUnitIds': ['u3', 'u4']},
            {'translationGroupId': 'g3', 'sourceUnitIds': ['u5', 'u6']}]


def source():
    return {'source': {'sourceId': 'synthetic'}}


class CandidateQueueTests(unittest.TestCase):
    def test_signalled_units_and_their_neighbours_are_candidates_plain_far_units_are_not(self):
        queue = queue_module.build_queue(source(), {'sourceUnits': units()}, plan())
        listed = [c['sourceUnitIds'][0] for c in queue['candidates']]
        self.assertEqual(listed, ['u1', 'u2', 'u3', 'u4'])
        self.assertEqual(queue['sourceUnitCount'], 6)
        self.assertEqual(queue['candidateCount'], 4)
        self.assertEqual([c['kinds'] for c in queue['candidates']][1], ['adjacent_to_signal'])

    def test_every_unit_is_in_the_full_review_list_with_a_suggestion_flag(self):
        queue = queue_module.build_queue(source(), {'sourceUnits': units()}, plan())
        review = {row['sourceUnitId']: row['suggested'] for row in queue['reviewUnits']}
        self.assertEqual(set(review), {'u1', 'u2', 'u3', 'u4', 'u5', 'u6'})
        self.assertTrue(review['u1'])
        self.assertFalse(review['u6'])

    def test_candidates_carry_no_classification_or_approval(self):
        queue = queue_module.build_queue(source(), {'sourceUnits': units()}, plan())
        for candidate in queue['candidates']:
            self.assertIsNone(candidate['machineClassification'])
            self.assertEqual(candidate['decisionStatus'], 'not_decided')
            self.assertNotIn('decidedBy', candidate)
        self.assertIn('No classification', queue['notice'])

    def test_candidates_bind_group_timing_neighbours_and_signals(self):
        queue = queue_module.build_queue(source(), {'sourceUnits': units()}, plan())
        by_unit = {c['sourceUnitIds'][0]: c for c in queue['candidates']}
        first, second = by_unit['u1'], by_unit['u3']
        self.assertEqual(first['translationGroupId'], 'g1')
        self.assertEqual((first['start'], first['end']), (0.0, 4.0))
        self.assertIsNone(first['previous'])
        self.assertEqual(first['next']['sourceUnitId'], 'u2')
        self.assertEqual(second['translationGroupId'], 'g2')
        self.assertEqual(second['previous']['sourceUnitId'], 'u2')
        self.assertIn('book_reference', second['kinds'])
        self.assertIn('Revelation 3:16', [s['text'] for s in second['signals']])

    def test_queue_is_deterministic_and_bound_to_inputs(self):
        first = queue_module.build_queue(source(), {'sourceUnits': units()}, plan())
        second = queue_module.build_queue(source(), {'sourceUnits': units()}, plan())
        self.assertEqual(first, second)
        changed = queue_module.build_queue(source(), {'sourceUnits': units()[:3]}, plan())
        self.assertNotEqual(first['bindings']['anchor.json'], changed['bindings']['anchor.json'])

    def test_cli_refuses_to_overwrite_an_existing_queue(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'source.json').write_text(json.dumps(source()), encoding='utf-8')
            (root / 'anchor.json').write_text(json.dumps({'sourceUnits': units()}), encoding='utf-8')
            (root / 'group-plan.json').write_text(json.dumps(plan()), encoding='utf-8')
            out = root / 'queue.json'
            self.assertEqual(queue_module.main([str(root), '--out', str(out)]), 0)
            self.assertEqual(json.loads(out.read_text(encoding='utf-8'))['candidateCount'], 4)
            with self.assertRaises(SystemExit):
                queue_module.main([str(root), '--out', str(out)])


if __name__ == '__main__':
    unittest.main()
