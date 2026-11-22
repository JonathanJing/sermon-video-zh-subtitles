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
