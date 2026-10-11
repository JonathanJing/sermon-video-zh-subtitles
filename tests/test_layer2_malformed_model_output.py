"""Malformed translator/reviewer replies fail one group, not the whole locale run."""
import json
from pathlib import Path
import tempfile
import unittest

from scripts import layer2_auto_repair as repair
from scripts import run_target_language_models as runner


class UtteranceShapeTests(unittest.TestCase):
    def test_wrapped_utterances_accept_text_or_target_text(self):
        for key in ("targetText", "text"):
            with self.subTest(key=key):
                value = [{"sourceUnitIds": ["u1"], key: "一句话。"}]
                self.assertEqual(runner._utterances(value, ["u1"]), ["一句话。"])

    def test_conflicting_or_unbound_wrappers_are_still_rejected(self):
        for value in ([{"sourceUnitIds": ["u1"], "text": "甲", "targetText": "乙"}],
                      [{"sourceUnitIds": ["u2"], "text": "甲"}], [{"text": "甲"}]):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "nonempty targetUtterances"):
                runner._utterances(value, ["u1"])


class CollectorTests(unittest.TestCase):
    def test_malformed_translator_reply_becomes_a_translator_repair(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder) / "group-0001-astra.json"
            cache.write_text(json.dumps({"result": {}}))
            collector = repair.FailureCollector(461)
            group = {"translationGroupId": "g1", "sourceUnitIds": ["u1"]}
            collector.record_malformed_output(1, group, "translator", cache, "Model must return nonempty targetUtterances")
            failure = collector.failures[0]
            self.assertEqual(failure["failureCodes"], ["malformed_model_output"])
            self.assertEqual(failure["action"], "repair_translation")
            row = repair.repair_row(failure)
            self.assertEqual(row["failedRole"], "translator")
            self.assertIn("JSON contract", row["instruction"])
            self.assertFalse(collector.stopped())

    def test_unknown_role_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "translator or reviewer"):
            repair.FailureCollector(10).record_malformed_output(1, {"translationGroupId": "g", "sourceUnitIds": ["u"]},
                                                                "judge", Path("missing"), "x")

    def test_repeated_malformed_output_escalates(self):
        self.assertEqual(repair.REPEATED_FAILURE_ACTIONS["malformed_model_output"], "escalate_engineering")


if __name__ == "__main__":
    unittest.main()


class PolicyV4AdmissionTests(unittest.TestCase):
    def test_v4_is_admitted_like_v2_and_strict_still_needs_v3(self):
        import inspect
        from scripts import produce_target_language_candidate as producer
        source = inspect.getsource(producer)
        self.assertIn("{policy_tools.POLICY_V2, policy_tools.POLICY_V4}", source)
        self.assertIn("{policy_tools.POLICY_V3} if strict_rubric is not None", source)


class ApiJudgeTests(unittest.TestCase):
    def test_api_judge_refuses_an_authorization_not_bound_to_its_approval(self):
        from scripts import run_machine_qc_clip_test as driver
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bounds = {"globalBounds": {"requests": 10, "wallTimeMs": 1000, "costMicrousd": 1000},
                      "requestLimits": {"schemaVersion": "sermon-openai-chat-request-limits-v1", "maxInputTokens": 1000,
                                        "maxCompletionTokens": 100, "wallTimeMs": 1000, "serviceTier": "default"}}
            (root / "approval.json").write_text(json.dumps({"binding": {"budgetRoot": "elsewhere", **bounds},
                                                            "humanApproval": True, "decision": "approved"}))
            import hashlib
            (root / "auth.json").write_text(json.dumps({
                "schemaVersion": "sermon-machine-qc-api-budget-authorization-v1", "budgetRoot": str(root / "budget"),
                "authority": {"approvalSha256": hashlib.sha256((root / "approval.json").read_bytes()).hexdigest(),
                              "bounds": bounds, "requestLimits": bounds["requestLimits"]},
                "approvalReceipt": "approval.json"}))
            with self.assertRaisesRegex(ValueError, "not bound to its approval"):
                driver.ApiJudge(root / "auth.json")
