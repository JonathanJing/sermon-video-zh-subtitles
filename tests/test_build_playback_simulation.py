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
                api_key_secret="projects/p/secrets/openai-api-key/versions/latest",
            )

            self.assertEqual(simulation["translationStatus"], "needs_translation")
            self.assertEqual(simulation["sermonTitle"], "Sermon")
            self.assertEqual(simulation["sourceVtt"], "live.en.vtt")
            self.assertFalse(simulation["secrets"]["apiKeyMaterialIncluded"])
            self.assertFalse(simulation["secrets"]["secretResourceNamesIncluded"])
            self.assertTrue(simulation["secrets"]["serverSideSecretConfigured"])
            self.assertEqual(len(simulation["segments"]), 2)
            self.assertEqual(len(simulation["rawSegments"]), 2)
            self.assertEqual(simulation["segments"], simulation["displaySegments"])
            self.assertEqual(simulation["reviewSegments"][0]["displaySegmentId"], simulation["displaySegments"][0]["id"])
            self.assertEqual(simulation["displaySegments"][0]["sourceSegmentIds"], ["sim_0001"])
            self.assertEqual(simulation["displaySegments"][0]["sourceCueRange"], "sim_0001")
            self.assertEqual(simulation["reviewSegments"][0]["sourceCueRange"], "sim_0001")
            self.assertEqual(simulation["displayPolicy"]["source"], "offline-caption-polisher")
            self.assertTrue(simulation["displayPolicy"]["avoidsConnectorBoundaries"])
            self.assertEqual(simulation["segments"][0]["ref"], "Numbers 16")
            self.assertEqual(simulation["segments"][0]["refs"][0]["title"], "民数记 16")
            self.assertEqual(simulation["scriptureReferences"][0]["canonicalRef"], "Numbers 16")
            self.assertTrue(simulation["segments"][0]["zh"].startswith("AI 中文待生成"))

            rendered = mod.render_js(simulation)
            self.assertTrue(rendered.startswith("window.SERMON_PLAYBACK_SIMULATION = "))
            self.assertNotIn("apiKeySecret", rendered)
            self.assertNotIn("openai-api-key", rendered)
            self.assertNotIn("projects/p/secrets", rendered)
            payload = rendered.split(" = ", 1)[1].rstrip(";\n")
            self.assertEqual(json.loads(payload)["live"]["id"], "live1")

    def test_builds_display_segments_that_avoid_half_sentence_breaks(self):
        raw_segments = [
            {
                "id": "sim_0001",
                "startMs": 0,
                "endMs": 2500,
                "zh": "如果我们真的相信神比其他一切都好，",
                "en": "But if we really believe that God is better than everything else,",
                "translationStatus": "ready",
                "confidence": 84,
                "refs": [],
            },
            {
                "id": "sim_0002",
                "startMs": 2510,
                "endMs": 5000,
                "zh": "认清我们挣扎的地方其实很有帮助，因为我们可以",
                "en": "identifying what we struggle with is actually really helpful because we can",
                "translationStatus": "ready",
                "confidence": 84,
                "refs": [],
            },
            {
                "id": "sim_0003",
                "startMs": 5010,
                "endMs": 6500,
                "zh": "把这些放下，更加信靠祂。",
                "en": "leave that behind and trust him more.",
                "translationStatus": "ready",
                "confidence": 84,
                "refs": [],
            },
        ]

        display = mod.build_display_segments(raw_segments)

        self.assertEqual(len(display), 1)
        self.assertEqual(display[0]["sourceSegmentIds"], ["sim_0001", "sim_0002", "sim_0003"])
        self.assertEqual(display[0]["sourceCueRange"], "sim_0001-sim_0003")
        self.assertIn("因为我们可以 把这些放下", display[0]["zh"])
        self.assertTrue(display[0]["en"].endswith("trust him more."))

    def test_refresh_polished_layers_adds_display_policy_to_legacy_segments(self):
        simulation = {
            "segments": [
                {
                    "id": "sim_0001",
                    "startMs": 0,
                    "endMs": 3000,
                    "zh": "神的百姓站在应许之地边缘。",
                    "en": "God's people are at the edge of the promised land.",
                    "translationStatus": "ready",
                }
            ]
        }

        refreshed = mod.refresh_polished_layers(simulation)

        self.assertEqual(refreshed["segments"], refreshed["displaySegments"])
        self.assertEqual(refreshed["rawSegments"][0]["id"], "sim_0001")
        self.assertEqual(refreshed["reviewSegments"][0]["sourceCueRange"], "sim_0001")
        self.assertEqual(refreshed["displayPolicy"]["source"], "offline-caption-polisher")
        self.assertTrue(refreshed["displayPolicy"]["avoidsConnectorBoundaries"])

    def test_keeps_connector_start_with_previous_sentence(self):
        raw_segments = [
            {
                "id": "sim_0001",
                "startMs": 0,
                "endMs": 2800,
                "zh": "这能帮助我们诚实面对自己。",
                "en": "This helps us be honest with ourselves.",
                "translationStatus": "ready",
            },
            {
                "id": "sim_0002",
                "startMs": 2810,
                "endMs": 5200,
                "zh": "因为我们会看见内心真正倚靠的是什么。",
                "en": "Because we see what our hearts are really relying on.",
                "translationStatus": "ready",
            },
        ]

        display = mod.build_display_segments(raw_segments)

        self.assertEqual(len(display), 1)
        self.assertEqual(display[0]["sourceSegmentIds"], ["sim_0001", "sim_0002"])
        self.assertIn("因为我们会看见", display[0]["zh"])

    def test_splits_long_complete_thoughts_at_safe_sentence_boundary(self):
        raw_segments = [
            {
                "id": "sim_0001",
                "startMs": 0,
                "endMs": 3200,
                "zh": "神的百姓站在应许之地边缘，他们需要凭信心向前。",
                "en": "God's people stood at the edge of the promised land, and they needed to move forward by faith.",
                "translationStatus": "ready",
            },
            {
                "id": "sim_0002",
                "startMs": 3210,
                "endMs": 6600,
                "zh": "他们也需要记得，真正供应他们的是神自己。",
                "en": "They also needed to remember that God himself was the one who supplied them.",
                "translationStatus": "ready",
            },
        ]

        display = mod.build_display_segments(raw_segments)

        self.assertEqual(len(display), 2)
        self.assertEqual(display[0]["sourceSegmentIds"], ["sim_0001"])
        self.assertEqual(display[1]["sourceSegmentIds"], ["sim_0002"])

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

    def test_rejects_raw_api_key_material_for_generated_web_file(self):
        with self.assertRaises(SystemExit):
            mod.validate_secret_resource_name("sk-this-looks-like-raw-key-material")

    def test_detects_multiple_scripture_chapters(self):
        refs = mod.detect_references("We will read Numbers 16, Romans chapter 8, and 1 Corinthians 13 today.")

        self.assertEqual(
            [ref["canonicalRef"] for ref in refs],
            ["1 Corinthians 13", "Numbers 16", "Romans 8"],
        )

    def test_detects_chinese_scripture_chapter_numbers(self):
        refs = mod.detect_references("今天也会提到民数记十六章和罗马书八章。")

        self.assertEqual(
            [ref["canonicalRef"] for ref in refs],
            ["Numbers 16", "Romans 8"],
        )


if __name__ == "__main__":
    unittest.main()
