"""Target-language forms seen in the 2026-10-11 weekend run that the screens misread."""
import unittest

from scripts.language_review_plugins import auto_qc_text_common as rules


class TargetFormTests(unittest.TestCase):
    def test_spanish_todo_is_a_word_but_upper_case_todo_is_a_placeholder(self):
        self.assertEqual(rules.script_problems("Todo está roto.", "es"), [])
        self.assertIn("placeholder marker", rules.script_problems("Dios es TODO amor.", "es"))

    def test_names_and_brands_the_english_spells_keep_latin_script(self):
        english = "I'm going to take a hammer and I'm going to break the PlayStation."
        target = "“我要拿一把锤子，把那台 PlayStation 砸坏。”"
        self.assertEqual(rules.script_problems(target, "zh-Hans", english), [])
        self.assertEqual(rules.untranslated_problems(english, target, "zh-Hans"), [])
        copied = "我要 break the PlayStation now please"
        self.assertTrue(rules.untranslated_problems(english, copied, "zh-Hans"))

    def test_initialed_name_stays_but_copied_spanish_phrase_still_fails(self):
        self.assertEqual(rules.untranslated_problems("C. S. Lewis put it this way.",
                                                     "C. S. Lewis lo expresó así.", "es"), [])
        self.assertTrue(rules.untranslated_problems("C. S. Lewis put it this way.",
                                                    "C. S. Lewis put it así.", "es"))

    def test_fractions_ordinals_and_scaled_numbers(self):
        cases = [
            ("One third of the sea creatures die.", "海里的生物有三分之一死亡。", "zh-Hans"),
            ("Only one third.", "삼분의 일뿐입니다.", "ko"),
            ("That's trumpet one.", "이것이 첫 번째 나팔입니다.", "ko"),
            ("That's trumpet one.", "Esa es la primera trompeta.", "es"),
            ("If you do the math, 2.7 billion people on the earth perish.", "地球上会有二十七亿人丧生。", "zh-Hans"),
            ("If you do the math, 2.7 billion people on the earth perish.", "지구상에서 27억 명이 목숨을 잃습니다.", "ko"),
            ("If you do the math, 2.7 billion people on the earth perish.",
             "Si hacen las cuentas, dos mil setecientos millones de personas perecen.", "es"),
            ("An army of 200 million rises up.", "一支由两亿人组成的大军兴起。", "zh-Hans"),
            ("They did this every day for six days.", "그들은 엿새 동안 매일 이렇게 했습니다.", "ko"),
            ("Zero sins.", "一次罪都没有犯过。", "zh-Hans"),
            ("not 99% of your sins, 100% of all of your sins.", "不是百分之九十九的罪，而是百分之百。", "zh-Hans"),
        ]
        for english, target, locale in cases:
            with self.subTest(target=target):
                self.assertEqual(rules.number_problems(english, target, locale), [])
                self.assertEqual(rules.added_number_problems(english, target, locale), [])

    def test_changed_numbers_still_fail(self):
        self.assertTrue(rules.number_problems("2.7 billion people perish.", "地球上会有二十六亿人丧生。", "zh-Hans"))
        self.assertTrue(rules.number_problems("That's trumpet one.", "这就是第二号。", "zh-Hans"))
        self.assertTrue(rules.number_problems("They did this for six days.", "그들은 닷새 동안 했습니다.", "ko"))
        self.assertTrue(rules.added_number_problems("2.7 billion people perish.", "지구상에서 28억 명이 죽습니다.", "ko"))

    def test_decade_allows_ten_years(self):
        self.assertEqual(rules.added_number_problems("she just prayed for me for a decade.",
                                                     "그녀는 그저 10년 동안 저를 위해 기도했습니다.", "ko"), [])

    def test_spanish_bare_chapter_for_a_said_book(self):
        for english, target in [("So today we're going to camp out in Revelation 8 and 9.",
                                 "Así que hoy vamos a centrarnos en Apocalipsis 8 y 9."),
                                ("in Luke 15,", "en Lucas 15,")]:
            with self.subTest(target=target):
                self.assertEqual(rules.scripture_reference_problems(english, target, "es"), [])
        self.assertTrue(rules.scripture_reference_problems("in Luke 15,", "en Lucas 16,", "es"))


    def test_spanish_wrong_book_seed_plants_on_a_bare_chapter_and_is_caught(self):
        from scripts import auto_qc_seeded_errors as seeds
        english, target = "in Luke 15,", "en Lucas 15,"
        mutated = seeds.mutate_text({"english": english, "targetText": target}, "wrong_book", "es", None)
        self.assertEqual(mutated, "en Juan 15,")
        self.assertTrue(rules.scripture_reference_problems(english, mutated, "es"))

    def test_driver_treats_only_a_siteless_role_swap_as_not_applicable(self):
        import inspect
        from scripts import run_machine_qc_clip_test as driver
        self.assertIn('kind != "swapped_name"', inspect.getsource(driver.calibration_coverage))


if __name__ == "__main__":
    unittest.main()
