import unittest

from scripts.language_review_plugins import es_laodicea, zh_hans_laodicea
from scripts.language_review_plugins.laodicea_common import SOURCE_SHA256


class LaodiceaLanguagePluginTests(unittest.TestCase):
    def policy(self, locale, plugin):
        return {"targetLocale": locale,
                "languageReview": {"requiredChecks": plugin.REQUIRED},
                "scripture": {"editionId": "RVR60-1960" if locale == "es" else "CUV",
                              "citationUseStatus": "project_source_reviewed",
                              "quoteCheckPolicy": "references_only"},
                "terminology": {"seriesNames": []}}

    def test_spanish_todo_is_ordinary_word_but_uppercase_marker_fails(self):
        units = [{"sourceUnitId": "block-18-u003", "english": "The whole cup."}]
        group = {"englishSourcePackageJsonSha256": SOURCE_SHA256,
                 "sourceUnitIds": ["block-18-u003"], "targetText": "Todo queda tibio.",
                 "targetUtterances": ["Todo queda tibio."]}
        checks = es_laodicea.review_group(self.policy("es", es_laodicea), units, group)
        self.assertTrue(all(row["status"] == "pass" for row in checks))
        group["targetText"] = "TODO queda tibio."
        self.assertEqual(es_laodicea.review_group(
            self.policy("es", es_laodicea), units, group)[0]["status"], "fail")

    def test_chinese_reference_policy_rejects_other_source_or_quote_policy(self):
        units = [{"sourceUnitId": "block-15-u002", "english": "Chapter 3, verse 16."}]
        group = {"englishSourcePackageJsonSha256": SOURCE_SHA256,
                 "sourceUnitIds": ["block-15-u002"],
                 "targetText": "启示录第3章第16节。",
                 "targetUtterances": ["启示录第3章第16节。"]}
        policy = self.policy("zh-Hans", zh_hans_laodicea)
        self.assertTrue(all(row["status"] == "pass" for row in
                            zh_hans_laodicea.review_group(policy, units, group)))
        group["englishSourcePackageJsonSha256"] = "0" * 64
        self.assertEqual(zh_hans_laodicea.review_group(policy, units, group)[1]["status"], "fail")
        group["englishSourcePackageJsonSha256"] = SOURCE_SHA256
        policy["scripture"]["quoteCheckPolicy"] = "source_bound_exact_quote"
        self.assertEqual(zh_hans_laodicea.review_group(policy, units, group)[1]["status"], "fail")


if __name__ == "__main__":
    unittest.main()
