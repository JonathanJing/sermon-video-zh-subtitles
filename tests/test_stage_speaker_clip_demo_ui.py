import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import stage_speaker_clip_demo_ui as demo


class StageSpeakerClipUI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.base = self.root / "base"
        self.public = self.base / "public"
        self.public.mkdir(parents=True)
        (self.base / "firebase.json").write_text('{"hosting":{"public":"public","site":"fixture"}}')
        (self.public / "weekly.json").write_text('{"fixture":"unchanged"}')
        (self.public / "icons.mjs").write_text("// preserved existing icons")
        (self.public / "icons.svg").write_text("<svg></svg>")
        self.clips = self.root / "clips"
        self.clips.mkdir()
        text = "Synthetic English fixture."
        english_hash = hashlib.sha256(text.encode()).hexdigest()
        speakers = []
        for index in range(6):
            sid = f"speaker_{index}"
            clip = f"clip-{index}"
            folder = self.clips / sid
            folder.mkdir()
            def asset(name):
                data = (sid + name).encode()
                (folder / name).write_bytes(data)
                return {"path": f"/{demo.PREFIX}/{sid}/{name}", "sha256": hashlib.sha256(data).hexdigest(),
                        "bytes": len(data), "durationSeconds": 12, "sourceClipId": clip,
                        "englishTextSha256": english_hash}
            speakers.append({"speakerId": sid, "displayName": sid, "clipId": clip,
                             "source": {"url": "https://example.org/source", "startSeconds": 120, "endSeconds": 132,
                                        "englishTextSha256": english_hash},
                             "original": {**asset("en.mp3"), "locale": "en", "text": text,
                                          "transcriptStatus": "machine_screening_only"},
                             "video": asset("en.mp4"),
                             "samples": [{**asset(locale + ".mp3"), "locale": locale, "text": "Fixture text",
                                          "humanListeningStatus": "pending"} for locale in ["zh-Hans", "ko", "es"]]})
        self.catalog = {"schemaVersion": "sermon-speaker-clip-demo-catalog-v2", "status": "audition_demo",
                        "sourceScope": "source_clip_translation_audition_not_sermon_release",
                        "humanListeningStatus": "pending", "speakerCount": 6, "sampleCount": 18, "speakers": speakers}
        (self.clips / "catalog.json").write_text(json.dumps(self.catalog))
        self.metadata = json.dumps({"format": {"duration": "12"}, "streams": [{"codec_type": "audio"}, {"codec_type": "video"}]})

    def tearDown(self):
        self.temp.cleanup()

    def test_both_readers_receive_identical_catalog_and_media_without_changing_weekly(self):
        for reader, marker in [("dev", 'id="moreOptions"'), ("production", 'id="voice-grid"')]:
            (self.public / "index.html").write_text(f"<html><head></head><body><div {marker}></div></body></html>")
            out = self.root / reader
            with patch.object(demo.subprocess, "check_output", return_value=self.metadata):
                report = demo.stage(self.base, self.clips, reader, out)
                demo.verify(out)
            self.assertEqual(report["status"], "validated_not_deployed")
            self.assertEqual((out / "public/weekly.json").read_bytes(), (self.public / "weekly.json").read_bytes())
            self.assertEqual((out / "public" / demo.PREFIX / "catalog.json").read_bytes(), (self.clips / "catalog.json").read_bytes())
            for speaker in self.catalog["speakers"]:
                for asset in [speaker["original"], speaker["video"], *speaker["samples"]]:
                    self.assertEqual(demo.digest(out / "public" / asset["path"].lstrip("/")), asset["sha256"])
            self.assertEqual(len(report["addedFiles"]), 34)
            self.assertEqual(report["modifiedFiles"], ["index.html"])

    def test_invalid_media_or_incomplete_binding_is_rejected_before_output_exists(self):
        (self.public / "index.html").write_text('<html><head></head><body><div id="moreOptions"></div></body></html>')
        (self.clips / "speaker_0/en.mp3").write_bytes(b"changed")
        with patch.object(demo.subprocess, "check_output", return_value=self.metadata):
            with self.assertRaises(ValueError):
                demo.stage(self.base, self.clips, "dev", self.root / "out")
        self.assertFalse((self.root / "out").exists())

    def test_existing_outputs_and_nested_baseline_outputs_are_rejected(self):
        with self.assertRaises(ValueError):
            demo.stage(self.base, self.clips, "dev", self.base / "nested")
        with self.assertRaises(ValueError):
            demo.stage(self.base, self.clips, "dev", self.base)


if __name__ == "__main__":
    unittest.main()
