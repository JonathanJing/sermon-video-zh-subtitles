import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_sermon_split_manifest.py"
SPEC = importlib.util.spec_from_file_location("build_sermon_split_manifest", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class BuildSermonSplitManifestTest(unittest.TestCase):
    def test_speaker_parser_handles_dash_colon_and_unknown(self):
        self.assertEqual(
            mod.parse_speaker("A Title - Eric Geiger | Mariners Church"), "Eric Geiger"
        )
        self.assertEqual(
            mod.parse_speaker("A Vision : Jared Kirkwood | Mariners Church"),
            "Jared Kirkwood",
        )
        self.assertEqual(mod.parse_speaker("A Title Without Speaker"), "unknown")

    def test_stratified_selection_is_deterministic_and_covers_groups(self):
        items = [
            {"videoId": "a1", "speaker": "A"},
            {"videoId": "a2", "speaker": "A"},
            {"videoId": "b1", "speaker": "B"},
            {"videoId": "b2", "speaker": "B"},
        ]
        first = mod.select_stratified(items, 2, "seed")
        second = mod.select_stratified(items, 2, "seed")
        self.assertEqual(first, second)
        selected_speakers = {
            item["speaker"] for item in items if item["videoId"] in first
        }
        self.assertEqual(selected_speakers, {"A", "B"})

    def test_stratified_selection_rejects_impossible_target(self):
        with self.assertRaises(ValueError):
            mod.select_stratified([], 1, "seed")

    def test_metadata_override_loader_rejects_unverified_file(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "overrides.json"
            path.write_text('{"status":"draft","items":[]}', encoding="utf-8")
            with self.assertRaises(RuntimeError):
                mod.load_metadata_overrides(path)


if __name__ == "__main__":
    unittest.main()
