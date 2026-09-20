"""Offline real extraction and mandatory weekly-build binding regressions."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import build_weekly_app as app
from deploy_firebase import bound_fingerprints, FINGERPRINT_UI
from poc import sha256, write_json
from test_build_weekly_app import app_fixture
from weekly_audio_fingerprint import bind_weekly_fingerprint
from weekly_dubbing import read


class WeeklyFingerprintTests(unittest.TestCase):
    def fixture(self, root):
        source = root / "original.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anoisesrc=color=pink:seed=42:sample_rate=8000:duration=12", str(source)], check=True)
        public = root.resolve() / "public"
        (public / "media").mkdir(parents=True)
        track = public / "media/chinese.mp3"
        track.write_bytes(b"fixture synchronized track")
        addressed = track.with_name(sha256(track)[:16] + "-chinese.mp3")
        track.rename(addressed)
        track = addressed
        clip = root / "clip.json"
        write_json(clip, {"source": {"sha256": sha256(source)}, "startSeconds": 1, "endSeconds": 11})
        job = {"sourceRoute": "live_archive", "sourceStartSeconds": 1, "sourceEndSeconds": 11, "sourceDurationSeconds": 10,
            "inputs": {"originalAudio": {"path": str(source), "sha256": sha256(source)}, "clipReceipt": {"path": str(clip), "sha256": sha256(clip)}}}
        week = {"id": "2026-09-20-live_archive-fixture", "sourceRoute": "live_archive", "sourceId": "fixture",
            "videoSynchronization": "candidate_aligned", "audioStatus": "full_candidate", "tracks": [{"sha256": sha256(track), "file": track.name, "audioUrl": "/media/" + track.name,
                "durationSeconds": 10, "subtitleTiming": "source_video_aligned_candidate"}]}
        return job, week, public

    @unittest.skipUnless(shutil.which("node") and shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires local Node and FFmpeg")
    def test_real_original_window_extracts_content_addressed_release_valid_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            job, week, public = self.fixture(Path(tmp))
            bind_weekly_fingerprint(job, week, public, synchronized=True)
            binding = week["audioFingerprint"]
            index = public / binding["indexUrl"][1:]
            self.assertEqual(sha256(index), binding["indexSha256"])
            self.assertEqual(read(index)["window"], {"startSeconds": 1, "endSeconds": 11})
            self.assertTrue(read(index)["postings"])
            self.assertEqual(week["automaticAudioAlignment"]["status"], "ready")
            write_json(public / "weekly.json", {"schemaVersion": "sermon-weekly-catalog-v1", "weeks": [week]})
            track = public / "media" / week["tracks"][0]["file"]
            expected = {binding["indexUrl"][1:]: {"sha256": sha256(index)},
                        "media/" + track.name: {"sha256": sha256(track), "bytes": track.stat().st_size},
                        **{n: {} for n in FINGERPRINT_UI}}
            self.assertEqual(bound_fingerprints(public, expected, [week["id"]]), {binding["indexUrl"][1:]})
            self.assertFalse(list(public.rglob("*.wav")))

    @unittest.skipUnless(shutil.which("node") and shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires local Node and FFmpeg")
    def test_full_sync_page_build_runs_real_extraction_and_release_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            source_job, _, _ = self.fixture(root)
            work = app_fixture(root)
            job = read(work / "job.json")
            job.update({k: source_job[k] for k in ("sourceRoute", "sourceStartSeconds", "sourceEndSeconds", "sourceDurationSeconds")})
            job["inputs"].update(source_job["inputs"])
            write_json(work / "job.json", job)
            assembly = read(work / "assembly-report.json")
            assembly["jobSha256"] = sha256(work / "job.json")
            write_json(work / "assembly-report.json", assembly)
            synced = read(work / "synchronization/assembly.json")
            # The dedicated candidate suite tests upstream alignment receipts;
            # this integration exercises the real new-page/index/release path.
            with patch.object(app, "synchronized_candidate", return_value=(synced, {})):
                report = app.build(root / "unused", root / "build", weekly_jobs=[work], review_preview=True, sync_preview=True)
            from deploy_firebase import verify_release
            verify_release(root / "build")
            week = read(root / "build/public/weekly.json")["weeks"][0]
            self.assertEqual(report["automaticAudioAlignmentPages"], [week["id"]])
            self.assertEqual(week["automaticAudioAlignment"]["status"], "ready")
            self.assertIn(week["audioFingerprint"]["indexUrl"][1:], {f["path"] for f in report["files"]})
            self.assertFalse(report["originalAudioPublished"])

    @unittest.skipUnless(shutil.which("node") and shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires local Node and FFmpeg")
    def test_other_verified_routes_use_original_or_complete_caption_audio(self):
        for route in ("same_video", "archive_caption"):
            with self.subTest(route=route), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                job, week, public = self.fixture(root)
                job["sourceRoute"] = week["sourceRoute"] = route
                if route == "archive_caption":
                    # Caption source contract is complete sermon-only audio.
                    source = job["inputs"].pop("originalAudio")
                    job["inputs"]["sourceAudio"] = source
                    contract = root / "contract.json"
                    write_json(contract, {"sermonOnly": True, "audio": source})
                    job["inputs"]["sourceContract"] = {"path": str(contract), "sha256": sha256(contract)}
                    job.update(sourceStartSeconds=0, sourceEndSeconds=12, sourceDurationSeconds=12)
                    week["tracks"][0]["durationSeconds"] = 12
                bind_weekly_fingerprint(job, week, public, synchronized=True)
                self.assertEqual(week["automaticAudioAlignment"]["status"], "ready")
                self.assertEqual(week["sourceStartSeconds"], job["sourceStartSeconds"])

    def test_preview_explicitly_unavailable_without_subprocess(self):
        week = {}
        with patch("weekly_audio_fingerprint.subprocess.run", side_effect=AssertionError("No extraction")):
            bind_weekly_fingerprint({}, week, Path("missing"), synchronized=False)
        self.assertEqual(week["automaticAudioAlignment"]["reason"], "unsynchronized_review_preview")
        self.assertNotIn("audioFingerprint", week)

    def test_sync_missing_original_is_fatal_not_optional(self):
        with self.assertRaisesRegex(ValueError, "frozen originalAudio"):
            bind_weekly_fingerprint({"inputs": {}}, {}, Path("missing"), synchronized=True)

    @unittest.skipUnless(shutil.which("ffmpeg"), "requires FFmpeg")
    def test_changed_source_and_wrong_absolute_window_fail_before_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            job, week, public = self.fixture(Path(tmp))
            with patch("weekly_audio_fingerprint.subprocess.run", side_effect=AssertionError("No extraction")):
                job["sourceEndSeconds"] = 10
                with self.assertRaisesRegex(ValueError, "absolute source window"):
                    bind_weekly_fingerprint(job, week, public, synchronized=True)
                job["sourceEndSeconds"] = 11
                Path(job["inputs"]["originalAudio"]["path"]).write_bytes(b"changed")
                with self.assertRaisesRegex(ValueError, "missing or changed"):
                    bind_weekly_fingerprint(job, week, public, synchronized=True)

    def test_build_sync_path_cannot_silently_skip_missing_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = app_fixture(root)
            with self.assertRaisesRegex(ValueError, "frozen originalAudio"):
                app.build(root / "unused", root / "build", weekly_jobs=[work], review_preview=True, sync_preview=True)
            self.assertFalse((root / "build/build-report.json").exists())

    def test_build_natural_preview_records_required_page_and_unavailable_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = app_fixture(root)
            report = app.build(root / "unused", root / "build", weekly_jobs=[work], review_preview=True)
            week = read(root / "build/public/weekly.json")["weeks"][0]
            self.assertEqual(report["automaticAudioAlignmentPages"], [week["id"]])
            self.assertEqual(week["automaticAudioAlignment"]["status"], "unavailable")
            self.assertNotIn("audioFingerprint", week)


if __name__ == "__main__":
    unittest.main()
