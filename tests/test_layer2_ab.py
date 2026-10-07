import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.experiments import layer2_ab as subject
from scripts import target_language_policy as policy_tools
from tests import test_produce_target_language_candidate as fixture_module


class Layer2ABTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.ProduceTargetLanguageCandidateTests(
            methodName="test_compiles_valid_candidate_without_human_approval")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        # This comparison freezes the historical medium-effort arms; the
        # current production policy intentionally uses Sol high/medium.
        policy = copy.deepcopy(self.fixture.policy)
        policy.pop('componentSha256')
        policy['translator'].update(model='gpt-6-astra', reasoningEffort='medium')
        policy['reviewer'].update(model='gpt-6-sol', reasoningEffort='medium')
        self.fixture.policy = policy_tools.freeze_policy(policy)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.out = Path(temporary.name) / "ab"
        self.calls = []

    def fake_call(self, key, payload):
        self.assertEqual(key, "fixture-key")
        self.calls.append(copy.deepcopy(payload))
        data = json.loads(payload["messages"][1]["content"])
        group = next(row for row in self.fixture.evidence["groups"]
                     if row["sourceUnitIds"] == data["sourceUnitIds"])
        reviewed = "draft" in data
        fields = ("translationGroupId", "sourceUnitIds", "targetUtterances", "coverage",
                  "semanticReview") if reviewed else (
                      "translationGroupId", "sourceUnitIds", "targetUtterances", "coverage")
        result = {field: copy.deepcopy(group[field]) for field in fields}
        result["translationGroupId"] = data["translationGroupId"]
        return {"id": f"response-{len(self.calls)}", "model": payload["model"],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20,
                          "total_tokens": 120},
                "choices": [{"finish_reason": "stop",
                             "message": {"content": json.dumps(result)}}]}

    def run_subject(self, caller=None, *, max_api_calls=60, max_groups=10):
        fixture = self.fixture
        return subject.run(fixture.source, fixture.anchor, fixture.policy,
                           self.out, "fixture-key", caller or self.fake_call,
                           plugin_path=fixture.plugin_path,
                           max_api_calls=max_api_calls, max_groups=max_groups,
                           clock=lambda: 10.0)

    def test_pairing_fixes_all_inputs_except_translator_model(self):
        summary = self.run_subject()
        self.assertEqual(summary["status"], "shadow_only")
        self.assertFalse(summary["humanApproval"])
        self.assertFalse(summary["releaseEligible"])
        self.assertEqual(len(self.calls), 12)
        for group_index in range(2):
            calls = [call for call in self.calls if json.loads(
                call["messages"][1]["content"])["sourceUnitIds"]
                == self.fixture.evidence["groups"][group_index]["sourceUnitIds"]]
            drafts = [call for call in calls if "draft" not in json.loads(
                call["messages"][1]["content"])]
            reviews = [call for call in calls if "draft" in json.loads(
                call["messages"][1]["content"])]
            self.assertEqual({call["model"] for call in drafts}, set(subject.MODELS.values()))
            self.assertEqual({call["model"] for call in reviews}, {subject.REVIEWER})
            self.assertEqual(len({call["messages"][0]["content"] for call in drafts}), 1)
            self.assertEqual(len({call["messages"][0]["content"] for call in reviews}), 1)
            self.assertEqual({call["reasoning_effort"] for call in calls}, {"medium"})
            fixed_inputs = [json.loads(call["messages"][1]["content"])
                            for call in drafts]
            self.assertEqual(fixed_inputs, [fixed_inputs[0]] * 3)
        arm_policies = [json.loads((self.out / f"arm-{arm}" /
                                    "experimental-policy.json").read_text())
                        for arm in subject.MODELS]
        self.assertEqual({policy["reviewer"]["model"] for policy in arm_policies},
                         {subject.REVIEWER})
        self.assertEqual(len({policy["translator"]["model"] for policy in arm_policies}), 3)

    def test_frozen_batch_size_does_not_change_group_plan(self):
        from scripts import target_language_policy as policy_tools
        policy = copy.deepcopy(self.fixture.policy)
        policy["batching"]["batchSize"] = 15
        policy["componentSha256"]["batching"] = policy_tools.canonical_sha256(
            policy["batching"])
        summary = subject.run(
            self.fixture.source, self.fixture.anchor, policy, self.out,
            "fixture-key", self.fake_call, plugin_path=self.fixture.plugin_path,
            max_api_calls=60, max_groups=10, clock=lambda: 10.0)
        self.assertEqual(summary["groups"], 2)
        self.assertEqual(len(self.calls), 12)
        for arm in subject.MODELS:
            saved = json.loads((self.out / f"arm-{arm}" /
                                "experimental-policy.json").read_text())
            self.assertEqual(saved["batching"]["batchSize"], 15)

    def test_receipts_cache_and_blinded_materials(self):
        self.run_subject()
        self.assertTrue((self.out / "arm-A/group-0001-translator.raw.json").exists())
        receipt = json.loads((self.out / "arm-A/group-0001-translator.timing.json").read_text())
        self.assertEqual(receipt["responseId"], "response-1")
        self.assertEqual(receipt["usage"]["total_tokens"], 120)
        self.assertEqual(receipt["elapsedSeconds"], 0)
        metrics = json.loads((self.out / "comparison.json").read_text())["arms"]["A"]["metrics"]
        self.assertEqual(metrics["logicalResponses"], 4)
        self.assertEqual(metrics["recordedHttpAttempts"], 4)
        self.assertEqual(metrics["usageObservedResponses"], 4)
        self.assertEqual(metrics["usageTotals"]["total_tokens"], 480)
        self.assertEqual(metrics["apiElapsedSecondsP95"], 0)
        self.assertEqual(json.loads((self.out / "comparison.json").read_text())
                         ["arms"]["A"]["languagePlugin"]["status"], "checked")
        sheet = json.loads((self.out / "blind-review.json").read_text())
        key = json.loads((self.out / "blinding-key.json").read_text())
        self.assertEqual(len(sheet["groups"]), 2)
        self.assertEqual(len(key["codes"]), 6)
        self.assertNotIn("arm", json.dumps(sheet))
        self.calls.clear()
        self.run_subject(lambda *_: self.fail("completed calls must use cache"))
        self.assertEqual(self.calls, [])

    def test_unconfirmed_paid_call_stops_retry(self):
        def interrupted(*_):
            raise TimeoutError("unknown API result")
        with self.assertRaises(TimeoutError):
            self.run_subject(interrupted)
        self.assertTrue((self.out / "arm-A/group-0001-translator.started.json").exists())
        with self.assertRaisesRegex(ValueError, "Uncertain paid translator call"):
            self.run_subject()
        self.assertEqual(self.calls, [])

    def test_invalid_response_raw_is_retained(self):
        def wrong_model(key, payload):
            response = self.fake_call(key, payload)
            response["model"] = "wrong-model"
            return response
        summary = self.run_subject(wrong_model)
        self.assertTrue((self.out / "arm-A/group-0001-translator.raw.json").exists())
        self.assertEqual(summary["arms"]["A"]["failedGroups"], 2)
        self.assertEqual(summary["arms"]["A"]["completedGroups"], 0)
        self.assertEqual(summary["arms"]["A"]["failures"][0]["stage"], "translator")
        self.assertTrue((self.out / "comparison.json").exists())

    def test_invalid_luna_utterance_fails_only_c_and_never_calls_c_reviewer(self):
        def malformed_luna(key, payload):
            response = self.fake_call(key, payload)
            data = json.loads(payload["messages"][1]["content"])
            if payload["model"] == "gpt-6-luna" and "draft" not in data \
                    and data["sourceUnitIds"] == ["block-1-u001"]:
                result = json.loads(response["choices"][0]["message"]["content"])
                result["targetUtterances"] = [{"text": "not a string"}]
                response["choices"][0]["message"]["content"] = json.dumps(result)
            return response
        summary = self.run_subject(malformed_luna)
        self.assertEqual(summary["status"], "shadow_only")
        self.assertEqual(summary["arms"]["A"]["completedGroups"], 2)
        self.assertEqual(summary["arms"]["B"]["completedGroups"], 2)
        self.assertEqual(summary["arms"]["C"]["attemptedGroups"], 2)
        self.assertEqual(summary["arms"]["C"]["completedGroups"], 1)
        self.assertEqual(summary["arms"]["C"]["failedGroups"], 1)
        self.assertEqual(summary["arms"]["C"]["failures"][0]["stage"], "translator")
        self.assertEqual(summary["arms"]["C"]["languagePlugin"]["checkedGroups"], 1)
        self.assertFalse((self.out / "arm-C/group-0001-reviewer.json").exists())
        sheet = json.loads((self.out / "blind-review.json").read_text())
        self.assertEqual(sheet["pairedGroups"], 1)
        self.assertEqual(sheet["excludedGroups"][0]["missingArms"], ["C"])
        self.assertEqual(len(self.calls), 11)
        self.calls.clear()
        self.run_subject(lambda *_: self.fail("must not retry failed response"))
        self.assertEqual(self.calls, [])

    def test_legacy_identity_migration_reuses_cached_invalid_response(self):
        def malformed_luna(key, payload):
            response = self.fake_call(key, payload)
            data = json.loads(payload["messages"][1]["content"])
            if payload["model"] == "gpt-6-luna" and "draft" not in data:
                result = json.loads(response["choices"][0]["message"]["content"])
                result["targetUtterances"] = [{"text": "not a string"}]
                response["choices"][0]["message"]["content"] = json.dumps(result)
            return response
        self.run_subject(malformed_luna, max_groups=1)
        (self.out / "arm-C/group-0001-failure.json").unlink()
        identity_path = self.out / "run-identity.json"
        identity = json.loads(identity_path.read_text())
        identity["schemaVersion"] = "layer2-ab-run-v1"
        identity["harnessSha256"] = subject.LEGACY_HARNESS_SHA256
        identity_path.write_text(json.dumps(identity))
        self.calls.clear()
        summary = self.run_subject(
            lambda *_: self.fail("cached response must not be recalled"),
            max_api_calls=0, max_groups=1)
        self.assertEqual(summary["status"], "incomplete")
        self.assertEqual(summary["arms"]["C"]["failedGroups"], 1)
        self.assertEqual(summary["arms"]["A"]["completedGroups"], 1)
        self.assertEqual(summary["arms"]["B"]["completedGroups"], 1)
        self.assertEqual(summary["lastInvocation"]["httpAttempts"], 0)
        migration = json.loads((self.out / "run-identity-migration.json").read_text())
        self.assertEqual(migration["fromHarnessSha256"], subject.LEGACY_HARNESS_SHA256)
        self.assertTrue((self.out / "run-identity-v2.json").exists())
        self.assertEqual(self.calls, [])

    def test_review_flag_is_measured_but_never_admitted(self):
        def review_flags(key, payload):
            response = self.fake_call(key, payload)
            data = json.loads(payload["messages"][1]["content"])
            if "draft" in data:
                result = json.loads(response["choices"][0]["message"]["content"])
                result["semanticReview"]["status"] = "fail"
                result["semanticReview"]["issues"] = ["Needs human inspection"]
                response["choices"][0]["message"]["content"] = json.dumps(result)
            return response
        summary = self.run_subject(review_flags)
        self.assertEqual(len(self.calls), 12)
        self.assertEqual({row["semanticReviewPassGroups"] for row in
                          summary["arms"].values()}, {0})
        self.assertFalse(any((self.out / f"arm-{arm}/evidence.json").exists()
                             for arm in subject.MODELS))

    def test_budget_pause_resumes_without_repeating_paid_calls(self):
        statuses = []
        for _ in range(6):
            result = self.run_subject(max_api_calls=2, max_groups=1)
            statuses.append(result["status"])
            self.assertLessEqual(result.get("httpAttemptsThisInvocation", 2), 2)
        self.assertEqual(statuses, ["incomplete"] * 5 + ["shadow_only"])
        self.assertEqual(len(self.calls), 12)
        self.assertEqual(len({json.loads((self.out / f"arm-{arm}" /
                                         f"group-{index:04d}-{role}.json").read_text())
                              ["requestId"]
                              for arm in subject.MODELS for index in (1, 2)
                              for role in ("translator", "reviewer")}), 12)
        summary = json.loads((self.out / "comparison.json").read_text())
        self.assertEqual(summary["lastInvocation"]["httpAttempts"], 2)
        self.assertGreater(summary["lastInvocation"]["cacheHits"], 0)
        self.assertEqual(summary["arms"]["A"]["metrics"]["recordedHttpAttempts"], 4)
        self.assertGreaterEqual(summary["localeActiveWallSeconds"], 0)
        self.assertGreaterEqual(summary["localeCalendarWallSeconds"], 0)

    def test_group_cap_and_unknown_usage_are_reported_separately(self):
        def without_usage(key, payload):
            response = self.fake_call(key, payload)
            response.pop("usage")
            return response
        first = self.run_subject(without_usage, max_groups=1)
        self.assertEqual(first["pauseReason"], "max_groups")
        self.assertEqual(first["lastInvocation"]["httpAttempts"], 6)
        self.assertEqual(len(self.calls), 6)
        final = self.run_subject(without_usage, max_groups=1)
        self.assertEqual(final["status"], "shadow_only")
        self.assertEqual(len(self.calls), 12)
        metrics = final["arms"]["A"]["metrics"]
        self.assertEqual(metrics["logicalResponses"], 4)
        self.assertEqual(metrics["usageObservedResponses"], 0)
        self.assertIsNone(metrics["usageTotals"])
        self.assertFalse(metrics["usageComplete"])

    def test_frozen_language_plugin_failure_is_separate_from_semantic_review(self):
        def plugin_failure(key, payload):
            response = self.fake_call(key, payload)
            data = json.loads(payload["messages"][1]["content"])
            if "draft" in data and data["sourceUnitIds"] == ["block-1-u001"]:
                result = json.loads(response["choices"][0]["message"]["content"])
                result["targetUtterances"] = ["禁"]
                result["coverage"] = [{"sourceUnitId": "block-1-u001", "targetText": "禁"}]
                response["choices"][0]["message"]["content"] = json.dumps(result)
            return response
        summary = self.run_subject(plugin_failure)
        for arm in subject.MODELS:
            self.assertEqual(summary["arms"][arm]["semanticReviewPassGroups"], 2)
            self.assertEqual(summary["arms"][arm]["languagePlugin"]["passGroups"], 1)
            self.assertEqual(summary["arms"][arm]["combinedMachinePassGroups"], 1)
            self.assertTrue((self.out / f"arm-{arm}/language-plugin.json").exists())

    def test_source_gate_blocks_all_calls(self):
        source = copy.deepcopy(self.fixture.source)
        source["translationEligible"] = False
        with self.assertRaisesRegex(ValueError, "Approved English Source Package"):
            subject.run(source, self.fixture.anchor, self.fixture.policy, self.out,
                        "fixture-key", self.fake_call,
                        max_api_calls=60, max_groups=10)
        self.assertEqual(self.calls, [])
        self.assertFalse(self.out.exists())

    def test_same_directory_rejects_changed_policy(self):
        self.run_subject()
        changed = copy.deepcopy(self.fixture.policy)
        changed["translator"]["reasoningEffort"] = "high"
        changed["reviewer"]["reasoningEffort"] = "high"
        from scripts import target_language_policy as policy_tools
        for role in ("translator", "reviewer"):
            changed["componentSha256"][role] = policy_tools.canonical_sha256(changed[role])
        with self.assertRaisesRegex(ValueError, "Run identity changed"):
            subject.run(self.fixture.source, self.fixture.anchor, changed,
                        self.out, "fixture-key", self.fake_call,
                        max_api_calls=60, max_groups=10)


if __name__ == "__main__":
    unittest.main()
