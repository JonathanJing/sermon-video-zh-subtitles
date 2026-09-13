"""Archive coverage failures must stop before model work or completion uploads."""
import json
import shutil
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

from scripts import run_post_live_subtitle_generation as generation
from scripts import run_post_live_timeline_job as timeline
from tests.test_run_post_live_subtitle_generation import make_args as generation_args, write_state as generation_state
from tests.test_run_post_live_timeline_job import make_args as timeline_args, write_state as timeline_state, make_handoff


def audio_probe(seconds, *, audio=True):
    return {"format": {"duration": str(seconds)}, "streams": [{"codec_type": "audio" if audio else "video"}]}


class ArchiveAudioIntegrityTest(unittest.TestCase):
    def test_duration_tolerance_accepts_remux_tail_but_rejects_incomplete_or_wrong_media(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "source_audio.m4a"
            path.write_bytes(b"media")
            for duration, accepted in [(4719, True), (4723.821, True), (4710, False), (2733.801, False), (5000, False)]:
                with self.subTest(duration=duration), mock.patch.object(generation, "probe_archive_audio", return_value=audio_probe(duration)):
                    if accepted:
                        generation.validate_archive_audio(path, expected_duration_seconds=4722)
                    else:
                        with self.assertRaisesRegex(generation.ArchiveAudioValidationError, "duration mismatch"):
                            generation.validate_archive_audio(path, expected_duration_seconds=4722)
            for probe in [audio_probe(4722, audio=False), audio_probe("nan"), audio_probe(0)]:
                with self.subTest(probe=probe), mock.patch.object(generation, "probe_archive_audio", return_value=probe):
                    with self.assertRaises(generation.ArchiveAudioValidationError):
                        generation.validate_archive_audio(path, expected_duration_seconds=4722)

    def test_missing_or_invalid_metadata_duration_is_not_completion_evidence(self):
        for value in [None, "", 0, -1, True, "nan", "inf"]:
            with self.subTest(value=value), self.assertRaisesRegex(generation.ArchiveAudioValidationError, "metadata has no valid duration"):
                generation.archive_expected_duration({"duration": value})

    def test_cache_filter_rejects_sidecars_fragments_and_directories(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ["source_audio.info.json", "source_audio.asr.json", "source_audio.m4a.part", "source_audio.m4a.ytdl", "source_audio.m4a.part-Frag4", "source_audio.part.m4a"]:
                (root / name).write_bytes(b"sidecar")
            (root / "source_audio.mp4").mkdir()
            self.assertIsNone(generation.newest_downloaded_audio(root))
            complete = root / "source_audio.m4a"
            complete.write_bytes(b"complete")
            self.assertEqual(generation.newest_downloaded_audio(root), complete)

    def test_download_exit_zero_does_not_admit_short_audio_and_uses_strict_fragment_flags(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            def fake_runner(command, check):
                self.assertIn("--abort-on-unavailable-fragments", command)
                self.assertIn("--no-overwrites", command)
                (root / "source_audio.m4a").write_bytes(b"incomplete archive")
                return subprocess.CompletedProcess(command, 0)
            with mock.patch.object(generation, "probe_archive_audio", return_value=audio_probe(2733.801)):
                with self.assertRaisesRegex(generation.ArchiveAudioValidationError, "measured 2733.801s, expected 4722.000s"):
                    generation.download_archive_audio("https://example.com/archive", root / "source_audio.%(ext)s", "bestaudio", "yt-dlp", fake_runner, expected_duration_seconds=4722)
            self.assertEqual((root / "source_audio.m4a").read_bytes(), b"incomplete archive")

    def test_finished_cache_is_validated_without_redownload_and_partial_files_are_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "source_audio.m4a"
            path.write_bytes(b"complete")
            runner = mock.Mock(side_effect=AssertionError("must not redownload"))
            with mock.patch.object(generation, "probe_archive_audio", return_value=audio_probe(4723.821)):
                self.assertEqual(generation.download_archive_audio("url", root / "source_audio.%(ext)s", "bestaudio", "yt-dlp", runner, expected_duration_seconds=4722), path)
            runner.assert_not_called()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            partial = root / "source_audio.m4a.part"
            partial.write_bytes(b"recoverable fragments")
            with self.assertRaisesRegex(generation.ArchiveAudioValidationError, "Partial download files preserved"):
                generation.download_archive_audio("url", root / "source_audio.%(ext)s", "bestaudio", "yt-dlp", runner, expected_duration_seconds=4722)
            self.assertEqual(partial.read_bytes(), b"recoverable fragments")
            runner.assert_not_called()

    def test_timeline_rejects_new_cached_and_handoff_short_audio_before_asr_or_upload(self):
        for mode in ["new", "cached", "handoff"]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                state = root / "state.json"
                timeline_state(state)
                args = timeline_args(root, str(state))
                path = root / args.sunday / "sermon_5GuhLMPflds" / "download/source_audio.m4a"
                def write_audio():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b"incomplete archive")
                    return path
                def fake_runner(command, check):
                    write_audio()
                    return subprocess.CompletedProcess(command, 0)
                if mode == "cached":
                    write_audio()
                downloader = mock.Mock(side_effect=lambda *_: write_audio())
                runner = mock.Mock(side_effect=fake_runner)
                upload = mock.Mock()
                with mock.patch.object(generation, "probe_archive_audio", return_value=audio_probe(2733.801)), mock.patch.object(timeline.build_multistage_post_live_timeline, "build_multistage_timeline") as model, mock.patch("builtins.print"):
                    report = timeline.run_job(
                        args, metadata_loader=lambda _: {"live_status": "was_live", "duration": 4722},
                        runner=runner, uploader=upload, marker_reader=lambda _: None,
                        handoff_reader=lambda _: make_handoff(b"incomplete archive") if mode == "handoff" else None,
                        gcs_downloader=downloader, marker_writer=lambda *_: None,
                    )
                self.assertEqual(report["status"], "failed")
                self.assertEqual(report["reason"], "archive_audio_integrity_failed")
                self.assertIn("2733.801", report["downloadDiagnostics"]["reason"])
                status = json.loads((path.parent.parent / "run-status.json").read_text())
                self.assertEqual(status["status"], "failed")
                self.assertEqual(status["stages"]["downloaded"]["status"], "failed")
                self.assertNotIn("completedAt", status["stages"]["downloaded"])
                model.assert_not_called()
                upload.assert_not_called()
                self.assertEqual(path.read_bytes(), b"incomplete archive")
                self.assertEqual(runner.call_count, 1 if mode == "new" else 0)

    def test_generation_rejects_incomplete_cache_before_paid_pipeline(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root / "state.json"
            generation_state(state)
            args = generation_args(state_file=str(state), work_root=root, plan_only=False)
            path = root / args.sunday / args.slug / "download/source_audio.m4a"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"incomplete archive")
            runner = mock.Mock()
            with mock.patch.object(generation, "probe_archive_audio", return_value=audio_probe(2733.801)), self.assertRaises(generation.ArchiveAudioValidationError):
                generation.run_post_live_generation(args, metadata_loader=lambda _: {"live_status": "was_live", "duration": 4722}, runner=runner)
            runner.assert_not_called()
            status = json.loads((path.parent.parent / "run-status.json").read_text())
            self.assertEqual(status["status"], "failed")
            self.assertEqual(status["currentStage"], "downloaded")
            self.assertEqual(path.read_bytes(), b"incomplete archive")

    @unittest.skipUnless(shutil.which("ffprobe"), "ffprobe is required for the real media probe")
    def test_real_ffprobe_accepts_audio_and_rejects_corrupt_media(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "source_audio.wav"
            with wave.open(str(path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(8000)
                audio.writeframes(b"\0\0" * 8000)
            generation.validate_archive_audio(path, expected_duration_seconds=1)
            path.write_bytes(b"not an audio file")
            with self.assertRaisesRegex(generation.ArchiveAudioValidationError, "could not be probed"):
                generation.validate_archive_audio(path, expected_duration_seconds=1)


if __name__ == "__main__":
    unittest.main()
