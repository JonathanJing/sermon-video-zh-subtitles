import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMMAND = [sys.executable, str(ROOT / "tools/ops/run.py"), "workflows.dual_pdf.local_post_live_download"]
from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.workflows.dual_pdf import local_post_live_download as mod


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
    def test_legacy_import_and_path_identity(self):
        from scripts import tongxing_host  # noqa: F401  binds the production package ports
        from tongxing_production.observability import accounting as sermon_accounting
        from tongxing_production import path_aliases

        root = ROOT
        self.assertEqual(mod.REPO_ROOT, root)
        self.assertEqual(mod.resolve_path(Path("artifacts/example")), root / "artifacts/example")
        self.assertEqual(mod.resolve_path(root / "absolute"), root / "absolute")
        self.assertEqual(mod.display_path(root / "artifacts/example"), "artifacts/example")
        self.assertEqual(mod.display_path(Path("/tmp/outside-example")), "/tmp/outside-example")
        key = path_aliases.resolve("scripts/run_local_post_live_download.py")
        self.assertEqual(key, "packages/production/src/tongxing_production/workflows/dual_pdf/local_post_live_download.py")
        loaded = sermon_accounting.execution_identity()["loadedProjectCodeSha256"]
        self.assertIn(key, loaded)
        self.assertTrue({"backend/cloud.py", "backend/config.py", "scripts/live_source_monitor.py",
                         "packages/production/src/tongxing_production/source/youtube_data_api.py"}.issubset(loaded))

    def test_legacy_cli_help_and_missing_source_from_other_directory(self):
        root = ROOT
        environment = os.environ.copy()
        environment["PYTHONPATH"] = os.pathsep.join((str(root / "packages/production/src"), str(root)))
        with tempfile.TemporaryDirectory() as tempdir:
            folder = Path(tempdir)
            help_result = subprocess.run([*COMMAND, "--help"],
                                         cwd=folder, env=environment, capture_output=True, text=True, timeout=30)
            self.assertEqual(help_result.returncode, 0, help_result.stderr)
            report = folder / "report.json"
            code = (
                "import sys; from scripts import tongxing_host; "
                "from tongxing_production.workflows.dual_pdf import local_post_live_download as m; "
                "m.live_source_monitor.read_state=lambda *_: {}; "
                "m.access_secret=lambda *_: 'mock-only'; "
                "m.discover_sunday_video=lambda *_a, **_k: None; "
                f"sys.argv=['legacy', '--sunday', '2026-07-12', '--state-file', 'unused', "
                f"'--youtube-api-key-secret', 'projects/p/secrets/unused/versions/latest', '--out', {str(report)!r}]; "
                "raise SystemExit(m.main())"
            )
            result = subprocess.run([sys.executable, "-c", code], cwd=folder, env=environment,
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(report.read_text(encoding="utf-8"))["status"], "missing_source")

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
        self.assertEqual(report["audio"]["sha256"], hashlib.sha256(b"audio").hexdigest())
        self.assertEqual(report["video"]["sha256"], hashlib.sha256(b"video").hexdigest())
        self.assertEqual(report["audio"]["sizeBytes"], 5)
        self.assertEqual(report["video"]["sizeBytes"], 5)
        self.assertTrue(manifests[0][0].endswith("/download/local-download-manifest.json"))
        self.assertEqual(json.loads(manifests[0][1])["audio"]["sha256"], report["audio"]["sha256"])
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
