import unittest

from scripts.run_unittest_ci import module_name, shard_assignments, timing_weights


class ShardAssignmentTests(unittest.TestCase):
    def test_every_module_is_assigned_once_including_new_modules(self):
        modules = ["slow", "medium", "fast", "new"]
        weights = {"slow": 9.0, "medium": 5.0, "fast": 2.0}

        assignments = shard_assignments(modules, weights, 2)

        self.assertEqual(set(assignments), set(modules))
        self.assertEqual(set(assignments.values()), {0, 1})
        self.assertEqual(assignments, shard_assignments(list(reversed(modules)), weights, 2))

    def test_slow_modules_are_spread_across_shards(self):
        assignments = shard_assignments(
            ["slow_a", "slow_b", "fast_a", "fast_b"],
            {"slow_a": 10.0, "slow_b": 9.0, "fast_a": 1.0, "fast_b": 1.0},
            2,
        )

        self.assertNotEqual(assignments["slow_a"], assignments["slow_b"])

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
        self.assertNotEqual(
            shard_assignments(list(weights), weights, 2)["slow"],
            shard_assignments(list(weights), weights, 2)["new"],
        )

    def test_invalid_profile_cannot_produce_a_shard_estimate(self):
        for seconds, tests in ((-1, 1), (float("nan"), 1), (float("inf"), 1), (1, 0)):
            with self.subTest(seconds=seconds, tests=tests), self.assertRaises(ValueError):
                timing_weights({"module": 1}, {"modules": {"module": {"seconds": seconds, "tests": tests}}})


if __name__ == "__main__":
    unittest.main()
