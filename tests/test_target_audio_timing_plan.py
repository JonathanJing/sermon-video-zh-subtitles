import copy
import math
import unittest
from scripts import target_audio_timing_plan as subject


class TimingPlanTests(unittest.TestCase):
    def row(self, gid, start, end, seconds):
        return dict(gid=gid, sourceStart=start, sourceEnd=end, audioSeconds=seconds)

    def test_own_span_excess_borrows_next_gap_without_formal_failure(self):
        result = subject.plan(20, [self.row('a', 0, 2, 4), self.row('b', 10, 14, 2)])
        self.assertEqual(result['ownSpanExcessWarnings'], ['a'])
        self.assertEqual(result['formalScheduleStatus'], 'pass')
        self.assertEqual(result['maxLagViolations'], [])
        self.assertGreater(result['groups'][0]['remainingBeforeNextSourceStartSeconds'], 5)

    def test_local_maxlag_pass_but_clip_tail_fails(self):
        result = subject.plan(10, [self.row('a', 0, 10, 11)])
        self.assertEqual(result['maxLagViolations'], [])
        self.assertEqual(result['clipTailOverflows'], ['a'])
        self.assertEqual(result['formalScheduleStatus'], 'fail')
        self.assertAlmostEqual(result['minimumDurationRecoverySeconds'], 1.05)

    def test_propagated_delay_and_actual_maxlag(self):
        result = subject.plan(50, [self.row('a', 0, 2, 13), self.row('b', 3, 5, 1)])
        self.assertEqual(result['maxLagViolations'], ['a', 'b'])
        self.assertGreater(result['groups'][1]['propagatedStartDelaySeconds'], 9)
        self.assertEqual(result['clipTailOverflows'], [])
        self.assertEqual(result['minimumDurationRecoverySeconds'], 0)

    def test_natural_lower_bound_distinct_from_anchor_waiting_tail(self):
        result = subject.plan(10, [self.row('a', 0, 1, 1), self.row('b', 9, 10, 2)])
        self.assertEqual(result['naturalConcatenatedPlusGapLowerBoundSeconds'], 3.05)
        self.assertEqual(result['minimumDurationRecoverySeconds'], 0)
        self.assertAlmostEqual(result['scheduledTailRecoverySeconds'], 1.05)

    def test_input_hash_is_order_and_identity_bound_no_mutation_or_approval(self):
        rows = [self.row('whole-scripture', 0, 5, 4)]
        rows[0]['audioSha256'] = 'a' * 64
        before = copy.deepcopy(rows)
        first = subject.plan(10, rows, identities={'source': 'b' * 64})
        second = subject.plan(10, rows, identities={'source': 'c' * 64})
        self.assertEqual(rows, before)
        self.assertNotEqual(first['inputSha256'], second['inputSha256'])
        self.assertTrue(first['diagnosticOnly'])
        for key in ('humanApproval', 'publicationEligible', 'grantsApproval', 'mutatesAudio', 'mutatesText'):
            self.assertFalse(first[key])
        self.assertEqual(first['groups'][0]['gid'], 'whole-scripture')
        self.assertEqual(first['modelCalls'], 0)

    def test_invalid_measurements_and_duplicate_or_overlap_rejected(self):
        bad = [self.row('a', 0, 2, math.nan), self.row('a', 0, 2, -1), self.row('a', 0, 2, True)]
        for row in bad:
            with self.subTest(row=row), self.assertRaises(ValueError):
                subject.plan(10, [row])
        for rows in ([self.row('a', 0, 2, 1), self.row('a', 3, 4, 1)],
                     [self.row('a', 0, 2, 1), self.row('b', 1, 4, 1)],
                     [self.row('a', 0, 12, 1)]):
            with self.assertRaises(ValueError):
                subject.plan(10, rows)
        with self.assertRaises(ValueError):
            subject.plan(10, [self.row('a', 0, 2, 1)], policy={'maxEndLagSeconds': 8})

    def test_schedule_is_exact_formal_scheduler_output(self):
        result = subject.plan(30, [self.row('a', 4, 8, 3), self.row('b', 10, 15, 7)])
        entries = result['formalSchedule']['entries']
        self.assertEqual(entries[0]['plannedStart'], 4.05)
        self.assertEqual(entries[1]['plannedStart'], 10.05)
        self.assertEqual(entries[1]['plannedEnd'], 17.05)
        self.assertEqual(result['groups'][1]['plannedEnd'], entries[1]['plannedEnd'])


if __name__ == '__main__':
    unittest.main()
