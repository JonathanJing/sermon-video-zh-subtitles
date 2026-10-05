import argparse
import json
import tempfile
import unittest
from pathlib import Path

from scripts import build_full_video_app_release as release


class FullVideoAppReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.page_id = "2026-09-27-weekend-sermon-drive-530"

    def fixture(self, locales=None):
        prepared = self.root / "prepared"
        public = prepared / "public"
        rows = []
        packages = {}
        for locale in (locales or release.LOCALES):
            assets = []
            for role, path in (
                ("page", f"/pages/{self.page_id}/{locale}/index.html"),
                ("content", f"/content/{self.page_id}/{locale}.json"),
                ("audio", f"/media/{self.page_id}/{locale}.mp3"),
                ("captions", f"/captions/{self.page_id}/{locale}.json"),
            ):
                target = public / path.lstrip("/")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((locale + role).encode())
                assets.append(release.asset(public, role, path))
            rows.extend(assets)
            package = {
                "schemaVersion": "sermon-target-language-release-package-v2",
                "packageId": f"{self.page_id}-{locale}-dual-script",
                "pageId": self.page_id, "sourceLocale": "en", "targetLocale": locale,
                "targetLanguageCandidateJsonSha256": "a" * 64,
                "spokenTargetLanguageCandidateJsonSha256": "b" * 64,
                "targetLanguageAudioPackageJsonSha256": "c" * 64,
                "status": "candidate", "contentStatus": "human_reviewed",
                "audioStatus": "human_reviewed", "interfaceLocale": locale,
                "contentLocale": locale, "audioLocale": locale,
                "assets": assets, "httpVerification": release.ACCEPT_NOT_RUN.copy(),
                "deviceAcceptance": release.ACCEPT_NOT_RUN.copy(),
                "venueAcceptance": release.ACCEPT_NOT_RUN.copy(), "issues": [],
            }
            release.validate(package, "sermon-target-language-release-package-v2.schema.json")
            path = public / f"releases-v2/{self.page_id}/{locale}.json"
            release.write(path, package)
            packages[locale] = {"releasePath": "/" + str(path.relative_to(public)),
                                "releaseSha256": release.digest(path)}
        manifest = {"schemaVersion": "sermon-dual-script-app-preparation-v1",
                    "status": "candidate_not_deployed", "pageId": self.page_id,
                    "date": "2026-09-27", "title": "耶稣配得",
                    "englishSourcePackageJsonSha256": "d" * 64,
                    "releases": packages, "assets": sorted(rows, key=lambda row: row["path"])}
        release.write(prepared / "preparation-manifest.json", manifest)
        receipt = {"schemaVersion": "sermon-app-assets-http-verification-v1",
                   "status": "pass", "origin": "https://example.org",
                   "verifiedAt": "2026-09-27T12:00:00Z",
                   "assets": [{**row, "status": "pass"} for row in rows]}
        receipt_path = self.root / "http.json"
        release.write(receipt_path, receipt)
        return prepared, receipt_path

    def test_static_page_contains_complete_text_and_escapes_html(self):
        content = {"title": "耶稣 <配得>", "series": "启示录", "speaker": "Eric Geiger",
                   "scripture": "启示录 4–5", "summary": "摘要", "outline": ["要点"],
                   "durationSeconds": 1860,
                   "cues": [{"start": 0, "text": "完整正文 & 保留"}]}
        page = release.static_page(content, "zh-Hans", self.page_id)
        self.assertIn("耶稣 &lt;配得&gt;", page)
        self.assertIn("完整正文 &amp; 保留", page)
        self.assertNotIn("<script", page)
        self.assertNotIn("<a ", page)
        self.assertIn("31:00 讲道视频", page)
        content["durationSeconds"] = 1942.123
        self.assertIn("32:22 讲道视频", release.static_page(content, "zh-Hans", self.page_id))
        content["durationSeconds"] = 3661.9
        self.assertIn("1:01:01 讲道视频", release.static_page(content, "zh-Hans", self.page_id))

    def test_v2_requires_spoken_candidate_and_v3_requires_title(self):
        prepared, receipt = self.fixture()
        sealed = self.root / "sealed"
        report = release.seal(argparse.Namespace(prepared=prepared, http_verification=receipt,
                                                 out=sealed))
        self.assertEqual(report["status"], "ready_for_catalog_deployment")
        catalog = release.read(sealed / "public/multilingual-v3.json")
        self.assertEqual(catalog["pages"][0]["title"], "耶稣配得")
        self.assertEqual(len(report["files"]), 16)
        for locale in release.LOCALES:
            package = release.read(sealed / f"public/releases-v2/{self.page_id}/{locale}.json")
            self.assertEqual(package["spokenTargetLanguageCandidateJsonSha256"], "b" * 64)
            self.assertEqual(package["status"], "published_http_verified")
            self.assertEqual(package["httpVerification"]["evidenceSha256"], release.digest(receipt))
        del catalog["pages"][0]["title"]
        with self.assertRaises(ValueError):
            release.validate(catalog, "sermon-multilingual-catalog-v3.schema.json")

    def test_single_chinese_seal_preserves_unrun_device_acceptance(self):
        prepared, receipt = self.fixture(("zh-Hans",))
        sealed = self.root / "sealed-zh"
        release.seal(argparse.Namespace(prepared=prepared, http_verification=receipt, out=sealed))
        catalog = release.read(sealed / "public/multilingual-v3.json")
        self.assertEqual(set(catalog["pages"][0]["targets"]), {"zh-Hans"})
        package = release.read(sealed / f"public/releases-v2/{self.page_id}/zh-Hans.json")
        self.assertEqual(package["status"], "published_http_verified")
        self.assertEqual(package["deviceAcceptance"], release.ACCEPT_NOT_RUN)
        self.assertEqual(package["venueAcceptance"], release.ACCEPT_NOT_RUN)

    def test_non_chinese_locale_subset_seals_with_locale_default(self):
        prepared, receipt = self.fixture(("ko", "es"))
        sealed = self.root / "sealed-ko-es"
        release.seal(argparse.Namespace(prepared=prepared, http_verification=receipt, out=sealed))
        catalog = release.read(sealed / "public/multilingual-v3.json")
        self.assertEqual(set(catalog["pages"][0]["targets"]), {"ko", "es"})
        self.assertEqual(catalog["pages"][0]["defaultTargetLocale"], "ko")

    def test_metadata_v2_is_bound_to_exact_approved_locale_subset(self):
        proposal = self.root / "proposal.md"
        proposal.write_text("Series. Korean title. Speaker. Scripture. Summary. Outline.")
        fields = {"series": "Series", "title": "Korean title", "speaker": "Speaker",
                  "scripture": "Scripture", "summary": "Summary", "outline": ["Outline."]}
        approval = {"schemaVersion": "sermon-formal-dev-metadata-approval-v2",
                    "pageId": self.page_id, "date": "2026-09-27",
                    "proposalFileSha256": release.formal_assets.stage.file_sha(proposal),
                    "decision": "approved_selected_locales", "approvalText": "所列语言页面信息已批准",
                    "reviewer": "user", "recordedAt": "2026-10-04T16:00:00Z",
                    "approvedLocales": ["ko"], "locales": {"ko": fields}}
        path = self.root / "approval.json"
        release.write(path, approval)
        checked = release.formal_assets.checked_metadata(path, proposal, self.page_id,
                                                         "2026-09-27", ("ko",))
        self.assertEqual(set(checked["locales"]), {"ko"})
        with self.assertRaisesRegex(ValueError, "exactly match"):
            release.formal_assets.checked_metadata(path, proposal, self.page_id,
                                                   "2026-09-27", ("ko", "es"))

    def test_seal_rejects_incomplete_http_receipt(self):
        prepared, receipt = self.fixture()
        value = release.read(receipt)
        value["assets"].pop()
        release.write(receipt, value)
        with self.assertRaisesRegex(ValueError, "HTTP receipt"):
            release.seal(argparse.Namespace(prepared=prepared, http_verification=receipt,
                                            out=self.root / "sealed"))


if __name__ == "__main__":
    unittest.main()


class SimulatedMetadataIsolationTests(unittest.TestCase):
    def test_simulated_metadata_requires_exact_dev_route_and_visible_notice(self):
        from scripts import build_formal_dev_release_assets as metadata
        from jsonschema import ValidationError
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            schema = release.read(release.ROOT / 'schemas/sermon-dev-simulated-metadata-v1.schema.json')
            intent = schema['properties']['releaseIntent']['const']
            fields = {'series': 'Series', 'title': '[模拟审核测试] Title', 'speaker': 'Speaker',
                      'scripture': 'Revelation', 'summary': 'simulation test only', 'outline': ['Point']}
            proposal = root / 'proposal.txt'
            proposal.write_text('\n'.join([value for value in fields.values() if isinstance(value, str)] + fields['outline']))
            value = {'schemaVersion': 'sermon-dev-simulated-metadata-v1', 'pageId': 'mockup-test',
                     'date': '2026-09-27', 'proposalFileSha256': release.digest(proposal),
                     'decision': 'simulated_test_only', 'approvalText': 'simulation test only - not a real human approval',
                     'reviewer': 'simulation-test-only', 'recordedAt': '2026-10-05T03:00:00Z',
                     'approvedLocales': ['ko'], 'locales': {'ko': fields}, 'releaseIntent': intent}
            path = root / 'metadata.json'
            release.write(path, value)
            self.assertEqual(metadata.checked_metadata(path, proposal, 'mockup-test', '2026-09-27', ['ko'], release_intent=intent)['decision'], 'simulated_test_only')
            for route in (None, {**intent, 'environment': 'production'}, {**intent, 'site': 'other'}):
                with self.assertRaisesRegex(ValueError, 'exact isolated Dev'):
                    metadata.checked_metadata(path, proposal, 'mockup-test', '2026-09-27', ['ko'], release_intent=route)
            value['releaseIntent'] = {**intent, 'site': 'production'}
            release.write(path, value)
            with self.assertRaises(ValidationError):
                metadata.checked_metadata(path, proposal, 'mockup-test', '2026-09-27', ['ko'], release_intent=value['releaseIntent'])

    def test_catalog_test_flags_are_boolean_and_old_catalog_stays_valid(self):
        from jsonschema import Draft202012Validator, ValidationError
        schema = release.read(release.ROOT / 'schemas/sermon-multilingual-catalog-v3.schema.json')
        validator = Draft202012Validator(schema)
        target = {'releasePackageUrl': '/releases-v2/p/ko.json', 'releasePackageJsonSha256': 'a' * 64,
                  'contentStatus': 'human_reviewed', 'audioStatus': 'human_reviewed', 'capabilities': ['text', 'captions', 'audio']}
        page = {'id': 'p', 'date': '2026-09-27', 'title': 'Test', 'sourceLocale': 'en',
                'sourceIdentitySha256': 'b' * 64, 'defaultTargetLocale': 'ko', 'targets': {'ko': target}}
        catalog = {'schemaVersion': 'sermon-multilingual-catalog-v3', 'generatedAt': '2026-10-05T03:00:00Z', 'defaultPageId': 'p', 'pages': [page]}
        validator.validate(catalog)
        catalog['defaultTargetLocale'] = 'zh-Hans'
        validator.validate(catalog)
        page.update(simulationOnly=True, diagnosticOnly=True)
        target.update(simulationOnly=True, diagnosticOnly=True)
        validator.validate(catalog)
        target['simulationOnly'] = 'true'
        with self.assertRaises(ValidationError):
            validator.validate(catalog)


class ReaderClosureTests(unittest.TestCase):
    def test_nested_root_and_relative_browser_imports_are_all_sealed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'app.mjs').write_text("import {x} from '/catalog.mjs';")
            (root / 'catalog.mjs').write_text("export {x} from './nested.mjs';")
            (root / 'nested.mjs').write_text('export const x=1;')
            (root / 'published-weeks.mjs').write_text('')
            (root / 'content-locales.mjs').write_text('')
            self.assertEqual(set(release.runtime_web_files(root)), {'app.mjs', 'catalog.mjs', 'nested.mjs', 'published-weeks.mjs', 'content-locales.mjs'})
            (root / 'nested.mjs').unlink()
            with self.assertRaisesRegex(ValueError, 'dependency is missing'):
                release.runtime_web_files(root)

    def test_actual_reader_contains_catalog_navigation_dependency(self):
        self.assertIn('catalog.mjs', release.RUNTIME_WEB_FILES)
        self.assertIn('fingerprint-capture.mjs', release.RUNTIME_WEB_FILES)
        self.assertIn('locales-ko.mjs', release.RUNTIME_WEB_FILES)
