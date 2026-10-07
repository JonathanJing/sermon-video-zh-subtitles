"""Offline public-contract tests; fixtures make no provider/dispatch/publication calls."""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import build_tracker_dag_projection as public
from scripts import four_layer_progress as tracker
from scripts import sermon_accounting as accounting
from scripts import sermon_log_contract as contract
from scripts import sermon_log_profile as profile
from scripts import sermon_run_progress as progress
from scripts import weekly_pipeline_report as weekly

AT = "2026-09-30T00:00:10+00:00"
SHA = "a" * 64
RUN = "private-run-identity"


def timestamp(seconds):
    return (datetime(2026, 9, 30, tzinfo=timezone.utc) + timedelta(seconds=seconds)).isoformat()


def events():
    result = []
    def event(kind, seconds, **fields):
        row = dict(schemaVersion=accounting.SCHEMA, eventId=str(len(result)), runId=RUN,
                   event=kind, recordedAt=timestamp(seconds), workflowId="private-workflow", **fields)
        result.append(row)
    def stage(ident, begin, end, deps, executor="deterministic_program"):
        fields = dict(stage=ident, spanId=ident, workUnitId=ident, attemptId=ident,
                      executorType=executor, dependsOn=deps)
        event("stage_started", begin, startedAt=timestamp(begin), **fields)
        event("stage_finished", end, elapsedSeconds=end-begin, status="completed",
              cacheHit=False, billing="local", **fields)
    event("run_started", 0, workflow="fixture")
    stage("source", 0, 2, [])
    stage("private-ko", 2, 7, ["source"], "production_model")
    stage("private-zh", 2, 5, ["source"], "production_model")
    stage("join", 7, 8, ["private-ko", "private-zh"])
    event("run_finished", 8, workflow="fixture", status="completed")
    return result


def profiled(rows, mode="current_execution"):
    result = []
    for index, event in enumerate(rows):
        event = copy.deepcopy(event)
        if event["event"] in {"stage_started", "stage_finished"}:
            event.update(blockedBy=[], dependencyReadyAt=None, queuedAt=None, clockDomainId="c" * 32)
            end = datetime.fromisoformat(event["recordedAt"])
            begin = end - timedelta(seconds=event.get("elapsedSeconds", 0))
            event["startedAt"] = begin.isoformat()
            event["monotonicStartNs"] = str(int((begin - datetime(2026, 9, 30, tzinfo=timezone.utc)).total_seconds() * 1e9) + 1000000000)
            if event["event"] == "stage_finished":
                event["monotonicEndNs"] = str(int((end - datetime(2026, 9, 30, tzinfo=timezone.utc)).total_seconds() * 1e9) + 1000000000)
        row = profile._build(event, {"stage": None, "spanId": None},
            {"workKind": "production", "evidenceMode": mode, "productionRunId": "private-production"},
            f"{index+1:032x}", "b" * 32, index+1)
        contract.validate_event(row)
        result.append(row)
    return result


def unit(ident, deps=(), requirements=None):
    return {"id": ident, "identitySha256": SHA, "stage": "translation", "model": "gpt-6-sol", "locale": "ko",
            "lengthBucket": "short", "cacheClass": "fresh", "resourceClass": "fixture-api", "dependsOn": list(deps),
            "weight": 1, "resources": ["api"], "requiredEvidence": requirements or ["executionSucceeded"]}


def plan(units):
    return progress.freeze_plan("private-plan", 1, RUN, units,
        {"api": {"capacity": 2, "resourceClass": "fixture-api"}}, dag_version="private-dag")


def receipt(frozen, key, **fields):
    return progress.status_receipt(frozen, key, event_id=fields.pop("event_id", key),
        attempt_id=fields.pop("attempt_id", key), sequence=fields.pop("sequence", 1), observed_at=AT, **fields)


def success(frozen, key, **fields):
    return receipt(frozen, key, executionStatus="succeeded", phase="complete", evidenceValidated=True,
                   artifactSha256=SHA, evidenceRefs=["private-receipt"], **fields)


def inputs(frozen, receipts, *, samples=True):
    value = {"plan": frozen, "receipts": receipts,
        "resource_state": {"api": {"capacity": 2, "resourceClass": "fixture-api", "status": "ready",
                                    "queueSeconds": [0, 0], "observedAt": AT, "maxAgeSeconds": 60}}}
    if samples:
        value["samples"] = [{**{key: frozen["units"][0][key] for key in progress.DIMENSIONS},
            "sampleId": "private-sample", "workUnitId": "private-old-work", "sourceRef": "private-timing",
            "observedAt": AT, "executionStatus": "succeeded", "measurementKind": "empirical", "elapsedSeconds": 10}]
    return value


class PublicDagTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rows = events()

    def write(self, suffix=""):
        data = "".join(json.dumps(row) + "\n" for row in self.rows) + suffix
        (self.root / "events.jsonl").write_text(data)
        return data

    def project(self, **kwargs):
        before = self.write()
        value = public.build_projection(self.root, run_id=RUN, at=AT, **kwargs)
        self.assertEqual((self.root / "events.jsonl").read_text(), before)
        self.assertEqual({p.name for p in self.root.iterdir()}, {"events.jsonl"})
        return value

    def test_parallel_observed_path_is_canonical_not_serial_eta(self):
        result = self.project()
        self.assertEqual(result["schemaVersion"], public.SCHEMA)
        self.assertEqual(result["quality"]["status"], "projected")
        self.assertEqual(result["summary"]["measuredSpanSeconds"], 11)
        self.assertEqual(result["summary"]["endToEndWallSeconds"], 8)
        self.assertEqual(result["criticalPath"]["activeSeconds"], 8)
        self.assertEqual(len(result["criticalPath"]["nodeIds"]), 3)
        self.assertEqual(result["eta"]["status"], "unknown")
        self.assertEqual(result["evidenceMode"], "unknown")
        self.assertEqual(result["acceptance"], "not_evaluated")
        self.assertEqual(result["executionAuthority"], "none")

    def test_order_duplicates_restarts_are_read_only_and_deterministic(self):
        baseline = self.project()
        self.rows.reverse()
        self.assertEqual(self.project(), baseline)
        self.rows.append(copy.deepcopy(self.rows[0]))
        duplicate = self.project()
        self.assertEqual(duplicate["nodes"], baseline["nodes"])
        self.assertEqual(duplicate["summary"], baseline["summary"])
        self.assertEqual(duplicate["logs"], baseline["logs"])
        self.assertEqual(duplicate["quality"]["duplicateEventsIgnored"], 1)
        self.assertEqual(self.project(), duplicate)

    def test_profile_mode_real_and_synthetic_no_assumed_legacy_provenance(self):
        for mode, public_mode in (("current_execution", "real"), ("cache_replay", "real"), ("synthetic", "synthetic")):
            self.rows = profiled(events(), mode)
            result = self.project()
            self.assertEqual(result["evidenceMode"], public_mode)
            self.assertEqual(result["quality"]["status"], "projected")
            self.assertEqual(result["logs"]["profileEventCount"], len(self.rows))
        self.rows = events()
        for row in self.rows:
            row["evidenceMode"] = "current_execution"
        self.assertEqual(self.project()["evidenceMode"], "unknown")

    def test_missing_truncated_malformed_and_unknown_schema_fail_closed(self):
        missing = public.build_projection(self.root, run_id=RUN, at=AT)
        self.assertEqual(missing["quality"]["reasonCodes"], ["accounting_missing"])
        for suffix in ('{"event":', '\n{"secret":"/private/token"}\n', '\xff'):
            self.write(suffix)
            result = public.build_projection(self.root, run_id=RUN, at=AT)
            self.assertEqual(result["quality"]["status"], "partial")
            self.assertGreater(result["quality"]["damagedRowCount"], 0)
            self.assertEqual(result["criticalPath"]["status"], "unknown")
        self.rows[0]["schemaVersion"] = "future-schema"
        self.assertIn("unsupported_schema", self.project()["quality"]["reasonCodes"])

    def test_stale_and_future_evidence_never_freshened_by_render(self):
        self.write()
        stale = public.build_projection(self.root, run_id=RUN, at=timestamp(600))
        self.assertEqual(stale["freshness"], {"status": "stale", "sourceObservedAt": timestamp(8), "ageSeconds": 592})
        later = public.build_projection(self.root, run_id=RUN, at=timestamp(800))
        self.assertEqual(later["freshness"]["sourceObservedAt"], stale["freshness"]["sourceObservedAt"])
        self.assertEqual(later["freshness"]["ageSeconds"], 792)
        future = public.build_projection(self.root, run_id=RUN, at=timestamp(1))
        self.assertEqual(future["freshness"]["status"], "unknown")
        self.assertEqual(future["criticalPath"]["status"], "unknown")

    def test_excluded_conflicting_timestamp_cannot_refresh_source_freshness(self):
        self.rows = profiled(events())
        self.rows.append({**self.rows[2], "recordedAt": timestamp(600)})
        self.write()
        result = public.build_projection(self.root, run_id=RUN, at=timestamp(600))
        self.assertEqual(result["freshness"]["status"], "stale")
        self.assertEqual(result["freshness"]["sourceObservedAt"], timestamp(8))
        self.assertEqual(result["quality"]["status"], "partial")

    def test_unfinished_span_is_not_measured_or_worker_alive(self):
        self.rows = [row for row in self.rows if not (row["event"] == "stage_finished" and row.get("spanId") == "join")]
        result = self.project()
        unfinished = next(row for row in result["nodes"] if row["status"] == "unfinished_or_ambiguous")
        self.assertEqual(unfinished["timing"]["status"], "unfinished")
        self.assertEqual(unfinished["dependencyStatus"], "recorded")
        self.assertEqual(len(unfinished["dependsOn"]), 2)
        self.assertIsNone(unfinished["timing"]["elapsedSeconds"])
        self.assertIsNone(unfinished["timing"]["activeElapsedSeconds"])
        self.assertEqual(result["summary"]["unfinishedSpanCount"], 1)
        self.assertIsNone(result["summary"]["retryCount"])
        self.assertEqual(result["criticalPath"]["status"], "unknown")

    def test_ambiguous_open_span_cannot_claim_known_root_or_model(self):
        self.rows = [row for row in self.rows if not (row["event"] == "stage_finished" and row.get("spanId") == "join")]
        other = copy.deepcopy(next(row for row in self.rows if row.get("spanId") == "join"))
        other.update(eventId="second-start", dependsOn=[])
        self.rows.append(other)
        result = self.project()
        node = next(row for row in result["nodes"] if row["status"] == "unfinished_or_ambiguous")
        self.assertEqual(node["dependencyStatus"], "unknown")
        self.assertEqual(node["dependsOn"], [])
        self.assertEqual(node["modelCodes"], [])

    def test_contradictory_unfinished_legacy_identity_is_order_independent(self):
        self.rows = [row for row in self.rows if not (row["event"] == "stage_finished" and row.get("spanId") == "source")]
        original = next(row for row in self.rows if row.get("spanId") == "source")
        self.rows.append({**original, "eventId": "contradiction", "stage": "asr", "executorType": "production_model"})
        result = self.project()
        node = next(n for n in result["nodes"] if n["status"] == "unfinished_or_ambiguous")
        self.assertEqual((node["code"], node["executorType"], node["dependencyStatus"]), ("unknown", "unknown", "unknown"))
        self.rows.reverse()
        self.assertEqual(self.project(), result)

    def test_attempts_retries_and_failed_spans_not_done_gate(self):
        for row in self.rows:
            if row.get("spanId") in {"private-ko", "private-zh"}:
                row["workUnitId"] = "shared-business-unit"
            if row.get("spanId") == "private-zh" and row["event"] == "stage_finished":
                row["status"] = "failed"
        result = self.project()
        self.assertEqual(result["summary"]["retryCount"], 1)
        self.assertEqual(result["summary"]["failedSpanCount"], 1)
        self.assertEqual(result["summary"]["completedSpanCount"], 4)
        self.assertIsNone(result["progress"])

    def test_invalid_graph_remains_partial_without_cycle_or_dangling_edges(self):
        for row in self.rows:
            if row.get("spanId") == "source":
                row["dependsOn"] = ["join"]
        result = self.project()
        self.assertEqual(result["quality"]["status"], "partial")
        self.assertTrue(all(not row["dependsOn"] for row in result["nodes"]))
        self.assertEqual(result["criticalPath"]["status"], "unknown")
        for row in self.rows:
            if row.get("spanId") == "source":
                row["dependsOn"] = ["missing-private-span"]
        result = self.project()
        self.assertEqual(sum(row["unresolvedDependencyCount"] for row in result["nodes"]), 1)
        self.assertNotIn("missing-private-span", json.dumps(result))

    def test_node_limit_discloses_omission_and_removes_critical_claim(self):
        with patch.object(public, "MAX_NODES", 2):
            result = self.project()
        self.assertEqual(len(result["nodes"]), 2)
        self.assertEqual(result["quality"]["omittedNodeCount"], 2)
        self.assertEqual(result["criticalPath"]["status"], "unknown")
        self.assertEqual(result["summary"]["observedNodeCount"], 4)

    def test_model_stage_locale_and_io_closed_projection(self):
        for row in self.rows:
            if row.get("spanId") == "private-ko":
                row["stage"] = "four_layer.L2-02:ko.sub.initial_translation"
        self.rows.append(dict(schemaVersion=accounting.SCHEMA, runId=RUN, eventId="model", event="sdk_call_finished",
            recordedAt=timestamp(7), spanId="private-ko", invocationId="secret-invocation", model="gpt-6-sol",
            status="completed", usage={}))
        self.rows.append(dict(schemaVersion=accounting.SCHEMA, runId=RUN, eventId="artifact", event="workflow_evidence",
            recordedAt=timestamp(8), phase="after", evidence={"artifacts": [{"category": "layer2_candidate",
            "sha256": SHA, "bytes": 20, "path": "/private/secret", "summary": {"sourceId": "secret-id"}}]}))
        result = self.project()
        node = next(n for n in result["nodes"] if n["code"] == "initial_translation")
        self.assertEqual((node["layer"], node["locale"]), (2, "ko"))
        self.assertEqual(node["modelCodes"], ["gpt-6-sol"])
        self.assertEqual(result["io"]["afterArtifactCount"], 1)
        self.assertEqual(result["io"]["categories"], ["layer2_candidate"])
        raw = json.dumps(result)
        for forbidden in (SHA, "/private", "private-ko", "secret-id", "secret-invocation", "spanSha256", "workflowId", "runId"):
            self.assertNotIn(forbidden, raw)
        self.assertNotRegex(raw, r'\b[a-f0-9]{64}\b')
        self.rows[-2]["model"] = "private-model-path"
        node = next(n for n in self.project()["nodes"] if n["code"] == "initial_translation")
        self.assertEqual(node["modelCodes"], [])
        self.assertEqual(node["modelStatus"], "unknown")

    def test_conflicting_event_never_gains_complete_graph(self):
        self.rows = profiled(events())
        other = copy.deepcopy(self.rows[2])
        other["elapsedSeconds"] = 1
        self.rows.append(other)
        result = self.project()
        self.assertEqual(result["quality"]["status"], "partial")
        self.assertEqual(result["criticalPath"]["status"], "unknown")
        self.rows.reverse()
        self.assertEqual(self.project(), result)

    def test_legacy_conflicting_event_timing_fails_closed_in_standalone_mode(self):
        self.rows.append({**self.rows[2], "elapsedSeconds": 1})
        first = self.project()
        self.assertEqual(first["quality"]["status"], "unavailable")
        self.assertIn("conflicting_event_identity", first["quality"]["reasonCodes"])
        self.assertIsNone(first["summary"]["measuredSpanSeconds"])
        self.assertEqual(first["nodes"], [])
        self.rows.reverse()
        self.assertEqual(self.project(), first)

    def test_unrelated_conflicting_identity_preserves_selected_run_dag(self):
        baseline = self.project()
        other = [dict(row, runId="historical-run") for row in self.rows]
        other.append({**other[2], "elapsedSeconds": 1})
        self.rows += other
        result = self.project()
        self.assertNotEqual(result["quality"]["status"], "unavailable")
        self.assertEqual(result["nodes"], baseline["nodes"])
        self.assertEqual(result["summary"], baseline["summary"])
        self.assertEqual(result["logs"], baseline["logs"])
        self.rows.reverse()
        self.assertEqual(self.project(), result)
        missing = public.build_projection(self.root, run_id="absent-run", at=AT)
        self.assertEqual(missing["quality"]["reasonCodes"], ["run_not_found"])

    def test_selected_run_does_not_become_latest_neighbor_run(self):
        other = [dict(row, runId="another-private-run") for row in self.rows]
        self.rows += other
        result = self.project()
        self.assertEqual(result["summary"]["observedNodeCount"], 4)
        missing = public.build_projection(self.root, run_id="absent-run", at=AT)
        self.assertEqual(missing["quality"]["reasonCodes"], ["run_not_found"])

    def test_binding_checks_source_target_incarnation_descendants_and_all_workflows(self):
        ledger = {"pageId": "week", "target": "dev", "locales": ["ko"], "createdAt": AT, "history": []}
        metadata = {"pageId": "week", "target": "dev", "ledgerIdentitySha256": tracker.ledger_identity(ledger)}
        root = dict(self.rows[0], event="workflow_started", eventId="root", workflowId="root", metadata=metadata)
        child = dict(root, eventId="child", workflowId="private-workflow", parentWorkflowId="root", metadata={})
        self.rows += [child, root]
        self.assertTrue(public.verify_ledger_run_binding(ledger, self.rows, RUN))
        self.project(ledger=ledger)
        for changed in ({**ledger, "target": "production"}, {**ledger, "pageId": "another"},
                        {**ledger, "createdAt": timestamp(5)}):
            self.assertFalse(public.verify_ledger_run_binding(changed, self.rows, RUN))
            with self.assertRaisesRegex(ValueError, "ledger_run_binding_mismatch"):
                self.project(ledger=changed)
        self.assertFalse(public.verify_ledger_run_binding(ledger, self.rows, "wrong-run"))
        self.rows[1]["workflowId"] = "unrelated-sibling"
        self.assertFalse(public.verify_ledger_run_binding(ledger, self.rows, RUN))

    def test_binding_rejects_unrelated_log_and_changed_source_binding(self):
        ledger = tracker.new_poc_ledger("fixture-week", ["ko"], target="dev", service_date="2026-09-30",
            source_id="abcdefghijk", source_url_sha256=SHA, window_start_seconds=0, window_end_seconds=10)
        metadata = {"pageId": ledger["pageId"], "target": "dev", "ledgerIdentitySha256": tracker.ledger_identity(ledger)}
        self.rows.append(dict(self.rows[0], event="workflow_started", eventId="bound-root", metadata=metadata))
        self.assertTrue(public.verify_ledger_run_binding(ledger, self.rows, RUN))
        changed = copy.deepcopy(ledger)
        tracker.poc_source_identity(changed)["windowEndSeconds"] = 12
        # Canonical source fields, not filename or page ID, own the binding.
        self.assertFalse(public.verify_ledger_run_binding(changed, self.rows, RUN))
        self.rows.append(dict(schemaVersion=accounting.SCHEMA, runId=RUN, eventId="foreign", event="log",
            recordedAt=timestamp(8), workflowId="unrelated", code="private", level="INFO", fields={}))
        self.assertFalse(public.verify_ledger_run_binding(ledger, self.rows, RUN))
        with self.assertRaisesRegex(ValueError, "ledger_run_binding_mismatch"):
            self.project(ledger=ledger)

    def test_binding_rejects_explicit_descendant_contradictions_and_parent_cycles(self):
        ledger = {"pageId": "week", "target": "dev", "locales": ["ko"], "createdAt": AT, "history": []}
        metadata = {"pageId": "week", "target": "dev", "ledgerIdentitySha256": tracker.ledger_identity(ledger)}
        root = dict(self.rows[0], event="workflow_started", eventId="root", workflowId="root", metadata=metadata)
        child = dict(root, eventId="child", workflowId="private-workflow", parentWorkflowId="root", metadata={})
        rows = [*self.rows, root, child]
        self.assertTrue(public.verify_ledger_run_binding(ledger, rows, RUN))
        for contradiction in ({"pageId": "another-page"}, {"target": "production"}, {"ledgerIdentitySha256": "f" * 64}):
            child["metadata"] = contradiction
            self.assertFalse(public.verify_ledger_run_binding(ledger, rows, RUN))
        child["metadata"] = {"pageId": "week"}
        self.assertTrue(public.verify_ledger_run_binding(ledger, rows, RUN))
        root["parentWorkflowId"] = "private-workflow"
        self.assertFalse(public.verify_ledger_run_binding(ledger, rows, RUN))

    def test_unknown_schema_root_cannot_grant_ledger_binding(self):
        ledger = {"pageId": "week", "target": "dev", "locales": ["ko"], "createdAt": AT, "history": []}
        metadata = {"pageId": "week", "target": "dev", "ledgerIdentitySha256": tracker.ledger_identity(ledger)}
        self.rows.append(dict(self.rows[0], event="workflow_started", eventId="root", metadata=metadata,
                              schemaVersion="future-schema"))
        self.assertFalse(public.verify_ledger_run_binding(ledger, self.rows, RUN))
        with self.assertRaisesRegex(ValueError, "ledger_run_binding_mismatch"):
            self.project(ledger=ledger)

    def test_profile_excluded_workflow_root_cannot_grant_binding(self):
        ledger = {"pageId": "week", "target": "dev", "locales": ["ko"], "createdAt": AT, "history": []}
        metadata = {"pageId": "week", "target": "dev", "ledgerIdentitySha256": tracker.ledger_identity(ledger)}
        rows = events()
        rows.insert(1, dict(rows[0], event="workflow_started", eventId="root", metadata=metadata, parentWorkflowId=None))
        self.rows = profiled(rows)
        self.rows[1]["sequence"] = self.rows[0]["sequence"]
        contract.validate_event(self.rows[1])
        self.assertIn(id(self.rows[1]), accounting.profile_integrity(self.rows)["_excluded"])
        self.assertFalse(public.verify_ledger_run_binding(ledger, self.rows, RUN))
        with self.assertRaisesRegex(ValueError, "ledger_run_binding_mismatch"):
            self.project(ledger=ledger)

    def test_cross_run_global_profile_collision_cannot_grant_binding(self):
        ledger = {"pageId": "week", "target": "dev", "locales": ["ko"], "createdAt": AT, "history": []}
        metadata = {"pageId": "week", "target": "dev", "ledgerIdentitySha256": tracker.ledger_identity(ledger)}
        rows = events()
        rows.insert(1, dict(rows[0], event="workflow_started", eventId="root", metadata=metadata, parentWorkflowId=None))
        self.rows = profiled(rows)
        self.rows.append({**self.rows[1], "runId": "other-run"})
        self.assertIn(id(self.rows[1]), accounting.profile_integrity(self.rows)["_excluded"])
        self.assertFalse(public.verify_ledger_run_binding(ledger, self.rows, RUN))
        with self.assertRaisesRegex(ValueError, "ledger_run_binding_mismatch"):
            self.project(ledger=ledger)

    def test_retry_order_uses_instants_not_offset_timestamp_strings(self):
        for row in self.rows:
            if row.get("spanId") in {"source", "join"}:
                row["workUnitId"] = "same-work"
            if row.get("spanId") == "source" and row["event"] == "stage_started":
                row["startedAt"] = "2026-09-30T01:00:00+01:00"
        result = self.project()
        source = next(n for n in result["nodes"] if n["timing"]["startSeconds"] == 0)
        later = next(n for n in result["nodes"] if n["timing"]["startSeconds"] == 7)
        self.assertEqual((source["attemptNumber"], later["attemptNumber"]), (1, 2))
        self.assertEqual((source["id"], later["id"]), ("n1", "n4"))

    def test_public_json_fields_are_closed_and_no_external_actions(self):
        with patch.object(accounting, "_emit", side_effect=AssertionError("no accounting writes")), \
                patch.object(public.weekly, "project", wraps=weekly.project) as canonical:
            result = self.project()
        canonical.assert_called_once()
        self.assertEqual(set(result), {"schemaVersion", "scope", "generatedAt", "executionAuthority", "acceptance",
            "evidenceMode", "freshness", "quality", "summary", "nodes", "criticalPath", "io", "logs", "progress", "eta"})
        self.assertEqual(set(result["nodes"][0]), {"id", "kind", "code", "layer", "locale", "executorType", "modelCodes",
            "modelStatus", "dependsOn", "dependencyStatus", "unresolvedDependencyCount", "status", "evidenceMode", "attemptNumber", "retryCount",
            "timing", "io"})

    def test_bounded_cli_and_separate_output_cannot_overwrite_ledger(self):
        self.write()
        command = [sys.executable, str(Path(public.__file__)), "--accounting-dir", str(self.root), "--run-id", RUN, "--at", AT]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["schemaVersion"], public.SCHEMA)
        before = (self.root / "events.jsonl").read_bytes()
        result = subprocess.run([*command, "--output", str(self.root / "events.jsonl")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual((self.root / "events.jsonl").read_bytes(), before)
        output = self.root / "public.json"
        result = subprocess.run([*command, "--output", str(output)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(output.read_text())["schemaVersion"], public.SCHEMA)
        with patch.object(public, "MAX_INPUT_BYTES", 5):
            too_large = public.build_projection(self.root, run_id=RUN, at=AT)
        self.assertEqual(too_large["quality"]["reasonCodes"], ["accounting_too_large"])


class PlannedProgressTests(unittest.TestCase):
    setUp = PublicDagTests.setUp
    write = PublicDagTests.write
    project = PublicDagTests.project
    def test_remaining_parallel_eta_matches_canonical_scheduler(self):
        self.rows = profiled(events())
        frozen = plan([unit("a"), unit("b"), unit("c", ["a", "b"])])
        data = inputs(frozen, [receipt(frozen, key) for key in ("a", "b", "c")])
        canonical = progress.project_progress(**data, at=AT)
        result = self.project(progress_inputs=data)
        self.assertEqual(result["eta"]["status"], "estimated")
        self.assertEqual(result["eta"]["upperSeconds"], canonical["eta"]["upperSeconds"])
        self.assertEqual(result["eta"]["upperSeconds"], 40)
        self.assertEqual(result["eta"]["remainingSerialSeconds"], 60)
        self.assertEqual([n["id"] for n in result["progress"]["nodes"]], ["p1", "p2", "p3"])
        self.assertEqual(result["progress"]["nodes"][2]["dependsOn"], ["p1", "p2"])

    def test_missing_history_wait_review_and_stale_heartbeat_stay_unknown(self):
        self.rows = profiled(events())
        frozen = plan([unit("a")])
        for row, samples, reason in (
            (receipt(frozen, "a"), False, "no_comparable_history"),
            (receipt(frozen, "a", phase="waiting_review"), True, "waiting_review"),
            (receipt(frozen, "a", phase="running", executionStatus="running", heartbeatStatus="stale",
                     heartbeatAgeSeconds=100, heartbeatTimeoutSeconds=60, activeElapsedSeconds=3), True,
             "heartbeat_or_active_elapsed_unknown")):
            result = self.project(progress_inputs=inputs(frozen, [row], samples=samples))
            self.assertEqual(result["eta"]["status"], "unknown")
            self.assertIn(reason, result["eta"]["reasonCodes"])

    def test_processed_review_human_admission_are_independent(self):
        self.rows = profiled(events())
        requirements = ["executionSucceeded", "contentReviewPassed", "realHumanApproved", "admitted"]
        frozen = plan([unit("a", requirements=requirements)])
        row = success(frozen, "a", reviewVerdict="pass", reviewedArtifactSha256=SHA,
                      humanReviewKind="simulated", humanApprovalStatus="approved", humanReviewedArtifactSha256=SHA,
                      admissionStatus="admitted")
        result = self.project(progress_inputs=inputs(frozen, [row]))
        counts = result["progress"]["counts"]
        self.assertEqual((counts["processed"], counts["executionSucceeded"], counts["contentReviewPassed"]), (1, 1, 1))
        self.assertEqual((counts["realHumanApproved"], counts["simulatedHumanApproved"], counts["admitted"]), (0, 1, 1))
        self.assertFalse(result["progress"]["complete"])
        row["humanReviewKind"] = "real"
        self.assertTrue(self.project(progress_inputs=inputs(frozen, [row]))["progress"]["complete"])
        self.rows = profiled(events(), "synthetic")
        synthetic = self.project(progress_inputs=inputs(frozen, [row]))
        self.assertEqual(synthetic["evidenceMode"], "synthetic")
        self.assertEqual(synthetic["progress"]["counts"]["realHumanApproved"], 0)
        self.assertEqual(synthetic["progress"]["counts"]["admitted"], 0)
        self.assertFalse(synthetic["progress"]["complete"])
        self.assertIsNone(synthetic["progress"]["gateCompletionPercent"])
        self.assertEqual(synthetic["eta"]["status"], "unknown")

    def test_unknown_old_attempt_survives_retry_and_order_duplicate_restart(self):
        self.rows = profiled(events())
        frozen = plan([unit("a")])
        old = receipt(frozen, "a", executionStatus="outcome_unknown", phase="unknown_outcome", attempt_id="old")
        new = success(frozen, "a", sequence=2, event_id="new", attempt_id="new", workKind="rework")
        data = inputs(frozen, [new, old, copy.deepcopy(new)])
        result = self.project(progress_inputs=data)
        self.assertEqual(result["progress"]["counts"]["processed"], 1)
        self.assertEqual(result["progress"]["extraWork"]["retryAttempts"], 1)
        self.assertEqual(result["progress"]["extraWork"]["reworkAttempts"], 1)
        self.assertFalse(result["progress"]["complete"])
        self.assertIn("unknown_attempt_outcome", result["eta"]["reasonCodes"])
        data["receipts"].reverse()
        self.assertEqual(self.project(progress_inputs=data), result)
        self.assertEqual(self.project(progress_inputs=data), result)

    def test_active_elapsed_is_exact_monitor_observation_never_wall_age(self):
        self.rows = profiled(events())
        frozen = plan([unit("a")])
        row = receipt(frozen, "a", executionStatus="running", phase="running", heartbeatStatus="fresh",
            heartbeatAgeSeconds=0, heartbeatTimeoutSeconds=60, activeElapsedSeconds=3)
        data = inputs(frozen, [row])
        first = self.project(progress_inputs=data)
        self.assertEqual(first["progress"]["nodes"][0]["timing"]["activeElapsedSeconds"], 3)
        self.write()
        later = public.build_projection(self.root, run_id=RUN, at=timestamp(20), progress_inputs=data)
        self.assertEqual(later["progress"]["nodes"][0]["timing"]["activeElapsedSeconds"], 3)
        stale = public.build_projection(self.root, run_id=RUN, at=timestamp(100), progress_inputs=data)
        self.assertIsNone(stale["progress"]["nodes"][0]["timing"]["activeElapsedSeconds"])
        self.assertEqual(stale["eta"]["status"], "unknown")

    def test_duplicate_sequence_future_receipt_and_mixed_mode_fail_closed(self):
        self.rows = profiled(events())
        frozen = plan([unit("a")])
        row = success(frozen, "a")
        cases = [[row, {**row, "eventId": "conflict", "phase": "blocked"}],
                 [{**row, "observedAt": timestamp(100)}]]
        for receipts in cases:
            result = self.project(progress_inputs=inputs(frozen, receipts))
            self.assertFalse(result["progress"]["complete"])
            self.assertEqual(result["eta"]["status"], "unknown")
            self.assertEqual(result["quality"]["status"], "partial")
        self.rows[-1]["evidenceMode"] = "synthetic"
        mixed = self.project(progress_inputs=inputs(frozen, [row]))
        self.assertEqual(mixed["evidenceMode"], "mixed")
        self.assertFalse(mixed["progress"]["complete"])
        self.assertEqual(mixed["eta"]["status"], "unknown")

    def test_mismatched_plan_malformed_receipts_and_private_reason_fail_closed(self):
        self.rows = profiled(events())
        frozen = plan([unit("a")])
        altered = copy.deepcopy(frozen)
        altered["runId"] = "other"
        altered["planSha256"] = progress.digest({k: v for k, v in altered.items() if k != "planSha256"})
        result = self.project(progress_inputs=inputs(altered, []))
        self.assertIn("progress_run_mismatch", result["eta"]["reasonCodes"])
        row = success(frozen, "a")
        row["planSha256"] = "f" * 64
        result = self.project(progress_inputs=inputs(frozen, [row]))
        self.assertFalse(result["progress"]["complete"])
        self.assertEqual(result["eta"]["status"], "unknown")
        row = receipt(frozen, "a", reasonCode="private.diagnostic.secret", phase="blocked")
        result = self.project(progress_inputs=inputs(frozen, [row]))
        self.assertNotIn("private.diagnostic.secret", json.dumps(result))
        self.assertEqual(result["progress"]["nodes"][0]["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
