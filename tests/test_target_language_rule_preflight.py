import copy
import json
import unittest
from unittest.mock import patch

from scripts import produce_target_language_candidate as producer
from scripts import run_target_language_models as runner
from scripts import target_language_policy as policy_tools
from scripts import target_language_rule_preflight as subject
from tests import test_run_target_language_models as fixture_module


class TargetLanguageRulePreflightTests(unittest.TestCase):
    def setUp(self):
        self.worker = fixture_module.RunTargetLanguageModelsTests(methodName="test_astra_then_sol_each_group_and_admit_human_pending")
        self.worker.setUp()
        self.addCleanup(self.worker.doCleanups)
        self.fixture = self.worker.fixture
        self.policy = copy.deepcopy(self.fixture.policy)
        self.request = copy.deepcopy(self.fixture.request)
        self.plugin = self.fixture.plugin_path
        self.plan = runner.group_plan(self.request, self.fixture.anchor)

    def repin(self):
        self.policy["languageReview"]["pluginImplementationSha256"] = producer.plugin_implementation_sha256(self.plugin)
        self.policy["componentSha256"]["languageReview"] = policy_tools.canonical_sha256(self.policy["languageReview"])
        self.request["translationPolicySha256"] = policy_tools.canonical_sha256(self.policy)

    def receipt(self):
        return subject.preflight(self.request, self.policy, self.plugin, self.plan)

    def test_real_runner_both_prompts_and_candidate_consume_matching_frozen_inputs(self):
        f = self.fixture
        evidence = runner.run(f.source, f.anchor, f.policy, self.worker.out,
                              "fixture-key", self.worker.fake_call, plugin_path=self.plugin)
        receipt = json.loads((self.worker.out / "rule-preflight.json").read_text())
        self.assertEqual("inputs_frozen_not_execution_evidence", receipt["status"])
        self.assertFalse(receipt["humanApproval"])
        self.assertEqual(4, len(self.worker.calls))
        for call in self.worker.calls:
            common = json.loads(call["messages"][1]["content"])
            self.assertEqual(receipt["ruleBundleSha256"], common["modelRules"]["ruleBundleSha256"])
            self.assertIn("Do not add editorial", call["messages"][0]["content"])
            self.assertIn("Preserve numbers in their spoken context", call["messages"][0]["content"])
        language = producer.run_language_plugin(f.source, f.anchor, f.policy, f.request,
                                               evidence, self.plugin, f.plugin_sha,
                                               rule_preflight_receipt=receipt)
        candidate = producer.admit_evidence(f.source, f.anchor, f.policy, f.request,
                                           evidence, language, self.plugin, f.plugin_sha,
                                           rule_preflight_receipt=receipt)
        self.assertEqual("machine_review_pass_human_review_pending", candidate["status"])
        self.worker.calls.clear()
        runner.run(f.source, f.anchor, f.policy, self.worker.out,
                   "fixture-key", self.worker.fake_call, plugin_path=self.plugin)
        self.assertEqual([], self.worker.calls)

    def assert_blocked_without_dispatch(self, message):
        with self.assertRaisesRegex(ValueError, message):
            runner.run(self.fixture.source, self.fixture.anchor, self.policy,
                       self.worker.out, "fixture-key", self.worker.fake_call, plugin_path=self.plugin)
        self.assertEqual([], self.worker.calls)
        self.assertFalse(any(self.worker.out.glob("*.started.json")))

    def test_matching_implementation_hash_does_not_hide_wrong_plugin_id(self):
        self.plugin.write_text(self.plugin.read_text().replace('"zh-Hans-sermon-v1"', '"other-plugin-v1"'))
        self.repin()
        self.assert_blocked_without_dispatch("plugin ID or version differs")

    def test_matching_hash_does_not_hide_required_check_mismatch(self):
        with self.plugin.open("a") as stream:
            stream.write('\nREQUIRED = ["only_one_check"]\n')
        self.repin()
        self.assert_blocked_without_dispatch("required checks differ")

    def test_consumer_binding_mismatch_is_rejected(self):
        receipt = self.receipt()
        bindings = copy.deepcopy(receipt["consumerBindings"])
        bindings["reviewer"]["terminologySha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "rule bindings differ"):
            subject.preflight(self.request, self.policy, self.plugin, self.plan, consumer_bindings=bindings)

    def test_stale_terminology_table_and_rehashed_component_are_rejected(self):
        self.policy["terminology"]["seriesTableSha256"] = "f" * 64
        self.policy["componentSha256"]["terminology"] = policy_tools.canonical_sha256(self.policy["terminology"])
        self.request["translationPolicySha256"] = policy_tools.canonical_sha256(self.policy)
        with self.assertRaisesRegex(ValueError, "terminology table changed"):
            self.receipt()

    def test_exact_quote_source_text_and_complete_group_checked_before_calls(self):
        unit = self.request["sourceUnits"][0]
        with self.plugin.open("a") as stream:
            stream.write("\nSOURCE_SHA256 = " + repr(self.request["englishSourcePackageJsonSha256"]) + "\n")
            stream.write("QUOTED_UNITS = " + repr({unit["sourceUnitId"]: (unit["english"], "完整引文。")}) + "\n")
        self.repin()
        good = self.receipt()
        self.assertEqual("完整引文。", good["modelRules"]["exactQuotes"][0]["targetText"])
        self.plan = [{"translationGroupId": "merged", "sourceUnitIds": [row["sourceUnitId"] for row in self.request["sourceUnits"]]}]
        with self.assertRaisesRegex(ValueError, "exact quote must occupy"):
            self.receipt()
        self.plan = runner.group_plan(self.request, self.fixture.anchor)
        self.request["sourceUnits"][0]["english"] += " Added text."
        with self.assertRaisesRegex(ValueError, "English quote unit changed"):
            self.receipt()

    def test_plugin_source_mismatch_is_detected_before_first_call(self):
        with self.plugin.open("a") as stream:
            stream.write('\nSOURCE_SHA256 = "' + "f" * 64 + '"\n')
        self.repin()
        self.assert_blocked_without_dispatch("plugin source differs")

    def test_quote_hash_mismatch_is_rejected(self):
        unit = self.request["sourceUnits"][0]
        with self.plugin.open("a") as stream:
            stream.write("\nQUOTED_UNITS = " + repr({unit["sourceUnitId"]: (unit["english"], "完整引文。")}) + "\n")
            stream.write("APPROVED_EXCERPTS = " + repr({"REV 1:1": ("完整引文。", "f" * 64)}) + "\n")
        self.repin()
        with self.assertRaisesRegex(ValueError, "excerpt hash changed"):
            self.receipt()

    def test_actual_prompt_tampering_blocks_before_started_marker(self):
        receipt = self.receipt()
        ids = self.plan[0]["sourceUnitIds"]
        prompt = {"instruction": subject.INSTRUCTION, "input": {
            "sourceUnitIds": ids, "modelRules": subject.group_rules(receipt, ids),
            **{key: copy.deepcopy(self.policy[key]) for key in ("terminology", "scripture", "formatting")}}}
        prompt["input"]["scripture"]["editionId"] = "unreviewed"
        path = self.worker.out / "tampered-astra.json"
        with self.assertRaisesRegex(ValueError, "actual model input differs: scripture"):
            runner._model_call("translator", prompt, self.policy, path, "fixture-key",
                               self.worker.fake_call, rule_receipt=receipt)
        self.assertFalse(path.with_suffix(".started.json").exists())
        self.assertFalse(path.with_suffix(".policy-preview.json").exists())
        self.assertEqual([], self.worker.calls)

    def test_plugin_only_change_plans_revalidation_without_retranslation(self):
        before = self.receipt()
        with self.plugin.open("a") as stream:
            stream.write("\n# A deterministic implementation repair, no model rule change.\n")
        self.repin()
        after = self.receipt()
        result = subject.change_plan(before, after)
        self.assertEqual("plugin_only_revalidate", result["classification"])
        self.assertFalse(result["requiresModelRecompute"])
        self.assertFalse(result["automaticReuseAuthorized"])
        self.assertEqual([], self.worker.calls)

    def test_changed_translator_configuration_is_not_plugin_only(self):
        before = self.receipt()
        self.policy["translator"]["reasoningEffort"] = (
            "medium" if self.policy["translator"]["reasoningEffort"] == "high" else "high")
        self.policy["componentSha256"]["translator"] = policy_tools.canonical_sha256(self.policy["translator"])
        self.request["translationPolicySha256"] = policy_tools.canonical_sha256(self.policy)
        self.assertTrue(subject.change_plan(before, self.receipt())["requiresModelRecompute"])

    def test_candidate_rejects_tampered_preflight_before_plugin_execution(self):
        receipt = self.receipt()
        receipt["modelRules"]["citationRule"] = "add_unspoken_references"
        f = self.fixture
        with patch.object(producer.runpy, "run_path", side_effect=AssertionError("must not execute plugin")):
            with self.assertRaisesRegex(ValueError, "inputs differ from frozen preflight"):
                producer.admit_evidence(f.source, f.anchor, f.policy, f.request, f.evidence,
                                        {}, self.plugin, f.plugin_sha, rule_preflight_receipt=receipt)

    def test_new_frozen_reference_instruction_does_not_invent_unspoken_citations(self):
        policy = {"scripture": {"quoteCheckPolicy": "references_only"}}
        instruction = runner.scripture_prompt_instruction(policy, frozen_rules=True)
        self.assertIn("actually spoken", instruction)
        self.assertNotIn("when known", instruction)
        self.assertIn("Do not present the text as an exact quotation", instruction)

    def test_static_inspection_does_not_execute_plugin(self):
        with self.plugin.open("a") as stream:
            stream.write('\nraise RuntimeError("plugin module must not execute during preflight")\n')
        self.repin()
        self.assertEqual("inputs_frozen_not_execution_evidence", self.receipt()["status"])

    def test_unproven_historical_carry_forward_requires_migration_without_new_calls(self):
        f = self.fixture
        legacy = self.worker.out.parent / "legacy"
        runner.run(f.source, f.anchor, f.policy, legacy, "fixture-key", self.worker.fake_call)
        self.worker.calls.clear()
        with self.assertRaisesRegex(ValueError, "prior cache lacks matching frozen rule receipt"):
            runner.run(f.source, f.anchor, f.policy, self.worker.out, "fixture-key", self.worker.fake_call,
                       plugin_path=self.plugin, reuse_from=legacy)
        self.assertEqual([], self.worker.calls)
        self.assertFalse(self.worker.out.exists())
        # Copying a new receipt alone still does not prove the old prompt consumed it.
        (legacy / "rule-preflight.json").write_text(json.dumps(self.receipt()))
        with self.assertRaisesRegex(ValueError, "actual model rule input differs"):
            runner.run(f.source, f.anchor, f.policy, self.worker.out, "fixture-key", self.worker.fake_call,
                       plugin_path=self.plugin, reuse_from=legacy, partial_repair_brief={})
        self.assertEqual([], self.worker.calls)

    def test_proven_frozen_rules_carry_forward_without_model_dispatch(self):
        f = self.fixture
        original = self.worker.out.parent / "prior"
        runner.run(f.source, f.anchor, f.policy, original, "fixture-key", self.worker.fake_call,
                   plugin_path=self.plugin)
        self.worker.calls.clear()
        runner.run(f.source, f.anchor, f.policy, self.worker.out, "fixture-key", self.worker.fake_call,
                   plugin_path=self.plugin, reuse_from=original)
        self.assertEqual([], self.worker.calls)
        for prior in original.glob("group-*.policy-preview.json"):
            self.assertEqual(prior.read_bytes(), (self.worker.out / prior.name).read_bytes())

    def test_missing_historical_model_payload_blocks_before_new_attempt(self):
        f = self.fixture
        original = self.worker.out.parent / "prior"
        runner.run(f.source, f.anchor, f.policy, original, "fixture-key", self.worker.fake_call,
                   plugin_path=self.plugin)
        (original / "group-0001-astra.policy-preview.json").unlink()
        self.worker.calls.clear()
        with self.assertRaisesRegex(ValueError, "prior cache lacks frozen model payload"):
            runner.run(f.source, f.anchor, f.policy, self.worker.out, "fixture-key", self.worker.fake_call,
                       plugin_path=self.plugin, reuse_from=original)
        self.assertEqual([], self.worker.calls)
        self.assertFalse(self.worker.out.exists())

    def test_plugin_number_tuple_forms_survive_durable_readback(self):
        with self.plugin.open("a") as stream:
            stream.write("\nNUMBERS = {'44': ('四十四', '44')}\n")
        self.repin()
        receipt = self.receipt()
        self.assertEqual(receipt, json.loads(json.dumps(receipt)))

    def test_source_bound_cuv_complete_quote_cannot_be_truncated(self):
        from scripts.cuv_scripture import CuvLibrary
        library = CuvLibrary.from_path()
        verse = library.lookup("REV 2:4")
        unit = self.request["sourceUnits"][0]
        part = {"sourceUnitId": unit["sourceUnitId"], "englishStartOffset": 0,
                "englishEndOffset": len(unit["english"]), "englishExcerptSha256": subject._sha_text(unit["english"]),
                "reference": "REV 2:4", "cuvExcerpt": verse["text"], "cuvExcerptSha256": verse["textSha256"]}
        approval = {"humanApproval": True, "decision": "approved",
                    "englishSourcePackageJsonSha256": self.request["englishSourcePackageJsonSha256"],
                    "anchorManifestJsonSha256": self.request["anchorManifestSha256"],
                    "decisions": [{"candidateId": "fixture-quote", "classification": "direct_quote",
                                   "parts": [part], "paraphraseUnitIds": []}]}
        additions = {"CUV_EDITION_ID": "cmn-cu89s",
                     "CANDIDATE_VERSES": {"fixture-quote": {"REV 2:4"}},
                     "CANDIDATE_QUOTE_UNITS": {"fixture-quote": {unit["sourceUnitId"]}},
                     "APPROVED_BOUNDARY_REVIEW": approval}
        base = self.plugin.read_text()
        def write():
            self.plugin.write_text(base + "\n" + "\n".join(key + " = " + repr(value) for key, value in additions.items()))
            self.repin()
        self.policy["scripture"]["editionId"] = "cmn-cu89s"
        self.policy["componentSha256"]["scripture"] = policy_tools.canonical_sha256(self.policy["scripture"])
        write()
        self.assertEqual(verse["text"], self.receipt()["modelRules"]["exactQuotes"][0]["targetText"])
        # This is still a valid exact substring, but not the complete direct verse.
        part["cuvExcerpt"] = verse["text"][:-1]
        part["cuvExcerptSha256"] = subject._sha_text(part["cuvExcerpt"])
        write()
        with self.assertRaisesRegex(ValueError, "complete direct quote was split or shortened"):
            self.receipt()

    def test_complete_quote_spans_one_group_and_a_split_plan_sends_nothing(self):
        from scripts.cuv_scripture import CuvLibrary
        library = CuvLibrary.from_path()
        verse = library.lookup("REV 2:4")
        units = self.request["sourceUnits"]
        self.assertGreaterEqual(len(units), 2)
        cut = verse["text"].index("，") + 1
        excerpts = (verse["text"][:cut], verse["text"][cut:])
        self.assertTrue(all(verse["text"].count(excerpt) == 1 and excerpt for excerpt in excerpts))
        parts = []
        for unit, excerpt in zip(units[:2], excerpts):
            selected = library.lookup("REV 2:4", excerpt=excerpt)
            parts.append({"sourceUnitId": unit["sourceUnitId"], "englishStartOffset": 0,
                "englishEndOffset": len(unit["english"]),
                "englishExcerptSha256": subject._sha_text(unit["english"]),
                "reference": "REV 2:4", "cuvExcerpt": excerpt,
                "cuvExcerptSha256": selected["textSha256"]})
        approval = {"humanApproval": True, "decision": "approved",
                    "englishSourcePackageJsonSha256": self.request["englishSourcePackageJsonSha256"],
                    "anchorManifestJsonSha256": self.request["anchorManifestSha256"],
                    "decisions": [{"candidateId": "fixture-quote", "classification": "direct_quote",
                                   "parts": parts, "paraphraseUnitIds": []}]}
        additions = {"CUV_EDITION_ID": "cmn-cu89s",
                     "CANDIDATE_VERSES": {"fixture-quote": {"REV 2:4"}},
                     "CANDIDATE_QUOTE_UNITS": {"fixture-quote": {part["sourceUnitId"] for part in parts}},
                     "APPROVED_BOUNDARY_REVIEW": approval}
        self.plugin.write_text(self.plugin.read_text() + "\n" + "\n".join(
            key + " = " + repr(value) for key, value in additions.items()))
        self.policy["scripture"]["editionId"] = "cmn-cu89s"
        self.policy["scripture"]["quoteCheckPolicy"] = "source_bound_exact_quote"
        self.policy["componentSha256"]["scripture"] = policy_tools.canonical_sha256(self.policy["scripture"])
        self.repin()
        joined = [{"translationGroupId": "quote-group",
                   "sourceUnitIds": [part["sourceUnitId"] for part in parts]}]
        receipt = subject.preflight(self.request, self.policy, self.plugin, joined)
        self.assertEqual([part["cuvExcerpt"] for part in parts],
                         [quote["targetText"] for quote in receipt["modelRules"]["exactQuotes"]])
        self.assertEqual(0, receipt["modelCalls"])
        split = [{"translationGroupId": "group-" + part["sourceUnitId"],
                  "sourceUnitIds": [part["sourceUnitId"]]} for part in parts]
        with self.assertRaisesRegex(ValueError, "split across groups or omitted"):
            subject.preflight(self.request, self.policy, self.plugin, split)
        self.worker.calls.clear()
        with self.assertRaisesRegex(ValueError, "split across groups or omitted"):
            runner.run(self.fixture.source, self.fixture.anchor, self.policy, self.worker.out,
                       "fixture-key", self.worker.fake_call, split, self.plugin)
        self.assertEqual([], self.worker.calls)

    def test_plugin_name_form_conflict_is_rejected_before_dispatch(self):
        self.policy["terminology"]["properNames"] = [{"source": "Jesus", "target": "耶稣", "reviewStatus": "project_established"}]
        self.policy["componentSha256"]["terminology"] = policy_tools.canonical_sha256(self.policy["terminology"])
        with self.plugin.open("a") as stream:
            stream.write("\nNAMES = {'Jesus': '另一名称'}\n")
        self.repin()
        with self.assertRaisesRegex(ValueError, "proper-name form differs"):
            self.receipt()

    def identity_caller(self, identity):
        worker = self.worker
        class Caller:
            execution_identity = identity
            def __call__(self, key, payload):
                return worker.fake_call(key, payload)
        return Caller()

    def test_same_transport_wrapped_fingerprint_proves_zero_call_carry_forward(self):
        f = self.fixture
        identity = {"backend": "fixture_transport", "version": "a"}
        caller = self.identity_caller(identity)
        original = self.worker.out.parent / "identity-prior"
        evidence = runner.run(f.source, f.anchor, f.policy, original, "fixture-key", caller,
                              plugin_path=self.plugin)
        receipt = json.loads((original / "rule-preflight.json").read_text())
        self.worker.calls.clear()
        subject.verify_prior_model_inputs(original, f.request, f.policy, self.plan, receipt,
                                          transport_identity=identity)
        for index, (group, prior) in enumerate(zip(self.plan, evidence["groups"]), 1):
            runner.carry_forward_group(original, self.worker.out, index, group, prior, f.policy)
        self.assertEqual([], self.worker.calls)
        for path in original.glob("group-*.json"):
            self.assertEqual(path.read_bytes(), (self.worker.out / path.name).read_bytes())

    def test_changed_transport_blocks_carry_before_dispatch_or_new_attempt(self):
        f = self.fixture
        original = self.worker.out.parent / "identity-prior"
        runner.run(f.source, f.anchor, f.policy, original, "fixture-key",
                   self.identity_caller({"backend": "fixture_transport", "version": "a"}),
                   plugin_path=self.plugin)
        self.worker.calls.clear()
        with self.assertRaisesRegex(ValueError, "prior model payload does not match cached response"):
            runner.run(f.source, f.anchor, f.policy, self.worker.out, "fixture-key",
                       self.identity_caller({"backend": "fixture_transport", "version": "b"}),
                       plugin_path=self.plugin, reuse_from=original)
        self.assertEqual([], self.worker.calls)
        self.assertFalse(self.worker.out.exists())

    def test_raw_wrapped_fingerprint_mismatch_is_rejected_without_calls(self):
        f = self.fixture
        identity = {"backend": "fixture_transport", "version": "a"}
        original = self.worker.out.parent / "identity-prior"
        runner.run(f.source, f.anchor, f.policy, original, "fixture-key", self.identity_caller(identity),
                   plugin_path=self.plugin)
        raw_path = original / "group-0001-astra.raw.json"
        raw = json.loads(raw_path.read_text())
        raw["payloadSha256"] = "f" * 64
        raw_path.write_text(json.dumps(raw))
        self.worker.calls.clear()
        with self.assertRaisesRegex(ValueError, "prior raw response transport or request identity differs"):
            subject.verify_prior_model_inputs(original, f.request, f.policy, self.plan,
                                              json.loads((original / "rule-preflight.json").read_text()),
                                              transport_identity=identity)
        self.assertEqual([], self.worker.calls)


class ControllerRulePreflightTests(unittest.TestCase):
    def setUp(self):
        from tests import test_canonical_layer2_controller as fixtures
        self.worker = fixtures.CanonicalLayer2ControllerTests(methodName="test_real_producer_and_plugin_create_only_human_pending_candidate")
        self.worker.setUp()
        self.addCleanup(self.worker.doCleanups)

    def test_controller_bad_pinned_plugin_is_blocked_before_job_dispatch(self):
        from scripts import canonical_layer2_controller as controller
        from scripts import sermon_workflow_jobs as jobs
        f = self.worker.fixture.fixture
        f.plugin_path.write_text(f.plugin_path.read_text().replace('"zh-Hans-sermon-v1"', '"mismatched-id"'))
        policy = copy.deepcopy(f.policy)
        policy["languageReview"]["pluginImplementationSha256"] = producer.plugin_implementation_sha256(f.plugin_path)
        policy["componentSha256"]["languageReview"] = policy_tools.canonical_sha256(policy["languageReview"])
        self.worker.fixture.write("policy.json", policy)
        with patch.object(jobs, "start_job", side_effect=AssertionError("must not dispatch")) as dispatch:
            result = controller.Controller(self.worker.path, mode="deterministic_execute").tick()
        dispatch.assert_not_called()
        self.assertFalse(result["dispatched"])
        self.assertEqual("layer2_rule_preflight_failed", result["nodes"]["text.zh-Hans"]["reasonCode"])
        self.assertEqual([], self.worker.calls)
        self.assertFalse(any(self.worker.output.glob("*.started.json")))

    def test_controller_passes_actual_frozen_receipt_to_plugin_and_candidate(self):
        from scripts import canonical_layer2_controller as controller
        plugin = controller.producer.run_language_plugin
        candidate = controller.producer.admit_evidence
        with self.worker.active() as (config, code, key, _), \
             patch.object(controller.producer, "run_language_plugin", wraps=plugin) as review, \
             patch.object(controller.producer, "admit_evidence", wraps=candidate) as admit:
            self.worker.execute(config, code, key)
        stored = json.loads((self.worker.output / "rule-preflight.json").read_text())
        self.assertEqual(stored, admit.call_args.kwargs["rule_preflight_receipt"])
        self.assertTrue(review.call_args_list)
        self.assertTrue(all(call.kwargs["rule_preflight_receipt"] == stored for call in review.call_args_list))
        self.assertEqual(4, len(self.worker.calls))


if __name__ == "__main__":
    unittest.main()
