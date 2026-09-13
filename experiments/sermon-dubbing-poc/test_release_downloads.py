"""Inert local download fixtures; no network or deployment calls."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from deploy_firebase import verify_release
import weekly_release as release
from test_weekly_release import ORIGIN, refresh_manifest, release_fixture, week, write_json


def downloadable_week(date, source):
    page, assets = week(date, source)
    page["downloads"] = {}
    for kind, extension in (("readingPdf", "pdf"), ("companionPdf", "pdf"),
                            ("fullVideoMp3", "mp3"), ("fullVideoSrt", "srt")):
        data = f"inert-download:{source}:{kind}".encode()
        name = f"downloads/{hashlib.sha256(data).hexdigest()[:16]}-{kind}.{extension}"
        page["downloads"][kind] = "/" + name
        assets[name] = data
    return page, assets


class DownloadReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.page, self.assets = downloadable_week("2026-09-13", "current")
        self.path = release_fixture(self.root / "candidate", [(self.page, self.assets)])

    def catalog(self):
        return json.loads((self.path / "public/weekly.json").read_text())

    def update_catalog(self, catalog):
        write_json(self.path / "public/weekly.json", catalog)
        refresh_manifest(self.path)

    def assert_rejected(self):
        for validate in (verify_release, release.read_release):
            with self.subTest(validator=validate.__name__):
                with self.assertRaises(ValueError):
                    validate(self.path)

    def test_all_four_formats_are_accepted_and_merge_preserves_history_and_ui(self):
        verify_release(self.path)
        release.read_release(self.path)
        old_page, old_assets = downloadable_week("2026-09-06", "old")
        base = release_fixture(self.root / "base", [(old_page, old_assets)], ui="old UI")
        registry, out = self.root / "registry", self.root / "prepared"
        release.bootstrap(registry, base, ORIGIN)
        registry_before = (registry / "registry.json").read_bytes()
        release.prepare(registry, self.path, out)
        _, catalog = release.read_release(out)
        self.assertEqual({p["id"] for p in catalog["weeks"]}, {old_page["id"], self.page["id"]})
        for name, data in {**old_assets, **self.assets}.items():
            self.assertEqual((out / "public" / name).read_bytes(), data)
        self.assertEqual((out / "public/index.html").read_text(), "old UI")
        self.assertEqual((registry / "registry.json").read_bytes(), registry_before)
        self.assertEqual(next(p for p in catalog["weeks"] if p["id"] == old_page["id"]), old_page)

    def test_downloads_do_not_weaken_hash_or_file_inventory(self):
        name = self.page["downloads"]["readingPdf"][1:]
        path = self.path / "public" / name
        path.write_bytes(b"tampered download")
        self.assert_rejected()
        refresh_manifest(self.path)  # Honest new digest still cannot reuse the old filename.
        self.assert_rejected()
        path.write_bytes(self.assets[name])
        refresh_manifest(self.path)
        (self.path / "public/downloads/unlisted.pdf").write_bytes(b"private")
        self.assert_rejected()
        refresh_manifest(self.path)
        self.assert_rejected()

    def test_catalog_bindings_are_required_and_missing_assets_rejected(self):
        catalog = self.catalog()
        del catalog["weeks"][0]["downloads"]["readingPdf"]
        self.update_catalog(catalog)
        self.assert_rejected()
        catalog["weeks"][0] = copy.deepcopy(self.page)
        (self.path / "public" / self.page["downloads"]["readingPdf"][1:]).unlink()
        self.update_catalog(catalog)
        self.assert_rejected()

    def test_rejects_external_traversal_encoded_and_non_ascii_urls(self):
        good = self.page["downloads"]["readingPdf"]
        invalid = ["https://fixture.example" + good, "//fixture.example" + good,
                   good[1:], "/downloads/../" + good.split("/")[-1],
                   good.replace("/downloads/", "/downloads/%2e%2e/"),
                   good.replace("/downloads/", "/downloads\\"),
                   good + "?download=1", good + "#page=1", good.replace("readingPdf", "阅读"),
                   good.replace("readingPdf", "nested/readingPdf"), "", None, {"url": good}]
        for url in invalid:
            with self.subTest(url=url):
                catalog = self.catalog()
                catalog["weeks"][0]["downloads"]["readingPdf"] = url
                self.update_catalog(catalog)
                self.assert_rejected()

    def test_format_must_match_semantic_kind_even_when_hash_bound(self):
        original = self.catalog()
        old_name = self.page["downloads"]["readingPdf"][1:]
        for extension in ("mp3", "srt", "html", "exe", "PDF"):
            with self.subTest(extension=extension):
                name = old_name.rsplit(".", 1)[0] + "." + extension
                (self.path / "public" / old_name).rename(self.path / "public" / name)
                catalog = copy.deepcopy(original)
                catalog["weeks"][0]["downloads"]["readingPdf"] = "/" + name
                self.update_catalog(catalog)
                self.assert_rejected()
                (self.path / "public" / name).rename(self.path / "public" / old_name)
        catalog = copy.deepcopy(original)
        catalog["weeks"][0]["downloads"]["privateNotes"] = self.page["downloads"]["readingPdf"]
        self.update_catalog(catalog)
        self.assert_rejected()

    def test_empty_and_symlink_files_rejected_even_with_matching_manifest(self):
        old_name = self.page["downloads"]["readingPdf"][1:]
        old_path = self.path / "public" / old_name
        empty_name = "downloads/" + hashlib.sha256(b"").hexdigest()[:16] + "-reading.pdf"
        old_path.unlink()
        empty = self.path / "public" / empty_name
        empty.write_bytes(b"")
        catalog = self.catalog()
        catalog["weeks"][0]["downloads"]["readingPdf"] = "/" + empty_name
        self.update_catalog(catalog)
        self.assert_rejected()
        empty.unlink()
        external = self.root / "original.pdf"
        external.write_bytes(self.assets[old_name])
        old_path.symlink_to(external)
        catalog["weeks"][0]["downloads"]["readingPdf"] = "/" + old_name
        self.update_catalog(catalog)
        self.assert_rejected()

    def test_duplicate_manifest_entry_rejected_by_uploader(self):
        report = json.loads((self.path / "build-report.json").read_text())
        report["files"].append(copy.deepcopy(report["files"][0]))
        write_json(self.path / "build-report.json", report)
        self.assert_rejected()


if __name__ == "__main__":
    unittest.main()
