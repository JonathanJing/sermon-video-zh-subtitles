"""Duration consumers use the frozen synthesis normalization, leaving v1 unchanged."""
import hashlib

import pytest

from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.audio import renderer as formal
from tongxing_production.review import audio_qc as qc
from tongxing_production.audio import predicted_schedule as predicted
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



def test_standalone_qc_cli_requires_and_binds_policy_job(tmp_path, monkeypatch):
    import json
    import sys
    from tests.auto_qc_fixtures import speech_wav
    wav = tmp_path / "unit.wav"
    wav.write_bytes(speech_wav(1))
    input_path, job_path, output = (tmp_path / name for name in ("units.json", "job.json", "qc.json"))
    input_path.write_text(json.dumps({"locale": "ko", "units": [{"groupId": "g1", "text": TEXT,
        "sourceSeconds": 20, "wavPath": str(wav)}]}))
    frozen = job()
    job_path.write_text(json.dumps(frozen))
    base = ["qc", "--input", str(input_path), "--out", str(output)]
    monkeypatch.setattr(sys, "argv", base)
    with pytest.raises(SystemExit) as rejected:
        qc.main()
    assert rejected.value.code == 2
    assert not output.exists()
    monkeypatch.setattr(sys, "argv", base + ["--speech-job", str(job_path)])
    qc.main()
    receipt = json.loads(output.read_text())
    assert receipt["durationNormalization"] == qc.duration_normalization_binding(frozen)
    assert qc.duration_binding_problems(receipt, frozen) == []
    assert qc.duration_binding_problems({**receipt, "durationNormalization": {"mode": "legacy_raw_text"}}, frozen)
    changed = {**frozen, "operatorNote": "changed job"}
    assert qc.duration_binding_problems(receipt, changed)
    output.unlink()
    monkeypatch.setattr(sys, "argv", base + ["--legacy-raw-text"])
    qc.main()
    legacy = json.loads(output.read_text())
    assert legacy["durationNormalization"] == {"mode": "legacy_raw_text"}
    assert qc.duration_binding_problems(legacy, frozen)
    assert qc.duration_binding_problems(legacy, job(False)) == []
    assert qc.duration_binding_problems({}, job(False)) == []


def test_audio_waiver_rejects_unbound_or_other_job_duration_qc():
    from tongxing_production.review import release_basis as basis
    from tests.test_machine_quality_release_basis import audio_fixture
    package, screening, receipt, text = audio_fixture()
    frozen = job()
    for binding in (None, {"mode": "legacy_raw_text"}, qc.duration_normalization_binding({**frozen, "note": "other"})):
        changed = dict(receipt)
        if binding is not None:
            changed["durationNormalization"] = binding
        with pytest.raises(ValueError, match="duration normalization"):
            basis.build_audio_waiver(package, screening, changed, text, {}, anchor={}, candidate={},
                                     repair_ledger=[], speech_job=frozen)



def test_real_calibration_entry_uses_policy_context_without_claiming_job_binding(monkeypatch):
    from tongxing_production.review import seeded_errors as seeded
    from tests import auto_qc_fixtures as fixtures
    units = [{"groupId": f"g{i}", "text": "가" * 10, "sourceSeconds": 20,
              "wav": fixtures.speech_wav(1)} for i in range(5)]
    raw, spoken = (predicted.speech_units(t, "ko") for t in (TEXT, SPOKEN))
    units.append({"groupId": "citation", "text": TEXT, "sourceSeconds": 20,
                  "wav": fixtures.speech_wav(.1 * qc.THRESHOLDS["minRatePerMedian"] * (raw + spoken) / 2)})
    receipts = []
    original = qc.screen
    def observed(*args, **kwargs):
        receipt = original(*args, **kwargs)
        receipts.append(receipt)
        return receipt
    monkeypatch.setattr(qc, "screen", observed)
    identity = {**fixtures.RENDER_IDENTITY, "synthesis": synthesis()}
    seeded.calibrate("ko", [], units, render=lambda *args: fixtures.speech_wav(1),
                     render_identity=identity, max_trials=1)
    assert len(receipts) > 1  # clean and actual seeded audio both traverse QC
    assert not any(i.startswith("truncated:") for i in receipts[0]["results"][-1]["issues"])
    for receipt in receipts:
        assert receipt["durationNormalization"] == {"mode": "calibration_policy_context",
            "normalizationPolicySha256": synthesis()["normalizationPolicySha256"]}
        assert "speechJobJsonSha256" not in receipt["durationNormalization"]
        assert qc.duration_binding_problems(receipt, job())
