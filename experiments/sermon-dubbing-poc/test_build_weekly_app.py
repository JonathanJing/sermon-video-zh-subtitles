"""App export uses frozen candidates; no models, network, or deployment."""
import contextlib
import io
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch

import build_weekly_app as app
from check_weekly_timing import budgets
from poc import sha256, write_json
from render_weekly_audio import render_identity
import run_weekly_dubbing as runner
from server import load_weekly
from test_resume_integrity import candidate_fixture, modify, snapshot
from weekly_dubbing import read


def app_fixture(root):
    work = root / "weekly"
    work.mkdir()
    candidate_fixture(work)
    notes = {"status": "ready", "sermonDate": "2026-09-06", "centralMessageZh": "中心信息", "summaryZh": "证道摘要",
        "outlineZh": [{"title": "主题大纲", "points": ["第一点"], "sourceSliceIndexes": [0]}], "scriptureRefs": [], "reflectionQuestionsZh": []}
    write_json(work / "outline.json", notes)
    job = read(work / "job.json")
    job.update(sourceId="weekly-fixture", sourceUrl="https://example.invalid/sermon", title="本周证道", speaker="Eric Geiger", scripture="诗篇 137 篇",
        inheritedReview={"generationComplete": False})
    job["inputs"]["outline"] = {"path": str(work / "outline.json"), "sha256": sha256(work / "outline.json")}
    write_json(work / "job.json", job)
    identity = render_identity(work / "job.json", job["voice"]["checkpointSha256"])
    write_json(work / "render/identity.json", identity)
    modify(work, "render/report.json", lambda data: data.update(identity))
    for i in range(2):
        modify(work, f"render/unit-{i:04d}.json", lambda data: data.update(identity=identity))
    for path in ["assembly-report.json", "audio-review.json", "source-alignment/report.json", "audio/asr-screening.json", "synchronization/report.json"]:
        modify(work, path, lambda data: data.update(jobSha256=identity["jobSha256"]))
    modify(work, "audio/library.json", lambda data: data["tracks"][0].update(label="整篇待审", voiceLabel="Eric Geiger · 训练音色", scope="full_candidate", audioUrl="/media/zh-natural.mp3"))
    alignment_path = work / "source-alignment/report.json"
    model_path = work / "source-alignment/anchor-model-review.json"
    write_json(model_path, {"schemaVersion": "sermon-anchor-model-review-v1", "reviewType": "model", "model": "gpt-6-astra", "humanApproval": False,
        "status": "approved_for_candidate_alignment", "reviewedBy": "fixture-model-review", "reviewedAt": "2026-09-05T00:00:00Z",
        "jobSha256": identity["jobSha256"], "sourceAudioSha256": job["inputs"]["sourceAudio"]["sha256"], "alignmentSha256": sha256(alignment_path),
        "unresolvedBoundaryIssues": [], "evidence": [job["inputs"]["sourceAudio"]],
        "blocks": [{"blockId": 0, "start": 0, "end": 4, "status": "model_supported", "reason": "Frozen acoustic fixture"}]})
    modify(work, "synchronization/report.json", lambda data: data.update(alignmentSha256=sha256(alignment_path), anchorReviewSha256=sha256(model_path), anchorReviewType="model"))
    render, timing = read(work / "render/report.json"), read(work / "synchronization/report.json")
    cues = [{**cue, "start": cue["start"] - row["chineseStart"] + row["videoStart"], "end": cue["end"] - row["chineseStart"] + row["videoStart"]}
        for row in timing["blocks"] for cue in render["cues"] if cue["blockId"] == row["blockId"]]
    (work / "synchronization/zh-synced.mp3").write_bytes(b"synchronized MP3 fixture")
    write_json(work / "synchronization/assembly.json", {"status": "synchronized_candidate", "jobSha256": identity["jobSha256"],
        "timingReportSha256": sha256(work / "synchronization/report.json"), "sourceNaturalMp3Sha256": sha256(work / "audio/zh-natural.mp3"),
        "sourceNaturalWavSha256": sha256(work / "render/chinese.raw.wav"), "sha256": sha256(work / "synchronization/zh-synced.mp3"),
        "fullDecode": "pass", "durationSeconds": 10.032, "cues": cues, "humanReview": "pending"})
    write_json(work / "audio-review-synced.json", {**read(work / "audio-review.json"), "mp3Sha256": sha256(work / "synchronization/zh-synced.mp3"),
        "reviewedBy": None, "reviewedAt": None, "humanApproval": False})
    return work


class WeeklyAppBuildTests(unittest.TestCase):
    def setUp(self):
        no_subprocess = patch.object(runner.subprocess, "run", side_effect=AssertionError("No subprocess / models / network"))
        no_subprocess.start()
        self.addCleanup(no_subprocess.stop)

    def build(self, root, work, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return app.build(root / "missing-comparison", root / "build", weekly_jobs=[work], **kwargs)

    def test_weekly_job_is_independent_of_historical_samples_and_outlines(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = app_fixture(root)
            before = snapshot(work)
            with patch.object(app, "ROOT", root / "missing-historical-root"), patch.object(app, "load_library", wraps=app.load_library) as load:
                report = self.build(root, work, review_preview=True, expansion=root / "missing-expansion")
            self.assertEqual([call.args[0] for call in load.call_args_list], [work / "audio"])
            catalog = load_weekly(root / "build/public")
            self.assertEqual(report["weeks"], 1)
            self.assertEqual(catalog["defaultWeekId"], "2026-09-06")
            self.assertEqual([w["id"] for w in catalog["weeks"]], ["2026-09-06"])
            track = catalog["weeks"][0]["tracks"][0]
            self.assertEqual(track["sha256"], sha256(work / "audio/zh-natural.mp3"))
            self.assertEqual(track["subtitleTiming"], "measured_synthesis_groups")
            self.assertEqual(snapshot(work), before)

    def test_legacy_build_without_weekly_job_keeps_both_examples(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = app_fixture(root)
            entries = [{"date": date, "sourceId": f"fixture-{i}", "title": "历史证道", "scripture": "诗篇 137 篇", "speaker": "Eric", "number": "137"}
                for i, date in enumerate(["2026-09-06", "2026-08-30"])]
            for entry in entries:
                path = root / f'artifacts/post-live-runs/{entry["date"]}/sermon_{entry["sourceId"]}/pipeline/sermon-interpretation/insights/openai-notes.json'
                write_json(path, {**read(work / "outline.json"), "sermonDate": entry["date"]})
            with patch.object(app, "ROOT", root), patch.object(app, "WEEKS", entries), contextlib.redirect_stdout(io.StringIO()):
                report = app.build(work / "audio", root / "build")
            catalog = load_weekly(root / "build/public")
            self.assertEqual(report["weeks"], 2)
            self.assertEqual(report["playableWeeks"], 1)
            self.assertEqual(catalog["defaultWeekId"], "2026-09-06")
            self.assertEqual(catalog["weeks"][1]["tracks"], [])

    def test_sync_preview_exports_verified_sync_audio_and_remains_a_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = app_fixture(root)
            before = snapshot(work)
            with patch("weekly_dubbing.validate_review", side_effect=AssertionError("No human approval in preview")):
                self.build(root, work, review_preview=True, sync_preview=True)
            week = load_weekly(root / "build/public")["weeks"][0]
            track = week["tracks"][0]
            assembled = read(work / "synchronization/assembly.json")
            self.assertEqual(track["sha256"], assembled["sha256"])
            self.assertEqual(track["cues"], assembled["cues"])
            self.assertEqual(track["cues"][1]["start"], 5)
            self.assertEqual(track["durationSeconds"], 10)
            self.assertEqual(track["subtitleTiming"], "source_video_aligned_candidate")
            self.assertEqual((root / "build/public/media" / track["file"]).read_bytes(), b"synchronized MP3 fixture")
            self.assertEqual(len(list((root / "build/public/media").iterdir())), 1)
            self.assertEqual(week["audioStatus"], "full_candidate")
            self.assertEqual(track["scope"], "full_candidate")
            self.assertFalse(week["humanApproval"])
            self.assertEqual(week["videoSynchronization"], "candidate_aligned")
            for phrase in ["同步试播", "模型审核不等于人工验收", "仍待现场试听"]:
                self.assertIn(phrase, week["audioNotice"])
            self.assertEqual(week["productionStages"][-1]["status"], "pending")
            self.assertEqual(week["candidateEvidence"]["syncAssemblySha256"], sha256(work / "synchronization/assembly.json"))
            self.assertEqual(snapshot(work), before)

    def test_include_history_keeps_three_old_auditions_and_replaces_matching_week(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = app_fixture(root)
            entries = [{"date": date, "sourceId": f"fixture-{i}", "title": "历史证道", "scripture": "诗篇 137 篇", "speaker": "Eric", "number": "137"}
                for i, date in enumerate(["2026-09-06", "2026-08-23"])]
            for entry in entries:
                path = root / f'artifacts/post-live-runs/{entry["date"]}/sermon_{entry["sourceId"]}/pipeline/sermon-interpretation/insights/openai-notes.json'
                write_json(path, {**read(work / "outline.json"), "sermonDate": entry["date"]})
            for name, identifiers in [("comparison", ["accepted", "default", "flow"]), ("expansion", ["expanded"])]:
                pack = root / name
                pack.mkdir()
                tracks = []
                for identifier in identifiers:
                    audio = pack / f"{identifier}.mp3"
                    audio.write_bytes(identifier.encode())
                    tracks.append({**read(work / "audio/library.json")["tracks"][0], "id": identifier, "file": audio.name,
                        "audioUrl": f"/media/{audio.name}", "sha256": sha256(audio)})
                write_json(pack / "library.json", {"schemaVersion": "sermon-audio-library-v1", "date": "2026-08-23", "tracks": tracks})
            with patch.object(app, "ROOT", root), patch.object(app, "WEEKS", entries), patch.object(app, "write_json", wraps=write_json) as write, contextlib.redirect_stdout(io.StringIO()):
                report = app.build(root / "comparison", root / "build", expansion=root / "expansion", weekly_jobs=[work],
                    review_preview=True, sync_preview=True, include_history=True)
            catalog = load_weekly(root / "build/public")
            self.assertEqual([week["id"] for week in catalog["weeks"]], ["2026-09-06", "2026-08-23"])
            self.assertEqual(catalog["weeks"][0]["title"], "本周证道")
            self.assertEqual(catalog["weeks"][0]["tracks"][0]["sha256"], sha256(work / "synchronization/zh-synced.mp3"))
            old = catalog["weeks"][1]
            self.assertEqual(old["title"], "历史证道")
            self.assertEqual(old["outline"][0]["title"], "主题大纲")
            self.assertEqual([track["id"] for track in old["tracks"]], ["accepted", "expanded", "default"])
            self.assertTrue(report["includeHistory"])
            self.assertEqual(sum(call.args[0] == root / "build/build-report.json" for call in write.call_args_list), 1)

    def test_sync_preview_requires_both_flags_and_a_weekly_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for kwargs in [{"weekly_jobs": [root / "missing"]}, {"review_preview": True}]:
                with self.subTest(kwargs=kwargs), self.assertRaisesRegex(ValueError, "requires --review-preview"):
                    app.build(root / "missing", root / "build", sync_preview=True, **kwargs)
                self.assertFalse((root / "build").exists())
            with patch.object(sys, "argv", [str(app.__file__), "--sync-preview"]), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
                runpy.run_path(str(app.__file__), run_name="__main__")
            self.assertEqual(exc.exception.code, 2)

    def test_reviewed_playback_lead_uses_video_start_without_changing_source_anchor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = app_fixture(root)
            job, render = read(work / "job.json"), read(work / "render/report.json")
            alignment = read(work / "source-alignment/report.json")
            review_path = work / "synchronization/placement-model-review.json"
            write_json(review_path, {"schemaVersion": "sermon-playback-placement-review-v1", "reviewType": "model", "model": "gpt-6-astra", "humanApproval": False,
                "status": "approved_for_candidate_playback", "reviewedBy": "fixture-model-review", "reviewedAt": "2026-09-05T00:00:00Z",
                "jobSha256": sha256(work / "job.json"), "renderSha256": sha256(work / "render/report.json"),
                "alignmentSha256": sha256(work / "source-alignment/report.json"), "sourceAudioSha256": job["inputs"]["sourceAudio"]["sha256"],
                "unresolvedPlacementIssues": [], "evidence": [job["inputs"]["sourceAudio"]],
                "blocks": [{"blockId": 1, "sourceAnchorStart": 5, "playbackStart": 4.5, "status": "model_supported", "reason": "Frozen playback fixture"}]})
            rows, failures = budgets(job["blocks"], alignment["blocks"], render["cues"], 10, {1: 4.5})
            modify(work, "synchronization/report.json", lambda d: d.update(blocks=rows, failures=failures, placementReviewSha256=sha256(review_path)))
            modify(work, "synchronization/assembly.json", lambda d: d.update(timingReportSha256=sha256(work / "synchronization/report.json"),
                cues=[d["cues"][0], {**d["cues"][1], "start": 4.5, "end": 6.5}]))
            before = snapshot(work)
            report = self.build(root, work, review_preview=True, sync_preview=True)
            track = load_weekly(root / "build/public")["weeks"][0]["tracks"][0]
            self.assertEqual(track["cues"][1]["start"], 4.5)
            self.assertEqual(read(work / "source-alignment/report.json")["blocks"][1]["start"], 5)
            self.assertTrue(report["syncPreview"])
            self.assertEqual(snapshot(work), before)

    def test_replaced_sync_receipts_audio_and_subtitles_cannot_be_exported(self):
        changes = [
            lambda w: modify(w, "synchronization/assembly.json", lambda d: d.update(jobSha256="changed")),
            lambda w: modify(w, "synchronization/assembly.json", lambda d: d.update(timingReportSha256="changed")),
            lambda w: modify(w, "synchronization/assembly.json", lambda d: d.update(sourceNaturalMp3Sha256="changed")),
            lambda w: modify(w, "synchronization/assembly.json", lambda d: d.update(sourceNaturalWavSha256="changed")),
            lambda w: modify(w, "synchronization/assembly.json", lambda d: d.update(fullDecode="failed")),
            lambda w: modify(w, "synchronization/assembly.json", lambda d: d.update(durationSeconds=9)),
            lambda w: modify(w, "synchronization/assembly.json", lambda d: d["cues"][1].update(start=4.5)),
            lambda w: modify(w, "synchronization/assembly.json", lambda d: d["cues"][0].update(text="改了字幕")),
            lambda w: (w / "synchronization/zh-synced.mp3").write_bytes(b"changed MP3"),
            lambda w: (w / "synchronization/assembly.json").unlink(),
        ]
        for i, change in enumerate(changes):
            with self.subTest(case=i), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                work = app_fixture(root)
                change(work)
                before = snapshot(work)
                with self.assertRaises(ValueError):
                    self.build(root, work, review_preview=True, sync_preview=True)
                self.assertFalse((root / "build/public/weekly.json").exists())
                self.assertEqual(list((root / "build/public/media").iterdir()), [])
                self.assertEqual(snapshot(work), before)

    def test_shared_validator_rejects_changed_source_render_review_or_screening(self):
        changes = [lambda w: (w / "source.wav").write_bytes(b"changed source"),
            lambda w: (w / "render/chinese.raw.wav").write_bytes(b"changed WAV"),
            lambda w: modify(w, "source-alignment/anchor-model-review.json", lambda d: d.update(humanApproval=True)),
            lambda w: modify(w, "audio/asr-screening.json", lambda d: d.update(jobSha256="changed"))]
        for i, change in enumerate(changes):
            with self.subTest(case=i), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                work = app_fixture(root)
                change(work)
                with self.assertRaises(ValueError):
                    self.build(root, work, review_preview=True, sync_preview=True)
                self.assertFalse((root / "build/public/weekly.json").exists())

    def test_valid_candidate_with_timing_failures_is_not_a_sync_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = app_fixture(root)
            (work / "source-alignment/anchor-model-review.json").unlink()
            anchors = [{"blockId": 0, "start": 0, "end": 1, "issues": []}, {"blockId": 1, "start": 1, "end": 9, "issues": []}]
            modify(work, "source-alignment/report.json", lambda d: d.update(blocks=anchors))
            rows, failures = budgets(read(work / "job.json")["blocks"], anchors, read(work / "render/report.json")["cues"], 10)
            modify(work, "synchronization/report.json", lambda d: d.update(blocks=rows, failures=failures, status="needs_timing_review",
                alignmentSha256=sha256(work / "source-alignment/report.json"), anchorReviewSha256=None))
            modify(work, "synchronization/assembly.json", lambda d: d.update(timingReportSha256=sha256(work / "synchronization/report.json")))
            self.assertTrue(runner.validate_candidate(work))
            with self.assertRaisesRegex(ValueError, "Timing still has unresolved failures"):
                self.build(root, work, review_preview=True, sync_preview=True)

    def test_model_review_cannot_replace_the_formal_human_release_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = app_fixture(root)
            with self.assertRaisesRegex(ValueError, "Human audio review is not complete"):
                self.build(root, work)
            self.assertFalse((root / "build/public/weekly.json").exists())


if __name__ == "__main__":
    unittest.main()
