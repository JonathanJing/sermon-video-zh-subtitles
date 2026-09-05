import copy
import json
from pathlib import Path
import tempfile
import unittest

from build_weekly_app import validate_catalog
from run_qwen_training_smoke import sha256, validate_inputs
from server import load_weekly


class WeeklyTests(unittest.TestCase):
    def fixture(self):
        return {"schemaVersion": "sermon-weekly-catalog-v1", "defaultWeekId": "2026-08-23", "weeks": [
            {"id": "2026-08-23", "title": "主题", "speaker": "Eric", "outline": [{"title": "大纲"}], "tracks": [
                {"id": "a", "file": "a.mp3", "audioUrl": "/media/a.mp3", "durationSeconds": 20, "cues": [{"start": 0, "end": 20, "text": "中文"}]}]},
            {"id": "2026-08-30", "title": "下一周", "speaker": "待核对", "outline": [{"title": "另一份大纲"}], "tracks": []}]}

    def test_pending_week_is_valid_but_missing_audio_is_not(self):
        catalog = self.fixture()
        validate_catalog(catalog)
        with tempfile.TemporaryDirectory() as tmp:
            pack = Path(tmp)
            (pack / "weekly.json").write_text(json.dumps(catalog))
            with self.assertRaises(ValueError):
                load_weekly(pack)
            (pack / "media").mkdir()
            (pack / "media/a.mp3").write_bytes(b"fixture")
            self.assertEqual(len(load_weekly(pack)["weeks"]), 2)

    def test_subtitle_overrun_and_escape_fail(self):
        for change in [lambda t: t.update(file="../private.mp3"), lambda t: t["cues"][0].update(end=21)]:
            catalog = self.fixture()
            change(catalog["weeks"][0]["tracks"][0])
            with self.assertRaises(ValueError):
                validate_catalog(catalog)


class ExpansionProtectionTests(unittest.TestCase):
    def test_dev_audio_cannot_be_admitted_by_an_expansion_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            (work / "sample.wav").write_bytes(b"sample")
            digest = sha256(work / "sample.wav")
            protection = {"protectedIds": ["reserved"], "protectedDates": ["20260101"]}
            (work / "protection.json").write_text(json.dumps(protection))
            sources = [{"sourceId": f"s{i}", "sha256": digest, "speaker": "Eric Geiger", "split": "train", "date": f"2026020{i + 1}"} for i in range(3)]
            authorization = {"status": "confirmed_by_user", "purposes": ["voice_training"], "sources": [{"sourceId": "ZDQwL3K-A44", "sha256": digest}] + sources}
            (work / "authorization.json").write_text(json.dumps(authorization))
            manifest = {"schemaVersion": "sermon-voice-multisource-training-v1", "purpose": "engineering_multisermon_training", "productionTrainingAdmission": False,
                "sourceId": "ZDQwL3K-A44", "sourceSha256": digest, "protectedEvaluationOverlap": False, "sources": sources, "protectionSha256": sha256(work / "protection.json"),
                "sampleSeconds": 5, "samples": [{"file": "sample.wav", "sha256": digest, "text": "English.", "language": "English", "durationSeconds": 5, "sourceId": "s0", "sourceSha256": digest, "split": "train", "speaker": "Eric Geiger"}],
                "reference": {"file": "sample.wav", "sha256": digest}}
            (work / "research-inputs.json").write_text(json.dumps(manifest))
            self.assertEqual(len(validate_inputs(work)["samples"]), 1)
            for field, value in [("split", "dev"), ("sourceId", "reserved"), ("date", "20260101"), ("speaker", "Another speaker")]:
                bad = copy.deepcopy(manifest)
                bad["sources"][0][field] = value
                (work / "research-inputs.json").write_text(json.dumps(bad))
                with self.subTest(field=field), self.assertRaises(ValueError):
                    validate_inputs(work)


if __name__ == '__main__':
    unittest.main()
