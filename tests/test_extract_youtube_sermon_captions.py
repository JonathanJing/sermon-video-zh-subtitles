import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "extract_youtube_sermon_captions.py"
SPEC = importlib.util.spec_from_file_location("extract_youtube_sermon_captions", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class ExtractYoutubeSermonCaptionsTest(unittest.TestCase):
    def test_progressive_youtube_vtt_becomes_incremental_text(self):
        cues = mod.parse_vtt(
            """WEBVTT
Kind: captions
Language: en

00:00:01.000 --> 00:00:03.000 align:start
That<00:00:01.200><c> video</c><00:00:01.500><c> is</c><00:00:01.800><c> exciting</c>

00:00:03.000 --> 00:00:03.010 align:start
That video is exciting

00:00:03.010 --> 00:00:05.000 align:start
That video is exciting
for<00:00:03.500><c> everyone.</c>

00:00:05.000 --> 00:00:05.010 align:start
for everyone.
"""
        )

        increments = mod.extract_incremental_cues(cues)

        self.assertEqual(len(cues), 4)
        self.assertEqual([cue.text for cue in increments], ["That video is exciting", "for everyone."])
        self.assertEqual(" ".join(cue.text for cue in increments), "That video is exciting for everyone.")

    def test_eligible_candidates_require_original_english_automatic_track(self):
        rows = [
            {
                "id": "new",
                "upload_date": "20260830",
                "webpage_url": "https://www.youtube.com/watch?v=new",
                "englishCaptionStatus": "automatic_english",
                "automaticEnglishCaptionTracks": ["en", "en-orig"],
            },
            {
                "id": "translated-only",
                "upload_date": "20260829",
                "webpage_url": "https://www.youtube.com/watch?v=translated-only",
                "englishCaptionStatus": "automatic_english",
                "automaticEnglishCaptionTracks": ["en"],
            },
            {
                "id": "none",
                "upload_date": "20260828",
                "webpage_url": "https://www.youtube.com/watch?v=none",
                "englishCaptionStatus": "none",
                "automaticEnglishCaptionTracks": [],
            },
        ]

        selected = mod.eligible_candidates(rows)

        self.assertEqual([row["id"] for row in selected], ["new"])

    def test_completed_manifest_requires_matching_file_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            asset_dir = Path(tmp) / "asset"
            text_path = asset_dir / "normalized" / "transcript.youtube-auto.txt"
            text_path.parent.mkdir(parents=True)
            text_path.write_text("a reviewed-later raw transcript\n", encoding="utf-8")
            manifest = {
                "schemaVersion": mod.SCHEMA_VERSION,
                "status": "ok",
                "files": [
                    {
                        "path": str(text_path.relative_to(asset_dir)),
                        "sha256": mod.sha256_file(text_path),
                    }
                ],
            }
            (asset_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

            self.assertTrue(mod.verify_completed_asset(asset_dir))
            text_path.write_text("changed\n", encoding="utf-8")
            self.assertFalse(mod.verify_completed_asset(asset_dir))

    def test_quality_checks_reject_short_or_incomplete_caption(self):
        raw = [mod.Cue(0, 10_000, "hello")]
        checks = mod.quality_checks(raw, raw, "hello", duration_seconds=100)
        failed = {item["name"] for item in checks if item["state"] == "fail"}

        self.assertIn("transcript_minimum_length", failed)
        self.assertIn("timeline_coverage", failed)


if __name__ == "__main__":
    unittest.main()
