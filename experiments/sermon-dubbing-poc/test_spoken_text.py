"""Pronunciation output contracts; no audio or model calls."""
import unittest

from spoken_text import LEGACY_VERSION, NUMBER_VERSION, VERSION, spoken_text


class SpokenTextVersionTests(unittest.TestCase):
    def test_v2_reads_supported_grouped_integers_as_one_number(self):
        cases = {
            "5,300英尺": "五千三百英尺",
            "3,000英尺": "三千英尺",
            "9,999名": "九千九百九十九名",
            "1,001名": "一千零一名",
            "1,010名": "一千零一十名",
            "5300英尺": "五千三百英尺",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(spoken_text(source, version=VERSION), expected)
                self.assertEqual(spoken_text(source), expected)

    def test_v2_preserves_unsupported_number_tokens_without_partial_conversion(self):
        cases = [
            "10,000名", "1,000,000名", "10000名", "100000名",
            "1,2,3", "12,34英尺", "05,300英尺", "5,,300英尺", "5,300,00英尺",
            "5,300.50美元", "3.14", ".5", "版本1.2.3",
            "A5,300", "5,300A", "A123", "A_5,300", "５300英尺",
        ]
        for source in cases:
            with self.subTest(source=source):
                self.assertEqual(spoken_text(source, version=VERSION), source)

    def test_v2_keeps_supported_year_integer_and_divine_pronoun_forms(self):
        self.assertEqual(
            spoken_text("2025年，600名学生读诗篇137篇，向祢祷告，信靠祂。"),
            "二零二五年，六百名学生读诗篇一百三十七篇，向你祷告，信靠他。",
        )

    def test_v1_reproduces_frozen_outputs_including_historical_number_errors(self):
        cases = {
            "5,300英尺": "五,三百英尺",
            "3,000英尺": "三,零英尺",
            "9,999名": "九,九百九十九名",
            "10,000名": "十,零名",
            "1,000,000名": "一,零,零名",
            "1,2,3": "一,二,三",
            "5,300.50美元": "五,300.50美元",
            "A5,300": "A5,三百",
            "2025年": "二零二五年",
            "3.14 与 A123": "3.14 与 A123",
            "祢与祂": "你与他",
            "5300英尺": "五千三百英尺",
            "５300英尺": "五千三百英尺",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(spoken_text(source, version=LEGACY_VERSION), expected)

    def test_unknown_or_missing_explicit_rule_version_is_rejected(self):
        for version in ["unknown", "chinese-sermon-pronunciation-v4", None, [], True]:
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, "Unsupported pronunciation"):
                spoken_text("5,300英尺", version=version)

    def test_cuv_bracket_words_are_spoken_and_old_versions_remain_frozen(self):
        source = "当主日，我被[圣]灵感动。以后[永]在。"
        self.assertEqual(spoken_text(source), "当主日，我被圣灵感动。以后永在。")
        for version in (LEGACY_VERSION, NUMBER_VERSION):
            self.assertEqual(spoken_text(source, version=version), source)


if __name__ == "__main__":
    unittest.main()
