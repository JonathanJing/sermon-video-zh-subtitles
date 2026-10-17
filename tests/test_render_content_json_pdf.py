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
    "status": "machine_checked",
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

    def test_renders_pdf_from_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "page.pdf"
            qa = mod.render_content_pdf(json.loads(json.dumps(CONTENT)), out=out)
            self.assertTrue(out.read_bytes().startswith(b"%PDF"))
            self.assertEqual(qa["contentStatus"], "machine_checked")


if __name__ == "__main__":
    unittest.main()
