import unittest
from pathlib import Path

from scripts import produce_target_language_candidate as producer
from scripts.language_review_plugins import es_weekly_reference, ko_weekly_reference


class WeeklyReferenceLanguagePluginTests(unittest.TestCase):
    def policy(self, locale, plugin):
        return {
            "targetLocale": locale,
            "sourceScope": {"englishSourcePackageJsonSha256": "a" * 64},
            "languageReview": {"requiredChecks": plugin.REQUIRED},
            "scripture": {"editionId": None, "citationUseStatus": "project_source_reviewed",
                          "quoteCheckPolicy": "references_only"},
            "terminology": {"seriesNames": [], "properNames": [
                {"source": "Julius Caesar", "target": "율리우스 카이사르" if locale == "ko"
                 else "Julio César", "reviewStatus": "human_reviewed"},
            ]},
        }

    def group(self, text):
        return {"englishSourcePackageJsonSha256": "a" * 64,
                "sourceUnitIds": ["s-u001"], "targetText": text,
                "targetUtterances": [text]}

    def test_korean_reference_only_passes_structural_checks(self):
        units = [{"sourceUnitId": "s-u001", "english": "Julius Caesar spoke of Revelation 4."}]
        checks = ko_weekly_reference.review_group(
            self.policy("ko", ko_weekly_reference), units,
            self.group("율리우스 카이사르는 요한계시록 4장을 말했습니다."))
        self.assertEqual([row["checkId"] for row in checks], ko_weekly_reference.REQUIRED)
        self.assertTrue(all(row["status"] == "pass" for row in checks))

    def test_spanish_rejects_edition_claim_and_wrong_source(self):
        units = [{"sourceUnitId": "s-u001", "english": "Julius Caesar spoke of Revelation 4."}]
        policy = self.policy("es", es_weekly_reference)
        group = self.group("Julio César habló de Apocalipsis 4, según RVR1960.")
        checks = es_weekly_reference.review_group(policy, units, group)
        self.assertEqual(checks[3]["status"], "fail")
        group = self.group("Julio César habló de Apocalipsis 4.")
        group["englishSourcePackageJsonSha256"] = "b" * 64
        self.assertEqual(es_weekly_reference.review_group(policy, units, group)[3]["status"], "fail")

    def test_missing_reviewed_name_and_explicit_digit_fail(self):
        units = [{"sourceUnitId": "s-u001", "english": "Julius Caesar spoke of Revelation 4."}]
        checks = es_weekly_reference.review_group(
            self.policy("es", es_weekly_reference), units,
            self.group("César habló de Apocalipsis."))
        self.assertEqual(checks[2]["status"], "fail")
        self.assertEqual(checks[4]["status"], "fail")

    def test_policy_and_plugin_checks_must_match(self):
        policy = self.policy("ko", ko_weekly_reference)
        policy["languageReview"]["requiredChecks"] = ["natural_korean"]
        with self.assertRaisesRegex(ValueError, "differs from plugin"):
            ko_weekly_reference.review_group(
                policy, [{"sourceUnitId": "s-u001", "english": "Hello."}],
                self.group("안녕하세요."))

    def test_missing_source_scope_cannot_pass_reference_check(self):
        policy = self.policy("es", es_weekly_reference)
        policy.pop("sourceScope")
        group = self.group("Julio César habló de Apocalipsis 4.")
        group.pop("englishSourcePackageJsonSha256")
        checks = es_weekly_reference.review_group(
            policy,
            [{"sourceUnitId": "s-u001", "english": "Julius Caesar spoke of Revelation 4."}],
            group,
        )
        self.assertEqual(checks[3]["status"], "fail")

    def test_dependency_hash_includes_shared_weekly_rules(self):
        path = Path(ko_weekly_reference.__file__)
        sources = producer.plugin_implementation_sources(path)
        self.assertEqual([source.name for source in sources],
                         ["ko_weekly_reference.py", "common.py", "weekly_reference_common.py"])


if __name__ == "__main__":
    unittest.main()
