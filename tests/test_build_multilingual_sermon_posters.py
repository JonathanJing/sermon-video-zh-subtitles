import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_multilingual_sermon_posters as poster


class MultilingualPosterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.release = Path(self.temporary.name)
        self.public = self.release / 'public'
        self.public.mkdir()
        self.page = dict(id='week-id', date='2026-09-27', sourceIdentitySha256='source', targets={})
        for locale in poster.COPY:
            content_path = f'/content/{locale}.json'
            content = dict(pageId='week-id', targetLocale=locale,
                           englishSourcePackageJsonSha256='source', targetLanguageCandidateJsonSha256='text',
                           title='Title ' + locale, series='Series', scripture='Revelation 4–5', speaker='Speaker')
            content_sha = self.save(content_path, content)
            package_path = f'/releases/{locale}.json'
            package = dict(pageId='week-id', targetLocale=locale, status='published_http_verified',
                           contentStatus='human_reviewed', audioStatus='human_reviewed',
                           targetLanguageCandidateJsonSha256='text',
                           assets=[dict(role='content', path=content_path, sha256=content_sha)])
            self.page['targets'][locale] = dict(releasePackageUrl=package_path,
                                                releasePackageJsonSha256=self.save(package_path, package))
        self.save_catalog()

    def save(self, path, value):
        target = self.public / path.lstrip('/')
        target.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(value).encode()
        target.write_bytes(data)
        return hashlib.sha256(data).hexdigest()

    def save_catalog(self):
        self.save('/multilingual-v3.json', dict(schemaVersion='sermon-multilingual-catalog-v3', pages=[self.page]))

    def load(self):
        return poster.load_sources(self.release, 'week-id', 'https://example.web.app')

    def test_each_qr_selects_week_content_and_interface_language(self):
        bundles, checks = self.load()
        self.assertEqual(len(checks), 7)
        for locale, result in bundles.items():
            brief = result['brief']
            url = urlsplit(brief['qrURL'])
            self.assertEqual(url.path, '/')
            self.assertEqual(parse_qs(url.query), dict(week=['week-id'], contentLang=[locale], lang=[poster.COPY[locale]['lang']]))
            self.assertEqual(brief['title'], 'Title ' + locale)

    def test_changed_content_fails_hash_binding(self):
        self.save('/content/ko.json', {'title': 'modified'})
        with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
            self.load()

    def test_draft_audio_cannot_be_promoted_by_poster(self):
        target = self.page['targets']['es']
        package = poster.read(self.public / target['releasePackageUrl'].lstrip('/'))
        package['audioStatus'] = 'unavailable'
        target['releasePackageJsonSha256'] = self.save(target['releasePackageUrl'], package)
        self.save_catalog()
        with self.assertRaisesRegex(ValueError, 'published, reviewed'):
            self.load()

    def test_unsafe_paths_and_non_origin_urls_rejected(self):
        for path in ('/../private.json', '//other.example/x', '/content/%2e%2e/private', '/x?token=1'):
            with self.assertRaises(ValueError):
                poster.asset_file(self.public, path)
        for origin in ('http://example.com', 'https://u:p@example.com', 'https://example.com/page', 'https://example.com/?x=1'):
            with self.assertRaises(ValueError):
                poster.origin_url(origin)


if __name__ == '__main__':
    unittest.main()
