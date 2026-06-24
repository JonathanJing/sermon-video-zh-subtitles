import unittest

from backend.scripture import DEFAULT_BIBLE_PATH, ScriptureNotFoundError, ScriptureService


class ScriptureServiceTest(unittest.TestCase):
    def test_full_bible_index_contains_all_books_and_numbers_16(self):
        service = ScriptureService(DEFAULT_BIBLE_PATH)

        metadata = service.metadata()
        chapter = service.chapter("Numbers", 16)
        chinese_chapter = service.chapter("民数记", "16")

        self.assertEqual(metadata["translation"]["id"], "cmn-cu89s")
        self.assertEqual(metadata["translation"]["license"], "Public Domain")
        self.assertEqual(metadata["bookCount"], 66)
        self.assertGreater(metadata["verseCount"], 30000)
        self.assertEqual(chapter["reference"]["title"], "民数记 16")
        self.assertEqual(len(chapter["verses"]), 50)
        self.assertEqual(chapter["verses"][47]["verse"], "16:48")
        self.assertIn("他站在活人死人中间", chapter["verses"][47]["text"])
        self.assertEqual(chinese_chapter["reference"]["bookCode"], "NUM")

    def test_unknown_scripture_reference_raises_not_found(self):
        service = ScriptureService(DEFAULT_BIBLE_PATH)

        with self.assertRaises(ScriptureNotFoundError):
            service.chapter("Numbers", 99)


if __name__ == "__main__":
    unittest.main()
