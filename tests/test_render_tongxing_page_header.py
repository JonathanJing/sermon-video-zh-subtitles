import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import render_tongxing_page_header as renderer


class HeaderQuoteGuardTests(unittest.TestCase):
    def test_screenshot_manifest_binds_bytes_and_uses_declared_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            screens = Path(directory)
            image = b'synthetic screenshot bytes'
            revision = 'a' * 40
            digest = hashlib.sha256(image).hexdigest()
            manifest = (f'- Revision: `{revision}` (branch `test`, clean)\n'
                        f'| File | SHA256 | Shows |\n|---|---|---|\n'
                        f'| {renderer.SCREENSHOT_NAME} | `{digest}` | transcript |\n')
            (screens / renderer.SCREENSHOT_NAME).write_bytes(image)
            (screens / 'MANIFEST.md').write_text(manifest)
            actual, sources = renderer.validate_screenshot_manifest(screens)
            self.assertEqual(actual, revision)
            (screens / renderer.SCREENSHOT_NAME).write_bytes(b'replaced')
            self.assertEqual(sources[renderer.SCREENSHOT_NAME], image)
            with self.assertRaisesRegex(ValueError, 'SHA256 differs'):
                renderer.validate_screenshot_manifest(screens)

    def test_unbound_manifest_fails_before_creating_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'MANIFEST.md').write_text('- Revision: `' + 'c' * 40 + '`\n')
            output = root / 'output'
            with patch('sys.argv', ['renderer', '--screens', str(root), '--logo', 'unused',
                                    '--font', 'unused', '--output', str(output)]):
                with self.assertRaisesRegex(ValueError, 'filename/SHA256'):
                    renderer.main()
            self.assertFalse(output.exists())

    def test_missing_ambiguous_or_invalid_screenshot_identity_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            screens = Path(directory)
            image = b'synthetic'
            (screens / renderer.SCREENSHOT_NAME).write_bytes(image)
            revision = '- Revision: `' + 'b' * 40 + '`\n'
            row = '| ' + renderer.SCREENSHOT_NAME + ' | ' + hashlib.sha256(image).hexdigest() + ' |\n'
            for manifest in (row, revision, revision + revision + row,
                             revision + row + row, revision + row.replace(' | ', ' | nope', 1),
                             '- Revision: `short`\n' + row):
                (screens / 'MANIFEST.md').write_text(manifest)
                with self.subTest(manifest=manifest), self.assertRaises(ValueError):
                    renderer.validate_screenshot_manifest(screens)

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
