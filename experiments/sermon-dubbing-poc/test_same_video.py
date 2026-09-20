"""Synthetic same-video intake through the real candidate evidence validator.

Media probes, local PDF render commands and model-produced audio are fixtures;
no ASR, TTS, network, human approval or production artifact is created here.
"""
from pathlib import Path
import json
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import prepare_same_video as intake
import render_weekly_audio as renderer
from continue_saturday_dubbing import continue_saturday
from poc import sha256, write_json
from prepare_voice_candidates import ASR, ALIGNER
from run_weekly_dubbing import validate_candidate
from scripts import sermon_accounting as accounting
from scripts.build_sermon_reading_edition_with_openai import build_semantic_blocks, reading_quality_report, write_block_srt
from scripts.generate_notes_with_openai import segments_from_srt, merge_aligned_segments, build_note_slices, summarize_slices
from scripts.sermon_pipeline import clean_text, reference_chunks_to_reading_segments, source_file_identity, parse_timecode
import test_saturday_bridge as live_fixture
from weekly_dubbing import prepare, read, validate_frozen
from check_weekly_timing import budgets


def fake_probe(_):
    return {"durationSeconds": 10, "streams": [{"codec_type": "video"}, {"codec_type": "audio"}]}


def fake_pdf_render(command, **kwargs):
    output = Path(command[command.index("--out") + 1])
    output.write_bytes(b"synthetic rendered PDF " + output.name.encode())
    write_json(output.with_suffix(".qa.json"), {"status": "pass", "pageCount": 1})
    return SimpleNamespace(returncode=0)


def same_source(root):
    media = root / "same-sermon.mp4"
    media.write_bytes(b"explicit same-version video fixture")
    return {"week": "2026-09-06", "sourceId": "same-fixture", "canonicalURL": "https://example.org/sermons/same-fixture",
        "path": str(media), "sha256": sha256(media), "durationSeconds": 10, "sameVersionConfirmed": True,
        "sermonOnly": True, "confirmationReference": "synthetic same-version confirmation; not a real source"}


def reviewed_fixture(root, *, chunked=False, seal=True):
    source, run = same_source(root), root / "same-run"
    intake.initialize(source, run, media_probe=fake_probe, title="已核实主题", speaker="Eric Geiger")
    pipeline = run / "pipeline"
    pipeline.mkdir()
    clip = pipeline / "source_clip.m4a"
    clip.write_bytes(b"same source audio clip fixture")
    write_json(clip.with_suffix(".m4a.cache.json"), {"source": {"sha256": source["sha256"]}, "startSeconds": 0, "endSeconds": 10})
    summary = {"source": str(run / "source/video.mp4"), "outputMode": "reading", "sourceDurationSeconds": 10,
        "sermonStartSeconds": 0, "sermonEndSeconds": 10, "models": {"referenceAsr": "gpt-transcribe"}, "readingSegmentTargetCharacters": 420}
    write_json(pipeline / "summary.json", summary)
    texts = ["Bring your questions to God."] if not chunked else ["Bring your questions to God.", "God hears us."]
    chunks = []
    for index, text in enumerate(texts):
        start, end = index * 10 / len(texts), (index + 1) * 10 / len(texts)
        result = {"text": text, "languages": ["en"], "usage": {"seconds": end - start}}
        chunks.append({"id": index, "start": start, "end": end, "duration": end - start,
            "text": clean_text(text), "usage": result["usage"], "detectedLanguages": ["en"]})
        if chunked:
            base = pipeline / "chunks_reference" / f"chunk_{index:04d}"
            base.parent.mkdir(exist_ok=True)
            audio = base.with_suffix(".m4a")
            audio.write_bytes(f"same source chunk {index}".encode())
            write_json(audio.with_suffix(".m4a.cache.json"), {"operation": "cut_chunk", "source": source_file_identity(clip),
                "startSeconds": start, "durationSeconds": end - start})
        else:
            base, audio = pipeline / "asr_reference", clip
        write_json(base.with_suffix(".json"), result)
        write_json(base.with_suffix(".request.json"), {"audioSha256": sha256(audio), "model": "gpt-transcribe", "startSeconds": start, "endSeconds": end})
    write_json(pipeline / "asr_reference_chunks.json", chunks)
    raw = reference_chunks_to_reading_segments(chunks, target_chars=420)
    write_json(pipeline / "segments_timed_en_raw.json", raw)
    write_json(pipeline / "segments_timed_en_corrected.json", raw)
    translated = [{**row, "zh": "把你的问题带到神面前。" if index == 0 else "神垂听我们。"} for index, row in enumerate(raw)]
    write_json(pipeline / "segments_timed_zh.json", translated)
    draft = build_semantic_blocks(raw, translated, preferred_seconds=24, preferred_english_chars=420, hard_seconds=55, hard_english_chars=840)
    final = [{**block, "zh": block["draftZh"]} for block in draft]
    reading = pipeline / "reading-edition-v2"
    write_json(reading / "reading_blocks.draft.json", draft)
    write_json(reading / "reading_blocks.final.json", final)
    quality = {**reading_quality_report(final), "sourcePipeline": str(pipeline), "model": "gpt-6-astra", "passes": 2,
        "layoutTargets": {"preferredSeconds": 24, "preferredEnglishCharacters": 420, "hardSeconds": 55, "hardEnglishCharacters": 840}}
    assert quality["status"] == "pass", quality
    write_json(reading / "reading_quality_report.json", quality)
    srts = {}
    for field in ("en", "zh"):
        path = reading / f"sermon_{field}_reading_revised.srt"
        write_block_srt(path, final, field)
        srts[field] = path.read_text()
    segments = merge_aligned_segments(segments_from_srt(srts["zh"], lang="zh"), segments_from_srt(srts["en"], lang="en"))
    notes = {"status": "ready", "sermonDate": source["week"], "sermonTitle": "已核实主题", "speaker": "Eric Geiger",
        "sourceSegmentCount": len(segments), "slices": summarize_slices(build_note_slices(segments))}
    write_json(pipeline / "sermon-interpretation/insights/openai-notes.json", notes)
    if seal:
        intake.seal_reviewed(run, source, media_probe=fake_probe, runner=fake_pdf_render)
    return source, run


def candidate_audio_fixture(work):
    """Mock model outputs while exercising the shared production validators."""
    job = read(work / "job.json")
    identity = renderer.render_identity(work / "job.json", job["voice"]["checkpointSha256"])
    write_json(work / "render/identity.json", identity)
    cues = []
    for index, unit in enumerate(job["units"]):
        audio = work / f"render/unit-{index:04d}.wav"
        audio.write_bytes(f"synthetic TTS unit {index}".encode())
        write_json(audio.with_suffix(".json"), {"unit": unit, "identity": identity, "sha256": sha256(audio), "durationSeconds": 2})
        cues.append({"unitId": index, "blockId": unit["blockId"], "start": index * 2.45, "end": index * 2.45 + 2, "text": unit["text"]})
        write_json(work / f"audio/unit-screening/unit-{index:04d}.json", {"unitId": index, "blockId": unit["blockId"],
            "identity": {"audioSha256": sha256(audio), "expected": unit.get("spokenText", unit["text"]), "model": ASR[0], "revision": ASR[1]},
            "recognized": unit.get("spokenText", unit["text"]), "similarity": 1, "differences": []})
    raw = work / "render/chinese.raw.wav"
    raw.write_bytes(b"synthetic assembled raw")
    duration = cues[-1]["end"]
    write_json(work / "render/report.json", {**identity, "status": "complete_candidate_render", "sha256": sha256(raw), "durationSeconds": duration, "cues": cues})
    mp3 = work / "audio/zh-natural.mp3"
    mp3.write_bytes(b"synthetic MP3")
    track = {"id": "full_candidate", "file": mp3.name, "sha256": sha256(mp3), "durationSeconds": duration,
        "cues": [{key: cue[key] for key in ("start", "end", "text", "blockId")} for cue in cues]}
    write_json(work / "audio/library.json", {"schemaVersion": "sermon-audio-library-v1", "date": job["week"], "tracks": [track]})
    write_json(work / "assembly-report.json", {"jobSha256": identity["jobSha256"], "sha256": sha256(mp3), "durationSeconds": duration, "fullDecode": "pass"})
    write_json(work / "audio-review.json", {"jobSha256": identity["jobSha256"], "mp3Sha256": sha256(mp3),
        "checkpointSha256": job["voice"]["checkpointSha256"], "humanApproval": False})
    anchors = [{"blockId": row["id"], "start": index * 5, "end": index * 5 + 4, "issues": []} for index, row in enumerate(job["blocks"])]
    write_json(work / "source-alignment/report.json", {"schemaVersion": "sermon-acoustic-anchors-v1", "jobSha256": identity["jobSha256"],
        "sourceAudioSha256": job["inputs"]["sourceAudio"]["sha256"], "timeOrigin": "approved_sermon_clip_start", "fullVideoOffsetSeconds": 0,
        "blocks": anchors, "asr": ASR, "aligner": ALIGNER})
    write_json(work / "audio/asr-screening.json", {"status": "machine_screening_only", "jobSha256": identity["jobSha256"], "model": ASR[0], "revision": ASR[1],
        "results": [{"id": "full_candidate", "sha256": sha256(mp3), "durationSeconds": duration, "fullDecode": "pass", "screenedUnits": len(cues), "expectedUnits": len(cues), "reviewCandidates": []}]})
    rows, failures = budgets(job["blocks"], anchors, cues, 10)
    write_json(work / "synchronization/report.json", {"schemaVersion": "sermon-video-sync-budget-v1", "jobSha256": identity["jobSha256"],
        "alignmentSha256": sha256(work / "source-alignment/report.json"), "anchorReviewSha256": None, "sourceVideoOffsetSeconds": 0,
        "durationSeconds": 10, "status": "natural_timing_fits", "blocks": rows, "failures": failures})


class SameVideoTests(unittest.TestCase):
    def setUp(self):
        for mocked in [patch.object(accounting, "execution_identity", return_value={"gitCommit": None}),
                       patch("weekly_dubbing.probe", side_effect=fake_probe)]:
            mocked.start()
            self.addCleanup(mocked.stop)

    def snapshot(self, root):
        return {str(path.relative_to(root)): sha256(path) for path in root.rglob("*")
                if path.is_file() and "accounting" not in path.relative_to(root).parts}

    def test_contract_inspection_plan_and_archive_are_readonly_or_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, run = same_source(root), root / "isolated"
            before = self.snapshot(root)
            normalized = intake.validate_source(source, source["week"], media_probe=fake_probe)
            plan = intake.production_plan(run, normalized, title="已核实主题", speaker="Eric Geiger")
            self.assertEqual(self.snapshot(root), before)
            self.assertFalse((root / "accounting").exists())
            self.assertEqual(parse_timecode(plan["commands"][0][plan["commands"][0].index("--end-time") + 1]), 10)
            self.assertTrue(all("--approval-evidence" not in command for command in plan["commands"]))
            intake.initialize(source, run, media_probe=fake_probe)
            before = self.snapshot(root)
            intake.initialize(source, run, media_probe=fake_probe)
            self.assertEqual(self.snapshot(root), before)
            Path(source["path"]).unlink()
            self.assertEqual(intake.validate_archive(run, source, media_probe=fake_probe)[0]["sourceId"], source["sourceId"])
            self.assertFalse((run / "operator-window-approval.json").exists())
            self.assertTrue(list((run.parent / "accounting").rglob("events.jsonl")))

    def test_source_contract_rejects_changed_or_unconfirmed_source(self):
        mutations = [{"week": "2026-09-13"}, {"sameVersionConfirmed": False}, {"sermonOnly": False}, {"confirmationReference": ""},
            {"sourceId": "../bad"}, {"sha256": "0" * 64}, {"durationSeconds": 11},
            {"canonicalURL": "https://www.youtube.com/watch?v=another-source"}]
        with tempfile.TemporaryDirectory() as tmp:
            source = same_source(Path(tmp))
            for change in mutations:
                with self.subTest(change=change), self.assertRaises(ValueError):
                    intake.validate_source({**source, **change}, source["week"], media_probe=fake_probe)

    def test_initialize_cached_and_failed_attempts_and_seal_failures_are_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, run = same_source(root), root / "intake-run"
            intake.initialize(source, run, media_probe=fake_probe)
            intake.initialize(source, run, media_probe=fake_probe)
            with self.assertRaises(ValueError):
                intake.initialize({**source, "sha256": "0" * 64}, run, media_probe=fake_probe)
            events = [json.loads(line) for line in (root / "accounting/intake-run/events.jsonl").read_text().splitlines()]
            archives = [row for row in events if row["event"] == "stage_finished" and row["stage"] == "same_video.archive"]
            self.assertEqual([row["cacheHit"] for row in archives], [False, True])
            finished = [row for row in events if row["event"] == "workflow_finished"]
            self.assertEqual([row["status"] for row in finished], ["completed", "completed", "failed"])
            source, reviewed = reviewed_fixture(root, seal=False)
            with self.assertRaisesRegex(ValueError, "local renderer failed"):
                intake.seal_reviewed(reviewed, source, media_probe=fake_probe, runner=Mock(side_effect=ValueError("local renderer failed")))
            events = [json.loads(line) for line in (reviewed / "accounting/events.jsonl").read_text().splitlines()]
            self.assertEqual([row["status"] for row in events if row["event"] == "workflow_finished"], ["failed"])
            self.assertFalse((reviewed / intake.HANDOFF_NAME).exists())
            self.assertFalse((reviewed / "same-video-pdfs").exists())

    def test_youtube_negative_or_underscore_id_is_valid_and_path_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg, sup, config, _ = live_fixture.SaturdayBridgeTests().fixture(root)
            source = same_source(root)
            for source_id in ("-BeFX5G2oAw", "_fixture-src"):
                source.update(sourceId=source_id, canonicalURL="https://www.youtube.com/watch?v=" + source_id)
                intake.validate_source(source, source["week"], media_probe=fake_probe)
                config["weeks"][source["week"]]["sameVideo"] = {"source": source}
                write_json(cfg, config)
                report = continue_saturday(cfg, source["week"], sup, media_probe=fake_probe)
                self.assertEqual(report["routes"]["same_video"]["status"], "waiting_same_video_intake")
                plan = intake.production_plan(Path(report["routes"]["same_video"]["run"]), source)
                self.assertEqual(plan["commands"][0][plan["commands"][0].index("--slug") + 1], "sermon_" + source_id)

    def test_single_and_chunked_asr_seal_without_human_window(self):
        for chunked in (False, True):
            with self.subTest(chunked=chunked), tempfile.TemporaryDirectory() as tmp:
                source, run = reviewed_fixture(Path(tmp), chunked=chunked)
                receipt = read(run / intake.HANDOFF_NAME)
                self.assertEqual(receipt["humanWindow"], "not_applicable")
                self.assertFalse(receipt["humanApproval"])
                self.assertNotIn("windowApproval", receipt["inputs"])
                self.assertIn("sameVideoPdfReceipt", receipt["inputs"])
                before = self.snapshot(run)
                intake.validate_handoff(run, source, media_probe=fake_probe)
                intake.seal_reviewed(run, source, media_probe=fake_probe, runner=Mock(side_effect=AssertionError("cached PDF")))
                self.assertEqual(self.snapshot(run), before)

    def test_changed_source_text_outline_pdf_or_qa_cannot_reseal(self):
        paths = ["source/video.mp4", "pipeline/source_clip.m4a", "pipeline/segments_timed_en_raw.json",
            "pipeline/reading-edition-v2/reading_blocks.final.json", "pipeline/reading-edition-v2/sermon_zh_reading_revised.srt",
            "pipeline/sermon-interpretation/insights/openai-notes.json", "same-video-pdfs/sermon_zh_en_reading.pdf",
            "same-video-pdfs/sermon_zh_en_reading.qa.json"]
        for relative in paths:
            with self.subTest(path=relative), tempfile.TemporaryDirectory() as tmp:
                source, run = reviewed_fixture(Path(tmp))
                (run / relative).write_bytes(b"another source or changed artifact")
                before = self.snapshot(run)
                with self.assertRaises((ValueError, KeyError)):
                    intake.seal_reviewed(run, source, media_probe=fake_probe, runner=Mock(side_effect=AssertionError("must not render")))
                self.assertEqual(self.snapshot(run), before)

    def test_fallback_raw_and_corrected_changed_together_are_not_same_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, run = reviewed_fixture(Path(tmp), seal=False)
            raw = read(run / "pipeline/segments_timed_en_raw.json")
            raw[0]["text"] = "A different archived sermon."
            for name in ("raw", "corrected"):
                write_json(run / f"pipeline/segments_timed_en_{name}.json", raw)
            with self.assertRaisesRegex(ValueError, "Raw English"):
                intake.seal_reviewed(run, media_probe=fake_probe, runner=Mock(side_effect=AssertionError("must not render")))

    def test_chunk_request_cut_and_coverage_bind_current_clip(self):
        for target, change in [("chunk_0001.request.json", {"audioSha256": "0" * 64}),
                               ("chunk_0001.m4a.cache.json", {"source": {"sizeBytes": 99}})]:
            with self.subTest(target=target), tempfile.TemporaryDirectory() as tmp:
                _, run = reviewed_fixture(Path(tmp), chunked=True, seal=False)
                path = run / "pipeline/chunks_reference" / target
                write_json(path, {**read(path), **change})
                with self.assertRaises(ValueError):
                    intake.seal_reviewed(run, media_probe=fake_probe, runner=fake_pdf_render)

    def test_bridge_contract_to_prepare_candidate_and_resume_uses_real_validator(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg, sup, config, fallback = live_fixture.SaturdayBridgeTests().fixture(root)
            checkpoint = root / "renderer-checkpoint"
            checkpoint.mkdir()
            (checkpoint / "model.safetensors").write_bytes(b"synthetic checkpoint weights")
            write_json(checkpoint / "config.json", {"talker_config": {"spk_id": {"eric_pilot": 0}}})
            training = root / "voice/training-report.json"
            write_json(training, {**read(training), "checkpointSha256": sha256(checkpoint / "model.safetensors")})
            fallback_before = self.snapshot(fallback)
            source, run = reviewed_fixture(root)
            config["weeks"][source["week"]]["sameVideo"] = {"source": source, "run": str(run)}
            write_json(cfg, config)
            before = self.snapshot(root)
            options = {"media_probe": fake_probe, "validator": validate_candidate}
            report = continue_saturday(cfg, source["week"], sup, **options)
            self.assertEqual(report["selectedRoute"], "same_video")
            self.assertEqual(report["status"], "ready_to_prepare")
            self.assertEqual(self.snapshot(root), before)
            def synthesize(command, **kwargs):
                candidate_audio_fixture(Path(command[command.index("--work") + 1]))
                return SimpleNamespace(returncode=0)
            synthesize = Mock(side_effect=synthesize)
            report = continue_saturday(cfg, source["week"], sup, execute=True, runner=synthesize, **options)
            self.assertEqual(report["status"], "waiting_conversation_review", report)
            work = Path(report["routes"]["same_video"]["work"])
            job = read(work / "job.json")
            self.assertEqual(job["schemaVersion"], "sermon-weekly-dubbing-job-v1")
            self.assertEqual(job["sourceStartSeconds"], 0)
            self.assertEqual(job["inheritedReview"]["humanWindow"], "not_applicable")
            self.assertFalse(job["inheritedReview"]["generationComplete"])
            self.assertEqual(validate_candidate(work)["mp3Sha256"], sha256(work / "audio/zh-natural.mp3"))
            # The existing v1 renderer consumes this extension unchanged and
            # exits through verified cache before importing a model runtime.
            with patch("sys.argv", ["render_weekly_audio.py", "--job", str(work / "job.json"), "--checkpoint", str(checkpoint), "--out", str(work / "render")]):
                renderer.main()
            second = continue_saturday(cfg, source["week"], sup, execute=True, runner=synthesize, **options)
            self.assertEqual(second["status"], "waiting_conversation_review")
            self.assertEqual(synthesize.call_count, 1)
            self.assertEqual(self.snapshot(fallback), fallback_before)
            for change in [{"sourceRoute": "live_archive"}, {"sourceId": "fallback-source"}, {"sourceStartSeconds": 1}]:
                with self.subTest(change=change), self.assertRaises(ValueError):
                    validate_frozen({**job, **change})

    def test_damaged_same_candidate_does_not_block_healthy_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg, sup, config, _ = live_fixture.SaturdayBridgeTests().fixture(root)
            source, run = reviewed_fixture(root)
            config["weeks"][source["week"]]["sameVideo"] = {"source": source, "run": str(run)}
            write_json(cfg, config)
            def synthesize(command, **kwargs):
                candidate_audio_fixture(Path(command[command.index("--work") + 1]))
                return SimpleNamespace(returncode=0)
            report = continue_saturday(cfg, source["week"], sup, media_probe=fake_probe, execute=True, runner=synthesize, validator=validate_candidate)
            work = Path(report["routes"]["same_video"]["work"])
            (work / "audio/zh-natural.mp3").write_bytes(b"damaged candidate")
            report = continue_saturday(cfg, source["week"], sup, media_probe=fake_probe, validator=validate_candidate)
            self.assertEqual(report["routes"]["same_video"]["status"], "waiting_evidence_repair")
            self.assertEqual(report["selectedRoute"], "live_archive")
            self.assertEqual(report["status"], "ready_to_prepare")

    def test_pdf_seal_retry_never_repeats_valid_reading_or_paid_companion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg, sup, config, _ = live_fixture.SaturdayBridgeTests().fixture(root)
            source, run = reviewed_fixture(root, seal=False)
            config["weeks"][source["week"]]["sameVideo"] = {"source": source, "run": str(run)}
            write_json(cfg, config)
            options = {"media_probe": fake_probe}
            report = continue_saturday(cfg, source["week"], sup, **options)
            commands = report["routes"]["same_video"]["nextActions"][0]["commands"]
            self.assertEqual(len(commands), 1)
            self.assertIn("--seal-reviewed", commands[0])
            (run / "pipeline/sermon-interpretation/insights/openai-notes.json").unlink()
            report = continue_saturday(cfg, source["week"], sup, **options)
            commands = report["routes"]["same_video"]["nextActions"][0]["commands"]
            self.assertEqual(len(commands), 2)
            self.assertTrue(commands[0][1].endswith("generate_notes_with_openai.py"))

    def test_awaiting_intake_and_production_emit_executable_actions_without_blocking_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg, sup, config, _ = live_fixture.SaturdayBridgeTests().fixture(root)
            source, run = same_source(root), root / "same-run"
            config["weeks"][source["week"]]["sameVideo"] = {"source": source, "run": str(run)}
            write_json(cfg, config)
            report = continue_saturday(cfg, source["week"], sup, media_probe=fake_probe)
            self.assertEqual(report["selectedRoute"], "live_archive")
            action = report["routes"]["same_video"]["nextActions"][0]["commands"][0]
            self.assertIn("--initialize", action)
            self.assertEqual(action[action.index("--config") + 1], str(cfg.resolve()))
            self.assertFalse(run.exists())
            intake.initialize(source, run, media_probe=fake_probe)
            report = continue_saturday(cfg, source["week"], sup, media_probe=fake_probe)
            self.assertEqual(report["routes"]["same_video"]["status"], "waiting_same_video_production")
            self.assertIn("--seal-reviewed", report["routes"]["same_video"]["productionPlan"]["commands"][-1])
            self.assertEqual(report["selectedRoute"], "live_archive")


if __name__ == "__main__":
    unittest.main()
