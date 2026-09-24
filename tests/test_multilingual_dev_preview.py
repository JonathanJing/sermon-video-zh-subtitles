import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts import multilingual_dev_preview as preview


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


if __name__ == "__main__":
    unittest.main()
