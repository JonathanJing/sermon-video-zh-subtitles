"""Two-way Mac TTS sharding keeps every sentence on its single-process seed."""
import unittest

from tests import experiment_modules

planner = experiment_modules.line_module("experiments/mac-tts-benchmark/split_windows.py")


def rows(count):
    return [{"id": f"s{i:04d}", "spokenText": f"text {i}"} for i in range(count)]


class MacTtsTwoWayTests(unittest.TestCase):
    def test_shards_keep_complete_windows_and_original_seeds(self):
        source = rows(20)
        result = planner.plan(source, workers=2, batch_size=8, base_seed=42)
        shards, manifest = result["shards"], result["manifest"]
        self.assertEqual([window["worker"] for window in manifest["windows"]], [0, 1, 0])
        self.assertEqual([window["seed"] for window in manifest["windows"]], [42, 50, 58])
        self.assertEqual([len(shard) for shard in shards], [12, 8])
        single = {row["id"]: 42 + (index // 8) * 8 for index, row in enumerate(source)}
        seen = []
        for shard in shards:
            for row in shard:
                self.assertEqual(row["seed"], single[row["id"]])
                self.assertEqual(row["windowStart"], (row["_originalIndex"] // 8) * 8)
                self.assertEqual(source[row["_originalIndex"]]["id"], row["id"])
                seen.append(row["id"])
        self.assertEqual(sorted(seen), sorted(single))
        self.assertEqual(len(seen), len(set(seen)))

    def test_partial_tail_window_stays_on_one_worker(self):
        result = planner.plan(rows(10), workers=2, batch_size=4, base_seed=42)
        windows = result["manifest"]["windows"]
        self.assertEqual([window["size"] for window in windows], [4, 4, 2])
        self.assertEqual([window["seed"] for window in windows], [42, 46, 50])
        self.assertFalse(windows[-1]["complete"])
        shard = next(shard for shard in result["shards"] if any(row["id"] == "s0008" for row in shard))
        self.assertIn("s0009", [row["id"] for row in shard])

    def test_manifest_records_each_shards_seed_set(self):
        result = planner.plan(rows(20), workers=2, batch_size=8, base_seed=42)
        self.assertEqual(result["manifest"]["shards"], [
            {"worker": 0, "sentences": 12, "seeds": [42, 58]},
            {"worker": 1, "sentences": 8, "seeds": [50]},
        ])
        self.assertIn("unchanged by sharding", result["manifest"]["seedPolicy"])

    def test_invalid_plans_are_refused(self):
        for kwargs in ({"workers": 0, "batch_size": 8}, {"workers": 2, "batch_size": 3}):
            with self.assertRaises(ValueError):
                planner.plan(rows(8), base_seed=42, **kwargs)
        with self.assertRaises(ValueError):
            planner.plan([], workers=2, batch_size=8, base_seed=42)


if __name__ == "__main__":
    unittest.main()
