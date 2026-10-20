"""Frozen v2 resumes unchanged; v3 bare chapters exclude quantities/numeric tokens."""
import json

import pytest

from scripts import ko_spoken_numerals as ko
from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.audio import renderer as formal
from tongxing_production.audio import predicted_schedule as predicted
from tongxing_production.review import audio_qc as qc


@pytest.mark.parametrize("locale", ["ko", "es", "zh-Hans"])
@pytest.mark.parametrize("policy", formal.REGISTERED_NORMALIZATION_POLICIES)
def test_frozen_registered_policies_validate_and_dispatch_without_migration(locale, policy):
    policies = {"normalization": policy, "asrScreening": {"policy": "screen_all"}, "subtitle": {"policy": "full"}}
    fields = {"normalization": "normalizationPolicySha256", "asrScreening": "asrScreeningPolicySha256",
              "subtitle": "subtitlePolicySha256"}
    adapter = {field: formal.identity.json_sha256(policies[name]) for name, field in fields.items()}
    job = {"targetLocale": locale, "adapter": adapter,
           "units": [{"translationGroupId": "g1", "text": "하박국 2장을 읽고 8장의 맨 첫 절"}]}
    before = json.dumps(job, sort_keys=True)
    formal.validate_operation_policies(policies, adapter, job)
    forms = formal.policy_spoken_forms(job)
    if locale == "ko":
        expected = "하박국 이장을 읽고 8장의 맨 첫 절" if policy == formal.FROZEN_V2_NORMALIZATION_POLICY else "하박국 이장을 읽고 팔장의 맨 첫 절"
        assert forms == {"g1": expected}
        assert predicted.policy_texts([job["units"][0]["text"]], locale, adapter["normalizationPolicySha256"]) == [expected]
    else:
        assert forms == {}
    assert qc.duration_binding_problems({"durationNormalization": qc.duration_normalization_binding(job)}, job) == []
    assert qc.duration_binding_problems({}, job)  # old registered forms never become unbound raw QC
    assert json.dumps(job, sort_keys=True) == before


def test_frozen_v2_hash_and_explicit_instruction_export_retain_original_rule(tmp_path):
    assert formal.identity.json_sha256(formal.FROZEN_V2_NORMALIZATION_POLICY) == "5c8e7ac6d14f8c5968b2a8d146d8d35eb9a9fa430317c413df71e3f4a402d744"
    text = "하박국 2장을 읽고 8장의 맨 첫 절"
    job = {"targetLocale": "ko", "adapter": {"normalizationPolicySha256": formal.identity.json_sha256(formal.FROZEN_V2_NORMALIZATION_POLICY)},
           "units": [{"translationGroupId": "g1", "text": text}]}
    document = ko.build(job)
    assert ko.RULE_V2 in document["units"][0]["operatorEvidence"]
    path = tmp_path / "instructions.json"
    path.write_text(json.dumps(document))
    assert formal.unit_instructions(job, path) == {"g1": {"spokenText": "하박국 이장을 읽고 8장의 맨 첫 절"}}
    document["units"][0]["spokenText"] = ko.spoken_form(text)
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="Spoken form changes|differs from"):
        formal.unit_instructions(job, path)


@pytest.mark.parametrize("noun", ko._COUNTED_NOUNS)
@pytest.mark.parametrize("particle", ["은", "는", "이", "가", "을", "를", "도", "만", "의", "에서", "에는", "에도", "으로", "로"])
def test_noun_particles_preserve_whole_counted_chain(noun, particle):
    for suffix in [" 2장", "3장부터 4장까지", " (2-3장)", " 2장과 3장"]:
        text = noun + particle + suffix
        assert ko.spoken_form(text) == text
    assert ko.spoken_form(noun + particle + " 2장. 8장을 보세요.").endswith("팔장을 보세요.")


@pytest.mark.parametrize("token", ["1 . 5장", "3, 000장", "3: 16절", "1 .5장", "3 ,000장", "3 : 16절", "3 ， 000장", "1 ． 5장"])
def test_complete_numeric_token_with_spaces_is_not_a_bare_chapter(token):
    assert ko.spoken_form(token) == token
    assert ko.spoken_form("본문 " + token + "부터 7장까지") == "본문 " + token + "부터 7장까지"
    assert ko.spoken_form(token + ". 8장을 보세요.") == token + ". 팔장을 보세요."


@pytest.mark.parametrize("expression", ["1/2", "1 / 2", "3／4", "3⁄4", "3∕4", "1+2", "1 + 2", "2*3",
                                      "2＊3", "2×3", "6÷3", "1+2=3", "2^3", "7%3", "7％3", "5−2", "+2", "-2", "−2"])
@pytest.mark.parametrize("counter", ["장", "절"])
def test_fractions_and_operator_quantities_keep_complete_numeric_expression(expression, counter):
    text = expression + counter
    assert ko.spoken_form(text) == text
    assert ko.spoken_form(text + "부터 7장까지") == text + "부터 7장까지"
    assert ko.spoken_form("사진은 " + text) == "사진은 " + text
    assert ko.spoken_form(text + ". 8장을 보세요.") == text + ". 팔장을 보세요."


@pytest.mark.parametrize("text, spoken", [("2장", "이장"), ("(2절)", "(이절)"), ("3-4장", "삼-사장"),
                                          ("3 - 4장", "삼 - 사장"), ("3~4절", "삼~사절"), ("3–4장", "삼–사장")])
def test_numeric_guard_retains_ordinary_bare_chapter_and_range_readings(text, spoken):
    assert ko.spoken_form(text) == spoken


@pytest.mark.parametrize("noun", ["서류", "문서", "복사본", "봉투", "스티커", "인쇄물", "서류는", "문서가", "봉투를"])
def test_arbitrary_noun_counter_is_conservative_and_not_admitted_as_sino(tmp_path, noun):
    text = noun + " 2장부터 4장까지"
    assert ko.spoken_form(text) == text
    assert ko.spoken_form(noun + " (2-3장)") == noun + " (2-3장)"
    job = {"targetLocale": "ko", "adapter": {"normalizationPolicySha256": formal.identity.json_sha256(formal.SPOKEN_FORMS_NORMALIZATION_POLICY)},
           "units": [{"translationGroupId": "g1", "text": text}]}
    assert formal.policy_spoken_forms(job) == {}
    assert ko.build(job) is None
    assert formal.unit_instructions(job, None) == {}
    document = {"schemaVersion": ko.INSTRUCTIONS_SCHEMA, "targetLocale": "ko", "speechJobJsonSha256": ko.identity.json_sha256(job),
                "units": [{"translationGroupId": "g1", "approvedTextSha256": ko.hashlib.sha256(text.encode()).hexdigest(),
                           "operatorEvidence": "test", "spokenText": noun + " 이장부터 사장까지"}]}
    path = tmp_path / "bad-instructions.json"
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="Spoken form changes"):
        formal.unit_instructions(job, path)


@pytest.mark.parametrize("text,spoken", [("그래서 8장을 보면 정말 놀랍습니다.", "그래서 팔장을 보면 정말 놀랍습니다."),
                                          ("8장의 맨 첫 절", "팔장의 맨 첫 절"), ("(3-4장)", "(삼-사장)"),
                                          ("이제 3장부터4장까지", "이제 삼장부터사장까지"),
                                          ("그렇기 때문에 8장을 보면 참으로 놀랍습니다.", "그렇기 때문에 팔장을 보면 참으로 놀랍습니다."),
                                          ("따라서 3장 16절을 보십시오.", "따라서 삼장 십육절을 보십시오."),
                                          ("본문은 8장입니다.", "본문은 팔장입니다."),
                                          ("하지만 다시 2장으로 돌아가 봅시다.", "하지만 다시 이장으로 돌아가 봅시다."),
                                          ("따라서, 3장을 보십시오.", "따라서, 삼장을 보십시오.")])
def test_explicit_bare_chapter_contexts_still_generate_and_screen(text, spoken):
    from tongxing_production.audio import screening as screen
    assert ko.spoken_form(text) == spoken
    assert ko.equivalent(text, spoken)
    assert screen.score(text, spoken, "ko", .88)[2]


@pytest.mark.parametrize("expected,wrong", [("12-3장", "1-23장"), ("1-23절", "12-3절"), ("3-4장", "34장"),
                                          ("34장", "3-4장"), ("3-4장", "4-3장"), ("3장과4장", "3장이나4장"),
                                          ("3장부터4장까지", "3장4장까지"), ("3장4장", "3장-4장"),
                                          ("3장4절", "3절4장")])
def test_current_bare_reference_structure_rejects_wrong_digit_runs_and_connectors(expected, wrong):
    from tongxing_production.audio import screening as screen
    assert not screen.score(expected, wrong, "ko", .88)[2]
    assert screen.score(expected, ko.spoken_form(expected), "ko", .88)[2]


def test_previous_asr_scoring_keeps_its_recorded_bare_range_semantics():
    from tongxing_production.audio import screening as screen
    for version in [screen.SCORING_V3, screen.SCORING_V4]:
        assert screen.score("12-3장", "1-23장", "ko", .88, scoring=version)[2]
    assert not screen.score("12-3장", "1-23장", "ko", .88)[2]



@pytest.mark.parametrize("text", ["그래서 서류 2장을 냈습니다", "또 사진 2장을 보냈습니다", "하지만 봉투 3장이 남았습니다"])
def test_a_connective_before_a_counted_noun_keeps_the_count(text):
    assert ko.spoken_form(text) == text


def test_frozen_v3_keeps_its_introducers_and_v4_adds_connectives_and_pause_commas(tmp_path):
    assert formal.identity.json_sha256(formal.FROZEN_V3_NORMALIZATION_POLICY) == "0ca53bbbf7f90a0b5a93b5df1f55f7dfa1162747371f4a0b8b306a227034ccd0"
    texts = {"그렇기 때문에 8장을 보면": "그렇기 때문에 팔장을 보면", "따라서, 3장을 봅시다": "따라서, 삼장을 봅시다",
             "그래서, 8장을 보면": "그래서, 팔장을 보면", "본문은 8장입니다": "본문은 팔장입니다"}
    for text, spoken in texts.items():
        assert ko.spoken_form_v3(text) == text
        assert ko.spoken_form(text) == spoken
        assert ko.equivalent(text, spoken) and not ko.equivalent(text, spoken, rule=ko.RULE_V3)
    assert ko.spoken_form_v3("그래서 8장을 보면") == "그래서 팔장을 보면"
    for policy, expected in ((formal.FROZEN_V3_NORMALIZATION_POLICY, None), (formal.SPOKEN_FORMS_NORMALIZATION_POLICY, "그렇기 때문에 팔장을 보면")):
        job = {"targetLocale": "ko", "adapter": {"normalizationPolicySha256": formal.identity.json_sha256(policy)},
               "units": [{"translationGroupId": "g1", "text": "그렇기 때문에 8장을 보면"}]}
        assert formal.policy_spoken_forms(job) == ({"g1": expected} if expected else {})
        document = ko.build(job)
        assert (document["units"][0]["spokenText"] if document else None) == expected


def test_tracked_layer3_configs_bind_the_current_rule():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    policies = json.loads((root / "config/layer3-audio-operation-policies.json").read_text())
    assert policies["normalization"] == formal.SPOKEN_FORMS_NORMALIZATION_POLICY
    for locale in ("ko", "es", "zh-Hans"):
        adapter = json.loads((root / f"config/layer3-adapters/adapter-{locale}.json").read_text())
        assert adapter["normalizationPolicySha256"] == formal.identity.json_sha256(formal.SPOKEN_FORMS_NORMALIZATION_POLICY)


@pytest.mark.parametrize("text", ["서류, 2장을 냈습니다", "사진, 2장", "또 사진, 2장을 보냈습니다"])
def test_a_pause_comma_after_a_noun_keeps_the_count(text):
    assert ko.spoken_form(text) == text
