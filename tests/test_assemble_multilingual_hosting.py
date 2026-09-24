import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts import assemble_multilingual_hosting as hosting


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, dict):
        path.write_text(json.dumps(value, sort_keys=True, ensure_ascii=False) + "\n")
    else:
        path.write_bytes(value)
    return hosting.digest(path)


def fixture(public, page_id, date):
    locale = "ko"
    prefix = f"/{page_id}/{locale}"
    assets = []
    for role, folder, extension, value in (
        ("content", "content", "json", b'{"reviewed":true}'),
        ("audio", "media", "wav", b"RIFF small fixture WAVE"),
        ("captions", "captions", "json", b'{"cues":[]}'),
    ):
        name = f"/{folder}{prefix}.{extension}"
        assets.append({"role": role, "path": name,
                       "sha256": write(public / name[1:], value)})
    release = {
        "schemaVersion": "sermon-target-language-release-package-v1",
        "pageId": page_id, "targetLocale": locale, "sourceLocale": "en",
        "contentLocale": locale, "audioLocale": locale,
        "contentStatus": "human_reviewed", "audioStatus": "human_reviewed",
        "issues": [], "assets": assets,
    }
    name = f"/releases/{page_id}/{locale}.json"
    target = {
        "releasePackageUrl": name,
        "releasePackageJsonSha256": write(public / name[1:], release),
        "contentStatus": "human_reviewed", "audioStatus": "human_reviewed",
        "capabilities": ["text", "captions", "audio"],
    }
    page = {
        "id": page_id, "date": date, "sourceLocale": "en",
        "sourceIdentitySha256": "a" * 64,
        "defaultTargetLocale": locale, "targets": {locale: target},
    }
    return page


class AssembleHostingTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / "base"
        self.stage = self.root / "stage"
        self.base.mkdir()
        self.stage.mkdir()
        self.old_page = fixture(self.base, "previous-week", "2026-09-13")
        self.new_page = fixture(self.stage, "new-week", "2026-09-20")
        self.base_catalog = {
            "schemaVersion": "sermon-multilingual-catalog-v2",
            "generatedAt": "2026-09-13T00:00:00Z",
            "defaultPageId": self.old_page["id"], "pages": [self.old_page],
        }
        self.new_catalog = {
            "schemaVersion": "sermon-multilingual-catalog-v2",
            "generatedAt": "2026-09-20T00:00:00Z",
            "defaultPageId": self.new_page["id"], "pages": [self.new_page],
        }
        write(self.base / hosting.CATALOG, self.base_catalog)
        write(self.base / "index.html", b"legacy reader")
        write(self.root / "build-report.json", {
            "schemaVersion": "sermon-weekly-build-v1", "feedbackEnabled": True})
        catalog_hash = write(self.stage / hosting.CATALOG, self.new_catalog)
        write(self.stage / "stage-receipt.json", {
            "schemaVersion": "sermon-formal-dev-stage-receipt-v1",
            "deploymentStatus": "not_deployed", "httpVerification": "not_run",
            "catalogSha256": catalog_hash, "pageId": self.new_page["id"],
            "sourceIdentitySha256": self.new_page["sourceIdentitySha256"],
            "targetLocales": ["ko"], "assetCount": 4,
            "releasePackageSha256": {
                "ko": self.new_page["targets"]["ko"]["releasePackageJsonSha256"]},
        })

    def test_new_page_preserves_prior_bytes_and_has_catalog_rollback(self):
        output = self.root / "release"
        report = hosting.assemble(self.base, self.stage, output)
        self.assertEqual(report["status"], "validated_not_deployed")
        self.assertEqual(report["addedFileCount"], 4)
        self.assertEqual((output / "public/index.html").read_bytes(), b"legacy reader")
        self.assertEqual((output / "rollback-multilingual-v2.json").read_bytes(),
                         (self.base / hosting.CATALOG).read_bytes())
        catalog = hosting.load(output / "public" / hosting.CATALOG)
        self.assertEqual([page["id"] for page in catalog["pages"]],
                         ["new-week", "previous-week"])
        self.assertEqual(catalog["defaultPageId"], "new-week")

    def test_rejects_changed_stage_asset_without_output(self):
        write(self.stage / "media/new-week/ko.wav", b"tampered")
        output = self.root / "release"
        with self.assertRaisesRegex(ValueError, "asset hash differs"):
            hosting.assemble(self.base, self.stage, output)
        self.assertFalse(output.exists())

    def test_production_overlay_keeps_legacy_catalog_and_exposes_reviewed_reader(self):
        write(self.base / "index.html", b'<main class="field-main"></main>')
        write(self.base / "weekly.json", {"schemaVersion": "sermon-weekly-catalog-v1",
                                          "weeks": [{"id": "old-legacy-week"}]})
        output = self.root / "production"
        report = hosting.assemble(self.base, self.stage, output, production_reader=True)
        public = output / "public"
        self.assertTrue(report["productionReader"])
        self.assertEqual((public / "weekly.json").read_bytes(),
                         (self.base / "weekly.json").read_bytes())
        self.assertIn('/pages/new-week/ko', (public / "index.html").read_text())
        self.assertIn('data-reader-mode="production"',
                      (public / "multilingual-reader.html").read_text())
        config = hosting.load(output / "firebase.json")
        self.assertEqual(config["hosting"]["target"], "sermonDubbing")
        self.assertFalse(config["hosting"]["cleanUrls"])
        self.assertIn({"source": "/api/**", "function": {
            "functionId": "sermon-feedback-api", "region": "us-west1"}},
            config["hosting"]["rewrites"])
        self.assertIn({"source": "/pages/**", "destination": "/multilingual-reader.html"},
                      config["hosting"]["rewrites"])

    def test_promoted_home_preserves_legacy_week_links_and_download_catalog(self):
        old_html = b'<html><main class="field-main"></main></html>'
        write(self.base / "index.html", old_html)
        write(self.base / "weekly.json", {"schemaVersion": "sermon-weekly-catalog-v1",
                                          "weeks": [{"id": "old-legacy-week"}]})
        output = self.root / "production"
        report = hosting.assemble(self.base, self.stage, output,
                                  production_reader=True, promote_home=True)
        public = output / "public"
        self.assertTrue(report["promotedHome"])
        self.assertEqual((public / "legacy-reader.html").read_bytes(), old_html)
        self.assertEqual((public / "weekly.json").read_bytes(),
                         (self.base / "weekly.json").read_bytes())
        self.assertIn('id="legacyReaderLink"', (public / "index.html").read_text())
        self.assertIn('data-reader-mode="production"',
                      (public / "index.html").read_text())
        self.assertIn("location.replace", (public / "legacy-query-router.js").read_text())
        self.assertIn('new Set(["old-legacy-week"])',
                      (public / "legacy-query-router.js").read_text())
        self.assertNotIn("__LEGACY_WEEK_IDS__",
                         (public / "legacy-query-router.js").read_text())
        config = hosting.load(output / "firebase.json")
        self.assertIn({"source": "/pages/**", "destination": "/index.html"},
                      config["hosting"]["rewrites"])
        next_stage = self.root / "next-promoted-stage"
        next_stage.mkdir()
        next_page = fixture(next_stage, "following-week", "2026-09-27")
        next_catalog = {**self.new_catalog, "pages": [next_page],
                        "defaultPageId": next_page["id"]}
        catalog_hash = write(next_stage / hosting.CATALOG, next_catalog)
        write(next_stage / "stage-receipt.json", {
            "schemaVersion": "sermon-formal-dev-stage-receipt-v1",
            "deploymentStatus": "not_deployed", "httpVerification": "not_run",
            "catalogSha256": catalog_hash, "pageId": next_page["id"],
            "sourceIdentitySha256": next_page["sourceIdentitySha256"],
            "targetLocales": ["ko"], "assetCount": 4,
            "releasePackageSha256": {
                "ko": next_page["targets"]["ko"]["releasePackageJsonSha256"]},
        })
        following = self.root / "following-promoted"
        hosting.assemble(public, next_stage, following,
                         production_reader=True, promote_home=True)
        self.assertEqual((following / "public/legacy-reader.html").read_bytes(), old_html)
        self.assertEqual(hosting.load(following / "public" / hosting.CATALOG)["defaultPageId"],
                         "following-week")
        self.assertEqual((following / "public/media/new-week/ko.wav").read_bytes(),
                         (public / "media/new-week/ko.wav").read_bytes())

    def test_rejects_overwrite_of_existing_page(self):
        self.new_page["id"] = "previous-week"
        self.new_catalog["pages"][0]["id"] = "previous-week"
        self.new_catalog["defaultPageId"] = "previous-week"
        # A real same-ID stage has different paths and a fresh receipt.
        same_stage = self.root / "same"
        same_stage.mkdir()
        same_page = fixture(same_stage, "previous-week", "2026-09-20")
        same_catalog = {**self.new_catalog, "pages": [same_page]}
        new_hash = write(same_stage / hosting.CATALOG, same_catalog)
        write(same_stage / "stage-receipt.json", {
            "schemaVersion": "sermon-formal-dev-stage-receipt-v1",
            "deploymentStatus": "not_deployed", "httpVerification": "not_run",
            "catalogSha256": new_hash, "pageId": "previous-week",
            "sourceIdentitySha256": same_page["sourceIdentitySha256"],
            "targetLocales": ["ko"], "assetCount": 4,
            "releasePackageSha256": {
                "ko": same_page["targets"]["ko"]["releasePackageJsonSha256"]},
        })
        with self.assertRaisesRegex(ValueError, "Existing page ID"):
            hosting.assemble(self.base, same_stage, self.root / "release")

    def test_second_week_updates_entry_and_keeps_prior_formal_assets(self):
        write(self.base / "index.html", b'<main class="field-main"></main>')
        write(self.base / "weekly.json", {"schemaVersion": "sermon-weekly-catalog-v1",
                                          "weeks": [{"id": "old-legacy-week"}]})
        first = self.root / "first"
        hosting.assemble(self.base, self.stage, first, production_reader=True)
        next_stage = self.root / "next-stage"
        next_stage.mkdir()
        next_page = fixture(next_stage, "following-week", "2026-09-27")
        next_catalog = {**self.new_catalog, "pages": [next_page],
                        "defaultPageId": next_page["id"]}
        catalog_hash = write(next_stage / hosting.CATALOG, next_catalog)
        write(next_stage / "stage-receipt.json", {
            "schemaVersion": "sermon-formal-dev-stage-receipt-v1",
            "deploymentStatus": "not_deployed", "httpVerification": "not_run",
            "catalogSha256": catalog_hash, "pageId": next_page["id"],
            "sourceIdentitySha256": next_page["sourceIdentitySha256"],
            "targetLocales": ["ko"], "assetCount": 4,
            "releasePackageSha256": {
                "ko": next_page["targets"]["ko"]["releasePackageJsonSha256"]},
        })
        second = self.root / "second"
        report = hosting.assemble(first / "public", next_stage, second,
                                  production_reader=True)
        homepage = (second / "public/index.html").read_text()
        self.assertEqual(homepage.count(hosting.ENTRY_LABEL), 1)
        self.assertIn("/pages/following-week/ko", homepage)
        catalog = hosting.load(second / "public" / hosting.CATALOG)
        self.assertEqual([page["id"] for page in catalog["pages"]],
                         ["following-week", "new-week", "previous-week"])
        self.assertEqual(
            hosting.digest(first / "public/media/new-week/ko.wav"),
            hosting.digest(second / "public/media/new-week/ko.wav"))
        self.assertEqual(report["modifiedFiles"], ["index.html", hosting.CATALOG])


if __name__ == "__main__":
    unittest.main()
