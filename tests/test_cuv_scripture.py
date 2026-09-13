import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path

from scripts import cuv_scripture as cuv


class CuvScriptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.library = cuv.CuvLibrary.from_path()

    def test_all_books_have_chinese_english_and_code_aliases(self):
        self.assertEqual(len(cuv.BOOKS), 66)
        for code, (english, chinese) in cuv.BOOKS.items():
            with self.subTest(book=code):
                for name in (code, english, chinese):
                    self.assertEqual(cuv.normalize_book(name), code)
                    self.assertTrue(self.library.lookup(cuv.Reference(name, 1, 1))["text"])
        for value, expected in (("First Peter", "1PE"), ("II Corinthians", "2CO"), ("約翰一書", "1JO"), ("Song of Solomon", "SOL"), ("JHN", "JOH"), ("MRK", "MAR")):
            self.assertEqual(cuv.normalize_book(value), expected)

    def test_spoken_and_written_references_are_canonical(self):
        cases = {
            "Revelation 1:8": "REV 1:8",
            "REV.1:8": "REV 1:8",
            "启示录第一章第八节": "REV 1:8",
            "《启示录》一章八至十节": "REV 1:8-10",
            "Revelation chapter one, verses eight through ten": "REV 1:8-10",
            "First Peter chapter two verses nine to ten": "1PE 2:9-10",
            "Psalm one hundred nineteen verse one hundred five": "PSA 119:105",
            "诗篇第一百一十九篇第一百零五节": "PSA 119:105",
            "约翰一书 1:9": "1JO 1:9",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(cuv.parse_reference(source).canonical_ref, expected)
        for source, expected in (("verse nine", "REV 1:9"), ("第九节", "REV 1:9"), ("12:9", "REV 12:9"), ("chapter two verse one", "REV 2:1")):
            self.assertEqual(cuv.parse_reference(source, context="REV 1:8").canonical_ref, expected)

    def test_refuses_ambiguous_or_invalid_ranges(self):
        for source in ("verse nine", "启示录1", "Revelation 0:1", "REV 1:9-8", "REV 1:8-2:1", "today we talked about John", "Revelation chapter one two verse eight"):
            with self.subTest(source=source), self.assertRaises(cuv.CuvError):
                cuv.parse_reference(source)
        for source in ("REV 99:1", "REV 1:99", "GEN 24:30", "GEN 24:29-31"):
            with self.subTest(source=source), self.assertRaises(cuv.CuvError):
                self.library.lookup(source)
        with self.assertRaises(cuv.CuvError):
            cuv.Reference("REV", True, 1)

    def test_actual_cuv_words_and_punctuation_preserved(self):
        quote = self.library.lookup("REV 1:8")
        self.assertEqual(quote["text"], "主 神说：「我是阿拉法，我是俄梅戛，是昔在、今在、以后[永]在的全能者。」")
        self.assertEqual(quote["textSha256"], cuv.sha256(quote["text"]))
        self.assertEqual(quote["source"]["archiveSha256"], cuv.SOURCE_ARCHIVE_SHA256)
        self.assertEqual(quote["edition"]["id"], "cmn-cu89s")
        full = self.library.lookup("REV 1:1-20")
        self.assertEqual(len(full["verses"]), 20)
        self.assertEqual(full["text"], "".join(v["text"] for v in full["verses"]))

    def test_partial_quote_must_be_exact_unambiguous_substring(self):
        excerpt = "不要惧怕！我是首先的，我是末后的，"
        result = self.library.lookup("REV 1:17", excerpt=excerpt)
        self.assertEqual(result["text"], excerpt)
        self.assertEqual(result["selection"]["kind"], "exact_excerpt")
        self.assertGreater(result["selection"]["startChar"], 0)
        self.assertEqual(result["fullText"][result["selection"]["startChar"]:result["selection"]["endChar"]], excerpt)
        for bad in ("不要害怕！", "", "我是"):
            with self.subTest(excerpt=bad), self.assertRaises(cuv.CuvError):
                self.library.lookup("REV 1:17", excerpt=bad)
        with self.assertRaises(cuv.CuvError):
            self.library.verify_text("REV 1:17", excerpt)
        self.library.verify_text("REV 1:17", excerpt, excerpt=True)

    def test_modified_library_or_provenance_is_rejected(self):
        data = json.loads(cuv.DEFAULT_LIBRARY_PATH.read_text())
        provenance = self.library.provenance
        changed = copy.deepcopy(data)
        changed["chapters"]["REV"]["1"][7]["text"] = "编造的经文。"
        with self.assertRaises(cuv.CuvError):
            cuv.CuvLibrary(changed, provenance)
        provenance["archiveSha256"] = "0" * 64
        with self.assertRaises(cuv.CuvError):
            cuv.CuvLibrary(data, provenance)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "fake.zip"
            path.write_bytes(b"not the pinned archive")
            with self.assertRaises(cuv.CuvError):
                cuv.verify_archive(path)

    def test_vpl_parser_does_not_silently_drop_bad_or_duplicate_lines(self):
        parsed = cuv.parse_vpl_bytes("GEN 1:1 起初，　神创造天地。\nGEN 1:2 地是空虚混沌。\n".encode())
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0].text, "起初， 神创造天地。")
        for source in ("GEN 1:1 经文\nbad line", "GEN 1:1 经文\nGEN 1:1 重复", "ZZZ 1:1 不存在", "GEN 0:1 不存在"):
            with self.subTest(source=source), self.assertRaises(cuv.CuvError):
                cuv.parse_vpl_bytes(source.encode())

    def test_speech_input_keeps_canonical_text_and_bracket_contents(self):
        text = self.library.lookup("REV 1:10")["text"]
        speech = cuv.prepare_spoken_input(text)
        self.assertEqual(speech["displayText"], text)
        self.assertIn("[圣]灵", text)
        self.assertIn("圣灵", speech["spokenText"])
        self.assertNotIn("[", speech["spokenText"])
        self.assertNotEqual(speech["displayTextSha256"], speech["spokenTextSha256"])
        self.assertEqual(self.library.lookup("REV 1:10")["text"], text)

    def test_cli_has_offline_query_verify_and_nonzero_missing_verse(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(cuv.main(["verify"]), 0)
        self.assertEqual(json.loads(out.getvalue())["status"], "verified")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cuv.main(["query", "REV 1:8", "--spoken-input"]), 0)
        self.assertIn("speechInput", json.loads(out.getvalue()))
        with contextlib.redirect_stderr(err):
            self.assertEqual(cuv.main(["query", "GEN 24:30"]), 2)
        self.assertIn("Missing verse", err.getvalue())


if __name__ == "__main__":
    unittest.main()
