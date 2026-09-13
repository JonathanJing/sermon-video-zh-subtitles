"""Model-free synthetic evidence for complete-service video windows."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import prepare_same_video as intake
import test_same_video as fixture
from poc import sha256, write_json
from weekly_dubbing import prepare, read, validate_frozen
from build_weekly_app import source_page


def window_probe(path):
    return {"durationSeconds": 10 if Path(path).name == "source_clip.m4a" else 30,
            "streams": [{"codec_type": "video"}, {"codec_type": "audio"}]}


def window_source(root):
    return {**fixture.same_source(root), "schemaVersion": intake.WINDOW_SOURCE_SCHEMA, "sermonOnly": False,
            "durationSeconds": 30, "sermonStartSeconds": 5, "sermonEndSeconds": 15,
            "canonicalURL": "https://www.marinerschurch.org/weekendlive/",
            "windowConfirmationReference": "Synthetic window; not real approval"}


class WindowSourceTests(unittest.TestCase):
    def test_v1_compatibility_and_v2_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = fixture.same_source(root)
            self.assertEqual(intake.validate_source(legacy, legacy["week"], media_probe=fixture.fake_probe)["schemaVersion"], intake.SOURCE_SCHEMA)
            source = window_source(root)
            self.assertEqual(intake.source_window(intake.validate_source(source, source["week"], media_probe=window_probe)), (5, 15))
            for change in [{"sermonStartSeconds": -1}, {"sermonEndSeconds": 31}, {"sermonEndSeconds": 5},
                           {"sermonStartSeconds": True}, {"sermonEndSeconds": float("nan")}, {"sameVersionConfirmed": False},
                           {"windowConfirmationReference": ""}, {"confirmationReference": ""}, {"sermonOnly": True},
                           {"schemaVersion": intake.SOURCE_SCHEMA}, {"sha256": "0" * 64}]:
                with self.subTest(change=change), self.assertRaises(ValueError):
                    intake.validate_source({**source, **change}, source["week"], media_probe=window_probe)

    def test_full_archive_clip_evidence_pdf_offset_and_job_binding(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(fixture.accounting, "execution_identity", return_value={"gitCommit": None}):
            root = Path(tmp)
            source = window_source(root)
            with patch.object(fixture, "same_source", return_value=source), patch.object(fixture, "fake_probe", side_effect=window_probe):
                _, run = fixture.reviewed_fixture(root, seal=False)
            plan = intake.production_plan(run, source, title="主题", speaker="Eric Geiger")
            command = plan["commands"][0]
            self.assertEqual(fixture.parse_timecode(command[command.index("--start-time") + 1]), 5)
            self.assertEqual(fixture.parse_timecode(command[command.index("--end-time") + 1]), 15)
            self.assertEqual(sha256(run / "source/video.mp4"), source["sha256"])
            summary = run / "pipeline/summary.json"
            write_json(summary, {**read(summary), "sourceDurationSeconds": 30, "sermonStartSeconds": 5, "sermonEndSeconds": 15})
            clip = run / "pipeline/source_clip.m4a.cache.json"
            write_json(clip, {**read(clip), "startSeconds": 5, "endSeconds": 15})
            notes = run / "pipeline/sermon-interpretation/insights/openai-notes.json"
            quality = read(run / "pipeline/reading-edition-v2/reading_quality_report.json")
            write_json(notes, {**read(notes), "seriesTerminology": quality["seriesTerminology"], "seriesZh": "启示录：耶稣带来的安慰与盼望"})
            rendered = []
            def render(command, **kwargs):
                rendered.append(command)
                return fixture.fake_pdf_render(command, **kwargs)
            receipt = intake.seal_reviewed(run, source, media_probe=window_probe, runner=render)
            self.assertEqual(receipt["schemaVersion"], "sermon-same-video-reviewed-handoff-v2")
            self.assertFalse(receipt["humanApproval"])
            self.assertEqual(float(rendered[0][rendered[0].index("--source-offset-seconds") + 1]), 5)
            self.assertEqual(rendered[0][rendered[0].index("--subtitle") + 1], "启示录：耶稣带来的安慰与盼望 · 中英对照阅读版")
            intake.validate_handoff(run, source, media_probe=window_probe)
            voice = root / "voice"
            write_json(voice / "research-inputs.json", {"speaker": "Eric Geiger"})
            write_json(voice / "training-report.json", {"status": "training_smoke_completed", "inputManifestSha256": sha256(voice / "research-inputs.json"),
                "checkpointSha256": "a" * 64, "baseModel": "fixture", "baseRevision": "fixture"})
            auth = root / "authorization.json"
            write_json(auth, {"schemaVersion": "sermon-voice-authorization-v1", "status": "confirmed_by_user", "statement": "Synthetic only",
                "purposes": ["chinese_dubbing"], "sources": [{"sourceId": source["sourceId"], "sha256": sha256(run / "pipeline/source_clip.m4a")}]})
            with patch("weekly_dubbing.probe", side_effect=window_probe):
                job = prepare(run, voice, root / "job", source["week"], "主题", "Eric Geiger", "启示录", auth, same_video_contract=run / intake.CONTRACT_NAME)
                self.assertEqual((job["sourceStartSeconds"], job["sourceEndSeconds"], job["sourceDurationSeconds"]), (5, 15, 10))
                self.assertEqual(job["humanAudioReview"], "pending")
                self.assertEqual(job["inheritedReview"]["humanWindow"], "explicit_source_contract")
                validate_frozen(job)
                for change in [{"sourceStartSeconds": 0}, {"sourceEndSeconds": 30}, {"sourceDurationSeconds": 30},
                               {"sameVideoContractVersion": intake.SOURCE_SCHEMA}, {"boundaryBasis": intake.BOUNDARY_BASIS}]:
                    with self.subTest(change=change), self.assertRaises(ValueError):
                        validate_frozen({**job, **change})
            page = source_page(job)
            self.assertEqual(page["sourceLabel"], "主日播放版")
            self.assertNotIn("YouTube", str(page))
            self.assertEqual(page["sourceOrigin"], "www.marinerschurch.org")
            self.assertEqual((page["sourceStartSeconds"], page["sourceEndSeconds"]), (5, 15))
            write_json(summary, {**read(summary), "sermonStartSeconds": 0})
            with self.assertRaises(ValueError):
                intake.validate_handoff(run, source, media_probe=window_probe)


if __name__ == "__main__":
    unittest.main()
