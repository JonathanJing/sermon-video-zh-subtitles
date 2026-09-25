import json
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import multilingual_dev_preview as preview
from tests.test_assemble_multilingual_hosting import fixture, write


class DevPreviewDeploymentTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.candidate = Path(self.temp.name) / "candidate"
        public = self.candidate / "public"
        public.mkdir(parents=True)
        (public / "index.html").write_text("<html>Dev preview</html>")
        config = {"hosting": {"site": preview.DEV_SITE, "public": "public",
                              "rewrites": [{"source": "/pages/**",
                                            "destination": "/index.html"}]}}
        (self.candidate / "firebase.json").write_text(json.dumps(config))
        report = {"schemaVersion": "sermon-multilingual-dev-preview-v1",
                  "status": "validated_not_deployed", "projectId": preview.DEV_PROJECT,
                  "siteId": preview.DEV_SITE, "origin": preview.DEV_ORIGIN,
                  "pageId": "reviewed-page", "preservedPocAliases": preview.ALIAS,
                  "files": preview.inventory(public),
                  "devBaseFiles": [{"path": "old.html", "sha256": "a" * 64, "bytes": 3}],
                  "firebaseConfigSha256": preview.hosting.digest(
                      self.candidate / "firebase.json")}
        (self.candidate / "build-report.json").write_text(json.dumps(report))
        self.preflight = Path(self.temp.name) / "preflight.json"
        self.write_preflight()

    def write_preflight(self, *, minutes_old=0):
        self.preflight.write_text(json.dumps({
            "schemaVersion": "sermon-multilingual-dev-preview-preflight-v1",
            "status": "pass", "origin": preview.DEV_ORIGIN,
            "checkedAt": (datetime.now(timezone.utc)
                          - timedelta(minutes=minutes_old)).isoformat(),
            "buildReportSha256": preview.hosting.digest(
                self.candidate / "build-report.json"), "checkedFiles": 1}))

    def test_plan_is_bound_to_dev_site_and_fresh_preflight(self):
        plan = preview.deploy(self.candidate, self.preflight, execute=False)
        self.assertEqual(plan["status"], "validated_not_deployed")
        self.assertEqual(plan["siteId"], preview.DEV_SITE)
        self.assertEqual(plan["command"][plan["command"].index("--project") + 1],
                         preview.DEV_PROJECT)
        self.write_preflight(minutes_old=31)
        with self.assertRaisesRegex(ValueError, "stale"):
            preview.deploy(self.candidate, self.preflight, execute=False)

    def test_rejects_site_or_file_change(self):
        config = preview.hosting.load(self.candidate / "firebase.json")
        config["hosting"]["site"] = "ai-for-god-sermon-audio"
        (self.candidate / "firebase.json").write_text(json.dumps(config))
        with self.assertRaisesRegex(ValueError, "target/config changed"):
            preview.deploy(self.candidate, self.preflight, execute=False)
        config["hosting"]["site"] = preview.DEV_SITE
        (self.candidate / "firebase.json").write_text(json.dumps(config))
        report = preview.hosting.load(self.candidate / "build-report.json")
        report["firebaseConfigSha256"] = preview.hosting.digest(
            self.candidate / "firebase.json")
        (self.candidate / "build-report.json").write_text(json.dumps(report))
        (self.candidate / "public/index.html").write_text("changed")
        with self.assertRaisesRegex(ValueError, "file changed"):
            preview.deploy(self.candidate, self.preflight, execute=False)

    def test_initial_poc_preflight_keeps_legacy_clean_url_routes(self):
        report = preview.hosting.load(self.candidate / "build-report.json")
        report["devBaseFiles"] = [
            {"path": "index.html", "sha256": "a" * 64, "bytes": 3},
            {"path": "404.html", "sha256": "b" * 64, "bytes": 4},
        ]
        (self.candidate / "build-report.json").write_text(json.dumps(report))
        requested = []

        def respond(origin, path):
            requested.append(path)
            return (200, {}, 3, "a" * 64) if path == "/" else (200, {}, 4, "b" * 64)

        with patch.object(preview.verifier, "request_file", side_effect=respond):
            receipt = preview.preflight(self.candidate)
        self.assertEqual(receipt["checkedFiles"], 2)
        self.assertEqual(requested, ["/", "/404"])


class DevPocAssetTest(unittest.TestCase):
    def test_rejects_missing_or_changed_archived_audio(self):
        with TemporaryDirectory() as folder:
            public = Path(folder)
            (public / "media").mkdir()
            (public / "content").mkdir()
            (public / "releases").mkdir()
            audio = public / "media/ko.mp3"
            audio.write_bytes(b"review-only fixture")
            content = public / "content/ko.json"
            content.write_text("{}")
            release = {"pageId": "poc", "targetLocale": "ko",
                       "productionEligible": False,
                       "contentUrl": "/content/ko.json",
                       "contentSha256": preview.hosting.digest(content),
                       "audioUrl": "/media/ko.mp3",
                       "audioSha256": preview.hosting.digest(audio)}
            release_file = public / "releases/ko.json"
            release_file.write_text(json.dumps(release))
            (public / "multilingual.json").write_text(json.dumps({
                "schemaVersion": "sermon-multilingual-demo-catalog-v1",
                "environment": "development", "poc": True,
                "pages": [{"id": "poc", "targets": {"ko": {
                    "releasePackageUrl": "/releases/ko.json",
                    "releasePackageJsonSha256": preview.hosting.digest(release_file)}}}]}))
            (public / "weekly.json").write_text(json.dumps({
                "schemaVersion": "sermon-weekly-catalog-v1",
                "weeks": [{"id": "poc", "tracks": [{"audioUrl": "/media/ko.mp3",
                    "sha256": preview.hosting.digest(audio)}]}]}))
            preview.verify_dev_poc_assets(public)
            audio.write_bytes(b"different")
            with self.assertRaisesRegex(ValueError, "referenced asset missing or changed"):
                preview.verify_dev_poc_assets(public)


class ProductionConfigBindingTest(unittest.TestCase):
    def test_refuses_modified_upstream_firebase_config(self):
        with TemporaryDirectory() as folder:
            candidate = Path(folder)
            config = {"hosting": {"target": "sermonDubbing", "public": "public",
                                  "ignore": ["firebase.json", "**/.*", "**/node_modules/**"]}}
            targets = {"projects": {"default": "ai-for-god-caption-dev"},
                       "targets": {"ai-for-god-caption-dev": {"hosting": {
                           "sermonDubbing": ["ai-for-god-sermon-audio"]}}}}
            (candidate / "firebase.json").write_text(json.dumps(config))
            (candidate / ".firebaserc").write_text(json.dumps(targets))
            report = {"firebaseConfigSha256": preview.hosting.digest(candidate / "firebase.json"),
                      "firebaseTargetsSha256": preview.hosting.digest(candidate / ".firebaserc")}
            self.assertEqual(preview.checked_production_config(candidate, report), config)
            config["hosting"]["ignore"].append("**/*.mp3")
            (candidate / "firebase.json").write_text(json.dumps(config))
            with self.assertRaisesRegex(ValueError, "configuration changed"):
                preview.checked_production_config(candidate, report)


class DevHttpVerificationTest(unittest.TestCase):
    def test_voice_demo_accepts_verified_full_body_when_range_is_ignored(self):
        with TemporaryDirectory() as folder:
            candidate = Path(folder)
            path = "/voice-demos/2026-09-21-v2/test/en-original.mp3"
            audio = candidate / "public" / path.lstrip("/")
            audio.parent.mkdir(parents=True)
            payload = b"ID3demo"
            audio.write_bytes(payload)
            (candidate / "build-report.json").write_text("{}")
            asset = {"path": path, "bytes": len(payload),
                     "sha256": hashlib.sha256(payload).hexdigest()}
            report = {"schemaVersion": "sermon-multilingual-dev-preview-v3",
                      "pageId": "reviewed-page", "files": []}
            catalog = {"pages": [{"id": "reviewed-page", "targets": {}}]}
            demos = {"speakers": [{"original": asset, "samples": []}]}
            with patch.object(preview, "candidate_report", return_value=report), \
                 patch.object(preview.hosting, "load", return_value=catalog), \
                 patch("scripts.stage_voice_demo_dev.public_catalog", return_value=demos), \
                 patch.object(preview.verifier, "request_file", return_value=(
                     200, {"content-type": "audio/mpeg"}, len(payload), asset["sha256"])) as request:
                receipt = preview.verify(candidate)
            self.assertEqual(receipt["status"], "pass")
            self.assertEqual(receipt["results"][0]["fullBodyFallback"], True)
            request.assert_called_once_with(preview.DEV_ORIGIN, path,
                                            request_headers={"Range": "bytes=0-0"})
            with patch.object(preview, "candidate_report", return_value=report), \
                 patch.object(preview.hosting, "load", return_value=catalog), \
                 patch("scripts.stage_voice_demo_dev.public_catalog", return_value=demos), \
                 patch.object(preview.verifier, "request_file", return_value=(
                     206, {"content-range": f"bytes 0-0/{len(payload)}"}, 1,
                     hashlib.sha256(payload[:1]).hexdigest())):
                receipt = preview.verify(candidate)
            self.assertEqual(receipt["results"][0]["range206"], True)
            with patch.object(preview, "candidate_report", return_value=report), \
                 patch.object(preview.hosting, "load", return_value=catalog), \
                 patch("scripts.stage_voice_demo_dev.public_catalog", return_value=demos), \
                 patch.object(preview.verifier, "request_file", return_value=(
                     200, {}, len(payload), "0" * 64)):
                with self.assertRaisesRegex(ValueError, "Range/full-body check failed"):
                    preview.verify(candidate)

    def test_rejects_wrong_public_content_type(self):
        with TemporaryDirectory() as folder:
            candidate = Path(folder)
            (candidate / "build-report.json").write_text("{}")
            report = {"pageId": "reviewed-page", "files": [{
                "path": "multilingual-v2.json", "bytes": 2, "sha256": "a" * 64}]}
            catalog = {"pages": [{"id": "reviewed-page", "targets": {}}]}
            with patch.object(preview, "candidate_report", return_value=report), \
                 patch.object(preview.hosting, "load", return_value=catalog), \
                 patch.object(preview.verifier, "request_file", return_value=(
                     200, {"content-type": "text/html", "cache-control": "no-store"},
                     2, "a" * 64)):
                with self.assertRaisesRegex(ValueError, "Unexpected Dev Content-Type"):
                    preview.verify(candidate)

    def test_records_content_type_on_pass(self):
        with TemporaryDirectory() as folder:
            candidate = Path(folder)
            (candidate / "build-report.json").write_text("{}")
            report = {"pageId": "reviewed-page", "files": [{
                "path": "multilingual-v2.json", "bytes": 2, "sha256": "a" * 64}]}
            catalog = {"pages": [{"id": "reviewed-page", "targets": {}}]}
            with patch.object(preview, "candidate_report", return_value=report), \
                 patch.object(preview.hosting, "load", return_value=catalog), \
                 patch.object(preview.verifier, "request_file", return_value=(
                     200, {"content-type": "application/json; charset=utf-8",
                           "cache-control": "no-store"}, 2, "a" * 64)):
                receipt = preview.verify(candidate)
            self.assertEqual(receipt["status"], "pass")
            self.assertEqual(receipt["results"][0]["contentType"], "application/json")


class DevUpdateTest(unittest.TestCase):
    def test_next_reviewed_page_preserves_dev_and_uses_current_clean_urls(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            base = root / "current-dev"
            public = base / "public"
            public.mkdir(parents=True)
            prior = fixture(public, "reviewed-prior", "2026-09-20")
            write(public / "multilingual-v2.json", {
                "schemaVersion": "sermon-multilingual-catalog-v2",
                "generatedAt": "2026-09-20T00:00:00Z",
                "defaultPageId": prior["id"], "pages": [prior]})
            write(public / "multilingual.json", {
                "schemaVersion": "sermon-multilingual-demo-catalog-v1",
                "environment": "development", "poc": True, "pages": []})
            write(public / "weekly.json", {"schemaVersion": "sermon-weekly-catalog-v1",
                                           "weeks": []})
            for name in preview.ALIAS.values():
                write(public / name, b"preserved experiment")
            html = ('<html><span id="devPreviewMessage">old clip only</span>'
                    '<div data-reader-mode="production"></div></html>')
            write(public / "index.html", html.encode())
            write(public / "multilingual-reader.html", html.encode())
            write(public / "404.html", b"dev not found")
            write(public / "dev-preview-label.mjs", b"old clip label")
            config = {"hosting": {"site": preview.DEV_SITE, "public": "public",
                                  "cleanUrls": False,
                                  "rewrites": [{"source": "/pages/**",
                                                "destination": "/index.html"}]}}
            write(base / "firebase.json", config)
            write(base / "build-report.json", {
                "schemaVersion": "sermon-multilingual-dev-preview-v1",
                "status": "validated_not_deployed", "projectId": preview.DEV_PROJECT,
                "siteId": preview.DEV_SITE, "origin": preview.DEV_ORIGIN,
                "pageId": prior["id"], "preservedPocAliases": preview.ALIAS,
                "files": preview.inventory(public),
                "devBaseFiles": [{"path": "old.html", "sha256": "a" * 64,
                                  "bytes": 3}],
                "firebaseConfigSha256": preview.hosting.digest(base / "firebase.json")})
            stage = root / "stage"
            stage.mkdir()
            new = fixture(stage, "reviewed-next", "2026-09-27")
            catalog = {"schemaVersion": "sermon-multilingual-catalog-v2",
                       "generatedAt": "2026-09-27T00:00:00Z",
                       "defaultPageId": new["id"], "pages": [new]}
            stage_hash = write(stage / "multilingual-v2.json", catalog)
            write(stage / "stage-receipt.json", {
                "schemaVersion": "sermon-formal-dev-stage-receipt-v1",
                "deploymentStatus": "not_deployed", "httpVerification": "not_run",
                "catalogSha256": stage_hash, "pageId": new["id"],
                "sourceIdentitySha256": new["sourceIdentitySha256"],
                "targetLocales": ["ko"], "assetCount": 4,
                "releasePackageSha256": {
                    "ko": new["targets"]["ko"]["releasePackageJsonSha256"]}})

            candidate = root / "next-dev"
            with self.assertRaisesRegex(ValueError, "all three locales"):
                preview.prepare_update(base, stage, candidate)
            self.assertFalse(candidate.exists())
            korean = preview.hosting.load(stage / "releases/reviewed-next/ko.json")
            for locale in ("zh-Hans", "es"):
                release = json.loads(json.dumps(korean))
                release["targetLocale"] = release["contentLocale"] = release["audioLocale"] = locale
                for asset in release["assets"]:
                    source = stage / asset["path"].lstrip("/")
                    asset["path"] = asset["path"].replace("/ko.", f"/{locale}.")
                    target = stage / asset["path"].lstrip("/")
                    asset["sha256"] = write(target, source.read_bytes())
                release_hash = write(stage / f"releases/reviewed-next/{locale}.json", release)
                new["targets"][locale] = {**new["targets"]["ko"],
                                          "releasePackageUrl": f"/releases/reviewed-next/{locale}.json",
                                          "releasePackageJsonSha256": release_hash}
            catalog["pages"] = [new]
            stage_hash = write(stage / "multilingual-v2.json", catalog)
            write(stage / "stage-receipt.json", {
                "schemaVersion": "sermon-formal-dev-stage-receipt-v1",
                "deploymentStatus": "not_deployed", "httpVerification": "not_run",
                "catalogSha256": stage_hash, "pageId": new["id"],
                "sourceIdentitySha256": new["sourceIdentitySha256"],
                "targetLocales": ["zh-Hans", "ko", "es"], "assetCount": 12,
                "releasePackageSha256": {
                    locale: target["releasePackageJsonSha256"]
                    for locale, target in new["targets"].items()}})
            report = preview.prepare_update(base, stage, candidate)
            self.assertEqual(report["schemaVersion"], "sermon-multilingual-dev-preview-v2")
            self.assertEqual(report["pageId"], new["id"])
            self.assertFalse(report["baseCleanUrls"])
            self.assertEqual(preview.candidate_report(candidate), report)
            self.assertEqual((candidate / "dev-base-build-report.json").read_bytes(),
                             (base / "build-report.json").read_bytes())
            merged = preview.hosting.load(candidate / "public/multilingual-v2.json")
            self.assertEqual([page["id"] for page in merged["pages"]],
                             ["reviewed-next", "reviewed-prior"])
            self.assertEqual((candidate / "public/dev-poc.html").read_bytes(),
                             (public / "dev-poc.html").read_bytes())
            self.assertEqual((candidate / "public/404.html").read_bytes(),
                             (public / "404.html").read_bytes())
            self.assertIn(preview.DEV_MESSAGE,
                          (candidate / "public/index.html").read_text())
            self.assertEqual((candidate / "rollback-multilingual-v2.json").read_bytes(),
                             (public / "multilingual-v2.json").read_bytes())
            expected = {"/" + item["path"]: item for item in report["devBaseFiles"]}
            requested = []

            def respond(origin, path):
                requested.append(path)
                item = expected[path]
                return 200, {}, item["bytes"], item["sha256"]

            with patch.object(preview.verifier, "request_file", side_effect=respond):
                preflight = preview.preflight(candidate)
            self.assertEqual(preflight["checkedFiles"], len(expected))
            self.assertIn("/404.html", requested)
            self.assertIn("/index.html", requested)
            self.assertNotIn("/404", requested)
            self.assertNotIn("/", requested)

            report_path = candidate / "build-report.json"
            report["baseBuildReportSha256"] = "0" * 64
            report_path.write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError, "provenance changed"):
                preview.candidate_report(candidate)
            report["baseBuildReportSha256"] = preview.hosting.digest(
                candidate / "dev-base-build-report.json")
            report_path.write_text(json.dumps(report))
            (candidate / "rollback-multilingual-v2.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "provenance changed"):
                preview.candidate_report(candidate)


if __name__ == "__main__":
    unittest.main()
