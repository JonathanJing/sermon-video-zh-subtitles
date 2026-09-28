import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from bind_published_alignment_catalog import bind_catalog


class CatalogAlignmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.public = Path(self.temp.name)
        self.page_id = 'week'
        self.source = 'a' * 64
        self.media = 'b' * 64
        track = self.save('/media/week/ko.mp3', b'audio')
        self.binding = dict(schemaVersion='sermon-audio-fingerprint-binding-v1',
                            algorithmVersion='spectral-landmarks-v1', captureSeconds=10,
                            pageId='week', sourceSha256=self.media, trackSha256=track,
                            sourceStartSeconds=0, sourceEndSeconds=30)
        index = dict(self.binding, schemaVersion='sermon-landmark-index-v1', durationSeconds=30)
        index_sha = self.save('/index.json', index)
        self.binding.update(indexSha256=index_sha, indexUrl=f'/fingerprints/{index_sha[:16]}-landmarks.json')
        self.save(self.binding['indexUrl'], index)
        content_sha = self.save('/content/week/ko.json', dict(sourceMediaSha256=self.media,
            englishSourcePackageJsonSha256=self.source, pageId='week', targetLocale='ko', durationSeconds=30))
        release = dict(status='published_http_verified', contentStatus='human_reviewed', audioStatus='human_reviewed',
                       pageId='week', targetLocale='ko', audioLocale='ko', contentLocale='ko', assets=[
                           dict(role='audio', path='/media/week/ko.mp3', sha256=track),
                           dict(role='content', path='/content/week/ko.json', sha256=content_sha)])
        release_sha = self.save('/releases-v2/week/ko.json', release)
        self.target = dict(releasePackageUrl='/releases-v2/week/ko.json', releasePackageJsonSha256=release_sha,
                           contentStatus='human_reviewed', audioStatus='human_reviewed', capabilities=['text', 'captions', 'audio'])
        self.page = dict(id='week', sourceIdentitySha256=self.source, targets={'ko': self.target})
        self.catalog = dict(schemaVersion='sermon-multilingual-catalog-v3', pages=[self.page, dict(id='old')])
        self.save('/multilingual-v3.json', self.catalog)
        self.sidecar = dict(schemaVersion='sermon-published-alignment-v1', pageId='week',
                            sourceIdentitySha256=self.source, targets={'ko': dict(
                                releasePackageJsonSha256=release_sha, audioFingerprint=self.binding)})
        self.save('/alignment/week.json', self.sidecar)

    def save(self, url, value):
        data = value if isinstance(value, bytes) else json.dumps(value).encode()
        path = self.public / url.lstrip('/')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return hashlib.sha256(data).hexdigest()

    def test_binding_preserves_prior_pages_and_release_identity(self):
        before = {p.relative_to(self.public): p.read_bytes() for p in self.public.rglob('*') if p.is_file()}
        result = bind_catalog(self.public, 'week')
        self.assertEqual(result['pages'][1], self.catalog['pages'][1])
        target = result['pages'][0]['targets']['ko']
        self.assertEqual(target['releasePackageJsonSha256'], self.target['releasePackageJsonSha256'])
        self.assertEqual(target['audioFingerprint'], self.binding)
        self.assertEqual(target['capabilities'], ['text', 'captions', 'audio', 'alignment'])
        self.assertEqual(result['pages'][0]['sourceMediaSha256'], self.media)
        self.assertEqual(before, {p.relative_to(self.public): p.read_bytes() for p in self.public.rglob('*') if p.is_file()})
        self.save('/multilingual-v3.json', result)
        self.assertEqual(bind_catalog(self.public, 'week'), result)

    def test_rejects_stale_release_binding(self):
        self.sidecar['targets']['ko']['releasePackageJsonSha256'] = 'f' * 64
        self.save('/alignment/week.json', self.sidecar)
        with self.assertRaisesRegex(ValueError, 'Release binding mismatch'):
            bind_catalog(self.public, 'week')

    def test_rejects_changed_audio(self):
        self.save('/media/week/ko.mp3', b'changed')
        with self.assertRaisesRegex(ValueError, 'audio hash mismatch'):
            bind_catalog(self.public, 'week')

    def test_rejects_other_source_sidecar(self):
        self.sidecar['sourceIdentitySha256'] = 'c' * 64
        self.save('/alignment/week.json', self.sidecar)
        with self.assertRaisesRegex(ValueError, 'Alignment source mismatch'):
            bind_catalog(self.public, 'week')

    def test_rejects_source_window_mismatch(self):
        self.binding['sourceEndSeconds'] = 31
        self.save('/alignment/week.json', self.sidecar)
        with self.assertRaisesRegex(ValueError, 'source/window mismatch'):
            bind_catalog(self.public, 'week')


if __name__ == '__main__':
    unittest.main()
