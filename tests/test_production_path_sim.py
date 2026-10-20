import contextlib
from dataclasses import replace
import io
import json
import unittest

from tools.ops import production_path_sim as sim
from tools.ops.production_path_sim import (
    Resource,
    SCENARIOS,
    Scenario,
    simulate,
    simulate_once,
    sweep_rows,
)


class ProductionPathSimTest(unittest.TestCase):
    def test_resource_serializes_single_capacity(self):
        resource = Resource(1)
        self.assertEqual(resource.earliest(0, 5), 0)
        resource.reserve(0, 5)
        self.assertEqual(resource.earliest(0, 3), 5)
        self.assertEqual(resource.earliest(2, 3), 5)
        resource.reserve(5, 1)  # back-to-back work extends the last reservation
        self.assertEqual(resource.reservations, [(0, 6, 1)])
        self.assertEqual(resource.busy_minutes(), 6)

    def test_family_page_waits_for_all_locales(self):
        family = simulate_once(SCENARIOS["batch_family_clean"], seed=1)
        separate = simulate_once(SCENARIOS["batch_separate_clean"], seed=1)
        self.assertGreater(family.first_page, separate.first_page)

    def test_streaming_beats_barrier_for_first_page(self):
        batch = simulate_once(SCENARIOS["batch_separate_clean"], seed=1)
        stream = simulate_once(SCENARIOS["stream_separate"], seed=1)
        self.assertLess(stream.first_page, batch.first_page)

    def test_stream_review_follows_individual_groups(self):
        # Without rework the first page is L1, one API wave, the whole review,
        # the last TTS batch window, package, spot check and deploy.
        scenario = replace(SCENARIOS["stream_separate"], rework="none")
        d = scenario.durations
        groups = scenario.locales[0].groups
        wave = d.text * sim.API_WORKERS / groups
        last_window = d.tts / groups * (groups - (groups - 1) // sim.TTS_BATCH * sim.TTS_BATCH)
        expected = d.l1 + wave + d.text_review + last_window + d.post + d.audio_spot + d.deploy
        self.assertAlmostEqual(simulate_once(scenario, seed=1).first_page, expected, places=6)

    def test_text_first_page_includes_its_audio_unavailable_package(self):
        result = simulate_once(SCENARIOS["stream_textfirst"], seed=1)
        self.assertLess(result.first_page, min(result.pages.values()))
        longer = replace(SCENARIOS["stream_textfirst"],
                         durations=replace(SCENARIOS["stream_textfirst"].durations, text_package=15.0))
        self.assertAlmostEqual(simulate_once(longer, seed=1).first_page - result.first_page, 10.0, places=6)

    def test_full_audio_review_adds_about_thirty_minutes(self):
        spot = simulate_once(SCENARIOS["stream_separate"], seed=1)
        full = simulate_once(replace(SCENARIOS["stream_separate"], audio_review="full"), seed=1)
        self.assertAlmostEqual(full.first_page - spot.first_page, 30.0, delta=0.2)

    def test_calibrated_actual_matches_observed_158_minutes(self):
        result = simulate_once(SCENARIOS["batch_family_actual"], seed=1)
        self.assertTrue(155.0 <= result.first_page <= 162.0, result.first_page)

    def test_whole_rework_is_reviewed_again(self):
        clean = simulate(SCENARIOS["batch_family_clean"], trials=60, seed=7)
        rework = simulate(SCENARIOS["batch_family_rework"], trials=60, seed=7)
        self.assertGreater(rework["human_busy"], clean["human_busy"])
        reran = next(seed for seed in range(100)
                     if simulate_once(SCENARIOS["batch_family_rework"], seed).first_page
                     > simulate_once(SCENARIOS["batch_family_clean"], seed).first_page + 40)
        # One rerun costs the regeneration and a second full text review.
        self.assertGreaterEqual(simulate_once(SCENARIOS["batch_family_rework"], reran).human_busy,
                                simulate_once(SCENARIOS["batch_family_clean"], reran).human_busy
                                + SCENARIOS["batch_family_rework"].durations.text_review)

    def test_group_rework_has_a_shorter_tail_than_whole_rework(self):
        batch = simulate(SCENARIOS["batch_family_rework"], trials=120, seed=7)
        stream = simulate(SCENARIOS["stream_separate"], trials=120, seed=7)
        self.assertLess(stream["first_p90"], batch["first_p90"])
        self.assertLess(stream["first_p90"], 75.0)

    def test_stream_scenarios_reject_whole_text_rework(self):
        with self.assertRaises(ValueError):
            Scenario(name="x", description="", page_mode="separate", text_mode="stream", rework="whole")

    def test_text_review_sweep_is_monotonic(self):
        rows = sweep_rows(5, seed=1)["text_review"]
        values = [row["paths"]["stream_textfirst"] for row in rows]
        self.assertEqual(values, sorted(values))

    def test_audio_review_leaves_text_page_unchanged(self):
        fast = simulate_once(replace(SCENARIOS["stream_textfirst"], audio_minutes_override=0.0), seed=1)
        slow = simulate_once(replace(SCENARIOS["stream_textfirst"], audio_minutes_override=33.0), seed=1)
        self.assertEqual(fast.first_page, slow.first_page)
        self.assertGreater(min(slow.pages.values()), min(fast.pages.values()))

    def test_machine_checked_text_first_is_faster_than_reviewed(self):
        reviewed = simulate_once(SCENARIOS["stream_textfirst"], seed=1)
        machine = simulate_once(replace(SCENARIOS["stream_textfirst"], text_review=False), seed=1)
        self.assertLess(machine.first_page, reviewed.first_page)

    def test_cli_calibrates_and_rejects_overrides_with_sweep(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(sim.main(["--calibrate", "--trials", "2"]), 0)
        result = json.loads(out.getvalue())
        self.assertEqual(result["observedFirstPageMinutes"], 158.0)
        self.assertLess(abs(result["simulatedFirstPageMinutes"] - 158.0), 2.0)
        for argv in (["--sweep", "--audio", "full"], ["--sweep", "--text-review", "none"],
                     ["--sweep", "--calibrate"]):
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                sim.main(argv)


if __name__ == "__main__":
    unittest.main()
