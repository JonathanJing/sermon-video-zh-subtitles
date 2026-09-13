"""Source-bound timeline recovery and byte-identical GCS handoff regression tests."""
import argparse
import asyncio
import copy
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from agents.tool_context import ToolContext

from scripts import run_post_live_timeline_job as timeline
from scripts import run_post_live_subtitle_generation as generation
from scripts import sermon_production_supervisor as supervisor
from scripts import run_sermon_production_supervisor_agent as agent
from tests.test_run_post_live_timeline_job import make_args, make_handoff, write_state


SOURCE = "https://www.youtube.com/watch?v=5GuhLMPflds"
SUNDAY = "2026-07-12"
SLUG = "sermon_5GuhLMPflds"
PROBE = {"format": {"duration": "3600"}, "streams": [{"codec_type": "audio"}]}


def put_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def failed_report(reason="archive_audio_integrity_failed"):
    return {"schemaVersion": 1, "status": "failed", "reason": reason,
            "sunday": SUNDAY, "sourceUrl": SOURCE, "slug": SLUG,
            "metadata": {"live_status": "was_live", "duration": 3600}}


def fake_timeline(args):
    args.outdir.mkdir(parents=True, exist_ok=True)
    return {"analysis": {"suggestedWindow": {"startTimecode": "00:20:00", "endTimecode": "00:40:00"}}}


class TimelineHandoffTest(unittest.TestCase):
    def run_handoff(self, root, content, *, existing=None, received=None):
        state = root / "state.json"
        write_state(state)
        canonical = root / SUNDAY / SLUG / "download/source_audio.m4a"
        if existing is not None:
            canonical.parent.mkdir(parents=True)
            canonical.write_bytes(existing)
        manifest = make_handoff(content)
        def download(uri, destination):
            self.assertEqual(uri, manifest["audio"]["gcsUri"])
            self.assertFalse(destination.exists(), "Existing bytes must never be overwritten")
            destination.write_bytes(content if received is None else received)
            return destination
        downloader = mock.Mock(side_effect=download)
        upload = mock.Mock()
        with mock.patch.object(generation, "probe_archive_audio", return_value=PROBE), mock.patch.object(timeline.build_multistage_post_live_timeline, "build_multistage_timeline", side_effect=fake_timeline) as model, mock.patch("builtins.print"):
            report = timeline.run_job(
                make_args(root, str(state)), metadata_loader=lambda _: {"live_status": "was_live", "duration": 3600},
                runner=mock.Mock(side_effect=AssertionError("Must use the handoff")),
                uploader=upload, marker_reader=lambda _: None, marker_writer=lambda *_: None,
                handoff_reader=lambda _: manifest, gcs_downloader=downloader,
                notifier=lambda *_: {"status": "not_configured"},
            )
        return report, canonical, downloader, model, upload

    def test_byte_identical_canonical_reuses_handoff_without_download(self):
        with tempfile.TemporaryDirectory() as temp:
            report, canonical, downloader, model, _ = self.run_handoff(Path(temp), b"bound archive", existing=b"bound archive")
            self.assertEqual(report["status"], "requires_operator_review")
            self.assertEqual(report["downloadedAudio"], str(canonical))
            self.assertEqual(report["audioSha256"], hashlib.sha256(b"bound archive").hexdigest())
            downloader.assert_not_called()
            model.assert_called_once()

    def test_equal_length_wrong_cache_is_preserved_and_correct_handoff_uses_isolated_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report, canonical, downloader, model, _ = self.run_handoff(root, b"right archive", existing=b"wrong archive")
            self.assertEqual(report["status"], "requires_operator_review")
            self.assertEqual(canonical.read_bytes(), b"wrong archive")
            selected = Path(report["downloadedAudio"])
            self.assertNotEqual(selected, canonical)
            self.assertTrue(selected.is_relative_to(canonical.parent / "handoffs"))
            self.assertEqual(selected.read_bytes(), b"right archive")
            self.assertEqual(report["audioSha256"], hashlib.sha256(b"right archive").hexdigest())
            self.assertEqual(report["handoffManifestSha256"], generation.stable_payload_hash(make_handoff(b"right archive")))
            downloader.assert_called_once()
            model.assert_called_once()
            locations = supervisor.artifact_locations(supervisor.SupervisorConfig(SUNDAY, "unused", root, gcs_bucket=None), SLUG)
            put_json(Path(locations["timelineReportLocal"]), report)
            with self.assertRaisesRegex(RuntimeError, "Canonical archive differs"):
                supervisor.validate_generation_archive_identity(locations)
            # A separately performed, evidence-preserving promotion restores the gate.
            preserved = canonical.with_name("previous-archive.m4a")
            canonical.rename(preserved)
            canonical.write_bytes(selected.read_bytes())
            put_json(canonical.parent / "relocation-receipt.json", {
                "previous": str(preserved), "previousSha256": hashlib.sha256(preserved.read_bytes()).hexdigest(),
                "promotedFrom": str(selected), "promotedSha256": report["audioSha256"],
            })
            supervisor.validate_generation_archive_identity(locations)
            self.assertEqual(preserved.read_bytes(), b"wrong archive")

    def test_bad_remote_bytes_never_enter_timeline_or_media_upload(self):
        with tempfile.TemporaryDirectory() as temp:
            report, canonical, downloader, model, upload = self.run_handoff(Path(temp), b"right archive", received=b"wrong archive")
            self.assertEqual(report["status"], "failed")
            self.assertIn("SHA-256/size differs", report["downloadDiagnostics"]["reason"])
            self.assertEqual(canonical.read_bytes(), b"wrong archive")
            downloader.assert_called_once()
            model.assert_not_called()
            upload.assert_not_called()

    def test_manifest_source_scope_and_byte_evidence_are_mandatory(self):
        for field, value in [
            ("sourceUrl", "https://www.youtube.com/watch?v=wrongSource1"), ("sunday", "2026-07-19"),
            ("slug", "sermon_wrongSource1"), ("schemaVersion", 2), ("handoffKind", "unbound"),
            ("audio.sha256", None), ("audio.sizeBytes", None), ("audio.sizeBytes", True),
            ("audio.gcsUri", "gs://test-bucket/unrelated/source_audio.m4a"),
            ("audio.fileName", "../source_audio.m4a"), ("audio.fileName", "source_audio.info.json"),
        ]:
            with self.subTest(field=field, value=value), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                manifest = make_handoff(b"right archive")
                handoff_uri = manifest["audio"]["gcsUri"].rsplit("/", 1)[0] + "/local-download-manifest.json"
                if field.startswith("audio."):
                    manifest["audio"][field.split(".", 1)[1]] = value
                else:
                    manifest[field] = value
                downloader = mock.Mock()
                with self.assertRaises(generation.ArchiveAudioValidationError):
                    timeline.materialize_handoff_audio(manifest, handoff_uri=handoff_uri,
                        live_url=SOURCE, sunday=SUNDAY, slug=SLUG, run_root=root,
                        expected_duration=3600, gcs_downloader=downloader)
                downloader.assert_not_called()
                self.assertEqual(list(root.iterdir()), [])


class TimelineResumeTest(unittest.TestCase):
    def config(self, root):
        state = root / "state.json"
        write_state(state)
        return supervisor.SupervisorConfig(SUNDAY, str(state), root, gcs_bucket=None, python_executable="/test/python")

    def test_repaired_cache_resumes_from_failure_to_review_and_preserves_failure_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = self.config(root)
            locations = supervisor.artifact_locations(config, SLUG)
            failed = failed_report()
            report_path = Path(locations["timelineReportLocal"])
            put_json(report_path, failed)
            old_status = {"schemaVersion": 1, "sunday": SUNDAY, "sourceUrl": SOURCE, "status": "failed", "currentStage": "downloaded"}
            put_json(Path(locations["runStatusLocal"]), old_status)
            audio = root / SUNDAY / SLUG / "download/source_audio.m4a"
            audio.parent.mkdir(parents=True)
            audio.write_bytes(b"repaired complete source")
            self.assertEqual(supervisor.production_snapshot(config)["recommendedAction"]["action"], "resume_failed_timeline")
            metadata = mock.Mock(return_value={"live_status": "was_live", "duration": 3600})
            download = mock.Mock(side_effect=AssertionError("Repaired cache must not be downloaded again"))
            writes = []
            def runner(command, **kwargs):
                self.assertIn("--resume-failed-timeline", command)
                args = make_args(root, config.state_file, out=command[command.index("--out") + 1],
                    resume_failed_timeline=command[command.index("--resume-failed-timeline") + 1])
                result = timeline.run_job(args, metadata_loader=metadata, runner=download,
                    uploader=lambda *_: None, marker_reader=lambda _: None,
                    marker_writer=lambda uri, text: writes.append((uri, json.loads(text))),
                    handoff_reader=lambda _: None, notifier=lambda *_: {"status": "not_configured"})
                put_json(Path(args.out), result)
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
            release = mock.Mock(wraps=supervisor.release_lease)
            with mock.patch.object(generation, "probe_archive_audio", return_value=PROBE), mock.patch.object(timeline.build_multistage_post_live_timeline, "build_multistage_timeline", side_effect=fake_timeline), mock.patch("builtins.print"):
                result = supervisor.run_timeline_probe(config, runner=runner,
                    lease_acquirer=lambda *_a, **kwargs: supervisor.acquire_lease(str(root / "test-timeline-lease.json"), **kwargs), lease_releaser=release)
            self.assertEqual(result["status"], "requires_operator_review")
            digest = supervisor.json_digest(failed)
            archived = report_path.parent / "failed-attempts" / digest / "job-report.json"
            self.assertEqual(json.loads(archived.read_text()), failed)
            self.assertEqual(supervisor.json_digest(json.loads(archived.read_text())), digest)
            self.assertEqual(json.loads(next(archived.parent.glob("run-status-*.json")).read_text()), old_status)
            self.assertEqual(writes[0][1], failed)
            self.assertEqual(result["report"]["resumedFailure"]["reportSha256"], digest)
            self.assertEqual(supervisor.production_snapshot(config)["recommendedAction"]["action"], "request_window_approval")
            self.assertFalse(Path(locations["windowApprovalLocal"]).exists())
            download.assert_not_called()
            release.assert_called_once()

    def test_unknown_failure_and_wrong_source_remain_inspection_only(self):
        for failure in [failed_report("unknown_model_failure"), {**failed_report(), "sourceUrl": "https://www.youtube.com/watch?v=wrongSource1"}]:
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                config = self.config(root)
                locations = supervisor.artifact_locations(config, SLUG)
                put_json(Path(locations["timelineReportLocal"]), failure)
                self.assertEqual(supervisor.production_snapshot(config)["recommendedAction"]["action"], "inspect_timeline_failure")
                runner = mock.Mock()
                result = supervisor.run_timeline_probe(config, runner=runner)
                self.assertEqual(result["status"], "skipped")
                runner.assert_not_called()

    def test_resume_requires_the_exact_failed_report_before_any_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = self.config(root)
            locations = supervisor.artifact_locations(config, SLUG)
            failed = failed_report()
            path = Path(locations["timelineReportLocal"])
            put_json(path, failed)
            original = path.read_bytes()
            metadata = mock.Mock()
            writer = mock.Mock()
            with self.assertRaisesRegex(RuntimeError, "unchanged source-bound"):
                timeline.run_job(make_args(root, config.state_file, out=str(path), resume_failed_timeline="0" * 64),
                    metadata_loader=metadata, marker_reader=lambda _: None, marker_writer=writer)
            metadata.assert_not_called()
            writer.assert_not_called()
            self.assertEqual(path.read_bytes(), original)
            self.assertFalse((path.parent / "failed-attempts").exists())

    def test_shared_output_from_another_source_is_preserved_and_never_returned_as_current(self):
        for status in ["failed", "requires_operator_review", "already_requires_operator_review"]:
            with self.subTest(status=status), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                config = self.config(root)
                output = root / "shared-job-report.json"
                old = {**failed_report(), "status": status, "sunday": "2026-07-05"}
                put_json(output, old)
                original = output.read_bytes()
                metadata, writer = mock.Mock(), mock.Mock()
                with self.assertRaisesRegex(RuntimeError, "source-scoped --out"):
                    timeline.run_job(make_args(root, config.state_file, out=str(output)),
                        metadata_loader=metadata, marker_writer=writer)
                self.assertEqual(output.read_bytes(), original)
                metadata.assert_not_called()
                writer.assert_not_called()

    def test_gcs_only_failed_run_status_is_archived_before_remote_status_is_replaced(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = self.config(root)
            failed = failed_report()
            prefix = f"gs://test-bucket/sundays/{SUNDAY}/post-live-subtitles/{SLUG}"
            marker_uri, status_uri = prefix + "/timeline/job-report.json", prefix + "/run-status.json"
            old_status = {"schemaVersion": 1, "sunday": SUNDAY, "sourceUrl": SOURCE,
                "status": "failed", "currentStage": "downloaded", "blocker": {"stage": "downloaded", "reason": "duration mismatch"}}
            remote = {marker_uri: failed, status_uri: old_status}
            audio = root / SUNDAY / SLUG / "download/source_audio.m4a"
            audio.parent.mkdir(parents=True)
            audio.write_bytes(b"repaired complete source")
            def writer(uri, text):
                remote[uri] = json.loads(text)
            with mock.patch.object(generation, "probe_archive_audio", return_value=PROBE), mock.patch.object(timeline.build_multistage_post_live_timeline, "build_multistage_timeline", side_effect=fake_timeline), mock.patch("builtins.print"):
                report = timeline.run_job(make_args(root, config.state_file,
                        resume_failed_timeline=supervisor.json_digest(failed), persist_run_status=True),
                    metadata_loader=lambda _: {"live_status": "was_live", "duration": 3600},
                    runner=mock.Mock(side_effect=AssertionError("Cache should be reused")),
                    uploader=lambda *_: None, marker_reader=lambda uri: copy.deepcopy(remote.get(uri)),
                    marker_writer=writer, handoff_reader=lambda _: None,
                    notifier=lambda *_: {"status": "not_configured"})
            self.assertEqual(report["status"], "requires_operator_review")
            archived = report["resumedFailure"]["runStatusArchives"]
            self.assertEqual(len(archived), 1)
            self.assertEqual(archived[0]["sha256"], supervisor.json_digest(old_status))
            self.assertEqual(remote[archived[0]["gcs"]], old_status)
            self.assertEqual(json.loads(Path(archived[0]["local"]).read_text()), old_status)
            self.assertEqual(remote[status_uri]["stages"]["downloaded"]["status"], "complete")

    def test_nonresume_gcs_failure_survives_missing_or_unready_metadata(self):
        for metadata in [None, {"live_status": "is_live", "is_live": True}]:
            with self.subTest(metadata=metadata), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                config = self.config(root)
                failed = failed_report()
                writer = mock.Mock()
                with mock.patch("builtins.print"):
                    result = timeline.run_job(make_args(root, config.state_file, persist_run_status=True),
                        metadata_loader=lambda _: metadata, marker_reader=lambda _: copy.deepcopy(failed), marker_writer=writer)
                self.assertEqual(result, failed)
                writer.assert_not_called()
                self.assertFalse((root / SUNDAY / SLUG / "run-status.json").exists())

    def test_recovery_tool_still_runs_at_most_once_and_decision_accepts_action(self):
        config = supervisor.SupervisorConfig(SUNDAY, "unused", gcs_bucket=None)
        runtime = agent.SupervisorRuntime(config, execute=True)
        wrapper = ToolContext(context=runtime, tool_name="run_timeline_probe", tool_call_id="test-resume", tool_arguments="{}")
        result = {"status": "requires_operator_review"}
        async def invoke_twice():
            first = await agent.run_timeline_probe.on_invoke_tool(wrapper, "{}")
            second = await agent.run_timeline_probe.on_invoke_tool(wrapper, "{}")
            return json.loads(first), json.loads(second)
        with mock.patch.object(supervisor, "run_timeline_probe", return_value=result) as execute:
            first, second = asyncio.run(invoke_twice())
        self.assertEqual(first["status"], "requires_operator_review")
        self.assertEqual(second["status"], "skipped")
        execute.assert_called_once()
        decision = agent.SupervisorDecision(status="advanced", action="resume_failed_timeline", summary_zh="已重验来源并恢复时间线。", human_action_required=False)
        self.assertEqual(decision.action, "resume_failed_timeline")
        self.assertIn("or resume_failed_timeline", agent.SUPERVISOR_INSTRUCTIONS)


class TimelineDurationMetadataTest(unittest.TestCase):
    def test_public_metadata_fills_only_same_video_duration(self):
        data_api = {"id": "5GuhLMPflds", "live_status": "was_live", "title": "Original source title"}
        for public, accepts in [
            ({"id": "5GuhLMPflds", "duration": 3600, "title": "Different title"}, True),
            ({"id": "wrongSource1", "duration": 3600}, False),
            ({"id": "5GuhLMPflds"}, False), (None, False),
        ]:
            with self.subTest(public=public), mock.patch.object(timeline, "access_secret", return_value="private-key"), mock.patch.object(timeline.youtube_data_api, "video_metadata", return_value=copy.deepcopy(data_api)), mock.patch.object(timeline, "youtube_metadata", return_value=public) as metadata:
                result, diagnostics = timeline.youtube_metadata_with_data_api(SOURCE, api_key_secret="secret-name", yt_dlp="yt-dlp", cookies_path=Path("private-cookies.txt"))
            metadata.assert_called_once_with(SOURCE, yt_dlp="yt-dlp", cookies_path=None)
            self.assertEqual(result["title"], data_api["title"])
            self.assertTrue(diagnostics["fallbackUsed"])
            if accepts:
                self.assertEqual(result["duration"], 3600)
            else:
                with self.assertRaises(generation.ArchiveAudioValidationError):
                    generation.archive_expected_duration(result)


if __name__ == "__main__":
    unittest.main()
