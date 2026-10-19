"""Stored coefficients cannot be combined with another spoken/counting implementation."""
import copy
from pathlib import Path

import pytest

from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.audio import predicted_schedule as predicted
from tests.test_target_audio_spoken_length import synthesis, TEXT


def rate(v2=True):
    return predicted.fit_rate([
        {"text": TEXT + "가" * n, "audioSeconds": 1 + n / 10, "audioSha256": "a" * 64}
        for n in range(24)], "ko", synthesis_identity=synthesis(v2))


def consumers(value):
    return [lambda: predicted.predict_seconds(TEXT, value),
            lambda: predicted.max_units_for(10, value),
            lambda: predicted.budget(30, [{"gid": "g1", "text": TEXT, "sourceStart": 0, "sourceEnd": 20}],
                                     value, synthesis_identity=value["synthesisIdentity"])]


@pytest.mark.parametrize("dependency", predicted.RATE_IMPLEMENTATION_FILES)
def test_each_real_dependency_mutation_invalidates_stored_coefficients(monkeypatch, dependency):
    fitted = rate()
    original = Path.read_bytes
    from scripts import sermon_source_producer_compatibility as compatibility
    key = dependency if dependency.startswith(("packages/", "scripts/")) else "scripts/" + dependency
    target = Path(__file__).resolve().parents[1] / compatibility.resolve(key)
    baseline = fitted["rateImplementationSha256"]
    with monkeypatch.context() as changed:
        changed.setattr(Path, "read_bytes", lambda path: original(path) + b"\n# mutation\n" if path == target else original(path))
        assert predicted.rate_implementation_sha256() != baseline
        for consume in consumers(fitted):
            with pytest.raises(ValueError, match="implementation identity.*stale"):
                consume()
    assert predicted.rate_implementation_sha256() == baseline
    for consume in consumers(fitted):
        consume()


@pytest.mark.parametrize("v2", [True, False])
def test_new_rate_requires_current_implementation_binding(v2):
    fitted = rate(v2)
    assert fitted["schemaVersion"] == predicted.RATE_SCHEMA
    for invalid in (None, "0" * 64):
        changed = copy.deepcopy(fitted)
        if invalid is None:
            changed.pop("rateImplementationSha256")
        else:
            changed["rateImplementationSha256"] = invalid
        for consume in consumers(changed):
            with pytest.raises(ValueError, match="implementation identity"):
                consume()


def test_old_rate_support_is_explicitly_raw_only():
    raw = rate(False)
    original = predicted.predict_seconds(TEXT, raw)
    raw["schemaVersion"] = predicted.RATE_SCHEMA_V1
    raw.pop("rateImplementationSha256")
    assert predicted.predict_seconds(TEXT, raw) == original
    spoken = rate()
    spoken["schemaVersion"] = predicted.RATE_SCHEMA_V1
    spoken.pop("rateImplementationSha256")
    for consume in consumers(spoken):
        with pytest.raises(ValueError, match="Legacy speech rate lacks.*identity"):
            consume()
