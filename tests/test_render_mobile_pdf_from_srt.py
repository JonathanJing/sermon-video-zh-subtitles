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

    def test_normalizes_spacing_around_chinese_punctuation(self):
        cleaned = mod.clean_caption_text("神 爱世人 。 这是 English text. 《 约翰福音 》 很清楚 。")

        self.assertEqual(cleaned, "神爱世人。这是 English text. 《约翰福音》很清楚。")

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
            mod.render_mobile_pdf(
                cues,
                secondary_cues=secondary,
                out=out,
                title="Test Sermon",
                subtitle="2026-06-28",
                source_url="https://www.youtube.com/watch?v=test123",
                source_offset_seconds=90,
            )
            data = out.read_bytes()

        self.assertTrue(data.startswith(b"%PDF"))
        self.assertGreater(len(data), 1000)
        self.assertIn(b"t=91s", data)

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

    def test_builds_reading_blocks_from_short_adjacent_cues(self):
        primary = [
            mod.Cue(start="00:00:01,000", end="00:00:02,000", text="第一句，"),
            mod.Cue(start="00:00:02,000", end="00:00:04,000", text="继续同一个意思。"),
            mod.Cue(start="00:00:04,100", end="00:00:06,000", text="这是新的完整句。"),
        ]
        secondary = [
            mod.Cue(start="00:00:01,000", end="00:00:02,000", text="First part,"),
            mod.Cue(start="00:00:02,000", end="00:00:04,000", text="same thought."),
            mod.Cue(start="00:00:04,100", end="00:00:06,000", text="A new sentence."),
        ]

        blocks = mod.build_reading_blocks(primary, secondary, max_primary_chars=15)

        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0].start, "00:00:01,000")
        self.assertEqual(blocks[0].end, "00:00:04,000")
        self.assertEqual(blocks[0].primary, "第一句，继续同一个意思。")
        self.assertEqual(blocks[0].secondary, "First part, same thought.")
        self.assertEqual(blocks[1].primary, "这是新的完整句。")

    def test_reading_blocks_prefer_complete_sentences_before_breaking(self):
        primary = [
            mod.Cue(start="00:00:01,000", end="00:00:02,000", text="这是一个"),
            mod.Cue(start="00:00:02,000", end="00:00:03,000", text="还没完成的"),
            mod.Cue(start="00:00:03,000", end="00:00:05,000", text="完整句。"),
            mod.Cue(start="00:00:05,100", end="00:00:07,000", text="下一段开始。"),
        ]
        secondary = [
            mod.Cue(start="00:00:01,000", end="00:00:02,000", text="This is"),
            mod.Cue(start="00:00:02,000", end="00:00:03,000", text="an unfinished"),
            mod.Cue(start="00:00:03,000", end="00:00:05,000", text="complete sentence."),
            mod.Cue(start="00:00:05,100", end="00:00:07,000", text="The next paragraph begins."),
        ]

        blocks = mod.build_reading_blocks(primary, secondary, preferred_primary_chars=1)

        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0].primary, "这是一个还没完成的完整句。")
        self.assertEqual(blocks[0].secondary, "This is an unfinished complete sentence.")
        self.assertEqual(blocks[1].primary, "下一段开始。")

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

    def test_wrap_text_prevents_chinese_punctuation_at_line_start(self):
        font_name = mod.register_cjk_font(None)

        lines = mod.wrap_text("这是一句需要换行的中文？然后继续下一句。", font_name, 15.5, 78)

        self.assertGreater(len(lines), 1)
        self.assertTrue(all(line[0] not in mod.KINSOKU_NO_LINE_START for line in lines if line))

    def test_balanced_pagination_avoids_a_sparse_last_page(self):
        blocks = [
            mod.RenderBlock(str(index), str(index), (), (), height, 0)
            for index, height in enumerate([140, 100, 100, 100, 100])
        ]

        pages = mod.balance_render_pages(blocks, first_capacity=250, regular_capacity=250)

        self.assertEqual([len(page) for page in pages], [1, 2, 2])

    def test_oversized_block_is_split_without_overflow(self):
        line_height = mod.BODY_FONT_SIZE + mod.LINE_GAP
        block = mod.RenderBlock(
            "00:00:00,000",
            "00:00:45,000",
            tuple(f"第{index}行" for index in range(30)),
            (),
            30 * line_height + mod.CUE_GAP + mod.TIME_LABEL_HEIGHT + mod.TIME_LABEL_BOTTOM_GAP,
            mod.CUE_GAP,
        )

        chunks = mod.split_render_block(block, max_height=250, include_timecodes=True)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(chunk.height <= 250.01 for chunk in chunks))
        self.assertFalse(chunks[0].continued)
        self.assertTrue(all(chunk.continued for chunk in chunks[1:]))

    def test_video_url_at_time_preserves_existing_query(self):
        url = mod.video_url_at_time("https://www.youtube.com/watch?v=abc123&feature=share", 305.9)

        self.assertIn("v=abc123", url)
        self.assertIn("feature=share", url)
        self.assertIn("t=305s", url)


if __name__ == "__main__":
    unittest.main()
