import copy
import importlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/ops/normalize_catalog_content_kind.py"
MODULE = importlib.import_module("tools.ops.normalize_catalog_content_kind")


def category(zh, en):
    return {"schemaVersion": "sermon-page-display-category-v1", "labels": {"en": en, "zh-Hans": zh}}


def page(identifier, media_type=None, display_category=None):
    entry = {"id": identifier, "title": f"Title {identifier}", "date": "2026-11-15",
             "sourceLocale": "en", "sourceIdentitySha256": "a" * 64, "defaultTargetLocale": "zh-Hans",
             "targets": {"zh-Hans": {
                 "releasePackageUrl": f"/releases-v2/{identifier}/zh-Hans.json",
                 "releasePackageJsonSha256": "b" * 64, "contentStatus": "human_reviewed",
                 "audioStatus": "unavailable", "capabilities": ["text"]}}}
    if media_type:
        entry["mediaType"] = media_type
    if display_category:
        entry["displayCategory"] = display_category
    return entry


def catalog():
    return {"schemaVersion": "sermon-multilingual-catalog-v3", "generatedAt": "2026-11-16T00:00:00Z",
            "defaultPageId": "revelation-jesus-is-better-20261115",
            "pages": [
                # The 2026-11-16 regression: a Sunday sermon tagged mediaType podcast.
                page("revelation-jesus-is-better-20261115", "podcast", category("周日证道", "Sunday sermon")),
                page("if-i-had-more-time-jesus-is-better-than-this-world", "podcast",
                     category("证道播客", "Sermon Podcast")),
                page("sentence-first-clip", "podcast", category("实验片段", "Experiment clip")),
                page("resi-20261004-69ba7a66"),
                page("legacy-podcast", "podcast"),
            ]}


class NormalizeCatalogContentKindTests(unittest.TestCase):
    def test_sermon_pages_stop_claiming_the_podcast_media_type(self):
        result, changes = MODULE.normalize(catalog())
        by_id = {entry["id"]: entry for entry in result["pages"]}
        sermon = by_id["revelation-jesus-is-better-20261115"]
        self.assertEqual(sermon["contentKind"], "sermon")
        self.assertNotIn("mediaType", sermon)
        podcast = by_id["if-i-had-more-time-jesus-is-better-than-this-world"]
        self.assertEqual(podcast["contentKind"], "podcast")
        self.assertEqual(podcast["mediaType"], "podcast")
        clip = by_id["sentence-first-clip"]
        self.assertEqual(clip["contentKind"], "clip")
        self.assertNotIn("mediaType", clip)
        # A page without a category keeps the historical client rule, made explicit.
        self.assertEqual(by_id["resi-20261004-69ba7a66"]["contentKind"], "sermon")
        self.assertEqual(by_id["legacy-podcast"]["contentKind"], "podcast")
        self.assertEqual({change["pageId"] for change in changes},
                         {entry["id"] for entry in result["pages"]})

    def test_input_is_not_mutated(self):
        before = catalog()
        snapshot = copy.deepcopy(before)
        MODULE.normalize(before)
        self.assertEqual(before, snapshot)

    def test_normalized_catalog_matches_the_catalog_schema(self):
        from jsonschema import Draft202012Validator, FormatChecker
        schema = json.loads((ROOT / "schemas/sermon-multilingual-catalog-v3.schema.json").read_text())
        result, _ = MODULE.normalize(catalog())
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(result)
        self.assertEqual(sorted(entry["contentKind"] for entry in result["pages"]),
                         ["clip", "podcast", "podcast", "sermon", "sermon"])

    def test_unknown_category_is_refused_instead_of_guessed(self):
        data = catalog()
        data["pages"][0]["displayCategory"] = category("研读材料", "Study material")
        with self.assertRaises(MODULE.CatalogKindError):
            MODULE.normalize(data)

    def test_unsupported_catalog_schema_is_refused(self):
        data = catalog()
        data["schemaVersion"] = "sermon-multilingual-catalog-v9"
        with self.assertRaises(MODULE.CatalogKindError):
            MODULE.normalize(data)

    def test_normalizing_twice_changes_nothing(self):
        once, _ = MODULE.normalize(catalog())
        twice, changes = MODULE.normalize(once)
        self.assertEqual(twice, once)
        self.assertEqual(changes, [])

    def test_cli_check_reports_pending_changes_and_passes_after_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "catalog.json"
            output = Path(directory) / "normalized.json"
            source.write_text(json.dumps(catalog()))
            pending = subprocess.run([sys.executable, str(SCRIPT), "--input", str(source), "--check"],
                                     capture_output=True, text=True)
            self.assertEqual(pending.returncode, 1, pending.stderr)
            self.assertIn("5 of 5 pages changed", pending.stdout)
            written = subprocess.run([sys.executable, str(SCRIPT), "--input", str(source),
                                      "--output", str(output)], capture_output=True, text=True)
            self.assertEqual(written.returncode, 0, written.stderr)
            settled = subprocess.run([sys.executable, str(SCRIPT), "--input", str(output), "--check"],
                                     capture_output=True, text=True)
            self.assertEqual(settled.returncode, 0, settled.stdout + settled.stderr)
            self.assertIn("0 of 5 pages changed", settled.stdout)


if __name__ == "__main__":
    unittest.main()
