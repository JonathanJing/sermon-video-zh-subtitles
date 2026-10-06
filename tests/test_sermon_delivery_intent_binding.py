"""Synthetic fixture approvals test receipt binding, never production acceptance."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import sermon_delivery_intent as intent
from scripts import sermon_delivery_intent_binding as subject
from tests import test_inspect_canonical_packages as inspection_fixtures


class _DeliveryFiles:
    """Isolated delivery files; upstream packages belong to the admission fixture."""
    def __init__(self, root):
        self.root = root

    def write(self, name, value):
        (self.root / name).write_text(json.dumps(value, ensure_ascii=False))

    def files(self):
        return {str(path.relative_to(self.root)): (path.read_bytes(), path.stat().st_mode, path.stat().st_mtime_ns)
                for path in self.root.rglob('*') if path.is_file()}


class DeliveryBindingTests(unittest.TestCase):
    def setUp(self):
        self.fixture = inspection_fixtures.PackageInspectionTests(methodName='test_independent_bound_review_is_required_and_never_grants_voice')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.candidate, self.review = self.fixture.approve_fixture()
        self.source = self.fixture.fixture.source
        self._set_up_delivery_inputs()

    def _set_up_delivery_inputs(self):
        """Bind request/audio/config to this test's actual upstream evidence."""
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
        # Build only the delivery files here. The strict fixture already created
        # the source, reviewed candidate, durable ledger and admission receipts.
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.fixture = _DeliveryFiles(self.root)
        self._set_up_delivery_inputs()
        self.config.update(source=str(self.boundary.config.source), anchor=str(self.boundary.config.anchor))
        self.config['locales']['zh-Hans'].update(policy=str(self.boundary.config.policy),
            candidate=str(self.boundary.config.public_candidate), humanReview=str(self.boundary.config.human_receipt))

    def rewrite_intent_receipt_identity(self, receipt_hash):
        from scripts import sermon_review_contracts as contracts
        from scripts import sermon_workflow_jobs as jobs
        old_id = self.strict_admissions['zh-Hans']['intentId']
        with self.boundary._locked() as (path, record, _, _):
            permission = record['intents'].pop(old_id)
            if receipt_hash is None:
                permission['identity'].pop('humanReceiptSha256')
            else:
                permission['identity']['humanReceiptSha256'] = receipt_hash
            new_id = contracts.canonical_sha256(permission['identity'])
            permission['intentId'] = new_id
            record['intents'][new_id] = permission
            jobs._persist(path, record)
        self.strict_admissions['zh-Hans']['intentId'] = new_id

    def test_legacy_intent_still_requires_current_full_receipt_chain(self):
        self.rewrite_intent_receipt_identity(None)
        binding = self.freeze()
        self.assertEqual(self.validate(binding)['status'], 'bindings_verified')
        self.strict_fixture.approve(evidence='Synthetic replacement evidence')
        with self.assertRaisesRegex(ValueError, 'delivery_strict_current_chain_blocked'):
            self.freeze()

    def test_new_intent_key_cannot_bind_a_different_human_receipt(self):
        self.rewrite_intent_receipt_identity('f' * 64)
        with self.assertRaisesRegex(ValueError, 'delivery_strict_intent_identity_changed'):
            self.freeze()

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
        # Only this case needs another candidate approved through the real
        # fixture validators, in addition to its own strict admission chain.
        other = inspection_fixtures.PackageInspectionTests(
            methodName='test_independent_bound_review_is_required_and_never_grants_voice')
        other.setUp(); self.addCleanup(other.doCleanups)
        candidate, _ = other.approve_fixture()
        self.fixture.write('candidate.json', candidate)
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


class FormalStrictDeliveryTests(unittest.TestCase):
    """Actual three-locale adapters, local tone decode and existing asset producers.

    All model responses and approval receipts below are synthetic test evidence.
    No provider, production recording, real reviewer or venue acceptance is used.
    """
    def setUp(self):
        from dataclasses import replace
        from types import SimpleNamespace
        import subprocess
        from scripts import sermon_review_contracts as c
        from scripts import target_language_policy as policies
        from scripts import sermon_strict_layer2 as strict
        from scripts import sermon_strict_candidate_bridge as bridge
        from scripts import sermon_strict_gate_admission as admission
        from scripts import review_target_language_candidate as human
        from scripts import build_formal_dev_release_assets as builder
        from tests import test_sermon_strict_budget_adapter as budget_fixtures
        from tests import test_stage_formal_multilingual_dev as formal_fixtures
        self.base = StrictDeliveryBindingTests()
        self.base.setUp(); self.addCleanup(self.base.doCleanups)
        b = self.base
        self.formal = formal_fixtures.FormalDevStageTests()
        self.formal.setUp(); self.addCleanup(self.formal.tearDown)
        f = self.formal
        f.page_id = b.request['pageId']
        f.source_path = b.boundary.config.source
        self.config = {'pageId': f.page_id, 'source': str(f.source_path),
            'anchor': str(b.boundary.config.anchor), 'locales': {}}
        self.admissions = dict(b.strict_admissions)
        candidates = {'zh-Hans': b.candidate}; reviews = {'zh-Hans': b.review}
        policy_paths = {'zh-Hans': b.boundary.config.policy}
        engine = b.strict_fixture.f.f
        source, anchor, _, rubric = [c.decode_json(raw) for raw in engine.args]
        for locale in ('ko', 'es'):
            draft = c.decode_json(engine.args[2]); draft.pop('componentSha256')
            draft['targetLocale'] = locale
            locale_rubric = dict(rubric, targetLocale=locale)
            draft['reviewContract']['rubricCanonicalJsonSha256'] = c.canonical_sha256(locale_rubric)
            policy = policies.freeze_strict_policy(draft, locale_rubric)
            args = [engine.args[0], engine.args[1], strict.material_bytes(policy), strict.material_bytes(locale_rubric)]
            rubric_path = b.strict_fixture.root / (locale + '-rubric.json')
            rubric_path.write_bytes(args[3])
            policy_path = b.strict_fixture.root / (locale + '-policy.json')
            policy_path.write_bytes(args[2]); policy_paths[locale] = policy_path
            roots = []
            with engine.session():
                for group in b.strict_fixture.f.groups:
                    engine.f.evidence['groups'][0] = group
                    from scripts import produce_target_language_candidate as producer
                    from scripts import run_target_language_models as models
                    from scripts import target_language_rule_preflight as rule_preflight
                    source_value, anchor_value = c.decode_json(args[0]), c.decode_json(args[1])
                    request = producer.prepare_request(source_value, anchor_value, policy, strict_rubric=locale_rubric)
                    receipt = rule_preflight.preflight(request, policy, b.boundary.config.plugin,
                                                       models.group_plan(request, anchor_value))
                    prepared = strict.prepare(*args, {key: group[key] for key in ('translationGroupId', 'sourceUnitIds')},
                                              rule_preflight=receipt)
                    root = b.strict_fixture.root / locale / group['translationGroupId']
                    b.strict_fixture.subject.generate(prepared, root, 'candidate', 'r1', 'fixture', engine.transport,
                        bounds=budget_fixtures.bounds(), usage_resolver=budget_fixtures.measured)
                    b.strict_fixture.subject.review(prepared, root, 'candidate', 'r1', 'fixture', engine.transport,
                        bounds=budget_fixtures.bounds(), usage_resolver=budget_fixtures.measured)
                    roots.append((root, 1))
            pending = bridge.compile_candidate(*args, roots, plugin_path=b.boundary.config.plugin,
                expected_plugin_sha256=b.boundary.config.plugin_sha256)['candidate']
            worksheet = human.build_worksheet(source, anchor, pending, policy, strict_rubric=locale_rubric)
            worksheet = human.apply_batch_approval(worksheet, reviewer='Synthetic fixture',
                reviewed_at='2026-09-30T00:00:00Z', evidence='Synthetic test only')
            candidate, review = human.approve_worksheet(source, anchor, pending, policy, worksheet, strict_rubric=locale_rubric)
            candidates[locale], reviews[locale] = candidate, review
            candidate_path = f.write_json(f.root / (locale + '-candidate.json'), candidate)
            review_path = f.write_json(f.root / (locale + '-receipt.json'), review)
            boundary = admission.AdmissionBoundary(replace(b.boundary.config, target_locale=locale,
                revision_roots=tuple(root for root, _ in roots), policy=policy_path, rubric=rubric_path,
                public_candidate=candidate_path, human_receipt=review_path), b.boundary.store)
            admitted = boundary.admit(expected_state_revision=boundary.snapshot().state_revision,
                created_at='2026-09-30T00:00:00Z')
            self.assertEqual(admitted['status'], 'committed', admitted)
            self.admissions[locale] = {'boundary': boundary, 'intentId': admitted['intent']['intentId']}
        track = f.root / 'full-tone.wav'
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
            'sine=frequency=440:duration=1', '-ac', '1', '-ar', '16000', '-acodec', 'pcm_s16le',
            '-y', str(track)], check=True)
        self.request = copy.deepcopy(b.request); self.request['requestedLocales'] = []
        for locale in subject.stage.LOCALES:
            candidate, review = candidates[locale], reviews[locale]
            boundary = self.admissions[locale]['boundary']
            candidate_path, review_path = boundary.config.public_candidate, boundary.config.human_receipt
            f.paths['candidate'][locale], f.paths['receipt'][locale] = candidate_path, review_path
            groups = candidate['groups']
            captions = {'cues': [{'textGroupId': group['translationGroupId'], 'text': group['targetText'],
                'start': index * .5, 'end': (index + 1) * .5} for index, group in enumerate(groups)]}
            captions_path = f.write_json(f.root / (locale + '-captions.json'), captions)
            schedule = {'targetLocale': locale, 'timingKind': 'measured_target_audio',
                'status': 'pass', 'issues': [], 'trackDurationSeconds': 1,
                'entries': [{'textGroupId': group['translationGroupId'], 'sourceUnitIds': group['sourceUnitIds'],
                    'plannedStart': index * .5, 'plannedEnd': (index + 1) * .5} for index, group in enumerate(groups)]}
            schedule_path = f.write_json(f.root / (locale + '-schedule.json'), schedule)
            audio = json.loads(f.paths['audio'][locale].read_text())
            audio.update(englishSourcePackageJsonSha256=intent.canonical_hash(source),
                targetLanguageCandidateJsonSha256=intent.canonical_hash(candidate),
                track={'path': str(track), 'sha256': subject.stage.file_sha(track)},
                captions={'path': str(captions_path), 'sha256': subject.stage.file_sha(captions_path)},
                schedule={'path': str(schedule_path), 'sha256': subject.stage.file_sha(schedule_path),
                          'jsonSha256': intent.canonical_hash(schedule)},
                units=[{'textGroupId': group['translationGroupId'],
                        'targetTextSha256': hashlib.sha256(group['targetText'].encode()).hexdigest(),
                        'audio': {'path': str(f.audio_file), 'sha256': subject.stage.file_sha(f.audio_file)},
                        'durationSeconds': .5} for group in groups])
            f.write_json(f.paths['audio'][locale], audio)
            audio_review = json.loads(f.paths['audio_receipt'][locale].read_text())
            audio_review.update(englishSourcePackageJsonSha256=intent.canonical_hash(source),
                targetLanguageCandidateJsonSha256=intent.canonical_hash(candidate),
                targetLanguageAudioPackageJsonSha256=intent.canonical_hash(audio),
                trackSha256=subject.stage.file_sha(track),
                reviewedUnitIds=[group['translationGroupId'] for group in groups])
            f.write_json(f.paths['audio_receipt'][locale], audio_review)
            approved = {'candidateJsonSha256': intent.canonical_hash(candidate),
                        'humanReviewReceiptJsonSha256': intent.canonical_hash(review)}
            self.request['requestedLocales'].append({'targetLocale': locale, 'audioRequirement': 'required',
                'approvedFullText': approved, 'approvedSpokenText': dict(kind='full_text', **approved),
                'layer3AudioUnavailable': None})
            self.config['locales'][locale] = {'policy': str(policy_paths[locale]),
                'candidate': str(candidate_path), 'humanReview': str(review_path),
                'audioPackage': str(f.paths['audio'][locale]), 'audioHumanReview': str(f.paths['audio_receipt'][locale])}
        self.manifest = intent.freeze_intent(self.request)
        proposal = f.root / 'metadata-proposal.md'
        proposal.write_text('Approved series. Approved title. Speaker. Revelation. Approved summary. First point.')
        metadata = {'schemaVersion': 'sermon-formal-dev-metadata-approval-v1', 'pageId': f.page_id,
            'date': '2026-09-20', 'proposalFileSha256': subject.stage.file_sha(proposal),
            'decision': 'approved_all_three_locales', 'approvalText': '三语全部批准', 'reviewer': 'user',
            'recordedAt': '2026-09-30T00:00:00Z', 'locales': {locale: {
                'series': 'Approved series', 'title': 'Approved title', 'speaker': 'Speaker',
                'scripture': 'Revelation', 'summary': 'Approved summary', 'outline': ['First point']}
                for locale in subject.stage.LOCALES}}
        metadata_path = f.write_json(f.root / 'metadata-approved.json', metadata)
        prepared_root = f.root / 'prepared'
        builder.build(SimpleNamespace(source=f.source_path, metadata=metadata_path, metadata_proposal=proposal,
            page_id=f.page_id, date='2026-09-20', service_date=None, out=prepared_root,
            candidate=[locale + '=' + str(f.paths['candidate'][locale]) for locale in subject.stage.LOCALES],
            audio_package=[locale + '=' + str(f.paths['audio'][locale]) for locale in subject.stage.LOCALES]))
        f.assets = prepared_root / 'assets'
        for locale in subject.stage.LOCALES:
            f.paths['content_receipt'][locale] = prepared_root / 'review/content' / (locale + '.json')
            f.paths['release'][locale] = prepared_root / 'releases' / (locale + '.json')
        self.preparation_receipt_path = prepared_root / 'preparation-receipt.json'
        self.args = f.args()

    def prepare(self):
        return subject.prepare_formal_delivery(self.manifest, root=self.formal.root, configuration=self.config,
            stage_args=self.args, preparation_receipt_path=self.preparation_receipt_path,
            strict_admissions=self.admissions)

    def test_actual_three_locale_asset_preflight_and_stage_with_strict_admissions(self):
        calls = len(self.base.strict_fixture.f.f.calls)
        result = self.prepare()
        self.assertEqual(result['status'], 'local_prepared_not_deployed')
        self.assertEqual(result['modelCalls'], 0)
        self.assertEqual(result['fullDecodeValidation'], 'existing_formal_preflight_pass')
        self.assertEqual(result['intentDurationStatus'], 'unknown')
        self.assertFalse(result['publicationAuthorized'])
        self.assertEqual(set(result['binding']['strictAdmissions']), set(subject.stage.LOCALES))
        self.assertNotIn('releasePlanJsonSha256', result['binding'])
        self.assertIn('formalDescriptorJsonSha256', result['binding'])
        self.assertEqual(len(self.base.strict_fixture.f.f.calls), calls)
        self.assertEqual(len(result['outputFileBytesSha256']), 14)
        self.assertNotIn(str(self.formal.root), json.dumps(result))
        self.assertTrue((self.args.out / 'multilingual-v2.json').is_file())
        with self.assertRaisesRegex(ValueError, 'requires_new_output'): self.prepare()

    def test_changed_audio_asset_blocks_before_stage(self):
        audio_path = self.formal.assets / 'media' / self.formal.page_id / 'ko.wav'
        audio_path.write_bytes(b'not a valid approved recording')
        with self.assertRaises(ValueError): self.prepare()
        self.assertFalse(self.args.out.exists())

    def test_formal_operation_emits_measured_program_span_and_safe_output_identity(self):
        from scripts import sermon_log_profile as profile
        logs = self.formal.root / 'formal-logs'
        finished = []
        with profile.session(logs, 'formal-test', work_kind='production', evidence_mode='synthetic'):
            with subject.accounting.stage('previous_audio_validation', executor_type='deterministic_program') as previous:
                pass
            result = subject.prepare_formal_delivery(self.manifest, root=self.formal.root,
                configuration=self.config, stage_args=self.args, preparation_receipt_path=self.preparation_receipt_path,
                strict_admissions=self.admissions, depends_on=[previous], completion_spans=finished)
        events, invalid = subject.accounting.read_events(logs)
        self.assertEqual(invalid, [])
        start = next(row for row in events if row['event']=='stage_started' and row['spanId']==finished[0])
        self.assertEqual(start['executorType'], 'deterministic_program')
        self.assertEqual(start['dependsOn'], [previous])
        end = next(row for row in events if row['event']=='stage_finished' and row['spanId']==finished[0])
        self.assertGreater(end['elapsedSeconds'], 0)
        self.assertTrue(any(row.get('metrics', {}).get('resultSha256')==result['resultSha256'] for row in events))
        self.assertFalse(any(row['event']=='api_attempt' for row in events))

    def test_mutation_after_stage_preserves_untrusted_output_without_success(self):
        real = subject.stage.stage
        def mutate(args):
            result = real(args)
            path = self.base.boundary.config.human_receipt
            value = json.loads(path.read_text()); value['candidateJsonSha256'] = 'f' * 64
            path.write_text(json.dumps(value))
            return result
        with patch.object(subject.stage, 'stage', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'requires_reconciliation'): self.prepare()
        self.assertTrue(self.args.out.exists())

    def test_stage_cannot_use_another_candidate_path_or_changed_preparation_receipt(self):
        self.args.candidate[0] = self.args.candidate[0].split('=')[0] + '=' + str(self.formal.root / 'foreign.json')
        with self.assertRaisesRegex(ValueError, 'lane_path_mismatch'): self.prepare()
        self.assertFalse(self.args.out.exists())

    def test_changed_asset_preparation_receipt_blocks_before_staging(self):
        value = json.loads(self.preparation_receipt_path.read_text())
        value['pageId'] = 'another-page'
        self.preparation_receipt_path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'asset_preparation_receipt_invalid'): self.prepare()
        self.assertFalse(self.args.out.exists())

    def test_formal_text_only_scope_remains_explicitly_unsupported(self):
        target = self.request['requestedLocales'][0]
        target.update(audioRequirement='text_only', approvedSpokenText=None,
            layer3AudioUnavailable={'packageJsonSha256': 'a' * 64,
                'englishSourcePackageJsonSha256': self.request['source']['englishSourcePackageJsonSha256'],
                'targetLanguageCandidateJsonSha256': target['approvedFullText']['candidateJsonSha256'],
                'targetLocale': target['targetLocale'], 'status': 'audio_unavailable'})
        self.manifest = intent.freeze_intent(self.request)
        with self.assertRaisesRegex(ValueError, 'requires_three_full_audio_locales'): self.prepare()
        self.assertFalse(self.args.out.exists())

    def test_unknown_stage_acknowledgement_preserves_completed_local_files(self):
        real = subject.stage.stage
        def lost_ack(args):
            real(args)
            raise OSError('synthetic acknowledgement loss')
        with patch.object(subject.stage, 'stage', side_effect=lost_ack):
            with self.assertRaisesRegex(ValueError, 'requires_reconciliation'): self.prepare()
        self.assertTrue((self.args.out / 'stage-receipt.json').is_file())
