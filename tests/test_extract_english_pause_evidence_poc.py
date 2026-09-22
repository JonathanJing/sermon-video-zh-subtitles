import array
import unittest

from scripts import extract_english_pause_evidence_poc as subject


class EnglishPauseEvidenceTest(unittest.TestCase):
    def test_alignment_gap_alone_is_not_pause_evidence(self):
        samples = array.array("h", [7000] * 8000 + [0] * 8000 + [7000] * 8000)
        intervals, _ = subject.low_energy_intervals(samples)
        words = [
            {"wordId": "w1", "text": "one", "start": 0.0, "end": 0.5},
            {"wordId": "w2", "text": "two", "start": 1.0, "end": 1.5},
        ]
        self.assertEqual(subject.boundary_evidence(words, intervals, 0.0)[0]["classification"],
                         "supported_pause_candidate")
        self.assertEqual(subject.boundary_evidence(words, [], 0.0)[0]["classification"],
                         "alignment_gap_only")


if __name__ == "__main__":
    unittest.main()
