import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "render_content_json_pdf.py"
SPEC = importlib.util.spec_from_file_location("render_content_json_pdf", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


CONTENT = {
    "schemaVersion": "sermon-full-video-text-content-v3",
    "pageId": "page-1",
    "targetLocale": "zh-Hans",
    "sourceLocale": "en",
    "status": "machine_checked",
    "durationSeconds": 3726,
    "audioDurationSeconds": 3700,
    "reviewMode": "formal",
    "series": "启示录",
    "title": "耶稣配得",
    "date": "2026年10月11日",
    "cues": [
        {"start": 0, "end": 4.5, "text": "神爱世人。", "source": "God so loved the world."},
        {"start": 4.5, "end": 3725.25, "text": "甚至将他的独生子赐给他们。", "source": "He gave his only Son."},
        {"start": 9, "end": 10, "text": "  "},
    ],
    "disclosure": {"locale": "zh-Hans", "text": "本页文稿经机器质检，未经人工审核。", "english": "Machine-checked."},
}


class RenderContentJsonPdfTest(unittest.TestCase):
    def test_srt_time_formats_hours(self):
        self.assertEqual(mod.srt_time(3725.25), "01:02:05,250")
        self.assertEqual(mod.srt_time(-1), "00:00:00,000")

    def test_content_cues_skip_empty_text_and_pair_source(self):
        primary, secondary = mod.content_cues(CONTENT)
        self.assertEqual([cue.text for cue in primary], ["神爱世人。", "甚至将他的独生子赐给他们。"])
        self.assertEqual(secondary[1].text, "He gave his only Son.")
        self.assertEqual(primary[1].end, "01:02:05,250")

    def test_machine_checked_disclosure_stays_in_footer(self):
        self.assertTrue(mod.footer_disclaimer(CONTENT).startswith("本页文稿经机器质检"))
        self.assertEqual(mod.footer_disclaimer({}), mod.renderer.COMPACT_DISCLAIMER)
        with self.assertRaises(SystemExit):
            mod.footer_disclaimer({"status": "machine_checked"})

    def test_english_reference_fills_missing_source_by_group(self):
        content = {"pageId": "page-1", "targetLocale": "zh-Hans",
                   "cues": [{"start": 0, "end": 2, "text": "神爱世人。", "textGroupId": "g1"}]}
        reference = {"schemaVersion": "sermon-published-english-reference-v1", "reviewState": "human_approved",
                     "pageId": "page-1", "targets": {"zh-Hans": {
            "contentSha256": "abc", "blocks": [{"textGroupId": "g1", "english": "God so loved the world."}]}}}
        english = mod.reference_english(reference, content, "abc")
        _, secondary = mod.content_cues(content, english)
        self.assertEqual(secondary[0].text, "God so loved the world.")
        with self.assertRaises(SystemExit):
            mod.reference_english(reference, content, "other")
        with self.assertRaises(SystemExit):
            mod.reference_english(dict(reference, reviewState="draft"), content, "abc")

    def test_partial_english_is_rejected(self):
        content = {"cues": [{"start": 0, "end": 1, "text": "一。", "source": "One."},
                            {"start": 1, "end": 2, "text": "二。"}]}
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(SystemExit):
            mod.render_content_pdf(content, out=Path(tmp) / "p.pdf")

    def test_missing_english_is_rejected_unless_target_only(self):
        content = {"pageId": "page-1", "cues": [{"start": 0, "end": 2, "text": "神爱世人。"}]}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "page.pdf"
            with self.assertRaises(SystemExit):
                mod.render_content_pdf(content, out=out)
            mod.render_content_pdf(content, out=out, include_english=False)
            self.assertTrue(out.read_bytes().startswith(b"%PDF"))

    def test_check_content_rejects_legacy_foreign_and_unsafe_pages(self):
        mod.check_content(CONTENT, "page-1")
        for bad in ({"schemaVersion": "sermon-demo-content-v1"}, {"targetLocale": "ko"}, {"pageId": "../x"},
                    {"status": "draft"}, {"schemaVersion": "sermon-full-video-text-content-v2"}):
            with self.assertRaises(SystemExit):
                mod.check_content(dict(CONTENT, **bad))
        with self.assertRaises(SystemExit):
            mod.check_content(CONTENT, "other-page")

    def test_overlapping_cues_keep_their_own_english(self):
        primary = [mod.renderer.Cue("00:00:00,000", "00:00:02,000", "一。"),
                   mod.renderer.Cue("00:00:01,500", "00:00:03,000", "二。")]
        blocks = mod.renderer.build_reading_blocks(primary, paired_secondary=["One.", "Two."])
        self.assertEqual(" ".join(block.secondary for block in blocks), "One. Two.")

    def test_renders_pdf_from_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "page.pdf"
            qa = mod.render_content_pdf(json.loads(json.dumps(CONTENT)), out=out)
            self.assertTrue(out.read_bytes().startswith(b"%PDF"))
            self.assertEqual(qa["contentStatus"], "machine_checked")
            self.assertTrue(qa["font"])


if __name__ == "__main__":
    unittest.main()
