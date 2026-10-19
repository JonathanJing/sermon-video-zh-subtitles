import json
from pathlib import Path
import tempfile
import unittest
import wave

from scripts import clip_timeline_map as subject
from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.source import sentence_interpretation as interpretation


def write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


class UnifiedSourceClipMapTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = self.root = Path(self.temporary.name)
        self.media = root / "audio-clean.flac"
        self.media.write_bytes(b"full recording bytes")
        media_sha = interpretation.sha256(self.media)
        self.report = write_json(root / "timeline-report.json", {
            "audioSha256": media_sha, "audioSizeBytes": self.media.stat().st_size,
            "mediaPath": str(self.media)})
        self.approval = write_json(root / "operator-window-approval.json", {
            "humanApproval": True, "status": "approved", "startTime": "00:00:10", "endTime": "00:00:14",
            "timelineReportSha256": interpretation.json_sha256(json.loads(self.report.read_text()))})
        self.clip = root / "source-clip.wav"
        with wave.open(str(self.clip), "wb") as handle:
            handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(16000)
            handle.writeframes(b"\0\0" * 16000 * 4)
        self.identity = write_json(root / "source-clip.identity.json", {
            "identity": {"mediaSha256": media_sha, "startSeconds": 10.0, "durationSeconds": 4},
            "sha256": interpretation.sha256(self.clip)})
        self.anchor = {"sourceUnits": [{"sourceUnitId": "u1", "start": 0.5, "end": 1.5},
                                       {"sourceUnitId": "u2", "start": 1.6, "end": 3.9}]}
        self.anchor_path = write_json(root / "anchor.json", self.anchor)
        self.source = {
            "anchors": {"artifact": {"jsonSha256": interpretation.json_sha256(self.anchor)}},
            "source": {"media": {"sha256": media_sha, "sizeBytes": self.media.stat().st_size,
                                 "durationSeconds": 100.0},
                       "approvedWindow": {"startSeconds": 10.0, "endSeconds": 14.0, "status": "approved",
                                          "humanApproval": True,
                                          "evidence": {"path": str(self.approval),
                                                       "sha256": interpretation.sha256(self.approval),
                                                       "jsonSha256": interpretation.json_sha256(
                                                           json.loads(self.approval.read_text()))}}}}
        self.source_path = write_json(root / "source.json", self.source)

    def build(self, name="map.json"):
        return subject.prepare_unified(self.source_path, self.anchor_path, self.clip, self.identity,
                                       self.report, self.root / name)

    def test_window_clip_binds_media_through_the_timeline_report(self):
        value = self.build()
        self.assertEqual(value["schemaVersion"], subject.UNIFIED_SOURCE_SCHEMA)
        self.assertEqual(value["clipDurationSeconds"], 4.0)
        self.assertEqual(subject.validate(value, self.source, self.anchor), 0.0)

    def test_report_for_other_media_is_rejected(self):
        write_json(self.report, {"audioSha256": "0" * 64, "audioSizeBytes": 1, "mediaPath": str(self.media)})
        with self.assertRaisesRegex(ValueError, "timeline report|media mismatch"):
            self.build()

    def test_clip_cut_from_another_start_is_rejected(self):
        identity = json.loads(self.identity.read_text())
        identity["identity"]["startSeconds"] = 11.0
        write_json(self.identity, identity)
        with self.assertRaisesRegex(ValueError, "clip identity mismatch"):
            self.build()

    def test_changed_clip_bytes_fail_later_validation(self):
        value = self.build()
        with wave.open(str(self.clip), "wb") as handle:
            handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(16000)
            handle.writeframes(b"\1\0" * 16000 * 4)
        with self.assertRaisesRegex(ValueError, "clip identity mismatch"):
            subject.validate(value, self.source, self.anchor)


if __name__ == "__main__":
    unittest.main()
