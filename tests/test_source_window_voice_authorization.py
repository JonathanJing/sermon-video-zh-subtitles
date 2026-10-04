"""Source-window authorization tests use synthetic human decisions only."""
import copy
import json
from pathlib import Path
import unittest

from scripts import prepare_target_language_speech_job as speech
from scripts import stage_formal_multilingual_dev as stage
from tests import test_prepare_target_language_speech_job as fixtures


class SourceWindowAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.TargetLanguageSpeechJobTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.f = self.fixture
        self.f.source_package['source'] = {
            'sourceId': 'synthetic:window-media',
            'media': {'sha256': '3' * 64, 'durationSeconds': 4801.898667},
            'approvedWindow': {'startSeconds': 2015.321, 'endSeconds': 3957.444,
                               'status': 'approved', 'humanApproval': True}}
        self.refresh_source()
        # Real fixture job preparation creates a human-reviewed locale capability.
        self.f.make_verified_speech_job()
        self.attestation_path = self.f.root / 'window-attestation.json'
        self.receipt_path = self.f.root / 'window-authorization.json'
        self.attestation = {
            'schemaVersion': 'sermon-source-user-voice-attestation-v2',
            'scope': 'source_approved_window_formal_audio_only',
            'sourceId': self.f.source_package['source']['sourceId'],
            'sourceMediaSha256': '3' * 64, 'mediaDurationSeconds': 4801.898667,
            'approvedWindow': {'startSeconds': 2015.321, 'endSeconds': 3957.444},
            'targetLocales': ['ko'], 'speakerId': self.f.adapter['speakerId'],
            'voiceCheckpointSha256': self.f.adapter['conditioningSha256'],
            'authorizedUses': ['formal_audio_generation'], 'permissionClaimed': True,
            'userStatement': 'Synthetic fixture: generate audio for this exact window only.',
            'recordedAt': '2026-10-04T00:00:00Z'}
        fixtures.write_json(self.attestation_path, self.attestation)
        self.receipt = speech.prepare_source_voice_authorization(
            self.f.source_package_path, self.f.candidate_path, self.f.adapter_path,
            self.attestation_path, self.receipt_path)

    def refresh_source(self):
        source_hash = speech.interpretation.json_sha256(self.f.source_package)
        self.f.candidate['englishSourcePackageJsonSha256'] = source_hash
        policy = copy.deepcopy(self.f.policy)
        policy.pop('componentSha256')
        policy['sourceScope']['englishSourcePackageJsonSha256'] = source_hash
        self.f.policy = speech.policy_tools.freeze_policy(policy)
        self.f.candidate['translationPolicySha256'] = speech.policy_tools.canonical_sha256(self.f.policy)
        self.f.human_review_receipt.update(
            englishSourcePackageJsonSha256=source_hash,
            translationPolicySha256=self.f.candidate['translationPolicySha256'],
            candidateJsonSha256=speech.interpretation.json_sha256(self.f.candidate))
        for path, value in ((self.f.source_package_path, self.f.source_package),
                            (self.f.candidate_path, self.f.candidate),
                            (self.f.policy_path, self.f.policy),
                            (self.f.human_review_receipt_path, self.f.human_review_receipt)):
            fixtures.write_json(path, value)

    def bind_attestation(self, attestation, receipt=None):
        receipt = copy.deepcopy(self.receipt if receipt is None else receipt)
        fixtures.write_json(self.attestation_path, attestation)
        receipt['userRightsAttestation'] = {
            'path': str(self.attestation_path),
            'sha256': speech.interpretation.sha256(self.attestation_path),
            'jsonSha256': speech.interpretation.json_sha256(attestation)}
        return receipt

    def validate(self, receipt=None, candidate=None, source=None):
        speech.validate_source_voice_authorization(
            self.receipt if receipt is None else receipt,
            self.f.source_package if source is None else source,
            self.f.candidate if candidate is None else candidate, self.f.adapter)

    def job_and_audio(self, receipt=None):
        fixtures.write_json(self.receipt_path, self.receipt if receipt is None else receipt)
        job = speech.prepare_job(
            self.f.source_package_path, self.f.anchor_path, self.f.candidate_path,
            self.f.policy_path, self.f.human_review_receipt_path, self.f.adapter_path,
            self.f.registry_path, self.f.root / 'authorized-job',
            source_voice_authorization_path=self.receipt_path, build_only=True)
        job_path = self.f.root / 'page-job.json'
        fixtures.write_json(job_path, job)
        audio = {'targetLanguageSpeechJobJsonSha256': stage.canonical_sha(job),
                 'englishSourcePackageJsonSha256': stage.canonical_sha(self.f.source_package),
                 'targetLanguageCandidateJsonSha256': stage.canonical_sha(self.f.candidate),
                 'targetLocale': 'ko'}
        return job_path, job, audio

    def permit_page(self):
        attestation = copy.deepcopy(self.attestation)
        attestation['scope'] = 'source_approved_window_formal_audio_and_page_only'
        attestation['authorizedUses'].append('formal_page_publication')
        receipt = copy.deepcopy(self.receipt)
        receipt['scope'], receipt['authorizedUses'] = attestation['scope'], attestation['authorizedUses']
        return self.bind_attestation(attestation, receipt)

    def test_legal_clip_prepares_v2_receipt_and_unchanged_v2_job_without_page_rights(self):
        self.validate()
        self.assertEqual(self.receipt['schemaVersion'], 'sermon-source-voice-authorization-v2')
        _, job, _ = self.job_and_audio()
        self.assertEqual(job['schemaVersion'], 'sermon-target-language-speech-job-v2')
        self.assertTrue(job['synthesisEligible'])
        self.assertFalse(job['releaseEligible'])
        self.assertEqual(self.receipt['approvedWindow'], self.attestation['approvedWindow'])
        self.assertEqual(self.receipt['authorizedUses'], ['formal_audio_generation'])
        self.assertEqual(self.f.validate_schema('sermon-source-voice-authorization-v2.schema.json', self.receipt), [])
        self.assertEqual(self.f.validate_schema('sermon-source-user-voice-attestation-v2.schema.json', self.attestation), [])

    def test_audio_only_rejected_by_formal_and_dev_page_gates(self):
        path, _, audio = self.job_and_audio()
        for dev in (False, True):
            with self.subTest(dev=dev), self.assertRaisesRegex(ValueError, 'formal_page_publication'):
                stage.validate_audio_page_authorization(audio, self.f.source_package,
                    self.f.candidate, path, allow_dev_clip=dev)

    def test_dev_release_assets_gate_cannot_skip_audio_only_rejection(self):
        path, _, audio = self.job_and_audio()
        with self.assertRaisesRegex(ValueError, 'formal_page_publication'):
            stage.validate_release_assets(
                page_id='synthetic-page', locale='ko', asset_root=self.f.root,
                source=self.f.source_package, candidate=self.f.candidate, audio=audio,
                audio_path=self.f.root / 'audio.json', release={},
                content_review_path=self.f.root / 'content-review.json', speech_job_path=path)

    def test_page_permission_requires_exact_original_job_and_bound_chain(self):
        path, job, audio = self.job_and_audio(self.permit_page())
        stage.validate_audio_page_authorization(audio, self.f.source_package, self.f.candidate, path)
        with self.assertRaisesRegex(ValueError, 'original --speech-job'):
            stage.validate_audio_page_authorization(audio, self.f.source_package, self.f.candidate, None)
        changed = copy.deepcopy(job)
        changed['createdAt'] = '2026-10-05T00:00:00Z'
        fixtures.write_json(path, changed)
        with self.assertRaisesRegex(ValueError, 'not bound'):
            stage.validate_audio_page_authorization(audio, self.f.source_package, self.f.candidate, path)
        fixtures.write_json(path, job)
        self.attestation_path.write_text(self.attestation_path.read_text() + '\n')
        with self.assertRaisesRegex(ValueError, 'file hash mismatch'):
            stage.validate_audio_page_authorization(audio, self.f.source_package, self.f.candidate, path)

    def test_attestation_media_window_and_identity_changes_rejected_even_after_rehash(self):
        mutations = {
            'source': lambda a: a.update(sourceId='synthetic:another'),
            'media': lambda a: a.update(sourceMediaSha256='4' * 64),
            'duration': lambda a: a.update(mediaDurationSeconds=4802),
            'window': lambda a: a['approvedWindow'].update(startSeconds=2015.322),
            'negative': lambda a: a['approvedWindow'].update(startSeconds=-1),
            'reverse': lambda a: a['approvedWindow'].update(startSeconds=4000, endSeconds=3000),
            'overrun': lambda a: a['approvedWindow'].update(endSeconds=5000),
            'locale': lambda a: a.update(targetLocales=['es']),
            'checkpoint': lambda a: a.update(voiceCheckpointSha256='5' * 64),
            'speaker': lambda a: a.update(speakerId='other-speaker'),
            'permission': lambda a: a.update(permissionClaimed=False),
            'scope': lambda a: a.update(scope='source_approved_window_formal_audio_and_page_only'),
            'uses': lambda a: a['authorizedUses'].append('formal_page_publication'),
            'version': lambda a: a.update(schemaVersion='sermon-source-user-voice-attestation-v3')}
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                a = copy.deepcopy(self.attestation)
                mutate(a)
                receipt = copy.deepcopy(self.receipt)
                for key in ('scope', 'sourceId', 'sourceMediaSha256', 'mediaDurationSeconds',
                            'approvedWindow', 'authorizedUses'):
                    receipt[key] = a[key]
                receipt = self.bind_attestation(a, receipt)
                with self.assertRaises(ValueError):
                    self.validate(receipt)

    def test_candidate_receipt_scope_version_and_human_window_changes_rejected(self):
        for key, value in (('targetLanguageCandidateJsonSha256', '6' * 64),
                           ('englishSourcePackageJsonSha256', '6' * 64),
                           ('targetLocale', 'es'), ('voiceCheckpointSha256', '6' * 64),
                           ('schemaVersion', 'sermon-source-voice-authorization-v3'),
                           ('scope', 'source_approved_window_formal_audio_and_page_only'),
                           ('mediaDurationSeconds', 4802), ('sourceMediaSha256', '7' * 64),
                           ('sourceId', 'synthetic:another'),
                           ('approvedWindow', {'startSeconds': 2015.322, 'endSeconds': 3957.444})):
            with self.subTest(key=key):
                receipt = copy.deepcopy(self.receipt)
                receipt[key] = value
                with self.assertRaises(ValueError):
                    self.validate(receipt)
        changed = copy.deepcopy(self.f.candidate)
        changed['groups'][0]['targetText'] += ' changed'
        with self.assertRaisesRegex(ValueError, 'candidate, locale'):
            self.validate(candidate=changed)
        for field, value in (('humanApproval', False), ('status', 'pending')):
            changed = copy.deepcopy(self.f.source_package)
            changed['source']['approvedWindow'][field] = value
            with self.assertRaisesRegex(ValueError, 'approved source media window'):
                self.validate(source=changed)

    def test_v1_cannot_wrap_v2_attestation_or_accept_clip_window(self):
        receipt = {key: value for key, value in self.receipt.items() if key not in
                   {'sourceId', 'sourceMediaSha256', 'mediaDurationSeconds', 'approvedWindow', 'authorizedUses'}}
        receipt.update(schemaVersion='sermon-source-voice-authorization-v1',
                       scope='source_bound_formal_audio_and_page_only')
        with self.assertRaisesRegex(ValueError, 'mismatched'):
            self.validate(receipt)
        attestation = copy.deepcopy(self.attestation)
        attestation.pop('mediaDurationSeconds')
        attestation.update(schemaVersion='sermon-source-user-voice-attestation-v1',
                           scope='source_bound_formal_audio_and_page_only',
                           authorizedUses=['formal_audio_generation', 'formal_page_publication'])
        with self.assertRaisesRegex(ValueError, 'Invalid source voice user attestation'):
            speech.validate_source_voice_attestation(attestation, self.f.source_package)

    def test_v1_complete_source_still_authorizes_audio_and_page(self):
        self.f.source_package['source']['approvedWindow'].update(startSeconds=0, endSeconds=4801.898667)
        self.refresh_source()
        a = copy.deepcopy(self.attestation)
        a.pop('mediaDurationSeconds')
        a.update(schemaVersion='sermon-source-user-voice-attestation-v1',
                 scope='source_bound_formal_audio_and_page_only',
                 approvedWindow={'startSeconds': 0, 'endSeconds': 4801.898667},
                 authorizedUses=['formal_audio_generation', 'formal_page_publication'])
        fixtures.write_json(self.attestation_path, a)
        receipt = speech.prepare_source_voice_authorization(
            self.f.source_package_path, self.f.candidate_path, self.f.adapter_path,
            self.attestation_path, self.f.root / 'v1-authorization.json')
        self.assertEqual(receipt['schemaVersion'], 'sermon-source-voice-authorization-v1')
        path, _, audio = self.job_and_audio(receipt)
        stage.validate_audio_page_authorization(audio, self.f.source_package, self.f.candidate, path)


if __name__ == '__main__':
    unittest.main()
