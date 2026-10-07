import copy
import hashlib
import json
import unittest

from scripts import run_target_language_models as runner
from scripts import spoken_condensation as condensation
from scripts import target_audio_predicted_schedule as predicted
from tests import auto_qc_fixtures as fixtures

LOCALE = "zh-Hans"
IDENTITY = {"targetLocale": LOCALE, "adapterId": "zh-tts", "adapterVersion": "1", "configSha256": "a" * 64,
            "provider": "local", "model": "tts", "modelRevision": "r1", "voice": "v1", "speakerId": "s1",
            "conditioningSha256": "b" * 64, "languageParameter": "zh", "normalizationPolicySha256": "c" * 64}
RATE = {"schemaVersion": predicted.RATE_SCHEMA, "locale": LOCALE, "secondsPerUnit": 0.35,
        "interceptSeconds": 0.2, "p90Factor": 1.0, "synthesisIdentity": IDENTITY}
CONDENSER = {"backend": "fake-transport", "model": "fake-condenser"}
UNITS = [("u1", "Good morning, church."),
         ("u2", "I want to say this again, and I want to say it clearly."),
         ("u3", "Jesus has not forgotten you, he has not forgotten you at all, not for a single moment."),
         ("u4", "Let us pray.")]
GROUPS = [("g1", ["u1"], ["早上好，教会。"]),
          ("g2", ["u2", "u3"], ["我想再说一遍，我想说得清清楚楚：",
                                "耶稣没有忘记你，祂一点也没有忘记你，一刻也没有忘记你。"]),
          ("g3", ["u4"], ["让我们一起祷告。"])]
TIMES = {"g1": (0.0, 1.5), "g2": (2.0, 5.0), "g3": (14.0, 15.0)}
SPOKEN = "耶稣没有忘记你，一刻也没有忘记你。"
OMISSIONS = [{"fullTextSpan": "我想再说一遍，我想说得清清楚楚：", "kind": "filler"},
             {"fullTextSpan": "祂一点也没有忘记你，", "kind": "repetition"}]


def sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def anchor():
    return {"sourceUnits": [{"sourceUnitId": unit_id, "english": english} for unit_id, english in UNITS]}


def candidate():
    return {"targetLocale": LOCALE, "englishSourcePackageJsonSha256": "1" * 64,
            "anchorManifestSha256": sha(anchor()), "translationPolicySha256": "2" * 64,
            "groups": [{"translationGroupId": gid, "sourceUnitIds": units, "targetUtterances": utterances,
                        "targetText": "".join(utterances)} for gid, units, utterances in GROUPS]}


def budget(full=None):
    full = full or candidate()
    groups = [{"gid": group["translationGroupId"], "sourceStart": TIMES[group["translationGroupId"]][0],
               "sourceEnd": TIMES[group["translationGroupId"]][1], "text": group["targetText"]}
              for group in full["groups"]]
    return predicted.budget(20.0, groups, RATE, synthesis_identity=IDENTITY)


class FakeCondenser:
    def __init__(self, *outputs):
        self.outputs, self.calls = list(outputs), []

    def __call__(self, role, system, user, schema):
        self.calls.append({"role": role, "system": system, "user": json.loads(user)})
        return self.outputs.pop(0)


def answer(text=SPOKEN, omissions=OMISSIONS):
    return {"translationGroupId": "g2", "spokenText": text, "omissions": copy.deepcopy(omissions)}


def spoken_candidate(text=SPOKEN, full=None):
    spoken = copy.deepcopy(full or candidate())
    group = spoken["groups"][1]
    group["targetUtterances"], group["targetText"] = [text], text
    return spoken


class RequestTests(unittest.TestCase):
    def test_only_over_window_groups_are_requested(self):
        plan = budget()
        self.assertEqual(plan["shortenGroupIds"], ["g2"])
        asked = condensation.requests(anchor(), candidate(), plan)
        self.assertEqual([row["translationGroupId"] for row in asked["requests"]], ["g2"])
        request = asked["requests"][0]
        self.assertEqual([unit["sourceUnitId"] for unit in request["englishUnits"]], ["u2", "u3"])
        self.assertLess(request["maxSpeechUnits"], request["fullSpeechUnits"])
        self.assertLessEqual(predicted.speech_units(SPOKEN, LOCALE), request["maxSpeechUnits"])

    def test_budget_and_anchor_must_belong_to_the_candidate(self):
        edited = candidate()
        edited["groups"][1]["targetText"] += "真的。"
        with self.assertRaisesRegex(ValueError, "other text"):
            condensation.requests(anchor(), edited, budget())
        other = anchor()
        other["sourceUnits"][0]["english"] = "Hello."
        with self.assertRaisesRegex(ValueError, "Anchor manifest differs"):
            condensation.requests(other, candidate(), budget())
        reordered = budget()
        reordered["groups"].reverse()
        with self.assertRaisesRegex(ValueError, "groups differ"):
            condensation.requests(anchor(), candidate(), reordered)


class CondenseTests(unittest.TestCase):
    def condense(self, *outputs):
        call = FakeCondenser(*outputs)
        record = condensation.condense(anchor(), candidate(), budget(), call=call, identity=CONDENSER,
                                       policy=fixtures.policy(LOCALE))
        return record, call

    def test_condensed_group_records_omissions_and_exports_a_runner_brief(self):
        record, call = self.condense(answer())
        self.assertEqual((record["status"], record["humanApproval"], record["modelCalls"]), ("condensed", False, 1))
        row = record["groups"][0]
        self.assertEqual((row["translationGroupId"], row["spokenText"], row["omissions"]), ("g2", SPOKEN, OMISSIONS))
        self.assertEqual(record["synthesisIdentity"], IDENTITY)
        self.assertEqual(record["condenserIdentitySha256"], sha(CONDENSER))
        self.assertEqual(call.calls[0]["user"]["fullTranslation"], candidate()["groups"][1]["targetText"])
        self.assertNotIn("previousAttemptProblems", call.calls[0]["user"])
        brief = condensation.revision_brief(record, candidate())
        self.assertEqual(brief["groups"], [{
            "translationGroupId": "g2", "sourceUnitIds": ["u2", "u3"], "proposedTargetText": SPOKEN,
            "priorTargetTextSha256": hashlib.sha256(candidate()["groups"][1]["targetText"].encode()).hexdigest()}])
        # The brief is accepted by the Layer 2 runner that produces the spoken candidate.
        full = candidate()
        keys = ("targetLocale", "englishSourcePackageJsonSha256", "anchorManifestSha256", "translationPolicySha256")
        source_units = anchor()["sourceUnits"]
        request = {**{key: full[key] for key in keys}, "sourceUnits": source_units}
        plan = [{"translationGroupId": g["translationGroupId"], "sourceUnitIds": g["sourceUnitIds"]}
                for g in full["groups"]]
        prior = {**request, "groups": [{"translationGroupId": g["translationGroupId"],
                                        "sourceUnitIds": g["sourceUnitIds"],
                                        "targetUtterances": g["targetUtterances"]} for g in full["groups"]]}
        self.assertEqual(list(runner.validate_revision_brief(brief, request, plan, prior)), ["g2"])

    def test_a_failed_attempt_is_retried_with_its_problems(self):
        too_long = answer(text=candidate()["groups"][1]["targetText"][:-1])
        record, call = self.condense(too_long, answer())
        self.assertEqual((record["status"], record["groups"][0]["attempts"], record["modelCalls"]),
                         ("condensed", 2, 2))
        self.assertTrue(any("exceed the budget" in problem
                            for problem in call.calls[1]["user"]["previousAttemptProblems"]))

    def test_dropped_facts_and_undeclared_spans_fail(self):
        cases = [
            (answer(text="没有忘记你，一刻也没有忘记你。"), "Jesus: expected 耶稣"),
            (answer(omissions=[]), "no omissions declared"),
            (answer(omissions=[{"fullTextSpan": "我从来没说过", "kind": "filler"}]), "not a span"),
            (answer(omissions=[{"fullTextSpan": "一刻也没有忘记你", "kind": "core_claim"}]), "kind not allowed"),
            ({"translationGroupId": "g2", "spokenText": SPOKEN}, "does not match the schema"),
        ]
        for output, message in cases:
            with self.subTest(message=message):
                record, _ = self.condense(output, copy.deepcopy(output))
                row = record["groups"][0]
                self.assertEqual((record["status"], row["status"], record["failedGroupIds"]),
                                 ("condensed_with_failures", "failed", ["g2"]))
                self.assertTrue(any(message in problem for problem in row["problems"]), row["problems"])
                with self.assertRaisesRegex(ValueError, "No condensed group"):
                    condensation.revision_brief(record, candidate())

    def test_scripture_reference_survives_condensation(self):
        request = {"translationGroupId": "g2", "fullTargetText": "正如约翰福音3章16节所说，神爱世人，神真的爱世人。",
                   "maxSpeechUnits": 30, "englishUnits": [{"sourceUnitId": "u",
                                                          "english": "As John 3:16 says, God loves the world."}]}
        self.assertEqual(condensation.spoken_problems(request, "约翰福音3章16节说，神爱世人。",
                                                      [{"fullTextSpan": "神真的爱世人。", "kind": "repetition"}],
                                                      LOCALE, None), [])
        self.assertTrue(any("reference" in problem for problem in condensation.spoken_problems(
            request, "神爱世人。", [{"fullTextSpan": "正如约翰福音3章16节所说，", "kind": "aside"}], LOCALE, None)))

    def test_condenser_identity_is_required(self):
        with self.assertRaisesRegex(ValueError, "backend and model"):
            condensation.condense(anchor(), candidate(), budget(), call=FakeCondenser(answer()), identity={})


class BindTests(unittest.TestCase):
    def setUp(self):
        self.record = condensation.condense(anchor(), candidate(), budget(), call=FakeCondenser(answer()),
                                            identity=CONDENSER, policy=fixtures.policy(LOCALE))

    def bind(self, spoken):
        return condensation.bind_spoken_candidate(self.record, anchor(), candidate(), spoken,
                                                  fixtures.policy(LOCALE))

    def test_spoken_candidate_from_the_brief_binds(self):
        spoken = spoken_candidate()
        binding = self.bind(spoken)
        self.assertEqual((binding["status"], binding["issues"]), ("pass", []))
        self.assertEqual(binding["spokenCandidateJsonSha256"], sha(spoken))
        self.assertEqual(binding["condensationRecordJsonSha256"], sha(self.record))
        self.assertFalse(binding["groups"][0]["changedByReview"])
        repaired = "耶稣没有忘记你，祂一刻也没有忘记你。"
        binding = self.bind(spoken_candidate(repaired))
        self.assertEqual(binding["status"], "pass", binding["issues"])
        self.assertTrue(binding["groups"][0]["changedByReview"])

    def test_review_that_undoes_or_overruns_the_condensation_fails(self):
        full_text = candidate()["groups"][1]["targetText"]
        self.assertIn("spoken text is the full translation", self.bind(spoken_candidate(full_text))["issues"][0])
        longer = "耶稣没有忘记你，祂一点也没有忘记你，祂一刻也没有忘记你，真的没有。"
        self.assertIn("exceed the budget", self.bind(spoken_candidate(longer))["issues"][0])
        changed = spoken_candidate()
        changed["groups"][0]["targetText"] = "大家早上好。"
        self.assertEqual(self.bind(changed)["issues"], ["g1: an uncondensed group differs from the full translation"])
        other = spoken_candidate()
        other["groups"].pop()
        with self.assertRaisesRegex(ValueError, "other groups"):
            self.bind(other)

    def test_record_is_bound_to_its_full_candidate(self):
        edited = candidate()
        edited["translationPolicySha256"] = "3" * 64
        with self.assertRaisesRegex(ValueError, "another full candidate"):
            condensation.revision_brief(self.record, edited)


if __name__ == "__main__":
    unittest.main()
