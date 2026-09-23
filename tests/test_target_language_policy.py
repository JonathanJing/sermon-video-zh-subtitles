import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts import target_language_policy as subject


ROOT = Path(__file__).resolve().parents[1]
POLICIES = ROOT / "config/target-language-policies"


def read_policy(locale):
    return json.loads((POLICIES / f"{locale}.json").read_text(encoding="utf-8"))


class TargetLanguagePolicyTests(unittest.TestCase):
    def test_frozen_chinese_and_korean_policies_are_separate_and_pending(self):
        zh = read_policy("zh-Hans")
        ko = read_policy("ko")
        zh_result = subject.validate_policy(zh)
        ko_result = subject.validate_policy(ko)
        self.assertNotEqual(zh_result["translationPolicySha256"], ko_result["translationPolicySha256"])
        self.assertEqual(zh["scripture"]["editionId"], "CUV")
        self.assertIn("cuv_exact_quote", zh["languageReview"]["requiredChecks"])
        self.assertIsNone(ko["scripture"]["editionId"])
        self.assertIn("scripture_policy_pending", ko_result["unresolved"])
        self.assertFalse(zh_result["productionPolicyReady"])
        self.assertFalse(ko_result["productionPolicyReady"])

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
