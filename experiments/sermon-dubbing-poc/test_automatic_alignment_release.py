"""New weekly-page audio alignment requirement and legacy release compatibility."""
import json
import tempfile
import unittest
from pathlib import Path

from deploy_firebase import FINGERPRINT_UI, verify_release
import weekly_release as release
from test_weekly_release import (ORIGIN, page_with_downloads_and_fingerprint,
                                 refresh_manifest, release_fixture, week, write_json)


class AutomaticAlignmentReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        page, assets = page_with_downloads_and_fingerprint('2026-09-13', 'new')
        page.update(sourceSha256=page['audioFingerprint']['sourceSha256'],
                    videoSynchronization='human_reviewed',
                    automaticAudioAlignment={'schemaVersion': 'sermon-automatic-audio-alignment-v1',
                                             'status': 'ready', 'required': True})
        self.page = page
        self.path = release_fixture(self.root / 'candidate', [(page, assets)])
        self.report(automaticAudioAlignmentPages=[page['id']])

    def report(self, **changes):
        path = self.path / 'build-report.json'
        report = json.loads(path.read_text())
        report.update(changes)
        write_json(path, report)

    def edit(self, mutate):
        path = self.path / 'public/weekly.json'
        catalog = json.loads(path.read_text())
        mutate(catalog['weeks'][0])
        write_json(path, catalog)
        refresh_manifest(self.path)

    def reject(self):
        for validator in (verify_release, release.read_release):
            with self.subTest(validator=validator.__name__), self.assertRaises(ValueError):
                validator(self.path)

    def test_synced_new_page_valid(self):
        verify_release(self.path)
        release.read_release(self.path)

    def test_sync_preview_remains_candidate_with_alignment_available(self):
        self.edit(lambda page: page.update(audioStatus='full_candidate',
                                          videoSynchronization='candidate_aligned', humanApproval=False))
        verify_release(self.path)

    def test_unknown_required_page_is_rejected(self):
        self.report(automaticAudioAlignmentPages=['missing-page'])
        self.reject()

    def test_missing_index_rejected_even_when_manifest_rehashed(self):
        for index in (self.path / 'public/fingerprints').glob('*'):
            index.unlink()
        refresh_manifest(self.path)
        self.reject()

    def test_rehashed_tampered_index_rejected_by_binding(self):
        index = next((self.path / 'public/fingerprints').glob('*'))
        index.write_text('{}')
        refresh_manifest(self.path)
        self.reject()

    def test_marker_cannot_be_removed_even_when_manifest_rehashed(self):
        self.edit(lambda page: page.pop('automaticAudioAlignment'))
        self.reject()

    def test_missing_binding_is_not_silently_optional(self):
        self.edit(lambda page: page.pop('audioFingerprint'))
        for index in (self.path / 'public/fingerprints').glob('*'):
            index.unlink()
        refresh_manifest(self.path)
        self.reject()

    def test_changed_source_identity_rejected(self):
        self.edit(lambda page: page.update(sourceSha256='b' * 64))
        self.reject()

    def test_other_verified_source_routes_supported(self):
        for route in ('archive_caption', 'live_archive'):
            self.edit(lambda page: page.update(sourceRoute=route, sourceId='youtube-id'))
            verify_release(self.path)

    def test_missing_runtime_or_tampered_index_rejected(self):
        (self.path / 'public/fingerprint-worker.mjs').unlink()
        refresh_manifest(self.path)
        self.reject()

    def test_synced_page_cannot_claim_unavailable(self):
        self.edit(lambda page: page.update(automaticAudioAlignment={
            'schemaVersion': 'sermon-automatic-audio-alignment-v1', 'status': 'unavailable',
            'required': False, 'reason': 'unsynchronized_review_preview'}))
        self.reject()

    def test_natural_review_preview_explicitly_unavailable(self):
        def natural(page):
            page.pop('audioFingerprint')
            page.update(audioStatus='full_candidate', videoSynchronization='not_validated',
                        automaticAudioAlignment={'schemaVersion': 'sermon-automatic-audio-alignment-v1',
                                                 'status': 'unavailable', 'required': False,
                                                 'reason': 'unsynchronized_review_preview'})
        self.edit(natural)
        for index in (self.path / 'public/fingerprints').glob('*'):
            index.unlink()
        refresh_manifest(self.path)
        verify_release(self.path)
        self.edit(lambda page: page.update(audioStatus='full_reviewed'))
        self.reject()

    def test_merge_preserves_requirement_with_legacy_base(self):
        base = release_fixture(self.root / 'base', [week('2026-09-06', 'legacy')])
        for name in FINGERPRINT_UI:
            (base / 'public' / name).write_text('// existing runtime')
        refresh_manifest(base)
        registry = self.root / 'registry'
        release.bootstrap(registry, base, ORIGIN)
        merged = self.root / 'merged'
        release.prepare(registry, self.path, merged)
        report, catalog = release.read_release(merged)
        self.assertEqual(report['automaticAudioAlignmentPages'], [self.page['id']])
        self.assertEqual(len(catalog['weeks']), 2)
        self.path = merged
        self.edit(lambda page: page.pop('automaticAudioAlignment'))
        self.reject()

    def test_historical_unmarked_page_still_valid(self):
        old = release_fixture(self.root / 'old', [week('2026-08-30', 'legacy')])
        verify_release(old)
        release.read_release(old)


if __name__ == '__main__':
    unittest.main()
