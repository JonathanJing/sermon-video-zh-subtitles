import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from scripts import render_sentence_interpretation_tts as render_subject
from scripts import screen_sentence_interpretation_tts as subject


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


class FakeModel:
    def generate(self, path, *, language, max_tokens):
        return SimpleNamespace(text="耶稣是得胜的君王。")


class RepresentativeTtsScreeningTests(unittest.TestCase):
    def test_screen_binds_audio_and_keeps_machine_only_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            job_path = root / "job.json"
            unit = {"id": 0, "blockId": "block-61", "translationGroupId": "g1",
                    "sourceUnitIds": ["u1"], "text": "耶稣是得胜的君王。", "gapAfterSeconds": 0.12}
            write_json(job_path, {
                "schemaVersion": "sermon-weekly-dubbing-job-v1",
                "purposeSchemaVersion": render_subject.JOB_SCHEMA,
                "units": [unit],
            })
            render = root / "render"
            render.mkdir()
            identity = {"jobSha256": render_subject.sha256(job_path)}
            write_json(render / "identity.json", identity)
            audio = render / "unit-0000.wav"
            audio.write_bytes(b"audio")
            write_json(audio.with_suffix(".json"), {
                "unit": unit, "identity": identity, "sha256": render_subject.sha256(audio),
            })
            report = subject.screen(job_path, render, root / "screen", [0], model_loader=FakeModel)
            self.assertEqual(report["status"], "representative_machine_screening_only")
            self.assertEqual(report["humanListeningReview"], "pending")
            self.assertEqual(report["results"][0]["similarity"], 1.0)
            self.assertEqual(report["results"][0]["differences"], [])

    def test_normalize_ignores_punctuation_and_case_only(self):
        self.assertEqual(subject.normalize("YouTube，耶稣！"), "youtube耶稣")


if __name__ == "__main__":
    unittest.main()
