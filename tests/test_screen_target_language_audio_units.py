import hashlib
from pathlib import Path
import tempfile
import unittest
import wave

from scripts import screen_target_language_audio_units as subject
from scripts import sermon_sentence_interpretation as identity


class FormalAudioScreenTests(unittest.TestCase):
    def test_long_units_preserve_negations_numbers_and_names(self):
        cases = [
            ("en", "Jesus does not leave us alone when we are walking through difficult days.", "not "),
            ("zh-Hans", "耶稣不会在我们失败的时候丢下我们，他始终与我们同行。", "不"),
            ("ko", "예수님은 우리가 실패할 때 우리를 홀로 두지 않으십니다.", "않"),
            ("es", "Jesús no nos deja solos cuando pasamos por los momentos difíciles de nuestra vida.", "no "),
            ("en", "We saw twelve people waiting in the church after the service today.", "twelve "),
            ("zh-Hans", "今天我们看见教会门口有十二个人一直在等待牧师走出来。", "二"),
            ("es", "Hoy vimos doce personas esperando en la iglesia después del servicio de la mañana.", "doce "),
            ("ko", "오늘 교회 앞에서 이십일 명이 예배가 끝나기를 기다리고 있었습니다.", "일"),
            ("ko", "오늘 요한복음삼장사절에서 예수님께서 우리에게 하시는 말씀을 읽겠습니다.", "사"),
            ("en", "We heard Jesus speaking to the church as they gathered together today.", "Jesus "),
            ("en", "Paul spoke to all the people gathered in the church that morning.", "Paul "),
            ("zh-Hans", "今天我们在教会里听见耶稣对我们每一个人所说的话。", "耶稣"),
        ]
        for locale, expected, omitted in cases:
            with self.subTest(locale=locale, omitted=omitted):
                similarity, _, passed = subject.score(expected, expected.replace(omitted, "", 1), locale, 0.88)
                self.assertGreaterEqual(similarity, 0.88)
                self.assertFalse(passed)

    def test_punctuation_and_capitalization_remain_acceptable(self):
        self.assertTrue(subject.score("Jesus saves us every day.", "jesus saves us every day", "en", 0.88)[2])

    def test_contracted_negation_cannot_disappear_in_long_units(self):
        for negative, positive in (("can't", "can"), ("doesn't", "does"), ("won’t", "will")):
            expected = f"Jesus {negative} leave people alone in the church when they need help today."
            similarity, _, passed = subject.score(expected, expected.replace(negative, positive), "en", 0.88)
            self.assertGreaterEqual(similarity, 0.88)
            self.assertFalse(passed)

    def test_protected_names_cannot_swap_roles(self):
        expected = "Pedro dijo que Juan estaba escuchando toda la enseñanza que el pastor explicó a la iglesia durante la mañana."
        heard = expected.replace("Pedro", "Juan").replace("que Juan", "que Pedro")
        similarity, _, passed = subject.score(expected, heard, "es", 0.88)
        self.assertGreaterEqual(similarity, 0.88)
        self.assertFalse(passed)

    def test_korean_quantities_cannot_swap(self):
        expected = "그 집에는 두 아들과 세 딸이 함께 살고 있었습니다."
        heard = "그 집에는 세 아들과 두 딸이 함께 살고 있었습니다."
        similarity, _, passed = subject.score(expected, heard, "ko", 0.88)
        self.assertGreaterEqual(similarity, 0.88)
        self.assertFalse(passed)
        self.assertEqual(subject.korean_native_numbers("마흔네 해 동안 두 아들"), ["마흔네", "두"])
        self.assertTrue(subject.score(expected, expected, "ko", 0.88)[2])

    def test_spanish_one_cannot_disappear(self):
        expected = "Solo tienes una vida y debes permanecer fiel cada día."
        similarity, _, passed = subject.score(expected, expected.replace("una ", ""), "es", 0.88)
        self.assertGreaterEqual(similarity, 0.88)
        self.assertFalse(passed)
        # Un for una is article noise, not a lost quantity.
        self.assertTrue(subject.score(expected, expected.replace("una", "un"), "es", 0.88)[2])
        long = "Cada uno de nosotros recibe la gracia de Dios en esta mañana tranquila."
        self.assertFalse(subject.score(long, long.replace("uno ", ""), "es", 0.88)[2])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        units = []
        rows = []
        for index, text in enumerate(("세 가지 무기", "처음 사랑을 버렸느니라")):
            path = f"languages/ko/audio/unit-{index:04d}.wav"
            audio = self.root / path
            audio.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(audio), "wb") as stream:
                stream.setnchannels(1)
                stream.setsampwidth(2)
                stream.setframerate(16000)
                stream.writeframes(b"\0\0" * 16000)
            group_id = f"g{index}"
            units.append({"translationGroupId": group_id, "text": text,
                          "outputRelativePath": path})
            rows.append({"textGroupId": group_id,
                         "targetTextSha256": hashlib.sha256(text.encode()).hexdigest(),
                         "audio": {"path": path, "sha256": subject.file_sha(audio)}})
        self.job = {
            "schemaVersion": "sermon-target-language-speech-job-v2",
            "status": "prepared_for_target_language_speech",
            "synthesisEligible": True,
            "targetLocale": "ko",
            "inputs": {
                "englishSourcePackage": {"jsonSha256": "a" * 64},
                "targetLanguageCandidate": {"jsonSha256": "b" * 64},
            },
            "units": units,
        }
        self.manifest = {
            "schemaVersion": "sermon-target-language-render-manifest-v1",
            "targetLocale": "ko",
            "targetLanguageSpeechJobJsonSha256": identity.json_sha256(self.job),
            "englishSourcePackageJsonSha256": "a" * 64,
            "targetLanguageCandidateJsonSha256": "b" * 64,
            "machineScreening": {"status": "not_run", "model": None, "coverage": 0.0},
            "units": rows,
        }
        track_path = self.root / "languages/ko/audio/track.wav"
        with wave.open(str(track_path), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(16000)
            stream.writeframes(b"\0\0" * 16000)
        self.manifest["track"] = {"path": "languages/ko/audio/track.wav",
                                  "sha256": subject.file_sha(track_path)}

    def run_screen(self, transcripts):
        return subject.screen(
            self.job, self.manifest, self.root,
            lambda path, locale: transcripts[int(path.stem.split("-")[-1])],
            model="fixture-asr", model_revision="fixture-v1",
            inference_identity={"backend": "fixture-asr-local"})

    def test_exact_two_unit_audio_gets_source_bound_machine_pass_only(self):
        receipt, screened = self.run_screen([unit["text"] for unit in self.job["units"]])
        self.assertEqual(receipt["status"], "pass")
        self.assertEqual(receipt["coverage"], 1.0)
        self.assertEqual(receipt["humanListeningStatus"], "pending")
        self.assertEqual(screened["machineScreening"]["status"], "pass")
        self.assertEqual(receipt["reviewedGroupIds"], ["g0", "g1"])
        self.assertEqual(receipt["trackSha256"], self.manifest["track"]["sha256"])

    def test_receipt_v2_records_the_asr_runtime_behind_every_score(self):
        import json
        from jsonschema import Draft202012Validator
        from scripts.target_audio_auto_qc import screening_asr_settings
        receipt, _ = self.run_screen([unit["text"] for unit in self.job["units"]])
        self.assertEqual(receipt["schemaVersion"], "sermon-target-language-audio-screening-v2")
        schema = json.loads((Path(__file__).resolve().parents[1] / "schemas"
                             / "sermon-target-language-audio-screening-v2.schema.json").read_text())
        self.assertEqual(list(Draft202012Validator(schema).iter_errors(receipt)), [])
        settings = receipt["asrSettings"]
        self.assertEqual((settings["model"], settings["modelRevision"], settings["batchSize"],
                          settings["minSimilarity"]), ("fixture-asr", "fixture-v1", 1, 0.88))
        self.assertEqual(settings["implementationSha256"], subject.file_sha(Path(subject.__file__)))
        self.assertEqual(receipt["asrSettingsSha256"], identity.json_sha256(settings))
        self.assertEqual(screening_asr_settings(receipt), settings)
        # A receipt that does not name its ASR backend cannot back a machine waiver.
        bare, _ = subject.screen(self.job, self.manifest, self.root,
                                 lambda path, locale: [unit["text"] for unit in self.job["units"]][
                                     int(path.stem.split("-")[-1])],
                                 model="fixture-asr", model_revision="fixture-v1")
        with self.assertRaisesRegex(ValueError, "backend"):
            screening_asr_settings(bare)

    def test_missing_word_stays_in_review_queue(self):
        receipt, screened = self.run_screen(["세 가지", "처음 사랑을 버렸느니라"])
        self.assertEqual(receipt["status"], "requires_review")
        self.assertEqual(receipt["results"][0]["status"], "requires_review")
        self.assertTrue(receipt["results"][0]["differences"])
        self.assertEqual(screened["machineScreening"]["status"], "requires_review")

    def test_changed_audio_and_job_identity_fail_before_transcription(self):
        path = self.root / self.job["units"][0]["outputRelativePath"]
        path.write_bytes(path.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "audio hash mismatch"):
            self.run_screen(["", ""])
        self.manifest["targetLanguageSpeechJobJsonSha256"] = "c" * 64
        with self.assertRaisesRegex(ValueError, "differs from formal speech job"):
            self.run_screen(["", ""])


if __name__ == "__main__":
    unittest.main()
