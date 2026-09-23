import importlib.util
from pathlib import Path
import json
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "screen_multilingual_voice_demos", ROOT / "scripts/screen_multilingual_voice_demos.py"
)
subject = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(subject)


class MultilingualVoiceDemoScreenTest(unittest.TestCase):
    def test_selected_locale_probe_does_not_require_vietnamese_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "manifest.json").write_text(json.dumps({
                "schemaVersion": "sermon-multilingual-voice-demo-manifest-v1",
                "tracks": [{"speakerId": "eric_geiger", "targetLocale": "ko"}],
            }), encoding="utf-8")
            self.assertEqual(subject.collect_generation_tracks(root),
                             [{"speakerId": "eric_geiger", "targetLocale": "ko"}])

    def test_chinese_compares_characters_without_punctuation(self):
        self.assertEqual(subject.normalize("神与我们相遇。", "zh-Hans"), list("神与我们相遇"))

    def test_multilingual_word_normalization_preserves_diacritics(self):
        self.assertEqual(subject.normalize("Chúa Giê-su!", "vi"), ["chúa", "giê", "su"])
        self.assertEqual(subject.normalize("Jesús, nos guía.", "es"), ["jesús", "nos", "guía"])
        self.assertEqual(subject.normalize("하나님은 우리를", "ko"), ["하나님은", "우리를"])


if __name__ == "__main__":
    unittest.main()
