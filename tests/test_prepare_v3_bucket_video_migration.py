import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts import prepare_v3_bucket_video_migration as migration
from tools.ops import prepare_v3_bucket_video_migration as implementation
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

    def test_legacy_and_new_cli_candidate_bytes_match(self) -> None:
        self.assertIs(migration, implementation)
        repo = Path(__file__).resolve().parents[1]
        source = {p.relative_to(self.base).as_posix(): p.read_bytes()
                  for p in self.base.rglob("*") if p.is_file()}
        candidates = []
        for index, command in enumerate((
            [sys.executable, str(repo / "scripts/prepare_v3_bucket_video_migration.py")],
            [sys.executable, "-m", "scripts.prepare_v3_bucket_video_migration"],
            [sys.executable, str(repo / "tools/ops/prepare_v3_bucket_video_migration.py")],
            [sys.executable, "-m", "tools.ops.prepare_v3_bucket_video_migration"],
        )):
            out = self.root / f"candidate-{index}"
            result = subprocess.run([*command, "--base", str(self.base), "--page-id", "sermon-1",
                                     "--bucket", "ai-for-god-sermon-media-dev", "--out", str(out)],
                                    cwd=repo, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            files = {p.relative_to(out).as_posix(): p.read_bytes()
                     for p in out.rglob("*") if p.is_file() and p.name != "migration-report.json"}
            report = json.loads((out / "migration-report.json").read_text())
            self.assertIn("createdAt", report)
            del report["createdAt"]
            candidates.append((result.stdout, files, report))
        self.assertTrue(all(candidate == candidates[0] for candidate in candidates))
        self.assertEqual(source, {p.relative_to(self.base).as_posix(): p.read_bytes()
                                  for p in self.base.rglob("*") if p.is_file()})

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
