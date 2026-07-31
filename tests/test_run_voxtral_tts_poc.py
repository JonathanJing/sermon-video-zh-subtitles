import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_voxtral_tts_poc.py"
SPEC = importlib.util.spec_from_file_location("run_voxtral_tts_poc", SCRIPT)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


class VoxtralTtsPocTest(unittest.TestCase):
    def test_parse_and_format_timecode_round_trip(self):
        value = "01:02:03,456"
        self.assertEqual(MOD.format_timecode(MOD.parse_timecode(value)), value)

    def test_parse_srt_and_select_overlap(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "fixture.srt"
            fixture.write_text(
                "1\n00:00:00,000 --> 00:00:02,000\n第一句。\n\n"
                "2\n00:00:02,000 --> 00:00:05,000\n第二句。\n",
                encoding="utf-8",
            )
            cues = MOD.parse_srt(fixture)
            selected = MOD.select_cues(cues, 1500, 2500)
            self.assertEqual([cue.index for cue in selected], [1, 2])

    def test_split_text_respects_limit(self):
        text = "第一句很短。第二句也很短。第三句还是很短。"
        chunks = MOD.split_text(text, 12)
        self.assertEqual("".join(chunks), text)
        self.assertTrue(all(len(chunk) <= 12 for chunk in chunks))

    def test_openrouter_preset_does_not_require_consent_flag(self):
        args = MOD.build_parser().parse_args(
            [
                "--srt",
                "input.srt",
                "--source-audio",
                "input.mp3",
                "--outdir",
                "out",
                "--provider",
                "openrouter",
                "--voice-id",
                "en_paul_neutral",
                "--voice-is-preset",
            ]
        )
        self.assertTrue(args.voice_is_preset)
        self.assertFalse(args.confirm_explicit_voice_consent)

    def test_request_fingerprint_changes_with_text_or_voice(self):
        first = MOD.request_fingerprint("openrouter", "voice-a", "第一句", None)
        second = MOD.request_fingerprint("openrouter", "voice-a", "第二句", None)
        third = MOD.request_fingerprint("openrouter", "voice-b", "第一句", None)
        self.assertNotEqual(first, second)
        self.assertNotEqual(first, third)


if __name__ == "__main__":
    unittest.main()
