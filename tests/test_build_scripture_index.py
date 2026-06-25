import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_scripture_index.py"
SPEC = importlib.util.spec_from_file_location("build_scripture_index", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class BuildScriptureIndexTest(unittest.TestCase):
    def test_builds_referenced_chapter_and_verse_payload(self):
        verses = mod.parse_vpl_text(
            [
                "NUM 16:1 可拉起来。",
                "NUM 16:2 二百五十个首领起来。",
                "NUM 16:48 他站在活人死人中间，瘟疫就止住了。",
                "NUM 16:49 遭瘟疫死的，共有一万四千七百人。",
                "NUM 16:50 亚伦回到会幕门口。",
                "ROM 8:1 如今，那些在基督耶稣里的就不定罪了。",
            ]
        )
        refs = [
            mod.parse_reference("Numbers 16"),
            mod.parse_reference("Numbers 16:48"),
            mod.parse_reference("Romans 8"),
        ]

        payload = mod.build_payload(verses, refs, mod.DEFAULT_SOURCE_URL)

        self.assertEqual(payload["translation"]["id"], "cmn-cu89s")
        self.assertEqual(payload["translation"]["license"], "Public Domain")
        self.assertEqual(payload["references"]["Numbers 16"]["title"], "民数记 16")
        self.assertEqual(len(payload["references"]["Numbers 16"]["verses"]), 5)
        self.assertEqual(payload["references"]["Numbers 16:48"]["verses"][0]["verse"], "16:48")
        self.assertEqual(payload["references"]["Romans 8"]["title"], "罗马书 8")
        self.assertIn("eBible.org cmn-cu89s", payload["references"]["Numbers 16"]["source"])

        full_payload = mod.build_full_bible_payload(verses, mod.DEFAULT_SOURCE_URL)
        self.assertEqual(full_payload["translation"]["id"], "cmn-cu89s")
        self.assertEqual(full_payload["verseCount"], 6)
        self.assertEqual(full_payload["books"][0]["code"], "NUM")
        self.assertEqual(full_payload["chapters"]["NUM"]["16"][2]["verse"], 48)


if __name__ == "__main__":
    unittest.main()
