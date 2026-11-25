"""Sync-run silence trim: edge silence is removed, speech bytes and interior pauses are kept."""

import array
import sys
import tempfile
import unittest
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "experiments" / "sentence-first-agent"))

import trim_tts_silence as T  # noqa: E402

RATE = 24000


def write_wav(path: Path, samples: list[int]) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(array.array("h", samples).tobytes())


def read_wav(path: Path) -> list[int]:
    with wave.open(str(path), "rb") as handle:
        pcm = array.array("h")
        pcm.frombytes(handle.readframes(handle.getnframes()))
    return list(pcm)


class TrimTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.run = Path(self.tmp.name) / "run"
        self.tts = self.run / "tts"
        self.tts.mkdir(parents=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_trims_edges_and_keeps_interior(self) -> None:
        lead = int(0.37 * RATE)
        speech = [8000] * int(1.0 * RATE)
        gap = [0] * int(0.30 * RATE)
        speech2 = [8000] * int(0.8 * RATE)
        trail = int(0.07 * RATE)
        path = self.tts / "s0001.wav"
        write_wav(path, [0] * lead + speech + gap + speech2 + [0] * trail)

        saved, before, after = T.trim(path, 0.02)

        self.assertAlmostEqual(before, 2.54, places=2)
        self.assertGreater(after, 1.0 + 0.30 + 0.8)  # interior pause survives
        self.assertLess(after, before - 0.35)  # edges are gone
        self.assertAlmostEqual(saved, before - after, places=3)
        pcm = read_wav(path)
        self.assertEqual(pcm.count(0), int(0.30 * RATE) + int(T.LEAD_KEEP * RATE) + int(T.TAIL_KEEP * RATE))
        backup = self.run / "tts-raw-before-trim" / "s0001.wav"
        self.assertTrue(backup.exists())
        self.assertEqual(len(read_wav(backup)), len([0] * lead + speech + gap + speech2 + [0] * trail))

    def test_second_call_is_a_noop(self) -> None:
        path = self.tts / "s0002.wav"
        write_wav(path, [0] * int(0.3 * RATE) + [5000] * RATE + [0] * int(0.05 * RATE))
        T.trim(path, 0.02)
        again_saved, _, _ = T.trim(path, 0.02)
        self.assertAlmostEqual(again_saved, 0.0, places=3)

    def test_report_lists_every_sentence(self) -> None:
        write_wav(self.tts / "s0003.wav", [0] * int(0.2 * RATE) + [4000] * int(0.5 * RATE))
        sys.argv = ["trim_tts_silence.py", "--run", str(self.run)]
        self.assertEqual(T.main(), 0)
        import json

        report = json.loads((self.run / "tts-silence-trim.json").read_text(encoding="utf-8"))
        self.assertEqual(report["sentences"], 1)
        self.assertGreater(report["savedSeconds"], 0.1)


if __name__ == "__main__":
    unittest.main()


class SpeedFitPlanTest(unittest.TestCase):
    def setUp(self) -> None:
        sys.path.insert(0, str(HERE / "experiments" / "sentence-first-agent"))
        import speed_fit_tts as S

        self.S = S

    def rows(self, spans: list[tuple[float, float]]) -> list[dict]:
        rows = []
        for i, (start, end) in enumerate(spans, 1):
            slot = spans[i][0] - start if i < len(spans) else end - start
            rows.append({"id": f"s{i:04d}", "start": start, "slotSeconds": slot})
        return rows

    def test_sentences_that_fit_are_untouched(self) -> None:
        rows = self.rows([(0.0, 3.0), (3.3, 6.0), (6.3, 9.0)])
        durations = {"s0001": 2.9, "s0002": 2.6, "s0003": 2.6}
        plan, summary = self.S.plan_speed_fit(rows, durations)
        self.assertEqual(plan, [])
        self.assertEqual(summary["adjusted"], 0)

    def test_overrunning_sentence_is_fitted_and_capped(self) -> None:
        rows = self.rows([(0.0, 3.0), (3.3, 6.0), (6.3, 9.0), (9.3, 12.0)])
        durations = {"s0001": 3.0, "s0002": 6.0, "s0003": 2.6, "s0004": 2.6}
        plan, summary = self.S.plan_speed_fit(rows, durations, max_speed=1.15)
        ids = [item["id"] for item in plan]
        self.assertEqual(ids, ["s0002"])
        factor = plan[0]["factor"]
        self.assertLessEqual(factor, 1.15)
        self.assertGreater(factor, 1.0)
        self.assertGreater(summary["savedSeconds"], 0)

    def test_small_overrun_under_threshold_is_left_alone(self) -> None:
        rows = self.rows([(0.0, 2.0), (2.2, 4.2), (4.4, 6.4)])
        durations = {"s0001": 2.05, "s0002": 2.05, "s0003": 2.0}
        plan, _ = self.S.plan_speed_fit(rows, durations, threshold=0.3)
        self.assertEqual(plan, [])

    def test_missing_wav_is_skipped(self) -> None:
        rows = self.rows([(0.0, 3.0), (3.3, 6.0)])
        plan, summary = self.S.plan_speed_fit(rows, {"s0001": 3.0})
        self.assertEqual(summary["sentences"], 2)
        self.assertEqual(plan, [])


class SpeedLagPlanTest(unittest.TestCase):
    def setUp(self) -> None:
        sys.path.insert(0, str(HERE / "experiments" / "sentence-first-agent"))
        import speed_fit_tts as S

        self.S = S

    def test_only_sentences_past_threshold_are_touched(self) -> None:
        rows = [{"id": "s0001", "lagSeconds": 0.2, "dubSeconds": 5.0},
                {"id": "s0002", "lagSeconds": 2.0, "dubSeconds": 5.0},
                {"id": "s0003", "lagSeconds": 0.4, "dubSeconds": 5.0}]
        durations = {"s0001": 5.0, "s0002": 5.0, "s0003": 5.0}
        plan, summary = self.S.plan_lag_fit(rows, durations, threshold=0.5)
        self.assertEqual([item["id"] for item in plan], ["s0002"])
        self.assertAlmostEqual(plan[0]["factor"], 1.15, places=3)  # 5/(5-2)=1.667 -> capped

    def test_factor_aligns_end_to_the_time_point(self) -> None:
        rows = [{"id": "s0001", "lagSeconds": 0.6, "dubSeconds": 3.0}]
        plan, _ = self.S.plan_lag_fit(rows, {"s0001": 3.0}, threshold=0.5)
        # dub/(dub-lag) = 3/2.4 = 1.25 -> capped at 1.15
        self.assertAlmostEqual(plan[0]["factor"], 1.15, places=3)

    def test_no_schedule_row_means_no_change(self) -> None:
        plan, summary = self.S.plan_lag_fit([], {"s0001": 3.0}, threshold=0.5)
        self.assertEqual(plan, [])
        self.assertEqual(summary["adjusted"], 0)
