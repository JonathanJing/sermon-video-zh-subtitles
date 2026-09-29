import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts import prepare_v3_bucket_video_migration as migration
from scripts import assemble_multilingual_v3_update as weekly
from tests.test_assemble_multilingual_v3_update import page_fixture, catalog, write


class BucketVideoMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.base = self.root / "base"
        public = self.base / "public"
        page = page_fixture(public, "sermon-1", "2026-09-27")
        write(public / weekly.CATALOG, catalog(page))
        write(public / "weekly.json", {"schemaVersion": "sermon-weekly-catalog-v1"})
        write(self.base / "firebase.json", {
            "hosting": {
                "public": "public", "site": "test-sermon-site",
                "headers": [{"source": "**", "headers": [{
                    "key": "Content-Security-Policy",
                    "value": "default-src 'none'; media-src 'self' blob:;"
                }]}],
            }
        })

    def test_migration_preserves_assets_and_adds_exact_redirect(self) -> None:
        out = self.root / "candidate"
        report = migration.prepare(self.base, "sermon-1",
                                   "ai-for-god-sermon-media-dev", out)
        self.assertEqual(report["status"], "validated_not_deployed")
        video = report["videoDelivery"]
        self.assertEqual(video["bytes"], len(b"complete sermon video"))
        self.assertFalse((out / "public/pages/sermon-1/full-video-browser.mp4").exists())
        self.assertTrue((self.base / "public/pages/sermon-1/full-video-browser.mp4").exists())
        candidate_page = weekly.load(out / "public/multilingual-v3.json")["pages"][0]
        self.assertEqual(candidate_page["videoDelivery"], video)
        config = weekly.load(out / "firebase.json")["hosting"]
        self.assertEqual(config["redirects"], [{
            "source": video["canonicalUrl"],
            "destination": video["storageUrl"], "type": 302,
        }])
        self.assertIn("https://storage.googleapis.com",
                      config["headers"][0]["headers"][0]["value"])
        weekly.validate_page(out / "public", candidate_page)

    def test_bad_bucket_and_existing_output_fail_without_changing_source(self) -> None:
        with self.assertRaisesRegex(ValueError, "dedicated public"):
            migration.prepare(self.base, "sermon-1", "gcf-v2-sources", self.root / "bad")
        out = self.root / "candidate"
        out.mkdir()
        with self.assertRaisesRegex(ValueError, "Output already exists"):
            migration.prepare(self.base, "sermon-1",
                              "ai-for-god-sermon-media-dev", out)
        self.assertTrue((self.base / "public/pages/sermon-1/full-video-browser.mp4").exists())


if __name__ == "__main__":
    unittest.main()
