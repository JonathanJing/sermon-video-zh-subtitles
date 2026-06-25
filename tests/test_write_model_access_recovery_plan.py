import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import scripts.write_model_access_recovery_plan as mod


class WriteModelAccessRecoveryPlanTest(unittest.TestCase):
    def test_plan_documents_required_model_recovery_without_substitution(self):
        report = mod.build_plan(
            Namespace(
                sunday="2026-06-28",
                required_model="gpt-5.5-mini",
                alternative_model="gpt-5.5",
                required_report=Path("missing-required.json"),
                alternative_report=Path("missing-alternative.json"),
                offline_run_root="artifacts/evidence/offline-caption-route",
                realtime_events_jsonl="<REALTIME_SESSION_EVENTS_JSONL>",
                realtime_session_id="<REALTIME_SESSION_ID>",
                backend_url="<BACKEND_BASE_URL>",
                out=None,
            )
        )

        self.assertEqual(report["status"], "waiting_for_required_model_access")
        self.assertTrue(report["modelPolicy"]["doNotSubstitute"])
        self.assertTrue(report["modelPolicy"]["alternativeModelIsSideEvidenceOnly"])
        commands = json.dumps(report["commands"])
        self.assertIn("run_openai_model_access_preflight.py", commands)
        self.assertIn("translate_playback_with_openai.py", commands)
        self.assertIn("stabilize_realtime_deltas_with_openai.py", commands)
        self.assertIn("validate_realtime_session.py", commands)
        self.assertIn("--require-stable-correction", commands)
        self.assertIn("gpt-5.5-mini", commands)
        self.assertIn("refresh_production_preflight_evidence.py", commands)
        self.assertIn("write_production_go_live_sequence.py", commands)
        self.assertNotIn("collect_production_evidence_matrix.py", commands)
        translate_command = next(command for command in report["commands"] if "scripts/translate_playback_with_openai.py" in command)
        playback_js = "artifacts/evidence/offline-caption-route/web/playback-simulation.generated.js"
        self.assertEqual(translate_command[translate_command.index("--input") + 1], playback_js)
        self.assertEqual(translate_command[translate_command.index("--out") + 1], playback_js)
        self.assertIn("--api-key-secret", translate_command)
        rendered = json.dumps(report)
        self.assertNotIn("projects/", rendered)
        self.assertNotIn("/secrets/", rendered)
        self.assertNotIn("evt_", rendered)
        self.assertFalse(report["apiKeyMaterialIncluded"])
        self.assertFalse(report["secretResourceNamesIncluded"])
        self.assertFalse(report["eventTokenIncluded"])

    def test_observed_reports_set_ready_when_required_model_access_is_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            required = root / "required.json"
            alternative = root / "alternative.json"
            required.write_text(
                json.dumps(model_report("gpt-5.5-mini", "ok", http_status=200)),
                encoding="utf-8",
            )
            alternative.write_text(
                json.dumps(model_report("gpt-5.5", "ok", http_status=200)),
                encoding="utf-8",
            )
            report = mod.build_plan(
                Namespace(
                    sunday="2026-06-28",
                    required_model="gpt-5.5-mini",
                    alternative_model="gpt-5.5",
                    required_report=required,
                    alternative_report=alternative,
                    offline_run_root="artifacts/evidence/offline-caption-route",
                    realtime_events_jsonl="<REALTIME_SESSION_EVENTS_JSONL>",
                    realtime_session_id="<REALTIME_SESSION_ID>",
                    backend_url="<BACKEND_BASE_URL>",
                    out=None,
                )
            )

        self.assertEqual(report["status"], "ready_to_rerun_model_routes")
        self.assertEqual(report["observedRequiredModelAccess"]["status"], "ok")
        self.assertEqual(report["observedAlternativeModelAccess"]["model"], "gpt-5.5")

    def test_main_writes_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "plan.json"
            original_argv = sys.argv
            try:
                sys.argv = [
                    "write_model_access_recovery_plan.py",
                    "--sunday",
                    "2026-06-28",
                    "--required-report",
                    str(Path(tmp) / "missing.json"),
                    "--alternative-report",
                    str(Path(tmp) / "missing-alt.json"),
                    "--out",
                    str(out),
                ]
                exit_code = mod.main()
            finally:
                sys.argv = original_argv

            written = json.loads(out.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(written["requiredModel"], "gpt-5.5-mini")


def model_report(model, status, http_status=None):
    return {
        "schemaVersion": 1,
        "status": "ok" if status == "ok" else "failed",
        "checks": [
            {
                "name": f"responses_model:{model}",
                "state": "pass" if status == "ok" else "fail",
                "observed": {
                    "endpoint": "responses",
                    "model": model,
                    "status": status,
                    "httpStatus": http_status,
                },
            }
        ],
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


if __name__ == "__main__":
    unittest.main()
