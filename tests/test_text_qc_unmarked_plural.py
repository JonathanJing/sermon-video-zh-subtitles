"""Korean and Chinese judge prompts treat grammatical number alone as minor; counts stay major."""
import unittest

from scripts import target_text_auto_qc as text_qc


class UnmarkedPluralTests(unittest.TestCase):
    def test_korean_and_chinese_prompts_carry_the_rule_and_spanish_does_not(self):
        for locale in ("ko", "zh-Hans"):
            for spoken in (False, True):
                system = text_qc.comparison_system(locale, spoken=spoken)
                self.assertIn("does not require plural marking", system)
                self.assertIn("still a major number issue", system)
                self.assertIn(text_qc.LANGUAGE_NAMES[locale], system)
                self.assertEqual(system.count("status is fail"), 1)
        self.assertNotIn("plural", text_qc.comparison_system("es"))
        self.assertEqual(text_qc.comparison_system("es"), text_qc.COMPARE_SYSTEM.format(language="Spanish"))

    def test_the_comparison_request_uses_the_locale_prompt(self):
        group = {"groupId": "g", "english": "before the trumpets are ever given", "targetText": "나팔이 주어지기도 전에"}
        request = text_qc.comparison_request(group, "ko", "before the trumpet was given")
        self.assertEqual(request["system"], text_qc.comparison_system("ko"))
        spoken = text_qc.comparison_request({**group, "condensation": {"x": 1}}, "ko", "before the trumpet was given")
        self.assertEqual(spoken["system"], text_qc.comparison_system("ko", spoken=True))


if __name__ == "__main__":
    unittest.main()
