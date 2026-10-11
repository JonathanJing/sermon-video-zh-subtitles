from pathlib import Path
import tempfile
import unittest

from scripts import sermon_source_budget as subject
from scripts import sermon_workflow_jobs as jobs

USAGE = {"prompt_tokens": 1200, "completion_tokens": 300, "total_tokens": 1500,
         "prompt_tokens_details": {"cached_tokens": 1000}, "completion_tokens_details": {"reasoning_tokens": 100}}


class SettlementTests(unittest.TestCase):
    def test_measured_usage_is_priced_at_the_requested_model_rate(self):
        result = subject.settlement({"model": "gpt-6.1-sol"}, {"model": "gpt-6.1-sol-2026-09-01", "usage": USAGE}, 4.2)
        self.assertEqual(result["costStatus"], "estimated_upper_bound")
        self.assertEqual(result["costMicrousd"], subject.text_limits._cost("gpt-6.1-sol", 1200, 300))
        self.assertGreater(result["costMicrousd"], 0)
        self.assertEqual(result["usage"], {"inputTokens": 1200, "outputTokens": 300, "cachedInputTokens": 1000,
                                           "reasoningTokens": 100, "totalTokens": 1500})
        self.assertEqual((result["requestedModel"], result["providerModel"], result["elapsedSeconds"]),
                         ("gpt-6.1-sol", "gpt-6.1-sol-2026-09-01", 4.2))
        self.assertFalse(result["invoiceVerified"])

    def test_unknown_usage_or_price_settles_as_unknown_not_zero(self):
        missing = subject.settlement({"model": "gpt-6.1-sol"}, {"fixture": "returned"}, 1.0)
        self.assertEqual((missing["costStatus"], missing["costMicrousd"], missing["reasonCode"]),
                         ("unknown", None, "missing_provider_usage"))
        malformed = subject.settlement({"model": "gpt-6.1-sol"}, {"usage": {"prompt_tokens": "12", "completion_tokens": 3}}, 1.0)
        self.assertEqual(malformed["reasonCode"], "missing_or_invalid_token_counts")
        unpriced = subject.settlement({"model": "gpt-transcribe"}, {"usage": {"input_tokens": 500, "output_tokens": 40}}, 2.0)
        self.assertEqual((unpriced["costStatus"], unpriced["reasonCode"]), ("unknown", "no_frozen_price_for_model"))
        self.assertEqual(unpriced["usage"]["inputTokens"], 500)  # tokens are still recorded for the retrospective

    def test_ledger_row_and_saved_response_carry_the_settlement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authority = {"approvalSha256": "a" * 64,
                         "globalBounds": {"requests": 8, "wallTimeMs": 10 ** 9, "costMicrousd": 10 ** 9},
                         "requestLimits": dict(subject.text_limits.DEFAULT_REQUEST_LIMITS)}
            store = subject.SourceBudget(root, authority, verify=lambda: None,
                                         transport=lambda *args: {"model": "gpt-6.1-sol", "usage": USAGE})
            bounds = {"requests": 1, "wallTimeMs": 1000, "costMicrousd": 1000}
            operation = "judge." + "c" * 64  # judge operations are keyed by the payload digest
            response = store.call(operation=operation, identity={"model": "gpt-6.1-sol", "index": 1}, bounds=bounds,
                                  request=b"fixture", api_key="", content_type="fixture", endpoint="fixture")
            self.assertEqual(response["usage"], USAGE)
            row = jobs._read(root / "source-budget.json")["requests"][operation]
            self.assertEqual(row["status"], "returned")
            self.assertEqual(row["bounds"]["costMicrousd"], 1000)  # the reservation stays what was booked
            self.assertEqual(row["settlement"]["costStatus"], "estimated_upper_bound")
            self.assertEqual(row["settlement"]["usage"]["inputTokens"], 1200)
            # A replay returns the saved response and keeps the row untouched.
            store.call(operation=operation, identity={"model": "gpt-6.1-sol", "index": 1}, bounds=bounds,
                       request=b"fixture", api_key="", content_type="fixture", endpoint="fixture")
            again = jobs._read(root / "source-budget.json")["requests"][operation]
            self.assertEqual(again["settlement"], row["settlement"])


if __name__ == "__main__":
    unittest.main()
