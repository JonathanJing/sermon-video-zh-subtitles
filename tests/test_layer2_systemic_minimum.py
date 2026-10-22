"""A clip may raise how many adjacent same-code failures stop Layer 2 repair.

A full week stops dispatch when three adjacent groups fail with one code, because adjacent
failures there usually mean a batch-wide rule gap. A clip cut from a reviewed sermon can contain
a cluster of one known defect (several sentences sharing a register error); stopping leaves the
locale with no candidate at all. The threshold is raise-only, so the week default never loosens.
"""
import unittest

from tongxing_production.text import auto_repair


class SystemicMinimumTests(unittest.TestCase):
    def test_the_default_is_three(self):
        self.assertEqual(auto_repair.SYSTEMIC_MINIMUM_GROUPS, 3)
        self.assertEqual(auto_repair.systemic_threshold(88), 3)

    def test_a_raised_minimum_needs_a_consecutive_run_at_least_that_long(self):
        self.assertEqual(auto_repair.systemic_threshold(88, 5), 5)
        # The fraction term still applies to a large batch.
        self.assertEqual(auto_repair.systemic_threshold(2000, 3), 20)

    def test_a_collector_records_the_effective_threshold(self):
        collector = auto_repair.FailureCollector(88, systemic_minimum_groups=5)
        self.assertEqual(collector.threshold, 5)
        self.assertEqual(collector.identity["systemicThreshold"], 5)
        default = auto_repair.FailureCollector(88)
        self.assertEqual(default.threshold, 3)
        self.assertEqual(default.identity["systemicThreshold"], 3)

    def test_an_out_of_range_minimum_is_refused(self):
        for value in (0, -1, 33, True, "5", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                auto_repair.FailureCollector(88, systemic_minimum_groups=value)


if __name__ == "__main__":
    unittest.main()
