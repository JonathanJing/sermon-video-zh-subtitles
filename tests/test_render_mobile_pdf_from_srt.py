import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "render_mobile_pdf_from_srt.py"
SPEC = importlib.util.spec_from_file_location("render_mobile_pdf_from_srt", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class RenderMobilePdfFromSrtTest(unittest.TestCase):
    def test_parses_and_cleans_srt_cues(self):
        cues = mod.parse_srt(
            """1
00:00:01,000 --> 00:00:02,500
<i>神爱世人。</i>

2
00:00:03.000 --> 00:00:05.000
甚至将他的独生子赐给他们。
"""
        )

        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0].start, "00:00:01,000")
        self.assertEqual(cues[0].text, "神爱世人。")
        self.assertEqual(cues[1].end, "00:00:05.000")

    def test_renders_mobile_pdf(self):
        cues = [
            mod.Cue(start="00:00:01,000", end="00:00:02,500", text="神爱世人。"),
            mod.Cue(start="00:00:03,000", end="00:00:05,000", text="甚至将他的独生子赐给他们。"),
        ]
        secondary = [
            mod.Cue(start="00:00:01,000", end="00:00:02,500", text="For God so loved the world."),
            mod.Cue(start="00:00:03,000", end="00:00:05,000", text="That he gave his only Son."),
        ]
        with tempfile.TemporaryDirectory() as tempdir:
            out = Path(tempdir) / "sermon_zh_mobile.pdf"
            mod.render_mobile_pdf(cues, secondary_cues=secondary, out=out, title="Test Sermon", subtitle="2026-06-28")
            data = out.read_bytes()

        self.assertTrue(data.startswith(b"%PDF"))
        self.assertGreater(len(data), 1000)

    def test_aligns_secondary_cues_by_time_overlap(self):
        primary = [
            mod.Cue(start="00:00:01,000", end="00:00:04,000", text="合并后的中文。"),
            mod.Cue(start="00:00:04,000", end="00:00:05,000", text="下一句。"),
        ]
        secondary = [
            mod.Cue(start="00:00:01,000", end="00:00:02,000", text="First English line."),
            mod.Cue(start="00:00:02,000", end="00:00:04,000", text="Second English line."),
            mod.Cue(start="00:00:04,000", end="00:00:05,000", text="Next sentence."),
        ]

        aligned = mod.align_secondary_cues(primary, secondary)

        self.assertEqual(aligned[0], "First English line. Second English line.")
        self.assertEqual(aligned[1], "Next sentence.")

    def test_default_footer_includes_disclaimer(self):
        wrapped = mod.wrap_text(
            mod.DEFAULT_DISCLAIMER,
            mod.register_cjk_font(None),
            mod.FOOTER_FONT_SIZE,
            mod.MOBILE_PAGE_SIZE[0] - 44,
        )

        self.assertGreaterEqual(len(wrapped), 1)
        self.assertLessEqual(len(wrapped[:2]), 2)
        self.assertIn("AI 辅助生成", mod.DEFAULT_DISCLAIMER)
        self.assertIn("原始英文讲道", mod.DEFAULT_DISCLAIMER)


if __name__ == "__main__":
    unittest.main()
