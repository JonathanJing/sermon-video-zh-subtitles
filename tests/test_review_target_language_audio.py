import copy
import unittest

from scripts import review_target_language_audio as subject
from scripts import stage_formal_multilingual_dev as stage


SHA = "a" * 64
TRACK = "b" * 64
AUDIO = "c" * 64
TEXT = "d" * 64


def fixture():
    package = {
        "schemaVersion": "sermon-target-language-audio-package-v1",
        "packageId": "target-audio-zh", "englishSourcePackageJsonSha256": SHA,
        "targetLanguageCandidateJsonSha256": SHA,
        "targetLanguageSpeechJobJsonSha256": SHA, "targetLocale": "zh-Hans",
        "status": "candidate", "ratePolicy": "natural_no_time_stretch",
        "voice": None,
        "units": [{"textGroupId": "g1", "targetTextSha256": TEXT,
                   "audio": {"path": "languages/zh-Hans/audio/u1.wav", "sha256": AUDIO},
                   "durationSeconds": 1.0}],
        "track": {"path": "languages/zh-Hans/audio/track.wav", "sha256": TRACK},
        "captions": {"path": "languages/zh-Hans/synchronization/captions.json", "sha256": SHA},
        "schedule": {"path": "languages/zh-Hans/synchronization/schedule.json",
                     "sha256": SHA, "jsonSha256": SHA},
        "machineScreening": {"status": "requires_review", "model": "Qwen3-ASR",
                             "coverage": 1.0},
        "humanReview": {"status": "pending", "humanApproval": False,
                        "reviewedBy": None, "reviewedAt": None, "fullPlayback": "pending"},
        "issues": [], "downstreamInvalidationKey": SHA,
    }
    screening = {
        "schemaVersion": "sermon-target-language-audio-screening-v1",
        "targetLocale": "zh-Hans", "targetLanguageSpeechJobJsonSha256": SHA,
        "trackSha256": TRACK, "status": "requires_review",
        "model": "Qwen3-ASR", "modelRevision": "weights:sha256:" + SHA,
        "minSimilarity": 0.88, "coverage": 1.0, "reviewedGroupIds": ["g1"],
        "unitAudioSha256s": [AUDIO],
        "results": [{"textGroupId": "g1", "targetTextSha256": TEXT,
                     "audioSha256": AUDIO, "recognized": "alternate spelling",
                     "similarity": 0.85, "differences": [],
                     "status": "requires_review"}],
        "humanListeningStatus": "pending",
    }
    return package, screening


class AudioReviewTests(unittest.TestCase):
    def test_requires_explicit_adjudication_before_human_reviewed(self):
        package, screening = fixture()
        worksheet = subject.prepare(package, screening)
        worksheet.update(decision="approved", reviewedBy="user",
                         reviewedAt="2026-09-23T12:00:00-07:00",
                         fullPlayback="approved", videoSync1x="approved",
                         checks={name: "approved" for name in subject.CHECKS})
        with self.assertRaisesRegex(ValueError, "ASR uncertainty"):
            subject.approve(package, screening, worksheet)
        worksheet["asrAdjudications"][0].update(
            decision="approved", evidence="Heard the complete approved term at 1x.")
        reviewed, receipt = subject.approve(package, screening, worksheet)
        self.assertEqual(reviewed["status"], "human_reviewed")
        self.assertEqual(reviewed["machineScreening"]["status"], "requires_review")
        self.assertEqual(receipt["asrAdjudications"][0]["textGroupId"], "g1")
        stage.validate_audio_screening_review(reviewed, receipt, screening)
        altered = copy.deepcopy(screening)
        altered["results"][0]["audioSha256"] = SHA
        with self.assertRaisesRegex(stage.StageError, "ASR receipt"):
            stage.validate_audio_screening_review(reviewed, receipt, altered)

    def test_legacy_receipt_cannot_clear_asr_review_queue(self):
        package, _ = fixture()
        with self.assertRaisesRegex(stage.StageError, "v2 human adjudication"):
            stage.validate_audio_screening_review(
                package, {"schemaVersion": "sermon-target-language-audio-human-review-receipt-v1"},
                None)


if __name__ == "__main__":
    unittest.main()
