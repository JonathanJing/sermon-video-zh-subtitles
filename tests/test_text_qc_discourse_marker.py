"""A listener-directed discourse marker may read back as an audience address; added common-knowledge claims stay major."""
import unittest

from scripts import target_text_auto_qc as text_qc


class DiscourseMarkerTests(unittest.TestCase):
    def test_every_caption_judge_carries_the_rule_once(self):
        for locale in ("zh-Hans", "ko", "es"):
            with self.subTest(locale=locale):
                system = text_qc.comparison_system(locale)
                self.assertIn('"you know", "you see", "I mean"', system)
                self.assertIn('"everyone knows that" is at most minor', system)
                self.assertIn("where ORIGINAL has no such marker, is still a major addition", system)
                self.assertEqual(system.count("status is fail"), 1)
                self.assertTrue(system.endswith("Return JSON matching the schema."))

    def test_the_spoken_judge_keeps_its_own_filler_rule(self):
        # The condensed dub's judge already treats filler as at most a minor omission.
        self.assertNotIn("everyone knows", text_qc.comparison_system("zh-Hans", spoken=True))
        self.assertIn("filler", text_qc.comparison_system("zh-Hans", spoken=True))

    def test_the_rule_comes_before_the_plural_note_and_the_verdict(self):
        system = text_qc.comparison_system("zh-Hans")
        self.assertLess(system.index("everyone knows that"), system.index("does not require plural marking"))
        self.assertLess(system.index("does not require plural marking"), system.index("status is fail"))


if __name__ == "__main__":
    unittest.main()
