import hashlib
from pathlib import Path
import tempfile
import unittest
import wave

from scripts import screen_target_language_audio_units as subject
from scripts import sermon_sentence_interpretation as identity


class FormalAudioScreenTests(unittest.TestCase):
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
            model="fixture-asr", model_revision="fixture-v1")

    def test_exact_two_unit_audio_gets_source_bound_machine_pass_only(self):
        receipt, screened = self.run_screen([unit["text"] for unit in self.job["units"]])
        self.assertEqual(receipt["status"], "pass")
        self.assertEqual(receipt["coverage"], 1.0)
        self.assertEqual(receipt["humanListeningStatus"], "pending")
        self.assertEqual(screened["machineScreening"]["status"], "pass")
        self.assertEqual(receipt["reviewedGroupIds"], ["g0", "g1"])
        self.assertEqual(receipt["trackSha256"], self.manifest["track"]["sha256"])

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
