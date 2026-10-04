import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import clip_timeline_map as subject


class DerivedClipTimelineMapV3Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source_media = self.root / "full-source.mp4"
        self.source_media.write_bytes(b"full-source-fixture")
        self.clip = self.root / "approved-window.m4a"
        self.clip.write_bytes(b"derived-aac-fixture")
        self.approval_path = self.root / "approval.json"
        self.approval = {
            "schemaVersion": "sermon-clip-window-approval-v1",
            "sourceId": "synthetic:approved-window-v3",
            "sourceMediaSha256": subject.interpretation.sha256(self.source_media),
            "startTime": "00:02:00.500", "endTime": "00:02:10.500",
            "status": "approved", "humanApproval": True,
        }
        self.write_json(self.approval_path, self.approval)
        self.receipt_path = self.root / "clip.m4a.cache.json"
        stat = self.source_media.stat()
        self.receipt = {
            "schemaVersion": 1, "operation": "clip_and_normalize",
            "source": {"sha256": subject.interpretation.sha256(self.source_media),
                       "sizeBytes": stat.st_size, "modifiedTimeNs": stat.st_mtime_ns},
            "startSeconds": 120.5, "endSeconds": 130.5,
            "audioFilter": "loudnorm=I=-16:TP=-1.5:LRA=11", "codec": "aac",
            "sampleRate": 44100, "channels": 1, "bitrate": "64k",
        }
        self.write_json(self.receipt_path, self.receipt)
        self.anchor = {"sourceUnits": [
            {"sourceUnitId": "u1", "start": 2.24, "end": 5.0},
            {"sourceUnitId": "u2", "start": 5.2, "end": 8.79},
        ]}
        self.anchor_path = self.root / "anchor.json"
        self.write_json(self.anchor_path, self.anchor)
        approval_evidence = {
            "path": str(self.approval_path),
            "sha256": subject.interpretation.sha256(self.approval_path),
            "jsonSha256": subject.interpretation.json_sha256(self.approval),
        }
        self.source = {
            "source": {
                "sourceId": "synthetic:approved-window-v3",
                "media": {"sha256": subject.interpretation.sha256(self.source_media),
                          "sizeBytes": stat.st_size, "durationSeconds": 240.0},
                "approvedWindow": {"startSeconds": 120.5, "endSeconds": 130.5,
                                   "status": "approved", "humanApproval": True,
                                   "evidence": approval_evidence},
            },
            "anchors": {"artifact": {
                "jsonSha256": subject.interpretation.json_sha256(self.anchor)}}
        }
        self.source_path = self.root / "source.json"
        self.write_json(self.source_path, self.source)
        self.probe = {
            "codec": "aac", "sampleRate": 44100, "channels": 1,
            "formatDurationSeconds": 10 + 1024 / 44100,
            "streamStartTimeSeconds": 0.0,
            "streamDurationSeconds": 10 + 1024 / 44100,
            "decodedAudioSamples": 441000,
            "decodedAudioDurationSeconds": 10.0,
            "containerPaddingSamples": 1024, "paddingBudgetSamples": 4096,
        }
        self.out = self.root / "map-v3.json"
        with mock.patch.object(subject, "media_duration", return_value=240.0), \
             mock.patch.object(subject, "probe_derived_audio", return_value=self.probe):
            self.mapping = subject.prepare(
                self.source_path, self.anchor_path, self.clip, None, self.out,
                source_media_path=self.source_media,
                extraction_receipt_path=self.receipt_path)

    def write_json(self, path, value):
        path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")

    def validate(self, mapping=None, source=None, anchor=None):
        with mock.patch.object(subject, "media_duration", return_value=240.0), \
             mock.patch.object(subject, "probe_derived_audio", return_value=self.probe):
            return subject.validate(mapping or self.mapping,
                                    source or self.source, anchor or self.anchor)

    def rebind_anchor(self, anchor):
        source = copy.deepcopy(self.source)
        source["anchors"]["artifact"]["jsonSha256"] = subject.interpretation.json_sha256(anchor)
        mapping = copy.deepcopy(self.mapping)
        mapping["anchorManifestJsonSha256"] = subject.interpretation.json_sha256(anchor)
        mapping["englishSourcePackageJsonSha256"] = subject.interpretation.json_sha256(source)
        mapping["anchorFirstStartSeconds"] = anchor["sourceUnits"][0]["start"]
        mapping["anchorLastEndSeconds"] = anchor["sourceUnits"][-1]["end"]
        return mapping, source

    def test_map_uses_derived_clip_zero_and_preserves_anchor_whitespace(self):
        self.assertEqual(self.mapping["schemaVersion"], subject.DERIVED_CLIP_SCHEMA)
        self.assertEqual(self.mapping["anchorOffsetSeconds"], 0)
        self.assertEqual(self.mapping["anchorOrigin"]["absoluteSourceStartSeconds"], 120.5)
        self.assertEqual(self.mapping["approvedWindowSeconds"], 10.0)
        self.assertEqual(self.mapping["clipDurationSeconds"], 10.0)
        self.assertEqual(self.validate(), 0.0)

    def test_rejects_changed_full_source_or_derived_clip_hash(self):
        self.source_media.write_bytes(b"changed-full-source")
        with self.assertRaisesRegex(ValueError, "full source media identity"):
            self.validate()
        # Restore the bound source; a changed clip still fails its independent digest.
        self.source_media.write_bytes(b"full-source-fixture")
        os.utime(self.source_media, ns=(self.source_media.stat().st_atime_ns,
                                       self.receipt["source"]["modifiedTimeNs"]))
        self.clip.write_bytes(b"changed-derived-clip")
        with self.assertRaisesRegex(ValueError, "clip media hash"):
            self.validate()

    def test_rejects_changed_extraction_receipt_hash_or_window(self):
        self.receipt_path.write_text(self.receipt_path.read_text() + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "receipt file hash"):
            self.validate()
        self.write_json(self.receipt_path, self.receipt)
        wrong_time = copy.deepcopy(self.receipt)
        wrong_time["startSeconds"] = 120.501
        self.write_json(self.receipt_path, wrong_time)
        mapping = copy.deepcopy(self.mapping)
        mapping["extractionReceipt"].update(
            sha256=subject.interpretation.sha256(self.receipt_path),
            jsonSha256=subject.interpretation.json_sha256(wrong_time))
        with self.assertRaisesRegex(ValueError, "receipt does not match source/window"):
            self.validate(mapping)

    def test_rejects_tampered_display_approved_window(self):
        mapping = copy.deepcopy(self.mapping)
        mapping["approvedWindow"]["startSeconds"] += 0.001
        with self.assertRaisesRegex(ValueError, "approved window is invalid"):
            self.validate(mapping)

    def test_full_source_identity_uses_bytes_not_copied_filesystem_mtime(self):
        receipt_bytes = self.receipt_path.read_bytes()
        receipt_sha = subject.interpretation.sha256(self.receipt_path)
        copied = self.root / "copied-source.mp4"
        copied.write_bytes(self.source_media.read_bytes())
        os.utime(copied, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
        mapping = copy.deepcopy(self.mapping)
        mapping["sourceMedia"]["path"] = str(copied)
        self.assertNotEqual(copied.stat().st_mtime_ns,
                            self.receipt["source"]["modifiedTimeNs"])
        self.assertEqual(self.validate(mapping), 0.0)
        self.assertEqual(self.receipt_path.read_bytes(), receipt_bytes)
        self.assertEqual(subject.interpretation.sha256(self.receipt_path), receipt_sha)

        wrong = self.root / "different-source.mp4"
        changed = bytearray(copied.read_bytes())
        changed[0] ^= 1
        wrong.write_bytes(changed)
        os.utime(wrong, ns=(copied.stat().st_atime_ns, copied.stat().st_mtime_ns))
        mapping["sourceMedia"]["path"] = str(wrong)
        with self.assertRaisesRegex(ValueError, "full source media identity"):
            self.validate(mapping)
        self.assertEqual(self.receipt_path.read_bytes(), receipt_bytes)
        self.assertEqual(subject.interpretation.sha256(self.receipt_path), receipt_sha)

    def test_rejects_changed_measured_duration_and_codec_padding_budget(self):
        mapping = copy.deepcopy(self.mapping)
        mapping["clipDurationSeconds"] += 0.01
        with self.assertRaisesRegex(ValueError, "measured audio duration"):
            self.validate(mapping)
        excessive = copy.deepcopy(self.probe)
        excessive["containerPaddingSamples"] = 4097
        excessive["paddingBudgetSamples"] = 4097
        mapping = copy.deepcopy(self.mapping)
        mapping["clipMediaProbe"] = excessive
        with mock.patch.object(subject, "media_duration", return_value=240.0), \
             mock.patch.object(subject, "probe_derived_audio", return_value=self.probe):
            with self.assertRaises(ValueError):
                subject.validate(mapping, self.source, self.anchor)

    def test_rejects_wrong_anchor_origin_and_anchor_beyond_approved_window(self):
        wrong_origin = copy.deepcopy(self.mapping)
        wrong_origin["anchorOrigin"]["absoluteSourceStartSeconds"] = 120.51
        with self.assertRaisesRegex(ValueError, "anchor origin"):
            self.validate(wrong_origin)
        outside = copy.deepcopy(self.anchor)
        outside["sourceUnits"][-1]["end"] = 10.001
        mapping, source = self.rebind_anchor(outside)
        with self.assertRaisesRegex(ValueError, "outside or disordered"):
            self.validate(mapping, source, outside)

    def test_v3_requires_both_real_source_and_extraction_receipt_inputs(self):
        with self.assertRaisesRegex(ValueError, "both --source-media"):
            subject.prepare(self.source_path, self.anchor_path, self.clip, None,
                            self.root / "missing-map.json", source_media_path=self.source_media)


if __name__ == "__main__":
    unittest.main()
