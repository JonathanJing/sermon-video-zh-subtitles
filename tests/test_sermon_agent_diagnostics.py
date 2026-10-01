"""Offline pilot fixtures; no OpenAI credentials, network, audio or transcript."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator
from scripts import sermon_agent_diagnostics as adapter
from scripts import sermon_agent_diagnostics_contracts as contract

FIXTURES = Path(__file__).parent / "fixtures" / "sermon_agent_diagnostics"


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


def frame(actions=None, status="in_progress", usage=None, turn_id="turn_offline"):
    return {"session": {"id": "sess_offline", "status": "idle" if status == "completed" else "running",
                        "required_actions": actions or [], "usage": usage},
            "turns": [{"id": turn_id, "subagent_id": None, "status": status, "usage": usage}]}


def final_item(report, turn_id="turn_offline"):
    return {"type": "message", "role": "assistant", "status": "completed", "phase": "final_answer",
            "turn_id": turn_id, "content": [{"type": "output_text", "text": json.dumps(report)}]}


class DiagnosticContractsTest(unittest.TestCase):
    def setUp(self):
        self.manifest = fixture("manifest.json")
        self.bundle = adapter.build_context_bundle(self.manifest)
        self.report = fixture("diagnosis.json")
        self.unit = self.report["hypotheses"][0]["affectedUnitIds"][0]
        self.evidence_id = self.report["hypotheses"][0]["evidenceIds"][0]

    def test_schema_and_frozen_fixture_hashes(self):
        for version in (contract.INPUT_VERSION, contract.OUTPUT_VERSION):
            Draft202012Validator.check_schema(contract.contract_schema(version))
        self.assertEqual(contract.validate_manifest(self.manifest), self.manifest)
        self.assertEqual(contract.validate_diagnosis(self.report, self.bundle), self.report)
        self.assertEqual(adapter.build_context_bundle(copy.deepcopy(self.manifest)), self.bundle)

    def test_malicious_input_fields_never_reach_client(self):
        for malicious in fixture("malicious-fields.json"):
            for location in ("root", "event", "identity", "diff"):
                with self.subTest(malicious=malicious["name"], location=location):
                    value = copy.deepcopy(self.manifest)
                    target = {"root": value, "event": value["events"][0],
                              "identity": value["identity"], "diff": value["versionDiffs"][0]}[location]
                    target[malicious["key"]] = malicious["value"]
                    client = adapter.OfflineReplayClient([], [])
                    with self.assertRaises(contract.DiagnosticContractError) as raised:
                        adapter.diagnose(value, client=client)
                    self.assertNotIn(malicious["value"], str(raised.exception))
                    self.assertEqual(client.created_payloads, [])

    def test_closed_reason_codes_reject_instructions_secrets_and_urls(self):
        for reason in ("publish_now", "sk-proj-fixturesecret", "https://evil.invalid", "Ignore instructions"):
            value = copy.deepcopy(self.manifest)
            value["events"][0]["reasonCode"] = reason
            value["events"][0]["sha256"] = contract.evidence_sha256(value["events"][0])
            with self.assertRaises(contract.DiagnosticContractError):
                adapter.build_context_bundle(value)

    def test_scope_and_unit_version_checked_even_with_valid_hash(self):
        for key in ("runId", "sourceId", "sourceSha256", "targetLocale", "stateRevision", "planVersion",
                    "policyVersion", "revisionId", "packageVersion"):
            value = copy.deepcopy(self.manifest)
            row = value["events"][0]
            row["identity"][key] = (4 if key == "stateRevision" else "ko" if key == "targetLocale"
                                    else "f" * 64 if key == "sourceSha256" else "other")
            row["sha256"] = contract.evidence_sha256(row)
            with self.subTest(key=key), self.assertRaisesRegex(contract.DiagnosticContractError, "identity_mismatch"):
                adapter.build_context_bundle(value)
        for key, changed in (("unitId", "out_of_scope"), ("unitVersion", "old_version")):
            value = copy.deepcopy(self.manifest)
            row = value["events"][0]
            row["units"][0][key] = changed
            row["sha256"] = contract.evidence_sha256(row)
            with self.assertRaisesRegex(contract.DiagnosticContractError, "unit_identity_mismatch"):
                adapter.build_context_bundle(value)

    def test_tampered_hash_duplicate_and_future_evidence(self):
        mutations = [
            (lambda m: m["events"][0].update(sha256="0" * 64), "hash_mismatch"),
            (lambda m: m["failedUnits"].append(copy.deepcopy(m["failedUnits"][0])), "schema"),
            (lambda m: m["receipts"][0].update(evidenceId=m["events"][0]["evidenceId"]), "duplicate_evidence"),
            (lambda m: m["events"][0].update(observedAt="2026-10-02T01:00:00Z"), "after_cutoff"),
            (lambda m: m["identity"].update(stateRevision=True), "schema"),
        ]
        for mutate, code in mutations:
            value = copy.deepcopy(self.manifest)
            mutate(value)
            with self.subTest(code=code), self.assertRaisesRegex(contract.DiagnosticContractError, code):
                adapter.build_context_bundle(value)

    def test_bounded_bytes_depth_arrays_and_duplicate_json_keys(self):
        for value in ({"x": "s" * (contract.MAX_INPUT_BYTES + 1)}, {"x": list(range(257))},
                      {"x": float("nan")}):
            with self.assertRaises(contract.DiagnosticContractError):
                contract.bounded_json(value)
        value = {}
        for _ in range(14):
            value = {"x": value}
        with self.assertRaisesRegex(contract.DiagnosticContractError, "complexity"):
            contract.bounded_json(value)
        for data in (b'{"x":1,"x":2}', b'{"x":NaN}', b"x" * (contract.MAX_INPUT_BYTES + 1)):
            with self.assertRaises(contract.DiagnosticContractError):
                contract.decode_json(data)

    def test_alias_export_excludes_original_identity_hashes_models_and_provider_ids(self):
        payload = adapter.build_session_payload(self.bundle)
        wire = json.dumps(payload)
        for key, value in self.manifest["identity"].items():
            if key in {"stage", "targetLocale", "stateRevision", "evidenceCutoff"}:
                continue
            self.assertNotIn(value, wire)
        for key in ("evidenceId", "callId", "attemptId", "model", "sha256"):
            self.assertNotIn(self.manifest["events"][0][key], wire)
        self.assertNotIn("localIdentity", wire)
        self.assertEqual(payload["environment"], {"type": "none"})
        self.assertEqual(payload["agent"]["multi_agent"], {"enabled": False})
        self.assertEqual([tool["name"] for tool in payload["agent"]["tools"]], list(adapter.READ_TOOLS))

    def test_read_tools_confined_to_same_frozen_packet(self):
        args = {"snapshotId": self.bundle["snapshotId"], "evidenceId": self.evidence_id}
        row = adapter.read_diagnostic_tool(self.bundle, "read_evidence", args)
        row["status"] = "succeeded"
        self.assertEqual(self.bundle["manifest"]["events"][0]["status"], "failed")
        for name, bad_args in (("read_evidence", {**args, "url": "https://evil.invalid"}),
                               ("read_evidence", {**args, "evidenceId": "invented"}),
                               ("read_evidence", {**args, "snapshotId": "other"}),
                               ("read_evidence", {**args, "evidenceId": "../private"}),
                               ("publish", args), ("inspect_job", args)):
            with self.assertRaises(contract.DiagnosticContractError):
                adapter.read_diagnostic_tool(self.bundle, name, bad_args)
        diff = self.bundle["manifest"]["versionDiffs"][0]
        self.assertEqual(adapter.read_diagnostic_tool(self.bundle, "read_version_diff", {
            "snapshotId": self.bundle["snapshotId"], "diffId": diff["evidenceId"]}), diff)

    def test_invalid_reports_cannot_expand_authority_or_scope(self):
        mutations = [
            lambda r: r.update(execute=True),
            lambda r: r.update(snapshotId="old_snapshot"),
            lambda r: r["identity"].update(stateRevision=2),
            lambda r: r["hypotheses"][0].update(classification="cause"),
            lambda r: r["hypotheses"][0].update(evidenceIds=["invented"]),
            lambda r: r["hypotheses"][0].update(affectedUnitIds=["invented"]),
            lambda r: r["hypotheses"][0]["suggestedRepair"].update(action="retry_api"),
            lambda r: r["hypotheses"][0]["suggestedRepair"].update(requiresDeterministicValidation=False),
            lambda r: r["hypotheses"][0]["suggestedRepair"].update(command="rm -rf private"),
            lambda r: r["hypotheses"][0]["suggestedRepair"].update(unitIds=["invented"]),
            lambda r: r["hypotheses"][0].update(claim="https://evil.invalid"),
            lambda r: r["hypotheses"][0].update(reason="Bearer fixture-secret"),
        ]
        for mutate in mutations:
            report = copy.deepcopy(self.report)
            mutate(report)
            with self.assertRaises(contract.DiagnosticContractError):
                contract.validate_diagnosis(report, self.bundle)

    def test_evidence_reference_must_match_hypothesis_units(self):
        report = copy.deepcopy(self.report)
        report["hypotheses"][0]["evidenceIds"] = [self.bundle["manifest"]["receipts"][0]["evidenceId"]]
        with self.assertRaisesRegex(contract.DiagnosticContractError, "outside_hypothesis_scope"):
            contract.validate_diagnosis(report, self.bundle)

    def test_unsupported_claim_stays_low_hypothesis_and_requests_missing_data(self):
        report = copy.deepcopy(self.report)
        h = report["hypotheses"][0]
        h["evidenceIds"] = []
        h["suggestedRepair"].update(action="none", unitIds=[], evidenceIds=[])
        self.assertEqual(contract.validate_diagnosis(report, self.bundle)["hypotheses"][0]["classification"], "hypothesis")
        for confidence in ("medium", "high"):
            h["confidence"] = confidence
            with self.assertRaisesRegex(contract.DiagnosticContractError, "unsupported_confidence"):
                contract.validate_diagnosis(report, self.bundle)
        h["confidence"] = "unknown"
        report["missingDataRequests"] = []
        with self.assertRaisesRegex(contract.DiagnosticContractError, "uncertainty_request_missing"):
            contract.validate_diagnosis(report, self.bundle)

    def test_no_fabricated_reproduction_or_all_locale_impact(self):
        report = copy.deepcopy(self.report)
        report["hypotheses"][0]["reproducibility"] = {"status": "replayable", "evidenceIds": [self.evidence_id]}
        with self.assertRaisesRegex(contract.DiagnosticContractError, "reproducibility_not_supported"):
            contract.validate_diagnosis(report, self.bundle)
        report = copy.deepcopy(self.report)
        report["hypotheses"][0]["impact"]["blockingScope"] = "all_locales_downstream"
        with self.assertRaisesRegex(contract.DiagnosticContractError, "scope_not_supported"):
            contract.validate_diagnosis(report, self.bundle)

    def test_fresh_recommendation_validation_does_not_authorize_execution(self):
        self.assertEqual(adapter.validate_recommendation(self.report, self.bundle,
                         current_identity=self.manifest["identity"]), self.report)
        identity = {**self.manifest["identity"], "stateRevision": 4}
        with self.assertRaisesRegex(contract.DiagnosticContractError, "stale_diagnostic_snapshot"):
            adapter.validate_recommendation(self.report, self.bundle, current_identity=identity)


class DiagnosticLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.manifest = fixture("manifest.json")
        self.report = fixture("diagnosis.json")
        self.bundle = adapter.build_context_bundle(self.manifest)
        self.action = {"type": "function_call", "turn_id": "turn_offline", "call_id": "call_read",
                       "name": "read_evidence", "arguments": {"snapshotId": self.bundle["snapshotId"],
                       "evidenceId": self.report["hypotheses"][0]["evidenceIds"][0]}}

    def client(self, frames=None, report=None):
        return adapter.OfflineReplayClient(frames or [frame([self.action]), frame(status="completed")],
                                           [final_item(self.report if report is None else report)])

    def test_complete_offline_lifecycle_with_exact_tool_result_and_null_usage(self):
        client = self.client()
        with patch("socket.create_connection", side_effect=AssertionError("network forbidden")), \
             patch("subprocess.run", side_effect=AssertionError("execution forbidden")), \
             patch.dict("os.environ", {}, clear=True):
            result = adapter.diagnose(self.manifest, client=client)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["diagnosis"], self.report)
        self.assertEqual(result["provenance"]["liveCompatibility"], "untested")
        self.assertIsNone(result["provenance"]["turnUsage"])
        self.assertIsNone(result["provenance"]["costUsd"])
        self.assertFalse(result["provenance"]["executionAuthorized"])
        self.assertEqual(len(client.created_payloads), 1)
        event = client.submitted[0]
        self.assertEqual(set(event), {"type", "turn_id", "call_id", "success", "output"})
        self.assertEqual(event["type"], "agent.session.input.tool_result")
        self.assertEqual(json.loads(event["output"])["evidenceId"], self.action["arguments"]["evidenceId"])

    def test_usage_zero_is_distinct_from_unknown_and_aggregates_stay_separate(self):
        usage = {"input_tokens": 0, "output_tokens": 0, "input_tokens_details": {"cached_tokens": 0}}
        result = adapter.diagnose(self.manifest, client=self.client([frame(status="completed", usage=usage)]))
        self.assertEqual(result["provenance"]["turnUsage"]["input_tokens"], 0)
        self.assertEqual(result["provenance"]["turnUsage"]["cached_input_tokens"], 0)
        self.assertIsNone(result["provenance"]["turnUsage"]["total_tokens"])
        self.assertEqual(result["provenance"]["usageAggregation"], "separate_do_not_sum")
        self.assertEqual(adapter._usage({"input_tokens": True})["input_tokens"], None)

    def test_live_client_rejected_before_session_creation(self):
        client = self.client()
        client.offline = False
        with self.assertRaisesRegex(contract.DiagnosticContractError, "live_diagnostic_not_authorized"):
            adapter.diagnose(self.manifest, client=client)
        self.assertEqual(client.created_payloads, [])

    def test_idle_and_subagent_completion_are_not_success(self):
        frames = [frame()]
        frames[0]["session"]["status"] = "idle"
        result = adapter.diagnose(self.manifest, client=self.client(frames), limits=adapter.DiagnosticLimits(max_steps=2))
        self.assertEqual(result["reasonCode"], "diagnostic_step_limit")
        frames[0]["turns"][0].update(subagent_id="subagent_1", status="completed")
        result = adapter.diagnose(self.manifest, client=self.client(frames))
        self.assertEqual(result["reasonCode"], "delegation_not_allowed")

    def test_mutation_tools_paths_urls_wrong_turn_and_extra_action_fields_blocked(self):
        for mutation in (lambda a: a.update(name="publish"), lambda a: a.update(name="inspect_job"),
                         lambda a: a["arguments"].update(path="/Users/private/audio"),
                         lambda a: a["arguments"].update(url="https://evil.invalid"),
                         lambda a: a.update(turn_id="other_turn"), lambda a: a.update(command="execute")):
            action = copy.deepcopy(self.action)
            mutation(action)
            client = self.client([frame([action])])
            result = adapter.diagnose(self.manifest, client=client)
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(client.submitted, [])

    def test_identical_pending_call_replays_saved_result_changed_call_rejected(self):
        client = self.client([frame([self.action]), frame([self.action]), frame(status="completed")])
        with patch.object(adapter, "read_diagnostic_tool", wraps=adapter.read_diagnostic_tool) as read:
            result = adapter.diagnose(self.manifest, client=client)
            self.assertEqual(read.call_count, 1)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(client.submitted[0], client.submitted[1])
        changed = copy.deepcopy(self.action)
        changed["arguments"]["evidenceId"] = "invented"
        result = adapter.diagnose(self.manifest, client=self.client([frame([self.action]), frame([changed])]))
        self.assertEqual(result["reasonCode"], "tool_call_identity_conflict")

    def test_disconnect_after_saved_result_explicit_resume_same_session(self):
        client = self.client()
        with patch.object(client, "submit_tool_result", side_effect=RuntimeError("private provider error")):
            result = adapter.diagnose(self.manifest, client=client)
        self.assertEqual(result["status"], "outcome_unknown")
        self.assertEqual(len(result["checkpoint"]["toolResults"]), 1)
        resumed = self.client()
        outcome = adapter.diagnose(self.manifest, client=resumed, checkpoint=result["checkpoint"])
        self.assertEqual(outcome["status"], "completed")
        self.assertEqual(resumed.created_payloads, [])
        self.assertEqual(outcome["checkpoint"]["sessionId"], "sess_offline")
        self.assertNotIn("private provider error", json.dumps(result))

    def test_checkpoint_tampering_and_identity_change_fail_before_calls(self):
        client = self.client()
        with patch.object(client, "submit_tool_result", side_effect=RuntimeError()):
            state = adapter.diagnose(self.manifest, client=client)["checkpoint"]
        for mutate in (lambda s: s.update(payloadSha256="0" * 64),
                       lambda s: s["toolResults"][0]["output"].update(secret="fixture-secret"),
                       lambda s: s["toolResults"][0]["action"].update(extra="fixture-secret"),
                       lambda s: s.update(extra="fixture-secret")):
            value = copy.deepcopy(state)
            mutate(value)
            resumed = self.client()
            with self.assertRaises(contract.DiagnosticContractError):
                adapter.diagnose(self.manifest, client=resumed, checkpoint=value)
            self.assertEqual(resumed.created_payloads, [])
            self.assertEqual(resumed.index, -1)

    def test_unknown_creation_has_no_automatic_retry_or_resume_creation(self):
        client = self.client()
        with patch.object(client, "create_session", side_effect=RuntimeError("secret")) as create:
            result = adapter.diagnose(self.manifest, client=client)
            self.assertEqual(create.call_count, 1)
        self.assertEqual(result["status"], "outcome_unknown")
        self.assertIsNone(result["checkpoint"]["sessionId"])
        with self.assertRaisesRegex(contract.DiagnosticContractError, "creation_outcome_unknown"):
            adapter.diagnose(self.manifest, client=self.client(), checkpoint=result["checkpoint"])

    def test_deadlines_propagated_and_elapsed_budget_not_reset_on_resume(self):
        times = iter([0.0, 0.0, 31.0, 31.0])
        client = self.client()
        result = adapter.diagnose(self.manifest, client=client, clock=lambda: next(times))
        self.assertEqual(result["reasonCode"], "diagnostic_deadline_exceeded")
        self.assertEqual(result["status"], "outcome_unknown")
        self.assertEqual(result["checkpoint"]["sessionId"], "sess_offline")
        client = self.client([frame(status="completed")])
        with patch.object(client, "create_session", wraps=client.create_session) as create:
            adapter.diagnose(self.manifest, client=client, clock=lambda: 0.0)
            self.assertEqual(create.call_args.kwargs["timeout_seconds"], 30.0)

        client = self.client()
        with patch.object(client, "submit_tool_result", side_effect=RuntimeError()):
            state = adapter.diagnose(self.manifest, client=client, clock=lambda: 0.0)["checkpoint"]
        state["elapsedSeconds"] = 30.0
        resumed = self.client()
        result = adapter.diagnose(self.manifest, client=resumed, checkpoint=state, clock=lambda: 10.0)
        self.assertEqual(result["reasonCode"], "diagnostic_deadline_exceeded")
        self.assertEqual(resumed.index, -1)
        self.assertEqual(resumed.created_payloads, [])

    def test_read_count_and_transport_response_size_are_bounded(self):
        client = self.client()
        result = adapter.diagnose(self.manifest, client=client, limits=adapter.DiagnosticLimits(max_tool_reads=0))
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(client.submitted, [])
        with patch.object(client, "create_session", return_value={"id": "sess_offline", "raw": "x" * 2048}):
            result = adapter.diagnose(self.manifest, client=client,
                                      limits=adapter.DiagnosticLimits(max_transport_bytes=1024))
        self.assertEqual(result["reasonCode"], "json_size_limit")

    def test_failed_cancelled_or_wrong_final_turn_does_not_deliver_diagnosis(self):
        for status in ("failed", "cancelled"):
            result = adapter.diagnose(self.manifest, client=self.client([frame(status=status)]))
            self.assertEqual(result["status"], "blocked")
            self.assertIsNone(result["diagnosis"])
        client = self.client([frame(status="completed")])
        client.items[0]["turn_id"] = "old_turn"
        self.assertEqual(adapter.diagnose(self.manifest, client=client)["reasonCode"], "structured_diagnosis_missing")

    def test_hallucinated_final_ids_and_unknown_response_fields_fail_closed(self):
        report = copy.deepcopy(self.report)
        report["hypotheses"][0]["evidenceIds"] = ["invented"]
        result = adapter.diagnose(self.manifest, client=self.client([frame(status="completed")], report))
        self.assertEqual(result["reasonCode"], "unknown_evidence_reference")
        self.assertIsNone(result["diagnosis"])
        client = self.client([frame(status="completed")])
        client.items[0]["content"][0]["text"] = '{"execute":true,"execute":false}'
        self.assertEqual(adapter.diagnose(self.manifest, client=client)["status"], "blocked")

    def test_unknown_usage_late_usage_and_actual_model_provenance(self):
        frames = [frame(), frame(status="completed", usage={"input_tokens": 3, "total_tokens": 4})]
        frames[1]["turns"][0]["model"] = "gpt-6-sol"
        result = adapter.diagnose(self.manifest, client=self.client(frames))
        self.assertEqual(result["provenance"]["turnUsage"]["input_tokens"], 3)
        self.assertEqual(result["provenance"]["actualModel"], "gpt-6-sol")
        self.assertIsNone(result["provenance"]["costUsd"])

    def test_transport_error_details_and_untrusted_identifier_never_exported(self):
        client = self.client()
        private = "Bearer fixture-private-body /Users/private/audio.wav"
        with patch.object(client, "retrieve_session", side_effect=RuntimeError(private)):
            result = adapter.diagnose(self.manifest, client=client)
        self.assertEqual(result["reasonCode"], "transport_outcome_unknown")
        self.assertNotIn(private, json.dumps(result))
        with patch.object(client, "create_session", return_value={"id": "sk-proj-fixturesecret"}):
            result = adapter.diagnose(self.manifest, client=client)
        self.assertNotIn("sk-proj-fixturesecret", json.dumps(result))
        self.assertIsNone(result["provenance"]["sessionId"])

    def test_cumulative_transport_limit_for_repeated_pending_actions(self):
        second = {**self.action, "call_id": "call_read2"}
        client = self.client([frame([self.action, second])])
        limits = adapter.DiagnosticLimits(max_steps=32, max_tool_reads=2)
        # Each step submits the same saved pure result; transport calls still count.
        result = adapter.diagnose(self.manifest, client=client, limits=limits, clock=lambda: 0.0)
        self.assertEqual(result["reasonCode"], "transport_call_limit")
        self.assertEqual(len(result["checkpoint"]["toolResults"]), 2)
        self.assertEqual(len(result["checkpoint"]["transportCalls"]), 1 + 3 * 32 + 2)

    def test_many_distinct_packet_reads_cannot_overgrow_checkpoint(self):
        manifest = copy.deepcopy(self.manifest)
        # A valid metadata packet can be large enough that repeated full-packet
        # cache copies exhaust the stricter checkpoint budget before read count.
        manifest["events"] = []
        template = self.manifest["events"][0]
        for index in range(50):
            row = {**template, "evidenceId": "event_" + str(index)}
            row["sha256"] = contract.evidence_sha256(row)
            manifest["events"].append(row)
        bundle = adapter.build_context_bundle(manifest)
        actions = [{"type": "function_call", "turn_id": "turn_offline", "call_id": "call_packet" + str(index),
                    "name": "read_diagnostic_packet", "arguments": {"snapshotId": bundle["snapshotId"]}}
                   for index in range(8)]
        client = self.client([frame(actions)])
        result = adapter.diagnose(manifest, client=client)
        self.assertEqual(result["status"], "blocked")
        self.assertIn(result["reasonCode"], {"json_complexity_limit", "json_size_limit"})
        self.assertLess(len(contract.bounded_json(result["checkpoint"], 256 * 1024)), 192 * 1024)

    def test_unknown_root_identity_and_multiple_terminal_roots_blocked(self):
        frames = [frame(status="completed")]
        del frames[0]["turns"][0]["subagent_id"]
        result = adapter.diagnose(self.manifest, client=self.client(frames), limits=adapter.DiagnosticLimits(max_steps=1))
        self.assertEqual(result["reasonCode"], "diagnostic_step_limit")
        frames = [frame(status="completed")]
        frames[0]["turns"].append({"id": "turn_other", "subagent_id": None, "status": "completed"})
        self.assertEqual(adapter.diagnose(self.manifest, client=self.client(frames))["reasonCode"], "ambiguous_root_turn")


if __name__ == "__main__":
    unittest.main()
