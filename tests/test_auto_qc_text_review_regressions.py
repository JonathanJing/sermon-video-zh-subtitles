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
                        self.assertEqual(rules.number_problems(english, target, locale), [])
                        self.assertTrue(rules.number_problems(english, "9", locale))
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

    def test_lone_one_is_a_count_unless_used_as_a_pronoun(self):
        for english in ("You only have one life.", "There is one God.", "He healed one man."):
            with self.subTest(english=english):
                self.assertEqual(rules.english_numbers(english), [1])
        for locale, bad, good in (("es", "Tienes dos vidas.", "Solo tienes una vida."),
                                  ("ko", "인생은 두 번입니다.", "인생은 한 번뿐입니다."),
                                  ("zh-Hans", "你有两次生命。", "你只有一次生命。")):
            with self.subTest(locale=locale):
                self.assertEqual(rules.number_problems("You only have one life.", bad, locale),
                                 ["missing number 1"])
                self.assertEqual(rules.number_problems("You only have one life.", good, locale), [])
        for english in ("the one who believes", "No one is righteous.", "Love one another.",
                        "One day he came.", "the Holy One of Israel", "Pick this one.",
                        "He is the only one."):
            with self.subTest(english=english):
                self.assertEqual(rules.english_numbers(english), [])
        self.assertEqual(rules.english_numbers("zero tolerance"), [0])
        self.assertTrue(rules.korean_number_present("제로 상태", 0))

    def test_book_identity_survives_spoken_verse_notation(self):
        for english in ("John chapter three verse sixteen", "John 3:16", "John 3 verse 16",
                        "John three verse sixteen"):
            for locale, good, bad in (
                ("es", "Juan 3:16", "Romanos 3:16"),
                ("es", "Juan capítulo tres versículo dieciséis", "Romanos capítulo tres versículo dieciséis"),
                ("ko", "요한복음 3:16", "로마서 3:16"),
                ("zh-Hans", "约翰福音3:16", "罗马书3:16"),
            ):
                with self.subTest(english=english, locale=locale, bad=bad):
                    self.assertNotIn("book changed for 3:16", rules.scripture_reference_problems(english, good, locale))
                    self.assertIn("book changed for 3:16", rules.scripture_reference_problems(english, bad, locale))

    def test_book_number_verse_citation_keeps_its_verse(self):
        for locale, target in (("es", "Juan 3:16"), ("ko", "요한복음 3장 16절"), ("zh-Hans", "约翰福音3章16节")):
            with self.subTest(locale=locale):
                self.assertEqual(rules.scripture_reference_problems("Turn to John 3 verse 16.", target, locale), [])
                self.assertEqual(rules.number_problems("Turn to John 3 verse 16.", target, locale), [])
        self.assertIn("missing reference 3:16",
                      rules.scripture_reference_problems("Turn to John 3 verse 16.", "Juan 3:17", "es"))

    def test_a_repeated_number_must_be_kept_each_time(self):
        english = "He took five loaves and five fish."
        for locale, bad, good in (("zh-Hans", "五个饼和六条鱼", "五个饼和五条鱼"),
                                  ("ko", "빵 다섯 개와 물고기 여섯 마리", "빵 다섯 개와 물고기 다섯 마리"),
                                  ("es", "cinco panes y seis peces", "cinco panes y cinco peces")):
            with self.subTest(locale=locale):
                self.assertEqual(rules.number_problems(english, bad, locale), ["missing number 5 (1 of 2)"])
                self.assertEqual(rules.number_problems(english, good, locale), [])
        # A number inside a larger one is not another occurrence (十五, 열다섯).
        self.assertEqual(rules.chinese_number_count("十五个饼和五条鱼", 5), 1)
        self.assertEqual(rules.korean_number_count("열다섯 개와 다섯 마리", 5), 1)
        # A complete Korean number is not the head of a longer one: 20 became 21, 40 became 44.
        for english, wrong, right in (("Twenty people came.", "이십일 명이 왔습니다.", "이십 명이 왔습니다."),
                                      ("Forty people came.", "마흔네 명이 왔습니다.", "마흔 명이 왔습니다."),
                                      ("Twenty people came.", "스물한 명이 왔습니다.", "스무 명이 왔습니다.")):
            with self.subTest(wrong=wrong):
                self.assertTrue(rules.number_problems(english, wrong, "ko"))
                self.assertEqual(rules.number_problems(english, right, "ko"), [])

    def test_digits_the_english_never_said_are_added_numbers(self):
        for locale, target in (("es", "Hay 5 personas."), ("ko", "5명이 있습니다."), ("zh-Hans", "有5个人。")):
            with self.subTest(locale=locale):
                self.assertEqual(rules.added_number_problems("There are people.", target, locale),
                                 ["added number 5"])
                self.assertEqual(rules.added_number_problems("There are five people.", target, locale), [])
        # Said values in other shapes are not additions.
        for english, target, locale in (
                ("Fifty thousand people came.", "5万人来了。", "zh-Hans"),
                ("Fifty thousand people came.", "5만 명이 왔습니다.", "ko"),
                ("Fifty thousand people came.", "Vinieron 50.000 personas.", "es"),
                ("It was 2.5 miles.", "Eran 2,5 millas.", "es"),
                ("In the twenty-first century.", "在21世纪。", "zh-Hans"),
                ("The second time.", "第2次。", "zh-Hans"),
                ("Two million people.", "200万人。", "zh-Hans"),
                ("We meet at half past ten.", "Nos reunimos a las 10:30.", "es"),
                ("Turn to First John 4:8.", "Vayamos a 1 Juan 4:8.", "es"),
                ("Psalm 23 says.", "시편 23편은 말합니다.", "ko"),
                # An article often becomes 1 ("a year", 1년).
                ("For a year he waited.", "그는 1년을 기다렸습니다.", "ko")):
            with self.subTest(english=english, target=target):
                self.assertEqual(rules.added_number_problems(english, target, locale), [])

    def test_numbers_beside_a_citation_must_survive(self):
        english = "John 3:16 mentions three people."
        for locale, bad, good in (
                ("zh-Hans", "约翰福音3:16提到了人。", "约翰福音3章16节提到了三个人。"),
                ("ko", "요한복음 3장 16절은 사람들을 말합니다.", "요한복음 3:16은 세 사람을 말합니다."),
                ("es", "Juan 3:16 menciona a personas.",
                 "Juan capítulo tres versículo dieciséis menciona a tres personas.")):
            with self.subTest(locale=locale):
                self.assertEqual(rules.number_problems(english, bad, locale), ["missing number 3"])
                self.assertEqual(rules.number_problems(english, good, locale), [])
        self.assertEqual(rules.number_problems("Chapter three, verse sixteen has three words.",
                                               "第三章第十六节有字。", "zh-Hans"), ["missing number 3"])

    def test_a_book_bound_verse_keeps_its_book(self):
        english = "As John 3:16 says, God loves the world."
        for locale, bare, named in (("zh-Hans", "正如3:16所说，神爱世人。", "正如约翰福音3:16所说，神爱世人。"),
                                    ("ko", "3장 16절 말씀처럼 하나님은 세상을 사랑하십니다.",
                                     "요한복음 3장 16절 말씀처럼 하나님은 세상을 사랑하십니다."),
                                    ("es", "Como dice 3:16, Dios ama al mundo.", "Como dice Juan 3:16, Dios ama al mundo.")):
            with self.subTest(locale=locale):
                self.assertEqual(rules.scripture_reference_problems(english, bare, locale), ["missing book for 3:16"])
                self.assertEqual(rules.scripture_reference_problems(english, named, locale), [])
        # The book named earlier in the group still identifies the passage.
        self.assertEqual(rules.scripture_reference_problems(english, "在约翰福音中，3:16说神爱世人。", "zh-Hans"), [])

    def test_chinese_one_needs_a_measure_word(self):
        english = "You only have one life; remain faithful."
        self.assertEqual(rules.number_problems(english, "你只有两条生命，但要一直忠心。", "zh-Hans"),
                         ["missing number 1"])
        self.assertEqual(rules.number_problems(english, "你只有一条生命，要一直忠心。", "zh-Hans"), [])
        for text in ("一起祷告", "一样的爱", "一切都好", "一直忠心"):
            self.assertEqual(rules.chinese_number_count(text, 1), 0, text)
        self.assertEqual(rules.chinese_number_count("神是一。", 1), 1)

    def test_terminology_needs_the_complete_term(self):
        policy = {"terminology": {"properNames": [{"source": "Anna", "target": "Ana"},
                                                  {"source": "Paul", "target": "바울"}], "seriesNames": []}}
        self.assertEqual(rules.name_problems(policy, "Anna prayed.", "Mañana oró."), ["Anna: expected Ana"])
        self.assertEqual(rules.name_problems(policy, "Anna prayed.", "Ana oró."), [])
        self.assertEqual(rules.name_problems(policy, "Anna prayed.", "Oró Ána."), [])
        # Korean particles attach to the name.
        self.assertEqual(rules.name_problems(policy, "Paul wrote.", "바울이 썼습니다."), [])
        # A one-character Chinese name inside an ordinary word does not name anyone.
        god = {"terminology": {"properNames": [{"source": "God", "target": "神"}], "seriesNames": []}}
        self.assertEqual(rules.name_problems(god, "God gives us courage.", "我们要振奋精神。"), ["God: expected 神"])
        self.assertEqual(rules.name_problems(god, "God gives us courage.", "神赐给我们精神。"), [])
        self.assertEqual(rules.name_spans("神", "精神来自神。"), [(4, 5)])

    def test_one_word_spanish_copies_are_untranslated(self):
        for english, target in (("Repent.", "Repent."), ("Listen!", "listen"), ("Believe.", "Believe.")):
            with self.subTest(target=target):
                self.assertEqual(rules.untranslated_problems(english, target, "es"),
                                 ["English source text copied into target"])
        # Translations, deliberate Spanish spellings and shared liturgical words stay.
        for english, target in (("Repent.", "Arrepiéntanse."), ("Amen.", "Amén."), ("Amen.", "Amen."),
                                ("Jesus.", "Jesús."), ("Hallelujah!", "Hallelujah!")):
            with self.subTest(target=target):
                self.assertEqual(rules.untranslated_problems(english, target, "es"), [])
        # A glossary name may read the same in both languages.
        policy = {"terminology": {"properNames": [{"source": "David", "target": "David"}], "seriesNames": []}}
        self.assertTrue(rules.untranslated_problems("David.", "David.", "es"))
        self.assertEqual(rules.untranslated_problems("David.", "David.", "es", rules.shared_terms(policy)), [])

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
        self.assertEqual(rules.number_problems("five people", "十五个人", "zh-Hans"),
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
