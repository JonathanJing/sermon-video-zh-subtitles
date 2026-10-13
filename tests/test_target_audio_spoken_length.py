"""Duration consumers use the frozen synthesis normalization, leaving v1 unchanged."""
import hashlib

import pytest

from scripts import render_formal_target_language_speech as formal
from scripts import target_audio_auto_qc as qc
from scripts import target_audio_predicted_schedule as predicted
from tests.test_machine_quality_waiver import IDENTITY


TEXT = "시편 101편 말씀을 읽읍시다"
SPOKEN = "시편 백일편 말씀을 읽읍시다"


def job(v2=True):
    return {"targetLocale": "ko", "adapter": {"normalizationPolicySha256": formal.identity.json_sha256(
        formal.SPOKEN_FORMS_NORMALIZATION_POLICY if v2 else {"policy": formal.EXACT_TEXT_POLICY})},
        "units": [{"translationGroupId": "g1", "text": TEXT}]}


def synthesis(v2=True):
    return {**IDENTITY, **job(v2)["adapter"]}


@pytest.mark.parametrize("v2", [True, False])
def test_rate_fit_prediction_and_budget_use_the_same_spoken_length(v2):
    # Measured length is exactly 0.2 seconds per actual policy-derived syllable.
    rows = []
    for index in range(24):
        text = TEXT + "가" * index
        spoken = (SPOKEN if v2 else TEXT) + "가" * index
        rows.append({"text": text, "audioSeconds": .2 * predicted.speech_units(spoken, "ko"),
                     "audioSha256": hashlib.sha256(text.encode()).hexdigest()})
    rate = predicted.fit_rate(rows, "ko", synthesis_identity=synthesis(v2))
    assert rate["secondsPerUnit"] == pytest.approx(.2)
    assert rate["interceptSeconds"] == pytest.approx(0)
    units = predicted.speech_units(SPOKEN if v2 else TEXT, "ko")
    assert predicted.predict_seconds(TEXT, rate) == pytest.approx(.2 * units)
    result = predicted.budget(30, [{"gid": "g1", "text": TEXT, "sourceStart": 0, "sourceEnd": 20}],
                              rate, synthesis_identity=synthesis(v2))
    assert result["groups"][0]["speechUnits"] == units
    assert result["groups"][0]["predictedSeconds"] == pytest.approx(.2 * units)
    assert rows[0]["text"] == TEXT  # approved measurement text is retained


def test_qc_rate_boundary_uses_job_policy_and_legacy_defaults_stay_raw():
    metrics = {"durationSeconds": 10, "rmsDbfs": -20, "silenceRatio": 0,
               "longestInternalSilenceSeconds": 0, "leadingSilenceSeconds": 0,
               "trailingSilenceSeconds": 0, "clippingRatio": 0}
    units = [{"text": "가" * 10, "sourceSeconds": 20, "metrics": dict(metrics)} for _ in range(5)]
    raw_count, spoken_count = (predicted.speech_units(text, "ko") for text in (TEXT, SPOKEN))
    duration = qc.THRESHOLDS["minRatePerMedian"] * (raw_count + spoken_count) / 2
    units.append({"text": TEXT, "sourceSeconds": 20, "metrics": {**metrics, "durationSeconds": duration}})
    assert qc.unit_issues(units, "ko", speech_job=job())[-1] == []
    for legacy in (None, job(False)):
        assert any(issue.startswith("truncated:") for issue in qc.unit_issues(units, "ko", speech_job=legacy)[-1])
    assert units[-1]["text"] == TEXT
    with pytest.raises(ValueError, match="another locale"):
        qc.unit_issues(units, "ko", speech_job={**job(), "targetLocale": "es"})


def test_screen_decodes_audio_and_consumes_frozen_spoken_policy():
    from tests.auto_qc_fixtures import speech_wav

    units = [{"groupId": f"g{index}", "text": "가" * 10, "sourceSeconds": 20,
              "wav": speech_wav(1)} for index in range(5)]
    raw_count, spoken_count = (predicted.speech_units(text, "ko") for text in (TEXT, SPOKEN))
    duration = .1 * qc.THRESHOLDS["minRatePerMedian"] * (raw_count + spoken_count) / 2
    units.append({"groupId": "citation", "text": TEXT, "sourceSeconds": 20, "wav": speech_wav(duration)})
    current = qc.screen(units, "ko", speech_job=job())["results"][-1]
    legacy = qc.screen(units, "ko")["results"][-1]
    assert not any(issue.startswith("truncated:") for issue in current["issues"])
    assert any(issue.startswith("truncated:") for issue in legacy["issues"])
    assert current["status"] == "pending_primary_asr"  # duration is not content acceptance
