import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


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
        "discord_bot_token_secret": None,
        "discord_channel_id": None,
        "audio_format": "bestaudio[ext=m4a]/bestaudio",
        "yt_dlp": "yt-dlp",
        "youtube_cookies_secret": None,
        "youtube_cookies": None,
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


def make_handoff(content: bytes, *, sunday="2026-07-12", source_id="5GuhLMPflds", bucket="test-bucket"):
    slug = f"sermon_{source_id}"
    return {
        "schemaVersion": 1, "status": "complete", "handoffKind": "local-download-to-gcs",
        "sunday": sunday, "slug": slug, "sourceUrl": f"https://www.youtube.com/watch?v={source_id}",
        "audio": {
            "gcsUri": f"gs://{bucket}/sundays/{sunday}/post-live-subtitles/{slug}/download/source_audio.m4a",
            "fileName": "source_audio.m4a", "sizeBytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(), "durationSeconds": 3600,
        },
    }


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
                "duration": 3600,
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
                marker_reader=lambda _: None,
            )
        self.assertEqual(report["status"], "waiting_for_post_live")

    def test_reports_download_access_separately_after_metadata_is_ready(self):
        marker_writes = []

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
                    "duration": 3600,
                },
                runner=failing_runner,
                marker_reader=lambda _: None,
                handoff_reader=lambda _: None,
                marker_writer=lambda uri, text: marker_writes.append((uri, json.loads(text))),
            )

        self.assertEqual(report["status"], "waiting_for_download_access")
        self.assertEqual(report["reason"], "youtube_metadata_ready_but_archive_download_failed")
        self.assertFalse(report["downloadDiagnostics"]["cookiesConfigured"])
        self.assertEqual(report["downloadDiagnostics"]["errorClass"], "CalledProcessError")
        self.assertEqual(marker_writes[-1][1]["status"], "waiting_for_download_access")

    def test_resolves_explicit_local_cookie_file(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "youtube.cookies.txt"
            path.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")

            resolved = mod.resolve_youtube_cookies(None, path, Path(tempdir) / "work")

        self.assertEqual(resolved, path.resolve())

    def test_rejects_cookie_secret_and_local_file_together(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "youtube.cookies.txt"
            path.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                mod.resolve_youtube_cookies("projects/p/secrets/cookies", path, Path(tempdir))

    @mock.patch.object(mod.run_post_live_subtitle_generation, "probe_archive_audio", return_value={"format": {"duration": "3600"}, "streams": [{"codec_type": "audio"}]})
    def test_downloads_uploads_probes_and_stops_for_review(self, _probe):
        uploads = []

        def runner(command, check):
            template = Path(command[command.index("-o") + 1])
            template.parent.mkdir(parents=True, exist_ok=True)
            (template.parent / "source_audio.m4a").write_bytes(b"audio")
            return subprocess.CompletedProcess(command, 0)

        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            state = root / "state.json"
            write_state(state)
            legacy = root / "2026-07-12" / "sermon_5GuhLMPflds" / "timeline" / "report.json"
            legacy.parent.mkdir(parents=True)
            legacy.write_text('{"legacy": true}', encoding="utf-8")
            report = mod.run_job(
                make_args(root, str(state)),
                metadata_loader=lambda _: {"live_status": "post_live", "was_live": True, "duration": 3600},
                runner=runner,
                uploader=lambda path, uri: uploads.append((str(path), uri)),
                marker_reader=lambda _: None,
                marker_writer=lambda _uri, _text: None,
                notifier=lambda _args, _report: {"status": "sent", "messageId": "123"},
                handoff_reader=lambda _: None,
            )

            self.assertEqual(legacy.read_text(), '{"legacy": true}')
            evidence = json.loads(legacy.with_name("source-media-report.json").read_text())
            self.assertEqual(evidence["status"], "source_media_verified")
            self.assertEqual(evidence["durationSeconds"], 3600)
            self.assertEqual(evidence["audioSha256"], report["audioSha256"])

        self.assertEqual(report["status"], "requires_operator_review")
        self.assertIsNone(report["suggestedWindow"])
        self.assertEqual(report["schemaVersion"], 2)
        self.assertEqual(report["stage"], "source_media_verified")
        self.assertEqual(report["boundaryMethod"], "operator_supplied")
        self.assertEqual(report["modelsUsed"], [])
        self.assertEqual(report["durationSeconds"], 3600)
        self.assertEqual(report["audioSha256"], hashlib.sha256(b"audio").hexdigest())
        self.assertFalse(hasattr(mod, "build_multistage_post_live_timeline"))
        self.assertEqual(report["notification"]["status"], "sent")
        self.assertTrue(any(uri.endswith("/download/source_audio.m4a") for _, uri in uploads))
        self.assertTrue(any(uri.endswith("/timeline/source-media-report.json") for _, uri in uploads))
        self.assertEqual(len(uploads), 2)

    @mock.patch.object(mod.run_post_live_subtitle_generation, "probe_archive_audio", return_value={"format": {"duration": "3600"}, "streams": [{"codec_type": "audio"}]})
    def test_consumes_local_gcs_handoff_before_youtube_download(self, _probe):
        uploads = []

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
            report = mod.run_job(
                make_args(root, str(state)),
                metadata_loader=lambda _: {"live_status": "was_live", "was_live": True, "duration": 3600},
                runner=lambda *_args, **_kwargs: self.fail("YouTube download should not run"),
                uploader=lambda path, uri: uploads.append((str(path), uri)),
                marker_reader=lambda _: None,
                marker_writer=lambda *_args: None,
                notifier=lambda *_args: {"status": "not_configured"},
                handoff_reader=lambda _: make_handoff(b"audio from gcs"),
                gcs_downloader=fake_gcs_download,
            )

        self.assertEqual(report["downloadSource"], "local-gcs-handoff")
        self.assertEqual(report["audioGcsUri"], make_handoff(b"audio from gcs")["audio"]["gcsUri"])
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
                    "sourceUrl": "https://www.youtube.com/watch?v=5GuhLMPflds",
                    "notification": {"status": "sent"},
                },
            )
        self.assertEqual(report["status"], "already_requires_operator_review")
        self.assertTrue(report["deduped"])

    def test_preserves_existing_source_media_report_on_conflict(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "source-media-report.json"
            original = {"audioSha256": "original", "durationSeconds": 3600}
            mod.preserve_json(path, original)
            mod.preserve_json(path, original)
            with self.assertRaisesRegex(RuntimeError, "not overwritten"):
                mod.preserve_json(path, {"audioSha256": "changed"})
            self.assertEqual(json.loads(path.read_text()), original)

    def test_rejects_cached_review_from_another_source(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            state = root / "state.json"
            write_state(state)
            with self.assertRaisesRegex(RuntimeError, "another or unverified source"):
                mod.run_job(
                    make_args(root, str(state)),
                    metadata_loader=lambda _: {"live_status": "post_live", "was_live": True},
                    marker_reader=lambda _: {
                        "status": "requires_operator_review", "sunday": "2026-07-12",
                        "sourceUrl": "https://www.youtube.com/watch?v=OtherSource",
                    },
                )

    @mock.patch.object(mod.run_post_live_subtitle_generation, "probe_archive_audio", return_value={"format": {"duration": "10"}, "streams": [{"codec_type": "audio"}]})
    def test_incomplete_audio_fails_without_model_or_media_report(self, _probe):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            state = root / "state.json"
            write_state(state)
            def runner(command, check):
                path = Path(command[command.index("-o") + 1]).parent / "source_audio.m4a"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"partial")
                return subprocess.CompletedProcess(command, 0)
            report = mod.run_job(
                make_args(root, str(state)),
                metadata_loader=lambda _: {"live_status": "post_live", "was_live": True, "duration": 3600},
                runner=runner, marker_reader=lambda _: None, handoff_reader=lambda _: None,
                marker_writer=lambda *_: None,
                uploader=lambda *_: self.fail("Invalid audio must not be uploaded"),
            )
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["reason"], "archive_audio_integrity_failed")
            self.assertFalse(list(root.rglob("source-media-report.json")))

    def test_cli_has_no_model_or_chunk_controls(self):
        with mock.patch.object(sys, "argv", ["timeline"]):
            args = mod.parse_args()
        for name in ("classifier_model", "timeline_model", "reasoning_effort", "chunk_seconds", "api_key_secret"):
            self.assertFalse(hasattr(args, name))


if __name__ == "__main__":
    unittest.main()
