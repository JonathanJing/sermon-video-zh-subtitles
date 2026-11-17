import copy
import importlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/ops/set_catalog_default_page.py"
MODULE = importlib.import_module("tools.ops.set_catalog_default_page")


def page(identifier, date, kind=None, media_type=None):
    entry = {"id": identifier, "title": f"Title {identifier}", "date": date, "sourceLocale": "en",
             "sourceIdentitySha256": "a" * 64, "defaultTargetLocale": "zh-Hans",
             "targets": {"zh-Hans": {
                 "releasePackageUrl": f"/releases-v2/{identifier}/zh-Hans.json",
                 "releasePackageJsonSha256": "b" * 64, "contentStatus": "human_reviewed",
                 "audioStatus": "unavailable", "capabilities": ["text"]}}}
    if kind is not None:
        entry["contentKind"] = kind
    if media_type is not None:
        entry["mediaType"] = media_type
    return entry


def catalog(pages, default):
    return {"schemaVersion": "sermon-multilingual-catalog-v3", "generatedAt": "2026-11-16T00:00:00Z",
            "defaultPageId": default, "pages": pages}


class DefaultPagePolicyTests(unittest.TestCase):
    def test_a_newer_podcast_never_wins_over_the_latest_sermon(self):
        # Production carried the 11-15 podcast as the default while the 11-15 sermon existed.
        data = catalog([
            page("sermon-20261115", "2026-11-15", "sermon"),
            page("podcast-20261115", "2026-11-15", "podcast", "podcast"),
            page("sermon-20261108", "2026-11-08", "sermon"),
        ], default="podcast-20261115")
        result, receipt = MODULE.apply_policy(data, "latest-sermon")
        self.assertEqual(result["defaultPageId"], "sermon-20261115")
        self.assertEqual(receipt["previousDefaultPageId"], "podcast-20261115")
        self.assertTrue(receipt["changed"])
        self.assertEqual(data["defaultPageId"], "podcast-20261115", "input must not be mutated")

    def test_the_newest_sermon_wins_among_sermons(self):
        data = catalog([page("s1", "2026-10-18", "sermon"), page("s2", "2026-10-25", "sermon"),
                        page("clip", "2026-11-15", "clip")], default="s1")
        result, _ = MODULE.apply_policy(data, "latest-sermon")
        self.assertEqual(result["defaultPageId"], "s2")

    def test_dev_only_pages_are_never_the_default(self):
        data = catalog([page("s1", "2026-10-18", "sermon"),
                        {**page("mockup", "2026-11-15", "sermon"), "simulationOnly": True}], default="s1")
        result, _ = MODULE.apply_policy(data, "latest-sermon")
        self.assertEqual(result["defaultPageId"], "s1")

    def test_a_catalog_without_sermons_is_refused(self):
        data = catalog([page("p1", "2026-11-15", "podcast", "podcast")], default="p1")
        with self.assertRaises(MODULE.DefaultPageError):
            MODULE.apply_policy(data, "latest-sermon")

    def test_applying_twice_reports_no_change(self):
        data = catalog([page("s1", "2026-10-18", "sermon"), page("s2", "2026-10-25", "sermon")], default="s1")
        once, _ = MODULE.apply_policy(data, "latest-sermon")
        twice, receipt = MODULE.apply_policy(once, "latest-sermon")
        self.assertEqual(twice, once)
        self.assertFalse(receipt["changed"])

    def test_legacy_catalog_without_content_kind_falls_back_to_media_type(self):
        data = catalog([page("s1", "2026-10-18"), page("p1", "2026-11-15", media_type="podcast")], default="p1")
        result, _ = MODULE.apply_policy(data, "latest-sermon")
        self.assertEqual(result["defaultPageId"], "s1")

    def test_cli_check_reports_and_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "catalog.json"
            output = Path(directory) / "out.json"
            source.write_text(json.dumps(catalog([page("s1", "2026-11-15", "sermon")], default="p2")
                                         | {"pages": [page("s1", "2026-11-15", "sermon")]}))
            # defaultPageId must exist: use a catalog whose default is an older sermon.
            source.write_text(json.dumps(catalog([page("s1", "2026-11-15", "sermon"),
                                                  page("s0", "2026-11-08", "sermon")], default="s0")))
            pending = subprocess.run([sys.executable, str(SCRIPT), "--input", str(source), "--check"],
                                     capture_output=True, text=True)
            self.assertEqual(pending.returncode, 1, pending.stderr)
            written = subprocess.run([sys.executable, str(SCRIPT), "--input", str(source),
                                      "--output", str(output)], capture_output=True, text=True)
            self.assertEqual(written.returncode, 0, written.stderr)
            settled = subprocess.run([sys.executable, str(SCRIPT), "--input", str(output), "--check"],
                                     capture_output=True, text=True)
            self.assertEqual(settled.returncode, 0, settled.stdout + settled.stderr)


if __name__ == "__main__":
    unittest.main()
