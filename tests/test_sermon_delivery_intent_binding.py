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
        return subject.freeze_binding(self.manifest, self.plan, root=self.root, configuration=self.config,
                                      strict_admissions=getattr(self, 'strict_admissions', None))

    def validate(self, binding):
        return subject.validate_preflight_binding(binding, self.manifest, self.plan,
                                                   root=self.root, configuration=self.config,
                                                   strict_admissions=getattr(self, 'strict_admissions', None))

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


class StrictDeliveryBindingTests(DeliveryBindingTests):
    """Real strict adapters and durable ledger, synthetic provider/human evidence."""
    def setUp(self):
        super().setUp()
        from tests import test_sermon_strict_gate_admission as gate_fixtures
        from scripts import sermon_review_contracts as contracts
        self.strict_fixture = gate_fixtures.AdmissionTests()
        self.strict_fixture.setUp()
        self.addCleanup(self.strict_fixture.doCleanups)
        self.boundary = self.strict_fixture.boundary
        admitted = self.strict_fixture.admit()
        self.assertEqual(admitted['status'], 'committed', admitted)
        self.strict_admissions = {'zh-Hans': {'boundary': self.boundary, 'intentId': admitted['intent']['intentId']}}
        self.source = contracts.read_snapshot(self.boundary.config.source)[0]
        self.candidate = contracts.read_snapshot(self.boundary.config.public_candidate)[0]
        self.review = contracts.read_snapshot(self.boundary.config.human_receipt)[0]
        raw = self.source['source']; window = raw['approvedWindow']
        approval = json.loads(Path(window['evidence']['path']).read_text())
        self.request['source'] = {
            'sourceId': raw['sourceId'], 'sourceUrlHash': raw['sourceUrlHash'],
            'englishSourcePackageJsonSha256': intent.canonical_hash(self.source),
            'downstreamInvalidationKey': self.source['downstreamInvalidationKey'],
            'mediaSha256': raw['media']['sha256'], 'mediaDurationSeconds': raw['media']['durationSeconds'],
            'window': {'startSeconds': window['startSeconds'], 'endSeconds': window['endSeconds'],
                       'approvalReceiptJsonSha256': intent.canonical_hash(approval)}}
        target = self.request['requestedLocales'][0]
        target['approvedFullText'] = {'candidateJsonSha256': intent.canonical_hash(self.candidate),
                                     'humanReviewReceiptJsonSha256': intent.canonical_hash(self.review)}
        self.audio.update(englishSourcePackageJsonSha256=intent.canonical_hash(self.source),
                          targetLanguageCandidateJsonSha256=intent.canonical_hash(self.candidate))
        target['layer3AudioUnavailable'] = dict(packageJsonSha256=intent.canonical_hash(self.audio),
            **{key: self.audio[key] for key in ('englishSourcePackageJsonSha256',
                'targetLanguageCandidateJsonSha256', 'targetLocale', 'status')})
        self.fixture.write('audio.json', self.audio)
        self.config.update(source=str(self.boundary.config.source), anchor=str(self.boundary.config.anchor))
        self.config['locales']['zh-Hans'].update(policy=str(self.boundary.config.policy),
            candidate=str(self.boundary.config.public_candidate), humanReview=str(self.boundary.config.human_receipt))
        self.manifest = intent.freeze_intent(self.request)

    def test_strict_receipt_chain_is_current_read_only_and_hash_bound(self):
        before = len(self.strict_fixture.f.f.calls)
        before_files = {str(p): p.read_bytes() for p in self.strict_fixture.root.rglob('*') if p.is_file()}
        binding = self.freeze()
        self.assertEqual(self.validate(binding)['status'], 'bindings_verified')
        self.assertEqual(binding['schemaVersion'], subject.STRICT_SCHEMA)
        proof = binding['strictAdmissions']['zh-Hans']
        self.assertEqual(proof['intentId'], self.strict_admissions['zh-Hans']['intentId'])
        self.assertIn('budget-ledger', proof['currentEvidenceFileBytesSha256'])
        self.assertIn('rubric', proof['currentEvidenceFileBytesSha256'])
        self.assertIn('group.0.reviewer.raw.json', proof['currentEvidenceFileBytesSha256'])
        self.assertEqual(len(self.strict_fixture.f.f.calls), before)
        self.assertEqual({str(p): p.read_bytes() for p in self.strict_fixture.root.rglob('*') if p.is_file()}, before_files)
        self.assertEqual(len(self.boundary.reconcile()['intents']), 1)
        self.assertNotIn(str(self.strict_fixture.root), json.dumps(binding))
        self.assertFalse(binding['publicationAuthorized'])

    def test_strict_missing_boundary_or_caller_boolean_cannot_replace_proof(self):
        saved = self.strict_admissions
        self.strict_admissions = None
        with self.assertRaisesRegex(ValueError, 'strict_v3_adapter_required'): self.freeze()
        self.strict_admissions = {'zh-Hans': dict(saved['zh-Hans'], boundary=True)}
        with self.assertRaisesRegex(ValueError, 'trusted_delivery_admission_boundary_required'): self.freeze()

    def test_strict_absent_intent_does_not_create_one(self):
        self.strict_admissions['zh-Hans']['intentId'] = 'f' * 64
        with self.assertRaisesRegex(ValueError, 'existing_intent_required'): self.freeze()
        self.assertEqual(len(self.boundary.reconcile()['intents']), 1)

    def test_strict_changed_budget_call_proof_blocks(self):
        path = self.strict_fixture.f.revisions[0][0] / 'generator.budget-call.json'
        value = json.loads(path.read_text()); value['reservationId'] = 'f' * 64
        path.write_text(json.dumps(value))
        with self.assertRaises(ValueError): self.freeze()

    def test_strict_missing_generation_reservation_blocks(self):
        from scripts import sermon_review_budget as budget
        from scripts import sermon_workflow_jobs as jobs
        path = self.boundary.store.root / budget.STORE_ID / 'state.json'
        value = json.loads(path.read_text())
        key = next(key for key, row in value['reservations'].items() if row['request']['kind'] == 'initial_generation')
        del value['reservations'][key]
        jobs._persist(path, value)
        with self.assertRaisesRegex(ValueError, 'current_chain_blocked'): self.freeze()

    def test_strict_config_cannot_substitute_other_approved_package(self):
        self.config['locales']['zh-Hans']['candidate'] = 'candidate.json'
        with self.assertRaisesRegex(ValueError, 'config_evidence_mismatch'): self.freeze()

    def test_strict_rubric_or_plugin_mutation_invalidates_whole_chain(self):
        path = self.boundary.config.rubric
        value = json.loads(path.read_text()); value['rubricVersion'] = 'mutated'
        path.write_text(json.dumps(value))
        with self.assertRaises(ValueError): self.freeze()

    def test_strict_final_reload_detects_private_evidence_mutation(self):
        real = intent.preflight
        def mutate(*args, **kwargs):
            result = real(*args, **kwargs)
            path = self.strict_fixture.f.revisions[0][0] / 'reviewer.raw.json'
            value = json.loads(path.read_text()); value['model'] = 'changed-model'
            path.write_text(json.dumps(value))
            return result
        with patch.object(intent, 'preflight', side_effect=mutate):
            with self.assertRaises(ValueError): self.freeze()

    def test_strict_short_script_cannot_borrow_full_text_admission(self):
        self.required_audio()
        self.request['requestedLocales'][0]['approvedSpokenText'].update(
            kind='short_script', candidateJsonSha256='e' * 64, humanReviewReceiptJsonSha256='f' * 64)
        self.manifest = intent.freeze_intent(self.request)
        with self.assertRaisesRegex(ValueError, 'strict_short_script_adapter_required'): self.freeze()

    # These inherited mutation helpers write the original legacy fixture paths;
    # strict tests must mutate the actual paths selected by the trusted boundary.
    def test_independent_source_and_text_approval_mutation_blocks(self):
        binding = self.freeze()
        value = json.loads(self.boundary.config.human_receipt.read_text())
        value['candidateJsonSha256'] = 'f' * 64
        self.boundary.config.human_receipt.write_text(json.dumps(value))
        with self.assertRaises(ValueError): self.validate(binding)

    def test_safe_files_reject_symlinks_and_duplicate_json(self):
        path = self.boundary.config.human_receipt
        path.unlink(); path.symlink_to(self.boundary.config.policy)
        with self.assertRaises(ValueError): self.freeze()
        path.unlink(); path.write_text('{"x":1,"x":2}')
        with self.assertRaises(ValueError): self.freeze()

    def test_strict_v3_is_explicitly_fail_closed_until_trusted_adapter_exists(self):
        self.strict_admissions = None
        with self.assertRaisesRegex(ValueError, 'strict_v3_adapter_required'): self.freeze()

    def test_strict_wrong_locale_or_mixed_authority_is_rejected(self):
        from dataclasses import replace
        from scripts import sermon_strict_gate_admission as admission
        original = self.strict_admissions['zh-Hans']
        self.strict_admissions['ko'] = original
        with self.assertRaisesRegex(ValueError, 'trusted_delivery_admission_boundary_required'): self.freeze()
        other = admission.AdmissionBoundary(replace(self.boundary.config, target_locale='ko',
            production_run_id='d' * 64), self.boundary.store)
        self.strict_admissions['ko'] = dict(original, boundary=other)
        with self.assertRaisesRegex(ValueError, 'shared_admission_store_required'): self.freeze()

    def test_strict_unrelated_ledger_mutation_during_validation_is_not_silently_accepted(self):
        from scripts import sermon_review_budget as budget
        from scripts import sermon_workflow_jobs as jobs
        real = intent.preflight
        path = self.boundary.store.root / budget.STORE_ID / 'state.json'
        def mutate(*args, **kwargs):
            result = real(*args, **kwargs)
            ledger = json.loads(path.read_text())
            ledger['testUnexpectedMutation'] = True
            jobs._persist(path, ledger)
            return result
        with patch.object(intent, 'preflight', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'delivery_strict_ledger_changed'): self.freeze()

    def test_strict_pending_other_group_budget_requires_reconciliation(self):
        from scripts import sermon_review_budget as budget
        from scripts import sermon_review_contracts as contracts
        root = self.strict_fixture.f.revisions[1][0]
        manifest = contracts.read_snapshot(root / 'revision.json')[0]
        identity = {key: manifest[key] for key in budget.IDENTITY_FIELDS
                    if key not in ('workUnitId', 'rubricSha256')}
        identity.update(workUnitId=manifest['workUnitIds'][0],
                        rubricSha256=contracts.canonical_sha256(json.loads(self.boundary.config.rubric.read_text())))
        self.boundary.store.reserve(identity, operation_id='proposal', kind='decision_proposal',
            revision_id='r1', revision_number=1, input_sha256='f' * 64,
            bounds={key: 1 for key in budget.METRICS})
        with self.assertRaisesRegex(ValueError, 'current_chain_blocked'): self.freeze()
        self.assertEqual(len(self.boundary.reconcile()['intents']), 1)
