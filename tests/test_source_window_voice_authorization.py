import copy
import unittest
from unittest import mock

from scripts import prepare_target_language_speech_job as subject
from scripts import sermon_sentence_interpretation as interpretation


class ApprovedWindowAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.source = {"status": "ready_for_translation", "translationEligible": True,
                       "source": {"sourceId": "synthetic-source", "media": {"sha256": "a" * 64, "durationSeconds": 100},
                                  "approvedWindow": {"startSeconds": 10, "endSeconds": 90,
                                                     "status": "approved", "humanApproval": True}}}
        self.candidate = {"targetLocale": "zh-Hans", "englishSourcePackageJsonSha256": interpretation.json_sha256(self.source)}
        self.adapter = {"targetLocale": "zh-Hans", "speakerId": "synthetic", "conditioningSha256": "b" * 64}
        self.attestation = {"schemaVersion": "sermon-source-user-voice-attestation-v2",
                            "scope": "source_approved_window_formal_audio_only", "sourceId": "synthetic-source",
                            "sourceMediaSha256": "a" * 64, "mediaDurationSeconds": 100,
                            "approvedWindow": {"startSeconds": 10, "endSeconds": 90},
                            "targetLocales": ["zh-Hans"], "speakerId": "synthetic", "voiceCheckpointSha256": "b" * 64,
                            "authorizedUses": ["formal_audio_generation"], "permissionClaimed": True,
                            "userStatement": "Synthetic approved window authorization.", "recordedAt": "2026-10-04T00:00:00Z"}
        self.receipt = {k: copy.deepcopy(self.attestation[k]) for k in
                        ("scope", "sourceId", "sourceMediaSha256", "mediaDurationSeconds", "approvedWindow",
                         "speakerId", "voiceCheckpointSha256", "authorizedUses")}
        self.receipt.update(schemaVersion="sermon-source-voice-authorization-v2", targetLocale="zh-Hans",
                            englishSourcePackageJsonSha256=interpretation.json_sha256(self.source),
                            targetLanguageCandidateJsonSha256=interpretation.json_sha256(self.candidate),
                            userRightsAttestation={"path": "synthetic.json", "sha256": "c" * 64, "jsonSha256": "d" * 64})

    def validate(self):
        with mock.patch.object(subject, "_bound_evidence", return_value=self.attestation):
            subject.validate_source_voice_authorization(self.receipt, self.source, self.candidate, self.adapter)

    def test_precise_approved_subwindow_is_accepted(self):
        self.validate()

    def test_rejects_receipt_window_or_duration_changes(self):
        for key, value in (("mediaDurationSeconds", 101), ("approvedWindow", {"startSeconds": 0, "endSeconds": 90}),
                           ("sourceMediaSha256", "0" * 64), ("authorizedUses", ["formal_page_publication"])):
            with self.subTest(key=key):
                before = copy.deepcopy(self.receipt)
                self.receipt[key] = value
                with self.assertRaises(ValueError):
                    self.validate()
                self.receipt = before

    def test_rejects_mixed_versions(self):
        self.attestation["schemaVersion"] = "sermon-source-user-voice-attestation-v1"
        with self.assertRaises(ValueError):
            self.validate()
