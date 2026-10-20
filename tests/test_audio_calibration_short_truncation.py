"""Very short Chinese sentences get no truncation trial; other kinds and locales are unchanged."""
from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.review import seeded_errors as seeded
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


def test_short_units_do_not_consume_truncation_quota():
    rows = units([SHORT_ZH[0], LONG_ZH, SHORT_ZH[1], LONG_ZH, LONG_ZH])
    kinds = seeded.calibrate_audio(rows, "zh-Hans", max_trials=2)["kinds"]
    assert kinds["truncated"]["trials"] == 2
    assert kinds["truncated"]["excludedShortGroupIds"] == ["g0", "g2"]
    assert kinds["silent"]["trials"] == 2
    exhausted = seeded.calibrate_audio(rows[:3], "zh-Hans", max_trials=2)["kinds"]["truncated"]
    assert exhausted["trials"] == 1
    assert exhausted["excludedShortGroupIds"] == ["g0", "g2"]


def test_all_short_preflight_has_no_truncation_but_other_kinds_are_available():
    from tongxing_production.review import qc_audio_run as driver
    coverage = driver.audio_coverage({"units": units(["一", "二"])}, "zh-Hans")
    assert coverage["untestableKinds"] == ["truncated"]
    assert coverage["truncationEligibleTrials"] == 0
    coverage = driver.audio_coverage({"units": units(["一"] * driver.MAX_TRIALS + [LONG_ZH])}, "zh-Hans")
    assert coverage["truncationEligibleTrials"] == 1


def test_calibration_schema_legacy_compatibility_exclusion_validation():
    from tongxing_production.review import waiver
    base = {"schemaVersion": waiver.LEGACY_CALIBRATION_SCHEMA, "locale": "zh-Hans",
            "implementationSha256": "frozen", "kinds": {"audio.truncated":
            {"trials": 2, "detected": 2, "rate": 1.0}}}
    problems = waiver.calibration_problems(base, "zh-Hans", "frozen")
    assert "unsupported calibration schema" not in problems
    row = base["kinds"]["audio.truncated"]
    row["excludedShortGroupIds"] = ["g0"]
    assert any("require calibration v3" in problem for problem in waiver.calibration_problems(base, "zh-Hans", "frozen"))
    base["schemaVersion"] = waiver.CALIBRATION_SCHEMA
    assert not any("exclusions" in problem for problem in waiver.calibration_problems(base, "zh-Hans", "frozen"))
    row["excludedShortGroupIds"] = ["g0", "g0"]
    assert any("invalid short-unit" in problem for problem in waiver.calibration_problems(base, "zh-Hans", "frozen"))
    base["schemaVersion"] = "sermon-auto-qc-calibration-v1"
    assert "unsupported calibration schema" in waiver.calibration_problems(base, "zh-Hans", "frozen")


def test_producer_persists_v3_and_zero_truncation_still_blocks_waiver():
    from tongxing_production.review import waiver
    receipt = seeded.calibrate("zh-Hans", fixtures.groups("zh-Hans"), units(["一", "二"]))
    assert receipt["schemaVersion"] == "sermon-auto-qc-calibration-v3"
    assert receipt["kinds"]["audio.truncated"]["excludedShortGroupIds"] == ["g0", "g1"]
    problems = waiver.calibration_problems(receipt, "zh-Hans", waiver.implementation_sha256(), require_audio=True)
    assert any("no trials" in p and "audio.truncated" in p for p in problems)


def test_release_consumer_accepts_unchanged_v2_and_current_v3_counts():
    from tongxing_production.review import release_basis as basis
    from tongxing_production.review import waiver
    from tests.test_machine_quality_release_basis import calibration, IMPLEMENTATION
    receipt = calibration()
    current = basis.calibration_summary(receipt, "ko", IMPLEMENTATION, require_audio=True)
    receipt["schemaVersion"] = waiver.LEGACY_CALIBRATION_SCHEMA
    legacy = basis.calibration_summary(receipt, "ko", IMPLEMENTATION, require_audio=True)
    assert legacy.pop("jsonSha256") != current.pop("jsonSha256")
    assert legacy == current
    receipt["implementationSha256"] = "outdated"
    import pytest
    with pytest.raises(ValueError, match="implementation changed"):
        basis.calibration_summary(receipt, "ko", IMPLEMENTATION, require_audio=True)
