import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/update_catalog_display_categories.py"
SPEC = importlib.util.spec_from_file_location("category_updates", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def category(label="正式播放版"):
    return {"schemaVersion": "sermon-page-display-category-v1", "labels": {"en": "Archive", "zh-Hans": label}}


def catalog(version=3):
    return {"schemaVersion": f"sermon-multilingual-catalog-v{version}", "generatedAt": "2026-10-06T00:00:00Z",
            "defaultPageId": "page-1", "pages": [{"id": "page-1", "title": "Existing sermon",
            "date": "2026-10-04", "sourceLocale": "en", "sourceIdentitySha256": "a" * 64,
            "defaultTargetLocale": "zh-Hans", "targets": {"zh-Hans": {
                "releasePackageUrl": f"/releases{'-v2' if version >= 3 else ''}/page-1/zh-Hans.json",
                "releasePackageJsonSha256": "b" * 64, "contentStatus": "human_reviewed",
                "audioStatus": "unavailable", "capabilities": ["text"]}}}]}


class CategoryUpdateTests(unittest.TestCase):
    def test_shared_contract_matches_all_inline_definitions(self):
        shared = json.loads((ROOT / "schemas/sermon-page-display-category-v1.schema.json").read_text())
        body = {k: v for k, v in shared.items() if k not in {"$schema", "$id", "title"}}
        Draft202012Validator.check_schema(shared)
        for version in (2, 3, 4):
            schema = json.loads((ROOT / f"schemas/sermon-multilingual-catalog-v{version}.schema.json").read_text())
            self.assertEqual(schema["$defs"]["displayCategory"], body)
            Draft202012Validator.check_schema(schema)

    def test_update_changes_only_category_and_preserves_identity(self):
        for version in (2, 3, 4):
            before = catalog(version)
            if version == 2:
                before["pages"][0].pop("title")
            result = MODULE.update_categories(before, {"page-1": category()})
            self.assertNotIn("displayCategory", before["pages"][0])
            self.assertEqual(result["pages"][0].pop("displayCategory"), category())
            self.assertEqual(result, before)

    def test_literal_text_and_unicode_scalar_length(self):
        for label in ("<Study>", "🎙" * 48):
            result = MODULE.update_categories(catalog(), {"page-1": category(label)})
            self.assertEqual(result["pages"][0]["displayCategory"]["labels"]["zh-Hans"], label)
        with self.assertRaises(ValueError):
            MODULE.update_categories(catalog(), {"page-1": category("🎙" * 49)})

    def test_removal_preserves_other_metadata(self):
        before = catalog()
        before["pages"][0]["displayCategory"] = category()
        result = MODULE.update_categories(before, {"page-1": None})
        expected = copy.deepcopy(before)
        expected["pages"][0].pop("displayCategory")
        self.assertEqual(result, expected)

    def test_bad_labels_are_rejected(self):
        for labels in ({"zh-Hans": "播客"}, {"en": " "}, {"en": "x" * 49},
                       {"en": "first\nsecond"}, {"en": "trailing\n"}, {"en": "a\u0085b"}, {"en": "a\u2028b"}, {"en": "Podcast", "bad_locale": "Bad"},
                       {"en": "Archive", **{f"aa-{i:02d}": "A" for i in range(16)}}):
            with self.subTest(labels=labels), self.assertRaises(ValueError):
                MODULE.update_categories(catalog(), {"page-1": {"schemaVersion": "sermon-page-display-category-v1", "labels": labels}})
        for value in ({**category(), "approval": "human_reviewed"}, {**category(), "schemaVersion": "future-v2"}):
            with self.assertRaises(ValueError):
                MODULE.update_categories(catalog(), {"page-1": value})

    def test_unknown_ids_and_invalid_input_are_rejected(self):
        for updates in ({"missing": category()}, {}, []):
            with self.assertRaises(ValueError):
                MODULE.update_categories(catalog(), updates)
        before = catalog()
        before["pages"].append(copy.deepcopy(before["pages"][0]))
        with self.assertRaises(ValueError):
            MODULE.update_categories(before, {"page-1": category()})
        before = catalog()
        before["pages"][0]["targets"]["zh-Hans"]["releasePackageJsonSha256"] = "bad"
        with self.assertRaises(ValueError):
            MODULE.update_categories(before, {"page-1": category()})

    def test_cli_atomic_output_receipt_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, updates, output = [root / name for name in ("catalog.json", "updates.json", "result.json")]
            source.write_text(json.dumps(catalog()))
            updates.write_text(json.dumps({"page-1": category("播客")}))
            args = [sys.executable, str(SCRIPT), "--catalog", str(source), "--updates", str(updates), "--output", str(output)]
            run = subprocess.run(args, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            receipt = json.loads(run.stdout)
            self.assertFalse(receipt["deployed"])
            self.assertEqual(receipt["updatedPageIds"], ["page-1"])
            saved = output.read_bytes()
            self.assertNotEqual(subprocess.run(args, capture_output=True).returncode, 0)
            self.assertEqual(output.read_bytes(), saved)
            args[-1] = str(source)
            self.assertNotEqual(subprocess.run(args, capture_output=True).returncode, 0)
            self.assertEqual(json.loads(source.read_text()), catalog())

    def test_v4_machine_checked_identity_and_removal(self):
        before = catalog(4)
        target = before["pages"][0]["targets"]["zh-Hans"]
        target.update(releasePackageUrl="/releases-v4/page-1/zh-Hans.json",
                      contentStatus="machine_checked", audioStatus="machine_checked",
                      capabilities=["text", "captions", "audio"])
        updated = MODULE.update_categories(before, {"page-1": category()})
        self.assertEqual(MODULE.update_categories(updated, {"page-1": None}), before)
        invalid = copy.deepcopy(before)
        invalid["pages"][0]["targets"]["zh-Hans"]["releasePackageUrl"] = "/releases-v2/page-1/zh-Hans.json"
        with self.assertRaises(ValueError):
            MODULE.update_categories(invalid, {"page-1": category()})

    def test_non_finite_json_constants_are_rejected(self):
        for constant in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(constant=constant), self.assertRaises(ValueError):
                MODULE.parse_json(('{"value":' + constant + '}').encode())

    def test_serialization_refuses_non_finite_values_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, updates, output = [root / name for name in ("catalog.json", "updates.json", "result.json")]
            source.write_text(json.dumps(catalog()))
            updates.write_text(json.dumps({"page-1": category()}))
            for value in (float("nan"), float("inf"), float("-inf")):
                result = catalog()
                result["unexpected"] = value
                args = [str(SCRIPT), "--catalog", str(source), "--updates", str(updates), "--output", str(output)]
                with self.subTest(value=value), mock.patch.object(sys, "argv", args), mock.patch.object(
                        MODULE, "update_categories", return_value=result), mock.patch("sys.stderr"):
                    with self.assertRaises(SystemExit) as error:
                        MODULE.main()
                    self.assertEqual(error.exception.code, 1)
                    self.assertFalse(output.exists())

    def test_duplicate_json_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text('{"page-1":null,"page-1":null}')
            with self.assertRaises(ValueError):
                MODULE.read_json(path)


if __name__ == "__main__":
    unittest.main()
