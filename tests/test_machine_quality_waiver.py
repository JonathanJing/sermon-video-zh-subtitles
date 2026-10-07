import copy
import hashlib
import io
import json
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import unittest
import wave

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
ROOT = Path(__file__).resolve().parents[1]
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

    def test_spoken_years_are_not_added_up(self):
        self.assertEqual(rules.english_numbers("In twenty twenty-four and nineteen ninety-nine"), [2024, 1999])
        self.assertEqual(rules.english_numbers("twenty oh five, fourteen ninety-two"), [2005, 1492])
        self.assertEqual(rules.english_numbers("twenty five people, nineteen hundred"), [25, 1900])
        self.assertEqual(rules.number_problems("In twenty twenty-four we moved.", "2024년에 이사했습니다.", "ko", set()), [])

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

    def test_scripture_book_must_survive_translation(self):
        english = "Turn to Revelation 3:4."
        for locale, good, bad in (("es", "Vayan a Apocalipsis 3:4.", "Vayan a Juan 3:4."),
                                  ("ko", "요한계시록 3장 4절을 보십시오.", "요한복음 3장 4절을 보십시오."),
                                  ("zh-Hans", "请看启示录3章4节。", "请看约翰福音3章4节。")):
            self.assertEqual(rules.scripture_reference_problems(english, good, locale), [], locale)
            self.assertIn("book changed for 3:4", rules.scripture_reference_problems(english, bad, locale))
            self.assertIn("book changed for 3:4", rules.scripture_reference_problems(
                english, seeded.mutate_text({"english": english, "targetText": good}, "wrong_book", locale, None),
                locale))
        # Numbered books are told apart by their number.
        self.assertIn("book changed for 4:8", rules.scripture_reference_problems(
            "As 1 John 4:8 says", "Como dice Juan 4:8", "es"))
        self.assertEqual(rules.scripture_reference_problems("As 1 John 4:8 says", "Como dice 1 Juan 4:8", "es"), [])
        self.assertEqual(rules.scripture_reference_problems("As 1 John 4:8 says", "요한일서 4장 8절 말씀처럼", "ko"), [])

    def test_short_copied_english_is_untranslated(self):
        for english in ("God loves you.", "This is it!", "Thank you"):
            self.assertEqual(rules.untranslated_problems(english, english, "es"),
                             ["English source text copied into target"], english)
            self.assertEqual(rules.untranslated_problems(english, f"Dice: {english}", "es"),
                             ["English source text copied into target"], english)
        # Folding makes these match, but they are Spanish.
        for english, target in (("Amen.", "Amén."), ("Jesus.", "Jesús."), ("No.", "No."),
                                ("God loves you.", "Dios te ama."), ("Pastor Ken", "Pastor Ken")):
            self.assertEqual(rules.untranslated_problems(english, target, "es"), [], target)

    def test_book_ordinals_are_not_cardinals(self):
        # "1 John" is 요한일서 / Primera de Juan / 约翰一书, never a separate "1".
        english = "As 1 John 4:8 says, God is love."
        for locale, target in (("ko", "요한일서 4장 8절 말씀처럼 하나님은 사랑이십니다."),
                               ("es", "Como dice Primera de Juan 4:8, Dios es amor."),
                               ("zh-Hans", "正如约翰一书4章8节说，神就是爱。")):
            self.assertEqual(rules.number_problems(english, target, locale, {(4, 8)}), [], locale)
        # A cardinal said beside the ordinal still has to survive.
        for locale, target in (("ko", "요한일서에서 그는 다시 말합니다."), ("es", "En Primera de Juan lo dice otra vez.")):
            self.assertEqual(rules.number_problems("In 1 John he says it 1 more time.", target, locale, set()),
                             ["missing number 1"], locale)
        self.assertEqual(rules.number_problems("In 2 Peter he says it 2 more times.", "在彼得后书里他又说了。",
                                               "zh-Hans", set()), ["missing number 2"])

    def test_dropped_chapter_after_a_book_is_a_missing_number(self):
        english = "Turn to Revelation 3."
        for locale, good, bad in (("ko", "요한계시록 3장을 펴십시오.", "요한계시록을 펴십시오."),
                                  ("es", "Vayan a Apocalipsis 3.", "Vayan a Apocalipsis."),
                                  ("zh-Hans", "请翻到启示录3章。", "请翻到启示录。")):
            self.assertEqual(rules.number_problems(english, good, locale, set()), [], locale)
            self.assertEqual(rules.number_problems(english, bad, locale, set()), ["missing number 3"], locale)

    def test_bible_book_table_matches_the_scripture_index(self):
        from scripts import build_scripture_index as index
        table = {code: chinese for code, *_, chinese in rules._BIBLE_BOOKS}
        self.assertEqual(table, {code: chinese for code, (_, chinese) in index.BOOKS.items()})

    def test_added_chapter_only_reference_is_rejected(self):
        english = "He said a few remain."
        self.assertIn("added chapter 3", rules.scripture_reference_problems(english, "몇 명이 남았습니다. 요한복음 3장", "ko"))
        self.assertIn("added chapter 3", rules.scripture_reference_problems(english, "Quedan unos pocos. Juan capítulo 3", "es"))
        self.assertIn("added chapter 3", rules.scripture_reference_problems(english, "还剩几个人。约翰福音3章", "zh-Hans"))
        # A count the English said is not a citation, unless a book name makes it one.
        self.assertEqual(rules.scripture_reference_problems("Take three sheets.", "종이 3장을 가져가세요.", "ko"), [])
        self.assertEqual(rules.scripture_reference_problems("Read three chapters a day.", "每天读三章。", "zh-Hans"), [])
        self.assertIn("added chapter 3", rules.scripture_reference_problems(
            "Take three sheets.", "Toma tres hojas. Juan capítulo 3", "es"))
        self.assertIn("added chapter 3", rules.scripture_reference_problems(
            "Take three sheets.", "종이 3장을 가져가세요. 요한복음 3장", "ko"))
        # "Revelation 3" names the chapter even without "chapter" or a verse.
        self.assertEqual(rules.scripture_reference_problems(
            "Turn to Revelation 3 tonight.", "오늘 밤 요한계시록 3장을 펴십시오.", "ko"), [])
        self.assertEqual(rules.scripture_reference_problems(
            "Turn to Revelation three.", "Abran Apocalipsis capítulo 3.", "es"), [])

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

    def test_chinese_must_be_simplified(self):
        self.assertEqual(rules.script_problems("恩典不是我们赚来的，而是我们领受的礼物。", "zh-Hans"), [])
        self.assertTrue(rules.script_problems("恩典不是我們賺來的，而是我們領受的禮物。", "zh-Hans"))
        self.assertTrue(rules.script_problems("恵みは私たちが受け取る贈り物です", "zh-Hans"))
        cuv = (ROOT / "data/scripture/cmn-cu89s.json").read_text(encoding="utf-8")
        self.assertEqual(sorted(set(cuv) & rules._TRADITIONAL_ONLY), [])

    def test_spanish_register_catches_pro_drop_vosotros(self):
        import re
        for text in ("Ya lo decís", "Si vivís así", "Sois la luz", "Vais a ver", "Vuestra fe", "Dios os ama"):
            self.assertTrue(re.search(es_weekly_auto.FORBIDDEN_REGISTER, text, re.I), text)
        for text in ("Nuestro país", "Vivimos en París", "Ustedes dicen", "Sí, así es", "Luís vino"):
            self.assertFalse(re.search(es_weekly_auto.FORBIDDEN_REGISTER, text, re.I), text)

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
                                    call=fixtures.PerfectSemanticJudge(locale), identity=fixtures.SEMANTIC_IDENTITY)
            self.assertEqual(judged["status"], "pass", locale)
            self.assertFalse(judged["humanApproval"])
            self.assertEqual(judged["semanticIdentity"], fixtures.SEMANTIC_IDENTITY)
        with self.assertRaisesRegex(ValueError, "semantic identity"):
            text_qc.screen(groups, locale, call=fixtures.PerfectSemanticJudge(locale))

    def test_back_translation_failure_follows_four_step_ladder(self):
        groups = fixtures.groups("ko")
        groups[3] = {**groups[3], "targetText": "은혜는 선물입니다."}
        judge = fixtures.PerfectSemanticJudge("ko")
        first = text_qc.screen(groups, "ko", policy=fixtures.policy("ko"), call=judge,
                               identity=fixtures.SEMANTIC_IDENTITY)
        row = first["results"][3]
        self.assertEqual((row["status"], row["nextAction"], row["failedAttempts"]),
                         ("fail", "revise_translation", 1))
        last = text_qc.screen(groups, "ko", policy=fixtures.policy("ko"), call=judge,
                              identity=fixtures.SEMANTIC_IDENTITY, prior_failed_attempts={"g004": 4})
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
        low = audio_qc.asr_opinion(0.5, audio=units[0]["wav"], text=units[0]["text"], model=fixtures.PRIMARY_ASR)
        units[0] = {**units[0], "asr": {"primary": low}}
        self.assertEqual(audio_qc.screen(units, "zh-Hans")["results"][0]["nextAction"], "run_secondary_asr")
        strong = audio_qc.asr_opinion(0.95, audio=units[0]["wav"], text=units[0]["text"], model=fixtures.SECONDARY_ASR)
        units[0] = {**units[0], "asr": {"primary": low, "secondary": strong}}
        row = audio_qc.screen(units, "zh-Hans")["results"][0]
        self.assertEqual((row["status"], row["asrSecondaryModel"]["model"]), ("pass", fixtures.SECONDARY_ASR))
        same = audio_qc.asr_opinion(0.95, audio=units[0]["wav"], text=units[0]["text"], model=fixtures.PRIMARY_ASR)
        units[0] = {**units[0], "asr": {"primary": low, "secondary": same}}
        with self.assertRaisesRegex(ValueError, "different model"):
            audio_qc.screen(units, "zh-Hans")

    def test_asr_scores_bind_the_current_audio_and_text(self):
        units = fixtures.units("ko")
        # Resynthesized audio keeping the earlier render's opinion: the stale score does not count.
        samples, rate = audio_qc.decode_pcm16(units[2]["wav"])
        resynthesized = audio_qc.encode_pcm16(samples + samples[:400], rate)
        units[2] = {**units[2], "wav": resynthesized}
        row = audio_qc.screen(units, "ko")["results"][2]
        self.assertEqual((row["status"], row["staleAsr"], row["asrPrimary"]),
                         ("pending_primary_asr", ["primary"], None))
        # An opinion about other text does not count either.
        other = audio_qc.asr_opinion(0.99, audio=resynthesized, text="다른 문장입니다.", model=fixtures.PRIMARY_ASR)
        units[2] = {**units[2], "asr": {"primary": other}}
        self.assertEqual(audio_qc.screen(units, "ko")["results"][2]["status"], "pending_primary_asr")
        with self.assertRaisesRegex(ValueError, "Bare ASR scores"):
            audio_qc.screen([{**units[0], "asrPrimary": 0.97}], "ko")

    def test_edge_silence_is_an_issue(self):
        units = fixtures.units("es")
        samples, rate = audio_qc.decode_pcm16(units[4]["wav"])
        padded = audio_qc.encode_pcm16([0.0] * (2 * rate) + samples, rate)
        text = units[4]["text"]
        units[4] = {**units[4], "wav": padded, "asr": {"primary": audio_qc.asr_opinion(
            0.97, audio=padded, text=text, model=fixtures.PRIMARY_ASR)}}
        row = audio_qc.screen(units, "es")["results"][4]
        self.assertEqual(row["status"], "fail")
        self.assertTrue(any(issue.startswith("leading_silence") for issue in row["issues"]), row["issues"])

    def test_missing_primary_asr_never_passes(self):
        units = fixtures.units("ko")
        units[1] = {key: value for key, value in units[1].items() if key != "asr"}
        result = audio_qc.screen(units, "ko")
        row = result["results"][1]
        self.assertEqual((row["status"], row["nextAction"]), ("pending_primary_asr", "run_primary_asr"))
        self.assertEqual(result["status"], "requires_repair")
        self.assertEqual(row["audioSha256"], hashlib.sha256(units[1]["wav"]).hexdigest())
        # An acoustic failure is still a failure without ASR.
        units[1] = {**units[1], "wav": audio_qc.encode_pcm16([0.0] * 16000, 8000)}
        self.assertEqual(audio_qc.screen(units, "ko")["results"][1]["status"], "fail")


    def test_metrics_come_from_the_wav_only(self):
        units = fixtures.units("ko")
        samples, rate = audio_qc.decode_pcm16(units[0]["wav"])
        clean_metrics = audio_qc.signal_metrics(samples, rate)
        with self.assertRaisesRegex(ValueError, "supplied metrics are not accepted"):
            audio_qc.screen([{**units[0], "metrics": clean_metrics}] + units[1:], "ko")
        with self.assertRaisesRegex(ValueError, "supplied metrics are not accepted"):
            audio_qc.screen([{key: value for key, value in units[0].items() if key != "wav"}] + units[1:], "ko")


def pcm_wav(pcm, rate, channels=1):
    out = io.BytesIO()
    with wave.open(out, "wb") as stream:
        stream.setnchannels(channels)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(pcm)
    return out.getvalue()


class TrackCheckTests(unittest.TestCase):
    """The assembled track must be the screened unit audio at its scheduled starts."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.units = fixtures.units("ko")[:4]
        self.rate = audio_qc.decode_pcm16(self.units[0]["wav"])[1]

    def write(self, name, data):
        path = self.dir / name
        path.write_bytes(data)
        return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest()}

    def package(self, track_units=None, *, mp3=None):
        start, entries, units = 0.5, [], []
        for unit in self.units:
            gid = unit["groupId"]
            units.append({"textGroupId": gid, "audio": self.write(f"{gid}.wav", unit["wav"])})
            entries.append({"textGroupId": gid, "plannedStart": start})
            start += len(audio_qc.decode_pcm16(unit["wav"])[0]) / self.rate + 0.4
        schedule = {"entries": entries}
        schedule_artifact = self.write("schedule.json", json.dumps(schedule).encode())
        schedule_artifact["jsonSha256"] = waiver.json_sha256(schedule)
        length = round((start + 0.5) * self.rate)
        pcm, rate, channels = audio_qc.scheduled_track(
            entries, track_units or [unit["wav"] for unit in self.units], length)
        track = self.write("track.wav", pcm_wav(pcm, rate, channels))
        if mp3 is not None:
            track = self.write("track.mp3", mp3(Path(track["path"])))
        return {"targetLocale": "ko", "schedule": schedule_artifact, "track": track, "units": units}

    def test_exact_pcm_track_passes_and_binds_the_package(self):
        package = self.package()
        result = audio_qc.check_track(package)
        self.assertEqual((result["status"], result["issues"], result["humanApproval"]), ("pass", [], False))
        self.assertEqual(result["targetLanguageAudioPackageJsonSha256"], waiver.json_sha256(package))
        self.assertEqual(result["unitAudioSha256s"], [unit["audio"]["sha256"] for unit in package["units"]])
        self.assertEqual(result["implementationSha256"], waiver.implementation_sha256())
        from scripts import machine_quality_release_basis as basis
        self.assertEqual(basis.track_check_problems(package, result, waiver.implementation_sha256()), [])

    def test_omitted_or_reordered_units_fail(self):
        silent = audio_qc.encode_pcm16([0.0] * len(audio_qc.decode_pcm16(self.units[1]["wav"])[0]), self.rate)
        wavs = [unit["wav"] for unit in self.units]
        for track_units in ([wavs[0], silent, *wavs[2:]], [wavs[1], wavs[0], *wavs[2:]]):
            result = audio_qc.check_track(self.package(track_units))
            self.assertEqual(result["issues"], ["pcm_track_differs_from_scheduled_units"])

    def test_changed_unit_or_schedule_bytes_are_refused(self):
        package = self.package()
        Path(package["units"][2]["audio"]["path"]).write_bytes(self.units[0]["wav"])
        with self.assertRaisesRegex(ValueError, "Unit g003 audio bytes differ"):
            audio_qc.check_track(package)
        package = self.package()
        package["schedule"]["jsonSha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "Schedule JSON differs"):
            audio_qc.check_track(package)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is not installed")
    def test_mp3_follows_its_pcm_master(self):
        def encode(source, target=None):
            out = self.dir / "encoded.mp3"
            subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(target or source),
                            "-b:a", "64k", str(out)], check=True)
            return out.read_bytes()
        package = self.package(mp3=encode)
        result = audio_qc.check_track(package)
        self.assertEqual((result["status"], result["method"]["compressed"]), ("pass", "decoded_waveform"))
        from scripts import machine_quality_release_basis as basis
        self.assertEqual(basis.track_check_problems(package, result, waiver.implementation_sha256()), [])
        self.assertLessEqual(result["envelope"]["deviantWindows"], 0.02 * result["envelope"]["windows"])
        # An MP3 of silence beside a correct master is not what listeners should hear.
        silence = self.dir / "silence.wav"
        with wave.open(io.BytesIO(Path(self.package()["track"]["path"]).read_bytes())) as stream:
            frames = stream.getnframes()
        silence.write_bytes(pcm_wav(bytes(frames * 2), self.rate))
        result = audio_qc.check_track(self.package(mp3=lambda source: encode(source, silence)))
        self.assertIn("compressed_track_differs_from_pcm_master", result["issues"])


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
    def calibration(self, locale, *, semantic=True, asr=True):
        call = fixtures.PerfectSemanticJudge(locale) if semantic else None
        return seeded.calibrate(locale, fixtures.groups(locale), fixtures.units(locale),
                                policy=fixtures.policy(locale), call=call,
                                identity=fixtures.SEMANTIC_IDENTITY if semantic else None,
                                asr=fixtures.FakeAsr(locale) if asr else None)

    def test_calibration_has_no_false_positives_on_clean_fixtures(self):
        for locale in LOCALES:
            result = self.calibration(locale, semantic=False)
            self.assertEqual(result["cleanFalsePositives"], 0, locale)
            for kind in ("text.english_leak", "text.placeholder", "text.added_reference", "text.wrong_book",
                         "audio.stretched", "audio.silent", "audio.clipped", "audio.truncated",
                         "audio.wrong_sentence"):
                self.assertEqual(result["kinds"][kind]["rate"], 1.0, (locale, kind))
            self.assertFalse(result["semanticChecksIncluded"])
            self.assertEqual(result["asrIdentity"]["secondary"]["model"], fixtures.SECONDARY_ASR)

    def test_wrong_sentence_needs_the_asr_path(self):
        without = self.calibration("ko", asr=False)
        self.assertEqual(without["kinds"]["audio.wrong_sentence"]["trials"], 0)
        self.assertIn("calibration has no trials for ['audio.wrong_sentence']",
                      waiver.calibration_problems(without, "ko", waiver.implementation_sha256(), require_audio=True))
        # An ASR integration that always agrees catches nothing.
        broken = seeded.calibrate("ko", fixtures.groups("ko"), fixtures.units("ko"), policy=fixtures.policy("ko"),
                                  asr=fixtures.FakeAsr("ko", primary_similarity_on_mismatch=0.97))
        self.assertEqual(broken["kinds"]["audio.wrong_sentence"]["rate"], 0.0)

    def test_baseline_false_positives_are_not_credited(self):
        groups = fixtures.groups("ko")
        # A clean group that already fails (a stray placeholder) must not count as detecting other kinds.
        groups[7] = {**groups[7], "targetText": groups[7]["targetText"] + " TODO"}
        result = seeded.calibrate_text(groups, "ko", policy=fixtures.policy("ko"))
        self.assertEqual(result["cleanFalsePositives"], 1)
        self.assertEqual(result["kinds"]["placeholder"]["detected"], result["kinds"]["placeholder"]["trials"] - 1)
        self.assertIn("g008", result["kinds"]["placeholder"]["missedGroupIds"])

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
        text = {"locale": locale, "sourceTextFallbackGroupIds": ids[:fallback],
                "implementationSha256": waiver.implementation_sha256(),
                "semanticIdentitySha256": text_qc.semantic_identity(fixtures.SEMANTIC_IDENTITY)["sha256"],
                "results": [{"groupId": gid, "nextAction": "source_text_fallback" if i < fallback else "keep",
                             "targetTextSha256": text_sha(groups[i]["targetText"])} for i, gid in enumerate(ids)]}
        audio = {"locale": locale, "subtitleOnlyGroupIds": ids[count - subtitle_only:],
                 "implementationSha256": waiver.implementation_sha256(), "results": [
            {"groupId": gid, "nextAction": "subtitle_only" if i >= count - subtitle_only else "keep",
             "audioSha256": package["units"][i]["audio"]["sha256"],
             "textSha256": package["units"][i]["targetTextSha256"],
             "asrPrimaryModel": {"model": fixtures.PRIMARY_ASR, "modelRevision": None}, "asrSecondaryModel": None}
            for i, gid in enumerate(ids)]}
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
        retexted = copy.deepcopy(audio)
        retexted["results"][3]["textSha256"] = text_sha("another script")
        with self.assertRaisesRegex(ValueError, "against different text"):
            waiver.waive("ko", candidate, text, retexted, calibration, audio_package=package)
        self.assertEqual(waiver.waive("ko", candidate, text, None, calibration)["status"],
                         "machine_quality_waived_text_only")

    def test_summary_lists_must_match_the_group_results(self):
        calibration = self.calibration("ko")
        candidate, package, text, audio = self.final_receipts("ko", fallback=1, subtitle_only=1)
        self.assertEqual(waiver.waive("ko", candidate, text, audio, calibration, audio_package=package)["status"],
                         "machine_quality_waived")
        hidden_text = copy.deepcopy(text)
        hidden_text["sourceTextFallbackGroupIds"] = []
        with self.assertRaisesRegex(ValueError, "fallback list differs"):
            waiver.waive("ko", candidate, hidden_text, audio, calibration, audio_package=package)
        hidden_audio = copy.deepcopy(audio)
        hidden_audio["subtitleOnlyGroupIds"] = []
        with self.assertRaisesRegex(ValueError, "subtitle-only list differs"):
            waiver.waive("ko", candidate, text, hidden_audio, calibration, audio_package=package)

    def test_condensed_spoken_groups_need_spoken_calibration(self):
        calibration = self.calibration("ko")
        candidate, package, text, audio = self.final_receipts("ko")
        text["results"][3]["mode"] = "spoken_condensed"
        with self.assertRaisesRegex(ValueError, "condensed-group list differs"):
            waiver.waive("ko", candidate, text, audio, calibration, audio_package=package)
        text["condensedGroupIds"] = ["g003"]
        result = waiver.waive("ko", candidate, text, audio, calibration, audio_package=package)
        self.assertEqual(result["status"], "blocked_calibration")
        self.assertIn("calibration did not include condensed spoken groups", result["reasons"])
        spoken = copy.deepcopy(calibration)
        spoken["spokenIncluded"] = True
        spoken["kinds"].update({f"spoken.{kind}": {"trials": 4, "detected": 4, "rate": 1.0}
                                for kind in waiver.SPOKEN_KINDS})
        spoken["trials"] += 4 * len(waiver.SPOKEN_KINDS)
        spoken["detected"] += 4 * len(waiver.SPOKEN_KINDS)
        self.assertEqual(waiver.waive("ko", candidate, text, audio, spoken, audio_package=package)["status"],
                         "machine_quality_waived")

    def test_non_finite_calibration_rates_block(self):
        calibration = self.calibration("ko")
        receipts = self.final_receipts("ko")
        for field in ("overallDetectionRate", "cleanFalsePositiveRate"):
            for value in (float("nan"), float("inf"), True, None, "0.99"):
                broken = copy.deepcopy(calibration)
                broken[field] = value
                self.assertEqual(self.waive("ko", receipts, broken)["status"], "blocked_calibration", (field, value))
        for kind in ("text.dropped_name", "audio.silent"):
            broken = copy.deepcopy(calibration)
            broken["kinds"][kind]["rate"] = float("nan")
            self.assertIn(f"seeded-error detection below minimum for ['{kind}']",
                          self.waive("ko", receipts, broken)["reasons"])
            broken["kinds"][kind].update(rate=1.0, trials=float("nan"))
            self.assertIn(f"calibration has no trials for ['{kind}']", self.waive("ko", receipts, broken)["reasons"])

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
                                     call=fixtures.PerfectSemanticJudge("ko"), identity=fixtures.SEMANTIC_IDENTITY)
        self.assertEqual(self.waive("ko", receipts, text_only)["status"], "blocked_calibration")
        candidate, _, text, _ = receipts
        self.assertEqual(waiver.waive("ko", candidate, text, None, text_only)["status"],
                         "machine_quality_waived_text_only")

    def test_qc_runtimes_must_match_the_calibration(self):
        calibration = self.calibration("ko")
        receipts = self.final_receipts("ko")
        weaker = copy.deepcopy(receipts)
        weaker[2]["semanticIdentitySha256"] = text_qc.semantic_identity(
            {**fixtures.SEMANTIC_IDENTITY, "model": "smaller-judge"})["sha256"]
        result = self.waive("ko", weaker, calibration)
        self.assertEqual(result["status"], "blocked_calibration")
        self.assertIn("back-translation runtime differs from calibration", result["reasons"])
        other_asr = copy.deepcopy(receipts)
        other_asr[3]["results"][5]["asrPrimaryModel"] = {"model": "other-asr", "modelRevision": None}
        self.assertIn("primary ASR model differs from calibration", self.waive("ko", other_asr, calibration)["reasons"])

    def test_text_only_release_ignores_audio_calibration(self):
        calibration = self.calibration("ko")
        calibration["kinds"]["audio.clipped"].update(detected=0, rate=0.0)
        self.recount(calibration)
        candidate, package, text, audio = self.final_receipts("ko")
        self.assertEqual(waiver.waive("ko", candidate, text, None, calibration)["status"],
                         "machine_quality_waived_text_only")
        self.assertEqual(waiver.waive("ko", candidate, text, audio, calibration, audio_package=package)["status"],
                         "blocked_calibration")

    @staticmethod
    def recount(calibration):
        calibration["trials"] = sum(row["trials"] for row in calibration["kinds"].values())
        calibration["detected"] = sum(row["detected"] for row in calibration["kinds"].values())
        calibration["overallDetectionRate"] = round(calibration["detected"] / calibration["trials"], 6)

    def test_semantic_only_seed_requires_new_backtranslation_issue(self):
        def always_pass(role, system, user, schema):
            return {"english": "A passage."} if role == "back_translator" else {"status": "pass", "issues": []}
        for locale in LOCALES:
            result = seeded.calibrate(locale, fixtures.groups(locale), policy=fixtures.policy(locale),
                                      call=always_pass, identity=fixtures.SEMANTIC_IDENTITY)
            row = result["kinds"]["text.semantic_negation"]
            self.assertGreater(row["trials"], 0, locale)
            self.assertEqual(row["detected"], 0, locale)
            self.assertTrue(waiver.calibration_problems(result, locale, waiver.implementation_sha256()))
            good = self.calibration(locale)
            self.assertEqual(good["kinds"]["text.semantic_negation"]["rate"], 1.0)

    def test_calibration_count_rate_inconsistencies_block(self):
        calibration = self.calibration("ko")
        for kind, value in (("text.wrong_number", {"detected": 0, "rate": 1.0}),
                            ("text.wrong_number", {"detected": True}),
                            ("text.wrong_number", {"trials": True}),
                            ("text.wrong_number", {"detected": -1}),
                            ("text.wrong_number", {"detected": 10000})):
            broken = copy.deepcopy(calibration)
            broken["kinds"][kind].update(value)
            self.assertTrue(waiver.calibration_problems(broken, "ko", waiver.implementation_sha256()))
        for field, value in (("overallDetectionRate", 0.0), ("trials", 1), ("detected", True),
                             ("cleanFalsePositives", 2), ("cleanChecked", 0), ("cleanFalsePositives", True)):
            broken = copy.deepcopy(calibration)
            broken[field] = value
            self.assertTrue(waiver.calibration_problems(broken, "ko", waiver.implementation_sha256()))

    def test_audio_trials_cannot_inflate_text_only_detection(self):
        calibration = self.calibration("ko")
        for kind, row in calibration["kinds"].items():
            row.update(trials=100, detected=94 if kind.startswith("text.") else 100,
                       rate=0.94 if kind.startswith("text.") else 1.0)
        self.recount(calibration)
        self.assertGreaterEqual(calibration["overallDetectionRate"], 0.95)
        self.assertIn("overall seeded-error detection below minimum",
                      waiver.calibration_problems(calibration, "ko", waiver.implementation_sha256()))

    def test_semantic_runtime_requires_settings_and_cache_revision(self):
        for key in ("settings", "modelRevision", "cacheNamespace"):
            identity = copy.deepcopy(fixtures.SEMANTIC_IDENTITY)
            del identity[key]
            with self.assertRaises(ValueError):
                text_qc.semantic_identity(identity)
        base = text_qc.semantic_identity(fixtures.SEMANTIC_IDENTITY)["sha256"]
        for key, value in (("modelRevision", "r2"), ("cacheNamespace", "another-cache"),
                           ("settings", {"temperature": 0.7, "reasoningEffort": "medium"})):
            self.assertNotEqual(base, text_qc.semantic_identity({**fixtures.SEMANTIC_IDENTITY, key: value})["sha256"])
        with self.assertRaises(ValueError):
            text_qc.semantic_identity({**fixtures.SEMANTIC_IDENTITY, "settings": {"temperature": float("nan")}})

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
