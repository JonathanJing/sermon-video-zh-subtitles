import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('listening_catalog', Path(__file__).resolve().parents[1] / 'scripts/build_language_listening_catalog.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.public = Path(self.temp.name)
        self.previous = dict(schemaVersion=1, sources=[], voiceIds=['retained'])
        self.write('weekly.json', dict(schemaVersion='sermon-weekly-catalog-v1', weeks=[]))
        self.page = dict(id='week-one', date='2026-09-27', sourceIdentitySha256='a'*64, targets={})
        for locale in ['zh-Hans', 'ko', 'es']:
            cues = [dict(start=0, end=10, text='approved', textGroupId='g1')]
            content = dict(pageId='week-one', targetLocale=locale, status='human_reviewed',
                           englishSourcePackageJsonSha256='a'*64, targetLanguageCandidateJsonSha256='b'*64, durationSeconds=10)
            assets = []
            for role, payload in [('content', content), ('captions', dict(cues=cues)), ('audio', b'test-audio')]:
                path = f'{role}/{locale}.json' if role != 'audio' else f'media/{locale}.mp3'
                self.write(path, payload)
                assets.append(dict(role=role, path='/'+path, sha256=module.digest(self.public/path)))
            release = dict(schemaVersion='sermon-target-language-release-package-v2', status='published_http_verified',
                           pageId='week-one', targetLocale=locale, contentLocale=locale, audioLocale=locale,
                           audioStatus='human_reviewed', contentStatus='human_reviewed', targetLanguageCandidateJsonSha256='b'*64, assets=assets)
            path=f'releases/{locale}.json'; self.write(path, release)
            self.page['targets'][locale] = dict(audioStatus='human_reviewed', releasePackageUrl='/'+path, releasePackageJsonSha256=module.digest(self.public/path))
        self.write('multilingual-v3.json', dict(schemaVersion='sermon-multilingual-catalog-v3', pages=[self.page]))

    def write(self, name, value):
        path=self.public/name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())

    def build(self, previous=None):
        return module.build(self.public, previous or self.previous, 'zh-Hans')

    def test_locales_are_bound_to_three_verified_audio_sources(self):
        result=self.build()
        self.assertEqual({s['audioLocale'] for s in result['sources']}, {'zh-Hans','ko','es'})
        self.assertTrue(all(s['pageId']=='week-one' for s in result['sources']))
        self.assertEqual(result['voiceIds'], ['retained'])
        self.assertEqual(result['weekIds'], ['2026-09-27'])

    def test_preserves_previous_unannotated_source(self):
        previous=copy.deepcopy(self.previous)
        old=dict(week='2026-09-20', trackId='old', audioSha256='d'*64)
        previous['sources'].append(old)
        self.assertIn(old,self.build(previous)['sources'])

    def test_bad_audio_hash_rejected(self):
        self.write('media/ko.mp3', b'changed')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'): self.build()

    def test_existing_audio_identity_cannot_change_locale(self):
        previous=self.build(); previous['sources'][0]['audioLocale']='es'
        with self.assertRaisesRegex(ValueError, 'metadata conflicts'): self.build(previous)

    def test_existing_audio_identity_cannot_change_cues(self):
        previous=self.build(); previous['sources'][0]['cues'][0]['end']=8
        with self.assertRaisesRegex(ValueError, 'cue binding changed'): self.build(previous)
