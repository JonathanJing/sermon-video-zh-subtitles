"""Focused offline tests for the isolated Supervisor model comparison."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.experiments import supervisor_ab as ab


class SupervisorABTests(unittest.TestCase):
    def setUp(self):
        self.cases = ab.load_cases(ab.FIXTURES)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_fixture_set_covers_complete_wait_human_and_executable_states(self):
        self.assertEqual(len(self.cases), 12)
        actions = {case["snapshot"]["recommendedAction"]["action"] for case in self.cases}
        self.assertTrue({"complete", "wait_for_source", "request_window_approval",
                         "run_timeline_probe", "run_reading_pdf_generation"} <= actions)
        self.assertEqual(len({case["id"] for case in self.cases}), len(self.cases))

    def test_both_arms_share_input_and_tools_and_use_only_shadow(self):
        with patch.object(ab, "AgentsAPIClient", side_effect=AssertionError("no network")):
            report = ab.run_experiment(self.cases, backend="replay", root=self.root)
        self.assertEqual(report["interpretation"], "simulated_protocol_only")
        self.assertEqual(len(report["cases"]), 24)
        by_case = {}
        for row in report["cases"]:
            by_case.setdefault(row["caseId"], []).append(row)
            expected_action = next(case["snapshot"]["recommendedAction"]["action"]
                                   for case in self.cases if case["id"] == row["caseId"])
            self.assertEqual(row["outboundSnapshot"]["recommendedAction"]["action"], expected_action)
            self.assertEqual(row["sessionStatus"], "completed")
            self.assertTrue(row["verifiedDecision"]["modelDecisionAccepted"])
            self.assertIsNone(row["requestIds"])
            self.assertIsNone(row["usage"])
            self.assertEqual(row["costStatus"], "unknown")
            self.assertEqual([call["name"] for call in row["toolTrace"]],
                             ["inspect_production_state", "submit_supervisor_decision"])
            self.assertEqual(row["toolCalls"], 2)
        for pair in by_case.values():
            self.assertEqual(pair[0]["commonPayloadSha256"], pair[1]["commonPayloadSha256"])
            self.assertEqual(pair[0]["outboundSha256"], pair[1]["outboundSha256"])

    def test_outbound_state_excludes_artifact_and_identity_fields(self):
        case = copy.deepcopy(self.cases[0])
        case["snapshot"].update(source={"url": "https://private.invalid"},
                                locations={"artifact": "/private/path"},
                                windowApproval={"valid": True, "approvedBy": "private-name"})
        row = ab.run_case(case, ab.MODELS[0], backend="replay", root=self.root)
        wire = json.dumps(row["outboundSnapshot"])
        for secret in ("private.invalid", "/private/path", "private-name"):
            self.assertNotIn(secret, wire)

    def test_false_completion_claim_is_rejected_by_real_validator(self):
        case = copy.deepcopy(next(c for c in self.cases if c["id"] == "approval-required"))
        case["script"][1]["arguments"].update(status="complete", action="complete",
                                                 human_action_required=False)
        row = ab.run_case(case, ab.MODELS[0], backend="replay", root=self.root)
        self.assertEqual(row["deterministicExpected"],
                         {"status": "blocked", "action": "request_window_approval",
                          "human_action_required": True})
        self.assertTrue(row["falseCompletionClaim"])
        self.assertFalse(row["verifiedDecision"]["modelDecisionAccepted"])

    def test_mutating_call_cannot_execute_in_shadow_even_if_scripted(self):
        case = copy.deepcopy(next(c for c in self.cases if c["id"] == "timeline-ready-shadow"))
        case["script"].insert(1, {"name": "run_timeline_probe", "arguments": {}})
        with patch.object(ab.supervisor.production, "run_timeline_probe",
                          side_effect=AssertionError("production mutation")):
            row = ab.run_case(case, ab.MODELS[0], backend="replay", root=self.root)
        self.assertEqual(row["toolTrace"][1]["output"],
                         {"status": "blocked", "reasonCode": "shadow_mode"})

    def test_fixture_loader_rejects_mutating_calls(self):
        bad = copy.deepcopy(self.cases)
        bad[0]["script"][0]["name"] = "run_timeline_probe"
        path = self.root / "bad.json"
        path.write_text(json.dumps(bad), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "non-read-only"):
            ab.load_cases(path)

    def test_request_id_is_not_inferred_from_session_or_turn_id(self):
        self.assertIsNone(ab.request_ids({"session_id": "sess_1", "turns": [{"id": "turn_1"}]}))
        self.assertEqual(ab.request_ids({"turns": [{"request_id": "req_2"}],
                                         "items": [{"requestId": "req_1"}]}),
                         ["req_1", "req_2"])

    def test_live_trace_recovers_function_names_from_items(self):
        directory = self.root / "session"
        receipts = directory / "tool-results"
        receipts.mkdir(parents=True)
        (receipts / "a.json").write_text(json.dumps({"call_id": "call_1",
            "output": {"status": "recorded"}, "error": None}), encoding="utf-8")
        trace = ab.live_tool_trace({"items": [{"type": "function_call",
            "call_id": "call_1", "name": "submit_supervisor_decision"}]}, directory)
        self.assertEqual(trace, [{"name": "submit_supervisor_decision",
                                  "output": {"status": "recorded"}, "error": None}])


if __name__ == "__main__":
    unittest.main()
