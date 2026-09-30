"""Synthetic fixture approvals test receipt binding, never production acceptance."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import sermon_delivery_intent as intent
from scripts import sermon_delivery_intent_binding as subject
from tests import test_inspect_canonical_packages as inspection_fixtures


class DeliveryBindingTests(unittest.TestCase):
    def setUp(self):
        self.fixture = inspection_fixtures.PackageInspectionTests(methodName='test_independent_bound_review_is_required_and_never_grants_voice')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.candidate, self.review = self.fixture.approve_fixture()
        self.source = self.fixture.fixture.source
        raw = self.source['source']; window = raw['approvedWindow']
        approval = json.loads(Path(window['evidence']['path']).read_text())
        self.request = intent.read_object(Path(__file__).parent / 'fixtures/sermon_delivery_intent/synthetic-request.json')
        self.request['source'] = {
            'sourceId': raw['sourceId'], 'sourceUrlHash': raw['sourceUrlHash'],
            'englishSourcePackageJsonSha256': intent.canonical_hash(self.source),
            'downstreamInvalidationKey': self.source['downstreamInvalidationKey'],
            'mediaSha256': raw['media']['sha256'], 'mediaDurationSeconds': raw['media']['durationSeconds'],
            'window': {'startSeconds': window['startSeconds'], 'endSeconds': window['endSeconds'],
                       'approvalReceiptJsonSha256': intent.canonical_hash(approval)}}
        self.request['requestedLocales'] = [self.request['requestedLocales'][0]]
        target = self.request['requestedLocales'][0]
        target['approvedFullText'] = {'candidateJsonSha256': intent.canonical_hash(self.candidate),
                                     'humanReviewReceiptJsonSha256': intent.canonical_hash(self.review)}
        target['approvedSpokenText'] = None
        target['audioRequirement'] = 'text_only'
        self.audio = {
            'schemaVersion': 'sermon-target-language-audio-package-v1', 'packageId': 'synthetic-unavailable',
            'englishSourcePackageJsonSha256': intent.canonical_hash(self.source),
            'targetLanguageCandidateJsonSha256': intent.canonical_hash(self.candidate),
            'targetLanguageSpeechJobJsonSha256': 'a' * 64, 'targetLocale': 'zh-Hans',
            'status': 'audio_unavailable', 'ratePolicy': 'natural_no_time_stretch', 'voice': None,
            'units': [], 'track': None, 'captions': None, 'schedule': None,
            'machineScreening': {'status': 'not_run', 'model': None, 'coverage': 0},
            'humanReview': {'status': 'pending', 'humanApproval': False, 'reviewedBy': None,
                            'reviewedAt': None, 'fullPlayback': 'pending'},
            'issues': ['voice_unavailable'], 'downstreamInvalidationKey': 'b' * 64}
        target['layer3AudioUnavailable'] = dict(packageJsonSha256=intent.canonical_hash(self.audio),
            **{key: self.audio[key] for key in ('englishSourcePackageJsonSha256',
                'targetLanguageCandidateJsonSha256', 'targetLocale', 'status')})
        self.fixture.write('audio.json', self.audio)
        self.config = {'pageId': self.request['pageId'], 'source': 'source.json', 'anchor': 'anchor.json',
            'locales': {'zh-Hans': {'policy': 'policy.json', 'candidate': 'candidate.json',
                        'humanReview': 'review.json', 'audioPackage': 'audio.json'}}}
        self.plan = {'schemaVersion': 'sermon-weekly-release-plan-v1', 'status': 'prepared_not_deployed',
            'weekIds': [self.request['pageId']], 'origin': self.request['delivery']['appRootUrl'].rstrip('/'),
            'buildReportSha256': 'f' * 64}
        self.manifest = intent.freeze_intent(self.request)

    def freeze(self):
        return subject.freeze_binding(self.manifest, self.plan, root=self.root, configuration=self.config)

    def validate(self, binding):
        return subject.validate_preflight_binding(binding, self.manifest, self.plan,
                                                   root=self.root, configuration=self.config)

    def required_audio(self):
        target = self.request['requestedLocales'][0]
        target.update(audioRequirement='required', layer3AudioUnavailable=None,
                      approvedSpokenText=dict(kind='full_text', **target['approvedFullText']))
        groups = self.candidate['groups']
        self.audio.update(status='human_reviewed', issues=[],
            voice={'provider': 'synthetic', 'model': 'synthetic', 'checkpointSha256': 'c' * 64,
                   'targetLocaleCapability': 'reviewed', 'authorizationStatus': 'authorized'},
            track={'path': 'not-probed.wav', 'sha256': 'd' * 64},
            units=[{'textGroupId': group['translationGroupId'],
                    'targetTextSha256': hashlib.sha256(group['targetText'].encode()).hexdigest(),
                    'audio': {'path': 'not-probed.wav', 'sha256': 'd' * 64}, 'durationSeconds': 1}
                   for group in groups],
            machineScreening={'status': 'pass', 'model': 'synthetic', 'coverage': 1},
            humanReview={'status': 'approved', 'humanApproval': True, 'reviewedBy': 'Synthetic fixture',
                         'reviewedAt': '2026-09-30T00:00:00Z', 'fullPlayback': 'approved'})
        self.audio_review = {'schemaVersion': 'sermon-target-language-audio-human-review-receipt-v1',
            'targetLocale': 'zh-Hans', 'englishSourcePackageJsonSha256': intent.canonical_hash(self.source),
            'targetLanguageCandidateJsonSha256': intent.canonical_hash(self.candidate),
            'targetLanguageAudioPackageJsonSha256': intent.canonical_hash(self.audio),
            'trackSha256': self.audio['track']['sha256'], 'decision': 'approved',
            'reviewedBy': 'Synthetic fixture', 'reviewedAt': '2026-09-30T00:00:00Z',
            'fullPlayback': 'approved', 'videoSync1x': 'approved',
            'reviewedUnitIds': [g['translationGroupId'] for g in groups],
            'checks': {key: 'approved' for key in ('pronunciation', 'naturalness', 'completeness',
                                                 'scripture', 'voiceIdentity', 'synchronization')}, 'issues': []}
        self.fixture.write('audio.json', self.audio)
        self.fixture.write('audio-review.json', self.audio_review)
        self.config['locales']['zh-Hans']['audioHumanReview'] = 'audio-review.json'
        self.manifest = intent.freeze_intent(self.request)

    def test_receipt_backed_text_only_requires_actual_same_locale_layer3_and_is_read_only(self):
        before = self.fixture.files()
        binding = self.freeze()
        self.assertEqual(self.validate(binding)['status'], 'bindings_verified')
        self.assertEqual(self.fixture.files(), before)
        self.assertIn('source.alignedTranscript', binding['evidence'])
        self.assertFalse(binding['publicationAuthorized'])
        self.assertFalse(binding['humanApprovalGranted'])
        self.assertFalse(binding['defaultReleaseHookInstalled'])
        self.assertNotIn(str(self.root), json.dumps(binding))
        self.assertEqual(binding['locales']['zh-Hans']['durationStatus'], 'not_applicable')

    def test_required_audio_uses_independent_receipt_but_never_invents_decode_duration(self):
        self.required_audio()
        binding = self.freeze()
        self.assertEqual(binding['locales']['zh-Hans']['durationStatus'], 'unknown')
        self.assertIsNone(binding['locales']['zh-Hans']['measuredDurationSeconds'])
        self.assertEqual(binding['offlinePreflight']['offlineStatus'], 'unknown')
        self.assertIn('complete_decode_and_duration', binding['remainingGates'])
        self.audio_review['trackSha256'] = 'e' * 64
        self.fixture.write('audio-review.json', self.audio_review)
        with self.assertRaisesRegex(ValueError, 'delivery_audio_approval_mismatch'): self.freeze()

    def test_required_audio_cannot_use_unavailable_or_missing_review(self):
        self.required_audio()
        del self.config['locales']['zh-Hans']['audioHumanReview']
        with self.assertRaisesRegex(ValueError, 'delivery_audio_approval_missing'): self.freeze()

    def test_required_audio_incomplete_screening_blocks_even_with_copied_flags(self):
        self.required_audio()
        self.audio['machineScreening']['coverage'] = 0.5
        self.audio_review['targetLanguageAudioPackageJsonSha256'] = intent.canonical_hash(self.audio)
        self.fixture.write('audio.json', self.audio)
        self.fixture.write('audio-review.json', self.audio_review)
        with self.assertRaisesRegex(ValueError, 'delivery_audio_not_reviewed'): self.freeze()

    def test_text_only_missing_wrong_locale_or_audio_assets_block(self):
        original = copy.deepcopy(self.audio)
        for change in ({'targetLocale': 'ko'}, {'voice': {'provider': 'synthetic', 'model': 'synthetic',
            'checkpointSha256': 'a' * 64, 'targetLocaleCapability': 'reviewed', 'authorizationStatus': 'authorized'}}):
            with self.subTest(change=change):
                self.fixture.write('audio.json', dict(original, **change))
                with self.assertRaises(ValueError): self.freeze()
        (self.root / 'audio.json').unlink()
        with self.assertRaises(OSError): self.freeze()

    def test_changed_release_plan_or_envelope_is_rejected(self):
        binding = self.freeze()
        self.plan['buildReportSha256'] = 'a' * 64
        with self.assertRaisesRegex(ValueError, 'stale_or_changed'): self.validate(binding)
        self.plan['buildReportSha256'] = 'f' * 64
        binding['publicationAuthorized'] = True
        with self.assertRaisesRegex(ValueError, 'stale_or_changed'): self.validate(binding)

    def test_missing_build_identity_wrong_page_origin_or_locale_blocks(self):
        original = copy.deepcopy(self.plan)
        for key, value in [('buildReportSha256', None), ('weekIds', ['another-page']), ('origin', 'https://other.invalid')]:
            with self.subTest(key=key):
                self.plan = dict(original, **{key: value})
                with self.assertRaises(ValueError): self.freeze()
        self.plan = original
        self.config['locales']['ko'] = self.config['locales']['zh-Hans']
        with self.assertRaisesRegex(ValueError, 'locale_set_mismatch'): self.freeze()

    def test_independent_source_and_text_approval_mutation_blocks(self):
        binding = self.freeze()
        self.review['candidateJsonSha256'] = 'e' * 64
        self.fixture.write('review.json', self.review)
        with self.assertRaises(ValueError): self.validate(binding)

    def test_source_transcript_mutation_blocks(self):
        binding = self.freeze()
        Path(self.source['transcript']['artifact']['path']).write_text('[]')
        with self.assertRaisesRegex(ValueError, 'source_or_text_gate_blocked'): self.validate(binding)

    def test_source_window_receipt_mutation_blocks(self):
        binding = self.freeze()
        path = Path(self.source['source']['approvedWindow']['evidence']['path'])
        value = json.loads(path.read_text()); value['humanApproval'] = False
        path.write_text(json.dumps(value))
        with self.assertRaises(ValueError): self.validate(binding)

    def test_safe_files_reject_symlinks_and_duplicate_json(self):
        path = self.root / 'review.json'
        original = path.read_text()
        path.unlink(); path.symlink_to(self.root / 'policy.json')
        with self.assertRaises(ValueError): self.freeze()
        path.unlink(); path.write_text('{"x":1,"x":2}')
        with self.assertRaises(ValueError): self.freeze()
        path.write_text(original)

    def test_final_recheck_detects_evidence_changed_during_validation(self):
        real = intent.preflight
        def mutate(*args, **kwargs):
            result = real(*args, **kwargs)
            self.fixture.write('audio.json', dict(self.audio, packageId='changed'))
            return result
        with patch.object(intent, 'preflight', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'changed_during_validation'): self.freeze()

    def test_strict_v3_is_explicitly_fail_closed_until_trusted_adapter_exists(self):
        policy = copy.deepcopy(self.fixture.fixture.policy)
        policy['schemaVersion'] = 'sermon-target-language-policy-v3'
        self.fixture.write('policy.json', policy)
        with self.assertRaisesRegex(ValueError, 'delivery_strict_v3_adapter_required'): self.freeze()
