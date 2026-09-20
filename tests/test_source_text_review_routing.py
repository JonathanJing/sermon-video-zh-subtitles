"""Source review routing / cache identity tests; no generation or network."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import run_post_live_subtitle_generation as generation
from scripts import sermon_production_supervisor as supervisor
from scripts import sermon_pipeline


ARCHIVE_DURATION_SECONDS = 3600.0


def finished_archive_metadata(_url):
    # The full archive is distinct from the five-second reviewed clip below.
    return {"live_status": "was_live", "duration": ARCHIVE_DURATION_SECONDS}


def review_cache_fixture(pipeline):
    pipeline.mkdir(parents=True)
    text = ("I am committed tonight to shield you. " + "Every promise points us back to the faithful character of God. " * 8).strip()
    result = {"text": text, "languages": ["en"], "usage": {"seconds": 6}}
    chunks = [{"id": 0, "start": 0.0, "end": 5.0, "duration": 5.0, "text": text, "usage": result["usage"], "detectedLanguages": ["en"]}]
    raw = sermon_pipeline.reference_chunks_to_reading_segments(chunks, target_chars=420)
    corrected = [{**row, "text": row["text"].replace("tonight to shield", "to not shield", 1)} if row["id"] == 0 else {**row} for row in raw]
    files = {"source_clip.m4a": b"frozen source audio", "asr_reference.json": json.dumps(result).encode(),
        "review-evidence.json": b'{"finding":"committed to not shield"}'}
    for name, contents in files.items():
        (pipeline / name).write_bytes(contents)
    evidence_hash = hashlib.sha256(files["review-evidence.json"]).hexdigest()
    review = {"schemaVersion": "sermon-source-text-review-v1", "reviewType": "model", "model": "gpt-6-astra", "humanApproval": False,
        "status": "approved_for_source_correction", "authority": "user_directed_conversation_review",
        "reviewedBy": "Frozen conversation review", "reviewedAt": "2026-09-05T12:00:00Z",
        "sourceAudioSha256": hashlib.sha256(files["source_clip.m4a"]).hexdigest(), "asrSha256": hashlib.sha256(files["asr_reference.json"]).hexdigest(),
        "evidence": [{"path": "review-evidence.json", "sha256": evidence_hash}],
        "patches": [{"segmentId": 0, "originalTextSha256": hashlib.sha256(raw[0]["text"].encode()).hexdigest(),
            "correctedText": corrected[0]["text"], "reason": "Explicit frozen source evidence", "evidenceSha256": evidence_hash}]}
    for name, data in [("source-text-review.json", review), ("segments_timed_en_raw.json", raw), ("segments_timed_en_corrected.json", corrected),
        ("segments_timed_zh.json", [{"id": 0, "text": "我承诺不再保护你。"}]), ("summary.json", {})]:
        (pipeline / name).write_text(json.dumps(data), encoding="utf-8")
    return pipeline / "source-text-review.json"


def reading_manifest_fixture(reading, *, applied=False):
    reading.mkdir(parents=True)
    manifest_path = reading.parent / "reading-review.json"
    manifest = {"schemaVersion": 1, "corrections": [{"blockId": 0, "field": "zh", "find": "keep walking", "replace": "继续前行", "reason": "Reviewed Chinese wording"}]}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    final = [{"id": 0, "start": 0, "end": 5, "en": "Keep walking.", "zh": "我们要继续前行。" if applied else "我们要 keep walking。"}]
    (reading / "reading_blocks.final.json").write_text(json.dumps(final), encoding="utf-8")
    report = {"status": "pass", "reviewManifest": {"path": str(manifest_path), "sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest()}}
    (reading / "reading_quality_report.json").write_text(json.dumps(report), encoding="utf-8")
    return manifest_path


class SourceTextReviewRoutingTests(unittest.TestCase):
    def setUp(self):
        remote = patch('scripts.mfa_backend.preflight', return_value={'backend': 'dgx-spark-ssh', 'runtime': {'version': 'fixture'}})
        remote.start()
        self.addCleanup(remote.stop)
        duration = patch.object(sermon_pipeline, "ffprobe_duration", return_value=5.0)
        duration.start()
        self.addCleanup(duration.stop)
        # These routing fixtures use opaque audio bytes. Mock only ffprobe's
        # media facts; retain validate_archive_audio's real completeness checks.
        archive_probe = patch.object(generation, "probe_archive_audio", return_value={
            "format": {"duration": str(ARCHIVE_DURATION_SECONDS)},
            "streams": [{"codec_type": "audio"}],
        })
        archive_probe.start()
        self.addCleanup(archive_probe.stop)

    def args(self, *extra):
        argv = ["run_post_live_subtitle_generation.py", "--sunday", "2026-08-30", "--state-file", "isolated-state.json", *extra]
        with patch.object(generation.sys, "argv", argv):
            return generation.parse_args()

    def test_supervisor_routes_optional_review_through_generation_to_pipeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            review = root / "source-text-review.json"
            config = supervisor.SupervisorConfig(sunday="2026-08-30", state_file=str(root / "state.json"), work_root=root,
                gcs_bucket=None, source_text_review=review)
            snapshot = {"slug": "sermon_fixture", "locations": {"generationReportLocal": str(root / "report.json"),
                "windowApprovalLocal": str(root / "operator-window-approval.json")}}
            approval = {"startTime": "00:29:00", "endTime": "00:58:30", "contentScope": "sermon_only"}
            with patch.object(supervisor, "live_url_from_snapshot", return_value="https://example.invalid/sermon"):
                command = supervisor.build_generation_command(config, snapshot, approval)
            self.assertEqual(command.count("--source-text-review"), 1)
            self.assertEqual(command[command.index("--source-text-review") + 1], str(review))
            with patch.object(generation.sys, "argv", command[1:]):
                args = generation.parse_args()
            self.assertEqual(args.source_text_review, review)
            pipeline = generation.build_pipeline_command(args, root / "download", root / "pipeline", "https://example.invalid/sermon")
            self.assertEqual(pipeline.count("--source-text-review"), 1)
            self.assertEqual(pipeline[pipeline.index("--source-text-review") + 1], str(review))
            self.assertIn("--export-sunday-context", command)

    def test_absent_review_preserves_the_legacy_identity_and_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "source.m4a"
            audio.write_bytes(b"frozen source audio")
            args = self.args()
            with_none = generation.build_pipeline_input_identity(args, audio)
            command_with_none = generation.build_pipeline_command(args, root / "download", root / "pipeline", "https://example.invalid/sermon")
            del args.source_text_review
            legacy = generation.build_pipeline_input_identity(args, audio)
            command_legacy = generation.build_pipeline_command(args, root / "download", root / "pipeline", "https://example.invalid/sermon")
            self.assertEqual(with_none, legacy)
            self.assertNotIn("sourceTextReview", legacy)
            self.assertEqual(command_with_none, command_legacy)
            self.assertNotIn("--source-text-review", command_legacy)
            self.assertIsNone(supervisor.SupervisorConfig(sunday="2026-08-30", state_file="isolated.json").source_text_review)

    def test_review_identity_tracks_content_instead_of_its_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio, review, copy = root / "source.m4a", root / "review.json", root / "review-copy.json"
            audio.write_bytes(b"frozen source audio")
            payload = b'{"correction": "committed to not shield"}'
            review.write_bytes(payload)
            copy.write_bytes(payload)
            args = self.args("--source-text-review", str(review))
            original = generation.build_pipeline_input_identity(args, audio)
            self.assertEqual(original["sourceTextReview"], {"exists": True, "sizeBytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
            args.source_text_review = copy
            moved = generation.build_pipeline_input_identity(args, audio)
            self.assertEqual(original, moved)
            copy.write_bytes(b'{"correction": "changed review"}')
            changed = generation.build_pipeline_input_identity(args, audio)
            self.assertNotEqual(generation.stable_payload_hash(original), generation.stable_payload_hash(changed))
            copy.unlink()
            self.assertEqual(generation.build_pipeline_input_identity(args, audio)["sourceTextReview"], {"exists": False})

    def test_source_review_is_reading_only_before_state_or_model_access(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
            self.args("--source-text-review", "review.json", "--output-mode", "subtitles")
        self.assertEqual(exc.exception.code, 2)
        args = self.args("--source-text-review", "review.json")
        args.output_mode = "subtitles"
        with patch.object(generation.live_source_monitor, "read_state", side_effect=AssertionError("No state/network access")) as state:
            with self.assertRaisesRegex(ValueError, "only with --output-mode reading"):
                generation.run_post_live_generation(args)
            state.assert_not_called()

    def test_mfa_never_accepts_legacy_review_cache_even_with_valid_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = Path(tmp) / "pipeline"
            review = review_cache_fixture(pipeline)
            args = self.args("--source-text-review", str(review))
            self.assertEqual(args.reading_aligner, "mfa")
            before = {p.name: p.read_bytes() for p in pipeline.iterdir()}
            self.assertFalse(generation.source_review_cache_ready(args, pipeline))
            self.assertEqual({p.name: p.read_bytes() for p in pipeline.iterdir()}, before)
            args.reading_aligner = "legacy"
            self.assertTrue(generation.source_review_cache_ready(args, pipeline))
            (pipeline / "review-evidence.json").write_text('{"finding":"changed"}')
            with self.assertRaisesRegex(ValueError, "evidence changed"):
                generation.source_review_cache_ready(args, pipeline)
            args.reading_aligner = "mfa"
            self.assertFalse(generation.source_review_cache_ready(args, pipeline))

    def test_valid_review_cache_is_read_only_and_supports_chunk_asr(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = Path(tmp) / "pipeline"
            review = review_cache_fixture(pipeline)
            args = self.args("--reading-aligner", "legacy", "--source-text-review", str(review))
            for chunks in [False, True]:
                if chunks:
                    asr = json.loads((pipeline / "asr_reference.json").read_text())
                    data = [{"id": 0, "start": 0.0, "end": 5.0, "duration": 5.0, "text": asr["text"], "usage": asr["usage"], "detectedLanguages": asr["languages"]}]
                    (pipeline / "asr_reference_chunks.json").write_text(json.dumps(data))
                    (pipeline / "asr_reference.json").unlink()
                    receipt = json.loads(review.read_text())
                    receipt["asrSha256"] = hashlib.sha256((pipeline / "asr_reference_chunks.json").read_bytes()).hexdigest()
                    review.write_text(json.dumps(receipt))
                before = {p.name: p.read_bytes() for p in pipeline.iterdir()}
                self.assertTrue(generation.source_review_cache_ready(args, pipeline))
                self.assertEqual({p.name: p.read_bytes() for p in pipeline.iterdir()}, before)

    def test_unreviewed_raw_and_corrected_changes_cannot_bypass_bound_asr_reconstruction(self):
        changes = [lambda rows: rows[1].update(text="Changed English without a reviewed patch."),
            lambda rows: rows[1].update(start=4.0), lambda rows: rows.pop(), lambda rows: rows[1].update(source="different-source")]
        for i, change in enumerate(changes):
            with self.subTest(case=i), tempfile.TemporaryDirectory() as tmp:
                pipeline = Path(tmp) / "pipeline"
                review = review_cache_fixture(pipeline)
                args = self.args("--reading-aligner", "legacy", "--source-text-review", str(review))
                for name in ["segments_timed_en_raw.json", "segments_timed_en_corrected.json"]:
                    path = pipeline / name
                    rows = json.loads(path.read_text())
                    self.assertGreater(len(rows), 1)
                    change(rows)
                    path.write_text(json.dumps(rows))
                before = {p.name: p.read_bytes() for p in pipeline.iterdir()}
                with self.assertRaisesRegex(ValueError, "Raw reading segments differ from the bound ASR"):
                    generation.source_review_cache_ready(args, pipeline)
                self.assertEqual({p.name: p.read_bytes() for p in pipeline.iterdir()}, before)

    def test_primary_bound_asr_ignores_unbound_chunk_copy_and_checks_segment_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = Path(tmp) / "pipeline"
            review = review_cache_fixture(pipeline)
            args = self.args("--reading-aligner", "legacy", "--source-text-review", str(review))
            (pipeline / "asr_reference_chunks.json").write_text('[{"id":0,"start":0,"end":999,"text":"Untrusted derived copy"}]')
            self.assertTrue(generation.source_review_cache_ready(args, pipeline))
            args.reading_segment_target_chars = 120
            with self.assertRaisesRegex(ValueError, "Raw reading segments differ from the bound ASR"):
                generation.source_review_cache_ready(args, pipeline)

    def test_stale_review_evidence_cannot_hide_behind_a_matching_core_cache(self):
        mutations = [
            lambda p: (p / "review-evidence.json").write_text('{"finding":"changed"}'),
            lambda p: (p / "source_clip.m4a").write_bytes(b"changed source audio"),
            lambda p: (p / "asr_reference.json").write_text('{"text":"changed ASR"}'),
            lambda p: (p / "segments_timed_en_raw.json").write_text('[{"id":0,"text":"changed English"}]'),
        ]
        for i, mutate in enumerate(mutations):
            with self.subTest(case=i), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                pipeline = root / "2026-08-30/sermon_fixture/pipeline"
                review = review_cache_fixture(pipeline)
                download = pipeline.parent / "download"
                download.mkdir()
                (download / "source_audio.m4a").write_bytes(b"source fixture")
                args = self.args("--reading-aligner", "legacy", "--source-text-review", str(review), "--work-root", str(root), "--slug", "sermon_fixture")
                args.state_file = str(root / "state.json")
                Path(args.state_file).write_text(json.dumps({"lastSunday": args.sunday, "lastGenerationRequest": {"liveUrl": "https://example.invalid/sermon"}}))
                mutate(pipeline)
                before = {p.name: p.read_bytes() for p in pipeline.iterdir()}
                with patch.object(generation, "set_openai_api_key"), patch.object(generation, "pipeline_summary_matches", return_value=True), \
                        patch.object(generation, "run_command", side_effect=AssertionError("No model stage")) as run:
                    with self.assertRaises(ValueError):
                        generation.run_post_live_generation(args, metadata_loader=finished_archive_metadata)
                    run.assert_not_called()
                self.assertEqual({p.name: p.read_bytes() for p in pipeline.iterdir()}, before)

    def test_missing_source_or_changed_corrected_cache_requires_the_pipeline(self):
        for missing in ["segments_timed_en_raw.json", "source_clip.m4a", "asr_reference.json", "segments_timed_en_corrected.json", None]:
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                pipeline = root / "2026-08-30/sermon_fixture/pipeline"
                review = review_cache_fixture(pipeline)
                if missing:
                    (pipeline / missing).unlink()
                else:
                    (pipeline / "segments_timed_en_corrected.json").write_text('[{"id":0,"text":"stale cached English"}]')
                args = self.args("--reading-aligner", "legacy", "--source-text-review", str(review), "--work-root", str(root), "--slug", "sermon_fixture")
                self.assertFalse(generation.source_review_cache_ready(args, pipeline))
                download = pipeline.parent / "download"
                download.mkdir()
                (download / "source_audio.m4a").write_bytes(b"source fixture")
                args.state_file = str(root / "state.json")
                Path(args.state_file).write_text(json.dumps({"lastSunday": args.sunday, "lastGenerationRequest": {"liveUrl": "https://example.invalid/sermon"}}))
                with patch.object(generation, "set_openai_api_key"), patch.object(generation, "pipeline_summary_matches", return_value=True), \
                        patch.object(generation, "run_command", side_effect=RuntimeError("pipeline sentinel")) as run:
                    with self.assertRaisesRegex(RuntimeError, "pipeline sentinel"):
                        generation.run_post_live_generation(args, metadata_loader=finished_archive_metadata)
                    self.assertEqual(Path(run.call_args.args[0][1]).name, "sermon_pipeline.py")

    def test_reading_manifest_routes_to_standard_builder_and_preserves_default_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            review = reading_manifest_fixture(root / "pipeline/reading-edition-v2")
            config = supervisor.SupervisorConfig(sunday="2026-08-30", state_file=str(root / "state.json"), work_root=root,
                gcs_bucket=None, reading_review_manifest=review)
            snapshot = {"slug": "sermon_fixture", "locations": {"generationReportLocal": str(root / "report.json"), "windowApprovalLocal": str(root / "approval.json")}}
            with patch.object(supervisor, "live_url_from_snapshot", return_value="https://example.invalid/sermon"):
                command = supervisor.build_generation_command(config, snapshot, {"startTime": "00:29:00", "endTime": "00:58:30"})
            self.assertEqual(command[command.index("--reading-review-manifest") + 1], str(review))
            with patch.object(generation.sys, "argv", command[1:]):
                args = generation.parse_args()
            reading_command = generation.build_reading_edition_command(args, root / "pipeline")
            self.assertEqual(reading_command[reading_command.index("--review-manifest") + 1], str(review))
            self.assertNotIn("--repair-existing", reading_command)
            args = self.args()
            plain = generation.build_reading_input_identity(args, root / "pipeline", pipeline_input_fingerprint="frozen-pipeline")
            plain_command = generation.build_reading_edition_command(args, root / "pipeline")
            del args.reading_review_manifest
            self.assertEqual(plain, generation.build_reading_input_identity(args, root / "pipeline", pipeline_input_fingerprint="frozen-pipeline"))
            self.assertEqual(plain_command, generation.build_reading_edition_command(args, root / "pipeline"))
            self.assertNotIn("readingReviewManifest", plain)
            self.assertTrue(generation.reading_review_cache_ready(args, root / "pipeline/reading-edition-v2"))

    def test_reading_manifest_hash_changes_only_reading_cache_and_verifies_cached_final(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reading = root / "pipeline/reading-edition-v2"
            review = reading_manifest_fixture(reading, applied=True)
            args = self.args("--reading-review-manifest", str(review))
            initial = generation.build_reading_input_identity(args, reading.parent, pipeline_input_fingerprint="frozen-pipeline")
            self.assertEqual(initial["readingReviewManifest"]["sha256"], hashlib.sha256(review.read_bytes()).hexdigest())
            before = {str(p): p.read_bytes() for p in reading.parent.rglob("*") if p.is_file()}
            self.assertTrue(generation.reading_review_cache_ready(args, reading))
            self.assertEqual({str(p): p.read_bytes() for p in reading.parent.rglob("*") if p.is_file()}, before)
            same = root / "review-copy.json"
            same.write_bytes(review.read_bytes())
            args.reading_review_manifest = same
            self.assertEqual(initial, generation.build_reading_input_identity(args, reading.parent, pipeline_input_fingerprint="frozen-pipeline"))
            data = json.loads(same.read_text())
            data["corrections"][0]["reason"] = "Updated review evidence"
            same.write_text(json.dumps(data))
            changed = generation.build_reading_input_identity(args, reading.parent, pipeline_input_fingerprint="frozen-pipeline")
            self.assertNotEqual(generation.stable_payload_hash(initial), generation.stable_payload_hash(changed))
            self.assertFalse(generation.reading_review_cache_ready(args, reading))
            audio = root / "source.m4a"
            audio.write_bytes(b"source")
            core = generation.build_pipeline_input_identity(args, audio)
            args.reading_review_manifest = None
            self.assertEqual(core, generation.build_pipeline_input_identity(args, audio))

    def test_missing_or_subtitle_reading_manifest_stops_before_state_or_models(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
            self.args("--reading-review-manifest", "missing.json", "--output-mode", "subtitles")
        self.assertEqual(exc.exception.code, 2)
        with tempfile.TemporaryDirectory() as tmp:
            args = self.args("--reading-review-manifest", str(Path(tmp) / "missing.json"))
            with patch.object(generation.live_source_monitor, "read_state", side_effect=AssertionError("No state/network access")) as state:
                with self.assertRaisesRegex(ValueError, "existing readable file"):
                    generation.run_post_live_generation(args)
                args.output_mode = "subtitles"
                with self.assertRaisesRegex(ValueError, "only with --output-mode reading"):
                    generation.run_post_live_generation(args)
                state.assert_not_called()

    def test_reading_manifest_rejects_every_non_chinese_field_before_identity_or_cache(self):
        for field in ["en", None, "ZH"]:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                reading = root / "reading-edition-v2"
                review = reading_manifest_fixture(reading, applied=True)
                manifest = json.loads(review.read_text())
                manifest["corrections"].append({"blockId": 0, "field": field, "find": "Keep", "replace": "Stop", "reason": "Unapproved English change"})
                review.write_text(json.dumps(manifest))
                args = self.args("--reading-review-manifest", str(review))
                with self.assertRaisesRegex(ValueError, "supports only field='zh'"):
                    generation.build_reading_input_identity(args, root, pipeline_input_fingerprint="frozen")
                with self.assertRaisesRegex(ValueError, "supports only field='zh'"):
                    generation.reading_review_cache_ready(args, reading)
                with patch.object(generation.live_source_monitor, "read_state", side_effect=AssertionError("No state/network access")) as state:
                    with self.assertRaisesRegex(ValueError, "supports only field='zh'"):
                        generation.run_post_live_generation(args)
                    state.assert_not_called()

    def test_reading_manifest_pending_or_changed_forces_builder_invalid_manifest_rejects(self):
        for condition in ["pending", "changed", "invalid"]:
            with self.subTest(condition=condition), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                pipeline = root / "2026-08-30/sermon_fixture/pipeline"
                reading = pipeline / "reading-edition-v2"
                review = reading_manifest_fixture(reading, applied=condition != "pending")
                if condition != "pending":
                    data = json.loads(review.read_text())
                    data["corrections"][0]["reason"] = "New review note"
                    if condition == "invalid":
                        data["corrections"][0]["blockId"] = 999
                    review.write_text(json.dumps(data))
                for name in ["segments_timed_en_corrected.json", "segments_timed_zh.json", "summary.json"]:
                    (pipeline / name).write_text("{}")
                for name in ["sermon_zh_reading_revised.srt", "sermon_en_reading_revised.srt"]:
                    (reading / name).write_text("cached SRT fixture")
                download = pipeline.parent / "download"
                download.mkdir()
                (download / "source_audio.m4a").write_bytes(b"source fixture")
                args = self.args("--reading-review-manifest", str(review), "--work-root", str(root), "--slug", "sermon_fixture")
                args.state_file = str(root / "state.json")
                Path(args.state_file).write_text(json.dumps({"lastSunday": args.sunday, "lastGenerationRequest": {"liveUrl": "https://example.invalid/sermon"}}))
                before = {str(p): p.read_bytes() for p in reading.rglob("*") if p.is_file()}
                with patch.object(generation, "set_openai_api_key"), patch.object(generation, "pipeline_summary_matches", return_value=True), \
                        patch.object(generation, "reading_report_matches_inputs", return_value=True), \
                        patch.object(generation, "run_command", side_effect=RuntimeError("builder sentinel")) as run:
                    if condition == "invalid":
                        with self.assertRaisesRegex(ValueError, "missing block 999"):
                            generation.run_post_live_generation(args, metadata_loader=finished_archive_metadata)
                        run.assert_not_called()
                    else:
                        with self.assertRaisesRegex(RuntimeError, "builder sentinel"):
                            generation.run_post_live_generation(args, metadata_loader=finished_archive_metadata)
                        self.assertEqual(Path(run.call_args.args[0][1]).name, "build_sermon_reading_edition_with_openai.py")
                        self.assertIn("--review-manifest", run.call_args.args[0])
                self.assertEqual({str(p): p.read_bytes() for p in reading.rglob("*") if p.is_file()}, before)


if __name__ == "__main__":
    unittest.main()
