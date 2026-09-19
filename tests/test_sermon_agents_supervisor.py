"""Offline production-boundary tests for the Agents API supervisor adapter."""

import argparse
import asyncio
from contextlib import nullcontext
import copy
from dataclasses import asdict, replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from scripts import run_codex_local_sermon_production as local_entry
from scripts import run_sermon_production_supervisor_agent as entry
from scripts import sermon_agents_supervisor as mod
from scripts.sermon_agents_api import AgentsAPIError, run_agent_session
from scripts.sermon_production_supervisor import SupervisorConfig


def snapshot(action="run_timeline_probe", human=False):
    return {"recommendedAction": {"action": action, "humanActionRequired": human,
                                  "reason": "Synthetic persisted evidence"}}


def decision(action="complete", status="complete"):
    return {"status": status, "action": action, "summary_zh": "合成测试状态",
            "human_action_required": False, "evidence": []}


def action(name, call_id, arguments=None):
    return {"type": "function_call", "turn_id": "turn_1", "call_id": call_id,
            "name": name, "arguments": arguments or {}}


class FakeClient:
    """An in-memory remote session; no credentials, network, model, or production."""

    def __init__(self, batches=(), *, terminal="completed", creation_error=False, cancel_status=None):
        self.batches = list(batches)
        self.terminal = terminal
        self.creation_error = creation_error
        self.index = -1
        self.created = 0
        self.submitted = []
        self.cancelled = 0
        self.cancel_status = cancel_status

    def create_session(self, payload):
        self.created += 1
        self.payload = copy.deepcopy(payload)
        if self.creation_error:
            raise AgentsAPIError("transport_error")
        return {"id": "sess_1"}

    def retrieve_session(self, session_id):
        self.index += 1
        return {"required_actions": self.batches[self.index] if self.index < len(self.batches) else []}

    def list_turns(self, session_id):
        status = "running" if self.index < len(self.batches) else self.terminal
        if self.cancelled and self.cancel_status is not None:
            status = self.cancel_status
        return [{"id": "turn_1", "subagent_id": None, "status": status}]

    def list_items(self, session_id):
        return []

    def submit_tool_result(self, session_id, call, output=None, *, error=None):
        self.submitted.append({"call": call, "output": output, "error": error})

    def cancel(self, session_id):
        self.cancelled += 1
        return {}


class SupervisorBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = SupervisorConfig(sunday="2026-09-13", state_file=str(self.root / "source.json"),
                                       work_root=self.root / "work", gcs_bucket=None)
        self.current = snapshot()
        self.read = self.start_patch(patch.object(mod.production, "production_snapshot",
                                                   side_effect=lambda _: copy.deepcopy(self.current)))
        self.timeline = self.start_patch(patch.object(mod.production, "run_timeline_probe",
                                                       return_value={"status": "completed", "returnCode": 0}))
        self.generation = self.start_patch(patch.object(mod.production, "run_reading_pdf_generation",
                                                         return_value={"status": "completed", "returnCode": 0}))
        self.approval = self.start_patch(patch.object(mod.production, "approve_window",
                                                      side_effect=AssertionError("No remote approval authority")))
        self.receipts = []

        def accounting(*args, **kwargs):
            receipt = {}
            self.receipts.append(receipt)
            return nullcontext(receipt)

        self.start_patch(patch.object(mod.sermon_accounting, "sdk_invocation", side_effect=accounting))

    def start_patch(self, patcher):
        value = patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def tools(self, *, execute=True, directory=None):
        directory = directory or self.root / "tools"
        directory.mkdir(exist_ok=True)
        return mod.ProductionTools(self.config, execute, directory, entry.SupervisorDecision)

    def args(self, **changes):
        values = dict(mode="execute", model="gpt-6-astra", sunday=self.config.sunday,
                      max_turns=20, agent_timeout_seconds=60, out=self.root / "report.json",
                      agent_run_dir=None, resume_agent_session=False)
        values.update(changes)
        return argparse.Namespace(**values)

    def report(self, client, **changes):
        # Keep the real durable session and ProductionTools, removing only polling delay.
        def offline_runner(*args, **kwargs):
            return run_agent_session(*args, poll_seconds=0, **kwargs)
        with patch.object(mod, "run_agent_session", side_effect=offline_runner):
            return mod.session_report(self.args(**changes), self.config, entry.supervisor_instructions("agents-api"),
                                      entry.SupervisorDecision, entry.verify_decision, client=client)

    def test_shadow_exposes_only_inspection_and_submission_and_denies_mutation(self):
        definitions = mod.tool_definitions(False, entry.SupervisorDecision.model_json_schema())
        self.assertEqual([item["name"] for item in definitions],
                         ["inspect_production_state", "submit_supervisor_decision"])
        tools = self.tools(execute=False)
        tools("inspect_production_state", {})
        for name in ("run_timeline_probe", "run_approved_reading_pdf_generation"):
            self.assertEqual(tools(name, {})["reasonCode"], "shadow_mode")
        self.timeline.assert_not_called()
        self.generation.assert_not_called()
        self.approval.assert_not_called()

    def test_first_inspection_required_before_mutation_and_decision(self):
        tools = self.tools()
        self.assertEqual(tools("run_timeline_probe", {})["reasonCode"], "inspect_current_state_before_mutation")
        self.assertEqual(tools("submit_supervisor_decision", decision())["reasonCode"], "inspect_current_state_before_decision")
        self.timeline.assert_not_called()

    def test_stage_rechecks_fresh_state_and_human_requirement(self):
        for changed in (snapshot("request_window_approval", True), snapshot("run_timeline_probe", True)):
            with self.subTest(changed=changed):
                tools = self.tools()
                self.current = snapshot()
                tools("inspect_production_state", {})
                self.current = changed
                result = tools("run_timeline_probe", {})
                self.assertEqual(result["reasonCode"], "current_state_does_not_allow_stage")
        self.timeline.assert_not_called()

    def test_mutation_requires_new_inspection_before_submission(self):
        tools = self.tools()
        tools("inspect_production_state", {})
        self.assertEqual(tools("run_timeline_probe", {})["status"], "completed")
        self.assertEqual(tools("submit_supervisor_decision", decision())["status"], "blocked")
        tools("inspect_production_state", {})
        self.assertEqual(tools("submit_supervisor_decision", decision())["status"], "recorded")
        self.assertFalse(tools("submit_supervisor_decision", decision())["productionComplete"])

    def test_execute_submission_rejects_each_unattempted_stage_without_closing_session(self):
        for index, next_action in enumerate(("run_timeline_probe", "resume_failed_timeline",
                                             "run_reading_pdf_generation")):
            with self.subTest(action=next_action):
                self.current = snapshot(next_action)
                tools = self.tools(directory=self.root / f"early-{index}")
                tools("inspect_production_state", {})
                result = tools("submit_supervisor_decision", decision(next_action, "observed"))
                self.assertEqual(result["reasonCode"], "unattempted_executable_stage")
                self.assertTrue(result["requiresFreshInspection"])
                self.assertIsNone(tools.state["decision"])
                resumed = self.tools(directory=self.root / f"early-{index}")
                self.assertIsNone(resumed.state["decision"])
                resumed("inspect_production_state", {})
                tool = ("run_approved_reading_pdf_generation" if next_action == "run_reading_pdf_generation"
                        else "run_timeline_probe")
                self.assertEqual(resumed(tool, {})["status"], "completed")
        self.assertEqual(self.timeline.call_count, 2)
        self.generation.assert_called_once()

    def test_submission_rechecks_state_that_became_executable_since_inspect(self):
        self.current = snapshot("wait_for_source")
        tools = self.tools()
        tools("inspect_production_state", {})
        self.current = snapshot("run_timeline_probe")
        result = tools("submit_supervisor_decision", decision("wait_for_source", "observed"))
        self.assertEqual(result["reasonCode"], "unattempted_executable_stage")
        self.assertIsNone(tools.state["decision"])
        self.timeline.assert_not_called()

    def test_premature_remote_end_is_failure_and_does_not_execute_work_in_verifier(self):
        report = self.report(FakeClient([[action("inspect_production_state", "i1"),
                                          action("submit_supervisor_decision", "d1",
                                                 decision("run_timeline_probe", "observed"))]]))
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["agentSession"]["errorCode"], "structured_decision_missing")
        self.timeline.assert_not_called()
        self.generation.assert_not_called()

    def test_host_rejects_new_executable_work_after_recorded_submission(self):
        self.current = snapshot("complete")
        client = FakeClient([[action("inspect_production_state", "i1"),
                              action("submit_supervisor_decision", "d1", decision())]])
        original_submit = client.submit_tool_result

        def change_after_submission(session_id, call, output=None, *, error=None):
            original_submit(session_id, call, output, error=error)
            if call["name"] == "submit_supervisor_decision":
                self.current = snapshot("run_reading_pdf_generation")

        client.submit_tool_result = change_after_submission
        report = self.report(client)
        self.assertEqual(report["agentSession"]["status"], "completed")
        self.assertEqual(report["status"], "blocked")
        self.assertFalse(report["decision"]["modelDecisionAccepted"])
        self.assertIn("unattempted_executable_stage", report["decision"]["evidence"])
        self.generation.assert_not_called()

    def test_rejected_submit_can_advance_both_new_stages_and_complete(self):
        def timeline(_):
            self.current = snapshot("run_reading_pdf_generation")
            return {"status": "completed"}

        def generation(_):
            self.current = snapshot("complete")
            return {"status": "completed"}

        self.timeline.side_effect = timeline
        self.generation.side_effect = generation
        client = FakeClient([[action("inspect_production_state", "i1"),
                              action("submit_supervisor_decision", "early", decision()),
                              action("inspect_production_state", "i2"),
                              action("run_timeline_probe", "m1"),
                              action("inspect_production_state", "i3"),
                              action("submit_supervisor_decision", "early2", decision()),
                              action("inspect_production_state", "i4"),
                              action("run_approved_reading_pdf_generation", "m2"),
                              action("inspect_production_state", "i5"),
                              action("submit_supervisor_decision", "d1", decision())]])
        report = self.report(client)
        self.assertEqual(report["status"], "complete")
        self.timeline.assert_called_once()
        self.generation.assert_called_once()
        self.assertEqual([item["output"]["reasonCode"] for item in client.submitted
                          if item["call"]["call_id"].startswith("early")],
                         ["unattempted_executable_stage"] * 2)

    def test_attempted_failed_stage_returns_resumable_block_without_retry(self):
        self.timeline.return_value = {"status": "failed", "returnCode": 1}
        client = FakeClient([[action("inspect_production_state", "i1"),
                              action("run_timeline_probe", "m1"),
                              action("inspect_production_state", "i2"),
                              action("submit_supervisor_decision", "d1",
                                     decision("run_timeline_probe", "blocked"))]])
        report = self.report(client)
        self.assertEqual(report["status"], "blocked")
        self.assertFalse(report["decision"]["human_action_required"])
        self.assertIn("stage_attempted_wait_for_next_run", report["decision"]["evidence"])
        self.timeline.assert_called_once()

    def test_shadow_and_nonactionable_waits_allow_submission(self):
        for index, (execute, next_action, human) in enumerate((
                (False, "run_timeline_probe", False), (True, "wait_for_active_run", False),
                (True, "request_window_approval", True), (True, "complete", False))):
            with self.subTest(execute=execute, action=next_action):
                self.current = snapshot(next_action, human)
                tools = self.tools(execute=execute, directory=self.root / f"stops-{index}")
                tools("inspect_production_state", {})
                self.assertEqual(tools("submit_supervisor_decision", decision())["status"], "recorded")
        self.timeline.assert_not_called()
        self.generation.assert_not_called()

    def test_sdk_premature_final_is_blocked_by_host_verification(self):
        with patch("sys.argv", ["supervisor", "--sunday", self.config.sunday,
                                "--state-file", self.config.state_file, "--work-root", str(self.config.work_root),
                                "--gcs-bucket", "", "--mode", "execute", "--agent-backend", "sdk"]):
            args = entry.parse_args()
        with patch.object(entry.Runner, "run", new_callable=AsyncMock,
                          return_value=Mock(final_output=decision("run_timeline_probe", "observed"),
                                            context_wrapper=None)):
            report = asyncio.run(entry.run_agent(args))
        self.assertEqual(report["status"], "blocked")
        self.assertFalse(report["decision"]["modelDecisionAccepted"])
        self.assertFalse(report["decision"]["human_action_required"])
        self.assertIn("unattempted_executable_stage", report["decision"]["evidence"])
        self.timeline.assert_not_called()

    def test_stage_attempt_is_persisted_before_operation_raises(self):
        tools = self.tools()
        tools("inspect_production_state", {})
        self.timeline.side_effect = RuntimeError("Synthetic interrupted operation")
        with self.assertRaises(RuntimeError):
            tools("run_timeline_probe", {})
        resumed = self.tools()
        resumed("inspect_production_state", {})
        self.assertEqual(resumed("run_timeline_probe", {})["reasonCode"], "stage_already_attempted_in_session")
        self.timeline.assert_called_once()

    def test_generation_is_once_per_session_across_reload(self):
        self.current = snapshot("run_reading_pdf_generation")
        tools = self.tools()
        tools("inspect_production_state", {})
        tools("run_approved_reading_pdf_generation", {})
        resumed = self.tools()
        resumed("inspect_production_state", {})
        self.assertEqual(resumed("run_approved_reading_pdf_generation", {})["status"], "skipped")
        self.generation.assert_called_once()

    def test_unknown_tool_and_injected_arguments_are_rejected(self):
        tools = self.tools()
        for name, arguments in (("shell", {}), ("approve_window", {}),
                                ("inspect_production_state", {"state_file": "other.json"}),
                                ("run_timeline_probe", {"command": "anything"}),
                                ("run_approved_reading_pdf_generation", {"start_time": "00:00"})):
            with self.subTest(name=name), self.assertRaises(AgentsAPIError):
                tools(name, arguments)
        self.timeline.assert_not_called()
        self.generation.assert_not_called()
        self.approval.assert_not_called()

    def test_submission_cannot_add_approval_fields_or_change_existing_decision(self):
        self.current = snapshot("complete")
        tools = self.tools()
        tools("inspect_production_state", {})
        with self.assertRaises(AgentsAPIError):
            tools("submit_supervisor_decision", {**decision(), "humanApproval": True})
        tools("submit_supervisor_decision", decision())
        self.assertEqual(tools("submit_supervisor_decision", decision("other"))["reasonCode"], "decision_already_submitted")
        self.assertEqual(tools("run_timeline_probe", {})["reasonCode"], "decision_already_submitted")
        self.approval.assert_not_called()
        self.timeline.assert_not_called()

    def test_operation_output_hides_commands_and_configuration(self):
        self.timeline.return_value = {"status": "completed", "returnCode": 0, "command": ["private-command"],
                                      "stderr": "private-stderr", "config": {"private": "value"}}
        tools = self.tools()
        tools("inspect_production_state", {})
        result = tools("run_timeline_probe", {})
        self.assertEqual(set(result), {"status", "returnCode", "stage", "requiresFreshInspection"})

    def private_snapshot(self):
        marker = "PRIVATE_SENTINEL /Users/private/source.json synthetic-secret person@example.invalid"
        detail = {"status": marker, "reason": marker, "log": marker, "path": marker,
                  "source": {"url": marker, "title": marker, "email": marker},
                  "nested": {"approval": {"approvedBy": marker, "note": marker}}}
        return {
            "sunday": marker, "schemaVersion": marker, "slug": marker, "stateFile": marker,
            "configFingerprint": marker, "config": detail, "locations": detail, "logs": [detail],
            "recommendedAction": {"action": "run_timeline_probe", "reason": marker,
                                  "humanActionRequired": False, "details": detail},
            "source": detail, "liveSource": detail, "timeline": detail,
            "windowApproval": {**detail, "valid": True},
            "generation": {**detail, "status": "completed", "publication": {**detail, "status": "pass"}},
            "quality": {name: {**detail, "status": "pass"} for name in
                        ("readingEdition", "readingPdf", "sermonInterpretationPdf")},
            "activeLeases": {"timeline": detail, "generation": detail},
        }

    def assert_no_private_text(self, value):
        encoded = json.dumps(value, ensure_ascii=False)
        for private in ("PRIVATE_SENTINEL", "/Users/private", "synthetic-secret", "person@example.invalid"):
            self.assertNotIn(private, encoded)

    def test_remote_snapshot_is_exact_allowlist_despite_private_nested_fields(self):
        private = self.private_snapshot()
        expected = {
            "schemaVersion": "sermon-agent-state-minimal-v1", "sunday": self.config.sunday,
            "recommendedAction": {"action": "run_timeline_probe", "reasonCode": "run_timeline_probe",
                                  "humanActionRequired": False},
            "sourceAvailable": True, "timelinePresent": True, "windowApprovalValid": True,
            "generationCompleted": True, "publicationVerified": True,
            "qualityPassed": {"readingEdition": True, "readingPdf": True, "sermonInterpretationPdf": True},
            "activeStageLeases": {"timeline": True, "generation": True},
        }
        remote = mod.remote_snapshot(private, self.config.sunday)
        self.assertEqual(remote, expected)
        self.assert_no_private_text(remote)
        self.current = private
        self.assertEqual(self.tools()("inspect_production_state", {}), expected)
        self.assertIn("PRIVATE_SENTINEL", json.dumps(self.current))

    def test_unknown_action_is_fixed_unrecognized_state_without_echoing_input(self):
        for unknown in ("PRIVATE_SENTINEL /Users/private person@example.invalid", "run_arbitrary_command", None,
                        ["PRIVATE_SENTINEL"], {"action": "PRIVATE_SENTINEL"}):
            with self.subTest(unknown=unknown):
                private = self.private_snapshot()
                private["recommendedAction"]["action"] = unknown
                remote = mod.remote_snapshot(private, self.config.sunday)
                self.assertEqual(remote["recommendedAction"]["action"], "inspect_unrecognized_state")
                self.assertEqual(remote["recommendedAction"]["reasonCode"], "inspect_unrecognized_state")
                self.assert_no_private_text(remote)

    def test_evidence_fields_are_booleans_and_never_return_untrusted_text(self):
        private = self.private_snapshot()
        private["recommendedAction"]["humanActionRequired"] = "PRIVATE_SENTINEL"
        private["windowApproval"]["valid"] = "PRIVATE_SENTINEL"
        private["generation"]["status"] = "PRIVATE_SENTINEL"
        private["generation"]["publication"]["status"] = "PRIVATE_SENTINEL"
        for quality in private["quality"].values():
            quality["status"] = "PRIVATE_SENTINEL"
        remote = mod.remote_snapshot(private, self.config.sunday)
        for key in ("sourceAvailable", "timelinePresent", "windowApprovalValid", "generationCompleted", "publicationVerified"):
            self.assertIs(type(remote[key]), bool)
        self.assertFalse(remote["windowApprovalValid"])
        self.assertFalse(remote["generationCompleted"])
        self.assertFalse(remote["publicationVerified"])
        self.assertFalse(remote["recommendedAction"]["humanActionRequired"])
        self.assertEqual(set(remote["qualityPassed"].values()), {False})
        self.assert_no_private_text(remote)

    def test_blocked_mutation_never_returns_raw_recommendation_details(self):
        tools = self.tools()
        tools("inspect_production_state", {})
        self.current = self.private_snapshot()
        self.current["recommendedAction"].update(action="PRIVATE_SENTINEL", humanActionRequired=True)
        result = tools("run_timeline_probe", {})
        self.assertEqual(result["reasonCode"], "current_state_does_not_allow_stage")
        self.assertEqual(result["recommendedAction"], {
            "action": "inspect_unrecognized_state", "reasonCode": "inspect_unrecognized_state",
            "humanActionRequired": True})
        self.assert_no_private_text(result)
        self.timeline.assert_not_called()

    def test_malicious_mutation_status_and_logs_are_not_sent_remotely(self):
        for index, status in enumerate(("PRIVATE_SENTINEL /Users/private person@example.invalid",
                                        {"private": "PRIVATE_SENTINEL"}, ["PRIVATE_SENTINEL"])):
            with self.subTest(status=status):
                tools = self.tools(directory=self.root / f"unsafe-status-{index}")
                tools("inspect_production_state", {})
                self.timeline.return_value = {"status": status, "returnCode": "synthetic-secret",
                                              "log": "PRIVATE_SENTINEL", "reason": "person@example.invalid",
                                              "details": {"path": "/Users/private"}}
                result = tools("run_timeline_probe", {})
                self.assertEqual(result, {"status": "requires_fresh_inspection", "stage": "timeline",
                                          "requiresFreshInspection": True})
                self.assert_no_private_text(result)

    def test_remote_payload_has_no_private_config_or_local_fingerprint(self):
        self.current = self.private_snapshot()
        self.current["recommendedAction"]["action"] = "complete"
        self.config = replace(self.config, state_file="/Users/private/PRIVATE_SENTINEL-source.json",
                              api_key_secret="synthetic-secret", notify_sender_secret="person@example.invalid")
        client = FakeClient([[action("inspect_production_state", "i1"),
                              action("submit_supervisor_decision", "d1", decision())]])
        report = self.report(client)
        self.assert_no_private_text(client.payload)
        self.assert_no_private_text(client.submitted)
        self.assertEqual(client.payload["agent"]["model"], "gpt-6-astra")
        self.assertEqual(client.payload["agent"]["reasoning"], {"effort": "medium"})
        self.assertNotIn("Configuration binding", client.payload["input"])
        directory = Path(report["agentSession"]["runDirectory"])
        local_state = json.loads((directory / "production-tool-state.json").read_text())
        self.assertIn("configFingerprint", local_state)
        outbound = json.dumps({"payload": client.payload, "submissions": client.submitted})
        self.assertNotIn(local_state["configFingerprint"], outbound)
        self.assertNotIn(mod.fingerprint({"model": self.args().model, "mode": "execute", "config": asdict(self.config)}), outbound)
        self.assertIn("PRIVATE_SENTINEL", json.dumps(report["finalSnapshot"]))

    def test_resume_rejects_changed_production_configuration_before_remote_contact(self):
        self.current = snapshot("complete")
        client = FakeClient([[action("inspect_production_state", "i1"),
                              action("submit_supervisor_decision", "d1", decision())]])
        first = self.report(client)
        directory = Path(first["agentSession"]["runDirectory"])
        saved = (directory / "production-tool-state.json").read_bytes()
        self.config = replace(self.config, state_file=str(self.root / "different-source.json"))
        resumed = FakeClient()
        with self.assertRaises(AgentsAPIError) as caught:
            self.report(resumed, agent_run_dir=directory, resume_agent_session=True)
        self.assertEqual(caught.exception.code, "production_configuration_changed")
        self.assertEqual(resumed.created, 0)
        self.assertEqual(resumed.index, -1)
        self.assertEqual((directory / "production-tool-state.json").read_bytes(), saved)
        self.timeline.assert_not_called()
        self.generation.assert_not_called()

    def legacy_pointer(self, *, terminal=None, tool_status=None):
        root = self.root / "agents-api-runs"
        directory = root / "run-legacy-boundary-model"
        directory.mkdir(parents=True)
        legacy_config = {**asdict(self.config), "timeline_model": "gpt-transcribe",
                         "timeline_classifier_model": "gpt-5.6"}
        binding = mod.fingerprint({"model": self.args().model, "mode": "execute", "config": legacy_config})
        pointer = root / ("active-" + binding[:16] + ".json")
        pointer.write_text(json.dumps({"runName": directory.name, "binding": binding}))
        if terminal is not None:
            (directory / "result.json").write_text(json.dumps(terminal))
        if tool_status is not None:
            (directory / "tool-results").mkdir()
            (directory / "tool-results" / "pending.json").write_text(json.dumps({"status": tool_status}))
        return directory, pointer

    def test_changed_binding_blocks_unresolved_old_session_without_remote_contact(self):
        directory, pointer = self.legacy_pointer(terminal={"status": "timeout"})
        before = {p: p.read_bytes() for p in directory.rglob("*.json")}
        client = FakeClient()
        with self.assertRaisesRegex(AgentsAPIError, "prior_configuration_session_unresolved"):
            self.report(client)
        self.assertEqual(client.created, 0)
        self.assertEqual(client.index, -1)
        self.assertEqual(list(pointer.parent.glob("active-*.json")), [pointer])
        self.assertEqual(list(pointer.parent.glob("run-*")), [directory])
        self.assertEqual({p: p.read_bytes() for p in directory.rglob("*.json")}, before)
        self.timeline.assert_not_called()
        self.generation.assert_not_called()

    def test_terminal_old_session_with_uncertain_tool_still_blocks_new_binding(self):
        self.legacy_pointer(terminal={"status": "completed"}, tool_status="started")
        client = FakeClient()
        with self.assertRaisesRegex(AgentsAPIError, "prior_configuration_session_unresolved"):
            self.report(client)
        self.assertEqual(client.created, 0)
        self.assertEqual(client.index, -1)

    def test_terminal_old_binding_allows_new_session_and_preserves_old_evidence(self):
        directory, pointer = self.legacy_pointer(terminal={"status": "completed"}, tool_status="completed")
        before = {p: p.read_bytes() for p in directory.rglob("*.json")}
        saved_pointer = pointer.read_bytes()
        self.current = snapshot("complete")
        client = FakeClient([[action("inspect_production_state", "i1"),
                              action("submit_supervisor_decision", "d1", decision())]])
        report = self.report(client)
        self.assertEqual(client.created, 1)
        self.assertNotEqual(Path(report["agentSession"]["runDirectory"]), directory)
        self.assertEqual(pointer.read_bytes(), saved_pointer)
        self.assertEqual({p: p.read_bytes() for p in directory.rglob("*.json")}, before)

    def test_new_remote_call_id_cannot_repeat_a_stage(self):
        calls = [[action("inspect_production_state", "i1"), action("run_timeline_probe", "m1"),
                  action("inspect_production_state", "i2"), action("run_timeline_probe", "m2"),
                  action("submit_supervisor_decision", "d1", decision())]]
        client = FakeClient(calls)
        self.report(client)
        self.timeline.assert_called_once()
        second = next(item for item in client.submitted if item["call"]["call_id"] == "m2")
        self.assertEqual(second["output"]["reasonCode"], "stage_already_attempted_in_session")

    def test_model_complete_cannot_override_missing_approval(self):
        self.current = snapshot("request_window_approval", True)
        client = FakeClient([[action("inspect_production_state", "i1"),
                              action("submit_supervisor_decision", "d1", decision())]])
        report = self.report(client)
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["decision"]["action"], "request_window_approval")
        self.assertFalse(report["decision"]["modelDecisionAccepted"])
        self.approval.assert_not_called()

    def test_missing_structured_output_fails_even_when_snapshot_is_complete(self):
        self.current = snapshot("complete")
        report = self.report(FakeClient())
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["agentSession"]["errorCode"], "structured_decision_missing")

    def test_remote_failure_cannot_become_production_complete(self):
        self.current = snapshot("complete")
        client = FakeClient([[action("inspect_production_state", "i1"),
                              action("submit_supervisor_decision", "d1", decision())]], terminal="failed")
        report = self.report(client)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["agentSession"]["errorCode"], "remote_turn_failed")

    def test_resume_restores_cached_decision_and_attempts_without_new_session(self):
        calls = [[action("inspect_production_state", "i1"), action("run_timeline_probe", "m1"),
                  action("inspect_production_state", "i2"), action("submit_supervisor_decision", "d1", decision())]]
        client = FakeClient(calls)
        first = self.report(client)
        directory = Path(first["agentSession"]["runDirectory"])
        self.assertEqual(json.loads((directory / "production-tool-state.json").read_text())["attemptedStages"], ["timeline"])
        self.current = snapshot("request_window_approval", True)
        resumed_client = FakeClient()
        resumed = self.report(resumed_client, agent_run_dir=directory, resume_agent_session=True)
        self.assertEqual(resumed["modelDecision"], decision())
        self.assertEqual(resumed["status"], "blocked")
        self.assertEqual(resumed_client.created, 0)
        self.assertEqual(resumed_client.index, -1)
        self.timeline.assert_called_once()

    def test_interrupted_stage_result_resume_reuses_cache_and_blocks_new_call_id(self):
        first_client = FakeClient([[action("inspect_production_state", "i1"),
                                    action("run_timeline_probe", "m1")]])
        original_submit = first_client.submit_tool_result

        def interrupted_submit(session_id, call, output=None, *, error=None):
            original_submit(session_id, call, output, error=error)
            if call["call_id"] == "m1":
                raise AgentsAPIError("transport_error")

        first_client.submit_tool_result = interrupted_submit
        first = self.report(first_client)
        self.assertEqual(first["status"], "failed")
        resumed_client = FakeClient([[action("run_timeline_probe", "m1"),
                                      action("inspect_production_state", "i2"),
                                      action("run_timeline_probe", "m2"),
                                      action("submit_supervisor_decision", "d1", decision())]])
        resumed = self.report(resumed_client)
        self.assertEqual(resumed["agentSession"]["runDirectory"], first["agentSession"]["runDirectory"])
        self.assertEqual(resumed_client.created, 0)
        self.timeline.assert_called_once()
        self.assertEqual(resumed_client.submitted[0]["output"]["status"], "completed")
        self.assertEqual(resumed_client.submitted[2]["output"]["reasonCode"], "stage_already_attempted_in_session")

    def test_pending_creation_unknown_never_creates_another_session(self):
        first_client = FakeClient(creation_error=True)
        first = self.report(first_client)
        self.assertEqual(first["agentSession"]["errorCode"], "creation_outcome_unknown")
        second_client = FakeClient()
        second = self.report(second_client)
        self.assertEqual(second["agentSession"]["runDirectory"], first["agentSession"]["runDirectory"])
        self.assertEqual(second["agentSession"]["errorCode"], "creation_outcome_unknown")
        self.assertEqual(second_client.created, 0)

    def test_budget_exhaustion_with_cancel_ack_and_running_root_cannot_start_new_session(self):
        calls = [[action("inspect_production_state", "i1"), action("run_timeline_probe", "m1"),
                  action("inspect_production_state", "i2")]]
        first_client = FakeClient(calls, cancel_status="running")
        first = self.report(first_client, max_turns=2)
        directory = Path(first["agentSession"]["runDirectory"])
        result = json.loads((directory / "result.json").read_text())
        self.assertEqual(result["status"], "tool_budget_exceeded")
        self.assertEqual(result["tool_calls"], 2)
        self.assertTrue(result["cancel_requested"])
        self.assertFalse(result["cancellation_observed"])
        self.assertEqual(result["observed_root_status"], "running")
        self.assertEqual(first_client.cancelled, 1)
        saved_tools = (directory / "production-tool-state.json").read_bytes()
        self.assertEqual(json.loads(saved_tools)["attemptedStages"], ["timeline"])

        second_client = FakeClient(calls, cancel_status="running")
        second = self.report(second_client, max_turns=2)
        self.assertEqual(second["status"], "failed")
        self.assertEqual(second["agentSession"]["errorCode"], "remote_turn_tool_budget_exceeded")
        self.assertEqual(second["agentSession"]["runDirectory"], str(directory))
        self.assertEqual(second_client.created, 0)
        self.assertEqual(second_client.index, -1)
        self.assertEqual(second_client.submitted, [])
        self.assertEqual((directory / "production-tool-state.json").read_bytes(), saved_tools)
        self.timeline.assert_called_once()

    def test_budget_exhaustion_with_confirmed_cancelled_root_allows_new_session(self):
        first_client = FakeClient([[action("inspect_production_state", "i1"), action("run_timeline_probe", "m1"),
                                    action("inspect_production_state", "i2")]], cancel_status="cancelled")
        first = self.report(first_client, max_turns=2)
        directory = Path(first["agentSession"]["runDirectory"])
        result = json.loads((directory / "result.json").read_text())
        self.assertEqual(result["status"], "tool_budget_exceeded")
        self.assertTrue(result["cancel_requested"])
        self.assertTrue(result["cancellation_observed"])
        self.assertEqual(result["observed_root_status"], "cancelled")
        saved_tools = (directory / "production-tool-state.json").read_bytes()

        self.current = snapshot("request_window_approval", True)
        second_client = FakeClient([[action("inspect_production_state", "i3"),
                                     action("submit_supervisor_decision", "d1", decision())]])
        second = self.report(second_client, max_turns=2)
        self.assertEqual(second_client.created, 1)
        self.assertNotEqual(second["agentSession"]["runDirectory"], str(directory))
        self.assertEqual(second["agentSession"]["status"], "completed")
        self.assertEqual((directory / "production-tool-state.json").read_bytes(), saved_tools)
        self.timeline.assert_called_once()

    def test_usage_none_remains_unknown_in_report_and_accounting(self):
        self.current = snapshot("complete")
        report = self.report(FakeClient([[action("inspect_production_state", "i1"),
                                         action("submit_supervisor_decision", "d1", decision())]]))
        self.assertEqual(report["status"], "complete")
        self.assertIsNone(report["agentSession"]["usage"])
        self.assertEqual(report["agentSession"]["costStatus"], "unknown")
        self.assertEqual(self.receipts[-1]["usage"], dict.fromkeys(["requests", "input_tokens", "output_tokens", "total_tokens"]))

    def test_partial_turn_usage_does_not_invent_missing_totals(self):
        usage = mod.usage_summary({"usage": {"turns": [{"usage": {"input_tokens": 4}},
                                                      {"usage": {"input_tokens": 6, "output_tokens": 2}}]}})
        self.assertEqual(usage["input_tokens"], 10)
        self.assertIsNone(usage["output_tokens"])
        self.assertIsNone(usage["total_tokens"])
        self.assertIsNone(usage["requests"])

    def test_session_transport_exception_returns_failure_without_sdk_fallback(self):
        with patch.object(mod, "run_agent_session", side_effect=AgentsAPIError("transport_error")), \
                patch.object(entry.Runner, "run", new_callable=AsyncMock) as sdk:
            report = mod.session_report(self.args(), self.config, entry.supervisor_instructions("agents-api"),
                                        entry.SupervisorDecision, entry.verify_decision, client=FakeClient())
        self.assertEqual(report["status"], "failed")
        sdk.assert_not_called()

    def test_entry_dispatches_only_the_explicitly_selected_backend(self):
        self.current = snapshot("complete")
        for backend in ("agents-api", "sdk"):
            with self.subTest(backend=backend), patch("sys.argv", [
                    "supervisor", "--sunday", self.config.sunday, "--state-file", self.config.state_file,
                    "--work-root", str(self.config.work_root), "--gcs-bucket", "", "--mode", "shadow",
                    "--agent-backend", backend]):
                args = entry.parse_args()
            with patch.object(mod, "session_report", return_value={"status": "observed"}) as remote, \
                    patch.object(entry.Runner, "run", new_callable=AsyncMock,
                                 return_value=Mock(final_output=decision(), context_wrapper=None)) as sdk:
                asyncio.run(entry.run_agent(args))
            if backend == "agents-api":
                remote.assert_called_once()
                sdk.assert_not_called()
            else:
                remote.assert_not_called()
                sdk.assert_awaited_once()


class BackendCLISelectionTests(unittest.TestCase):
    def test_both_entrypoints_default_to_agents_api_and_allow_explicit_sdk(self):
        for module, required in ((entry, ["--sunday", "2026-09-13", "--state-file", "state.json"]),
                                 (local_entry, [])):
            with self.subTest(module=module.__name__):
                with patch("sys.argv", ["supervisor", *required]):
                    args = module.parse_args()
                    self.assertEqual(args.agent_backend, "agents-api")
                    self.assertEqual(args.model, "gpt-6-astra")
                with patch("sys.argv", ["supervisor", *required, "--agent-backend", "sdk"]):
                    self.assertEqual(module.parse_args().agent_backend, "sdk")

    def test_sdk_rollback_keeps_medium_reasoning_default(self):
        agent = entry.build_agent(model="gpt-6-astra", execute=False)
        self.assertEqual(agent.model, "gpt-6-astra")
        self.assertEqual(agent.model_settings.reasoning.effort, "medium")

    def test_local_entry_forwards_backend_and_session_recovery_parameters(self):
        with patch("sys.argv", ["supervisor", "--agent-backend", "sdk", "--agent-run-dir", "/tmp/fake-run",
                                "--resume-agent-session", "--agent-timeout-seconds", "120"]):
            args = local_entry.make_agent_args(local_entry.parse_args())
        self.assertEqual(args.agent_backend, "sdk")
        self.assertEqual(args.agent_run_dir, Path("/tmp/fake-run"))
        self.assertTrue(args.resume_agent_session)
        self.assertEqual(args.agent_timeout_seconds, 120)


if __name__ == "__main__":
    unittest.main()
