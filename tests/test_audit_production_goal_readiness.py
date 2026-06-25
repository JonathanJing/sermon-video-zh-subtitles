import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "audit_production_goal_readiness.py"
SPEC = importlib.util.spec_from_file_location("audit_production_goal_readiness", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def args_for(reports=None, cloud_run_config_report=None):
    return SimpleNamespace(
        production_readiness_report=reports or [],
        cloud_run_config_report=cloud_run_config_report,
        cloud_run_api_preflight_report=None,
        evidence_matrix_report=None,
        out=None,
    )


def args_for_all(
    reports=None,
    cloud_run_config_report=None,
    cloud_run_api_preflight_report=None,
    evidence_matrix_report=None,
):
    return SimpleNamespace(
        production_readiness_report=reports or [],
        cloud_run_config_report=cloud_run_config_report,
        cloud_run_api_preflight_report=cloud_run_api_preflight_report,
        evidence_matrix_report=evidence_matrix_report,
        out=None,
    )


def readiness_report(*, offline_decision: str, include_input_transcript: bool = True) -> dict:
    realtime_counts = {
        "realtimeCaptionEvents": 2,
        "stableCorrectionEvents": 1,
    }
    if include_input_transcript:
        realtime_counts["realtimeInputTranscriptEvents"] = 1
        realtime_counts["inputTranscriptEvents"] = 1
    return {
        "schemaVersion": 1,
        "status": "ok",
        "offline": {
            "status": "ok",
            "notRealtimeChain": "pass",
            "checks": {"not_realtime_chain": "pass"},
            "offlineRoute": {
                "strategy": "captions_first_then_asr",
                "decision": offline_decision,
                "selectedSourceKind": "live_archive" if offline_decision == "use_caption_track" else "openai_asr",
                "asrFallbackRequired": offline_decision == "use_asr_fallback",
                "audioExtractionAttempted": offline_decision == "use_asr_fallback",
            },
        },
        "sundayManifest": {"status": "ok"},
        "realtime": {
            "status": "ok",
            "counts": realtime_counts,
        },
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def cloud_run_config_report() -> dict:
    return {
        "schemaVersion": 1,
        "status": "ok",
        "failedChecks": [],
        "cloudRun": {
            "service": "sermon-zh-caption-web",
            "maxInstances": 1,
            "configuredEnv": [
                "APP_TIMEZONE",
                "SERMON_ARTIFACT_BUCKET",
                "SERMON_ARTIFACT_PREFIX",
                "REALTIME_EVENT_GCS_PREFIX",
                "OPENAI_API_KEY_SECRET",
                "OPERATOR_ADMIN_TOKEN",
                "INTERNAL_TASK_TOKEN",
            ],
        },
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def cloud_run_api_preflight_report(*, skipped_realtime_session=False, missing_metadata_check=False) -> dict:
    checks = []
    if not skipped_realtime_session:
        checks.append({"name": "realtime_local_session_create", "state": "pass"})
        if not missing_metadata_check:
            checks.append({"name": "realtime_local_session_metadata", "state": "pass"})
    return {
        "schemaVersion": 1,
        "status": "ok",
        "failedChecks": [],
        "warnings": ["realtime_local_session_create"] if skipped_realtime_session else [],
        "checks": checks,
        "realtimeSession": None
        if skipped_realtime_session
        else {
            "status": 201,
            "ready": True,
            "sessionId": "rt_test",
            "eventTokenReturned": True,
            "model": "gpt-realtime-translate",
            "targetLanguage": "zh",
            "audioSourceKind": "ipad_mic",
        },
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
        "eventTokenIncluded": False,
    }


def evidence_matrix_report(*, realtime_live="pass", stable="pass", caption="pass", asr="pass") -> dict:
    states = {
        "cloud_run_realtime_config": "pass",
        "cloud_run_api_preflight": "pass",
        "realtime_audio_source_preflight": "pass",
        "realtime_public_sse_contract": "pass",
        "realtime_live": realtime_live,
        "stable_correction": stable,
        "offline_archive_preflight": "pass",
        "offline_caption_route": caption,
        "offline_asr_route": asr,
        "cloud_run_gcs_manifest": "pass",
    }
    return {
        "schemaVersion": 1,
        "status": "complete" if all(value == "pass" for value in states.values()) else "incomplete",
        "summary": {
            "passed": sum(1 for value in states.values() if value == "pass"),
            "failed": sum(1 for value in states.values() if value == "fail"),
            "warnings": sum(1 for value in states.values() if value == "warn"),
            "missing": sum(1 for value in states.values() if value == "missing"),
            "total": len(states),
        },
        "matrix": [matrix_row(key, value) for key, value in states.items()],
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def matrix_row(key: str, value: str) -> dict:
    row = {"id": key, "state": value}
    if key == "offline_caption_route" and value == "pass":
        row["observed"] = {
            "notRealtimeChain": "pass",
            "translation": {"model": "gpt-5.5-mini"},
            "offlineRoute": {"decision": "use_caption_track"},
        }
    return row


class AuditProductionGoalReadinessTest(unittest.TestCase):
    def test_without_external_reports_local_implementation_passes_but_goal_is_incomplete(self):
        report = mod.audit_goal_readiness(args_for())

        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["summary"]["localFailed"], 0)
        self.assertEqual(report["summary"]["externalMissing"], 8)
        self.assertTrue(all(check["state"] == "pass" for check in report["localImplementation"]))
        self.assertIn(
            "browser_webrtc_public_caption_view",
            [check["id"] for check in report["localImplementation"]],
        )
        self.assertIn(
            "server_media_worker_realtime_path",
            [check["id"] for check in report["localImplementation"]],
        )
        self.assertIn("external_realtime_live", report["failedChecks"])
        self.assertIn("external_offline_asr_route", report["failedChecks"])
        self.assertIn("external_offline_not_realtime_chain", report["failedChecks"])
        self.assertIn("external_cloud_run_realtime_config", report["failedChecks"])
        self.assertIn("external_cloud_run_api_preflight", report["failedChecks"])
        self.assertFalse(report["apiKeyMaterialIncluded"])
        self.assertEqual(report["missingReportPaths"], [])

    def test_missing_optional_report_paths_are_recorded_instead_of_crashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            matrix = root / "matrix.json"
            matrix.write_text(json.dumps(evidence_matrix_report(stable="fail")), encoding="utf-8")
            missing_readiness = root / "missing-readiness.json"
            missing_preflight = root / "missing-preflight.json"

            report = mod.audit_goal_readiness(
                args_for_all(
                    reports=[str(missing_readiness)],
                    cloud_run_api_preflight_report=str(missing_preflight),
                    evidence_matrix_report=str(matrix),
                )
            )

        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["productionReadinessReports"], 0)
        self.assertIn(str(missing_readiness), report["missingReportPaths"])
        self.assertIn(str(missing_preflight), report["missingReportPaths"])
        self.assertIn("external_stable_correction", report["failedChecks"])

    def test_repeated_readiness_reports_and_cloud_run_config_can_satisfy_external_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            caption = root / "caption-route.json"
            asr = root / "asr-route.json"
            cloud_run = root / "cloud-run-config.json"
            preflight = root / "cloud-run-preflight.json"
            caption.write_text(json.dumps(readiness_report(offline_decision="use_caption_track")), encoding="utf-8")
            asr.write_text(
                json.dumps(readiness_report(offline_decision="use_asr_fallback", include_input_transcript=False)),
                encoding="utf-8",
            )
            cloud_run.write_text(json.dumps(cloud_run_config_report()), encoding="utf-8")
            preflight.write_text(json.dumps(cloud_run_api_preflight_report()), encoding="utf-8")

            report = mod.audit_goal_readiness(
                args_for_all([str(caption), str(asr)], str(cloud_run), str(preflight))
            )

        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["failedChecks"], [])
        self.assertEqual(report["summary"]["totalFailed"], 0)
        self.assertEqual(report["nextActions"], [])
        self.assertEqual(report["productionReadinessReports"], 2)

    def test_realtime_readiness_requires_caption_and_input_transcript_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            caption = root / "caption-route.json"
            asr = root / "asr-route.json"
            cloud_run = root / "cloud-run-config.json"
            preflight = root / "cloud-run-preflight.json"
            caption.write_text(
                json.dumps(readiness_report(offline_decision="use_caption_track", include_input_transcript=False)),
                encoding="utf-8",
            )
            asr.write_text(
                json.dumps(readiness_report(offline_decision="use_asr_fallback", include_input_transcript=False)),
                encoding="utf-8",
            )
            cloud_run.write_text(json.dumps(cloud_run_config_report()), encoding="utf-8")
            preflight.write_text(json.dumps(cloud_run_api_preflight_report()), encoding="utf-8")

            report = mod.audit_goal_readiness(
                args_for_all([str(caption), str(asr)], str(cloud_run), str(preflight))
            )

        self.assertEqual(report["status"], "incomplete")
        self.assertIn("external_realtime_live", report["failedChecks"])

    def test_readiness_reports_without_cloud_run_config_still_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            caption = root / "caption-route.json"
            asr = root / "asr-route.json"
            caption.write_text(json.dumps(readiness_report(offline_decision="use_caption_track")), encoding="utf-8")
            asr.write_text(json.dumps(readiness_report(offline_decision="use_asr_fallback")), encoding="utf-8")

            report = mod.audit_goal_readiness(args_for([str(caption), str(asr)]))

        self.assertEqual(report["status"], "incomplete")
        self.assertIn("external_cloud_run_realtime_config", report["failedChecks"])

    def test_preflight_must_include_realtime_session_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            caption = root / "caption-route.json"
            asr = root / "asr-route.json"
            cloud_run = root / "cloud-run-config.json"
            preflight = root / "cloud-run-preflight.json"
            caption.write_text(json.dumps(readiness_report(offline_decision="use_caption_track")), encoding="utf-8")
            asr.write_text(json.dumps(readiness_report(offline_decision="use_asr_fallback")), encoding="utf-8")
            cloud_run.write_text(json.dumps(cloud_run_config_report()), encoding="utf-8")
            preflight.write_text(
                json.dumps(cloud_run_api_preflight_report(skipped_realtime_session=True)),
                encoding="utf-8",
            )

            report = mod.audit_goal_readiness(
                args_for_all([str(caption), str(asr)], str(cloud_run), str(preflight))
            )

        self.assertEqual(report["status"], "incomplete")
        self.assertIn("external_cloud_run_api_preflight", report["failedChecks"])

    def test_preflight_must_include_realtime_session_metadata_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            caption = root / "caption-route.json"
            asr = root / "asr-route.json"
            cloud_run = root / "cloud-run-config.json"
            preflight = root / "cloud-run-preflight.json"
            caption.write_text(json.dumps(readiness_report(offline_decision="use_caption_track")), encoding="utf-8")
            asr.write_text(json.dumps(readiness_report(offline_decision="use_asr_fallback")), encoding="utf-8")
            cloud_run.write_text(json.dumps(cloud_run_config_report()), encoding="utf-8")
            preflight.write_text(
                json.dumps(cloud_run_api_preflight_report(missing_metadata_check=True)),
                encoding="utf-8",
            )

            report = mod.audit_goal_readiness(
                args_for_all([str(caption), str(asr)], str(cloud_run), str(preflight))
            )

        self.assertEqual(report["status"], "incomplete")
        self.assertIn("external_cloud_run_api_preflight", report["failedChecks"])

    def test_single_caption_route_report_still_requires_asr_external_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            caption = root / "caption-route.json"
            caption.write_text(json.dumps(readiness_report(offline_decision="use_caption_track")), encoding="utf-8")

            report = mod.audit_goal_readiness(args_for([str(caption)]))

        self.assertEqual(report["status"], "incomplete")
        self.assertIn("external_offline_asr_route", report["failedChecks"])

    def test_evidence_matrix_can_satisfy_external_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            matrix = Path(tmp) / "matrix.json"
            matrix.write_text(json.dumps(evidence_matrix_report()), encoding="utf-8")

            report = mod.audit_goal_readiness(args_for_all(evidence_matrix_report=str(matrix)))

        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["failedChecks"], [])
        self.assertEqual(report["productionReadinessReports"], 0)
        self.assertEqual(report["productionEvidenceMatrix"]["status"], "complete")

    def test_evidence_matrix_keeps_warning_rows_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            matrix = Path(tmp) / "matrix.json"
            matrix.write_text(
                json.dumps(evidence_matrix_report(realtime_live="pass", stable="fail", caption="fail", asr="warn")),
                encoding="utf-8",
            )

            report = mod.audit_goal_readiness(args_for_all(evidence_matrix_report=str(matrix)))

        self.assertEqual(report["status"], "incomplete")
        self.assertNotIn("external_realtime_live", report["failedChecks"])
        self.assertIn("external_stable_correction", report["failedChecks"])
        self.assertIn("external_offline_caption_route", report["failedChecks"])
        self.assertIn("external_offline_asr_route", report["failedChecks"])
        self.assertIn("external_offline_not_realtime_chain", report["failedChecks"])
        self.assertEqual(report["summary"]["externalMissing"], 4)
        actions = {action["id"]: action for action in report["nextActions"]}
        self.assertEqual(actions["external_stable_correction"]["sourceRow"], "stable_correction")
        self.assertEqual(actions["external_stable_correction"]["sourceRowState"], "fail")
        self.assertEqual(actions["external_stable_correction"]["state"], "missing_external_evidence")
        self.assertEqual(actions["external_offline_asr_route"]["sourceRow"], "offline_asr_route")
        self.assertEqual(actions["external_offline_asr_route"]["sourceRowState"], "warn")
        self.assertEqual(actions["external_offline_asr_route"]["state"], "partial_external_evidence")

    def test_matrix_next_actions_are_carried_into_goal_audit(self):
        matrix = evidence_matrix_report(stable="fail", caption="fail", asr="warn")
        for row in matrix["matrix"]:
            if row["id"] == "stable_correction":
                row["nextAction"] = "Fix gpt-5.5-mini model access."
            if row["id"] == "offline_asr_route":
                row["nextAction"] = "Run a real no-caption YouTube archive."

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "matrix.json"
            path.write_text(json.dumps(matrix), encoding="utf-8")

            report = mod.audit_goal_readiness(args_for_all(evidence_matrix_report=str(path)))

        actions = {action["id"]: action for action in report["nextActions"]}
        stable_action = actions["external_stable_correction"]
        asr_action = actions["external_offline_asr_route"]
        self.assertEqual(stable_action["sourceRow"], "stable_correction")
        self.assertEqual(stable_action["nextAction"], "Fix gpt-5.5-mini model access.")
        self.assertEqual(asr_action["sourceRow"], "offline_asr_route")
        self.assertEqual(asr_action["nextAction"], "Run a real no-caption YouTube archive.")

    def test_offline_caption_route_requires_explicit_not_realtime_chain_evidence(self):
        matrix = evidence_matrix_report()
        for row in matrix["matrix"]:
            if row["id"] == "offline_caption_route":
                row.pop("observed", None)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "matrix.json"
            path.write_text(json.dumps(matrix), encoding="utf-8")

            report = mod.audit_goal_readiness(args_for_all(evidence_matrix_report=str(path)))

        self.assertEqual(report["status"], "incomplete")
        self.assertNotIn("external_offline_caption_route", report["failedChecks"])
        self.assertIn("external_offline_not_realtime_chain", report["failedChecks"])


if __name__ == "__main__":
    unittest.main()
