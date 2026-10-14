import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import target_language_policy as subject


ROOT = Path(__file__).resolve().parents[1]
POLICIES = ROOT / "config/target-language-policies"


def read_policy(locale):
    return json.loads((POLICIES / f"{locale}.json").read_text(encoding="utf-8"))


class TargetLanguagePolicyTests(unittest.TestCase):
    def test_claude_selection_and_manual_draft_cannot_freeze(self):
        draft = read_policy("ko")
        draft.pop("componentSha256")
        selected = subject.apply_translator_backend(draft, 'claude_cli')
        for policy in (selected, {**draft, 'reviewer': {**draft['reviewer'], 'model': 'claude-opus-5-5'}}):
            with self.assertRaisesRegex(ValueError, 'freezes only as the claude_cli_opus'):
                subject.freeze_policy(policy)
        strict = {**selected, 'schemaVersion': subject.POLICY_V3}
        with self.assertRaisesRegex(ValueError, 'freezes only as the claude_cli_opus'):
            subject.freeze_strict_policy(strict, {})

    def test_claude_cli_opus_backend_freezes_both_roles_through_claude(self):
        draft = read_policy("ko")
        draft.pop("componentSha256")
        selected = subject.apply_layer2_backend(draft, 'claude_cli_opus')
        self.assertEqual({role: (selected[role]['model'], selected[role]['reasoningEffort'])
                          for role in ('translator', 'reviewer')},
                         {'translator': ('claude-opus-5-5', 'high'), 'reviewer': ('claude-opus-5-5', 'medium')})
        self.assertEqual(selected['translator']['promptVersion'], draft['translator']['promptVersion'])
        policy = subject.freeze_policy(selected)
        self.assertEqual(subject.layer2_backend(policy), 'claude_cli_opus')
        self.assertEqual(subject.layer2_backend(subject.freeze_policy(subject.apply_layer2_backend(draft, 'openai_api'))),
                         'openai_api')
        # Any other Claude combination stays refused: e.g. an Opus reviewer at high effort.
        wrong = {**selected, 'reviewer': {**selected['reviewer'], 'reasoningEffort': 'high'}}
        with self.assertRaisesRegex(ValueError, 'freezes only as the claude_cli_opus'):
            subject.freeze_policy(wrong)
        with tempfile.TemporaryDirectory() as folder:
            source, out = Path(folder) / 'draft.json', Path(folder) / 'policy.json'
            source.write_text(json.dumps(draft))
            with patch('sys.argv', ['policy', 'freeze', '--policy', str(source), '--out', str(out),
                                    '--layer2-backend', 'claude_cli_opus']):
                subject.main()
            self.assertEqual(subject.layer2_backend(json.loads(out.read_text())), 'claude_cli_opus')

    def test_claude_cli_freeze_leaves_no_policy_artifact(self):
        draft = read_policy("ko")
        draft.pop("componentSha256")
        with tempfile.TemporaryDirectory() as folder:
            source, out = Path(folder) / 'draft.json', Path(folder) / 'new/policy.json'
            source.write_text(json.dumps(draft))
            with patch('sys.argv', ['policy', 'freeze', '--policy', str(source), '--out', str(out),
                                    '--translator-backend', 'claude_cli']):
                with self.assertRaisesRegex(ValueError, 'freezes only as the claude_cli_opus'):
                    subject.main()
            self.assertFalse(out.exists())
            self.assertFalse(out.parent.exists())

    def test_already_frozen_claude_identity_still_validates_without_migration(self):
        policy = read_policy("ko")
        policy['translator'].update(model='claude-opus-5-5', reasoningEffort='high')
        policy['componentSha256']['translator'] = subject.canonical_sha256(policy['translator'])
        before = json.dumps(policy, sort_keys=True)
        identity = subject.validate_policy(policy)
        self.assertEqual(identity['translationPolicySha256'], subject.canonical_sha256(policy))
        self.assertEqual(json.dumps(policy, sort_keys=True), before)

    def test_frozen_three_language_policies_keep_distinct_unresolved_gates(self):
        zh = read_policy("zh-Hans")
        ko = read_policy("ko")
        es = read_policy("es")
        zh_result = subject.validate_policy(zh)
        ko_result = subject.validate_policy(ko)
        es_result = subject.validate_policy(es)
        self.assertEqual(len({result["translationPolicySha256"] for result in
                              (zh_result, ko_result, es_result)}), 3)
        self.assertEqual(zh["scripture"]["editionId"], "CUV")
        self.assertIn("cuv_exact_quote", zh["languageReview"]["requiredChecks"])
        self.assertEqual(ko["scripture"]["editionId"], "NKRV-1998")
        self.assertEqual(es["scripture"]["editionId"], "RVR60-1960")
        self.assertEqual(es["formatting"]["speechRegister"],
                         "neutral_latin_american_public_sermon_spanish")
        self.assertIn("scripture_policy_pending", ko_result["unresolved"])
        self.assertIn("scripture_policy_pending", es_result["unresolved"])
        self.assertTrue(all(not result["productionPolicyReady"] for result in
                            (zh_result, ko_result, es_result)))

    def test_reference_only_policy_needs_no_bible_edition_but_keeps_other_gates(self):
        draft = read_policy("ko")
        draft.pop("componentSha256")
        draft["scripture"]["editionId"] = None
        draft["scripture"]["citationUseStatus"] = "project_source_reviewed"
        draft["scripture"]["quoteCheckPolicy"] = "references_only"
        resolved = subject.validate_policy(subject.freeze_policy(draft))
        self.assertNotIn("scripture_policy_pending", resolved["unresolved"])
        self.assertIn("language_review_plugin_pending", resolved["unresolved"])
        draft["scripture"]["quoteCheckPolicy"] = "source_bound_exact_quote"
        exact_quote = subject.validate_policy(subject.freeze_policy(draft))
        self.assertIn("scripture_policy_pending", exact_quote["unresolved"])

    def test_every_component_changes_global_identity_and_stale_hash_fails(self):
        original = read_policy("ko")
        original_hash = subject.validate_policy(original)["translationPolicySha256"]
        replacements = {
            "translator": ("promptVersion", "translate-ko-v2"),
            "reviewer": ("promptVersion", "review-ko-v2"),
            "terminology": ("properNames", []),
            "scripture": ("referenceStyle", "Review every citation."),
            "languageReview": ("registerRules", ["Use natural Korean."]),
            "formatting": ("speechRegister", "formal_korean"),
            "batching": ("batchSize", 10),
        }
        for component, (field, value) in replacements.items():
            with self.subTest(component=component):
                changed = copy.deepcopy(original)
                changed[component][field] = value
                with self.assertRaisesRegex(ValueError, f"component hash changed: {component}"):
                    subject.validate_policy(changed)
                changed.pop("componentSha256")
                frozen = subject.freeze_policy(changed)
                self.assertNotEqual(subject.validate_policy(frozen)["translationPolicySha256"], original_hash)

    def test_terminology_source_and_review_status_fail_closed(self):
        ko = read_policy("ko")
        with tempfile.TemporaryDirectory() as temporary:
            changed_table = Path(temporary) / "series.md"
            changed_table.write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Series terminology source changed"):
                subject.validate_policy(ko, series_table=changed_table)
        ko.pop("componentSha256")
        ko["terminology"]["seriesNames"][0]["reviewStatus"] = "human_reviewed"
        with self.assertRaisesRegex(ValueError, "lacks target text"):
            subject.freeze_policy(ko)
        ko["terminology"]["seriesNames"][0]["target"] = "   "
        with self.assertRaisesRegex(ValueError, "lacks target text"):
            subject.freeze_policy(ko)

    def test_series_table_coverage_and_chinese_names_cannot_drift(self):
        zh = read_policy("zh-Hans")
        zh.pop("componentSha256")
        zh["terminology"]["seriesNames"].pop()
        with self.assertRaisesRegex(ValueError, "series terminology coverage"):
            subject.freeze_policy(zh)
        zh = read_policy("zh-Hans")
        zh.pop("componentSha256")
        zh["terminology"]["seriesNames"][0]["target"] = "未经审核的替代译名"
        with self.assertRaisesRegex(ValueError, "differs from established"):
            subject.freeze_policy(zh)

    def test_reviewer_prompt_must_be_independent(self):
        ko = read_policy("ko")
        ko.pop("componentSha256")
        ko["reviewer"]["promptVersion"] = ko["translator"]["promptVersion"]
        with self.assertRaisesRegex(ValueError, "independent prompt"):
            subject.freeze_policy(ko)


if __name__ == "__main__":
    unittest.main()
