import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_sunday_evidence_bundle.py"
SPEC = importlib.util.spec_from_file_location("run_sunday_evidence_bundle", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def args(**overrides):
    values = {
        "sunday": "2026-06-28",
        "session_id": "worker-test",
        "artifact_location": "local",
        "work_root": Path("/tmp/sermon-worker"),
        "artifact_bucket": "sermon-zh-artifacts-ai-for-god",
        "artifact_prefix": "sundays",
        "realtime_session_id": "rt_test",
        "realtime_events_jsonl": None,
        "realtime_location": "local",
        "realtime_event_dir": Path("/tmp/sermon-realtime-events"),
        "realtime_event_gcs_prefix": None,
        "allow_missing_realtime": False,
        "allow_missing_stable_correction": False,
        "require_readable_sunday_artifacts": True,
        "out": None,
        "evidence_matrix_out": None,
        "goal_audit_out": None,
        "bundle_report_out": None,
        "cloud_run_config_report": None,
        "cloud_run_api_preflight_report": None,
        "realtime_audio_source_preflight_report": None,
        "server_realtime_contract_report": None,
        "web_realtime_contract_report": None,
        "public_caption_view_runtime_report": None,
        "realtime_public_sse_smoke_report": None,
        "realtime_openai_smoke_report": None,
        "realtime_session_validation_report": None,
        "stable_correction_contract_report": None,
        "offline_archive_preflight_report": None,
        "offline_chain_validation_report": None,
        "offline_asr_chain_validation_report": None,
        "offline_asr_smoke_report": None,
        "offline_translation_report": None,
        "sunday_manifest_validation_report": None,
        "openai_model_access_preflight_report": None,
        "openai_alternative_model_access_preflight_report": [],
        "cloud_run_update_plan": None,
        "cloud_run_update_execution": None,
        "dry_run": True,
    }
    values.update(overrides)
    return type("Args", (), values)()


class RunSundayEvidenceBundleTest(unittest.TestCase):
    def test_builds_local_validation_command(self):
        command = mod.build_validation_command(args())
        joined = " ".join(command)

        self.assertIn("validate_production_readiness.py", joined)
        self.assertIn("/tmp/sermon-worker/2026-06-28/worker-test/artifacts/report.json", command)
        self.assertIn("/tmp/sermon-worker/2026-06-28/worker-test/web/playback-simulation.generated.js", command)
        self.assertIn("gs://sermon-zh-artifacts-ai-for-god/sundays/2026-06-28/cloud-manifest.json", command)
        self.assertIn("/tmp/sermon-realtime-events/rt_test.jsonl", command)
        self.assertIn("--require-readable-sunday-artifacts", command)

    def test_builds_gcs_validation_command_with_realtime_mirror(self):
        command = mod.build_validation_command(
            args(
                artifact_location="gcs",
                realtime_location="gcs",
                realtime_event_gcs_prefix="gs://sermon-zh-artifacts-ai-for-god/realtime-events",
                realtime_session_id="rt bad/id",
            )
        )

        self.assertIn(
            "gs://sermon-zh-artifacts-ai-for-god/sundays/2026-06-28/runs/worker-test/artifacts/report.json",
            command,
        )
        self.assertIn(
            "gs://sermon-zh-artifacts-ai-for-god/sundays/2026-06-28/runs/worker-test/artifacts/sermon.zh.live-aligned.srt",
            command,
        )
        self.assertIn(
            "gs://sermon-zh-artifacts-ai-for-god/realtime-events/2026-06-28/rt_bad_id.jsonl",
            command,
        )

    def test_requires_realtime_session_unless_explicitly_allowed(self):
        with self.assertRaises(SystemExit):
            mod.validate_args(args(realtime_session_id=None, allow_missing_realtime=False))

        mod.validate_args(args(realtime_session_id=None, allow_missing_realtime=True))

    def test_requires_bucket_for_gcs_artifacts(self):
        with self.assertRaises(SystemExit):
            mod.validate_args(args(artifact_location="gcs", artifact_bucket=None))

    def test_reads_realtime_session_id_from_smoke_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "realtime-smoke-report.json"
            report.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "sessionId": "rt_from_report",
                        "realtimeEventsJsonl": "gs://bucket/realtime-events/2026-06-28/rt_from_report.jsonl",
                    }
                ),
                encoding="utf-8",
            )

            session_id = mod.realtime_session_id_from_report(str(report))
            evidence = mod.realtime_evidence_from_report(str(report))

        self.assertEqual(session_id, "rt_from_report")
        self.assertEqual(
            evidence["realtimeEventsJsonl"],
            "gs://bucket/realtime-events/2026-06-28/rt_from_report.jsonl",
        )

    def test_parse_args_uses_realtime_smoke_report_when_session_id_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "realtime-smoke-report.json"
            report.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "sessionId": "rt_from_report",
                        "realtimeEventsJsonl": "gs://bucket/realtime-events/2026-06-28/rt_from_report.jsonl",
                    }
                ),
                encoding="utf-8",
            )
            argv = [
                "run_sunday_evidence_bundle.py",
                "--sunday",
                "2026-06-28",
                "--session-id",
                "worker-test",
                "--artifact-bucket",
                "sermon-zh-artifacts-ai-for-god",
                "--realtime-smoke-report",
                str(report),
            ]
            original_argv = mod.sys.argv
            try:
                mod.sys.argv = argv
                parsed = mod.parse_args()
            finally:
                mod.sys.argv = original_argv

        self.assertEqual(parsed.realtime_session_id, "rt_from_report")
        self.assertEqual(parsed.realtime_events_jsonl, "gs://bucket/realtime-events/2026-06-28/rt_from_report.jsonl")

    def test_explicit_realtime_jsonl_is_used_before_derived_path(self):
        command = mod.build_validation_command(
            args(realtime_events_jsonl="gs://custom/events.jsonl", realtime_session_id="rt_test")
        )

        values = [value for index, value in enumerate(command) if index and command[index - 1] == "--realtime-events-jsonl"]
        self.assertEqual(values, ["gs://custom/events.jsonl"])

    def test_dry_run_prints_command_without_secret_references(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "readiness.json"
            bundle = Path(tmp) / "bundle.json"
            argv = [
                "run_sunday_evidence_bundle.py",
                "--sunday",
                "2026-06-28",
                "--session-id",
                "worker-test",
                "--artifact-bucket",
                "sermon-zh-artifacts-ai-for-god",
                "--realtime-session-id",
                "rt_test",
                "--out",
                str(out),
                "--bundle-report-out",
                str(bundle),
                "--dry-run",
            ]
            original_argv = mod.sys.argv
            original_stdout = mod.sys.stdout
            stdout = io.StringIO()
            try:
                mod.sys.argv = argv
                mod.sys.stdout = stdout
                exit_code = mod.main()
            finally:
                mod.sys.argv = original_argv
                mod.sys.stdout = original_stdout
            payload = json.loads(stdout.getvalue())
            written = json.loads(bundle.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "planned")
        self.assertEqual(written["status"], "planned")
        self.assertEqual(written["bundleReport"], str(bundle))
        self.assertEqual(payload["realtimeEventsJsonl"], "/tmp/sermon-realtime-events/rt_test.jsonl")
        self.assertFalse(payload["apiKeyMaterialIncluded"])
        self.assertFalse(payload["secretResourceNamesIncluded"])
        self.assertNotIn("/secrets/", stdout.getvalue())

    def test_builds_matrix_and_goal_audit_commands(self):
        command_args = args(
            out=Path("artifacts/evidence/readiness.json"),
            evidence_matrix_out=Path("artifacts/evidence/matrix.json"),
            goal_audit_out=Path("artifacts/evidence/audit.json"),
            cloud_run_config_report="artifacts/evidence/cloud-run-config.json",
            cloud_run_api_preflight_report="artifacts/evidence/cloud-run-api.json",
            realtime_public_sse_smoke_report="artifacts/evidence/public-sse.json",
            server_realtime_contract_report="artifacts/evidence/server-realtime-contract.json",
            web_realtime_contract_report="artifacts/evidence/web-realtime-contract.json",
            public_caption_view_runtime_report="artifacts/evidence/public-caption-view-runtime.json",
            realtime_openai_smoke_report="artifacts/evidence/realtime-smoke.json",
            realtime_session_validation_report="artifacts/evidence/realtime-session.json",
            stable_correction_contract_report="artifacts/evidence/stable-correction-contract.json",
            offline_archive_preflight_report="artifacts/evidence/offline-archive.json",
            offline_chain_validation_report="artifacts/evidence/offline-chain.json",
            offline_asr_chain_validation_report="artifacts/evidence/no-caption-offline-chain.json",
            offline_asr_smoke_report="artifacts/evidence/asr-smoke.json",
            offline_translation_report="artifacts/evidence/offline-translation.json",
            sunday_manifest_validation_report="artifacts/evidence/sunday-manifest-validation.json",
            openai_model_access_preflight_report="artifacts/evidence/model-access.json",
            openai_alternative_model_access_preflight_report=["artifacts/evidence/model-access-gpt-5.5.json"],
            cloud_run_update_plan="artifacts/evidence/update-plan.json",
            cloud_run_update_execution="artifacts/evidence/update-execution.json",
        )

        commands = mod.build_bundle_commands(command_args)
        matrix = commands["productionEvidenceMatrix"]
        audit = commands["productionGoalAudit"]

        self.assertIn("collect_production_evidence_matrix.py", " ".join(matrix))
        self.assertIn("audit_production_goal_readiness.py", " ".join(audit))
        self.assertIn("--offline-chain-validation-report", matrix)
        self.assertIn("--offline-asr-chain-validation-report", matrix)
        self.assertIn("--server-realtime-contract-report", matrix)
        self.assertIn(str(mod.REPO_ROOT / "artifacts/evidence/server-realtime-contract.json"), matrix)
        self.assertIn("--web-realtime-contract-report", matrix)
        self.assertIn(str(mod.REPO_ROOT / "artifacts/evidence/web-realtime-contract.json"), matrix)
        self.assertIn("--public-caption-view-runtime-report", matrix)
        self.assertIn(str(mod.REPO_ROOT / "artifacts/evidence/public-caption-view-runtime.json"), matrix)
        self.assertIn("--stable-correction-contract-report", matrix)
        self.assertIn(str(mod.REPO_ROOT / "artifacts/evidence/stable-correction-contract.json"), matrix)
        self.assertIn(str(mod.REPO_ROOT / "artifacts/evidence/offline-chain.json"), matrix)
        self.assertIn(str(mod.REPO_ROOT / "artifacts/evidence/no-caption-offline-chain.json"), matrix)
        self.assertIn("--offline-asr-smoke-report", matrix)
        self.assertIn("--sunday-manifest-validation-report", matrix)
        self.assertIn(str(mod.REPO_ROOT / "artifacts/evidence/sunday-manifest-validation.json"), matrix)
        self.assertIn("--openai-alternative-model-access-preflight-report", matrix)
        self.assertIn(str(mod.REPO_ROOT / "artifacts/evidence/model-access-gpt-5.5.json"), matrix)
        self.assertIn("--realtime-session-validation-report", matrix)
        self.assertIn("--update-plan", matrix)
        self.assertIn("--evidence-matrix-report", audit)
        self.assertIn(str(mod.REPO_ROOT / "artifacts/evidence/matrix.json"), audit)

    def test_parse_args_defaults_readiness_report_when_matrix_requested(self):
        argv = [
            "run_sunday_evidence_bundle.py",
            "--sunday",
            "2026-06-28",
            "--session-id",
            "worker-test",
            "--artifact-bucket",
            "sermon-zh-artifacts-ai-for-god",
            "--realtime-session-id",
            "rt_test",
            "--evidence-matrix-out",
            "artifacts/evidence/matrix.json",
            "--dry-run",
        ]
        original_argv = mod.sys.argv
        try:
            mod.sys.argv = argv
            parsed = mod.parse_args()
        finally:
            mod.sys.argv = original_argv

        self.assertEqual(
            parsed.out,
            Path("artifacts/evidence/2026-06-28-worker-test-production-readiness.json"),
        )

    def test_dry_run_includes_bundle_commands(self):
        argv = [
            "run_sunday_evidence_bundle.py",
            "--sunday",
            "2026-06-28",
            "--session-id",
            "worker-test",
            "--artifact-bucket",
            "sermon-zh-artifacts-ai-for-god",
            "--realtime-session-id",
            "rt_test",
            "--evidence-matrix-out",
            "artifacts/evidence/matrix.json",
            "--goal-audit-out",
            "artifacts/evidence/audit.json",
            "--offline-chain-validation-report",
            "artifacts/evidence/offline-chain.json",
            "--dry-run",
        ]
        original_argv = mod.sys.argv
        original_stdout = mod.sys.stdout
        stdout = io.StringIO()
        try:
            mod.sys.argv = argv
            mod.sys.stdout = stdout
            exit_code = mod.main()
        finally:
            mod.sys.argv = original_argv
            mod.sys.stdout = original_stdout

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "planned")
        self.assertIn("productionReadiness", payload["commands"])
        self.assertIn("productionEvidenceMatrix", payload["commands"])
        self.assertIn("productionGoalAudit", payload["commands"])
        self.assertIn("--offline-chain-validation-report", payload["commands"]["productionEvidenceMatrix"])

    def test_main_writes_bundle_report_after_running_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            readiness = root / "readiness.json"
            bundle = root / "bundle.json"
            argv = [
                "run_sunday_evidence_bundle.py",
                "--sunday",
                "2026-06-28",
                "--session-id",
                "worker-test",
                "--artifact-bucket",
                "sermon-zh-artifacts-ai-for-god",
                "--realtime-session-id",
                "rt_test",
                "--out",
                str(readiness),
                "--bundle-report-out",
                str(bundle),
            ]
            stdout = io.StringIO()
            original_argv = mod.sys.argv
            original_stdout = mod.sys.stdout
            try:
                mod.sys.argv = argv
                mod.sys.stdout = stdout
                with mock.patch.object(
                    mod,
                    "run_bundle_commands",
                    return_value={"productionReadiness": {"returnCode": 2, "stdout": "", "stderr": "failed"}},
                ):
                    exit_code = mod.main()
            finally:
                mod.sys.argv = original_argv
                mod.sys.stdout = original_stdout

            written = json.loads(bundle.read_text(encoding="utf-8"))
            printed = json.loads(stdout.getvalue())

        self.assertEqual(exit_code, 2)
        self.assertEqual(written["status"], "failed")
        self.assertEqual(written["returnCode"], 2)
        self.assertEqual(printed["bundleReport"], str(bundle))
        self.assertFalse(written["apiKeyMaterialIncluded"])
        self.assertFalse(written["secretResourceNamesIncluded"])

    def test_bundle_writes_placeholder_readiness_report_when_validator_exits_before_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            readiness = root / "readiness.json"
            matrix = root / "matrix.json"
            audit = root / "audit.json"
            commands = {
                "productionReadiness": ["python", "validate.py", "--out", str(readiness)],
                "productionEvidenceMatrix": [
                    "python",
                    "matrix.py",
                    "--production-readiness-report",
                    str(readiness),
                    "--out",
                    str(matrix),
                ],
                "productionGoalAudit": [
                    "python",
                    "audit.py",
                    "--production-readiness-report",
                    str(readiness),
                    "--out",
                    str(audit),
                ],
            }
            calls = []

            def fake_run(command, **_kwargs):
                calls.append(command)
                if "validate.py" in command:
                    return completed(returncode=2, stderr="missing offline artifacts")
                return completed(returncode=0, stdout='{"status":"ok"}')

            with mock.patch.object(mod.subprocess, "run", side_effect=fake_run):
                results = mod.run_bundle_commands(commands)

            placeholder = json.loads(readiness.read_text(encoding="utf-8"))

        self.assertEqual([call[1] for call in calls], ["validate.py", "matrix.py", "audit.py"])
        self.assertEqual(results["productionReadiness"]["returnCode"], 2)
        self.assertEqual(placeholder["status"], "failed")
        self.assertEqual(placeholder["failedChecks"], ["production_readiness_report_missing"])
        self.assertFalse(placeholder["apiKeyMaterialIncluded"])
        self.assertFalse(placeholder["secretResourceNamesIncluded"])
        self.assertIn("missing offline artifacts", placeholder["commandStderrTail"])

    def test_bundle_does_not_overwrite_existing_failed_readiness_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            readiness = root / "readiness.json"
            readiness.write_text(json.dumps({"status": "failed", "failedChecks": ["offline_chain"]}), encoding="utf-8")
            commands = {
                "productionReadiness": ["python", "validate.py", "--out", str(readiness)],
                "productionEvidenceMatrix": [
                    "python",
                    "matrix.py",
                    "--production-readiness-report",
                    str(readiness),
                ],
            }

            with mock.patch.object(
                mod.subprocess,
                "run",
                side_effect=[
                    completed(returncode=2, stderr="validator failed"),
                    completed(returncode=2, stderr="matrix failed"),
                ],
            ):
                mod.run_bundle_commands(commands)

            payload = json.loads(readiness.read_text(encoding="utf-8"))

        self.assertEqual(payload["failedChecks"], ["offline_chain"])

    def test_bundle_writes_placeholder_matrix_report_when_matrix_exits_before_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            readiness = root / "readiness.json"
            matrix = root / "matrix.json"
            audit = root / "audit.json"
            readiness.write_text(json.dumps({"status": "failed", "failedChecks": ["offline_chain"]}), encoding="utf-8")
            commands = {
                "productionReadiness": ["python", "validate.py", "--out", str(readiness)],
                "productionEvidenceMatrix": ["python", "matrix.py", "--out", str(matrix)],
                "productionGoalAudit": [
                    "python",
                    "audit.py",
                    "--evidence-matrix-report",
                    str(matrix),
                    "--out",
                    str(audit),
                ],
            }
            calls = []

            def fake_run(command, **_kwargs):
                calls.append(command)
                if "matrix.py" in command:
                    return completed(returncode=2, stderr="missing optional evidence report")
                return completed(returncode=0, stdout='{"status":"ok"}')

            with mock.patch.object(mod.subprocess, "run", side_effect=fake_run):
                results = mod.run_bundle_commands(commands)

            placeholder = json.loads(matrix.read_text(encoding="utf-8"))

        self.assertEqual([call[1] for call in calls], ["validate.py", "matrix.py", "audit.py"])
        self.assertEqual(results["productionEvidenceMatrix"]["returnCode"], 2)
        self.assertEqual(placeholder["status"], "incomplete")
        self.assertEqual(placeholder["matrix"][0]["id"], "production_evidence_matrix")
        self.assertFalse(placeholder["apiKeyMaterialIncluded"])
        self.assertFalse(placeholder["secretResourceNamesIncluded"])
        self.assertIn("missing optional evidence report", placeholder["matrix"][0]["observed"]["commandStderrTail"])

    def test_bundle_does_not_overwrite_existing_matrix_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            readiness = root / "readiness.json"
            matrix = root / "matrix.json"
            readiness.write_text(json.dumps({"status": "failed"}), encoding="utf-8")
            matrix.write_text(json.dumps({"status": "incomplete", "matrix": [{"id": "existing"}]}), encoding="utf-8")
            commands = {
                "productionReadiness": ["python", "validate.py", "--out", str(readiness)],
                "productionEvidenceMatrix": ["python", "matrix.py", "--out", str(matrix)],
                "productionGoalAudit": ["python", "audit.py", "--evidence-matrix-report", str(matrix)],
            }

            with mock.patch.object(
                mod.subprocess,
                "run",
                side_effect=[
                    completed(returncode=2, stderr="validator failed"),
                    completed(returncode=2, stderr="matrix failed"),
                    completed(returncode=2, stderr="audit failed"),
                ],
            ):
                mod.run_bundle_commands(commands)

            payload = json.loads(matrix.read_text(encoding="utf-8"))

        self.assertEqual(payload["matrix"][0]["id"], "existing")

def completed(*, returncode: int, stdout: str = "", stderr: str = ""):
    return type("Completed", (), {"returncode": returncode, "stdout": stdout, "stderr": stderr})()


if __name__ == "__main__":
    unittest.main()
