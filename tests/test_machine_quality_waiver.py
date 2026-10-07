import copy
import random
import unittest

from scripts import auto_qc_seeded_errors as seeded
from scripts import machine_quality_waiver as waiver
from scripts import produce_target_language_candidate as producer
from scripts import target_audio_auto_qc as audio_qc
from scripts import target_audio_predicted_schedule as predicted
from scripts import target_text_auto_qc as text_qc
from scripts.language_review_plugins import auto_qc_text_common as rules
from scripts.language_review_plugins import es_weekly_auto, ko_weekly_auto
from tests import auto_qc_fixtures as fixtures

LOCALES = ("zh-Hans", "ko", "es")


class TextRuleTests(unittest.TestCase):
    def test_english_numbers_skip_idiomatic_one(self):
        self.assertEqual(rules.english_numbers("the one who waited forty-four years, one of them, 1,990 people"),
                         [44, 1990])
        self.assertEqual(rules.english_numbers("two hundred and fifty"), [250])

    def test_target_number_forms(self):
        self.assertTrue(rules.korean_number_present("마흔네 살", 44))
        self.assertTrue(rules.korean_number_present("세 가지", 3))
        self.assertFalse(rules.korean_number_present("세상", 3))
        self.assertTrue(rules.spanish_number_present("quinientas personas", 500))
        self.assertTrue(rules.spanish_number_present("veintiún años", 21))
        self.assertTrue(rules.chinese_number_present("两百个人", 200))
        self.assertTrue(rules.chinese_number_present("一九九〇年", 1990))
        self.assertEqual(rules.chinese_numeral(105), "一百零五")

    def test_scripture_references_said_and_added(self):
        english = "In chapter three, verse four he says; see also Romans 2:1."
        self.assertEqual(rules.scripture_reference_problems(english, "3장 4절에서, 또 2:1", "ko"), [])
        self.assertEqual(rules.scripture_reference_problems(english, "capítulo tres, versículo cuatro; 2:1", "es"), [])
        self.assertEqual(rules.scripture_reference_problems(english, "三章四节，也看2:1", "zh-Hans"), [])
        self.assertIn("added reference 3:16",
                      rules.scripture_reference_problems("He said a few remain.", "몇 명 (요한복음 3장 16절)", "ko"))
        self.assertIn("missing reference 2:1", rules.scripture_reference_problems(english, "3장 4절", "ko"))
        # A clock time is neither a required nor an added reference.
        self.assertEqual(rules.scripture_reference_problems("We meet at 10:30.", "10시 30분에 모입니다.", "ko"), [])
        self.assertEqual(rules.scripture_reference_problems("We meet at 10:30.", "Nos reunimos a las 10:30.", "es"), [])

    def test_plugins_pass_clean_and_reject_mechanical_errors(self):
        for locale, plugin in (("ko", ko_weekly_auto), ("es", es_weekly_auto)):
            policy = fixtures.policy(locale, plugin.REQUIRED)
            for group in fixtures.groups(locale):
                units = [{"sourceUnitId": "u", "english": group["english"]}]
                checks = plugin.review_group(policy, units, {"targetText": group["targetText"],
                                                             "targetUtterances": [group["targetText"]]})
                self.assertEqual([c["checkId"] for c in checks], plugin.REQUIRED)
                self.assertTrue(all(c["status"] == "pass" for c in checks), (locale, group, checks))
            group = fixtures.groups(locale)[2]
            bad = group["targetText"] + " TODO (3:16)"
            checks = {c["checkId"]: c["status"] for c in plugin.review_group(
                policy, [{"english": group["english"]}], {"targetText": bad, "targetUtterances": [bad]})}
            self.assertEqual(checks["target_script"], "fail")
            self.assertEqual(checks["scripture_references"], "fail")

    def test_plugin_rejects_policy_with_other_checks(self):
        with self.assertRaises(ValueError):
            ko_weekly_auto.review_group(fixtures.policy("ko", ["other"]), [{"english": "x"}],
                                        {"targetText": "가", "targetUtterances": ["가"]})

    def test_plugins_hash_their_shared_rules(self):
        sources = producer.plugin_implementation_sources(
            producer.Path(ko_weekly_auto.__file__))
        self.assertEqual([path.name for path in sources],
                         ["ko_weekly_auto.py", "common.py", "auto_qc_text_common.py"])


class TextQcTests(unittest.TestCase):
    def test_clean_candidates_pass_only_with_back_translation(self):
        for locale in LOCALES:
            groups = fixtures.groups(locale)
            pending = text_qc.screen(groups, locale, policy=fixtures.policy(locale))
            self.assertTrue(all(r["status"] == "pending_back_translation" for r in pending["results"]))
            judged = text_qc.screen(groups, locale, policy=fixtures.policy(locale),
                                    call=fixtures.PerfectSemanticJudge(locale))
            self.assertEqual(judged["status"], "pass", locale)
            self.assertFalse(judged["humanApproval"])

    def test_back_translation_failure_follows_four_step_ladder(self):
        groups = fixtures.groups("ko")
        groups[3] = {**groups[3], "targetText": "은혜는 선물입니다."}
        judge = fixtures.PerfectSemanticJudge("ko")
        first = text_qc.screen(groups, "ko", policy=fixtures.policy("ko"), call=judge)
        row = first["results"][3]
        self.assertEqual((row["status"], row["nextAction"], row["failedAttempts"]),
                         ("fail", "revise_translation", 1))
        last = text_qc.screen(groups, "ko", policy=fixtures.policy("ko"), call=judge,
                              prior_failed_attempts={"g004": 4})
        self.assertEqual(last["sourceTextFallbackGroupIds"], ["g004"])

    def test_judge_cannot_pass_a_major_issue(self):
        verdict = text_qc.validate_comparison({"status": "pass", "issues": [
            {"kind": "negation", "severity": "major", "english": "not", "backTranslation": "does"}]})
        self.assertEqual(verdict["status"], "fail")
        with self.assertRaises(ValueError):
            text_qc.validate_comparison({"status": "pass", "issues": [{"kind": "tone"}]})

    def test_back_translator_never_sees_english(self):
        group = fixtures.groups("es")[0]
        request = text_qc.back_translation_requests(group, "es")["backTranslation"]
        self.assertEqual(request["user"], group["targetText"])
        self.assertNotIn(group["english"], request["system"] + request["user"])


class AudioQcTests(unittest.TestCase):
    def test_clean_units_pass_and_u172_class_anomaly_is_isolated(self):
        units = fixtures.units("ko")
        self.assertEqual(audio_qc.screen(units, "ko")["status"], "pass")
        samples, rate = audio_qc.decode_pcm16(units[5]["wav"])
        units[5] = {**units[5], "wav": audio_qc.encode_pcm16(samples * 15, rate)}
        result = audio_qc.screen(units, "ko")
        self.assertEqual(result["repairGroupIds"], ["g006"])
        self.assertTrue(any(issue.startswith("duration_anomaly") for issue in result["results"][5]["issues"]))
        self.assertEqual(result["results"][5]["nextAction"], "resynthesize_new_seed")

    def test_repair_ladder_is_per_sentence_and_four_attempts(self):
        self.assertEqual([audio_qc.next_action(n) for n in range(5)],
                         ["resynthesize_new_seed", "resynthesize_new_seed",
                          "revise_spoken_text", "revise_spoken_text", "subtitle_only"])
        units = fixtures.units("es")
        units[2] = {**units[2], "wav": audio_qc.encode_pcm16([0.0] * 16000, 8000), "priorFailedAttempts": 4}
        result = audio_qc.screen(units, "es")
        self.assertEqual(result["subtitleOnlyGroupIds"], ["g003"])
        self.assertEqual(result["repairGroupIds"], [])

    def test_two_level_asr(self):
        self.assertEqual(audio_qc.asr_decision(0.95, None), "pass")
        self.assertEqual(audio_qc.asr_decision(0.6, None), "needs_secondary_asr")
        self.assertEqual(audio_qc.asr_decision(0.6, 0.93), "pass")
        self.assertEqual(audio_qc.asr_decision(0.6, 0.7), "fail")
        units = fixtures.units("zh-Hans")
        units[0] = {**units[0], "asrPrimary": 0.5}
        self.assertEqual(audio_qc.screen(units, "zh-Hans")["results"][0]["nextAction"], "run_secondary_asr")


class PredictedScheduleTests(unittest.TestCase):
    def rate(self):
        rng = random.Random(7)
        rows = [{"text": "가" * n, "audioSeconds": 0.2 + 0.17 * n * rng.uniform(0.9, 1.1)} for n in range(5, 60)]
        rows.append({"text": "가나다", "audioSeconds": 61.0})
        return predicted.fit_rate(rows, "ko")

    def test_fit_excludes_synthesis_anomaly(self):
        rate = self.rate()
        self.assertEqual(rate["excludedOutliers"], 1)
        self.assertAlmostEqual(rate["secondsPerUnit"], 0.17, delta=0.02)

    def test_budget_shortens_only_the_long_group_and_fits_8s(self):
        groups = [{"gid": "g1", "sourceStart": 0, "sourceEnd": 3, "text": "가" * 15},
                  {"gid": "g2", "sourceStart": 3, "sourceEnd": 5, "text": "가" * 120},
                  {"gid": "g3", "sourceStart": 5.5, "sourceEnd": 8, "text": "가" * 15}]
        result = predicted.budget(30, groups, self.rate())
        self.assertEqual(result["status"], "requires_spoken_revision")
        self.assertEqual(result["shortenGroupIds"], ["g2"])
        self.assertEqual(result["budgetedScheduleStatus"], "pass")
        self.assertLess(result["groups"][1]["maxSpeechUnits"], 120)
        self.assertEqual(result["groups"][2]["action"], "keep")
        self.assertEqual(result["modelCalls"], 0)

    def test_fitting_text_is_kept(self):
        groups = [{"gid": "a", "sourceStart": 0, "sourceEnd": 4, "text": "가" * 20}]
        self.assertEqual(predicted.budget(10, groups, self.rate())["status"], "fits")


class CalibrationAndWaiverTests(unittest.TestCase):
    def calibration(self, locale, *, semantic=True):
        call = fixtures.PerfectSemanticJudge(locale) if semantic else None
        return seeded.calibrate(locale, fixtures.groups(locale), fixtures.units(locale),
                                policy=fixtures.policy(locale), call=call)

    def test_calibration_has_no_false_positives_on_clean_fixtures(self):
        for locale in LOCALES:
            result = self.calibration(locale, semantic=False)
            self.assertEqual(result["cleanFalsePositives"], 0, locale)
            for kind in ("text.english_leak", "text.placeholder", "text.added_reference",
                         "audio.stretched", "audio.silent", "audio.clipped", "audio.truncated"):
                self.assertEqual(result["kinds"][kind]["rate"], 1.0, (locale, kind))
            self.assertFalse(result["semanticChecksIncluded"])

    def final_receipts(self, locale, count=40, subtitle_only=0, fallback=0):
        ids = [f"g{i:03d}" for i in range(count)]
        text = {"locale": locale, "sourceTextFallbackGroupIds": ids[:fallback], "results": [
            {"groupId": gid, "nextAction": "source_text_fallback" if i < fallback else "keep"}
            for i, gid in enumerate(ids)]}
        audio = {"locale": locale, "subtitleOnlyGroupIds": ids[count - subtitle_only:], "results": [
            {"groupId": gid, "nextAction": "subtitle_only" if i >= count - subtitle_only else "keep"}
            for i, gid in enumerate(ids)]}
        return text, audio

    def test_waiver_requires_semantic_calibration(self):
        text, audio = self.final_receipts("ko")
        blocked = waiver.waive("ko", "c" * 64, text, audio, self.calibration("ko", semantic=False))
        self.assertEqual(blocked["status"], "blocked_calibration")
        self.assertFalse(blocked["releaseEligible"])
        waived = waiver.waive("ko", "c" * 64, text, audio, self.calibration("ko"))
        self.assertEqual(waived["status"], "machine_quality_waived")
        self.assertFalse(waived["humanApproval"])
        self.assertIn("기계 품질 검사", waived["disclosure"])

    def test_five_percent_rules(self):
        calibration = self.calibration("es")
        text, audio = self.final_receipts("es", subtitle_only=2)
        self.assertEqual(waiver.waive("es", "c" * 64, text, audio, calibration)["status"],
                         "machine_quality_waived")
        text, audio = self.final_receipts("es", subtitle_only=3)
        result = waiver.waive("es", "c" * 64, text, audio, calibration)
        self.assertEqual(result["status"], "machine_quality_waived_text_only")
        self.assertFalse(result["audioAvailable"])
        text, audio = self.final_receipts("es", fallback=3)
        self.assertEqual(waiver.waive("es", "c" * 64, text, audio, calibration)["status"],
                         "blocked_text_quality")

    def test_pending_repairs_and_stale_calibration_block(self):
        calibration = self.calibration("zh-Hans")
        text, audio = self.final_receipts("zh-Hans")
        audio["results"][0]["nextAction"] = "resynthesize_new_seed"
        self.assertEqual(waiver.waive("zh-Hans", "c" * 64, text, audio, calibration)["status"],
                         "repair_in_progress")
        text, audio = self.final_receipts("zh-Hans")
        stale = copy.deepcopy(calibration)
        stale["implementationSha256"] = "0" * 64
        self.assertEqual(waiver.waive("zh-Hans", "c" * 64, text, audio, stale)["status"],
                         "blocked_calibration")


if __name__ == "__main__":
    unittest.main()
