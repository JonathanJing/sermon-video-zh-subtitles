import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import align_firebase_dev_v3 as dev


class DevV3CurrentWeekTests(unittest.TestCase):
    def test_required_schemas_are_checked_in(self):
        for name in ("sermon-multilingual-catalog-v3.schema.json",
                     "sermon-target-language-release-package-v2.schema.json"):
            path = dev.ROOT / "schemas" / name
            self.assertTrue(path.is_file(), name)
            self.assertTrue(json.loads(path.read_text(encoding="utf-8")))

    def test_validates_catalog_default_instead_of_old_migration_week(self):
        page_id = "reviewed-next-week"
        with TemporaryDirectory() as folder:
            public = Path(folder)

            def write(name, value):
                path = public / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(value), encoding="utf-8")

            targets = {}
            for locale in ("zh-Hans", "ko", "es"):
                release_path = f"releases-v2/{page_id}/{locale}.json"
                targets[locale] = {
                    "contentStatus": "human_reviewed", "audioStatus": "human_reviewed",
                    "releasePackageUrl": "/" + release_path,
                    "releasePackageJsonSha256": "a" * 64,
                }
                write(release_path, {
                    "pageId": page_id, "targetLocale": locale,
                    "status": "published_http_verified", "httpVerification": {"status": "pass"},
                    "assets": [{"role": role, "path": f"/{role}/{page_id}/{locale}.json",
                                "sha256": "a" * 64}
                               for role in ("page", "content", "captions", "audio")],
                })
                write(f"content/{page_id}/{locale}.json", {
                    "pageId": page_id, "targetLocale": locale,
                    "browserVideoSha256": "b" * 64,
                })
            write("multilingual-v3.json", {"defaultPageId": page_id,
                                           "pages": [{"id": page_id, "targets": targets}]})
            write(f"english-reference/{page_id}.json", {
                "pageId": page_id, "targets": targets, "reviewState": "human_approved"})
            write(f"alignment/{page_id}.json", {"pageId": page_id, "targets": targets})
            with patch.object(dev, "Draft202012Validator") as validator, \
                 patch.object(dev, "checked", side_effect=lambda path, _: path) as checked:
                self.assertEqual(dev.validate_published_week(public),
                                 (page_id, ["es", "ko", "zh-Hans"]))
            self.assertEqual(validator.return_value.validate.call_count, 4)
            self.assertIn(public / f"pages/{page_id}/full-video-browser.mp4",
                          [call.args[0] for call in checked.call_args_list])


if __name__ == "__main__":
    unittest.main()
