import copy
import json
import unittest

from scripts import inspect_canonical_audio as subject
from scripts import inspect_canonical_packages as packages
from scripts import review_target_language_audio as review
from scripts import build_english_source_package as english
from tests import test_build_target_language_audio_package as fixtures


class AudioInspectionTests(unittest.TestCase):
    def setUp(self):
        class CompleteSourceAudioFixture(fixtures.AudioPackageTests):
            def complete_source_fixture(self, source):
                segments = [{'id': i, 'text': unit['english'], 'start': unit['start'], 'end': unit['end']}
                            for i, unit in enumerate(self.anchor['sourceUnits'])]
                aligned = self.root / 'aligned.json'
                fixtures.write_json(aligned, segments)
                self.anchor['input'] = {'mfaSegmentsSha256': english.file_sha256(aligned), 'timingKind': 'mfa'}
                self.anchor['counts'] = {'sourceWords': 9, 'sourceSentences': 2}
                self.anchor['policy'] = {'unitPolicy': fixtures.interpretation.UNIT_POLICY_V2}
                for i, unit in enumerate(self.anchor['sourceUnits']):
                    unit['sourceSentenceId'] = 'sentence-' + str(i)
                anchor = self.root / 'complete-anchor.json'
                fixtures.write_json(anchor, self.anchor)
                summary = self.root / 'source-summary.json'
                fixtures.write_json(summary, {'sourceDurationSeconds': 0.7, 'sermonStartSeconds': 0,
                    'sermonEndSeconds': 0.7, 'readingAligner': 'mfa', 'pipelineInputIdentity': {
                        'sourceAudio': {'sha256': source['source']['media']['sha256'], 'sizeBytes': self.clip_media_path.stat().st_size}}})
                receipt = self.root / 'source-review.json'
                fixtures.write_json(receipt, {'schemaVersion': english.REVIEW_SCHEMA_VERSION,
                    'alignedSegmentsSha256': english.file_sha256(aligned),
                    'anchorManifestJsonSha256': english.json_sha256(self.anchor), 'humanApproval': True,
                    'reviewedBy': 'Synthetic fixture reviewer', 'reviewedAt': '2026-09-30T00:00:00Z',
                    'reviewedSourceUnitIds': [u['sourceUnitId'] for u in self.anchor['sourceUnits']],
                    'checks': {key: 'approved' for key in english.APPROVED_CHECKS}})
                return english.build_package(aligned, anchor, summary_path=summary,
                    approval_evidence_path=self.root / 'synthetic-window-approval.json', review_path=receipt,
                    source_id='synthetic-audio-test', source_url_hash='2' * 64, service_date='2026-09-30')
        self.fixture = CompleteSourceAudioFixture()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.package = self.fixture.build()
        fixtures.write_json(self.root / 'audio.json', self.package)
        self.upstream = {key: self.fixture.paths[key] for key in
                         ('source', 'anchor', 'candidate', 'policy', 'human_receipt')}
        self.config = {field: str(self.fixture.paths[key]) for field, key in subject.PATH_FIELDS.items()
                       if key in self.fixture.paths}
        self.config.update(renderManifest=str(self.fixture.manifest_path),
                           artifactRoot=str(self.fixture.asset_root), package='audio.json')

    def inspect(self):
        return subject.inspect(self.root, self.config, self.upstream, packages._read_package, {}, 'ko')

    def files(self):
        return {str(p.relative_to(self.root)): (p.read_bytes(), p.stat().st_mode, p.stat().st_mtime_ns)
                for p in self.root.rglob('*') if p.is_file()}

    def approve_fixture(self):
        worksheet = review.prepare(self.package, self.fixture.screening)
        worksheet.update(decision='approved', reviewedBy='Synthetic test reviewer',
                         reviewedAt='2026-09-30T00:00:00Z', fullPlayback='approved',
                         videoSync1x='approved', checks={name: 'approved' for name in review.CHECKS})
        package, receipt = review.approve(self.package, self.fixture.screening, worksheet)
        fixtures.write_json(self.root / 'audio.json', package)
        fixtures.write_json(self.root / 'review.json', receipt)
        fixtures.write_json(self.root / 'screening.json', self.fixture.screening)
        self.config.update(humanReview='review.json', screening='screening.json')
        return package, receipt

    def test_actual_audio_and_voice_validation_is_read_only_without_human_promotion(self):
        before = self.files()
        result = self.inspect()
        self.assertEqual(result['outputSha256'], fixtures.subject.json_sha256(self.package))
        self.assertIsNone(result['listeningReviewSha256'])
        self.assertEqual(len(result['voiceAuthorizationSha256']), 64)
        self.assertEqual(before, self.files())
        self.assertNotIn(str(self.root), json.dumps(result))

    def test_full_listening_receipt_is_bound_without_writes(self):
        _, receipt = self.approve_fixture()
        before = self.files()
        result = self.inspect()
        self.assertEqual(result['listeningReviewSha256'], fixtures.subject.json_sha256(receipt))
        self.assertEqual(before, self.files())

    def test_reviewed_flag_without_independent_receipt_is_rejected(self):
        self.approve_fixture()
        del self.config['humanReview']
        with self.assertRaisesRegex(ValueError, 'independent_audio_review_required'):
            self.inspect()

    def test_stale_or_incomplete_listening_and_video_sync_cannot_pass(self):
        _, receipt = self.approve_fixture()
        for key, value in (('trackSha256', '0' * 64), ('reviewedBy', 'Another reviewer'),
                           ('targetLanguageAudioPackageJsonSha256', '0' * 64),
                           ('videoSync1x', 'pending'), ('fullPlayback', 'pending')):
            with self.subTest(key=key):
                fixtures.write_json(self.root / 'review.json', {**receipt, key: value})
                with self.assertRaises(ValueError):
                    self.inspect()

    def test_serialized_package_must_match_actual_producer_artifacts(self):
        for key, value in (('packageId', 'different-package'), ('downstreamInvalidationKey', '0' * 64)):
            with self.subTest(key=key):
                fixtures.write_json(self.root / 'audio.json', {**self.package, key: value})
                with self.assertRaises(ValueError):
                    self.inspect()
        fixtures.write_json(self.root / 'audio.json', self.package)
        track = self.fixture.asset_root / self.fixture.manifest['track']['path']
        track.write_bytes(b'corrupted media')
        with self.assertRaises(ValueError):
            self.inspect()

    def test_voice_authorization_and_screening_drift_cannot_pass(self):
        self.approve_fixture()
        changed = copy.deepcopy(self.fixture.screening)
        changed['trackSha256'] = '0' * 64
        fixtures.write_json(self.root / 'screening.json', changed)
        with self.assertRaises(ValueError): self.inspect()
        fixtures.write_json(self.root / 'screening.json', self.fixture.screening)
        auth = self.fixture.paths['clip_voice_authorization']
        changed = json.loads(auth.read_text())
        changed['englishSourcePackageJsonSha256'] = '0' * 64
        fixtures.write_json(auth, changed)
        with self.assertRaises(ValueError): self.inspect()

    def test_missing_package_or_symlink_artifact_cannot_become_unavailable(self):
        (self.root / 'audio.json').unlink()
        with self.assertRaises(OSError): self.inspect()
        fixtures.write_json(self.root / 'audio.json', self.package)
        (self.fixture.asset_root / 'redirect').symlink_to(self.root / 'audio.json')
        with self.assertRaisesRegex(ValueError, 'Symlink'): self.inspect()

    def test_configuration_rejects_dispatch_and_overridden_upstream(self):
        for key in ('source', 'candidate', 'command', 'approve'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                subject.validate_configuration({**self.config, key: 'not allowed'})

    def pipeline_config(self):
        config = {'schemaVersion': packages.SCHEMA_V2, 'source': str(self.upstream['source']),
                  'anchor': str(self.upstream['anchor']), 'locales': {'ko': {
                      'policy': str(self.upstream['policy']), 'candidate': str(self.upstream['candidate']),
                      'humanReview': str(self.upstream['human_receipt']), 'audio': self.config}}}
        path = self.root / 'inspection.json'
        fixtures.write_json(path, config)
        return path

    def test_full_source_text_audio_adapter_preserves_listening_gate(self):
        path = self.pipeline_config()
        before = self.files()
        result = packages.inspect(path)
        self.assertEqual(result['inspectionDiagnostics'], {})
        for node in ('source', 'text.ko', 'audio.ko'):
            self.assertEqual(result['nodes'][node]['status'], 'validated')
        self.assertEqual(result['nodes']['page.ko']['missingGates'], ['audio_listening_review'])
        self.assertEqual(before, self.files())
        self.assertFalse(result['dispatchEnabled'])

    def test_full_adapter_requires_exact_existing_audio_review(self):
        self.approve_fixture()
        path = self.pipeline_config()
        before = self.files()
        result = packages.inspect(path)
        self.assertEqual(result['inspectionDiagnostics'], {})
        self.assertEqual(result['nodes']['page.ko']['status'], 'ready')
        self.assertEqual(result['status'], 'in_progress')
        self.assertEqual(before, self.files())
        self.assertFalse(result['dispatchEnabled'])
        receipt = json.loads((self.root / 'review.json').read_text())
        receipt['trackSha256'] = '0' * 64
        fixtures.write_json(self.root / 'review.json', receipt)
        stale = packages.inspect(path)
        self.assertEqual(stale['nodes']['audio.ko']['status'], 'blocked')
        self.assertEqual(stale['nodes']['page.ko']['status'], 'waiting_dependency')
        self.assertNotEqual(stale['stateRevision'], result['stateRevision'])

    def test_v1_migration_is_explicit_and_missing_audio_retains_gate(self):
        path = self.pipeline_config()
        config = json.loads(path.read_text())
        config['schemaVersion'] = packages.SCHEMA
        fixtures.write_json(path, config)
        with self.assertRaisesRegex(ValueError, 'invalid_locale_configuration'):
            packages.inspect(path)
        config['schemaVersion'] = packages.SCHEMA_V2
        del config['locales']['ko']['audio']
        fixtures.write_json(path, config)
        result = packages.inspect(path)
        self.assertEqual(result['nodes']['audio.ko']['missingGates'], ['voice_authorization'])
        self.assertEqual(result['nodes']['page.ko']['status'], 'waiting_dependency')


if __name__ == '__main__':
    unittest.main()
