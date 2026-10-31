import copy
import unittest

from tongxing_production.audio import human_review as subject
from tongxing_production.delivery import formal_stage as stage
from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.source import sentence_interpretation as identity


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
        "machineScreening": {"status": "not_run", "model": None, "coverage": 0.0},
        "humanReview": {"status": "pending", "humanApproval": False,
                        "reviewedBy": None, "reviewedAt": None, "fullPlayback": "pending"},
        "issues": [], "downstreamInvalidationKey": SHA,
    }
    return package


def approved_worksheet(package):
    worksheet = subject.prepare(package)
    worksheet.update(decision="approved", reviewedBy="user",
                     reviewedAt="2026-10-28T12:00:00-07:00",
                     fullPlayback="approved", videoSync1x="approved",
                     checks={name: "approved" for name in subject.CHECKS})
    return worksheet


class AudioReviewTests(unittest.TestCase):
    def test_full_playback_is_the_only_gate_and_issues_a_v5_receipt(self):
        package = fixture()
        reviewed, receipt = subject.approve(package, approved_worksheet(package))
        self.assertEqual(reviewed["status"], "human_reviewed")
        self.assertEqual(reviewed["machineScreening"]["status"], "not_run")
        self.assertEqual(receipt["schemaVersion"],
                         "sermon-target-language-audio-human-review-receipt-v5")
        self.assertNotIn("machineScreeningStatus", receipt)
        self.assertNotIn("asrAdjudications", receipt)
        stage.validate_audio_screening_review(reviewed, receipt, None)

    def test_without_full_playback_approval_nothing_is_accepted(self):
        package = fixture()
        worksheet = approved_worksheet(package)
        worksheet["fullPlayback"] = "pending"
        with self.assertRaisesRegex(ValueError, "Full playback"):
            subject.approve(package, worksheet)
        worksheet = approved_worksheet(package)
        worksheet["checks"]["completeness"] = "pending"
        with self.assertRaisesRegex(ValueError, "Full playback"):
            subject.approve(package, worksheet)

    def test_no_machine_review_queue_remains(self):
        package = fixture()
        self.assertEqual(subject.queue(package), [])
        package["status"] = "human_reviewed"
        with self.assertRaisesRegex(ValueError, "pending candidate"):
            subject.queue(package)

    def test_publication_exception_keeps_video_sync_unrun_and_exact_track(self):
        package = fixture()
        worksheet = approved_worksheet(package)
        checks = {name: "approved" for name in subject.CHECKS}
        checks["synchronization"] = "not_run"
        worksheet.update(videoSync1x="not_run", checks=checks)
        exception = {"schemaVersion": "sermon-video-sync-publication-exception-v1",
                     "scope": "publish_reviewed_chinese_audio_with_video_sync_not_run",
                     "humanApproval": True, "userDecision": "接受，先发布并如实保留未验收状态",
                     "recordedAt": "2026-10-28T19:00:00Z", "trackSha256": TRACK}
        with self.assertRaises(ValueError):
            subject.approve(package, worksheet)
        reviewed, receipt = subject.approve(package, worksheet, publication_exception=exception)
        self.assertEqual(receipt["videoSync1x"], "not_run")
        self.assertEqual(receipt["checks"]["synchronization"], "not_run")
        stage.validate_audio_screening_review(reviewed, receipt, None)
        altered = copy.deepcopy(receipt)
        altered["publicationException"]["trackSha256"] = SHA
        with self.assertRaises(stage.StageError):
            stage.validate_audio_screening_review(reviewed, altered, None)
        exception["humanApproval"] = False
        with self.assertRaises(ValueError):
            subject.approve(package, worksheet, publication_exception=exception)

    def test_locale_exception_binds_source_candidate_package_and_track(self):
        package = fixture()
        package["targetLocale"] = "es"
        worksheet = approved_worksheet(package)
        checks = {name: "approved" for name in subject.CHECKS}
        checks["synchronization"] = "not_run"
        worksheet.update(videoSync1x="not_run", checks=checks)
        expected_audio = copy.deepcopy(package)
        expected_audio["status"] = "human_reviewed"
        expected_audio["humanReview"] = {"status": "approved", "humanApproval": True,
            "reviewedBy": "user", "reviewedAt": worksheet["reviewedAt"], "fullPlayback": "approved"}
        expected_audio.pop("downstreamInvalidationKey")
        expected_audio["downstreamInvalidationKey"] = identity.json_sha256(expected_audio)
        reviewed_hash = identity.json_sha256(expected_audio)
        exception = {"schemaVersion": "sermon-video-sync-publication-exception-v2",
                     "scope": "publish_reviewed_audio_with_video_sync_not_run", "targetLocale": "es",
                     "humanApproval": True, "userDecision": "接受，先发布并如实保留未验收状态",
                     "recordedAt": "2026-10-28T19:00:00Z",
                     "englishSourcePackageJsonSha256": SHA,
                     "targetLanguageCandidateJsonSha256": SHA,
                     "targetLanguageAudioPackageJsonSha256": reviewed_hash,
                     "trackSha256": TRACK}
        reviewed, receipt = subject.approve(package, worksheet, publication_exception=exception)
        self.assertEqual(receipt["schemaVersion"],
                         "sermon-target-language-audio-human-review-receipt-v5")
        self.assertEqual(receipt["videoSync1x"], "not_run")
        stage.validate_audio_screening_review(reviewed, receipt, None)
        altered = copy.deepcopy(receipt)
        altered["publicationException"]["targetLocale"] = "ko"
        with self.assertRaises(stage.StageError):
            stage.validate_audio_screening_review(reviewed, altered, None)

    def test_historical_asr_receipts_are_still_rejected_for_a_not_run_package(self):
        package = fixture()
        with self.assertRaisesRegex(stage.StageError, "v2 human adjudication"):
            stage.validate_audio_screening_review(
                package, {"schemaVersion": "sermon-target-language-audio-human-review-receipt-v1"},
                None)


if __name__ == "__main__":
    unittest.main()
