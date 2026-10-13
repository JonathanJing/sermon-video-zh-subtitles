import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import ko_spoken_numerals as subject

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("text, spoken", [
    ("그래서 요한계시록 8장을 보면 정말 놀랍습니다.", "그래서 요한계시록 팔장을 보면 정말 놀랍습니다."),
    ("요한계시록 8장의 맨 첫 절에 주목하십시오.", "요한계시록 팔장의 맨 첫 절에 주목하십시오."),
    ("요한복음 3장 16절", "요한복음 삼장 십육절"),
    ("시편 23편과 119편", "시편 이십삼편과 백십구편"),
    ("요한복음 3장16-17절", "요한복음 삼장십육-십칠절"),
    ("요한복음 3장부터 4장까지", "요한복음 삼장부터 사장까지"),
    ("창세기 1장 1절에서 3절", "창세기 일장 일절에서 삼절"),
    ("하박국 2 장", "하박국 이 장"),
    ("요한복음 3장16절", "요한복음 삼장십육절"),
])
def test_scripture_numbers_are_spelled_in_sino_korean(text, spoken):
    assert subject.spoken_form(text) == spoken
    assert subject.equivalent(text, spoken)


@pytest.mark.parametrize("text", ["두 사람", "3:16", "3,000장", "1.5장", "2026년", "8명", "1234장", "8장의 맨 첫 절", "16-17절", "2 장", "사진 2장", "영화 2편",
                                  "요한복음 3,000장", "요한복음 1.5장", "요한복음 1234장",
                                  "영화 요한복음 2편"])
def test_other_numbers_are_left_alone(text):
    assert subject.spoken_form(text) == text
    assert not subject.equivalent(text, text)


def test_only_the_rule_may_change_the_words():
    approved = "하박국 2장을 보십시오."
    assert subject.equivalent(approved, "하박국 이 장을, 보십시오")
    assert not subject.equivalent(approved, "하박국 두 장을 보십시오.")
    assert not subject.equivalent(approved, "하박국 이장을 보세요.")


def test_build_lists_only_changed_units_and_binds_the_job(tmp_path):
    job = {"targetLocale": "ko", "units": [
        {"translationGroupId": "g1", "text": "하박국 2장을 보십시오."},
        {"translationGroupId": "g2", "text": "두 사람이 왔습니다."}]}
    document = subject.build(job)
    assert document["schemaVersion"] == "sermon-unit-delivery-instructions-v2"
    assert document["speechJobJsonSha256"] == subject.identity.json_sha256(job)
    assert [(row["translationGroupId"], row["spokenText"]) for row in document["units"]] == [
        ("g1", "하박국 이장을 보십시오.")]
    assert subject.build(dict(job, units=job["units"][1:])) is None
    with pytest.raises(ValueError, match="Korean"):
        subject.build(dict(job, targetLocale="es"))

    job_path, out = tmp_path / "job.json", tmp_path / "instructions.json"
    job_path.write_text(json.dumps(job, ensure_ascii=False))
    command = [sys.executable, str(ROOT / "scripts/ko_spoken_numerals.py"), "--job", str(job_path), "--out", str(out)]
    assert json.loads(subprocess.run(command, check=True, capture_output=True, text=True).stdout)["units"] == 1
    assert json.loads(out.read_text()) == document
    assert subprocess.run(command, capture_output=True, text=True).returncode != 0


def test_context_does_not_leak_from_a_citation_to_an_ordinary_counter():
    text = "요한복음 3장16절을 읽고 사진 2장과 영화 2편을 봅니다."
    assert subject.spoken_form(text) == "요한복음 삼장십육절을 읽고 사진 2장과 영화 2편을 봅니다."
    assert subject.spoken_form("새요한복음 3장") == "새요한복음 3장"


@pytest.mark.parametrize("symbol", ["%", "+", "$", "₩", "/", "=", "°", "&", "#", ":", "-", "~", "–"])
def test_audible_symbols_cannot_be_dropped_or_changed(symbol):
    approved = f"요한복음 3장과 50{symbol}를 읽습니다."
    spoken = subject.spoken_form(approved)
    assert subject.equivalent(approved, spoken)
    assert not subject.equivalent(approved, spoken.replace(symbol, ""))
    assert not subject.equivalent(approved, spoken.replace(symbol, "*"))


@pytest.mark.parametrize("number", ["1.5", "1,500", "1 . 5", "1，500", "1٫5"])
def test_numeric_separators_cannot_be_removed_or_replaced(number):
    approved = f"요한복음 3장과 {number}를 읽습니다."
    spoken = subject.spoken_form(approved)
    assert subject.equivalent(approved, spoken)
    separator = next(char for char in number if not char.isdigit() and not char.isspace())
    assert not subject.equivalent(approved, spoken.replace(separator, ""))
    assert not subject.equivalent(approved, spoken.replace(separator, ":"))


@pytest.mark.parametrize("text, spoken", [
    ("사진 2장부터 4장까지", "사진 2장부터 4장까지"),
    ("영화 2편에서 3편까지", "영화 2편에서 3편까지"),
    ("요한복음 3장부터 읽고 사진 4장까지 봅니다.", "요한복음 삼장부터 읽고 사진 4장까지 봅니다."),
    ("창세기 1장 1절에서 배운 뒤 3절을 읽습니다.", "창세기 일장 일절에서 배운 뒤 3절을 읽습니다."),
])
def test_range_particles_do_not_expand_book_anchored_scope(text, spoken):
    assert subject.spoken_form(text) == spoken


@pytest.mark.parametrize("dash", ["-", "~", "–"])
@pytest.mark.parametrize("start, end", [(3, 4), (16, 27), (3, 17), (16, 3)])
@pytest.mark.parametrize("template", ["요한복음 {start}{dash}{end}장", "요한복음 {start}장{dash}{end}장", "창세기 1장{start}절{dash}{end}절", "창세기 1장 {start}{dash}{end}절"])
def test_citation_ranges_generate_fold_and_score(template, start, end, dash):
    from scripts import screen_target_language_audio_units as screen
    approved = template.format(start=start, end=end, dash=dash)
    spoken = subject.spoken_form(approved)
    assert spoken != approved
    assert not any(char.isdigit() for char in spoken)
    assert screen.fold_transcript(spoken, "ko") == approved
    assert screen.score(approved, spoken, "ko", 0.88)[2]
    wrong = spoken.replace(subject.korean_sino(end), subject.korean_sino(end + 1))
    assert not screen.score(approved, wrong, "ko", 0.88)[2]


@pytest.mark.parametrize("connector", ["부터", "에서"])
@pytest.mark.parametrize("start, end", [(3, 4), (16, 27)])
def test_particle_ranges_generate_fold_and_score(connector, start, end):
    from scripts import screen_target_language_audio_units as screen
    approved = f"창세기 1장 {start}절{connector} {end}절까지"
    spoken = subject.spoken_form(approved)
    assert screen.fold_transcript(spoken, "ko") == approved
    assert screen.score(approved, spoken, "ko", 0.88)[2]
    assert not screen.score(approved, spoken.replace(subject.korean_sino(end), subject.korean_sino(end + 1)), "ko", 0.88)[2]


def test_range_folding_keeps_legacy_scoring_and_non_citations():
    from scripts import screen_target_language_audio_units as screen
    approved = "요한복음 3-4장"
    spoken = subject.spoken_form(approved)
    assert not screen.score(approved, spoken, "ko", 0.88, screen.SCORING_V4)[2]
    assert not screen.score(approved, spoken, "ko", 0.88, screen.SCORING_V3)[2]
    assert screen.fold_transcript("삼-사장", "ko") == "삼-4장"
    for text in ["사진 2장-4장", "영화 2편~3편", "요한복음 3장 읽고 사진 2장-4장"]:
        expected = text.replace("요한복음 3장", "요한복음 삼장")
        assert subject.spoken_form(text) == expected
    assert not screen.score(approved, "요한복음 세-네장", "ko", 0.88)[2]


@pytest.mark.parametrize("approved", [
    "요한복음 3장16절", "요한복음3장16절", "요한복음 3장 16절",
    "요한복음 3장16-17절", "요한복음3장16절~27절",
    "시편 1-2편", "시편1편–2편", "시편 16편부터 27편까지",
])
def test_adjacent_and_psalm_citations_generate_fold_and_score(approved):
    from scripts import screen_target_language_audio_units as screen
    spoken = subject.spoken_form(approved)
    assert spoken != approved
    assert not any(char.isdigit() for char in spoken)
    assert screen.fold_transcript(spoken, "ko") == approved
    assert screen.score(approved, spoken, "ko", 0.88)[2]
    # Deliberately change every endpoint, never relax protected-number checks.
    for numeral in ["삼", "십육", "십칠", "일", "이", "이십칠"]:
        if numeral in spoken:
            assert not screen.score(approved, spoken.replace(numeral, "구십구"), "ko", 0.88)[2]
