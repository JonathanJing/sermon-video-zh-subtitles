"""Reading-equivalent folding in the ASR screener, fixed against the 2026-10-11 run.

The fixture under tests/fixtures/weekly-20261011/audio-qc holds the 42 units the
audio QC failed that week and the 101 units the Qwen3-ASR screening flagged, each
with the expected text and what the ASR heard. Folding spellings a listener cannot
tell apart must clear the number/homophone/accent flags and keep every material
difference, so the remaining sets are asserted exactly.
"""
import hashlib
import json
import unittest
from pathlib import Path

from scripts import screen_target_language_audio_units as subject

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "weekly-20261011" / "audio-qc"
THRESHOLD = 0.88


def passes(expected: str, heard: str, locale: str) -> bool:
    return subject.score(expected, heard, locale, THRESHOLD)[2]


class FoldTranscriptTests(unittest.TestCase):
    def test_numbers_fold_to_digits_by_value(self):
        cases = {
            ("zh-Hans", "你算一算就会发现，地球上会有27亿人丧生。"): "2700000000人",
            ("zh-Hans", "地球上会有二十七亿人丧生。"): "2700000000人",
            ("zh-Hans", "可以看看第八十一页上方的表格"): "第81页",
            ("zh-Hans", "两千零二十六年，一亿两千万人"): "2026年,120000000人",
            ("ko", "땅의 약 삼분의 일과"): "3분의 1과",
            ("ko", "삼 분의 일을 정복합니다"): "3분의 1을",
            ("ko", "여러분은 일 년 전이나"): "1 년 전이나",
            ("ko", "요한계시록 8장과 구 장에서"): "8장과 9 장에서",
            ("ko", "2억 명으로 이루어진 군대"): "200000000 명으로",
            ("ko", "초등학교 이학년 때"): "2학년",
            ("ko", "나팔 일곱 개가, 스무 살, 열다섯 명, 네 번째"): "7 개가, 20살, 15 명, 4 번째",
            ("es", "orar por mí durante diez años"): "10 años",
            ("es", "un ejército de doscientos millones"): "1 ejército de 200000000",
            ("es", "treinta y uno días, veintiún días, mil gracias"): "31 días, 21 días, 1000 gracias",
            ("es", "no el 99% de sus pecados, sino el cien por ciento"): "99 por 100 de sus pecados, sino el 100 por 100",
        }
        for (locale, text), fragment in cases.items():
            with self.subTest(text=text):
                self.assertIn(fragment, subject.fold_transcript(text, locale))

    def test_words_that_merely_contain_numerals_stay_words(self):
        cases = [("ko", "그 천사들에게", "천사"), ("ko", "사람이 많군요", "사람이"), ("ko", "수십 년 전에", "수십"),
                 ("ko", "그 한 가지 일, 그 실수", "일,"), ("zh-Hans", "领受圣餐的合一方式", "合一"),
                 ("zh-Hans", "一直一样一起", "一直一样一起"), ("es", "Y en ese momento", "Y en ese")]
        for locale, text, kept in cases:
            with self.subTest(text=text):
                self.assertIn(kept, subject.fold_transcript(text, locale))

    def test_korean_native_numeral_before_sino_counter_is_not_folded(self):
        # 8장 is read 팔장; 여덟 장 is a misread chapter and must stay as heard.
        self.assertEqual(subject.fold_transcript("요한계시록 여덟 장", "ko"), "요한계시록 여덟 장")
        self.assertEqual(subject.fold_transcript("누가복음 열 다섯 장", "ko"), "누가복음 열 다섯 장")
        self.assertEqual(subject.fold_transcript("하박국 두 장을", "ko"), "하박국 두 장을")
        self.assertFalse(passes("요한계시록 8장은 저를 초대합니다. 다시 기도하도록 초대합니다.",
                                "요한계시록 여덟 장은 저를 초대합니다. 다시 기도하도록 초대합니다.", "ko"))

    def test_chinese_homophones_fold_only_with_the_same_tone(self):
        self.assertTrue(passes("一共有七支号角。", "一共有七只号角。", "zh-Hans"))
        self.assertTrue(passes("而正是因为神有慈爱，祂也有忿怒。", "而正是因为神有慈爱，他也有愤怒。", "zh-Hans"))
        self.assertTrue(passes("你们作出了回应。", "你们做出了回应。", "zh-Hans"))
        # 义 (yì) and 宜 (yí) differ from 一 (yī) in tone: a listener hears the change.
        self.assertFalse(passes("他牺牲了自己的生命，为要使你我在他里面成为义人。",
                                "他牺牲了自己的生命，为要使你我在他里面成为一人。", "zh-Hans"))
        self.assertFalse(passes("所以，今晚我们领受圣餐的合宜方式", "所以今晚我们领受圣餐的合一方式。", "zh-Hans"))

    def test_spanish_accents_and_spelled_numbers_fold(self):
        self.assertTrue(passes("Por ejemplo, él no toma agua; se hidrata.", "Por ejemplo, el no toma agua se hidrata.", "es"))
        self.assertTrue(passes("Lleva décadas como pastor en 1 iglesia, y todos los que lo conocen dan fe de su integridad.",
                               "Lleva décadas como pastor en una iglesia y todos los que lo conocen dan fe de su integridad.", "es"))
        self.assertTrue(passes("Ella elevó sus oraciones ante la presencia de Dios durante 10 años.",
                               "ella elevó sus oraciones ante la presencia de Dios durante diez años", "es"))
        self.assertFalse(passes("Si aún no nos conocemos, mi nombre es Steve Bang Lee.",
                                "Si aún no nos conocemos, mi nombre es Steve Bangley.", "es"))
        self.assertFalse(passes("Es su megáfono para despertar a un mundo sordo.",
                                "Es un megáfono para despertar a un mundo sordo.", "es"))

    def test_punctuation_does_not_change_protected_numeral_matching(self):
        expected = "여러분은 일 년 전이나 수십 년 전에 저질러서 후회하는 그 한 가지 일, 그 한 가지 죄, 그 실수를 계속 생각해 왔습니다."
        heard = "여러분은 1년 전이나 수십 년 전에 저질러서 후회하는 그 한 가지 일 그 한 가지 죄 그 실수를 계속 생각해 왔습니다."
        self.assertTrue(passes(expected, heard, "ko"))

    def test_existing_protections_survive_folding(self):
        self.assertFalse(passes("그 집에는 두 아들과 세 딸이 함께 살고 있었습니다.",
                                "그 집에는 세 아들과 두 딸이 함께 살고 있었습니다.", "ko"))
        self.assertFalse(passes("Solo tienes una vida y debes permanecer fiel cada día.",
                                "Solo tienes vida y debes permanecer fiel cada día.", "es"))
        self.assertFalse(passes("今天我们看见教会门口有十二个人一直在等待牧师走出来。",
                                "今天我们看见教会门口有十个人一直在等待牧师走出来。", "zh-Hans"))
        self.assertIn("token-sequence-ratio-v4", subject.SCORING)


class ReviewCounterexampleTests(unittest.TestCase):
    """Each review finding on PR 342: a fold must never merge readings a listener can tell apart."""

    def distinct(self, locale, left, right):
        self.assertNotEqual(subject.fold_transcript(left, locale), subject.fold_transcript(right, locale), (left, right))

    def same(self, locale, left, right):
        self.assertEqual(subject.fold_transcript(left, locale), subject.fold_transcript(right, locale), (left, right))

    def test_spanish_scales_nest_by_multiplication(self):
        self.distinct("es", "dos mil millones", "un millón dos mil")
        self.assertEqual(subject.fold_transcript("dos mil millones de personas", "es"), "2000000000 de personas")
        self.assertEqual(subject.fold_transcript("un millón dos mil", "es"), "1002000")
        self.assertEqual(subject.fold_transcript("mil millones", "es"), "1000000000")
        self.assertEqual(subject.fold_transcript("ciento veinte mil", "es"), "120000")
        self.assertEqual(subject.fold_transcript("doscientos millones", "es"), "200000000")
        self.same("es", "doscientos millones", "200 millones")
        self.same("es", "treinta y uno años", "31 años")
        self.assertEqual(subject.fold_transcript("veintiún días y", "es"), "21 días y")  # a dangling y stays text

    def test_spanish_stress_accents_stay_but_diacritic_pairs_fold(self):
        self.distinct("es", "practicó", "práctico")
        self.distinct("es", "está", "esta")
        self.distinct("es", "papá", "papa")
        self.same("es", "él", "el")
        self.same("es", "aún", "aun")
        self.same("es", "qué", "que")
        self.assertEqual(subject.fold_transcript("él sí sabe, más aún", "es"), "el si sabe, mas aun")
        # In a long unit one differing word still scores under the threshold, but it is reported
        # as a difference instead of folding into a perfect match.
        similarity, differences, _ = subject.score("Ya practicó mucho esta semana con todos los hermanos de la iglesia.",
                                                  "Ya práctico mucho esta semana con todos los hermanos de la iglesia.", "es", 0.88)
        self.assertLess(similarity, 1.0)
        self.assertEqual(differences, [{"kind": "replace", "expected": ["practicó"], "recognized": ["práctico"]}])

    def test_chinese_polyphones_fold_only_in_their_context(self):
        for text in ("土地", "得到", "只是", "地球", "作坊"):
            self.assertEqual(subject.fold_transcript(text, "zh-Hans"), text, text)
        self.distinct("zh-Hans", "土地得到", "土的的到")
        self.distinct("zh-Hans", "只是", "支是")
        self.same("zh-Hans", "七只号角", "七支号角")      # measure word after a numeral
        self.same("zh-Hans", "作出回应", "做出回应")
        self.same("zh-Hans", "祂也有忿怒", "他也有愤怒")
        self.same("zh-Hans", "再来", "在来")

    def test_chinese_big_units_nest_and_must_descend(self):
        self.assertEqual(subject.fold_transcript("一万亿", "zh-Hans"), "1000000000000")
        self.assertEqual(subject.fold_transcript("一亿一万", "zh-Hans"), "100010000")
        self.distinct("zh-Hans", "一万亿", "一亿一万")
        self.assertEqual(subject.fold_transcript("三千万亿", "zh-Hans"), "3000000000000000")
        for invalid in ("万一", "一万一亿", "万"):
            self.assertEqual(subject.fold_transcript(invalid, "zh-Hans"), invalid, invalid)

    def test_digit_strings_never_equal_positional_numerals(self):
        self.distinct("zh-Hans", "十一", "一一")
        self.distinct("zh-Hans", "十二月", "一二月")
        self.distinct("ko", "십일 년", "일일 년")
        self.distinct("ko", "십이 년", "일이 년")
        self.assertEqual(subject.fold_transcript("십일 년", "ko"), "11 년")
        self.assertEqual(subject.fold_transcript("일일 년", "ko"), "일일 년")
        # A spoken year is the one digit-by-digit reading that is folded.
        self.same("zh-Hans", "二〇二六年", "2026年")
        self.assertEqual(subject.fold_transcript("二〇二六", "zh-Hans"), "二〇二六")
        self.assertFalse(passes("今年是十一周年纪念，我们要一起感谢神的恩典。", "今年是一一周年纪念，我们要一起感谢神的恩典。", "zh-Hans"))

    def test_common_measure_words_fold_lone_numerals(self):
        for left, right in (("教会里有1名牧师", "教会里有一名牧师"), ("读了3本书", "读了三本书"),
                            ("说了1句话", "说了一句话"), ("1位弟兄", "一位弟兄")):
            self.same("zh-Hans", left, right)
        self.assertTrue(passes("教会里有1名牧师一直忠心服事", "教会里有一名牧师一直忠心服事", "zh-Hans"))
        self.assertEqual(subject.fold_transcript("一直一样一起", "zh-Hans"), "一直一样一起")

    def test_a_receipt_is_rescored_by_the_scoring_identity_it_recorded(self):
        expected, heard = "我们读了第八十一页的内容，谢谢大家的参与和支持。", "我们读了第81页的内容，谢谢大家的参与和支持。"
        v3 = subject.score(expected, heard, "zh-Hans", 0.88, subject.SCORING_V3)
        v4 = subject.score(expected, heard, "zh-Hans", 0.88)
        self.assertEqual(v4[0], 1.0)
        self.assertLess(v3[0], 1.0)  # unfolded: the number spelling counts as a difference
        self.assertFalse(v3[2])
        self.assertTrue(v4[2])
        self.assertEqual(subject.score(expected, heard, "zh-Hans", 0.88, subject.SCORING), v4)
        with self.assertRaisesRegex(ValueError, "Unknown ASR scoring identity"):
            subject.score(expected, heard, "zh-Hans", 0.88, "token-sequence-ratio-v9")

    def test_release_basis_rescoring_follows_the_receipt(self):
        from scripts import machine_quality_release_basis as basis
        text = "我们读了第八十一页的内容，谢谢大家的参与和支持。"
        heard = "我们读了第81页的内容，谢谢大家的参与和支持。"
        candidate = {"groups": [{"translationGroupId": "g1", "targetText": text}]}

        def receipt(scoring):
            similarity, differences, passed = subject.score(text, heard, "zh-Hans", 0.88, scoring)
            return {"targetLocale": "zh-Hans", "minSimilarity": 0.88, "asrSettings": {"scoring": scoring},
                    "results": [{"textGroupId": "g1", "targetTextSha256": hashlib.sha256(text.encode()).hexdigest(),
                                 "recognized": heard, "similarity": similarity, "differences": differences,
                                 "status": "pass" if passed else "requires_review"}]}
        for scoring in (subject.SCORING_V3, subject.SCORING):
            self.assertEqual(basis.screening_score_problems(receipt(scoring), candidate), [], scoring)
        # A v3 receipt cannot be passed off as v4, nor the reverse.
        mislabeled = receipt(subject.SCORING_V3)
        mislabeled["asrSettings"]["scoring"] = subject.SCORING
        self.assertEqual(len(basis.screening_score_problems(mislabeled, candidate)), 1)
        unknown = receipt(subject.SCORING)
        unknown["asrSettings"]["scoring"] = "token-sequence-ratio-v9"
        self.assertEqual(basis.screening_score_problems(unknown, candidate),
                         ["screening was scored under an unknown scoring identity"])
        # Without a recorded identity the receipt predates folding.
        legacy = receipt(subject.SCORING_V3)
        legacy.pop("asrSettings")
        self.assertEqual(basis.screening_score_problems(legacy, candidate), [])


class Weekly20261011FixtureTests(unittest.TestCase):
    """The run's real flags: what folding clears and what it must keep."""

    STILL_FAILING = {
        "zh-Hans": {"translation-chunk-0010-u009", "translation-chunk-0011-u009"},  # 义/一, 宜/一
        "ko": {"translation-chunk-0000-u008", "translation-chunk-0000-u015", "translation-chunk-0001-u006",
               "translation-chunk-0001-u039", "translation-chunk-0002-u020", "translation-chunk-0002-u023",
               "translation-chunk-0003-u002", "translation-chunk-0005-u007", "translation-chunk-0005-u016",
               "translation-chunk-0005-u027", "translation-chunk-0006-u014", "translation-chunk-0006-u039",
               "translation-chunk-0008-u026", "translation-chunk-0009-u021"},
        "es": {"translation-chunk-0000-u002", "translation-chunk-0000-u022", "translation-chunk-0003-u003",
               "translation-chunk-0003-u005", "translation-chunk-0003-u008", "translation-chunk-0003-u009"},
    }
    # Five misread Korean chapter numbers and 참혹합니다 must never be folded away.
    MUST_KEEP = {"translation-chunk-0001-u039", "translation-chunk-0005-u007", "translation-chunk-0005-u016",
                 "translation-chunk-0008-u026", "translation-chunk-0009-u021", "translation-chunk-0002-u023"}
    STILL_FLAGGED = {"zh-Hans": 10, "ko": 31, "es": 27}

    def test_failed_units_keep_exactly_the_material_differences(self):
        failed = json.loads((FIXTURES / "failed-units.json").read_text(encoding="utf-8"))
        self.assertEqual(failed["counts"], {"zh-Hans": 11, "ko": 19, "es": 12})
        for locale, rows in failed["rows"].items():
            still = {row["groupId"] for row in rows
                     if not passes(row["targetText"], row["asrPrimaryRecognized"], locale)}
            self.assertEqual(still, self.STILL_FAILING[locale], locale)
        self.assertTrue(self.MUST_KEEP <= self.STILL_FAILING["ko"])
        self.assertEqual(sum(map(len, self.STILL_FAILING.values())), 22)

    def test_screening_flags_drop_to_the_measured_counts(self):
        flags = json.loads((FIXTURES / "screening-flags.json").read_text(encoding="utf-8"))
        for locale, block in flags["locales"].items():
            still = [row["textGroupId"] for row in block["flagged"]
                     if not passes(row["targetText"], row["recognized"], locale)]
            self.assertEqual(len(still), self.STILL_FLAGGED[locale], (locale, still))
            self.assertEqual(block["counts"]["requires_review"], len(block["flagged"]))


if __name__ == "__main__":
    unittest.main()
