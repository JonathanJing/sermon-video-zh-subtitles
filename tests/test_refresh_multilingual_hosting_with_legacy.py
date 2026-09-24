import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from scripts import assemble_multilingual_hosting as hosting
from scripts import refresh_multilingual_hosting_with_legacy as refresh
from tests.test_assemble_multilingual_hosting import fixture, write


LEGACY = Path(__file__).resolve().parents[1] / "experiments/sermon-dubbing-poc"
if str(LEGACY) not in sys.path:
    sys.path.insert(0, str(LEGACY))
from test_weekly_release import release_fixture, week  # noqa: E402
import weekly_release  # noqa: E402


class RefreshHostingTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.base_legacy = release_fixture(
            root / "legacy-base", [week("2026-09-13", "old")],
            ui='<main class="field-main"></main>')
        registry = root / "registry"
        weekly_release.bootstrap(registry, self.base_legacy,
                                 "https://ai-for-god-sermon-audio.web.app")
        candidate = release_fixture(root / "legacy-new", [week("2026-09-20", "new")],
                                    ui="candidate UI")
        self.new_legacy = root / "legacy-prepared"
        weekly_release.prepare(registry, candidate, self.new_legacy)
        stage = root / "stage"
        stage.mkdir()
        page = fixture(stage, "formal-page", "2026-09-20")
        catalog = {"schemaVersion": "sermon-multilingual-catalog-v2",
                   "generatedAt": "2026-09-20T00:00:00Z", "defaultPageId": page["id"],
                   "pages": [page]}
        catalog_hash = write(stage / hosting.CATALOG, catalog)
        write(stage / "stage-receipt.json", {
            "schemaVersion": "sermon-formal-dev-stage-receipt-v1",
            "deploymentStatus": "not_deployed", "httpVerification": "not_run",
            "catalogSha256": catalog_hash, "pageId": page["id"],
            "sourceIdentitySha256": page["sourceIdentitySha256"],
            "targetLocales": ["ko"], "assetCount": 4,
            "releasePackageSha256": {
                "ko": page["targets"]["ko"]["releasePackageJsonSha256"]},
        })
        self.overlay = root / "overlay"
        hosting.assemble(self.base_legacy / "public", stage, self.overlay,
                         production_reader=True)
        self.http = root / "prior-http.json"
        write(self.http, {
            "schemaVersion": "sermon-multilingual-hosting-http-verification-v1",
            "status": "pass", "origin": "https://ai-for-god-sermon-audio.web.app",
            "buildReportSha256": hosting.digest(self.overlay / "build-report.json"),
            "checkedFiles": len(hosting.regular_files(self.overlay / "public")),
        })
        self.out = root / "refreshed"

    def test_weekly_update_retains_formal_assets_and_old_reader(self):
        report = refresh.refresh(self.overlay, self.new_legacy, self.http, self.out)
        self.assertEqual(report["modifiedFiles"], ["weekly.json"])
        self.assertEqual((self.out / "public/multilingual-v2.json").read_bytes(),
                         (self.overlay / "public/multilingual-v2.json").read_bytes())
        self.assertEqual((self.out / "public/index.html").read_bytes(),
                         (self.overlay / "public/index.html").read_bytes())
        self.assertEqual((self.out / "firebase.json").read_bytes(),
                         (self.overlay / "firebase.json").read_bytes())
        catalog = json.loads((self.out / "public/weekly.json").read_text())
        self.assertEqual(len(catalog["weeks"]), 2)
        self.assertTrue((self.out / "public/media/formal-page/ko.wav").is_file())
        self.assertEqual(report["baseFiles"],
                         refresh.snapshot_files(self.overlay / "public"))

    def test_changed_legacy_ui_or_missing_http_receipt_stops(self):
        (self.new_legacy / "public/index.html").write_text("changed UI")
        with self.assertRaisesRegex(ValueError, "unsupported or unsafe|Release file|UI changed"):
            refresh.refresh(self.overlay, self.new_legacy, self.http, self.out)
        self.assertFalse(self.out.exists())
        (self.new_legacy / "public/index.html").write_text('<main class="field-main"></main>')
        prior = json.loads(self.http.read_text())
        prior["buildReportSha256"] = "0" * 64
        write(self.http, prior)
        with self.assertRaisesRegex(ValueError, "Prior Production HTTP receipt"):
            refresh.refresh(self.overlay, self.new_legacy, self.http, self.out)


if __name__ == "__main__":
    unittest.main()
