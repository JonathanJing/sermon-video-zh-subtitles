from __future__ import annotations

import unittest

from backend.asr_gold import prepare_review_queue, validate_human_gold


class AsrGoldTest(unittest.TestCase):
    def test_pending_queue_fails_closed(self) -> None:
        queue = prepare_review_queue({"cases": [{"caseId": "case-1", "referenceText": "Candidate", "asrTextSpeechOnly": "Hypothesis"}]})
        self.assertEqual(queue[0]["reviewStatus"], "pending_human_review")
        with self.assertRaisesRegex(ValueError, "not approved_human_gold"):
            validate_human_gold(queue)

    def test_complete_human_review_passes(self) -> None:
        record = {
            "schemaVersion": "asr-human-gold-review-v1",
            "caseId": "case-1",
            "correctedReferenceText": "Human corrected words.",
            "reviewStatus": "approved_human_gold",
            "reviewer": "Reviewer Name",
            "reviewedAt": "2099-01-01T00:00:00Z",
        }
        self.assertEqual(validate_human_gold([record]), {"case-1": "Human corrected words."})


if __name__ == "__main__":
    unittest.main()
