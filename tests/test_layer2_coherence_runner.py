import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.orchestration import group_legacy
from tongxing_production.text import auto_repair
from tongxing_production.text import coherence
from tongxing_production.text import controller
from tongxing_production.text import models as subject
from tests import test_produce_target_language_candidate as fixture_module

OPTIONS = {"schemaVersion": coherence.LAYER2_SCHEMA, "locales": ["zh-Hans"],
           "priorTargetGroups": 4, "chains": 1, "windowGroups": 8}


class CoherenceRunnerTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.ProduceTargetLanguageCandidateTests(
            methodName="test_compiles_valid_candidate_without_human_approval")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.out = Path(temp.name) / "run"
        self.calls = []
        self.window_reply = None

    def fake_call(self, api_key, payload):
        self.calls.append(payload)
        prompt = json.loads(payload["messages"][1]["content"])
        if "knownGlossary" in prompt:
            result = {"people": [{"source": "Jesus", "target": "耶稣", "note": ""}],
                      "pronouns": {"jesus": "祂"}}
        elif "priorChinese" in prompt:
            if self.window_reply is not None:
                return {"id": f"response-{len(self.calls)}", "model": payload["model"],
                        "choices": [{"finish_reason": "stop", "message": {"content": self.window_reply}}]}
            result = {"groups": [{"translationGroupId": row["translationGroupId"], "chinese": f"草稿{n}"}
                                 for n, row in enumerate(prompt["groups"], 1)]}
        else:
            group = next(row for row in self.fixture.evidence["groups"]
                         if row["sourceUnitIds"] == prompt["sourceUnitIds"])
            keys = ("translationGroupId", "sourceUnitIds", "targetUtterances", "coverage")
            if payload["reasoning_effort"] != "high":
                keys += ("semanticReview",)
            result = {key: copy.deepcopy(group[key]) for key in keys}
            result["translationGroupId"] = prompt["translationGroupId"]
        return {"id": f"response-{len(self.calls)}", "model": payload["model"],
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}]}

    def run_models(self, options):
        f = self.fixture
        return subject.run(f.source, f.anchor, f.policy, self.out, "fixture-key", self.fake_call,
                           plugin_path=f.plugin_path, coherence=options)

    def group_prompts(self):
        prompts = []
        for payload in self.calls:
            prompt = json.loads(payload["messages"][1]["content"])
            if "knownGlossary" not in prompt and "priorChinese" not in prompt:
                prompts.append((payload["messages"][0]["content"], prompt))
        return prompts

    def test_first_round_chain_passes_glossary_prior_text_and_hints(self):
        evidence = self.run_models(OPTIONS)
        # One glossary slice, one window draft, then translate and review for each of the two groups.
        self.assertEqual(len(self.calls), 6)
        prompts = self.group_prompts()
        first_text = "".join(evidence["groups"][0]["targetUtterances"])
        for instruction, prompt in prompts:
            self.assertEqual(prompt["sermonGlossary"]["people"][0]["target"], "耶稣")
            self.assertEqual(prompt["sermonGlossary"]["pronouns"], {"jesus": "祂"})
            self.assertEqual(set(prompt["continuation"]), {"continuesPrevious", "continuedByNext"})
        self.assertIn(coherence.TRANSLATOR_RULE, prompts[0][0])
        self.assertIn(coherence.REVIEWER_RULE, prompts[1][0])
        prior = [{"translationGroupId": evidence["groups"][0]["translationGroupId"], "targetText": first_text}]
        # Translator and reviewer of group 1, then of group 2.
        self.assertEqual([prompt["priorTarget"] for _, prompt in prompts], [[], [], prior, prior])
        self.assertEqual([prompt["windowDraft"] for _, prompt in prompts],
                         [{"targetText": "草稿1"}] * 2 + [{"targetText": "草稿2"}] * 2)
        receipt = json.loads((self.out / "coherence" / "receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["dispatch"], {"mode": "chains", "chains": [[1, 2]]})
        self.assertEqual(receipt["priorTargetSources"], {"chain": 2})
        self.assertEqual(receipt["groupsWithWindowDraft"], 2)
        self.assertFalse(receipt["humanApproval"])
        self.assertEqual(set(evidence["generation"]), {"translator", "reviewer"})
        self.assertNotIn("coherence", evidence)

    def test_rerun_of_the_same_round_makes_no_new_call(self):
        first = self.run_models(OPTIONS)
        count = len(self.calls)
        self.assertEqual(self.run_models(OPTIONS), first)
        self.assertEqual(len(self.calls), count)

    def test_unusable_window_reply_leaves_groups_without_a_draft(self):
        self.window_reply = "not json"
        evidence = self.run_models(OPTIONS)
        self.assertEqual(len(evidence["groups"]), 2)
        self.assertFalse(any("windowDraft" in prompt for _, prompt in self.group_prompts()))
        self.window_reply = json.dumps({"groups": [{"translationGroupId": "unknown", "chinese": "x"}]})
        self.calls, self.out = [], self.out.parent / "second"
        self.run_models({**OPTIONS, "windowGroups": 1})
        self.assertFalse(any("windowDraft" in prompt for _, prompt in self.group_prompts()))

    def test_separate_chains_do_not_see_each_others_text(self):
        self.run_models({**OPTIONS, "chains": 2})
        self.assertEqual([prompt["priorTarget"] for _, prompt in self.group_prompts()], [[], [], [], []])
        receipt = json.loads((self.out / "coherence" / "receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["dispatch"]["chains"], [[1], [2]])

    def test_default_run_prompts_are_unchanged(self):
        self.run_models(None)
        self.assertEqual(len(self.calls), 4)
        for instruction, prompt in self.group_prompts():
            self.assertFalse({"sermonGlossary", "priorTarget", "continuation"} & set(prompt))
            self.assertNotIn(coherence.TRANSLATOR_RULE, instruction)
        self.assertFalse((self.out / "coherence").exists())

    def test_unlisted_locale_or_bad_options_send_nothing(self):
        for options in ({**OPTIONS, "locales": ["ko"]}, {**OPTIONS, "chains": 0},
                        {**OPTIONS, "extra": True}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.run_models(options)
        self.assertEqual(self.calls, [])

    def test_repair_round_reuses_glossary_and_recorded_prior_text(self):
        f = self.fixture
        previous = self.out.parent / "round-1"
        failed_id = subject.group_plan(f.request, f.anchor)[1]["translationGroupId"]

        def failing(api_key, payload):
            response = self.fake_call(api_key, payload)
            prompt = json.loads(payload["messages"][1]["content"])
            if payload["reasoning_effort"] == "medium" and prompt.get("translationGroupId") == failed_id:
                result = json.loads(response["choices"][0]["message"]["content"])
                result["semanticReview"]["status"] = "fail"
                result["semanticReview"]["issues"] = ["Misread a paraphrase as a quote"]
                response["choices"][0]["message"]["content"] = json.dumps(result)
            return response

        with self.assertRaisesRegex(ValueError, "Sol flagged group"):
            subject.run(f.source, f.anchor, f.policy, previous, "fixture-key", failing,
                        plugin_path=f.plugin_path, coherence=OPTIONS)
        first_text = "".join(f.evidence["groups"][0]["targetUtterances"])
        brief = {"schemaVersion": subject.PARTIAL_REPAIR_SCHEMA,
                 **{key: f.request[key] for key in ("targetLocale", "englishSourcePackageJsonSha256",
                                                    "anchorManifestSha256", "translationPolicySha256")},
                 "groups": [{"translationGroupId": failed_id,
                             "sourceUnitIds": f.evidence["groups"][1]["sourceUnitIds"],
                             "failedRole": "reviewer",
                             "failedCacheSha256": hashlib.sha256(
                                 (previous / "group-0002-sol.json").read_bytes()).hexdigest(),
                             "failureReason": "Sol confused indirect description with a direct quote",
                             "instruction": "Treat this sentence as the speaker's paraphrase."}]}
        before = len(self.calls)
        evidence = subject.run(f.source, f.anchor, f.policy, self.out, "fixture-key", self.fake_call,
                               plugin_path=f.plugin_path, reuse_from=previous,
                               partial_repair_brief=brief, coherence=OPTIONS)
        # Only the failed group is translated and reviewed again; the glossary is reused.
        self.assertEqual(len(self.calls) - before, 2)
        self.assertEqual(json.loads(self.calls[-1]["messages"][1]["content"])["windowDraft"], {"targetText": "草稿2"})
        del self.calls[:before]
        for _, prompt in self.group_prompts():
            self.assertEqual(prompt["translationGroupId"], failed_id)
            self.assertEqual(prompt["priorTarget"][0]["targetText"], first_text)
        self.assertEqual(len(evidence["groups"]), 2)
        receipt = json.loads((self.out / "coherence" / "receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["dispatch"], {"mode": "independent_groups"})
        self.assertEqual(receipt["priorTargetSources"], {"recorded": 2})

    def test_coherence_inputs_are_not_a_revision_in_group_records(self):
        self.run_models(OPTIONS)
        preview = json.loads((self.out / "group-0002-astra.policy-preview.json").read_text(encoding="utf-8"))
        cache = json.loads((self.out / "group-0002-astra.json").read_text(encoding="utf-8"))
        self.assertIsNone(group_legacy._role_inputs(preview, cache, None)["revisionSha256"])


class CoherenceHelperTests(unittest.TestCase):
    def test_glossary_merge_keeps_first_entry_and_pronoun(self):
        known = coherence.merge_glossary(coherence.empty_glossary(), {
            "people": [{"source": "Betsie", "target": "贝茜", "note": "姐姐"}], "pronouns": {"jesus": "祂"}})
        merged = coherence.merge_glossary(known, {
            "people": [{"source": "betsie", "target": "贝特西"}, {"source": "Corrie", "target": "彭柯丽"}],
            "pronouns": {"jesus": "他", "god": "祂"}})
        self.assertEqual([row["target"] for row in merged["people"]], ["贝茜", "彭柯丽"])
        self.assertEqual(merged["pronouns"], {"jesus": "祂", "god": "祂"})
        self.assertEqual(known["people"][0]["target"], "贝茜")

    def test_bounded_glossary_drops_least_useful_entries_first(self):
        glossary = coherence.empty_glossary()
        glossary["people"] = [{"source": "Corrie", "target": "彭柯丽"}]
        glossary["culturalReferences"] = [{"source": f"idiom {i}", "meaning": "x" * 50} for i in range(200)]
        bounded, dropped = coherence.bounded_glossary(glossary, max_chars=2000)
        self.assertLessEqual(len(json.dumps(bounded, ensure_ascii=False)), 2000)
        self.assertEqual(bounded["people"], glossary["people"])
        self.assertGreater(dropped, 0)

    def test_slices_and_chains_cover_every_item_once_in_order(self):
        units = [{"sourceUnitId": f"u{i:03d}", "english": "word " * 30} for i in range(100)]
        slices = coherence.glossary_slices(units, max_chars=1000)
        self.assertEqual([row for part in slices for row in part], units)
        self.assertTrue(all(sum(len(r["sourceUnitId"]) + len(r["english"]) + 3 for r in part) <= 1000
                            for part in slices))
        self.assertEqual(coherence.chain_plan(10, 4), [[1, 2, 3], [4, 5, 6], [7, 8], [9, 10]])
        self.assertEqual(coherence.chain_plan(2, 16), [[1], [2]])
        self.assertEqual(coherence.chain_plan(0, 4), [])

    def test_continuation_flags_mark_both_sides(self):
        units = [{"sourceUnitId": "a", "english": "She is nourished for a time,", "start": 0, "end": 2},
                 {"sourceUnitId": "b", "english": "times and half a time.", "start": 2.1, "end": 4},
                 {"sourceUnitId": "c", "english": "Both.", "start": 6, "end": 7}]
        flags = coherence.continuation_flags(units)
        self.assertEqual(coherence.group_continuation(flags, ["a"]),
                         {"continuesPrevious": False, "continuedByNext": True})
        self.assertEqual(coherence.group_continuation(flags, ["b"]),
                         {"continuesPrevious": True, "continuedByNext": False})
        self.assertFalse(any(flags["c"].values()))


class CoherenceConfigurationTests(unittest.TestCase):
    def test_auto_repair_binding_accepts_only_valid_coherence_options(self):
        binding = {"routingVersion": auto_repair.ROUTING_VERSION, "groupWorkers": 4, "maxActiveLocales": 1}
        self.assertEqual(controller._auto_repair_binding({**binding, "coherence": OPTIONS})["coherence"], OPTIONS)
        for bad in ({**OPTIONS, "locales": ["es"]}, {**OPTIONS, "priorTargetGroups": 13}, {}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                controller._auto_repair_binding({**binding, "coherence": bad})

    def test_only_listed_locales_receive_the_options(self):
        class Config:
            auto_repair = {"coherence": OPTIONS}
        self.assertEqual(controller._coherence(Config, "zh-Hans"), OPTIONS)
        self.assertIsNone(controller._coherence(Config, "ko"))
        Config.auto_repair = {}
        self.assertIsNone(controller._coherence(Config, "zh-Hans"))


if __name__ == "__main__":
    unittest.main()
