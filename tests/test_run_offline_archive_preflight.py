import unittest
from argparse import Namespace
from unittest.mock import patch
import sys

import scripts.run_offline_archive_preflight as mod


class OfflineArchivePreflightTest(unittest.TestCase):
    def test_live_archive_caption_route_passes(self):
        live = meta(subtitles={"en": [{}]}, automatic_captions={})
        with patched_offline(live_meta=live):
            report = mod.run_preflight(args_for())

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["offlineRoute"]["decision"], "use_caption_track")
        self.assertEqual(report["captionSource"]["kind"], "live_archive")
        self.assertEqual(report["warnings"], [])
        self.assertFalse(report["apiKeyMaterialIncluded"])

    def test_no_caption_archive_plans_asr_fallback_without_calling_openai(self):
        live = meta(subtitles={}, automatic_captions={})
        with patched_offline(live_meta=live):
            report = mod.run_preflight(args_for(no_discover=True))

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["offlineRoute"]["decision"], "use_asr_fallback")
        self.assertIn("asr_fallback_planned", report["warnings"])
        self.assertEqual(report["asr"]["model"], "gpt-4o-transcribe")
        self.assertFalse(report["offlineRoute"]["audioExtractionAttempted"])

    def test_explicit_sermon_vod_caption_route_passes(self):
        live = meta(subtitles={}, automatic_captions={})
        sermon = meta(video_id="sermon", subtitles={"en-orig": [{}]}, automatic_captions={})
        with patched_offline(live_meta=live, sermon_meta=sermon):
            report = mod.run_preflight(args_for(sermon_url="https://www.youtube.com/watch?v=sermon"))

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["offlineRoute"]["decision"], "use_caption_track")
        self.assertEqual(report["captionSource"]["kind"], "sermon_vod")

    def test_metadata_failure_marks_report_failed(self):
        with patch.object(mod.offline, "require_yt_dlp", return_value="yt-dlp"):
            with patch.object(mod.offline, "fetch_metadata", side_effect=RuntimeError("metadata failed")):
                report = mod.run_preflight(args_for())

        self.assertEqual(report["status"], "failed")
        self.assertIn("preflight_exception", report["failedChecks"])

    def test_parse_args_rejects_realtime_asr_model(self):
        original_argv = sys.argv
        try:
            sys.argv = [
                "run_offline_archive_preflight.py",
                "--live-url",
                "https://www.youtube.com/watch?v=live",
                "--asr-model",
                "gpt-realtime-translate",
            ]
            with self.assertRaises(SystemExit):
                mod.parse_args()
        finally:
            sys.argv = original_argv


def args_for(no_discover=False, sermon_url=None):
    return Namespace(
        live_url="https://www.youtube.com/watch?v=live",
        sermon_url=sermon_url,
        no_discover=no_discover,
        playlist_end=40,
        lang=["en-orig", "en"],
        sermon_start=None,
        tail_padding_seconds=0,
        yt_dlp="yt-dlp",
        asr_model="gpt-4o-transcribe",
        out=None,
    )


def meta(video_id="live", subtitles=None, automatic_captions=None):
    return {
        "id": video_id,
        "title": "The Cure for Our Rebellion",
        "duration": 3600,
        "webpage_url": f"https://www.youtube.com/watch?v={video_id}",
        "subtitles": subtitles if subtitles is not None else {},
        "automatic_captions": automatic_captions if automatic_captions is not None else {},
    }


class patched_offline:
    def __init__(self, *, live_meta, sermon_meta=None):
        self.live_meta = live_meta
        self.sermon_meta = sermon_meta
        self.patches = []

    def __enter__(self):
        self.patches = [
            patch.object(mod.offline, "require_yt_dlp", return_value="yt-dlp"),
            patch.object(mod.offline, "fetch_metadata", side_effect=self.fetch_metadata),
            patch.object(mod.offline, "discover_matching_sermon_vod", return_value=(self.sermon_meta, {"enabled": True, "selected_by": None, "candidates": []})),
        ]
        for item in self.patches:
            item.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        for item in reversed(self.patches):
            item.stop()
        return False

    def fetch_metadata(self, yt_dlp, url):
        if "sermon" in url and self.sermon_meta is not None:
            return self.sermon_meta
        return self.live_meta


if __name__ == "__main__":
    unittest.main()
