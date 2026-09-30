import copy
import json
from pathlib import Path
import shutil
import unittest

from scripts import inspect_canonical_packages as packages
from scripts import stage_formal_multilingual_dev as stage
from tests import test_inspect_canonical_audio as audio_fixture


class ReleaseInspectionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = audio_fixture.AudioInspectionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.audio, _ = self.fixture.approve_fixture()
        self.path = self.fixture.pipeline_config()
        self.config = json.loads(self.path.read_text())
        self.page_id = 'synthetic-inspection'
        self.config.update(schemaVersion=packages.SCHEMA_V3, pageId=self.page_id)
        producer = self.fixture.fixture
        self.assets = self.root / 'release-assets'
        self.content = {
            'schemaVersion': 'sermon-formal-dev-content-v1', 'pageId': self.page_id,
            'sourceLocale': 'en', 'locale': 'ko',
            'englishSourcePackageJsonSha256': stage.canonical_sha(producer.source),
            'targetLanguageCandidateJsonSha256': stage.canonical_sha(producer.candidate),
            'targetLanguageAudioPackageJsonSha256': stage.canonical_sha(self.audio),
            'contentStatus': 'human_reviewed', 'audioStatus': 'human_reviewed',
            'series': 'Synthetic series', 'title': 'Synthetic title', 'speaker': 'Fixture speaker',
            'scripture': 'Synthetic reference', 'date': '2026-09-30', 'summary': 'Synthetic summary',
            'durationSeconds': 0.7, 'outline': [], 'cues': [
                {'textGroupId': group['translationGroupId'], 'sourceUnitIds': group['sourceUnitIds'],
                 'start': entry['plannedStart'], 'end': entry['plannedEnd'], 'text': group['targetText']}
                for group, entry in zip(producer.candidate['groups'], producer.schedule['entries'])]}
        self.content_path = self.assets / 'content' / self.page_id / 'ko.json'
        self.write(self.content_path, self.content)
        self.content_review = {
            'schemaVersion': 'sermon-formal-dev-content-review-receipt-v1',
            'pageId': self.page_id, 'targetLocale': 'ko',
            **{key: self.content[key] for key in ('englishSourcePackageJsonSha256',
               'targetLanguageCandidateJsonSha256', 'targetLanguageAudioPackageJsonSha256')},
            'contentJsonSha256': stage.canonical_sha(self.content), 'decision': 'approved',
            'reviewer': 'Synthetic reviewer', 'reviewedAt': '2026-09-30T00:00:00Z',
            'reviewedFields': ['series', 'title', 'speaker', 'scripture', 'date', 'summary', 'outline']}
        self.write(self.root / 'content-review.json', self.content_review)
        media = self.assets / 'media' / self.page_id / 'ko.wav'
        captions = self.assets / 'captions' / self.page_id / 'ko.json'
        for source, target in ((self.audio['track']['path'], media), (self.audio['captions']['path'], captions)):
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        self.release = {
            'schemaVersion': 'sermon-target-language-release-package-v1', 'packageId': 'synthetic-ko-release',
            'pageId': self.page_id, 'sourceLocale': 'en', 'targetLocale': 'ko',
            'targetLanguageCandidateJsonSha256': self.content['targetLanguageCandidateJsonSha256'],
            'targetLanguageAudioPackageJsonSha256': self.content['targetLanguageAudioPackageJsonSha256'],
            'status': 'candidate', 'contentStatus': 'human_reviewed', 'audioStatus': 'human_reviewed',
            'interfaceLocale': 'ko', 'contentLocale': 'ko', 'audioLocale': 'ko', 'issues': [],
            'assets': [{'role': role, 'path': '/' + str(path.relative_to(self.assets)), 'sha256': stage.file_sha(path)}
                       for role, path in (('content', self.content_path), ('audio', media), ('captions', captions))],
            **{gate: {'status': 'not_run', 'evidenceSha256': None}
               for gate in ('httpVerification', 'deviceAcceptance', 'venueAcceptance')}}
        self.write(self.root / 'release.json', self.release)
        self.config['locales']['ko']['release'] = {
            'package': 'release.json', 'assetRoot': 'release-assets', 'contentReview': 'content-review.json'}
        self.write(self.path, self.config)

    @staticmethod
    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False))

    def inspect(self):
        return packages.inspect(self.path)

    def assert_blocked(self):
        result = self.inspect()
        self.assertEqual(result['nodes']['page.ko']['status'], 'blocked')
        self.assertEqual(result['status'], 'in_progress')
        self.assertFalse(result['dispatchEnabled'])

    def test_actual_four_layer_inspection_observes_candidate_without_acceptance_or_writes(self):
        before = self.fixture.files()
        result = self.inspect()
        self.assertEqual(result['inspectionDiagnostics'], {})
        self.assertEqual(result['nodes']['page.ko']['status'], 'validated')
        self.assertEqual(result['status'], 'terminal_evidence_observed')
        self.assertEqual(result['productionAcceptance'], 'not_evaluated')
        self.assertEqual(result['deviceAcceptance'], 'not_run')
        self.assertEqual(before, self.fixture.files())
        self.assertFalse(result['dispatchEnabled'])
        self.assertNotIn(str(self.root), json.dumps(result))

    def test_stale_metadata_review_or_audio_binding_blocks_release(self):
        for key in ('contentJsonSha256', 'targetLanguageAudioPackageJsonSha256'):
            self.write(self.root / 'content-review.json', {**self.content_review, key: '0' * 64})
            self.assert_blocked()
        self.write(self.root / 'content-review.json', self.content_review)
        self.write(self.root / 'release.json', {**self.release, 'targetLanguageAudioPackageJsonSha256': '0' * 64})
        self.assert_blocked()

    def test_rehashed_content_cannot_repair_upstream_text_downstream(self):
        content = copy.deepcopy(self.content)
        content['cues'][0]['text'] = 'Changed content despite same source and candidate'
        self.write(self.content_path, content)
        release = copy.deepcopy(self.release)
        release['assets'][0]['sha256'] = stage.file_sha(self.content_path)
        self.write(self.root / 'release.json', release)
        self.write(self.root / 'content-review.json', {
            **self.content_review, 'contentJsonSha256': stage.canonical_sha(content)})
        self.assert_blocked()

    def test_corrupt_or_redirected_assets_are_rejected(self):
        self.content_path.write_text('{}')
        self.assert_blocked()
        self.write(self.content_path, self.content)
        target = self.root / 'copy.json'
        shutil.copyfile(self.content_path, target)
        self.content_path.unlink(); self.content_path.symlink_to(target)
        self.assert_blocked()

    def test_published_or_device_status_is_not_inferred_from_candidate_inspection(self):
        for field, value in (('status', 'published_http_verified'),
                             ('deviceAcceptance', {'status': 'pass', 'evidenceSha256': 'a' * 64}),
                             ('pageId', 'other-page')):
            self.write(self.root / 'release.json', {**self.release, field: value})
            self.assert_blocked()

    def test_rebuilt_valid_candidate_changes_terminal_revision(self):
        original = self.inspect()
        content = {**self.content, 'title': 'Another reviewed synthetic title'}
        self.write(self.content_path, content)
        release = copy.deepcopy(self.release)
        release['assets'][0]['sha256'] = stage.file_sha(self.content_path)
        self.write(self.root / 'release.json', release)
        self.write(self.root / 'content-review.json', {
            **self.content_review, 'contentJsonSha256': stage.canonical_sha(content)})
        changed = self.inspect()
        self.assertEqual(changed['status'], 'terminal_evidence_observed')
        self.assertNotEqual(changed['stateRevision'], original['stateRevision'])

    def test_config_migration_and_lane_isolation(self):
        old = {**self.config, 'schemaVersion': packages.SCHEMA_V2}
        old.pop('pageId'); self.write(self.path, old)
        with self.assertRaises(ValueError): self.inspect()
        self.config['locales']['es'] = {'policy': 'missing.json'}
        self.write(self.path, self.config)
        result = self.inspect()
        self.assertEqual(result['nodes']['page.ko']['status'], 'validated')
        self.assertEqual(result['nodes']['text.es']['status'], 'blocked')
        self.assertEqual(result['status'], 'in_progress')


if __name__ == '__main__':
    unittest.main()
