import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "experiments" / "sentence-first-agent"))

import lag_loop  # noqa: E402


class LagGateTest(unittest.TestCase):
    def test_clean_track_passes(self):
        gate = lag_loop.final_gate({"maxLagSeconds": 6.4, "sentencesOverLag8s": 0}, 8.0)
        self.assertTrue(gate["clean"])

    def test_any_over_threshold_fails(self):
        gate = lag_loop.final_gate({"maxLagSeconds": 9.2, "sentencesOverLag8s": 1}, 8.0)
        self.assertFalse(gate["clean"])

    def test_max_lag_alone_fails_even_with_zero_over(self):
        gate = lag_loop.final_gate({"maxLagSeconds": 8.7, "sentencesOverLag8s": 0}, 8.0)
        self.assertFalse(gate["clean"])


if __name__ == "__main__":
    unittest.main()
