import copy
import hashlib
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
IDENTITY = {"targetLocale": "ko", "adapterId": "ko-tts", "adapterVersion": "1", "configSha256": "a" * 64,
            "provider": "local", "model": "tts", "modelRevision": "r1", "voice": "v1", "speakerId": "s1",
            "conditioningSha256": "b" * 64, "languageParameter": "ko", "normalizationPolicySha256": "c" * 64}


def text_sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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

    def test_decimal_numbers_are_checked(self):
        english = "It grew 2.5 percent in 2026."
        self.assertEqual(rules.english_numbers(english), ["2.5", 2026])
        for locale, good, spoken in (("ko", "2026년에 2.5퍼센트 성장했습니다.", "2026년에 이점오 퍼센트"),
                                     ("es", "En 2026 creció un 2,5 por ciento.", "En 2026 creció dos coma cinco"),
                                     ("zh-Hans", "2026年增长了2.5%。", "2026年增长了两点五")):
            self.assertEqual(rules.number_problems(english, good, locale, set()), [], locale)
            self.assertEqual(rules.number_problems(english, spoken, locale, set()), [], locale)
            changed = good.replace("2.5", "25").replace("2,5", "25")
            self.assertEqual(rules.number_problems(english, changed, locale, set()), ["missing number 2.5"])
            self.assertIsNotNone(seeded.mutate_text({"english": english, "targetText": good},
                                                    "wrong_number", locale, None))

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
        self.assertEqual(rules.english_references("At 10:30 we meet."), (set(), set()))
        self.assertEqual(rules.scripture_reference_problems("At 10:30 we meet.", "10시 30분에 모입니다.", "ko"), [])
        self.assertEqual(rules.english_references("Turn to Revelation 3:4.")[0], {(3, 4)})

    def test_korean_chapter_markers_take_particles(self):
        english = "Turn with me to chapter three."
        for target in ("3장에서 보겠습니다", "3장을 펴십시오", "3장에 있습니다", "오늘 본문은 3장입니다"):
            self.assertEqual(rules.scripture_reference_problems(english, target, "ko"), [], target)
        self.assertIn("missing chapter 3", rules.scripture_reference_problems(english, "세상을 봅니다", "ko"))

    def test_added_chapter_only_reference_is_rejected(self):
        english = "He said a few remain."
        self.assertIn("added chapter 3", rules.scripture_reference_problems(english, "몇 명이 남았습니다. 요한복음 3장", "ko"))
        self.assertIn("added chapter 3", rules.scripture_reference_problems(english, "Quedan unos pocos. Juan capítulo 3", "es"))
        self.assertIn("added chapter 3", rules.scripture_reference_problems(english, "还剩几个人。约翰福音3章", "zh-Hans"))
        # A count the English said is not a citation.
        self.assertEqual(rules.scripture_reference_problems("Take three sheets.", "종이 3장을 가져가세요.", "ko"), [])

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

    def test_spanish_requires_latin_script(self):
        self.assertEqual(rules.script_problems("La gracia es un regalo que recibimos.", "es"), [])
        self.assertTrue(rules.script_problems("Благодать — это дар, который мы получаем.", "es"))
        self.assertTrue(rules.script_problems("النعمة هبة نتلقاها.", "es"))

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

    def test_missing_primary_asr_never_passes(self):
        units = fixtures.units("ko")
        units[1] = {key: value for key, value in units[1].items() if key != "asrPrimary"}
        result = audio_qc.screen(units, "ko")
        row = result["results"][1]
        self.assertEqual((row["status"], row["nextAction"]), ("pending_primary_asr", "run_primary_asr"))
        self.assertEqual(result["status"], "requires_repair")
        self.assertEqual(row["audioSha256"], hashlib.sha256(units[1]["wav"]).hexdigest())
        # An acoustic failure is still a failure without ASR.
        units[1] = {**units[1], "wav": audio_qc.encode_pcm16([0.0] * 16000, 8000)}
        self.assertEqual(audio_qc.screen(units, "ko")["results"][1]["status"], "fail")


class PredictedScheduleTests(unittest.TestCase):
    def rows(self):
        rng = random.Random(7)
        rows = [{"text": "가" * n, "audioSeconds": 0.2 + 0.17 * n * rng.uniform(0.9, 1.1),
                 "audioSha256": text_sha(str(n))} for n in range(5, 60)]
        rows.append({"text": "가나다", "audioSeconds": 61.0, "audioSha256": "f" * 64})
        return rows

    def rate(self):
        return predicted.fit_rate(self.rows(), "ko", synthesis_identity=IDENTITY)

    def test_fit_excludes_synthesis_anomaly(self):
        rate = self.rate()
        self.assertEqual(rate["excludedOutliers"], 1)
        self.assertAlmostEqual(rate["secondsPerUnit"], 0.17, delta=0.02)
        self.assertEqual(rate["synthesisIdentity"], IDENTITY)
        self.assertEqual(rate["measuredUnits"], 56)

    def test_rate_is_bound_to_synthesis_identity(self):
        groups = [{"gid": "a", "sourceStart": 0, "sourceEnd": 4, "text": "가" * 20}]
        for field in ("voice", "modelRevision", "configSha256"):
            other = {**IDENTITY, field: IDENTITY[field] + "x"}
            with self.assertRaisesRegex(ValueError, "another synthesis identity"):
                predicted.budget(10, groups, self.rate(), synthesis_identity=other)
        with self.assertRaisesRegex(ValueError, "another locale"):
            predicted.fit_rate(self.rows(), "es", synthesis_identity=IDENTITY)
        unhashed = [{key: value for key, value in row.items() if key != "audioSha256"} for row in self.rows()]
        with self.assertRaisesRegex(ValueError, "audioSha256"):
            predicted.fit_rate(unhashed, "ko", synthesis_identity=IDENTITY)
        job = {"targetLocale": "ko", "adapter": {**{k: v for k, v in IDENTITY.items() if k != "targetLocale"},
                                                 "capabilityStatus": "verified"}}
        self.assertEqual(predicted.synthesis_identity(job), IDENTITY)
        with self.assertRaises(ValueError):
            predicted.synthesis_identity({"targetLocale": "ko", "adapter": {"voice": "v1"}})

    def test_budget_shortens_only_the_long_group_and_fits_8s(self):
        groups = [{"gid": "g1", "sourceStart": 0, "sourceEnd": 3, "text": "가" * 15},
                  {"gid": "g2", "sourceStart": 3, "sourceEnd": 5, "text": "가" * 120},
                  {"gid": "g3", "sourceStart": 5.5, "sourceEnd": 8, "text": "가" * 15}]
        result = predicted.budget(30, groups, self.rate(), synthesis_identity=IDENTITY)
        self.assertEqual(result["status"], "requires_spoken_revision")
        self.assertEqual(result["shortenGroupIds"], ["g2"])
        self.assertEqual(result["budgetedScheduleStatus"], "pass")
        self.assertLess(result["groups"][1]["maxSpeechUnits"], 120)
        self.assertEqual(result["groups"][2]["action"], "keep")
        self.assertEqual(result["modelCalls"], 0)

    def test_fitting_text_is_kept(self):
        groups = [{"gid": "a", "sourceStart": 0, "sourceEnd": 4, "text": "가" * 20}]
        self.assertEqual(predicted.budget(10, groups, self.rate(), synthesis_identity=IDENTITY)["status"], "fits")


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

    def final_receipts(self, locale, count=40, subtitle_only=0, fallback=0, sentences=None):
        """A candidate, its audio package and final QC receipts that screened exactly them."""
        sentences = sentences or [1] * count
        ids = [f"g{i:03d}" for i in range(count)]
        groups = [{"translationGroupId": gid, "sourceUnitIds": [f"{gid}-u{n}" for n in range(sentences[i])],
                   "targetText": f"{locale} text {gid}"} for i, gid in enumerate(ids)]
        candidate = {"targetLocale": locale, "groups": groups}
        package = {"targetLocale": locale, "targetLanguageCandidateJsonSha256": waiver.json_sha256(candidate),
                   "units": [{"textGroupId": group["translationGroupId"], "targetTextSha256": text_sha(group["targetText"]),
                              "audio": {"sha256": text_sha("audio " + group["translationGroupId"])}}
                             for group in groups]}
        text = {"locale": locale, "sourceTextFallbackGroupIds": ids[:fallback], "results": [
            {"groupId": gid, "nextAction": "source_text_fallback" if i < fallback else "keep",
             "targetTextSha256": text_sha(groups[i]["targetText"])} for i, gid in enumerate(ids)]}
        audio = {"locale": locale, "subtitleOnlyGroupIds": ids[count - subtitle_only:], "results": [
            {"groupId": gid, "nextAction": "subtitle_only" if i >= count - subtitle_only else "keep",
             "audioSha256": package["units"][i]["audio"]["sha256"]} for i, gid in enumerate(ids)]}
        return candidate, package, text, audio

    def waive(self, locale, receipts, calibration):
        candidate, package, text, audio = receipts
        return waiver.waive(locale, candidate, text, audio, calibration, audio_package=package)

    def test_waiver_requires_semantic_calibration(self):
        receipts = self.final_receipts("ko")
        blocked = self.waive("ko", receipts, self.calibration("ko", semantic=False))
        self.assertEqual(blocked["status"], "blocked_calibration")
        self.assertFalse(blocked["releaseEligible"])
        waived = self.waive("ko", receipts, self.calibration("ko"))
        self.assertEqual(waived["status"], "machine_quality_waived")
        self.assertFalse(waived["humanApproval"])
        self.assertIn("기계 품질 검사", waived["disclosure"])
        self.assertEqual(waived["candidateSha256"], waiver.json_sha256(receipts[0]))
        self.assertEqual(waived["audioPackageSha256"], waiver.json_sha256(receipts[1]))

    def test_five_percent_rules(self):
        calibration = self.calibration("es")
        self.assertEqual(self.waive("es", self.final_receipts("es", subtitle_only=2), calibration)["status"],
                         "machine_quality_waived")
        result = self.waive("es", self.final_receipts("es", subtitle_only=3), calibration)
        self.assertEqual(result["status"], "machine_quality_waived_text_only")
        self.assertFalse(result["audioAvailable"])
        self.assertEqual(self.waive("es", self.final_receipts("es", fallback=3), calibration)["status"],
                         "blocked_text_quality")

    def test_five_percent_counts_sentences_not_groups(self):
        calibration = self.calibration("ko")
        # One failing ten-sentence group among 20 is 10/29 sentences, not 1/20 groups.
        receipts = self.final_receipts("ko", count=20, subtitle_only=1, sentences=[1] * 19 + [10])
        result = self.waive("ko", receipts, calibration)
        self.assertEqual(result["status"], "machine_quality_waived_text_only")
        self.assertEqual((result["sentenceCount"], result["undubbedSentenceCount"]), (29, 10))
        receipts = self.final_receipts("ko", count=20, fallback=1, sentences=[10] + [1] * 19)
        self.assertEqual(self.waive("ko", receipts, calibration)["status"], "blocked_text_quality")
        receipts = self.final_receipts("ko", count=20, subtitle_only=1, sentences=[10] * 19 + [1])
        self.assertEqual(self.waive("ko", receipts, calibration)["status"], "machine_quality_waived")

    def test_qc_receipts_must_bind_the_candidate_and_audio(self):
        calibration = self.calibration("ko")
        candidate, package, text, audio = self.final_receipts("ko")
        edited = copy.deepcopy(candidate)
        edited["groups"][4]["targetText"] = "changed after QC"
        with self.assertRaisesRegex(ValueError, "Text QC screened different text"):
            waiver.waive("ko", edited, text, audio, calibration, audio_package=package)
        with self.assertRaisesRegex(ValueError, "another candidate"):
            other = copy.deepcopy(package)
            other["targetLanguageCandidateJsonSha256"] = "0" * 64
            waiver.waive("ko", candidate, text, audio, calibration, audio_package=other)
        regenerated = copy.deepcopy(package)
        regenerated["units"][7]["audio"]["sha256"] = "9" * 64
        regenerated["targetLanguageCandidateJsonSha256"] = waiver.json_sha256(candidate)
        with self.assertRaisesRegex(ValueError, "Audio QC screened different audio"):
            waiver.waive("ko", candidate, text, audio, calibration, audio_package=regenerated)
        with self.assertRaisesRegex(ValueError, "needs the audio package"):
            waiver.waive("ko", candidate, text, audio, calibration)
        self.assertEqual(waiver.waive("ko", candidate, text, None, calibration)["status"],
                         "machine_quality_waived_text_only")

    def test_untested_or_missing_calibration_kinds_block(self):
        calibration = self.calibration("ko")
        receipts = self.final_receipts("ko")
        untested = copy.deepcopy(calibration)
        untested["kinds"]["text.dropped_name"].update(trials=0, detected=0, rate=0.0)
        result = self.waive("ko", receipts, untested)
        self.assertEqual(result["status"], "blocked_calibration")
        self.assertIn("calibration has no trials for ['text.dropped_name']", result["reasons"])
        missing = copy.deepcopy(calibration)
        del missing["kinds"]["audio.silent"]
        self.assertIn("calibration lacks seeded-error kinds ['audio.silent']",
                      self.waive("ko", receipts, missing)["reasons"])
        text_only = seeded.calibrate("ko", fixtures.groups("ko"), None, policy=fixtures.policy("ko"),
                                     call=fixtures.PerfectSemanticJudge("ko"))
        self.assertEqual(self.waive("ko", receipts, text_only)["status"], "blocked_calibration")
        candidate, _, text, _ = receipts
        self.assertEqual(waiver.waive("ko", candidate, text, None, text_only)["status"],
                         "machine_quality_waived_text_only")

    def test_pending_repairs_and_stale_calibration_block(self):
        calibration = self.calibration("zh-Hans")
        receipts = self.final_receipts("zh-Hans")
        receipts[3]["results"][0]["nextAction"] = "resynthesize_new_seed"
        self.assertEqual(self.waive("zh-Hans", receipts, calibration)["status"], "repair_in_progress")
        stale = copy.deepcopy(calibration)
        stale["implementationSha256"] = "0" * 64
        self.assertEqual(self.waive("zh-Hans", self.final_receipts("zh-Hans"), stale)["status"],
                         "blocked_calibration")

if __name__ == "__main__":
    unittest.main()
