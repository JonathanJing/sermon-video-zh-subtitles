import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_playback_simulation.py"
SPEC = importlib.util.spec_from_file_location("build_playback_simulation", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class BuildPlaybackSimulationTest(unittest.TestCase):
    def test_builds_js_playback_data_from_english_vtt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vtt = root / "live.en.vtt"
            vtt.write_text(
                """WEBVTT

00:23:25.000 --> 00:23:28.000
Today we are in Numbers 16.

00:23:29.000 --> 00:23:32.500
Moses and Aaron stood before the people.
""",
                encoding="utf-8",
            )
            report = {
                "live": {"id": "live1", "title": "Sunday Service", "url": "https://youtube.test/live1"},
                "sermon_candidate": {"id": "vod1", "title": "Sermon"},
                "sermon_start": {"timecode": "0:23:25", "seconds": 1405},
                "outputs": [
                    {
                        "lang": "en",
                        "local_vtt": str(vtt),
                        "live_aligned_vtt": str(vtt),
                    }
                ],
            }
            simulation = mod.build_simulation(
                report=report,
                output=report["outputs"][0],
                cues=mod.subtitle_mod.parse_vtt(vtt.read_text(encoding="utf-8")),
                source_vtt=vtt,
                playback_speed=18,
            )

            self.assertEqual(simulation["translationStatus"], "needs_translation")
            self.assertEqual(len(simulation["segments"]), 2)
            self.assertEqual(simulation["segments"][0]["ref"], "Numbers 16")
            self.assertTrue(simulation["segments"][0]["zh"].startswith("AI 中文待生成"))

            rendered = mod.render_js(simulation)
            self.assertTrue(rendered.startswith("window.SERMON_PLAYBACK_SIMULATION = "))
            payload = rendered.split(" = ", 1)[1].rstrip(";\n")
            self.assertEqual(json.loads(payload)["live"]["id"], "live1")

    def test_merges_progressive_youtube_cues_into_readable_segments(self):
        cues = [
            mod.subtitle_mod.Cue(0, 10, "Welcome to Mariners Church. I'm so glad"),
            mod.subtitle_mod.Cue(
                10,
                1200,
                "Welcome to Mariners Church. I'm so glad\nthat you are with us today. I want to",
            ),
            mod.subtitle_mod.Cue(1200, 1210, "that you are with us today. I want to"),
            mod.subtitle_mod.Cue(
                1210,
                2600,
                "that you are with us today. I want to\nwelcome those watching online.",
            ),
        ]

        merged = mod.merge_progressive_cues(cues, max_segment_ms=6000, max_segment_chars=220)

        self.assertEqual(len(merged), 1)
        self.assertEqual(
            merged[0].text,
            "Welcome to Mariners Church. I'm so glad that you are with us today. I want to welcome those watching online.",
        )


if __name__ == "__main__":
    unittest.main()
