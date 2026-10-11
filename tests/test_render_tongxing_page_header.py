import copy
import tempfile
import unittest
from pathlib import Path
from scripts import render_tongxing_page_header as renderer


class HeaderQuoteGuardTests(unittest.TestCase):
    def test_selected_locale_must_match_formal_source_and_candidate(self):
        quote = {"pageId": "page", "sourceIdentitySha256": "source"}
        page = {"targets": {"ko": {}}}
        valid = {"pageId": "page", "targetLocale": "ko",
                 "englishSourcePackageJsonSha256": "source",
                 "targetLanguageCandidateJsonSha256": "candidate"}
        renderer.validate_target_binding(quote, page, "ko", valid, valid)
        for flag in ("diagnosticOnly", "simulationOnly"):
            bad_page = copy.deepcopy(page)
            bad_page["targets"]["ko"][flag] = True
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                renderer.validate_target_binding(quote, bad_page, "ko", valid, valid)
        for field in valid:
            bad = dict(valid, **{field: "other"})
            for content, release in ((bad, valid), (valid, bad)):
                with self.subTest(field=field), self.assertRaises(ValueError):
                    renderer.validate_target_binding(quote, page, "ko", content, release)

    def test_all_locale_outputs_are_checked_before_any_write(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            old = output / "tongxing-page-header-es.mp4"
            old.write_bytes(b"existing video")
            with self.assertRaises(FileExistsError):
                renderer.preflight_outputs(output, ["zh", "en", "ko", "es"])
            self.assertEqual(old.read_bytes(), b"existing video")
            self.assertEqual(list(output.iterdir()), [old])
