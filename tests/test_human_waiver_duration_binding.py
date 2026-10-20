"""Human acceptance cannot bypass frozen duration normalization binding."""
import copy
import pytest
from tongxing_production.review import audio_waiver_acceptance as v3
from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.review import audio_qc as qc
from tongxing_production.review import audio_qc_acceptance as acceptance_rules
from tests.test_machine_quality_release_basis import audio_fixture
from tests.test_target_audio_spoken_length import job


@pytest.mark.parametrize("binding", [None, {"mode": "legacy_raw_text"},
    {"mode": "calibration_policy_context", "normalizationPolicySha256": "0" * 64},
    qc.duration_normalization_binding({**job(), "note": "another job"})])
def test_human_waiver_cannot_accept_unbound_v2_duration_qc(binding):
    package, screening, receipt, text = audio_fixture(flagged=True)
    changed = copy.deepcopy(receipt)
    changed["status"] = "fail"
    changed["results"][1].update(status="fail", asrDecision="fail", nextAction="re_render",
                                 asrSecondary=0.5, asrSecondaryRecognized="내가 함께")
    if binding is not None:
        changed["durationNormalization"] = binding
    accepted = acceptance_rules.build(package=package, audio_qc=changed, decided_by="test operator",
        decided_at="2026-10-12T00:00:00Z", user_statement="offline fixture acceptance", group_ids=["g2"])
    assert acceptance_rules.check(accepted, package=package, audio_qc=changed) == {"g2"}
    with pytest.raises(ValueError, match="duration normalization"):
        v3.build_audio_waiver(package, screening, changed, text, {}, human_acceptance=accepted,
            anchor={}, candidate={}, repair_ledger=[], speech_job=job())


def test_human_waiver_bound_qc_reaches_its_separate_acceptance_gate():
    package, screening, receipt, text = audio_fixture()
    receipt["durationNormalization"] = qc.duration_normalization_binding(job())
    with pytest.raises(ValueError, match="human_acceptance_identity"):
        v3.build_audio_waiver(package, screening, receipt, text, {}, human_acceptance={},
            anchor={}, candidate={}, repair_ledger=[], speech_job=job())
