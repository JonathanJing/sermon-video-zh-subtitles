import unittest

from scripts.run_unittest_ci import case_costs, case_shard_assignments, module_name, timing_weights


class ShardAssignmentTests(unittest.TestCase):
    def assign(self, cases, weights, counts, shards, slow=None):
        return case_shard_assignments(cases, case_costs(cases, weights, counts, slow), shards)

    def test_every_case_is_assigned_once_including_new_modules(self):
        cases = ["slow.A.test_1", "slow.A.test_2", "medium.B.test_1", "fast.C.test_1", "new.D.test_1"]
        counts = {"slow": 2, "medium": 1, "fast": 1, "new": 1}
        weights = {"slow": 18.0, "medium": 5.0, "fast": 2.0}

        assignments = self.assign(cases, weights, counts, 2)

        self.assertEqual(len(assignments), len(cases))
        self.assertEqual(set(assignments), {0, 1})
        by_case = dict(zip(cases, assignments))
        reversed_cases = list(reversed(cases))
        self.assertEqual(by_case, dict(zip(reversed_cases, self.assign(reversed_cases, weights, counts, 2))))

    def test_one_slow_module_spreads_across_shards(self):
        cases = [f"slow.A.test_{index}" for index in range(4)] + ["fast.B.test_1", "fast.B.test_2"]
        assignments = self.assign(cases, {"slow": 40.0, "fast": 2.0}, {"slow": 4, "fast": 2}, 4)

        self.assertEqual(set(assignments[:4]), {0, 1, 2, 3})

    def test_packaged_case_ids_use_their_module_cost(self):
        assignments = self.assign(
            ["tests.slow.A.test_1", "slow.A.test_2", "fast.B.test_1"],
            {"slow": 20.0, "fast": 1.0}, {"slow": 2, "fast": 1}, 2,
        )

        self.assertNotEqual(assignments[0], assignments[1])

    def test_a_case_discovered_twice_runs_in_some_shard_both_times(self):
        assignments = self.assign(["mod.A.test_1", "mod.A.test_1", "mod.A.test_2"], {"mod": 3.0}, {"mod": 3}, 2)

        self.assertEqual(sorted(assignments), [0, 0, 1])

    def test_slow_cases_keep_their_own_cost_and_the_module_remainder_is_shared(self):
        cases = ["mod.A.test_big", "tests.mod.A.test_medium", "mod.A.test_small_1", "mod.A.test_small_2"]
        slow = {"mod.A.test_big": 60.0, "tests.mod.A.test_medium": 30.0, "gone.A.test_old": 99.0}

        costs = case_costs(cases, {"mod": 100.0}, {"mod": 4}, slow)

        self.assertEqual(costs, [60.0, 30.0, 5.0, 5.0])
        self.assertEqual(case_shard_assignments(cases, costs, 2), [0, 1, 1, 1])

    def test_slow_cases_beyond_the_module_total_leave_a_minimal_remainder(self):
        costs = case_costs(["mod.A.test_big", "mod.A.test_small"], {"mod": 10.0}, {"mod": 2}, {"mod.A.test_big": 20.0})

        self.assertEqual(costs, [20.0, 0.001])

    def test_invalid_slow_case_timings_are_rejected(self):
        for seconds in (-1, float("nan"), float("inf")):
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                case_costs(["mod.A.test"], {"mod": 1.0}, {"mod": 1}, {"mod.A.test": seconds})

    def test_packaged_test_classes_keep_their_module_identity(self):
        class PackagedCase(unittest.TestCase):
            def id(self):
                return "tests.test_audio.AudioTests.test_replay"

        self.assertEqual(module_name(PackagedCase()), "test_audio")
        self.assertEqual(module_name(self), "test_run_unittest_ci")

    def test_changed_case_counts_and_new_modules_use_measured_cost(self):
        previous = {"modules": {
            "slow": {"seconds": 20.0, "tests": 10},
            "fast": {"seconds": 2.0, "tests": 10},
        }}
        weights = timing_weights({"slow": 5, "fast": 20, "new": 30}, previous)
        self.assertEqual(weights["slow"], 10.0)
        self.assertEqual(weights["fast"], 4.0)
        self.assertAlmostEqual(weights["new"], 33.0)

    def test_invalid_profile_cannot_produce_a_shard_estimate(self):
        for seconds, tests in ((-1, 1), (float("nan"), 1), (float("inf"), 1), (1, 0)):
            with self.subTest(seconds=seconds, tests=tests), self.assertRaises(ValueError):
                timing_weights({"module": 1}, {"modules": {"module": {"seconds": seconds, "tests": tests}}})


if __name__ == "__main__":
    unittest.main()
