import io
import mimetypes
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.error import HTTPError
from urllib.parse import urlparse

from scripts import assemble_multilingual_hosting as hosting
from scripts import deploy_multilingual_hosting as deployment
from scripts import verify_multilingual_hosting as verification
from tests.test_assemble_multilingual_hosting import fixture, write


ORIGIN = "https://ai-for-god-sermon-audio.web.app"


class Response(io.BytesIO):
    def __init__(self, url, data, status, headers):
        super().__init__(data)
        self.url = url
        self.status = status
        self.headers = headers

    def geturl(self):
        return self.url


class FakeHosting:
    def __init__(self, root, *, omit_catalog=False):
        self.root = root
        self.omit_catalog = omit_catalog

    def __call__(self, request, timeout):
        assert timeout > 0
        url = request.full_url
        path = urlparse(url).path
        if path == "/" + hosting.CATALOG and self.omit_catalog:
            raise HTTPError(url, 404, "not found", {}, None)
        if path.startswith("/pages/"):
            path = "/multilingual-reader.html"
        source = self.root / path.lstrip("/")
        if not source.is_file():
            raise HTTPError(url, 404, "not found", {}, None)
        data = source.read_bytes()
        mime = mimetypes.guess_type(str(source))[0] or "application/octet-stream"
        headers = {"Content-Type": mime, "Cache-Control": "no-store"}
        if request.get_header("Range") == "bytes=0-0":
            headers["Content-Range"] = f"bytes 0-0/{len(data)}"
            return Response(url, data[:1], 206, headers)
        return Response(url, data, 200, headers)


class VerifyHostingTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.base, self.stage, self.out = root / "base", root / "stage", root / "out"
        self.base.mkdir()
        self.stage.mkdir()
        new = fixture(self.stage, "new-week", "2026-09-27")
        catalog = {"schemaVersion": "sermon-multilingual-catalog-v2",
                   "generatedAt": "2026-09-27T00:00:00Z", "defaultPageId": "new-week",
                   "pages": [new]}
        catalog_hash = write(self.stage / hosting.CATALOG, catalog)
        write(self.stage / "stage-receipt.json", {
            "schemaVersion": "sermon-formal-dev-stage-receipt-v1",
            "deploymentStatus": "not_deployed", "httpVerification": "not_run",
            "catalogSha256": catalog_hash, "pageId": "new-week",
            "sourceIdentitySha256": new["sourceIdentitySha256"],
            "targetLocales": ["ko"], "assetCount": 4,
            "releasePackageSha256": {
                "ko": new["targets"]["ko"]["releasePackageJsonSha256"]},
        })
        write(self.base / "index.html", b'<html><main class="field-main"></main></html>')
        write(self.base / "weekly.json", {
            "schemaVersion": "sermon-weekly-catalog-v1", "weeks": []})
        write(root / "build-report.json", {
            "schemaVersion": "sermon-weekly-build-v1", "feedbackEnabled": False})
        hosting.assemble(self.base, self.stage, self.out, production_reader=True)

    def test_preflight_checks_all_base_files_and_absent_catalog(self):
        receipt = verification.verify_baseline(
            self.out, ORIGIN, opener=FakeHosting(self.base, omit_catalog=True))
        self.assertEqual(receipt["status"], "pass")
        self.assertEqual(receipt["checkedFiles"], 2)

    def test_preflight_refuses_changed_base(self):
        write(self.base / "weekly.json", b'{"weeks":["newer"]}')
        with self.assertRaisesRegex(ValueError, "baseline changed"):
            verification.verify_baseline(
                self.out, ORIGIN, opener=FakeHosting(self.base, omit_catalog=True))

    def test_postdeploy_checks_hash_range_and_deep_link(self):
        receipt = verification.verify(self.out, ORIGIN,
                                      opener=FakeHosting(self.out / "public"))
        self.assertEqual(receipt["status"], "pass")
        self.assertEqual(receipt["deviceAcceptance"], "not_run")
        self.assertTrue(any(item.get("range206") for item in receipt["results"]))
        self.assertTrue(any(item.get("routeHtml") for item in receipt["results"]))

    def test_two_page_candidate_checks_original_baseline_and_every_route(self):
        second_stage = Path(self.temp.name) / "second-stage"
        second_stage.mkdir()
        next_page = fixture(second_stage, "following-week", "2026-10-04")
        catalog = {"schemaVersion": "sermon-multilingual-catalog-v2",
                   "generatedAt": "2026-10-04T00:00:00Z",
                   "defaultPageId": next_page["id"], "pages": [next_page]}
        catalog_hash = write(second_stage / hosting.CATALOG, catalog)
        write(second_stage / "stage-receipt.json", {
            "schemaVersion": "sermon-formal-dev-stage-receipt-v1",
            "deploymentStatus": "not_deployed", "httpVerification": "not_run",
            "catalogSha256": catalog_hash, "pageId": next_page["id"],
            "sourceIdentitySha256": next_page["sourceIdentitySha256"],
            "targetLocales": ["ko"], "assetCount": 4,
            "releasePackageSha256": {
                "ko": next_page["targets"]["ko"]["releasePackageJsonSha256"]},
        })
        candidate = Path(self.temp.name) / "two-pages"
        hosting.assemble_many(self.base, [self.stage, second_stage], candidate,
                              production_reader=True)
        preflight = verification.verify_baseline(
            candidate, ORIGIN, opener=FakeHosting(self.base, omit_catalog=True))
        self.assertEqual(preflight["checkedFiles"], len(hosting.regular_files(self.base)))
        receipt = verification.verify(candidate, ORIGIN,
                                      opener=FakeHosting(candidate / "public"))
        self.assertEqual(receipt["pageIds"], ["following-week", "new-week"])
        self.assertEqual(sum(bool(item.get("routeHtml")) for item in receipt["results"]), 2)
        self.assertEqual(sum(bool(item.get("range206")) for item in receipt["results"]), 2)

    def test_postdeploy_refuses_tampered_media(self):
        deployed = Path(self.temp.name) / "tampered"
        import shutil
        shutil.copytree(self.out / "public", deployed)
        write(deployed / "media/new-week/ko.wav", b"different")
        with self.assertRaisesRegex(ValueError, "Online file missing or incomplete|Online SHA-256 differs"):
            verification.verify(self.out, ORIGIN, opener=FakeHosting(deployed))

    def test_deployment_plan_binds_fresh_preflight_and_exact_site(self):
        receipt = verification.verify_baseline(
            self.out, ORIGIN, opener=FakeHosting(self.base, omit_catalog=True))
        preflight = Path(self.temp.name) / "preflight.json"
        write(preflight, receipt)
        plan = deployment.prepare(self.out, preflight)
        self.assertEqual(plan["status"], "validated_not_deployed")
        self.assertEqual(plan["siteId"], "ai-for-god-sermon-audio")
        self.assertEqual(plan["command"][5], "hosting:sermonDubbing")
        receipt["checkedAt"] = "2020-01-01T00:00:00+00:00"
        write(preflight, receipt)
        with self.assertRaisesRegex(ValueError, "older than 30 minutes"):
            deployment.prepare(self.out, preflight)

    def test_deployment_plan_refuses_changed_firebase_target(self):
        receipt = verification.verify_baseline(
            self.out, ORIGIN, opener=FakeHosting(self.base, omit_catalog=True))
        preflight = Path(self.temp.name) / "preflight.json"
        write(preflight, receipt)
        config = hosting.load(self.out / "firebase.json")
        config["hosting"]["target"] = "differentSite"
        write(self.out / "firebase.json", config)
        with self.assertRaisesRegex(ValueError, "Firebase configuration changed"):
            deployment.prepare(self.out, preflight)

    def test_deployment_plan_accepts_promoted_multilingual_home(self):
        promoted = Path(self.temp.name) / "promoted"
        hosting.assemble(self.base, self.stage, promoted,
                         production_reader=True, promote_home=True)
        receipt = verification.verify_baseline(
            promoted, ORIGIN, opener=FakeHosting(self.base, omit_catalog=True))
        preflight = Path(self.temp.name) / "preflight-promoted.json"
        write(preflight, receipt)
        self.assertEqual(deployment.prepare(promoted, preflight)["status"],
                         "validated_not_deployed")


if __name__ == "__main__":
    unittest.main()
