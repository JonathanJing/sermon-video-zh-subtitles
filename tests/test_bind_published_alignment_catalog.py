import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from bind_published_alignment_catalog import bind_catalog, bind_catalogs, main
from delivery_contract import project_human_catalog
from unittest import mock


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
            englishSourcePackageJsonSha256=self.source, pageId='week', targetLocale='ko', status='human_reviewed',
            durationSeconds=30))
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

    def add_machine_locale(self, catalog_page, *, audio_duration=30, release_status='machine_checked'):
        """Publish a machine-checked es locale beside the human ko locale, as the four-layer seal does."""
        track = self.save('/media/week/es.mp3', b'es-audio')
        binding = dict(self.binding, trackSha256=track)
        index = dict(binding, schemaVersion='sermon-landmark-index-v1', durationSeconds=30)
        for key in ('indexSha256', 'indexUrl'):
            index.pop(key)
        index_sha = self.save('/index-es.json', index)
        binding.update(indexSha256=index_sha, indexUrl=f'/fingerprints/{index_sha[:16]}-landmarks.json')
        self.save(binding['indexUrl'], index)
        content_sha = self.save('/content/week/es.json', dict(sourceMediaSha256=self.media,
            englishSourcePackageJsonSha256=self.source, pageId='week', targetLocale='es', status='machine_checked',
            durationSeconds=30, audioDurationSeconds=audio_duration))
        release = dict(schemaVersion='sermon-target-language-release-package-v4', status='published_http_verified',
                       contentStatus='machine_checked', audioStatus=release_status, pageId='week',
                       targetLocale='es', audioLocale='es', contentLocale='es', englishSourcePackageJsonSha256=self.source,
                       assets=[dict(role='audio', path='/media/week/es.mp3', sha256=track),
                               dict(role='content', path='/content/week/es.json', sha256=content_sha)])
        release_sha = self.save('/releases-v4/week/es.json', release)
        catalog_page['targets']['es'] = dict(releasePackageUrl='/releases-v4/week/es.json',
            releasePackageJsonSha256=release_sha, contentStatus='machine_checked', audioStatus='machine_checked',
            capabilities=['text', 'captions', 'audio'])
        self.sidecar['targets']['es'] = dict(releasePackageJsonSha256=release_sha, audioFingerprint=binding)
        self.save('/alignment/week.json', self.sidecar)
        return binding

    def seal_v4(self, **kwargs):
        page = dict(self.page, date='2026-10-04', sourceLocale='en', defaultTargetLocale='es', title='Week',
                    targets={'ko': dict(self.target)})
        old = dict(id='old', date='2026-09-27', sourceLocale='en', sourceIdentitySha256='d' * 64,
                   defaultTargetLocale='ko', title='Old',
                   targets={'ko': dict(self.target, releasePackageUrl='/releases-v2/old/ko.json')})
        binding = self.add_machine_locale(page, **kwargs)
        v4 = dict(schemaVersion='sermon-multilingual-catalog-v4', generatedAt='2026-10-04T00:00:00Z',
                  defaultPageId='week', pages=[page, old])
        self.save('/multilingual-v4.json', v4)
        self.save('/multilingual-v3.json', project_human_catalog(v4))
        return v4, binding

    def read(self, name):
        return json.loads((self.public / name).read_text())

    def test_v4_binds_machine_locale_and_keeps_v3_as_projection(self):
        v4, es_binding = self.seal_v4()
        before = {p.relative_to(self.public): p.read_bytes() for p in self.public.rglob('*')
                  if p.is_file() and not p.name.startswith('multilingual-')}
        with mock.patch('sys.argv', ['bind', '--public', str(self.public), '--page-id', 'week']), \
                mock.patch('builtins.print'):
            main()
        bound_v4, bound_v3 = self.read('multilingual-v4.json'), self.read('multilingual-v3.json')
        self.assertEqual(project_human_catalog(bound_v4), bound_v3)
        es = bound_v4['pages'][0]['targets']['es']
        self.assertEqual((es['contentStatus'], es['audioStatus']), ('machine_checked', 'machine_checked'))
        self.assertEqual(es['releasePackageUrl'], '/releases-v4/week/es.json')
        self.assertEqual(es['audioFingerprint'], es_binding)
        self.assertIn('alignment', es['capabilities'])
        self.assertEqual(set(bound_v3['pages'][0]['targets']), {'ko'})
        self.assertEqual(bound_v3['pages'][0]['targets']['ko']['audioFingerprint'], self.binding)
        self.assertEqual(bound_v4['pages'][1], v4['pages'][1])
        self.assertEqual(before, {p.relative_to(self.public): p.read_bytes() for p in self.public.rglob('*')
                                  if p.is_file() and not p.name.startswith('multilingual-')})
        self.assertEqual(sorted(p.name for p in self.public.glob('.*')), [])
        # Idempotent, and bind_catalog returns the projection rather than a v3 with machine locales.
        self.assertEqual(bind_catalogs(self.public, 'week'), {'multilingual-v4.json': bound_v4,
                                                              'multilingual-v3.json': bound_v3})
        self.assertEqual(bind_catalog(self.public, 'week'), bound_v3)

    def test_v4_rerun_after_interrupted_write_is_accepted(self):
        self.seal_v4()
        catalogs = bind_catalogs(self.public, 'week')
        self.save('/multilingual-v3.json', catalogs['multilingual-v3.json'])  # v4 write never happened
        self.assertEqual(bind_catalogs(self.public, 'week'), catalogs)

    def test_v4_refuses_diverged_v3(self):
        v4, _ = self.seal_v4()
        diverged = project_human_catalog(v4)
        diverged['pages'][0]['title'] = 'Edited outside the seal'
        self.save('/multilingual-v3.json', diverged)
        with self.assertRaisesRegex(ValueError, 'human-only projection'):
            bind_catalogs(self.public, 'week')

    def test_v4_refuses_release_status_differing_from_catalog(self):
        self.seal_v4(release_status='human_reviewed')
        with self.assertRaisesRegex(ValueError, 'Unreviewed or mismatched release'):
            bind_catalogs(self.public, 'week')

    def test_v4_refuses_dub_on_its_own_clock(self):
        self.seal_v4(audio_duration=24)
        with self.assertRaisesRegex(ValueError, 'source clock'):
            bind_catalogs(self.public, 'week')

    def test_v3_snapshot_keeps_single_catalog_output(self):
        expected = bind_catalog(self.public, 'week')
        with mock.patch('sys.argv', ['bind', '--public', str(self.public), '--page-id', 'week']), \
                mock.patch('builtins.print') as printed:
            main()
        self.assertFalse((self.public / 'multilingual-v4.json').exists())
        self.assertEqual((self.public / 'multilingual-v3.json').read_text(),
                         json.dumps(expected, ensure_ascii=False, indent=2) + '\n')
        self.assertEqual(set(json.loads(printed.call_args.args[0])),
                         {'catalogPath', 'beforeSha256', 'afterSha256', 'pageId', 'locales'})

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
