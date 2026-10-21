"""A longer clip may shard its Layer 2 budget ledger per locale, as a week always does.

A run-wide Layer 2 ledger is capped at 256 KiB. A 7-minute clip is ~88 groups per locale, and the
reservations alone reach the cap before any of them settles, so the clip must be able to use the
week's per-locale layout (8 MiB each) when the approved profile says so.
"""
import json
import unittest
from pathlib import Path

from scripts import plan_run_budgets


def sharded_for(scale, profile_layer2):
    profile = {"layer2": profile_layer2}
    return scale == "week" or (profile_layer2.get("ledgerScope") or {}).get(scale) == "locale", profile


class LedgerScopeTests(unittest.TestCase):
    def test_a_week_always_shards(self):
        sharded, _ = sharded_for("week", {})
        self.assertTrue(sharded)

    def test_a_clip_keeps_one_run_ledger_unless_the_profile_says_otherwise(self):
        sharded, _ = sharded_for("clip", {})
        self.assertFalse(sharded)

    def test_a_clip_may_opt_into_per_locale_ledgers(self):
        sharded, _ = sharded_for("clip", {"ledgerScope": {"clip": "locale"}})
        self.assertTrue(sharded)

    def test_the_default_profile_still_shares_one_clip_ledger(self):
        profile = json.loads((Path(__file__).resolve().parents[1]
                              / "config/weekly-run-profile.json").read_text())
        self.assertFalse(sharded_for("clip", profile["layer2"])[0])
        self.assertTrue(sharded_for("week", profile["layer2"])[0])

    def test_the_seven_minute_profile_shards_its_clip_ledger(self):
        profile = json.loads((Path(__file__).resolve().parents[1]
                              / "config/clip-e2e/seven-minute-run-profile.json").read_text())
        self.assertTrue(sharded_for("clip", profile["layer2"])[0])

    def test_the_planner_reads_the_profile_rather_than_the_scale_alone(self):
        # The decision statement the planner runs, kept in one place to catch a silent revert.
        source = Path(plan_run_budgets.__file__).read_text()
        self.assertIn('(layer2.get("ledgerScope") or {}).get(scale) == "locale"', source)


if __name__ == "__main__":
    unittest.main()
