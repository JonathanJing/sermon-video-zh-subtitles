import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "export_sermon_human_confirmation_pack.py"
)
SPEC = importlib.util.spec_from_file_location(
    "export_sermon_human_confirmation_pack", SCRIPT_PATH
)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class ExportSermonHumanConfirmationPackTest(unittest.TestCase):
    def test_timestamp(self):
        self.assertEqual(mod.timestamp(3_723_999), "01:02:03")

    def test_preformatted_escapes_html(self):
        rendered = mod.preformatted("before </pre> & after")
        self.assertNotIn("before </pre>", rendered)
        self.assertIn("&lt;/pre&gt;", rendered)
        self.assertIn("&amp;", rendered)

    def test_receipts_detect_hash_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "a.txt"
            path.write_text("first", encoding="utf-8")
            receipts = mod.receipts_for(root)
            self.assertEqual(mod.verify_receipts(root, receipts), [])
            path.write_text("second", encoding="utf-8")
            self.assertEqual(mod.verify_receipts(root, receipts), ["hash:a.txt"])


if __name__ == "__main__":
    unittest.main()
