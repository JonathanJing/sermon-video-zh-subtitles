import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_post_live_timeline_job.py"
SPEC = importlib.util.spec_from_file_location("run_post_live_timeline_job", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def make_args(root: Path, state_file: str, **overrides):
    values = {
        "sunday": "2026-07-12",
        "state_file": state_file,
        "work_root": root,
        "out": str(root / "job-report.json"),
        "gcs_bucket": "test-bucket",
        "gcs_prefix": "sundays",
        "api_key_secret": None,
        "discord_bot_token_secret": None,
        "discord_channel_id": None,
        "chunk_seconds": 120.0,
        "transition_chunk_seconds": 30.0,
        "fine_chunk_seconds": 5.0,
        "wide_margin_seconds": 180.0,
        "fine_zone_radius_seconds": 75.0,
        "timeline_model": "gpt-4o-transcribe",
        "classifier_model": "gpt-5.6",
        "reasoning_effort": "high",
        "audio_format": "bestaudio[ext=m4a]/bestaudio",
        "yt_dlp": "yt-dlp",
        "youtube_cookies_secret": None,
        "youtube_api_key_secret": None,
        "allow_non_post_live": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def write_state(path: Path):
    path.write_text(
        json.dumps(
            {
                "lastSunday": "2026-07-12",
                "lastSelectedSource": {"url": "https://www.youtube.com/watch?v=5GuhLMPflds"},
                "lastGenerationRequest": {"liveUrl": "https://www.youtube.com/watch?v=5GuhLMPflds"},
            }
        ),
        encoding="utf-8",
    )


class PostLiveTimelineJobTest(unittest.TestCase):
    def test_metadata_prefers_youtube_data_api_without_calling_ytdlp(self):
        original_secret = mod.access_secret
        original_api = mod.youtube_data_api.video_metadata
        original_ytdlp = mod.youtube_metadata
        try:
            mod.access_secret = lambda _name: "test-key"
            mod.youtube_data_api.video_metadata = lambda video_id, api_key: {
                "id": video_id,
                "live_status": "was_live",
                "was_live": True,
                "metadata_provider": "youtube-data-api-v3",
            }
            mod.youtube_metadata = lambda *_args, **_kwargs: self.fail("yt-dlp fallback should not run")
            metadata, diagnostics = mod.youtube_metadata_with_data_api(
                "https://www.youtube.com/watch?v=5GuhLMPflds",
                api_key_secret="projects/p/secrets/youtube/versions/latest",
                yt_dlp="yt-dlp",
                cookies_path=None,
            )
        finally:
            mod.access_secret = original_secret
            mod.youtube_data_api.video_metadata = original_api
            mod.youtube_metadata = original_ytdlp

        self.assertTrue(metadata["was_live"])
        self.assertEqual(diagnostics["selectedProvider"], "youtube-data-api-v3")
        self.assertFalse(diagnostics["fallbackUsed"])

    def test_metadata_falls_back_to_ytdlp_when_data_api_fails(self):
        original_secret = mod.access_secret
        original_api = mod.youtube_data_api.video_metadata
        original_ytdlp = mod.youtube_metadata
        try:
            mod.access_secret = lambda _name: "test-key"
            mod.youtube_data_api.video_metadata = lambda *_args, **_kwargs: (_ for _ in ()).throw(
                mod.youtube_data_api.YouTubeDataApiError("disabled")
            )
            mod.youtube_metadata = lambda *_args, **_kwargs: {"live_status": "was_live", "was_live": True}
            metadata, diagnostics = mod.youtube_metadata_with_data_api(
                "https://www.youtube.com/watch?v=5GuhLMPflds",
                api_key_secret="projects/p/secrets/youtube/versions/latest",
                yt_dlp="yt-dlp",
                cookies_path=None,
            )
        finally:
            mod.access_secret = original_secret
            mod.youtube_data_api.video_metadata = original_api
            mod.youtube_metadata = original_ytdlp

        self.assertTrue(metadata["was_live"])
        self.assertEqual(diagnostics["selectedProvider"], "yt-dlp")
        self.assertTrue(diagnostics["fallbackUsed"])
        self.assertIn("YouTubeDataApiError", diagnostics["dataApiError"])

    def test_waits_while_stream_is_live(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            state = root / "state.json"
            write_state(state)
            report = mod.run_job(
                make_args(root, str(state)),
                metadata_loader=lambda _: {"live_status": "is_live", "is_live": True},
            )
        self.assertEqual(report["status"], "waiting_for_post_live")

    def test_reports_download_access_separately_after_metadata_is_ready(self):
        def failing_runner(command, check):
            raise subprocess.CalledProcessError(1, command)

        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            state = root / "state.json"
            write_state(state)
            report = mod.run_job(
                make_args(root, str(state)),
                metadata_loader=lambda _: {
                    "live_status": "was_live",
                    "was_live": True,
                    "metadata_provider": "youtube-data-api-v3",
                },
                runner=failing_runner,
                marker_reader=lambda _: None,
                handoff_reader=lambda _: None,
            )

        self.assertEqual(report["status"], "waiting_for_download_access")
        self.assertEqual(report["reason"], "youtube_metadata_ready_but_archive_download_failed")
        self.assertFalse(report["downloadDiagnostics"]["cookiesConfigured"])
        self.assertEqual(report["downloadDiagnostics"]["errorClass"], "CalledProcessError")

    def test_downloads_uploads_probes_and_stops_for_review(self):
        uploads = []

        def runner(command, check):
            template = Path(command[command.index("-o") + 1])
            template.parent.mkdir(parents=True, exist_ok=True)
            (template.parent / "source_audio.m4a").write_bytes(b"audio")
            return subprocess.CompletedProcess(command, 0)

        def fake_timeline(args):
            chunks = args.outdir / "coarse_120s" / "timeline_chunks.json"
            chunks.parent.mkdir(parents=True, exist_ok=True)
            chunks.write_text("[]", encoding="utf-8")
            return {
                "status": "requires_operator_review",
                "analysis": {
                    "suggestedWindow": {
                        "startTimecode": "00:20:30.000",
                        "endTimecode": "00:58:45.000",
                    }
                },
            }

        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            state = root / "state.json"
            write_state(state)
            original = mod.build_multistage_post_live_timeline.build_multistage_timeline
            mod.build_multistage_post_live_timeline.build_multistage_timeline = fake_timeline
            try:
                report = mod.run_job(
                    make_args(root, str(state)),
                    metadata_loader=lambda _: {"live_status": "post_live", "was_live": True},
                    runner=runner,
                    uploader=lambda path, uri: uploads.append((str(path), uri)),
                    marker_reader=lambda _: None,
                    marker_writer=lambda _uri, _text: None,
                    notifier=lambda _args, _report: {"status": "sent", "messageId": "123"},
                    handoff_reader=lambda _: None,
                )
            finally:
                mod.build_multistage_post_live_timeline.build_multistage_timeline = original

        self.assertEqual(report["status"], "requires_operator_review")
        self.assertEqual(report["suggestedWindow"]["startTimecode"], "00:20:30.000")
        self.assertEqual(report["notification"]["status"], "sent")
        self.assertTrue(any(uri.endswith("/download/source_audio.m4a") for _, uri in uploads))
        self.assertTrue(any(uri.endswith("/timeline/report.json") for _, uri in uploads))
        self.assertTrue(any(uri.endswith("/timeline/coarse_120s/timeline_chunks.json") for _, uri in uploads))

    def test_consumes_local_gcs_handoff_before_youtube_download(self):
        uploads = []

        def fake_timeline(args):
            args.outdir.mkdir(parents=True, exist_ok=True)
            return {
                "status": "requires_operator_review",
                "analysis": {"suggestedWindow": {"startTimecode": "00:17:10", "endTimecode": "00:44:55"}},
            }

        def fake_gcs_download(uri, destination):
            self.assertTrue(uri.endswith("/download/source_audio.m4a"))
            path = Path(destination)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"audio from gcs")
            return path

        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            state = root / "state.json"
            write_state(state)
            original = mod.build_multistage_post_live_timeline.build_multistage_timeline
            mod.build_multistage_post_live_timeline.build_multistage_timeline = fake_timeline
            try:
                report = mod.run_job(
                    make_args(root, str(state)),
                    metadata_loader=lambda _: {"live_status": "was_live", "was_live": True},
                    runner=lambda *_args, **_kwargs: self.fail("YouTube download should not run"),
                    uploader=lambda path, uri: uploads.append((str(path), uri)),
                    marker_reader=lambda _: None,
                    marker_writer=lambda *_args: None,
                    notifier=lambda *_args: {"status": "not_configured"},
                    handoff_reader=lambda _: {
                        "status": "complete",
                        "audio": {"gcsUri": "gs://test-bucket/sundays/x/download/source_audio.m4a"},
                    },
                    gcs_downloader=fake_gcs_download,
                )
            finally:
                mod.build_multistage_post_live_timeline.build_multistage_timeline = original

        self.assertEqual(report["downloadSource"], "local-gcs-handoff")
        self.assertEqual(report["audioGcsUri"], "gs://test-bucket/sundays/x/download/source_audio.m4a")
        self.assertFalse(any(uri.endswith("/download/source_audio.m4a") for _, uri in uploads))

    def test_dedupes_completed_review_gate(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            state = root / "state.json"
            write_state(state)
            report = mod.run_job(
                make_args(root, str(state)),
                metadata_loader=lambda _: {"live_status": "post_live", "was_live": True},
                marker_reader=lambda _: {
                    "status": "requires_operator_review",
                    "sunday": "2026-07-12",
                    "notification": {"status": "sent"},
                },
            )
        self.assertEqual(report["status"], "already_requires_operator_review")
        self.assertTrue(report["deduped"])


if __name__ == "__main__":
    unittest.main()
