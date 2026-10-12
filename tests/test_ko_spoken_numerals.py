import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import ko_spoken_numerals as subject

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("text, spoken", [
    ("그래서 8장을 보면 정말 놀랍습니다.", "그래서 팔장을 보면 정말 놀랍습니다."),
    ("8장의 맨 첫 절에 주목하십시오.", "팔장의 맨 첫 절에 주목하십시오."),
    ("요한복음 3장 16절", "요한복음 삼장 십육절"),
    ("시편 23편과 119편", "시편 이십삼편과 백십구편"),
    ("16-17절", "십육-십칠절"),
    ("2 장", "이 장"),
])
def test_scripture_numbers_are_spelled_in_sino_korean(text, spoken):
    assert subject.spoken_form(text) == spoken
    assert subject.equivalent(text, spoken)


@pytest.mark.parametrize("text", ["두 사람", "3:16", "3,000장", "1.5장", "2026년", "8명", "1234장"])
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
