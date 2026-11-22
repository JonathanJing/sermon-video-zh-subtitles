"""Chinese years are read digit by digit in TTS spoken forms (1980 -> 一九八零年)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "experiments" / "sentence-first-agent"))

import spoken_forms as S  # noqa: E402


def test_year_with_nian_is_digit_by_digit():
    assert S.forms_for_text("然后在 1980 年，世界卫生组织宣布。", "zh-Hans") == {"1980 年": "一九八零年"}
    assert S.forms_for_text("他在 2024 年从公羊队退役。", "zh-Hans") == {"2024 年": "二零二四年"}


def test_years_inside_longer_sentence_keep_other_patterns():
    forms = S.forms_for_text("2024 年他读启示录 20 章 15 节，第 146 页。", "zh-Hans")
    assert forms["2024 年"] == "二零二四年"
    assert forms["20 章 15 节"] == "二十章十五节"
    assert forms["第 146 页"] == "第一百四十六页"


def test_non_year_numbers_still_use_the_cardinal_reader():
    forms = S.forms_for_text("我们收到了 25% 的奉献。", "zh-Hans")
    assert forms["25"] == "二十五"  # the percent sign itself is left to the TTS phonemizer


def test_other_locales_keep_their_year_reading():
    assert S.forms_for_text("그러다 천구백팔십년에", "ko") == {}
    assert S.forms_for_text("1980년에", "ko")["1980"] == "천구백팔십"
    assert S.forms_for_text("en 1980", "es")["1980"] == "mil novecientos ochenta"
