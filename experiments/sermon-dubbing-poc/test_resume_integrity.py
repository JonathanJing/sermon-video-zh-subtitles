"""Resume regressions use fake media; subprocess/model/SSH work is forbidden."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from check_weekly_timing import budgets
from poc import sha256, write_json
from prepare_voice_candidates import ASR, ALIGNER
from render_weekly_audio import render_identity
import run_weekly_dubbing as runner
from scripts import sermon_accounting as accounting
from weekly_dubbing import read


def candidate_fixture(work):
    source = work / "source.wav"
    source.write_bytes(b"original audio fixture")
    job = {"schemaVersion": "sermon-weekly-dubbing-job-v1", "week": "2026-09-06", "sourceStartSeconds": 100, "sourceDurationSeconds": 10,
        "inputs": {"sourceAudio": {"path": str(source), "sha256": sha256(source)}}, "voice": {"checkpointSha256": "fixture-checkpoint"},
        "blocks": [{"id": 0, "en": "First English sentence.", "zh": "第一句。"}, {"id": 1, "en": "Second English sentence.", "zh": "第二句。"}],
        "units": [{"id": 0, "blockId": 0, "text": "第一句。", "gapAfterSeconds": .45}, {"id": 1, "blockId": 1, "text": "第二句。", "gapAfterSeconds": .45}]}
    write_json(work / "job.json", job)
    identity = render_identity(work / "job.json", job["voice"]["checkpointSha256"])
    write_json(work / "render/identity.json", identity)
    cues = []
    for i, unit in enumerate(job["units"]):
        raw = work / f"render/unit-{i:04d}.wav"
        raw.write_bytes(f"fake unit {i}".encode())
        write_json(raw.with_suffix(".json"), {"unit": unit, "identity": identity, "sha256": sha256(raw), "durationSeconds": 2})
        cues.append({"unitId": i, "blockId": i, "text": unit["text"], "start": i * 2.45, "end": i * 2.45 + 2})
        write_json(work / f"audio/unit-screening/unit-{i:04d}.json", {"unitId": i, "blockId": i,
            "identity": {"audioSha256": sha256(raw), "expected": unit["text"], "model": ASR[0], "revision": ASR[1]},
            "recognized": unit["text"], "similarity": 1, "differences": []})
    (work / "render/chinese.raw.wav").write_bytes(b"assembled raw fixture")
    render = {**identity, "status": "complete_candidate_render", "sha256": sha256(work / "render/chinese.raw.wav"), "durationSeconds": 4.45, "cues": cues}
    write_json(work / "render/report.json", render)
    (work / "audio/zh-natural.mp3").write_bytes(b"encoded MP3 fixture")
    digest = sha256(work / "audio/zh-natural.mp3")
    track = {"id": "full_candidate", "file": "zh-natural.mp3", "sha256": digest, "durationSeconds": 4.45,
        "cues": [{k: c[k] for k in ["start", "end", "text", "blockId"]} for c in cues]}
    write_json(work / "audio/library.json", {"schemaVersion": "sermon-audio-library-v1", "date": job["week"], "tracks": [track]})
    write_json(work / "assembly-report.json", {"jobSha256": identity["jobSha256"], "sha256": digest, "durationSeconds": 4.48, "fullDecode": "pass"})
    write_json(work / "audio-review.json", {"jobSha256": identity["jobSha256"], "mp3Sha256": digest, "checkpointSha256": "fixture-checkpoint", "humanApproval": False})
    anchors = [{"blockId": 0, "start": 0, "end": 4, "issues": []}, {"blockId": 1, "start": 5, "end": 9, "issues": []}]
    write_json(work / "source-alignment/report.json", {"schemaVersion": "sermon-acoustic-anchors-v1", "jobSha256": identity["jobSha256"],
        "sourceAudioSha256": sha256(source), "timeOrigin": "approved_sermon_clip_start", "fullVideoOffsetSeconds": 100, "blocks": anchors, "asr": ASR, "aligner": ALIGNER})
    write_json(work / "audio/asr-screening.json", {"status": "machine_screening_only", "jobSha256": identity["jobSha256"], "model": ASR[0], "revision": ASR[1],
        "results": [{"id": "full_candidate", "sha256": digest, "durationSeconds": 4.45, "fullDecode": "pass", "screenedUnits": 2, "expectedUnits": 2, "reviewCandidates": []}]})
    rows, failures = budgets(job["blocks"], anchors, cues, 10)
    write_json(work / "synchronization/report.json", {"schemaVersion": "sermon-video-sync-budget-v1", "jobSha256": identity["jobSha256"],
        "alignmentSha256": sha256(work / "source-alignment/report.json"), "anchorReviewSha256": None, "sourceVideoOffsetSeconds": 100, "durationSeconds": 10,
        "status": "natural_timing_fits", "blocks": rows, "failures": failures})
    return work


def snapshot(work):
    return {str(p.relative_to(work)): sha256(p) for p in work.rglob("*")
            if p.is_file() and p.relative_to(work).parts[0] != "accounting"}


def modify(work, path, change):
    data = read(work / path)
    change(data)
    write_json(work / path, data)


class ResumeIntegrityTests(unittest.TestCase):
    def setUp(self):
        # Shared accounting tests cover its read-only Git probe separately.
        # Keep this suite's no-SSH/no-model subprocess assertions strict.
        identity = patch.object(accounting, "execution_identity", return_value={"gitCommit": None})
        identity.start()
        self.addCleanup(identity.stop)

    def run_main(self, work):
        argv = ["run_weekly_dubbing.py", "--work", str(work), "--remote-checkpoint", runner.REMOTE_ROOT + "/sermon-fixture/checkpoint"]
        with patch.object(runner.sys, "argv", argv):
            runner.main()

    def assert_preserved_rejection(self, work, pattern):
        before = snapshot(work)
        with patch.object(runner.subprocess, "run", side_effect=AssertionError("No subprocess on stale cache")) as call, patch.object(runner, "assemble") as assemble:
            with self.assertRaisesRegex(ValueError, pattern):
                self.run_main(work)
            call.assert_not_called()
            assemble.assert_not_called()
        self.assertEqual(snapshot(work), before)

    def test_complete_cache_is_read_only_and_runner_does_no_remote_or_model_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = candidate_fixture(Path(tmp))
            before = snapshot(work)
            with patch.object(runner.subprocess, "run", side_effect=AssertionError("No subprocess")), patch.object(runner, "assemble", side_effect=AssertionError("No assembly")):
                evidence = runner.validate_candidate(work)
                self.assertEqual(snapshot(work), before)
                self.run_main(work)
            after = snapshot(work)
            after.pop("workflow-receipt.json")
            self.assertEqual(after, before)
            self.assertEqual(evidence["mp3Sha256"], sha256(work / "audio/zh-natural.mp3"))
            self.assertEqual(read(work / "workflow-receipt.json")["humanAudioReview"], "pending")

    def test_missing_job_or_frozen_source_has_consistent_read_only_failure(self):
        for missing in ["job.json", "source.wav"]:
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                work = candidate_fixture(Path(tmp))
                (work / missing).unlink()
                before = snapshot(work)
                with self.assertRaisesRegex(ValueError, "Job cache is incomplete"):
                    runner.validate_candidate(work)
                self.assertEqual(snapshot(work), before)

    def test_stale_or_unreceipted_natural_audio_never_reaches_models(self):
        changes = [
            lambda w: (w / "audio/zh-natural.mp3").write_bytes(b"replaced MP3"),
            lambda w: modify(w, "audio/library.json", lambda d: d.update(date="another-week")),
            lambda w: modify(w, "audio/library.json", lambda d: d["tracks"][0]["cues"][0].update(text="changed Chinese")),
            lambda w: modify(w, "assembly-report.json", lambda d: d.update(jobSha256="old-job")),
            lambda w: modify(w, "audio-review.json", lambda d: d.update(checkpointSha256="other-speaker")),
            lambda w: (w / "assembly-report.json").unlink(),
            lambda w: (w / "audio/library.json").unlink(),
            lambda w: (w / "audio-review.json").unlink(),
        ]
        for i, change in enumerate(changes):
            with self.subTest(case=i), tempfile.TemporaryDirectory() as tmp:
                work = candidate_fixture(Path(tmp))
                change(work)
                self.assert_preserved_rejection(work, "Natural audio")

    def test_missing_replaced_or_changed_render_receipts_fail_before_ssh(self):
        changes = [
            lambda w: (w / "render/unit-0000.json").unlink(),
            lambda w: (w / "render/unit-0000.wav").unlink(),
            lambda w: (w / "render/identity.json").unlink(),
            lambda w: (w / "render/report.json").unlink(),
            lambda w: (w / "render/chinese.raw.wav").write_bytes(b"replaced raw"),
            lambda w: modify(w, "render/unit-0000.json", lambda d: d["identity"].update(maxNewTokens=999)),
            lambda w: modify(w, "render/report.json", lambda d: d["cues"][0].update(end=3)),
        ]
        for i, change in enumerate(changes):
            with self.subTest(case=i), tempfile.TemporaryDirectory() as tmp:
                work = candidate_fixture(Path(tmp))
                change(work)
                self.assert_preserved_rejection(work, "Render")

    def test_alignment_source_model_and_timeline_changes_fail_closed(self):
        changes = [{"jobSha256": "old-job"}, {"sourceAudioSha256": "other-audio"}, {"asr": [ASR[0], "other-revision"]},
            {"aligner": [ALIGNER[0], "other-revision"]}, {"fullVideoOffsetSeconds": 20}, {"timeOrigin": "reading-layout"}]
        for change in changes:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                work = candidate_fixture(Path(tmp))
                modify(work, "source-alignment/report.json", lambda d: d.update(change))
                self.assert_preserved_rejection(work, "Source alignment")

    def test_new_changed_or_removed_anchor_review_invalidates_timing_cache(self):
        for mode in ["added", "changed", "removed"]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                work = candidate_fixture(Path(tmp))
                path = work / "source-alignment/anchor-review.json"
                write_json(path, {"alignmentSha256": sha256(work / "source-alignment/report.json"), "humanApproval": True,
                    "reviewedBy": "fixture reviewer", "reviewedAt": "2026-09-06T00:00:00Z", "blocks": []})
                if mode != "added":
                    modify(work, "synchronization/report.json", lambda d: d.update(anchorReviewSha256=sha256(path)))
                    if mode == "changed":
                        modify(work, "source-alignment/anchor-review.json", lambda d: d.update(reviewedAt="2026-09-07T00:00:00Z"))
                    else:
                        path.unlink()
                self.assert_preserved_rejection(work, "Timing")

    def test_screening_requires_current_audio_text_model_and_every_unit_receipt(self):
        changes = [
            lambda w: modify(w, "audio/asr-screening.json", lambda d: d.update(jobSha256="old-job")),
            lambda w: modify(w, "audio/asr-screening.json", lambda d: d.update(revision="old-model")),
            lambda w: modify(w, "audio/asr-screening.json", lambda d: d["results"][0].update(sha256="other-MP3")),
            lambda w: modify(w, "audio/asr-screening.json", lambda d: d["results"][0].update(screenedUnits=1)),
            lambda w: modify(w, "audio/asr-screening.json", lambda d: d["results"][0].update(reviewCandidates=[{"madeUp": True}])),
            lambda w: modify(w, "audio/unit-screening/unit-0000.json", lambda d: d["identity"].update(expected="old spoken text")),
            lambda w: modify(w, "audio/unit-screening/unit-0000.json", lambda d: d["identity"].update(audioSha256="other-WAV")),
            lambda w: (w / "audio/unit-screening/unit-0001.json").unlink(),
        ]
        for i, change in enumerate(changes):
            with self.subTest(case=i), tempfile.TemporaryDirectory() as tmp:
                work = candidate_fixture(Path(tmp))
                change(work)
                self.assert_preserved_rejection(work, "ASR screening")

    def test_timing_is_recomputed_from_current_anchors_and_audio_cues(self):
        changes = [lambda d: d.update(jobSha256="old-job"), lambda d: d.update(durationSeconds=11),
            lambda d: d.update(alignmentSha256="replaced-alignment"), lambda d: d["blocks"][0].update(naturalSeconds=1),
            lambda d: d.update(failures=[{"blockId": 0, "reason": "invented"}])]
        for i, change in enumerate(changes):
            with self.subTest(case=i), tempfile.TemporaryDirectory() as tmp:
                work = candidate_fixture(Path(tmp))
                modify(work, "synchronization/report.json", change)
                self.assert_preserved_rejection(work, "Timing")

    def test_missing_timing_runs_only_that_stage_and_validates_its_output(self):
        for writes_receipt in [True, False]:
            with self.subTest(writes_receipt=writes_receipt), tempfile.TemporaryDirectory() as tmp:
                work = candidate_fixture(Path(tmp))
                timing = read(work / "synchronization/report.json")
                (work / "synchronization/report.json").unlink()
                def finish_stage(command, **kwargs):
                    self.assertEqual(Path(command[1]).name, "check_weekly_timing.py")
                    if writes_receipt:
                        write_json(work / "synchronization/report.json", timing)
                with patch.object(runner.subprocess, "run", side_effect=finish_stage) as call:
                    if writes_receipt:
                        self.run_main(work)
                    else:
                        with self.assertRaisesRegex(ValueError, "Timing cache is incomplete"):
                            self.run_main(work)
                        self.assertFalse((work / "workflow-receipt.json").exists())
                    self.assertEqual(call.call_count, 1)

    def test_derivative_job_keeps_verified_unit_audio_and_asr_cache_reusable(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent, work = Path(tmp) / "parent", Path(tmp) / "derivative"
            parent.mkdir()
            work.mkdir()
            candidate_fixture(parent)
            candidate_fixture(work)
            old = read(parent / "render/unit-0000.json")
            modify(work, "render/unit-0000.json", lambda d: d.update(reusedFrom={"wavSha256": old["sha256"], "receiptSha256": sha256(parent / "render/unit-0000.json"), "generationIdentity": old["identity"]}))
            self.assertNotEqual(sha256(work / "job.json"), sha256(parent / "job.json"))
            self.assertEqual(read(work / "audio/unit-screening/unit-0000.json"), read(parent / "audio/unit-screening/unit-0000.json"))
            with patch.object(runner.subprocess, "run", side_effect=AssertionError("No model/SSH work")):
                runner.validate_candidate(work)
                self.run_main(work)

    def test_partial_acoustic_cache_needs_matching_source_and_wave_receipts(self):
        for mode in ["valid", "no_receipt", "changed_source", "missing_wave"]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                work = candidate_fixture(Path(tmp))
                (work / "source-alignment/report.json").unlink()
                (work / "synchronization/report.json").unlink()
                wav = work / "source-alignment/window-0000.wav"
                wav.write_bytes(b"acoustic window fixture")
                job = read(work / "job.json")
                write_json(wav.with_suffix(".asr.json"), {"identity": {"audioSha256": sha256(wav), "sourceSha256": job["inputs"]["sourceAudio"]["sha256"], "model": ASR[0], "revision": ASR[1]}, "text": "English"})
                if mode == "no_receipt":
                    wav.with_suffix(".asr.json").unlink()
                elif mode == "changed_source":
                    modify(work, "source-alignment/window-0000.asr.json", lambda d: d["identity"].update(sourceSha256="other-source"))
                elif mode == "missing_wave":
                    wav.unlink()
                if mode == "valid":
                    runner.validate_cached_stages(work, job)
                else:
                    self.assert_preserved_rejection(work, "Source alignment")


if __name__ == "__main__":
    unittest.main()
