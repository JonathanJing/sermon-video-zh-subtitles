"""Dev banner patching uses temporary Hosting snapshots only."""
import os
from pathlib import Path
import tempfile
import unittest

from scripts import patch_firebase_dev_app_banner as legacy
from tools.ops import patch_firebase_dev_app_banner as banner


class DevBannerPatchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.source = root / "source"
        self.candidate = root / "candidate"
        self.source.mkdir()
        self.candidate.mkdir()
        self.index_before = ("\n".join(banner.COPY) +
                             ' · <a id="devDryRunLink" href="/dry-run">Dry run</a>\n')
        self.label_before = "\n".join(banner.COPY) + "\n"
        (self.source / "index.html").write_text(self.index_before)
        (self.source / "dev-preview-label.mjs").write_text(self.label_before)
        for name in ("index.html", "dev-preview-label.mjs"):
            os.link(self.source / name, self.candidate / name)

    def test_old_import_is_package_module(self):
        self.assertIs(legacy, banner)

    def test_all_banner_copy_and_link_change_without_writing_hardlinked_source(self):
        banner.patch_public(self.candidate)
        index = (self.candidate / "index.html").read_text()
        label = (self.candidate / "dev-preview-label.mjs").read_text()
        self.assertNotIn("devDryRunLink", index)
        for before, after in banner.COPY.items():
            self.assertNotIn(before, index)
            self.assertNotIn(before, label)
            self.assertIn(after, index)
            self.assertIn(after, label)
        self.assertEqual((self.source / "index.html").read_text(), self.index_before)
        self.assertEqual((self.source / "dev-preview-label.mjs").read_text(), self.label_before)
        for name in ("index.html", "dev-preview-label.mjs"):
            self.assertNotEqual((self.source / name).stat().st_ino, (self.candidate / name).stat().st_ino)

    def test_unknown_dry_run_link_rejects_without_changes(self):
        (self.candidate / "index.html").unlink()
        (self.candidate / "index.html").write_text("index without the expected link")
        with self.assertRaisesRegex(ValueError, "Expected known standalone Dev dry-run link"):
            banner.patch_public(self.candidate)
        self.assertEqual((self.candidate / "index.html").read_text(), "index without the expected link")
        self.assertEqual((self.source / "index.html").read_text(), self.index_before)
        self.assertEqual((self.source / "dev-preview-label.mjs").read_text(), self.label_before)


if __name__ == "__main__":
    unittest.main()
