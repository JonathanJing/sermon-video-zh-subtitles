import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import build_target_language_audio_package as audio_package
from scripts import clip_timeline_map as subject


class CompleteMediaTimelineMapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.media_path = root / "complete.mp4"
        self.media_path.write_bytes(b"complete-media-fixture")
        self.approval_path = root / "approval.json"
        self.approval = {"status": "approved", "humanApproval": True,
                         "sourceMediaSha256": subject.interpretation.sha256(self.media_path),
                         "startTime": "00:00:00", "endTime": "00:00:10"}
        self.approval_path.write_text(json.dumps(self.approval))
        self.anchor_path = root / "anchor.json"
        self.anchor = {"sourceUnits": [
            {"sourceUnitId": "u1", "start": 0.44, "end": 2.0},
            {"sourceUnitId": "u2", "start": 3.0, "end": 8.9},
        ]}
        self.anchor_path.write_text(json.dumps(self.anchor))
        self.source_path = root / "source.json"
        self.source = {"source": {
            "media": {"sha256": subject.interpretation.sha256(self.media_path),
                      "durationSeconds": 10.0},
            "approvedWindow": {
                "startSeconds": 0, "endSeconds": 10.0,
                "status": "approved", "humanApproval": True,
                "evidence": {"path": str(self.approval_path),
                             "sha256": subject.interpretation.sha256(self.approval_path),
                             "jsonSha256": subject.interpretation.json_sha256(self.approval)},
            },
        }, "anchors": {"artifact": {
            "jsonSha256": subject.interpretation.json_sha256(self.anchor)}}}
        self.source_path.write_text(json.dumps(self.source))

    def prepare(self, offset=None):
        with mock.patch.object(subject, "media_duration", return_value=10.0):
            return subject.prepare(self.source_path, self.anchor_path, self.media_path,
                                   offset, Path(self.temp.name) / "map.json")

    def validate(self, mapping):
        with mock.patch.object(subject, "media_duration", return_value=10.0):
            return subject.validate(mapping, self.source, self.anchor)

    def test_complete_source_binds_natural_leading_and_trailing_silence(self):
        mapping = self.prepare()
        self.assertEqual(mapping["schemaVersion"], subject.COMPLETE_MEDIA_SCHEMA)
        self.assertEqual(mapping["anchorOffsetSeconds"], 0)
        self.assertNotIn("originalRecordingStartSeconds", mapping)
        self.assertEqual(self.validate(mapping), 0)

    def test_complete_source_rejects_arbitrary_offset_and_partial_window(self):
        with self.assertRaisesRegex(ValueError, "media origin"):
            self.prepare(0.44)
        mapping = self.prepare()
        mapping["anchorOffsetSeconds"] = 0.44
        with self.assertRaisesRegex(ValueError, "schema error"):
            self.validate(mapping)
        mapping["anchorOffsetSeconds"] = 0
        self.source["source"]["approvedWindow"]["endSeconds"] = 9.0
        self.approval["endTime"] = "00:00:09"
        self.approval_path.write_text(json.dumps(self.approval))
        evidence = self.source["source"]["approvedWindow"]["evidence"]
        evidence["sha256"] = subject.interpretation.sha256(self.approval_path)
        evidence["jsonSha256"] = subject.interpretation.json_sha256(self.approval)
        mapping["windowApproval"] = evidence
        mapping["englishSourcePackageJsonSha256"] = subject.interpretation.json_sha256(self.source)
        with self.assertRaisesRegex(ValueError, "full-media approval"):
            self.validate(mapping)

    def test_legacy_clip_still_requires_explicit_offset_and_original_window(self):
        self.approval["originalRecordingWindow"] = "00:00:02-00:00:12"
        self.approval_path.write_text(json.dumps(self.approval))
        evidence = self.source["source"]["approvedWindow"]["evidence"]
        evidence["sha256"] = subject.interpretation.sha256(self.approval_path)
        evidence["jsonSha256"] = subject.interpretation.json_sha256(self.approval)
        self.source_path.write_text(json.dumps(self.source))
        with self.assertRaisesRegex(ValueError, "explicit anchor offset"):
            self.prepare()
        # A legacy extracted clip is still rejected when its anchors do not
        # reach the approved clip edges, even if the offset is explicit.
        with self.assertRaisesRegex(ValueError, "anchor offset"):
            self.prepare(0)


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

    def test_bounded_trailing_silence_is_allowed_but_larger_gap_is_not(self):
        mapping = subject.prepare(self.source_path, self.anchor_path, self.clip_path,
                                  320.16, Path(self.temp.name) / "map.json")
        source, anchor = subject.read_object(self.source_path), subject.read_object(self.anchor_path)
        shortened = copy.deepcopy(anchor)
        shortened["sourceUnits"][-1]["end"] -= 0.23
        mapping["anchorLastEndSeconds"] -= 0.23
        mapping["anchorManifestJsonSha256"] = subject.interpretation.json_sha256(shortened)
        source["anchors"]["artifact"]["jsonSha256"] = mapping["anchorManifestJsonSha256"]
        mapping["englishSourcePackageJsonSha256"] = subject.interpretation.json_sha256(source)
        self.assertAlmostEqual(subject.validate(mapping, source, shortened), 320.16)
        shortened["sourceUnits"][-1]["end"] -= 0.2
        mapping["anchorLastEndSeconds"] -= 0.2
        mapping["anchorManifestJsonSha256"] = subject.interpretation.json_sha256(shortened)
        source["anchors"]["artifact"]["jsonSha256"] = mapping["anchorManifestJsonSha256"]
        mapping["englishSourcePackageJsonSha256"] = subject.interpretation.json_sha256(source)
        with self.assertRaisesRegex(ValueError, "anchor offset"):
            subject.validate(mapping, source, shortened)


if __name__ == "__main__":
    unittest.main()
