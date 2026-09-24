import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts import run_target_language_models as subject
from scripts import produce_target_language_candidate as producer
from scripts import target_language_policy as policy_tools
from tests import test_produce_target_language_candidate as fixture_module


class RunTargetLanguageModelsTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.ProduceTargetLanguageCandidateTests(
            methodName="test_compiles_valid_candidate_without_human_approval")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.out = Path(temp.name) / "run"
        self.calls = []

    def fake_call(self, api_key, payload):
        self.assertEqual(api_key, "fixture-key")
        self.calls.append(payload)
        index = (len(self.calls) + 1) // 2
        group = self.fixture.evidence["groups"][index - 1]
        input_group = json.loads(payload["messages"][1]["content"])
        if payload["model"] == "gpt-6-astra":
            result = {key: copy.deepcopy(group[key]) for key in
                      ("translationGroupId", "sourceUnitIds", "targetUtterances", "coverage")}
        else:
            result = {key: copy.deepcopy(group[key]) for key in
                      ("translationGroupId", "sourceUnitIds", "targetUtterances", "coverage",
                       "semanticReview")}
        result["translationGroupId"] = input_group["translationGroupId"]
        return {"id": f"response-{len(self.calls)}", "model": payload["model"],
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}]}

    def test_astra_then_sol_each_group_and_admit_human_pending(self):
        f = self.fixture
        evidence = subject.run(f.source, f.anchor, f.policy, self.out,
                               "fixture-key", self.fake_call)
        self.assertEqual([call["model"] for call in self.calls],
                         ["gpt-6-astra", "gpt-6-sol"] * 2)
        self.assertEqual([call["reasoning_effort"] for call in self.calls],
                         ["medium"] * 4)
        self.assertEqual(evidence["generation"]["translator"]["requestIds"],
                         ["response-1", "response-3"])
        self.assertEqual(evidence["generation"]["reviewer"]["requestIds"],
                         ["response-2", "response-4"])
        receipt = producer.run_language_plugin(f.source, f.anchor, f.policy,
                                               f.request, evidence, f.plugin_path, f.plugin_sha)
        candidate = producer.admit_evidence(f.source, f.anchor, f.policy,
                                            f.request, evidence, receipt,
                                            f.plugin_path, f.plugin_sha)
        self.assertEqual(candidate["status"], "machine_review_pass_human_review_pending")
        self.assertFalse(candidate["releaseEligible"])
        self.assertEqual(candidate["humanReview"]["translation"], "pending")
        self.calls.clear()
        self.assertEqual(subject.run(f.source, f.anchor, f.policy, self.out,
                                     "fixture-key", self.fake_call), evidence)
        self.assertEqual(self.calls, [])

    def test_wrong_role_model_or_coverage_blocks_before_paid_call(self):
        f = self.fixture
        wrong = copy.deepcopy(f.policy)
        wrong["reviewer"]["model"] = "gpt-6-astra"
        wrong["componentSha256"]["reviewer"] = policy_tools.canonical_sha256(wrong["reviewer"])
        with self.assertRaisesRegex(ValueError, "Production reviewer model"):
            subject.run(f.source, f.anchor, wrong, self.out, "fixture-key", self.fake_call)
        wrong_batch = copy.deepcopy(f.policy)
        wrong_batch["batching"]["batchSize"] = 15
        wrong_batch["componentSha256"]["batching"] = policy_tools.canonical_sha256(
            wrong_batch["batching"])
        with self.assertRaisesRegex(ValueError, "batchSize=1"):
            subject.run(f.source, f.anchor, wrong_batch, self.out,
                        "fixture-key", self.fake_call)
        with self.assertRaisesRegex(ValueError, "cover source units"):
            subject.run(f.source, f.anchor, f.policy, self.out, "fixture-key", self.fake_call,
                        [{"translationGroupId": "partial", "sourceUnitIds": ["block-1-u001"]}])
        self.assertFalse(self.calls)

    def test_sol_failure_keeps_group_evidence_and_blocks_candidate(self):
        f = self.fixture
        def failing(api_key, payload):
            response = self.fake_call(api_key, payload)
            if payload["model"] == "gpt-6-sol":
                import json
                result = json.loads(response["choices"][0]["message"]["content"])
                result["semanticReview"]["status"] = "fail"
                result["semanticReview"]["issues"] = ["Unresolved omission"]
                response["choices"][0]["message"]["content"] = json.dumps(result)
            return response
        with self.assertRaisesRegex(ValueError, "Sol flagged group"):
            subject.run(f.source, f.anchor, f.policy, self.out, "fixture-key", failing)
        self.assertTrue((self.out / "group-0001-sol.json").exists())
        self.assertFalse((self.out / "evidence.json").exists())
        self.assertEqual(len(self.calls), 2)

    def test_sol_boolean_checks_are_normalized_without_rewriting_raw_response(self):
        f = self.fixture
        def boolean_checks(api_key, payload):
            response = self.fake_call(api_key, payload)
            if payload["model"] == "gpt-6-sol":
                result = json.loads(response["choices"][0]["message"]["content"])
                semantic = result["semanticReview"]
                semantic["checks"] = {key: True for key in semantic["checks"]}
                semantic["uncertainty"] = False
                response["choices"][0]["message"]["content"] = json.dumps(result)
            return response
        evidence = subject.run(f.source, f.anchor, f.policy, self.out,
                               "fixture-key", boolean_checks)
        self.assertEqual(set(evidence["groups"][0]["semanticReview"]["checks"].values()),
                         {"pass"})
        self.assertEqual(evidence["groups"][0]["semanticReview"]["uncertainty"], [])
        raw = json.loads((self.out / "group-0001-sol.json").read_text())["result"]
        self.assertTrue(raw["semanticReview"]["checks"]["completeMeaning"])

    def test_sol_boolean_uncertainty_still_blocks(self):
        f = self.fixture
        def uncertain(api_key, payload):
            response = self.fake_call(api_key, payload)
            if payload["model"] == "gpt-6-sol":
                result = json.loads(response["choices"][0]["message"]["content"])
                result["semanticReview"]["uncertainty"] = True
                response["choices"][0]["message"]["content"] = json.dumps(result)
            return response
        with self.assertRaisesRegex(ValueError, "Sol flagged group"):
            subject.run(f.source, f.anchor, f.policy, self.out,
                        "fixture-key", uncertain)

    def test_sol_null_empty_fields_normalize_to_empty_lists(self):
        self.assertEqual(subject.normalize_semantic_review({"uncertainty": None,
                                                            "issues": None}),
                         {"uncertainty": [], "issues": []})

    def test_unconfirmed_request_blocks_automatic_paid_retry(self):
        f = self.fixture
        def interrupted(api_key, payload):
            raise TimeoutError("Response status unknown")
        with self.assertRaises(TimeoutError):
            subject.run(f.source, f.anchor, f.policy, self.out, "fixture-key", interrupted)
        self.assertTrue((self.out / "group-0001-astra.started.json").exists())
        with self.assertRaisesRegex(ValueError, "Uncertain paid translator call"):
            subject.run(f.source, f.anchor, f.policy, self.out,
                        "fixture-key", self.fake_call)
        self.assertFalse(self.calls)

    def test_invalid_completed_response_is_saved_before_validation(self):
        f = self.fixture
        def malformed(api_key, payload):
            response = self.fake_call(api_key, payload)
            response["model"] = "unexpected-model"
            return response
        with self.assertRaisesRegex(ValueError, "exact model"):
            subject.run(f.source, f.anchor, f.policy, self.out,
                        "fixture-key", malformed)
        raw_path = self.out / "group-0001-astra.raw.json"
        self.assertTrue(raw_path.exists())
        self.assertEqual(json.loads(raw_path.read_text())["response"]["id"], "response-1")
        self.calls.clear()
        with self.assertRaisesRegex(ValueError, "exact model"):
            subject.run(f.source, f.anchor, f.policy, self.out,
                        "fixture-key", self.fake_call)
        self.assertFalse(self.calls)

    def test_saved_raw_response_can_rebuild_validated_cache_without_api(self):
        f = self.fixture
        subject.run(f.source, f.anchor, f.policy, self.out, "fixture-key", self.fake_call)
        (self.out / "group-0001-astra.json").unlink()
        self.calls.clear()
        subject.run(f.source, f.anchor, f.policy, self.out, "fixture-key", self.fake_call)
        self.assertFalse(self.calls)
        self.assertTrue((self.out / "group-0001-astra.json").exists())

    def test_stale_group_cache_and_source_change_fail_closed(self):
        f = self.fixture
        subject.run(f.source, f.anchor, f.policy, self.out, "fixture-key", self.fake_call)
        changed = copy.deepcopy(f.anchor)
        changed["sourceUnits"][0]["english"] = "Different source."
        with self.assertRaises(ValueError):
            subject.run(f.source, changed, f.policy, self.out,
                        "fixture-key", self.fake_call)
        cache = self.out / "group-0001-astra.json"
        saved = json.loads(cache.read_text())
        saved["model"] = "gpt-6-sol"
        cache.write_text(json.dumps(saved))
        self.calls.clear()
        with self.assertRaisesRegex(ValueError, "Cached translator response"):
            subject.run(f.source, f.anchor, f.policy, self.out,
                        "fixture-key", self.fake_call)
        self.assertFalse(self.calls)

    def test_group_revision_reuses_unchanged_calls_and_invalidates_changed_payloads(self):
        f = self.fixture
        previous = self.out.parent / "previous"
        old = subject.run(f.source, f.anchor, f.policy, previous,
                          "fixture-key", self.fake_call)
        self.calls.clear()
        changed = old["groups"][1]
        prior_text = "".join(changed["targetUtterances"])
        brief = {
            "schemaVersion": subject.REVISION_BRIEF_SCHEMA,
            "targetLocale": f.request["targetLocale"],
            "englishSourcePackageJsonSha256": f.request["englishSourcePackageJsonSha256"],
            "anchorManifestSha256": f.request["anchorManifestSha256"],
            "translationPolicySha256": f.request["translationPolicySha256"],
            "groups": [{
                "translationGroupId": changed["translationGroupId"],
                "sourceUnitIds": changed["sourceUnitIds"],
                "priorTargetTextSha256": hashlib.sha256(prior_text.encode()).hexdigest(),
                "proposedTargetText": "A shorter, still complete translation.",
            }],
        }

        def revised_call(api_key, payload):
            self.assertEqual(api_key, "fixture-key")
            self.calls.append(payload)
            model_input = json.loads(payload["messages"][1]["content"])
            self.assertEqual(model_input["translationGroupId"], changed["translationGroupId"])
            self.assertEqual(model_input["revisionBrief"]["proposedTargetText"],
                             "A shorter, still complete translation.")
            if payload["model"] == "gpt-6-astra":
                fields = ("translationGroupId", "sourceUnitIds", "targetUtterances", "coverage")
            else:
                fields = ("translationGroupId", "sourceUnitIds", "targetUtterances", "coverage",
                          "semanticReview")
            result = {key: copy.deepcopy(changed[key]) for key in fields}
            return {"id": f"new-response-{len(self.calls)}", "model": payload["model"],
                    "choices": [{"finish_reason": "stop",
                                 "message": {"content": json.dumps(result)}}]}

        updated = subject.run(f.source, f.anchor, f.policy, self.out,
                              "fixture-key", revised_call,
                              revision_brief=brief, reuse_from=previous)
        self.assertEqual([call["model"] for call in self.calls],
                         ["gpt-6-astra", "gpt-6-sol"])
        self.assertEqual(updated["groups"][0], old["groups"][0])
        for role in ("astra", "sol"):
            self.assertEqual((self.out / f"group-0001-{role}.json").read_bytes(),
                             (previous / f"group-0001-{role}.json").read_bytes())
            self.assertNotEqual(
                json.loads((self.out / f"group-0002-{role}.json").read_text())["payloadSha256"],
                json.loads((previous / f"group-0002-{role}.json").read_text())["payloadSha256"])

    def test_group_revision_rejects_changed_source_group_and_prior_text_before_calls(self):
        f = self.fixture
        previous = self.out.parent / "previous"
        old = subject.run(f.source, f.anchor, f.policy, previous,
                          "fixture-key", self.fake_call)
        self.calls.clear()
        changed = old["groups"][1]
        brief = {
            "schemaVersion": subject.REVISION_BRIEF_SCHEMA,
            "targetLocale": f.request["targetLocale"],
            "englishSourcePackageJsonSha256": f.request["englishSourcePackageJsonSha256"],
            "anchorManifestSha256": f.request["anchorManifestSha256"],
            "translationPolicySha256": f.request["translationPolicySha256"],
            "groups": [{"translationGroupId": changed["translationGroupId"],
                        "sourceUnitIds": changed["sourceUnitIds"],
                        "priorTargetTextSha256": "0" * 64,
                        "proposedTargetText": "A shorter translation."}],
        }
        with self.assertRaisesRegex(ValueError, "prior target text"):
            subject.run(f.source, f.anchor, f.policy, self.out,
                        "fixture-key", self.fake_call,
                        revision_brief=brief, reuse_from=previous)
        brief["groups"][0]["priorTargetTextSha256"] = hashlib.sha256(
            "".join(changed["targetUtterances"]).encode()).hexdigest()
        brief["groups"][0]["sourceUnitIds"] = ["wrong-unit"]
        with self.assertRaisesRegex(ValueError, "revision group"):
            subject.run(f.source, f.anchor, f.policy, self.out,
                        "fixture-key", self.fake_call,
                        revision_brief=brief, reuse_from=previous)
        brief["groups"][0]["sourceUnitIds"] = changed["sourceUnitIds"]
        brief["englishSourcePackageJsonSha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "source or policy changed"):
            subject.run(f.source, f.anchor, f.policy, self.out,
                        "fixture-key", self.fake_call,
                        revision_brief=brief, reuse_from=previous)
        self.assertFalse(self.calls)
        self.assertFalse(self.out.exists())

    def test_coverage_tolerates_only_whitespace_at_utterance_boundary(self):
        self.assertTrue(subject._coverage_substring(
            "다시 데웁니다. 차가운 것이", "다시 데웁니다.차가운 것이"))
        self.assertFalse(subject._coverage_substring(
            "다시 데웁니다. 뜨거운 것이", "다시 데웁니다.차가운 것이"))


if __name__ == "__main__":
    unittest.main()
