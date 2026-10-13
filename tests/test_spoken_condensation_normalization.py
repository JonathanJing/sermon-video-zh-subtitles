"""Condensation consumes the same frozen spoken-length contract as its budget."""
import copy

import pytest

from scripts import spoken_condensation as condensation
from scripts import target_audio_predicted_schedule as predicted
from tests.test_target_audio_spoken_length import synthesis

BASE = "시편 101편을 읽으십시오."
REPEAT = " 다시 말합니다."


def inputs(v2=True):
    anchor = {"sourceUnits": [{"sourceUnitId": "u1", "english": "Read 101. We repeat this.", "start": 0, "end": 1},
                              {"sourceUnitId": "u2", "english": "Read 101.", "start": 12, "end": 13}]}
    candidate = {"targetLocale": "ko", "englishSourcePackageJsonSha256": "1" * 64,
                 "anchorManifestSha256": condensation._sha(anchor), "translationPolicySha256": "2" * 64,
                 "groups": [{"translationGroupId": "g1", "sourceUnitIds": ["u1"], "targetText": BASE + REPEAT * 5},
                            {"translationGroupId": "g2", "sourceUnitIds": ["u2"], "targetText": BASE}]}
    identity = synthesis(v2)
    rate = {"schemaVersion": predicted.RATE_SCHEMA, "locale": "ko", "secondsPerUnit": .25,
            "interceptSeconds": 0, "p90Factor": 1, "synthesisIdentity": identity}
    groups = [{"gid": g["translationGroupId"], "sourceStart": u["start"], "sourceEnd": u["end"], "text": g["targetText"]}
              for g, u in zip(candidate["groups"], anchor["sourceUnits"])]
    # Give the first group 4.5 s / 18 spoken units: v2 output fits, raw digits do not.
    plan = predicted.budget(30, groups, rate, synthesis_identity=identity, target_end_lag_seconds=4)
    return anchor, candidate, plan


def test_v2_citation_in_keep_group_does_not_reject_condensation_budget():
    anchor, candidate, plan = inputs()
    requested = condensation.requests(anchor, candidate, plan)["requests"]
    assert [r["translationGroupId"] for r in requested] == ["g1"]
    assert requested[0]["synthesisIdentity"] == plan["rate"]["synthesisIdentity"]
    assert plan["groups"][1]["speechUnits"] == 11
    # Equality remains strict: using the old raw count is rejected.
    changed = copy.deepcopy(plan)
    changed["groups"][1]["speechUnits"] = predicted.speech_units(BASE, "ko")
    with pytest.raises(ValueError, match="other text"):
        condensation.requests(anchor, candidate, changed)
    changed = copy.deepcopy(plan)
    changed["groups"][0]["maxSpeechUnits"] += 1
    with pytest.raises(ValueError, match="recomputed budget"):
        condensation.requests(anchor, candidate, changed)


def test_v2_output_and_binding_recheck_normalized_length_and_legacy_is_raw():
    anchor, candidate, plan = inputs()
    request = condensation.requests(anchor, candidate, plan)["requests"][0]
    spoken = BASE + REPEAT
    omissions = [{"fullTextSpan": REPEAT, "kind": "repetition"}] * 4
    assert condensation.spoken_problems(request, spoken, omissions, "ko", None) == []
    assert condensation._speech_units(request, spoken, "ko") == 17
    assert predicted.speech_units(spoken, "ko") == 19.5
    # Changing the policy to v1 cannot retain a v2 budget proof.
    legacy = copy.deepcopy(request)
    legacy["synthesisIdentity"] = synthesis(False)
    assert any("exceed the budget" in issue for issue in condensation.spoken_problems(legacy, spoken, omissions, "ko", None))
    runtime = {"backend": "fake", "model": "fake", "modelRevision": "1", "cacheNamespace": "test",
               "settings": {"temperature": 0}}
    result = {"translationGroupId": "g1", "spokenText": spoken, "omissions": omissions}
    record = condensation.condense(anchor, candidate, plan, call=lambda *args: result, identity=runtime)
    assert record["status"] == "condensed"
    assert record["groups"][0]["spokenSpeechUnits"] == 17
    revised = copy.deepcopy(candidate)
    revised["groups"][0]["targetText"] = spoken
    binding = condensation.bind_spoken_candidate(record, anchor, candidate, revised)
    assert binding["status"] == "pass"
    assert binding["groups"][0]["finalSpeechUnits"] == 17
    legacy_anchor, legacy_candidate, legacy_plan = inputs(False)
    legacy_request = condensation.requests(legacy_anchor, legacy_candidate, legacy_plan)["requests"][0]
    assert legacy_request["fullSpeechUnits"] == predicted.speech_units(candidate["groups"][0]["targetText"], "ko")
