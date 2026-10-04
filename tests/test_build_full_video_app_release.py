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
                   "cues": [{"start": 0, "text": "完整正文 & 保留"}]}
        page = release.static_page(content, "zh-Hans", self.page_id)
        self.assertIn("耶稣 &lt;配得&gt;", page)
        self.assertIn("完整正文 &amp; 保留", page)
        self.assertNotIn("<script", page)
        self.assertNotIn("<a ", page)

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
