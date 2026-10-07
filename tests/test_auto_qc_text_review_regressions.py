"""Focused deterministic-gate regressions for PR 260 review feedback."""
import unittest

from scripts.language_review_plugins import auto_qc_text_common as rules


class TextReviewRegressions(unittest.TestCase):
    def test_adjacent_spoken_numbers_remain_separate(self):
        for english in ("two, three, four", "two three four", "two and three and four",
                        "two; three; four", "two. Three. Four"):
            with self.subTest(english=english):
                self.assertEqual(rules.english_numbers(english), [2, 3, 4])
                for locale, target in (("es", "dos, tres, cuatro"),
                                       ("ko", "두 명, 세 명, 네 명"),
                                       ("zh-Hans", "二、三、四")):
                    with self.subTest(locale=locale):
                        self.assertEqual(rules.number_problems(english, target, locale, set()), [])
                        self.assertTrue(rules.number_problems(english, "9", locale, set()))
        for english, expected in (
            ("twenty-five", [25]), ("two hundred and thirty-four", [234]),
            ("one thousand two hundred and five", [1205]),
            ("two thousand and twenty-six", [2026]),
            ("nineteen ninety-nine", [1999]), ("twenty twenty-four", [2024]),
            ("twenty oh five", [2005]), ("2.5 and 1,234", ["2.5", 1234]),
            ("twenty, five", [20, 5]), ("nineteen, ninety-nine", [19, 99]),
            ("two hundred and five and six", [205, 6]),
        ):
            with self.subTest(english=english):
                self.assertEqual(rules.english_numbers(english), expected)

    def test_chapter_only_book_identity_and_presence(self):
        for english in ("Turn to Revelation 3.", "Turn to Revelation three.",
                        "Turn to Revelation chapter three."):
            for locale, good, bad in (
                ("es", "Apocalipsis capítulo 3", "Juan capítulo 3"),
                ("ko", "요한계시록 3장을 보십시오", "요한복음 3장을 보십시오"),
                ("zh-Hans", "请看启示录第三章", "请看约翰福音第三章"),
            ):
                with self.subTest(english=english, locale=locale):
                    self.assertEqual(rules.scripture_reference_problems(english, good, locale), [])
                    self.assertIn("book changed for 3", rules.scripture_reference_problems(english, bad, locale))
                    self.assertIn("missing chapter 3", rules.scripture_reference_problems(english, "Nada", locale))
        self.assertIn("book changed for 3", rules.scripture_reference_problems(
            "Read 1 John 3.", "Juan capítulo 3", "es"))
        self.assertEqual(rules.scripture_reference_problems(
            "Read 1 John 3.", "Primera de Juan capítulo tres", "es"), [])

    def test_chinese_complete_numerals(self):
        for value, bad in ((5, "十五个人"), (12, "一百十二个人"), (2, "两百个人"),
                           (5, "五十个人"), (5, "五佰个人"), (2026, "二〇二六五年"), ("2.5", "十二点五个人"),
                           (5, "五点二个人")):
            with self.subTest(value=value, bad=bad):
                self.assertFalse(rules.chinese_number_present(bad, value))
        for value, good in ((5, "五个人"), (12, "十二个人"), (2, "两个人"), (200, "两百个人"),
                            (2026, "二〇二六年"), ("2.5", "两点五倍"), (5, "第五章")):
            with self.subTest(value=value, good=good):
                self.assertTrue(rules.chinese_number_present(good, value))
        self.assertEqual(rules.number_problems("five people", "十五个人", "zh-Hans", set()),
                         ["missing number 5"])

    def test_translated_spoken_clocks_are_not_added_references(self):
        for locale, target in (("es", "Nos reunimos a las 10:30."),
                               ("ko", "오전 10:30에 만납니다."),
                               ("zh-Hans", "上午10:30见。"), ("es", "10:30")):
            with self.subTest(locale=locale, target=target):
                self.assertEqual(rules.scripture_reference_problems(
                    "We meet at half past ten.", target, locale), [])
        for locale, target in (("es", "Son las 10:30."), ("ko", "오전 10:30입니다."),
                               ("zh-Hans", "时间是10:30。")):
            self.assertEqual(rules.target_references(target, locale), (set(), set()))
        # Positive time evidence cannot erase a book-bound added passage.
        self.assertIn("added reference 10:30", rules.scripture_reference_problems(
            "We meet at half past ten.", "Juan 10:30", "es"))
        self.assertIn("added reference 3:16", rules.scripture_reference_problems(
            "We meet soon.", "3:16", "es"))
        self.assertEqual(rules.scripture_reference_problems(
            "Read John 10:30.", "Juan 10:30", "es"), [])

    def test_book_citations_cannot_be_exempted_by_matching_source_clocks(self):
        english = "Meet me at 10:30."
        for locale, citation, clock in (
            ("es", "Juan 10:30", "Nos reunimos a las 10:30."),
            ("ko", "요한복음 10장 30절", "오전 10:30에 만납니다."),
            ("zh-Hans", "约翰福音10章30节", "上午10:30见。"),
        ):
            with self.subTest(locale=locale):
                self.assertEqual(rules.scripture_reference_problems(english, clock, locale), [])
                for target in (citation, clock + " " + citation):
                    self.assertIn("added reference 10:30", rules.scripture_reference_problems(
                        english, target, locale))
        self.assertEqual(rules.scripture_reference_problems(english, "10:30", "es"), [])

    def test_exact_short_copies_without_function_words(self):
        for english in ("Jesus saves", "God loves all", "Jesus Saves", "Grace transforms lives"):
            for target in (english, "Dice: " + english + "."):
                self.assertEqual(rules.untranslated_problems(english, target, "es"),
                                 ["English source text copied into target"])
        for english, target in (("Jesus saves", "Jesús salva"), ("God loves all", "Dios ama a todos"),
                                ("Jesus", "Jesús"), ("Pastor Ken", "Pastor Ken")):
            self.assertEqual(rules.untranslated_problems(english, target, "es"), [])


if __name__ == "__main__":
    unittest.main()
