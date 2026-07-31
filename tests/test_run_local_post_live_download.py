import argparse
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_local_post_live_download.py"
SPEC = importlib.util.spec_from_file_location("run_local_post_live_download", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def args_for(root: Path):
    return argparse.Namespace(
        sunday="2026-07-12",
        state_file=str(root / "unused.json"),
        live_url="https://www.youtube.com/watch?v=5GuhLMPflds",
        work_root=root / "work",
        out=root / "report.json",
        gcs_bucket="test-bucket",
        gcs_prefix="sundays",
        youtube_api_key_secret="projects/p/secrets/youtube/versions/latest",
        youtube_streams_url="https://www.youtube.com/@marinerschurch/streams",
        timezone="America/Los_Angeles",
        youtube_cookies=None,
        yt_dlp="yt-dlp",
        audio_format="bestaudio",
        video_format="bestvideo+bestaudio",
        existing_audio=None,
        existing_video=None,
        force=False,
    )


class LocalPostLiveDownloadTest(unittest.TestCase):
    def test_missing_source_is_a_successful_polling_noop(self):
        self.assertEqual(mod.exit_code_for_status("missing_source"), 0)
        self.assertEqual(mod.exit_code_for_status("waiting_for_post_live"), 0)
        self.assertEqual(mod.exit_code_for_status("failed"), 2)

    def test_discovers_current_sunday_video_from_official_streams(self):
        metadata = {
            "old12345678": {"actual_start_time": "2026-07-05T15:21:04Z", "live_status": "was_live"},
            "live1234567": {"actual_start_time": "2026-07-12T16:51:04Z", "live_status": "is_live"},
            "done1234567": {"actual_start_time": "2026-07-12T15:21:04Z", "live_status": "was_live"},
        }
        result = mod.discover_sunday_video(
            "2026-07-12",
            streams_url="streams",
            timezone_name="America/Los_Angeles",
            api_key="key",
            urls_loader=lambda _url: [
                "https://www.youtube.com/watch?v=old12345678",
                "https://www.youtube.com/watch?v=done1234567",
                "https://www.youtube.com/watch?v=live1234567",
            ],
            metadata_loader=lambda video_id, api_key: metadata[video_id],
        )
        self.assertEqual(result, "https://www.youtube.com/watch?v=live1234567")

    def test_uploads_audio_video_and_complete_handoff_manifest(self):
        uploads = []
        manifests = []
        originals = {
            "access_secret": mod.access_secret,
            "video_metadata": mod.youtube_data_api.video_metadata,
            "prepare_audio": mod.prepare_audio,
            "prepare_video": mod.prepare_video,
            "upload": mod.upload_file_to_gcs,
            "write": mod.write_gcs_text,
            "duration": mod.sermon_pipeline.ffprobe_duration,
        }
        try:
            mod.access_secret = lambda _name: "key"
            mod.youtube_data_api.video_metadata = lambda *_args, **_kwargs: {
                "id": "5GuhLMPflds", "live_status": "was_live", "was_live": True,
            }
            mod.prepare_audio = lambda args, _url, directory: write_media(directory / "source_audio.m4a", b"audio")
            mod.prepare_video = lambda args, _url, directory: write_media(directory / "source_video.mp4", b"video")
            mod.upload_file_to_gcs = lambda path, uri: uploads.append((Path(path).name, uri))
            mod.write_gcs_text = lambda uri, text: manifests.append((uri, text))
            mod.sermon_pipeline.ffprobe_duration = lambda path: 100.0 if Path(path).suffix == ".m4a" else 101.0
            with tempfile.TemporaryDirectory() as tempdir:
                report = mod.run_local_download(args_for(Path(tempdir)))
        finally:
            mod.access_secret = originals["access_secret"]
            mod.youtube_data_api.video_metadata = originals["video_metadata"]
            mod.prepare_audio = originals["prepare_audio"]
            mod.prepare_video = originals["prepare_video"]
            mod.upload_file_to_gcs = originals["upload"]
            mod.write_gcs_text = originals["write"]
            mod.sermon_pipeline.ffprobe_duration = originals["duration"]

        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["handoffKind"], "local-download-to-gcs")
        self.assertEqual(len(uploads), 2)
        self.assertTrue(report["audio"]["gcsUri"].endswith("/download/source_audio.m4a"))
        self.assertTrue(report["video"]["gcsUri"].endswith("/download/source_video.mp4"))
        self.assertTrue(manifests[0][0].endswith("/download/local-download-manifest.json"))
        self.assertNotIn("key", manifests[0][1])

    def test_complete_local_manifest_makes_retries_idempotent(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            args = args_for(root)
            manifest = root / "work" / "2026-07-12" / "sermon_5GuhLMPflds" / "download" / "local-download-manifest.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text('{"status":"complete","handoffKind":"local-download-to-gcs"}', encoding="utf-8")
            original_secret = mod.access_secret
            original_metadata = mod.youtube_data_api.video_metadata
            try:
                mod.access_secret = lambda _name: "key"
                mod.youtube_data_api.video_metadata = lambda *_args, **_kwargs: {
                    "id": "5GuhLMPflds", "live_status": "was_live", "was_live": True,
                }
                report = mod.run_local_download(args)
            finally:
                mod.access_secret = original_secret
                mod.youtube_data_api.video_metadata = original_metadata

        self.assertEqual(report["status"], "already_complete")


def write_media(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


if __name__ == "__main__":
    unittest.main()
