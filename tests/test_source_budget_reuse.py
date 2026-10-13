"""A budget root may reuse a response another approved root of the run already paid for."""
from pathlib import Path
import tempfile
import unittest

from scripts import sermon_source_budget as subject
from scripts import sermon_workflow_jobs as jobs
from tests.test_source_budget_settlement import AUTHORITY, BOUNDS, IDENTITY, OPERATION, USAGE, call, ledger


def store(root, *, reuse=(), transport=None, authority=AUTHORITY):
    return subject.SourceBudget(root, authority, verify=lambda: None, reuse_roots=reuse,
                                transport=transport or (lambda *args: {"model": "gpt-6.1-sol", "usage": USAGE}))


class ReuseTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.text, self.audio = Path(directory.name) / "text", Path(directory.name) / "audio"
        # The text QC root pays for the call once.
        self.paid = call(store(self.text))

    def test_a_paid_response_is_reused_at_no_cost_and_records_where_it_came_from(self):
        dispatched = []
        audio = store(self.audio, reuse=[self.text], transport=lambda *args: dispatched.append(1))
        self.assertEqual(call(audio), self.paid)
        self.assertEqual(dispatched, [])
        row = ledger(self.audio)["requests"][OPERATION]
        self.assertEqual(row["status"], "returned")
        self.assertEqual((row["settlement"]["costStatus"], row["settlement"]["costMicrousd"]), ("reused", 0))
        saved = jobs._read(next((self.audio / "responses").iterdir()))
        self.assertEqual(saved["reusedFrom"]["budgetRoot"], str(self.text.resolve()))
        self.assertEqual(saved["reusedFrom"]["responseSha256"], ledger(self.text)["requests"][OPERATION]["responseSha256"])
        self.assertEqual(saved["reusedFrom"]["originalSettlement"]["costStatus"], "estimated_upper_bound")
        # A replay in the reusing root reads its own copy; the source root is untouched.
        self.assertEqual(call(store(self.audio, reuse=[self.text], transport=lambda *a: self.fail("dispatched"))), self.paid)
        self.assertEqual(len(ledger(self.text)["requests"]), 1)

    def test_a_reused_response_does_not_count_against_the_cap(self):
        tight = dict(AUTHORITY, globalBounds={"requests": 1, "wallTimeMs": 10 ** 9, "costMicrousd": 10 ** 9})
        audio = store(self.audio, reuse=[self.text], authority=tight)
        call(audio)  # reused, free
        other = dict(IDENTITY, index=2)
        audio.call(operation="judge." + "d" * 64, identity=other, bounds=BOUNDS, request=b"fixture", api_key="",
                   content_type="fixture", endpoint="fixture")  # the one paid request still fits
        rows = ledger(self.audio)["requests"]
        self.assertEqual(sorted(row["settlement"]["costStatus"] for row in rows.values()), ["estimated_upper_bound", "reused"])

    def test_only_an_identical_request_with_an_intact_response_is_reused(self):
        dispatched = []
        audio = store(self.audio, reuse=[self.text], transport=lambda *args: dispatched.append(1) or {"model": "gpt-6.1-sol", "usage": USAGE})
        changed = dict(IDENTITY, index=9)
        audio.call(operation=OPERATION.replace("c", "e"), identity=changed, bounds=BOUNDS, request=b"fixture",
                   api_key="", content_type="fixture", endpoint="fixture")
        self.assertEqual(dispatched, [1])
        # A matching paid receipt that was damaged blocks reconciliation; it is never re-bought.
        response = next((self.text / "responses").iterdir())
        saved = jobs._read(response); saved["response"] = {"model": "forged"}
        response.write_text(__import__("json").dumps(saved))
        fresh = Path(self.audio.parent) / "fresh"
        dispatched.clear()
        with self.assertRaisesRegex(ValueError, "source_reuse_response_reconciliation_required"):
            call(store(fresh, reuse=[self.text], transport=lambda *args: dispatched.append(1)))
        self.assertEqual(dispatched, [])

    def test_without_reuse_roots_the_call_is_paid_as_before(self):
        dispatched = []
        call(store(self.audio, transport=lambda *args: dispatched.append(1) or {"model": "gpt-6.1-sol", "usage": USAGE}))
        self.assertEqual(dispatched, [1])

    def test_a_root_cannot_reuse_itself(self):
        with self.assertRaisesRegex(ValueError, "invalid_source_reuse_roots"):
            store(self.text, reuse=[self.text])


if __name__ == "__main__":
    unittest.main()


class JudgeAuthorizationTests(unittest.TestCase):
    def write(self, directory, *, approved_reuse, requested_reuse):
        import hashlib, json
        bounds = {"globalBounds": {"requests": 10, "wallTimeMs": 10 ** 6, "costMicrousd": 10 ** 6},
                  "requestLimits": dict(subject.text_limits.DEFAULT_REQUEST_LIMITS)}
        root = str(directory / ".api-budget-audio")
        approval = {"schemaVersion": "sermon-machine-qc-api-budget-approval-v1", "humanApproval": True, "decision": "approved",
                    "binding": {"budgetRoot": root, **bounds, **({"reuseBudgetRoots": approved_reuse} if approved_reuse else {})}}
        (directory / "approval.json").write_text(json.dumps(approval))
        value = {"schemaVersion": "sermon-machine-qc-api-budget-authorization-v1", "budgetRoot": root,
                 "authority": {"approvalSha256": hashlib.sha256((directory / "approval.json").read_bytes()).hexdigest(),
                               "bounds": bounds, "requestLimits": bounds["requestLimits"]},
                 "approvalReceipt": "approval.json", **({"reuseBudgetRoots": requested_reuse} if requested_reuse else {})}
        (directory / "authorization.json").write_text(json.dumps(value))
        return directory / "authorization.json"

    def test_reuse_roots_must_be_named_by_the_approval(self):
        from unittest.mock import patch
        from scripts import run_machine_qc_clip_test as driver
        with tempfile.TemporaryDirectory() as name, patch("scripts.sermon_openai_runtime.selected_route", return_value=None):
            directory = Path(name)
            unapproved = self.write(directory, approved_reuse=None, requested_reuse=[str(directory / "text")])
            with self.assertRaisesRegex(ValueError, "not bound to its approval"):
                driver.ApiJudge(unapproved)
            approved = self.write(directory, approved_reuse=[str(directory / "text")], requested_reuse=[str(directory / "text")])
            # Bound correctly, it proceeds to the launcher check.
            with self.assertRaisesRegex(ValueError, "dev or prod OpenAI launcher"):
                driver.ApiJudge(approved)
