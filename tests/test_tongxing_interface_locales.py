import json
import re
import unittest
from pathlib import Path


CATALOG = Path(__file__).resolve().parents[1] / "apps/tongxing-ios/App/Resources/Localizable.xcstrings"
PLACEHOLDER = re.compile(r"\{[A-Za-z][A-Za-z0-9_]*\}")


class TongxingInterfaceLocalesTests(unittest.TestCase):
    def test_supported_interface_locales_are_complete_and_keep_placeholders(self):
        document = json.loads(CATALOG.read_text(encoding="utf-8"))
        self.assertEqual(document["sourceLanguage"], "zh-Hans")
        self.assertTrue(document["strings"])
        for source, entry in document["strings"].items():
            expected = set(PLACEHOLDER.findall(source))
            for locale in ("en", "ko", "es", "vi"):
                with self.subTest(source=source, locale=locale):
                    value = entry["localizations"][locale]["stringUnit"]["value"]
                    self.assertTrue(value.strip())
                    self.assertEqual(set(PLACEHOLDER.findall(value)), expected)


if __name__ == "__main__":
    unittest.main()
