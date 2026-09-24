import unittest

from scripts.run_unittest_ci import shard_assignments


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


if __name__ == "__main__":
    unittest.main()
