"""Check semantic experiment identity and rejection boundaries without network."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from scripts.experiments import decision_semantic_eval as e
from tests import test_decision_api_cases_content as content_fixtures
response = content_fixtures.response


def fixture_item():
    return {"caseId": "constructed-negation", "sharedEvidence": {"source": "Do not fear.", "draft": "要害怕。"},
            "expected": "error", "question": e.question("classification", "Does the draft preserve the negation?", ["ok", "error"])}


class SemanticEvalTests(unittest.TestCase):
    def test_author_labels_not_in_either_arm_evidence(self):
        case = e.generic_case("E02", [fixture_item()], "constructed_semantic_challenge", "test")
        user = json.loads(case["a"]["payload"]["messages"][-1]["content"])
        self.assertEqual(user, json.loads(case["b"]["input"]))
        self.assertNotIn("expected", user["items"][0])
        self.assertEqual(case["expected"]["labels"], {"q00": "error"})
        e.ab.validate_cases([case])

    def test_classifier_rejects_missing_extra_and_invalid_labels(self):
        case = e.generic_case("E02", [fixture_item()], "constructed_semantic_challenge", "test")
        for labels in ({}, {"q00": "error", "unexpected": "error"}, {"q00": "not_allowed"}):
            with self.assertRaises(ValueError):
                e.normalize_a(case, response("gpt-6.1-sol", labels))
        self.assertEqual(e.normalize_a(case, response("gpt-6.1-sol", {"q00": "error"}))["labels"], {"q00": "error"})

    def test_shuffling_keeps_author_labels_bound_to_evidence(self):
        items = [fixture_item(), {**fixture_item(), "caseId": "faithful-case",
                 "sharedEvidence": {"source": "Do not fear.", "draft": "不要害怕。"}, "expected": "ok"}]
        case = e.generic_case("E02", items, "constructed_semantic_challenge", "test")
        by_hash = {e.ab.digest(i["sharedEvidence"]): i["expected"] for i in items}
        for item in case["sharedEvidence"]["items"]:
            self.assertEqual(case["expected"]["labels"][item["id"]], by_hash[e.ab.digest(item["evidence"])])

    def test_report_rejects_tampered_receipt(self):
        case = e.generic_case("E02", [fixture_item()], "constructed_semantic_challenge", "test")
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder).resolve()
            bound = {"schemaVersion": "decision-ab-budget-authority-v1", "root":str(out),
                     "maxCostMicrousd":20_000_000, "maxRequests":2,
                     "caseSetSha256":e.ab.digest([case]), "codeDependencySha256":"fixture"}
            ledger = e.ab.Ledger(out, bound)
            envelope = {"status":"returned", "response": response("gpt-6.1-sol", {"q00":"error"})}
            row = e.ab.measured_attempt(case,"A",mode="live",directory=out/"live",ledger=ledger,
                                       dispatcher=lambda *args: envelope)
            e.ab.atomic(out/"cases.json",[case]); e.ab.atomic(out/"authority.json",bound)
            self.assertEqual(e.report(out)["groups"]["E02:constructed_semantic_challenge"]["arms"]["A"]["validated"],1)
            row["labels"] = {"q00":"ok"}
            e.ab.atomic(out/"live"/"E02"/case["caseId"]/"A"/"receipt.json",row)
            with self.assertRaisesRegex(ValueError,"report_receipt_identity_changed"):e.report(out)

    def test_english_batch_coverage_and_receipt_evidence_required(self):
        fixture = content_fixtures.ContentCasesTests(); fixture.setUp()
        try:
            fixture.english_fixture()
            from scripts.experiments import decision_api_cases_content as c
            original = c.build_content_cases(fixture.root)[0]
            case = e.english_batch([original])
            self.assertEqual({c["value"] for c in case["b"]["questions"][0]["choices"]}, {"pass","fail"})
            self.assertEqual(case["a"]["payload"]["messages"][0]["content"], e.english.SYSTEM_PROMPT)
            unit = case["sharedEvidence"]["sentences"][0]
            row = {"sourceSentenceId": unit["sourceSentenceId"],
                   "sourceUnitIds": [u["sourceUnitId"] for u in unit["units"]], "verdict": "pass",
                   "risk": "low", "checks": {k: "pass" for k in e.english.CHECKS},
                   "evidence": "Fixture explanation", "unresolvedIssues": []}
            result = {"schemaVersion": e.english.BATCH_SCHEMA, "sentences": [row]}
            self.assertEqual(e.normalize_a(case, response("gpt-6.1-sol", result))["labels"], {"q00": "pass"})
            for change in ({"sourceSentenceId": "wrong"}, {"evidence": ""}):
                changed = copy.deepcopy(result); changed["sentences"][0].update(change)
                with self.assertRaises(ValueError): e.normalize_a(case, response("gpt-6.1-sol", changed))
            result["sentences"][0]["unresolvedIssues"] = ["Unresolved slicing concern"]
            self.assertEqual(e.normalize_a(case, response("gpt-6.1-sol", result))["labels"], {"q00": "fail"})
        finally:
            fixture.temp.cleanup()


if __name__ == "__main__": unittest.main()
