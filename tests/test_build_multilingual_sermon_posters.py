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

    def test_production_origin_required_unless_labeled_proof(self):
        self.assertEqual(poster.poster_origin(poster.PRODUCTION_ORIGIN + '/'), poster.PRODUCTION_ORIGIN)
        with self.assertRaisesRegex(ValueError, 'production origin'):
            poster.poster_origin('https://ai-for-god-sermon-audio-dev.web.app')
        self.assertEqual(poster.poster_origin('https://ai-for-god-sermon-audio-dev.web.app', True),
                         'https://ai-for-god-sermon-audio-dev.web.app')

    def test_posters_follow_the_locales_this_page_published(self):
        del self.page['targets']['ko'], self.page['targets']['es']
        self.save_catalog()
        bundles, checks = self.load()
        self.assertEqual(list(bundles), ['zh-Hans'])
        self.assertEqual(len(checks), 3)
        with self.assertRaisesRegex(ValueError, 'published targets'):
            poster.load_sources(self.release, 'week-id', 'https://example.web.app', locales=['ko'])

    def test_a_text_only_locale_can_be_left_out_explicitly(self):
        target = self.page['targets']['es']
        package = poster.read(self.public / target['releasePackageUrl'].lstrip('/'))
        package['audioStatus'] = 'unavailable'
        target['releasePackageJsonSha256'] = self.save(target['releasePackageUrl'], package)
        self.save_catalog()
        bundles, _ = poster.load_sources(self.release, 'week-id', 'https://example.web.app', locales=['zh-Hans', 'ko'])
        self.assertEqual(list(bundles), ['zh-Hans', 'ko'])

    def machine_week(self, statuses=('machine_checked', 'machine_checked'), disclosure=True):
        """Republish every locale as a machine-checked v4 release listed only in catalog v4."""
        for locale, target in self.page['targets'].items():
            package = poster.read(self.public / target['releasePackageUrl'].lstrip('/'))
            package.update(schemaVersion='sermon-target-language-release-package-v4',
                           contentStatus=statuses[0], audioStatus=statuses[1])
            if disclosure:
                package['disclosure'] = dict(locale=locale, text='机器质检', english='Machine checked')
            target.update(releasePackageUrl=f'/releases-v4/week-id/{locale}.json',
                          contentStatus=statuses[0], audioStatus=statuses[1])
            target['releasePackageJsonSha256'] = self.save(target['releasePackageUrl'], package)
        self.save('/multilingual-v4.json', dict(schemaVersion='sermon-multilingual-catalog-v4', pages=[self.page]))

    def test_machine_checked_week_reads_v4_and_never_claims_human_review(self):
        self.machine_week()
        bundles, checks = self.load()
        self.assertIn('/multilingual-v4.json', checks)
        self.assertNotIn('/multilingual-v3.json', checks)
        for locale, result in bundles.items():
            label = result['brief']['reviewLabel']
            self.assertEqual(label, poster.MACHINE_REVIEW_LABELS[locale][('machine_checked', 'machine_checked')])
            self.assertNotEqual(label, poster.COPY[locale]['reviewLabel'])
        self.assertEqual(bundles['zh-Hans']['brief']['reviewLabel'], '译文与配音经机器质检 · 未经人工审核')

    def test_mixed_review_discloses_unreviewed_product_in_label_and_brief(self):
        expected = {
            ('human_reviewed', 'machine_checked'): {
                'zh-Hans': '译文已审核 · 配音经机器质检，未经人工审核',
                'ko': '번역 검토 완료 · 음성 기계 품질 검사, 음성은 사람의 검토를 거치지 않음',
                'es': 'Traducción revisada · Audio con control de calidad automático, sin revisión humana del audio',
            },
            ('machine_checked', 'human_reviewed'): {
                'zh-Hans': '译文经机器质检，未经人工审核 · 配音已审核',
                'ko': '번역 기계 품질 검사, 번역은 사람의 검토를 거치지 않음 · 음성 검토 완료',
                'es': 'Traducción con control de calidad automático, sin revisión humana de la traducción · Audio revisado',
            },
        }
        for statuses, labels in expected.items():
            self.machine_week(statuses)
            bundles, _ = self.load()
            for locale, label in labels.items():
                with self.subTest(statuses=statuses, locale=locale):
                    package = poster.read(self.public / self.page['targets'][locale]['releasePackageUrl'].lstrip('/'))
                    self.assertEqual(poster.review_label(locale, package), label)
                    self.assertEqual(bundles[locale]['brief']['reviewLabel'], label)
                    self.assertEqual(bundles[locale]['source']['brief']['reviewLabel'], label)

    def test_human_only_label_stays_human_only(self):
        bundles, _ = self.load()
        for locale, bundle in bundles.items():
            self.assertEqual(bundle['brief']['reviewLabel'], poster.COPY[locale]['reviewLabel'])

    def test_machine_checked_release_requires_its_disclosure(self):
        self.machine_week(disclosure=False)
        with self.assertRaisesRegex(ValueError, 'published, reviewed'):
            self.load()

    def test_machine_status_cannot_hide_behind_a_human_catalog_target(self):
        self.machine_week()
        for target in self.page['targets'].values():
            target['contentStatus'] = target['audioStatus'] = 'human_reviewed'
        self.save('/multilingual-v4.json', dict(schemaVersion='sermon-multilingual-catalog-v4', pages=[self.page]))
        with self.assertRaisesRegex(ValueError, 'published, reviewed'):
            self.load()


if __name__ == '__main__':
    unittest.main()
