from pathlib import Path
import tempfile
import unittest

from scripts import sermon_source_budget as subject
from scripts import sermon_workflow_jobs as jobs

USAGE = {"prompt_tokens": 1200, "completion_tokens": 300, "total_tokens": 1500,
         "prompt_tokens_details": {"cached_tokens": 1000}, "completion_tokens_details": {"reasoning_tokens": 100}}


AUTHORITY = {"approvalSha256": "a" * 64, "globalBounds": {"requests": 8, "wallTimeMs": 10 ** 9, "costMicrousd": 10 ** 9},
             "requestLimits": dict(subject.text_limits.DEFAULT_REQUEST_LIMITS)}
BOUNDS = {"requests": 1, "wallTimeMs": 1000, "costMicrousd": 1000}
IDENTITY = {"model": "gpt-6.1-sol", "index": 1}
OPERATION = "judge." + "c" * 64  # judge operations are keyed by the payload digest


def store(root, transport=None):
    return subject.SourceBudget(root, AUTHORITY, verify=lambda: None,
                                transport=transport or (lambda *args: {"model": "gpt-6.1-sol", "usage": USAGE}))


def call(budget):
    return budget.call(operation=OPERATION, identity=IDENTITY, bounds=BOUNDS, request=b"fixture", api_key="",
                       content_type="fixture", endpoint="fixture")


def ledger(root):
    return jobs._read(root / "source-budget.json")


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



class LedgerVersionTests(unittest.TestCase):
    """Review finding: settlement widened v2 in place, so a frozen v2 reader would call the ledger corrupt."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.addCleanup(self.directory.cleanup)

    def v2_ledger(self, requests=None):
        jobs._persist(self.root / "source-budget.json", {"schemaVersion": subject.LEDGER_V2, "authority": AUTHORITY,
                      "requests": requests or {}, "maxConcurrent": 1, "resourcePolicySha256": None})

    def test_a_v2_ledger_stays_v2_and_gets_no_settlement(self):
        self.v2_ledger()
        call(store(self.root))
        written = ledger(self.root)
        self.assertEqual(written["schemaVersion"], subject.LEDGER_V2)
        self.assertNotIn("settlement", written["requests"][OPERATION])
        # The saved response still records it, so an explicit migration can book it later.
        saved = jobs._read(store(self.root)._response_path(OPERATION, jobs._digest(IDENTITY)))
        self.assertEqual(saved["settlement"]["costStatus"], "estimated_upper_bound")

    def test_v2_rows_with_settlement_and_v3_returned_rows_without_it_are_corrupt(self):
        row = {"identitySha256": "b" * 64, "bounds": BOUNDS, "status": "returned", "responseSha256": "d" * 64}
        self.v2_ledger({"asr.0000": dict(row, settlement={"costStatus": "unknown", "costMicrousd": None})})
        with self.assertRaisesRegex(ValueError, "source_budget_ledger_corrupt"):
            store(self.root).returned("asr.0000", {})
        jobs._persist(self.root / "source-budget.json", dict(ledger(self.root), schemaVersion=subject.LEDGER_V3,
                      requests={"asr.0000": row}))
        with self.assertRaisesRegex(ValueError, "source_budget_ledger_corrupt"):
            store(self.root).returned("asr.0000", {})

    def test_explicit_migration_settles_returned_rows_from_their_saved_responses(self):
        self.v2_ledger()
        call(store(self.root))
        receipt = store(self.root).migrate_to_v3()
        self.assertEqual((receipt["status"], receipt["settledRows"], receipt["unknownCostRows"], receipt["modelCalls"]),
                         ("migrated", 1, 0, 0))
        written = ledger(self.root)
        self.assertEqual(written["schemaVersion"], subject.LEDGER_V3)
        self.assertEqual(written["requests"][OPERATION]["settlement"]["usage"]["inputTokens"], 1200)
        self.assertEqual(store(self.root).migrate_to_v3()["status"], "already_v3")
        self.assertEqual(call(store(self.root))["usage"], USAGE)  # a replay still reads the migrated ledger

    def test_migration_refuses_a_changed_response_and_leaves_the_ledger_alone(self):
        self.v2_ledger()
        call(store(self.root))
        path = store(self.root)._response_path(OPERATION, jobs._digest(IDENTITY))
        jobs._persist(path, dict(jobs._read(path), elapsedSeconds=99))
        before = ledger(self.root)
        with self.assertRaisesRegex(ValueError, "source_response_identity_changed"):
            store(self.root).migrate_to_v3()
        self.assertEqual(ledger(self.root), before)

    def test_reconciliation_books_the_saved_settlement(self):
        """Review finding: a crash after saving the response but before booking it lost the settlement."""
        budget = store(self.root)
        with budget._locked() as (written, path):
            written["requests"][OPERATION] = {"identitySha256": jobs._digest(IDENTITY), "bounds": BOUNDS,
                                              "status": "started_response_unconfirmed"}
            jobs._persist(path, written)
        saved = {"identitySha256": jobs._digest(IDENTITY), "requestIdentity": IDENTITY,
                 "response": {"model": "gpt-6.1-sol", "usage": USAGE}, "modelCallId": None, "elapsedSeconds": 3.0,
                 "reservationBounds": BOUNDS, "invoiceVerified": False}  # written before settlement existed
        response_path = budget._response_path(OPERATION, jobs._digest(IDENTITY))
        response_path.parent.mkdir(parents=True)
        jobs._persist(response_path, saved)
        self.assertEqual(budget.reconcile_returned(OPERATION, jobs._digest(IDENTITY))["status"], "returned_response_reconciled")
        row = ledger(self.root)["requests"][OPERATION]
        self.assertEqual(row["status"], "returned")
        self.assertEqual(row["settlement"], subject.settlement(IDENTITY, saved["response"], 3.0))
        self.assertEqual(row["settlement"]["costStatus"], "estimated_upper_bound")


if __name__ == "__main__":
    unittest.main()
