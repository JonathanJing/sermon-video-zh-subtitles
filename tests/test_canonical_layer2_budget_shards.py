"""Per-locale canonical Layer 2 budget ledgers (authorization v2)."""
import json
import tempfile
import unittest

from scripts import canonical_layer2_budget as budget
from scripts import sermon_review_budget as ledger
from tests import test_canonical_layer2_budget as base_tests

PER_CALL = {"requests": 1, "inputTokens": 16384, "outputTokens": 4096, "wallTimeMs": 300000,
            "costMicrousd": 81920}


def reserve_many(store, count):
    for n in range(count):
        h = "%064x" % n
        identity = {"sourceIdentitySha256": "1" * 64, "sourcePackageSha256": "2" * 64, "anchorSha256": "3" * 64,
                    "policySha256": "4" * 64, "rubricSha256": "5" * 64, "targetLocale": "zh-Hans",
                    "workUnitId": "l2.zh-Hans.call-" + h}
        store.reserve(identity, operation_id="model." + h, kind="initial_generation", revision_id="initial",
                      revision_number=1, input_sha256=h, bounds=PER_CALL)


class LocaleLedgerTests(unittest.TestCase):
    def setUp(self):
        self.base = base_tests.CanonicalLayer2BudgetTests(
            "test_missing_authority_blocks_drive_without_job_or_budget_writes")
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)

    def write_locale_authorization(self, *, scope_in_receipt=True):
        receipt = json.loads(self.base.receipt.read_text())
        if scope_in_receipt:
            receipt["binding"]["ledgerScope"] = "locale"
        path = self.base.fixture.root / "approval-locale.json"
        path.write_text(json.dumps(receipt))
        value = json.loads(self.base.auth_path.read_text())
        value.update(schemaVersion=budget.LOCALE_SCHEMA, ledgerScope="locale", approvalReceipt=path.name)
        value["authority"]["approvalSha256"] = budget.sha(path)
        auth = self.base.fixture.root / "budget-locale.json"
        auth.write_text(json.dumps(value))
        return auth

    def test_locale_authorization_shards_the_ledger_by_locale(self):
        auth = budget.load_authorization(self.base.config, self.write_locale_authorization(), self.base.code)
        self.assertEqual(auth["scope"], "locale")
        self.assertEqual(budget.ledger_root(auth, "zh-Hans"), auth["root"] / "zh-Hans")
        caller = budget.BudgetedCaller(auth, self.base.config, self.base.source, self.base.anchor, self.base.policy)
        self.assertEqual(caller.store.root, (auth["root"] / "zh-Hans").resolve())
        self.assertEqual(caller.store.max_ledger_bytes, budget.LOCALE_LEDGER_MAX_BYTES)
        run_scope = budget.load_authorization(self.base.config, self.base.auth_path, self.base.code)
        self.assertEqual(run_scope["scope"], "run")
        self.assertEqual(budget.ledger_root(run_scope, "zh-Hans"), run_scope["root"])

    def test_receipt_must_name_the_locale_scope(self):
        path = self.write_locale_authorization(scope_in_receipt=False)
        with self.assertRaisesRegex(ValueError, "budget_approval_not_bound"):
            budget.load_authorization(self.base.config, path, self.base.code)

    def test_v1_authorization_cannot_carry_a_scope(self):
        value = json.loads(self.base.auth_path.read_text())
        value["ledgerScope"] = "locale"
        self.base.auth_path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "invalid_budget_authorization"):
            budget.load_authorization(self.base.config, self.base.auth_path, self.base.code)

    def test_widened_ledger_passes_the_default_limit_which_still_applies_elsewhere(self):
        authority = {"approvalSha256": "a" * 64,
                     "globalBounds": {k: v * 2000 for k, v in PER_CALL.items()}, "unitBounds": PER_CALL,
                     "limits": dict(ledger.DEFAULT_LIMITS)}
        with tempfile.TemporaryDirectory() as root:
            wide = ledger.BudgetStore(root + "/wide", authority, max_ledger_bytes=budget.LOCALE_LEDGER_MAX_BYTES)
            reserve_many(wide, 300)  # past the 154 a default ledger holds
            narrow = ledger.BudgetStore(root + "/narrow", authority)
            with self.assertRaisesRegex(ValueError, "budget_ledger_size_limit"):
                reserve_many(narrow, 200)
        with self.assertRaisesRegex(ValueError, "invalid_budget_ledger_limit"):
            ledger.BudgetStore("/tmp/x", authority, max_ledger_bytes=1024)


if __name__ == "__main__":
    unittest.main()
