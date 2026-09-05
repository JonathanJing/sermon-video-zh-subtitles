import json
import os
from contextlib import ExitStack, contextmanager
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import run_weekly_dubbing as runner
import check_weekly_timing as timing
from scripts.sermon_accounting import ENV_KEYS, accounting_session
from scripts import sermon_accounting as accounting
from test_resume_integrity import candidate_fixture


class WeeklyAccountingTests(unittest.TestCase):
    def setUp(self):
        identity = patch.object(accounting, "execution_identity", return_value={"gitCommit": None})
        identity.start()
        self.addCleanup(identity.stop)

    @contextmanager
    def fixture(self, folder, cached=False, block_count=1, unit_count=1):
        work = Path(folder) / "weekly"
        work.mkdir()
        job = {"week": "2026-09-06", "sourceDurationSeconds": unit_count * 2,
               "blocks": [{"id": i, "en": "English", "zh": "中文"} for i in range(block_count)],
               "units": [{"id": i, "blockId": i % block_count, "text": "中文", "gapAfterSeconds": .45} for i in range(unit_count)]}
        (work / "job.json").write_text(json.dumps(job), encoding="utf-8")
        render_report = {"jobSha256": runner.sha256(work / "job.json"), "generationSeconds": 12.5,
                         "durationSeconds": unit_count, "cues": []}

        def render_files():
            (work / "render").mkdir(exist_ok=True)
            for i, unit in enumerate(job["units"]):
                wav = work / f"render/unit-{i:04d}.wav"
                wav.write_bytes(f"fake WAV {i}".encode())
                runner.write_json(wav.with_suffix(".json"), {"unit": unit, "sha256": runner.sha256(wav),
                    "identity": {"jobSha256": render_report["jobSha256"]}, "durationSeconds": 1})
            raw = work / "render/chinese.raw.wav"
            raw.write_bytes(b"fake combined WAV")
            render_report["sha256"] = runner.sha256(raw)
            runner.write_json(work / "render/report.json", render_report)

        if cached:
            for name in ("render/report.json", "audio/library.json", "source-alignment/report.json",
                         "audio/asr-screening.json", "synchronization/report.json"):
                path = work / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}", encoding="utf-8")
            render_files()
        commands = []

        def command(argv, **kwargs):
            commands.append({"argv": argv, "stage": os.environ.get("SERMON_ACCOUNTING_STAGE"),
                             "runId": os.environ.get("SERMON_ACCOUNTING_RUN_ID")})
            if os.environ.get("SERMON_ACCOUNTING_STAGE") == "transfer_download":
                render_files()
            return subprocess.CompletedProcess(argv, 0)

        mocks = {}
        values = {"validated_job": job, "validate_cached_stages": None, "validate_render": render_report,
                  "validate_natural": {}, "validate_alignment": {}, "validate_screening": None,
                  "validate_timing": None, "validate_candidate": {"jobSha256": runner.sha256(work / "job.json")},
                  "assemble": None}
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {key: "" for key in ENV_KEYS}))
            stack.enter_context(patch.object(sys, "argv", ["run_weekly_dubbing.py", "--work", str(work),
                "--remote-checkpoint", runner.REMOTE_ROOT + "/sermon-fixture/checkpoint", "--mlx-python", "/fixture/python"]))
            stack.enter_context(patch("builtins.print"))
            for name, value in values.items():
                mocks[name] = stack.enter_context(patch.object(runner, name, return_value=value))
            process = stack.enter_context(patch.object(runner.subprocess, "run", side_effect=command))
            output = stack.enter_context(patch.object(runner.subprocess, "check_output", return_value=json.dumps({"reason": "duration_or_signal", "unit": 0})))
            yield SimpleNamespace(work=work, mocks=mocks, process=process, output=output,
                                  command=command, commands=commands)

    def read_accounting(self, folder):
        folder = Path(folder)
        events = [json.loads(line) for line in (folder / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
        finished = [row for row in events if row["event"] == "stage_finished"]
        return events, summary, finished

    def test_fresh_run_records_separate_local_execution_and_no_invented_usage(self):
        with tempfile.TemporaryDirectory() as tmp, self.fixture(tmp) as f:
            runner.main()
            events, summary, finished = self.read_accounting(f.work / "accounting")
            names = [row["stage"] for row in finished]
            self.assertEqual(names, ["job_validation", "cache_validation", "transfer_upload", "render",
                "transfer_download", "render_validation", "assemble", "source_alignment", "local_asr",
                "timing", "candidate_validation", "weekly_dubbing"])
            self.assertTrue(all(not row["cacheHit"] and row["status"] == "completed" for row in finished))
            self.assertEqual(events[0]["metadata"]["jobSha256"], runner.sha256(f.work / "job.json"))
            self.assertEqual(summary["runs"][0]["status"], "completed")
            workload = {row["stage"]: row["metrics"] for row in events if row["event"] == "workload"}
            self.assertEqual(workload["render_cache"]["localCachedUnitCount"], 0)
            self.assertEqual(workload["render_output"]["newlyAvailableOutputUnitCount"], 1)
            self.assertEqual(workload["render_output"]["modelTimerSeconds"], 12.5)
            self.assertIsNone(workload["render_output"]["modelTimerIsHistorical"])
            self.assertFalse(workload["render_output"]["modelTimerIsPureModelTime"])
            self.assertFalse(workload["render_output"]["modelTimerIncludesLoadOrPriorRetries"])
            self.assertIsNone(workload["render_output"]["modelInputUnitCount"])
            self.assertIsNone(workload["render_output"]["currentRunGeneratedUnitCount"])
            self.assertTrue(workload["candidate_evidence"]["candidateReady"])
            self.assertFalse(workload["candidate_evidence"]["humanApproval"])
            for row in summary["stages"]:
                if row["stage"] == "weekly_dubbing":
                    continue
                self.assertEqual(row["billing"], "local")
                self.assertEqual(row["tokenStatus"], "not_applicable")
                self.assertIsNone(row["inputTokens"])
                self.assertIsNone(row["outputTokens"])
                self.assertEqual(row["costStatus"], "no_api_receipts")
                self.assertEqual(row["apiAttempts"], 0)
                self.assertGreaterEqual(row["elapsedSeconds"], 0)
            self.assertEqual([row["stage"] for row in f.commands], ["transfer_upload", "transfer_upload",
                "render", "transfer_download", "source_alignment", "local_asr", "timing"])
            receipt = json.loads((f.work / "workflow-receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["humanAudioReview"], "pending")
            self.assertFalse(receipt["renderImported"])

    def test_verified_cache_records_hits_and_never_launches_commands(self):
        with tempfile.TemporaryDirectory() as tmp, self.fixture(tmp, cached=True) as f:
            runner.main()
            _, _, finished = self.read_accounting(f.work / "accounting")
            self.assertEqual({row["stage"] for row in finished if row["cacheHit"]},
                {"render", "assemble", "source_alignment", "local_asr", "timing"})
            f.process.assert_not_called()
            f.output.assert_not_called()
            f.mocks["assemble"].assert_not_called()
            for name in ("validate_cached_stages", "validate_render", "validate_natural", "validate_alignment",
                         "validate_screening", "validate_timing", "validate_candidate"):
                f.mocks[name].assert_called_once()
            receipt = json.loads((f.work / "workflow-receipt.json").read_text(encoding="utf-8"))
            self.assertTrue(receipt["renderImported"])
            self.assertIsNone(receipt["remoteWork"])

    def test_invalid_inputs_and_cache_failures_are_recorded_before_any_model(self):
        for method, message, failed_stage in (("validated_job", "frozen evidence changed", "job_validation"),
                                            ("validate_cached_stages", "cache evidence changed", "cache_validation")):
            with self.subTest(method=method), tempfile.TemporaryDirectory() as tmp, self.fixture(tmp, cached=True) as f:
                f.mocks[method].side_effect = ValueError(message)
                with self.assertRaisesRegex(ValueError, message):
                    runner.main()
                events, summary, finished = self.read_accounting(f.work / "accounting")
                failed = [row for row in finished if row["status"] == "failed"]
                self.assertEqual([row["stage"] for row in failed], [failed_stage, "weekly_dubbing"])
                self.assertTrue(all(row["errorType"] == "ValueError" for row in failed))
                self.assertEqual(summary["runs"][0]["status"], "failed")
                self.assertFalse(any(message in json.dumps(row) for row in events))
                f.process.assert_not_called()
                f.mocks["assemble"].assert_not_called()
                self.assertFalse((f.work / "workflow-receipt.json").exists())

    def test_recoverable_render_attempts_are_recorded_without_changing_retry_path(self):
        with tempfile.TemporaryDirectory() as tmp, self.fixture(tmp) as f:
            failed = False

            def fail_once(argv, **kwargs):
                nonlocal failed
                result = f.command(argv, **kwargs)
                if os.environ.get("SERMON_ACCOUNTING_STAGE") == "render" and not failed:
                    failed = True
                    raise subprocess.CalledProcessError(1, argv)
                return result

            f.process.side_effect = fail_once
            runner.main()
            _, summary, finished = self.read_accounting(f.work / "accounting")
            render = [row for row in finished if row["stage"] == "render"]
            self.assertEqual([row["status"] for row in render], ["failed", "completed"])
            self.assertEqual([row["status"] for row in finished if row["stage"] == "render_recovery"], ["completed"])
            f.output.assert_called_once()
            repair = [row for row in f.commands if row["stage"] == "render_recovery"]
            self.assertEqual(len(repair), 1)
            self.assertIn("/work/retry_weekly_unit.py", repair[0]["argv"][-1])
            self.assertIn("--seed 142", repair[0]["argv"][-1])
            render_summary = next(row for row in summary["stages"] if row["stage"] == "render")
            self.assertEqual(render_summary["stageAttempts"], 2)
            self.assertEqual(render_summary["failedStages"], 1)
            self.assertEqual(summary["runs"][0]["status"], "completed")

    def test_local_asr_failure_stops_later_stages_and_records_failure(self):
        with tempfile.TemporaryDirectory() as tmp, self.fixture(tmp) as f:
            def fail_asr(argv, **kwargs):
                result = f.command(argv, **kwargs)
                if os.environ.get("SERMON_ACCOUNTING_STAGE") == "local_asr":
                    raise subprocess.CalledProcessError(1, argv)
                return result

            f.process.side_effect = fail_asr
            with self.assertRaises(subprocess.CalledProcessError):
                runner.main()
            _, summary, finished = self.read_accounting(f.work / "accounting")
            self.assertEqual([row["stage"] for row in finished if row["status"] == "failed"], ["local_asr", "weekly_dubbing"])
            self.assertNotIn("timing", [row["stage"] for row in finished])
            f.mocks["validate_screening"].assert_not_called()
            f.mocks["validate_candidate"].assert_not_called()
            self.assertFalse((f.work / "workflow-receipt.json").exists())
            self.assertEqual(summary["runs"][0]["status"], "failed")

    def test_parent_accounting_is_inherited_by_runner_and_subprocess_commands(self):
        with tempfile.TemporaryDirectory() as tmp, self.fixture(tmp) as f:
            parent = Path(tmp) / "parent-accounting"
            with accounting_session(parent, "saturday") as session:
                runner.main()
                self.assertTrue(f.commands)
                self.assertTrue(all(row["runId"] == session["runId"] for row in f.commands))
            events, summary, finished = self.read_accounting(parent)
            self.assertEqual(len([row for row in events if row["event"] == "run_started"]), 1)
            self.assertEqual(len(summary["runs"]), 1)
            parent_stage = next(row for row in finished if row["stage"] == "saturday")
            weekly = next(row for row in finished if row["stage"] == "weekly_dubbing")
            self.assertEqual(weekly["parentSpanId"], parent_stage["spanId"])
            self.assertTrue(all(row["parentSpanId"] == weekly["spanId"] for row in finished
                                if row["stage"] not in ("saturday", "weekly_dubbing")))
            self.assertFalse((f.work / "accounting").exists())
            self.assertTrue(all(not os.environ.get(key) for key in ENV_KEYS))

    def test_job_workload_counts_actual_blocks_units_and_historical_render_timer(self):
        with tempfile.TemporaryDirectory() as tmp, self.fixture(tmp, cached=True, block_count=55, unit_count=119) as f:
            runner.main()
            events, _, _ = self.read_accounting(f.work / "accounting")
            workload = {row["stage"]: row["metrics"] for row in events if row["event"] == "workload"}
            self.assertEqual(workload["weekly_job"]["blockCount"], 55)
            self.assertEqual(workload["weekly_job"]["unitCount"], 119)
            output = workload["render_output"]
            self.assertEqual(output["acceptedUnitCount"], 119)
            self.assertEqual(output["localCachedUnitCountAtStart"], 119)
            self.assertEqual(output["newlyAvailableOutputUnitCount"], 0)
            self.assertEqual(output["preservedLocalReceiptCount"], 119)
            self.assertEqual(output["currentRunGeneratedUnitCount"], 0)
            self.assertEqual(output["modelInputUnitCount"], 0)
            self.assertEqual(output["modelTimerSeconds"], 12.5)
            self.assertTrue(output["modelTimerIsHistorical"])
            self.assertEqual(output["renderReportSha256"], runner.sha256(f.work / "render/report.json"))
            f.process.assert_not_called()

    def revision_fixture(self, base):
        parent, work = Path(base) / "parent", Path(base) / "revised"
        parent.mkdir()
        work.mkdir()
        candidate_fixture(parent)
        candidate_fixture(work)
        job = runner.read(work / "job.json")
        job["revisionOf"] = {"path": str(parent), "jobSha256": runner.sha256(parent / "job.json")}
        runner.write_json(work / "job.json", job)
        identity = runner.render_identity(work / "job.json", job["voice"]["checkpointSha256"])
        runner.write_json(work / "render/identity.json", identity)
        for i in range(2):
            path = work / f"render/unit-{i:04d}.json"
            receipt = runner.read(path)
            receipt["identity"] = identity
            if i == 0:
                original_wav = parent / "render/unit-0000.wav"
                original = runner.read(original_wav.with_suffix(".json"))
                receipt["reusedFrom"] = {"path": str(original_wav), "unitId": 0,
                    "wavSha256": runner.sha256(original_wav), "receiptSha256": runner.sha256(original_wav.with_suffix(".json")),
                    "generationIdentity": original["identity"]}
            runner.write_json(path, receipt)
        render = {**runner.read(work / "render/report.json"), **identity, "generationSeconds": 45.25}
        runner.write_json(work / "render/report.json", render)
        runner.write_json(work / "revision-report.json", {"jobSha256": identity["jobSha256"],
            "parentJobSha256": job["revisionOf"]["jobSha256"], "reusedUnits": [{"unitId": 0, "parentUnitId": 0}],
            "regenerateUnitIds": [1]})
        return parent, work, job, runner.validate_render(work, job)

    def test_parent_revision_delta_is_receipt_bound_and_not_model_input_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent, work, job, render = self.revision_fixture(tmp)
            before = {str(p): runner.sha256(p) for p in Path(tmp).rglob("*") if p.is_file()}
            with patch.dict(os.environ, {key: "" for key in ENV_KEYS}), accounting_session(work / "accounting", "fixture"):
                runner.record_render_workload(work, job, render, {}, False)
            events, _, _ = self.read_accounting(work / "accounting")
            metrics = next(row["metrics"] for row in events if row["event"] == "workload")
            self.assertEqual(metrics["newlyAvailableOutputUnitCount"], 2)
            self.assertEqual(metrics["parentReusedUnitCount"], 1)
            self.assertEqual(metrics["revisionRegenerateUnitCount"], 1)
            self.assertTrue(metrics["revisionEvidenceVerified"])
            self.assertIsNone(metrics["currentRunGeneratedUnitCount"])
            self.assertIsNone(metrics["modelInputUnitCount"])
            self.assertTrue(all(runner.sha256(Path(path)) == digest for path, digest in before.items()))

    def test_unverified_revision_receipts_do_not_claim_reuse_or_change_existing_gates(self):
        for case in ("report_hash", "receipt_hash", "changed_parent_wav", "unknown_ids", "pronunciation_ids"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                parent, work, job, _ = self.revision_fixture(tmp)
                report = runner.read(work / "revision-report.json")
                if case == "report_hash":
                    report["jobSha256"] = "stale"
                elif case == "unknown_ids":
                    report["regenerateUnitIds"] = [99]
                elif case == "pronunciation_ids":
                    report.pop("reusedUnits")
                    report["reusedUnitIds"] = [0]
                elif case == "receipt_hash":
                    path = work / "render/unit-0000.json"
                    receipt = runner.read(path)
                    receipt["reusedFrom"]["receiptSha256"] = "stale"
                    runner.write_json(path, receipt)
                else:
                    (parent / "render/unit-0000.wav").write_bytes(b"changed")
                runner.write_json(work / "revision-report.json", report)
                metrics = runner.revision_workload(work, job)
                if case == "pronunciation_ids":
                    self.assertTrue(metrics["revisionEvidenceVerified"])
                    self.assertEqual(metrics["parentReusedUnitCount"], 1)
                else:
                    self.assertFalse(metrics["revisionEvidenceVerified"])
                    self.assertIsNone(metrics["parentReusedUnitCount"])
                    self.assertIsNone(metrics["revisionRegenerateUnitCount"])

    def test_independent_sync_assembly_records_evidence_and_preserves_existing_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = candidate_fixture(Path(tmp))
            review = runner.read(work / "audio-review.json")
            review.update(humanApproval=True, checks={"sameVideoSynchronization": "pass"})
            runner.write_json(work / "audio-review.json", review)
            def write_wav(path, wave, rate, **kwargs):
                Path(path).write_bytes(b"fake synchronized WAV")
            def normalize(raw, mp3):
                Path(mp3).write_bytes(b"fake synchronized MP3")
                return {"sha256": runner.sha256(mp3), "durationSeconds": 10, "fullDecode": "pass"}
            fake_np = SimpleNamespace(zeros=lambda n, dtype: [0.0] * n, float32=float)
            fake_sf = SimpleNamespace(read=lambda *a, **k: ([.25] * 445, 100), write=write_wav)
            with patch.dict(os.environ, {key: "" for key in ENV_KEYS}), patch.dict(sys.modules, {"numpy": fake_np, "soundfile": fake_sf}), \
                 patch.object(timing, "normalize_mp3", side_effect=normalize) as encode, \
                 patch.object(sys, "argv", ["check_weekly_timing.py", "--work", str(work), "--assemble"]), patch("builtins.print"):
                timing.main()
                first = runner.sha256(work / "synchronization/zh-synced.mp3")
                with self.assertRaisesRegex(ValueError, "Preserve the existing synchronized audio"):
                    timing.main()
                encode.assert_called_once()
            self.assertEqual(runner.sha256(work / "synchronization/zh-synced.mp3"), first)
            events, summary, finished = self.read_accounting(work / "accounting")
            self.assertEqual([row["status"] for row in summary["runs"]], ["completed", "failed"])
            self.assertTrue(all(row["workflow"] == "dubbing_sync_assembly" for row in summary["runs"]))
            self.assertEqual([row["status"] for row in finished if row["stage"] == "sync_assembly"], ["completed", "failed"])
            output = next(row["metrics"] for row in events if row["event"] == "workload" and row["stage"] == "synchronized_output")
            self.assertEqual(output["mp3Sha256"], first)
            self.assertEqual(output["cueCount"], 2)
            self.assertEqual(output["assemblySha256"], runner.sha256(work / "synchronization/assembly.json"))
            self.assertFalse(output["humanApproval"])
            self.assertFalse(runner.read(work / "audio-review-synced.json")["humanApproval"])

    def test_sync_assembly_timing_failure_is_accounted_and_does_not_encode(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = candidate_fixture(Path(tmp))
            render = runner.read(work / "render/report.json")
            render["cues"][0]["end"] = 6
            runner.write_json(work / "render/report.json", render)
            with patch.dict(os.environ, {key: "" for key in ENV_KEYS}), patch.object(timing, "normalize_mp3") as encode, \
                 patch.object(sys, "argv", ["check_weekly_timing.py", "--work", str(work), "--assemble"]):
                with self.assertRaisesRegex(ValueError, "Timing repair required"):
                    timing.main()
                encode.assert_not_called()
            _, summary, finished = self.read_accounting(work / "accounting")
            self.assertEqual(summary["runs"][0]["status"], "failed")
            self.assertEqual([row["stage"] for row in finished if row["status"] == "failed"], ["sync_assembly", "dubbing_sync_assembly"])
            self.assertFalse((work / "synchronization/zh-synced.raw.wav").exists())


if __name__ == "__main__":
    unittest.main()
