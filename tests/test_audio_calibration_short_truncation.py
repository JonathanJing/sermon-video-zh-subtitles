"""Very short Chinese sentences get no truncation trial; other kinds and locales are unchanged."""
from scripts import auto_qc_seeded_errors as seeded
from tests import auto_qc_fixtures as fixtures


def units(texts):
    return [{"groupId": f"g{index}", "text": text, "sourceSeconds": 20, "wav": fixtures.speech_wav(1)}
            for index, text in enumerate(texts)]


LONG_ZH = "这在两个方面都令人惊叹了"   # 12 Han characters
SHORT_ZH = ["第一，是通过静默。", "静默。"]  # 7 and 2


def test_short_chinese_sentences_are_excluded_from_truncation_trials_only():
    rows = units([LONG_ZH] * 5 + SHORT_ZH)
    kinds = seeded.calibrate_audio(rows, "zh-Hans")["kinds"]
    assert kinds["truncated"]["trials"] == 5
    assert kinds["truncated"]["excludedShortGroupIds"] == ["g5", "g6"]
    for kind in ("stretched", "silent", "clipped"):
        assert kinds[kind]["trials"] == 7 and "excludedShortGroupIds" not in kinds[kind]


def test_other_locales_keep_truncation_trials_on_every_sentence():
    rows = units(["가" * 10] * 5 + ["침묵입니다.", "네."])
    kinds = seeded.calibrate_audio(rows, "ko")["kinds"]
    assert kinds["truncated"]["trials"] == 7 and "excludedShortGroupIds" not in kinds["truncated"]
