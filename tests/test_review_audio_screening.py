"""L4 D2a: the audio screening review gate lives in tongxing_production.review.

The scripts/ name stays a delegate that turns the gate's rejection back into
StageError, so its seven callers are unchanged. These tests pin every rejection
reason through both names, and that the gate reaches the machine audio waiver
and the human receipt schemas only through the review backend.
"""
import copy
import dataclasses
import unittest
from unittest.mock import patch

from scripts import machine_audio_waiver_acceptance as audio_waivers
from tongxing_production.audio import human_review as review_audio
from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.delivery import formal_stage as stage
from tests.test_review_target_language_audio import SHA, fixture
from tongxing_production.delivery import backend as delivery
from tongxing_production.review import audio_screening
from tongxing_production.review import backend as review


def approved(publication_exception=None, locale="zh-Hans"):
    package, screening = fixture()
    package["targetLocale"] = screening["targetLocale"] = locale
    worksheet = review_audio.prepare(package, screening)
    checks = {name: "approved" for name in review_audio.CHECKS}
    sync = "not_run" if publication_exception else "approved"
    checks["synchronization"] = sync
    worksheet.update(decision="approved", reviewedBy="user", reviewedAt="2026-10-04T16:00:00Z",
                     fullPlayback="approved", videoSync1x=sync, checks=checks)
    worksheet["asrAdjudications"][0].update(decision="approved", evidence="Heard the full unit at 1x.")
    reviewed, receipt = review_audio.approve(package, screening, worksheet,
                                             publication_exception=publication_exception)
    return reviewed, receipt, screening


def chinese_exception():
    return {"schemaVersion": "sermon-video-sync-publication-exception-v1",
            "scope": "publish_reviewed_chinese_audio_with_video_sync_not_run",
            "humanApproval": True, "userDecision": "接受，先发布并如实保留未验收状态",
            "recordedAt": "2026-10-04T16:00:00Z", "trackSha256": fixture()[0]["track"]["sha256"]}


class AudioScreeningGateTests(unittest.TestCase):
    def assert_rejected(self, reason, audio, receipt, screening):
        """Both names reject with the same reason: StageError from scripts/, AudioScreeningError from review/."""
        with self.assertRaises(audio_screening.AudioScreeningError) as moved:
            audio_screening.validate_audio_screening_review(audio, receipt, screening)
        self.assertNotIsInstance(moved.exception, stage.StageError)
        with self.assertRaises(stage.StageError) as delegated:
            stage.validate_audio_screening_review(audio, receipt, screening)
        self.assertEqual(str(moved.exception), reason)
        self.assertEqual(str(delegated.exception), reason)
        self.assertIsInstance(delegated.exception.__cause__, audio_screening.AudioScreeningError)

    def test_human_receipts_v1_v2_accept_and_reject_with_unchanged_reasons(self):
        reviewed, receipt, screening = approved()
        self.assertEqual(receipt["schemaVersion"], "sermon-target-language-audio-human-review-receipt-v2")
        self.assertIsNone(stage.validate_audio_screening_review(reviewed, receipt, screening))
        self.assertIsNone(audio_screening.validate_audio_screening_review(reviewed, receipt, screening))
        self.assert_rejected("v2 audio review requires the bound full ASR screening receipt", reviewed, receipt, None)
        unbound = copy.deepcopy(screening)
        unbound["trackSha256"] = SHA
        self.assert_rejected("Audio ASR receipt is not bound to the reviewed package", reviewed, receipt, unbound)
        differing, rebound = copy.deepcopy(screening), copy.deepcopy(receipt)
        differing["results"][0]["targetTextSha256"] = SHA
        rebound["machineScreeningReceiptJsonSha256"] = stage.canonical_sha(differing)
        self.assert_rejected("ASR result differs from reviewed audio unit", reviewed, rebound, differing)
        unexplained = copy.deepcopy(receipt)
        unexplained["asrAdjudications"][0]["evidence"] = " "
        self.assert_rejected("ASR review queue lacks exact human adjudications", reviewed, unexplained, screening)
        legacy = {"schemaVersion": "sermon-target-language-audio-human-review-receipt-v1"}
        self.assert_rejected("Unresolved ASR review requires a v2 human adjudication receipt", reviewed, legacy, None)
        passed = copy.deepcopy(reviewed)
        passed["machineScreening"]["status"] = "pass"
        self.assertIsNone(stage.validate_audio_screening_review(passed, legacy, None))
        self.assert_rejected("Unsupported audio human review receipt", reviewed,
                             {"schemaVersion": "sermon-target-language-audio-human-review-receipt-v9"}, screening)

    def test_both_publication_exceptions_keep_their_reasons(self):
        reviewed, receipt, screening = approved(chinese_exception())
        self.assertEqual(receipt["schemaVersion"], "sermon-target-language-audio-human-review-receipt-v3")
        self.assertIsNone(stage.validate_audio_screening_review(reviewed, receipt, screening))
        altered = copy.deepcopy(receipt)
        altered["publicationException"]["trackSha256"] = SHA
        self.assert_rejected("Invalid exact-track Chinese publication exception", reviewed, altered, screening)
        reviewed, receipt, screening = approved(chinese_exception())
        reviewed["targetLocale"] = "ko"
        self.assert_rejected("Invalid exact-track Chinese publication exception", reviewed, receipt, screening)

        reviewed, _, screening = approved(locale="es")
        exception = {"schemaVersion": "sermon-video-sync-publication-exception-v2",
                     "scope": "publish_reviewed_audio_with_video_sync_not_run", "targetLocale": "es",
                     "humanApproval": True, "userDecision": "接受，先发布并如实保留未验收状态",
                     "recordedAt": "2026-10-04T16:00:00Z", "englishSourcePackageJsonSha256": SHA,
                     "targetLanguageCandidateJsonSha256": SHA,
                     "targetLanguageAudioPackageJsonSha256": stage.canonical_sha(reviewed),
                     "trackSha256": reviewed["track"]["sha256"]}
        reviewed, receipt, screening = approved(exception, locale="es")
        self.assertEqual(receipt["schemaVersion"], "sermon-target-language-audio-human-review-receipt-v4")
        self.assertIsNone(stage.validate_audio_screening_review(reviewed, receipt, screening))
        for key, value in (("targetLocale", "ko"), ("trackSha256", SHA)):
            altered = copy.deepcopy(receipt)
            altered["publicationException"][key] = value
            with self.subTest(key=key):
                self.assert_rejected("Invalid locale-bound publication exception v2", reviewed, altered, screening)

    def test_machine_audio_waiver_is_reached_through_the_review_backend(self):
        reviewed, receipt, screening = approved()
        with patch.object(audio_waivers, "is_audio_waiver", return_value=True) as detect, \
                patch.object(audio_waivers, "validate_audio_waiver") as validate:
            self.assertIsNone(stage.validate_audio_screening_review(reviewed, receipt, screening))
            detect.assert_called_once_with(receipt)
            validate.assert_called_once_with(reviewed, receipt, screening)
            validate.side_effect = ValueError("machine audio waiver: track check is not bound")
            self.assert_rejected("machine audio waiver: track check is not bound", reviewed, receipt, screening)
        self.assertIs(review.current().waivers, delivery.current().waivers)

    def test_receipt_schemas_are_read_through_schemas(self):
        reviewed, receipt, screening = approved(chinese_exception())
        current = review.current()
        read = []

        def path(name):
            read.append(name)
            return current.schemas.path(name)

        bound = dataclasses.replace(current, schemas=dataclasses.replace(current.schemas, path=path))
        with patch.object(review, "_current", bound):
            audio_screening.validate_audio_screening_review(reviewed, receipt, screening)
        self.assertEqual(read, ["sermon-target-language-audio-human-review-receipt-v3.schema.json"])
        self.assertTrue(current.schemas.path(read[0]).is_file())

    def test_local_rules_match_the_stage_they_came_from(self):
        """review/ cannot import the L4 stage; its copies of the locale list and canonical hash are pinned here."""
        self.assertEqual(audio_screening.LOCALES, stage.LOCALES)
        package, screening = fixture()
        for value in (package, screening, {"text": "接受", "n": [1.0, None, True]}):
            self.assertEqual(audio_screening._canonical_sha(value), stage.canonical_sha(value))


if __name__ == "__main__":
    unittest.main()
