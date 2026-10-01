"""Guard selection, actual execution evidence and concurrent resource ownership."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import preview


class PreviewCommandTests(unittest.TestCase):
    def test_registered_aliases_are_canonical_and_deduplicated(self):
        self.assertEqual(preview.selected_files("App/ContentView.swift,PlaybackDock.swift ContentView.swift"),
                         ["ContentView.swift", "PlaybackDock.swift"])

    def test_unknown_and_missing_files_fail_before_xcode(self):
        for selection in ("", "AnyView.swift", "../ContentView.swift"):
            with self.assertRaises(ValueError):
                preview.selected_files(selection)
        with tempfile.TemporaryDirectory() as directory, patch.object(preview, "APP_ROOT", Path(directory)):
            with self.assertRaises(ValueError):
                preview.selected_files("ContentView.swift")

    def test_skipped_zero_or_failed_test_is_not_success(self):
        passed = dict(result="Passed", totalTestCount=1, passedTests=1, failedTests=0,
                      skippedTests=0, expectedFailures=0)
        preview.validate_summary(passed)
        for change in (dict(result="Skipped", passedTests=0, skippedTests=1),
                       dict(totalTestCount=0, passedTests=0), dict(failedTests=1), dict(expectedFailures=1)):
            with self.assertRaises(ValueError):
                preview.validate_summary(dict(passed, **change))

    def test_xcresulttool_attachment_suffix_is_normalized_strictly(self):
        expected = {"preview-ContentView-light.png"}
        actual = "preview-ContentView-light_0_AB54E6DB-BDE6-4AEB-8A17-F7DAD3E75944.png"
        self.assertEqual(preview.canonical_attachment_name(actual, expected), "preview-ContentView-light.png")
        self.assertEqual(preview.canonical_attachment_name("preview-ContentView-light.png", expected),
                         "preview-ContentView-light.png")
        for malformed in ("preview-ContentView-light_0_not-a-uuid.png", actual + ".png",
                          actual.replace("_0_", "_index_"), actual.replace("ContentView", "Unknown")):
            self.assertIsNone(preview.canonical_attachment_name(malformed, expected))

    def test_export_requires_complete_unique_named_pngs(self):
        class AttachmentRunner:
            def __init__(self, attachments):
                self.attachments = attachments

            def run(self, command):
                directory = Path(command[-1])
                directory.mkdir()
                (directory / "manifest.json").write_text(json.dumps([
                    dict(testIdentifier="SwiftUIPreviewTests/testRenderRequestedViews()", attachments=self.attachments)]))
                (directory / "exported.png").write_bytes(b"\x89PNG\r\n\x1a\nfixture")

        attachment = dict(suggestedHumanReadableName="preview-ContentView-light.png",
                          exportedFileName="exported.png", isAssociatedWithFailure=False)
        suffixed = dict(attachment, suggestedHumanReadableName=
                        "preview-ContentView-light_0_AB54E6DB-BDE6-4AEB-8A17-F7DAD3E75944.png")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            success = root / "success"
            success.mkdir()
            images = preview.export_images(AttachmentRunner([suffixed]), "unused.xcresult", success,
                                           ["ContentView.swift"], ["light"])
            self.assertEqual(len(images), 1)
            self.assertTrue(Path(images[0]["path"]).is_file())
            for label, entries, variants in (("missing", [attachment], ["light", "dark"]),
                                            ("duplicate", [attachment, suffixed], ["light"])):
                directory = root / label
                directory.mkdir()
                with self.assertRaises(ValueError):
                    preview.export_images(AttachmentRunner(entries), "unused.xcresult", directory,
                                          ["ContentView.swift"], variants)

    def test_shared_lock_rejects_parallel_owner_and_releases(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(preview.tempfile, "gettempdir", return_value=temporary):
            with preview.process_lock("simulator-test", {"repository": "one"}):
                with self.assertRaisesRegex(ValueError, "另一进程"):
                    with preview.process_lock("simulator-test", {"repository": "two"}):
                        self.fail("Concurrent simulator owner accepted")
            with preview.process_lock("simulator-test", {"repository": "two"}):
                pass


if __name__ == "__main__":
    unittest.main()
