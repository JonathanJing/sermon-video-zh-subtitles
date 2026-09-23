import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import build_target_language_audio_package as audio_package
from scripts import clip_timeline_map as subject


class Mp4DurationFallbackTests(unittest.TestCase):
    def test_movie_header_duration_when_ffprobe_is_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "clip.mp4"
            mvhd = b"\x00\x00\x00\x00" + b"\x00" * 8 + (240000).to_bytes(4, "big") + (42762720).to_bytes(4, "big")
            movie = (len(mvhd) + 8).to_bytes(4, "big") + b"mvhd" + mvhd
            path.write_bytes((len(movie) + 8).to_bytes(4, "big") + b"moov" + movie)
            with mock.patch.object(subject.subprocess, "run", side_effect=FileNotFoundError()):
                self.assertAlmostEqual(subject.media_duration(path), 178.178, places=3)
            path.write_bytes(path.read_bytes()[:10])
            with self.assertRaises(ValueError):
                subject.mp4_movie_duration(path)


class RealSep20TimelineMapTests(unittest.TestCase):
    def setUp(self):
        configured = os.environ.get("SERMON_SEP20_CLIP_ROOT")
        if not configured:
            self.skipTest("Set SERMON_SEP20_CLIP_ROOT to ignored real clip artifacts")
        self.root = Path(configured)
        self.layer1 = self.root / "layer1/3fb4ca066371c249c8454a8f7627f425871d4a8c54a2cc340713f7bd656f3276"
        self.source_path = self.layer1 / "english-source-package.json"
        self.anchor_path = self.layer1 / "anchor-manifest.json"
        self.clip_path = self.root / "source-clip.mp4"
        if not all(path.is_file() for path in (self.source_path, self.anchor_path, self.clip_path)):
            self.skipTest("Real Sep 20 clip artifacts are incomplete")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def test_real_approved_clip_and_sermon_relative_anchors_map_to_178_seconds(self):
        mapping = subject.prepare(self.source_path, self.anchor_path, self.clip_path,
                                  320.16, Path(self.temp.name) / "map.json")
        source, anchor = subject.read_object(self.source_path), subject.read_object(self.anchor_path)
        self.assertEqual(mapping["anchorFirstStartSeconds"], 320.16)
        self.assertAlmostEqual(mapping["anchorLastEndSeconds"], 498.32, places=2)
        self.assertAlmostEqual(mapping["clipDurationSeconds"], 178.178, places=2)
        self.assertAlmostEqual(subject.validate(mapping, source, anchor), 320.16, places=2)
        first = anchor["sourceUnits"][0]
        source_start = first["start"] - mapping["anchorOffsetSeconds"]
        self.assertAlmostEqual(source_start, 0.0, places=2)
        schedule = {
            "targetLocale": "ko", "timingKind": "measured_target_audio",
            "status": "pass", "issues": [], "trackDurationSeconds": 178.178,
            "policy": {"reactionLagSeconds": 0.25, "interUtteranceGapSeconds": 0.12,
                       "maxEndLagSeconds": 8.0},
            "entries": [{"textGroupId": "first", "sourceUnitIds": [first["sourceUnitId"]],
                         "plannedStart": 0.25, "plannedEnd": 0.75}],
        }
        candidate = {"targetLocale": "ko", "groups": [
            {"translationGroupId": "first", "sourceUnitIds": [first["sourceUnitId"]]}]}
        audio_package.validate_schedule(schedule, candidate, anchor, [0.5], 178.178,
                                        320.16, 178.178)

    def test_real_clip_rejects_wrong_offset_even_if_explicit(self):
        mapping = subject.prepare(self.source_path, self.anchor_path, self.clip_path,
                                  320.16, Path(self.temp.name) / "map.json")
        mapping = copy.deepcopy(mapping)
        mapping["anchorOffsetSeconds"] = 0.0
        with self.assertRaisesRegex(ValueError, "anchor offset"):
            subject.validate(mapping, subject.read_object(self.source_path),
                             subject.read_object(self.anchor_path))


if __name__ == "__main__":
    unittest.main()
