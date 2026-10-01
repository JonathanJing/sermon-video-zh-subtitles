"""Offline evidence/denominator and remaining-DAG acceptance fixtures."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import four_layer_progress as tracker
from scripts import sermon_run_progress as p
from scripts.sermon_accounting import SCHEMA as ACCOUNTING_SCHEMA

AT = "2026-10-01T01:00:00+00:00"
SHA = "a" * 64
FIXTURE = Path(__file__).parent / "fixtures" / "sermon_run_progress" / "offline-scenarios.json"


def unit(key, deps=(), *, locale="ko", resources=("api",), weight=1, requirements=None, prior=None):
    row = {"id": key, "identitySha256": p.digest({"source": SHA, "unit": key}),
           "stage": "translation", "model": "fixture-model", "locale": locale,
           "lengthBucket": "short", "cacheClass": "fresh", "resourceClass": "fixture-api",
           "dependsOn": list(deps), "weight": weight, "resources": list(resources),
           "requiredEvidence": requirements or ["executionSucceeded"]}
    if prior:
        row["priorSeconds"] = prior
    return row


def plan(units, capacity=2, **kwargs):
    return p.freeze_plan("fixture-plan", kwargs.pop("version", 1), "fixture-run", units,
                         {"api": {"capacity": capacity, "resourceClass": "fixture-api"}},
                         dag_version="fixture-dag-v1", **kwargs)


def pools(capacity=2, queue=None):
    return {"api": {"capacity": capacity, "resourceClass": "fixture-api", "status": "ready",
                    "queueSeconds": queue or [0] * capacity, "observedAt": AT, "maxAgeSeconds": 60}}


def sample(unit_row, seconds=10, key="sample"):
    return {**{k: unit_row[k] for k in p.DIMENSIONS}, "sampleId": key, "workUnitId": key, "elapsedSeconds": seconds,
            "sourceRef": "fixture-timing", "observedAt": AT, "executionStatus": "succeeded", "measurementKind": "empirical"}


def done(frozen, key, **fields):
    defaults = dict(executionStatus="succeeded", phase="complete", evidenceValidated=True,
                    artifactSha256=SHA, evidenceRefs=["fixture-receipt"])
    defaults.update(fields)
    return p.status_receipt(frozen, key, event_id=defaults.pop("event_id", "done-" + key),
                            attempt_id=defaults.pop("attempt_id", "attempt-" + key),
                            sequence=defaults.pop("sequence", 1), observed_at=AT, **defaults)


def project(frozen, receipts=(), samples=None, resource_state=None, **kwargs):
    return p.project_progress(frozen, receipts, samples=samples or [sample(frozen["units"][0])], at=AT,
                              resource_state=resource_state or pools(frozen["resources"]["api"]["capacity"]), **kwargs)


class ProgressEvidenceTests(unittest.TestCase):
    def test_fixed_weight_and_locale_counts_no_task_count_denominator(self):
        frozen = plan([unit("a", weight=3), unit("b", locale="es")])
        result = project(frozen, [done(frozen, "a")])
        self.assertEqual(result["plannedCompletionPercent"], 75)
        self.assertEqual(result["denominator"], "4")
        self.assertEqual(result["counts"]["done"], 1)
        self.assertEqual(result["phaseLocales"][0]["locale"], "es")
        self.assertEqual(result["currentPhases"], ["translation"])

    def test_processed_failed_is_not_execution_success_or_completion(self):
        frozen = plan([unit("a")])
        failed = p.status_receipt(frozen, "a", event_id="failed", attempt_id="one", sequence=1, observed_at=AT,
                                  executionStatus="failed", phase="blocked", reasonCode="provider_failed")
        result = project(frozen, [failed])
        self.assertEqual(result["counts"]["processed"], 1)
        self.assertEqual(result["counts"]["executionSucceeded"], 0)
        self.assertEqual(result["plannedCompletionPercent"], 0)
        self.assertEqual(result["eta"]["status"], "unknown")

    def test_unknown_review_human_and_simulated_human_never_real_approval(self):
        frozen = plan([unit("a", requirements=["executionSucceeded", "contentReviewPassed", "realHumanApproved", "admitted"])])
        result = project(frozen, [done(frozen, "a")])
        self.assertEqual(result["plannedCompletionPercent"], 0)
        self.assertEqual(result["counts"]["executionSucceeded"], 1)
        simulated = done(frozen, "a", reviewVerdict="pass", reviewedArtifactSha256=SHA,
                         humanReviewKind="simulated", humanApprovalStatus="approved",
                         humanReviewedArtifactSha256=SHA, admissionStatus="admitted")
        result = project(frozen, [simulated])
        self.assertEqual(result["counts"]["contentReviewPassed"], 1)
        self.assertEqual(result["counts"]["simulatedHumanApproved"], 1)
        self.assertEqual(result["counts"]["realHumanApproved"], 0)
        self.assertFalse(result["complete"])
        actual = {**simulated, "humanReviewKind": "real"}
        result = project(frozen, [actual])
        self.assertTrue(result["complete"])
        self.assertEqual(result["plannedCompletionPercent"], 100)

    def test_review_hash_mismatch_missing_validation_and_unbound_receipts(self):
        frozen = plan([unit("a")])
        valid = done(frozen, "a")
        for invalid in ({**valid, "planSha256": "b" * 64}, {**valid, "identitySha256": "b" * 64},
                        {**valid, "reviewVerdict": "pass", "reviewedArtifactSha256": "b" * 64},
                        {**valid, "unitId": "unplanned"}):
            with self.subTest(invalid=invalid):
                result = project(frozen, [invalid])
                self.assertFalse(result["complete"])
                self.assertEqual(result["plannedCompletionPercent"], 0)
        result = project(frozen, [{**valid, "evidenceValidated": False}])
        self.assertEqual(result["counts"]["executionSucceeded"], 0)

    def test_conflicting_events_sequences_and_duplicate_replay(self):
        frozen = plan([unit("a")])
        valid = done(frozen, "a")
        self.assertTrue(project(frozen, [valid, copy.deepcopy(valid)])["complete"])
        for other in ({**valid, "phase": "blocked"}, {**valid, "eventId": "other", "phase": "blocked"}):
            result = project(frozen, [valid, other])
            self.assertFalse(result["complete"])
            self.assertLess(result["plannedCompletionPercent"], 100)

    def test_downstream_receipt_cannot_complete_missing_upstream(self):
        frozen = plan([unit("a"), unit("b", ["a"])])
        result = project(frozen, [done(frozen, "b")])
        self.assertEqual(result["counts"]["executionSucceeded"], 1)
        self.assertEqual(result["counts"]["done"], 0)
        self.assertEqual(result["units"][1]["blockedReason"], "dependency_unresolved")

    def test_retry_rework_separate_denominator_and_unknown_not_erased(self):
        frozen = plan([unit("a")])
        unknown = p.status_receipt(frozen, "a", event_id="unknown", attempt_id="one", sequence=1,
                                   observed_at=AT, executionStatus="outcome_unknown", phase="unknown_outcome")
        repaired = done(frozen, "a", attempt_id="two", sequence=2, workKind="rework")
        result = project(frozen, [unknown, repaired])
        self.assertFalse(result["complete"])
        self.assertEqual(result["extraWork"], {"retryAttempts": 1, "reworkAttempts": 1, "includedInDenominator": False})
        self.assertEqual(result["denominator"], "1")
        reconciled = {**repaired, "reconcilesAttemptIds": ["one"]}
        proof = p.reconciliation_proof(frozen, "a", "one", proof_id="proof", unknown_event_id="unknown",
                                        evidence_sha256=SHA, evidence_refs=["durable-reconciliation"],
                                        outcome="failed", evidence_validated=True)
        self.assertFalse(project(frozen, [unknown, reconciled])["complete"])
        self.assertTrue(project(frozen, [unknown, reconciled], reconciliations=[proof])["complete"])

    def test_primary_processed_weight_retains_failed_history_through_retry(self):
        frozen = plan([unit("a", weight=3), unit("b")])
        failed = p.status_receipt(frozen, "a", event_id="failed", attempt_id="one", sequence=1, observed_at=AT,
                                  executionStatus="failed", phase="blocked")
        pending = p.status_receipt(frozen, "b", event_id="pending", attempt_id="b", sequence=1, observed_at=AT)
        retry = p.status_receipt(frozen, "a", event_id="retry", attempt_id="two", sequence=2, observed_at=AT,
                                 executionStatus="running", phase="retrying", heartbeatStatus="fresh",
                                 heartbeatAgeSeconds=1, heartbeatTimeoutSeconds=30, activeElapsedSeconds=1)
        for history in ([failed, pending], [failed, retry, pending]):
            result = project(frozen, history)
            self.assertEqual(result["plannedProcessedPercent"], 75)
            self.assertEqual(result["knownProcessedWeight"], "3")
            self.assertEqual(result["counts"]["processed"], 1)
            self.assertEqual(result["gateCompletionPercent"], 0)
            self.assertFalse(result["complete"])

    def test_unknown_processed_weight_and_review_applicability_are_explicit(self):
        frozen = plan([unit("a", weight=3), unit("b")])
        unknown = p.status_receipt(frozen, "a", event_id="unknown", attempt_id="one", sequence=1,
                                   observed_at=AT, executionStatus="outcome_unknown", phase="unknown_outcome")
        pending = p.status_receipt(frozen, "b", event_id="pending", attempt_id="b", sequence=1, observed_at=AT)
        result = project(frozen, [unknown, pending])
        self.assertIsNone(result["plannedProcessedPercent"])
        self.assertEqual(result["processingCoverage"]["unknownWeight"], "3")
        self.assertEqual(result["processingCoverage"]["unknownUnits"], ["a"])
        self.assertEqual(result["knownProcessedPercentLowerBound"], 0)
        self.assertEqual(result["evidenceProgress"]["realHumanApproved"]["status"], "not_applicable")
        self.assertIsNone(result["evidenceProgress"]["realHumanApproved"]["percent"])
        passed = done(frozen, "a")
        conflicting = {**passed, "eventId": "conflict"}
        self.assertIsNone(project(frozen, [passed, conflicting, pending])["plannedProcessedPercent"])

    def test_reconciliation_requires_independent_validated_proof_of_exact_old_attempt(self):
        frozen = plan([unit("a")])
        unknown = p.status_receipt(frozen, "a", event_id="unknown", attempt_id="one", sequence=1,
                                   observed_at=AT, executionStatus="outcome_unknown", phase="unknown_outcome")
        assertion = p.status_receipt(frozen, "a", event_id="assertion", attempt_id="two", sequence=2,
                                     observed_at=AT, reconcilesAttemptIds=["one"])
        def proof(**changes):
            options = dict(proof_id="proof", unknown_event_id="unknown", evidence_sha256=SHA,
                           evidence_refs=["durable-reconciliation"], outcome="failed", evidence_validated=True)
            options.update(changes)
            return p.reconciliation_proof(frozen, "a", options.pop("attempt_id", "one"), **options)
        invalid = [[], [proof(evidence_validated=False)], [proof(evidence_refs=[])],
                   [proof(attempt_id="other")], [proof(unknown_event_id="different-event")]]
        for proofs in invalid:
            result = project(frozen, [unknown, assertion], reconciliations=proofs)
            self.assertEqual(result["eta"]["status"], "unknown")
            self.assertEqual(result["units"][0]["blockedReason"], "attempt_outcome_requires_reconciliation")
        valid = project(frozen, [unknown, assertion], reconciliations=[proof()])
        self.assertEqual(valid["eta"]["status"], "estimated")
        self.assertFalse(valid["complete"])
        self.assertEqual(valid["plannedProcessedPercent"], 100)
        self.assertEqual(valid["gateCompletionPercent"], 0)

    def test_plan_hash_drift_and_explicit_versioned_transition(self):
        first = plan([unit("a")])
        previous = project(first)
        same_version = plan([unit("a"), unit("b")])
        with self.assertRaisesRegex(ValueError, "versioned_plan_migration"):
            project(same_version, previous=previous)
        new = plan([unit("a"), unit("b")], version=2, supersedes=first["planSha256"], migration_reason="new-unit")
        result = project(new, previous=previous)
        self.assertEqual(result["planTransition"]["previousDenominator"], "1")
        tampered = copy.deepcopy(first)
        tampered["denominator"] = "0.5"
        with self.assertRaisesRegex(ValueError, "denominator_drift"):
            project(tampered)

    def test_incomplete_rounding_never_yields_false_100(self):
        frozen = plan([unit("a", weight=10**12), unit("b", weight=1)])
        result = project(frozen, [done(frozen, "a")])
        self.assertEqual(result["plannedCompletionPercent"], 99.999999)
        self.assertEqual(result["knownProcessedPercentLowerBound"], 99.999999)
        self.assertFalse(result["complete"])

    def test_input_integrity_issues_hold_completion_and_future_receipt_rejected(self):
        frozen = plan([unit("a")])
        result = project(frozen, [done(frozen, "a")], input_issues=["damaged_accounting_snapshot"])
        self.assertFalse(result["complete"])
        self.assertLess(result["plannedCompletionPercent"], 100)
        future = {**done(frozen, "a"), "observedAt": "2026-10-02T01:00:00Z"}
        self.assertFalse(project(frozen, [future])["complete"])

    def test_full_closed_status_and_explicit_complete_phase_required(self):
        frozen = plan([unit("a")])
        valid = done(frozen, "a")
        partial = copy.deepcopy(valid)
        partial.pop("reviewVerdict")
        for row in (partial, {**valid, "taskCount": 200}, {**valid, "phase": "running"}):
            self.assertFalse(project(frozen, [row])["complete"])

    def test_changed_artifact_cannot_reuse_old_human_approval(self):
        frozen = plan([unit("a", requirements=["executionSucceeded", "realHumanApproved"])])
        approved = done(frozen, "a", humanReviewKind="real", humanApprovalStatus="approved", humanReviewedArtifactSha256=SHA)
        changed = {**approved, "artifactSha256": "b" * 64}
        result = project(frozen, [changed])
        self.assertEqual(result["counts"]["realHumanApproved"], 0)
        self.assertFalse(result["complete"])


class EtaProjectionTests(unittest.TestCase):
    def test_null_unit_queue_keeps_processed_progress_and_degrades_eta(self):
        frozen = plan([unit("a"), unit("b")])
        pending = p.status_receipt(frozen, "b", event_id="pending", attempt_id="b", sequence=1,
                                   observed_at=AT, queueRemainingSeconds=None)
        result = project(frozen, [done(frozen, "a"), pending])
        self.assertEqual(result["plannedProcessedPercent"], 50)
        self.assertEqual(result["gateCompletionPercent"], 50)
        self.assertEqual(result["eta"]["status"], "unknown")
        self.assertIn("unit_queue_unknown", result["eta"]["reasonCodes"])

    def test_serial_parallel_resource_limit_and_known_queue_fixture(self):
        fixture = json.loads(FIXTURE.read_text())
        for scenario in fixture["scenarios"]:
            with self.subTest(scenario=scenario["name"]):
                frozen = plan([unit(row["id"], row["dependsOn"]) for row in scenario["units"]], scenario["capacity"])
                result = project(frozen, resource_state=pools(scenario["capacity"], scenario["queueSeconds"]))
                self.assertEqual(result["eta"]["status"], "estimated")
                self.assertEqual(result["eta"]["upperSeconds"], scenario["upperSeconds"])
                self.assertEqual(result["eta"]["criticalPathSeconds"], scenario["criticalPathSeconds"])
                self.assertEqual(result["eta"]["remainingSerialSeconds"], scenario["serialSeconds"])

    def test_multiresource_capacity_and_locale_parallel_convergence(self):
        units = [unit("source"), unit("ko", ["source"], resources=["api", "gpu"]),
                 unit("es", ["source"], resources=["api", "gpu"]), unit("join", ["ko", "es"])]
        frozen = p.freeze_plan("fixture-plan", 1, "fixture-run", units,
                               {"api": {"capacity": 2, "resourceClass": "fixture-api"},
                                "gpu": {"capacity": 1, "resourceClass": "fixture-gpu"}}, dag_version="fixture-dag-v1")
        resources = pools()
        resources["gpu"] = {**resources["api"], "capacity": 1, "resourceClass": "fixture-gpu", "queueSeconds": [0]}
        result = project(frozen, resource_state=resources)
        self.assertEqual(result["eta"]["upperSeconds"], 80)
        self.assertEqual(result["eta"]["criticalPathSeconds"], 60)

    def test_empirical_matching_stage_model_locale_length_cache_resource(self):
        frozen = plan([unit("a")])
        matching = sample(frozen["units"][0])
        for dimension in p.DIMENSIONS:
            with self.subTest(dimension=dimension):
                other = {**matching, dimension: "different"}
                result = project(frozen, samples=[other])
                self.assertIsNone(result["eta"]["upperSeconds"])
                self.assertEqual(result["eta"]["perUnit"]["a"]["sampleCount"], 0)

    def test_current_run_measurement_updates_without_invented_history(self):
        frozen = plan([unit("a"), unit("b")])
        measured = done(frozen, "a", elapsedSeconds=30, measurementValidated=True, timingSampleId="fixture-current-span")
        result = p.project_progress(frozen, [measured], at=AT, resource_state=pools())
        self.assertEqual(result["eta"]["sampleCount"], 1)
        self.assertEqual(result["eta"]["upperSeconds"], 60)
        self.assertEqual(result["eta"]["confidence"], "low")
        unmeasured = {**measured, "measurementValidated": False}
        self.assertEqual(p.project_progress(frozen, [unmeasured], at=AT, resource_state=pools())["eta"]["status"], "unknown")

    def test_cold_start_prior_low_confidence_zero_samples_and_no_prior_unknown(self):
        frozen = plan([unit("a", prior={"lower": 5, "upper": 90, "sourceRef": "planning-prior"})])
        result = p.project_progress(frozen, [], at=AT, resource_state=pools())
        self.assertEqual(result["eta"]["upperSeconds"], 90)
        self.assertEqual(result["eta"]["sampleCount"], 0)
        self.assertEqual(result["eta"]["confidence"], "low")
        self.assertEqual(p.project_progress(plan([unit("a")]), [], at=AT, resource_state=pools())["eta"]["status"], "unknown")

    def test_missing_stale_queue_outage_and_capacity_change_unknown(self):
        frozen = plan([unit("a")])
        for change in ({"status": "outage"}, {"queueSeconds": [None, 0]}, {"capacity": 1},
                       {"observedAt": "2026-09-30T01:00:00Z"}):
            resource = pools()
            resource["api"].update(change)
            self.assertEqual(project(frozen, resource_state=resource)["eta"]["status"], "unknown")
        self.assertEqual(p.project_progress(frozen, [], samples=[sample(frozen["units"][0])], at=AT)["eta"]["status"], "unknown")

    def test_active_remaining_duration_heartbeat_stale_unknown_and_overrun(self):
        frozen = plan([unit("a")])
        running = p.status_receipt(frozen, "a", event_id="running", attempt_id="one", sequence=1, observed_at=AT,
                                   executionStatus="running", phase="running", heartbeatStatus="fresh",
                                   heartbeatAgeSeconds=1, heartbeatTimeoutSeconds=30, activeElapsedSeconds=6)
        result = project(frozen, [running])
        self.assertEqual(result["eta"]["upperSeconds"], 14)
        self.assertEqual(result["eta"]["lowerSeconds"], 0)
        for change in ({"heartbeatStatus": "stale"}, {"heartbeatStatus": "unknown"},
                       {"activeElapsedSeconds": 30}, {"activeElapsedSeconds": None},
                       {"observedAt": "2026-10-01T00:59:00Z"}):
            self.assertEqual(project(frozen, [{**running, **change}])["eta"]["status"], "unknown")

    def test_human_wait_blocked_unknown_and_review_inconclusive_have_no_eta(self):
        frozen = plan([unit("a", requirements=["executionSucceeded", "contentReviewPassed"])])
        for phase, execution, verdict in (("waiting_review", "succeeded", "not_assessed"),
                                         ("blocked", "succeeded", "inconclusive"),
                                         ("unknown_outcome", "outcome_unknown", "not_assessed")):
            row = done(frozen, "a", phase=phase, executionStatus=execution, reviewVerdict=verdict)
            result = project(frozen, [row])
            self.assertEqual(result["eta"]["status"], "unknown")
            self.assertIsNone(result["eta"]["latestAt"])
            self.assertEqual(result["plannedCompletionPercent"], 0)

    def test_duplicate_samples_conflict_and_failed_samples_not_performance_history(self):
        frozen = plan([unit("a")])
        valid = sample(frozen["units"][0])
        result = project(frozen, samples=[valid, copy.deepcopy(valid)])
        self.assertEqual(result["eta"]["sampleCount"], 1)
        for other in ({**valid, "elapsedSeconds": 20}, {**valid, "executionStatus": "failed"}):
            self.assertEqual(project(frozen, samples=[valid, other])["eta"]["status"], "unknown")

    def test_distinct_exports_for_same_work_unit_count_only_once(self):
        frozen = plan([unit("a")])
        first = sample(frozen["units"][0], key="span-one")
        replay = {**first, "sampleId": "span-two", "sourceRef": "replayed-export"}
        result = project(frozen, samples=[first, replay])
        self.assertEqual(result["eta"]["sampleCount"], 1)
        self.assertEqual(result["eta"]["confidence"], "low")
        conflict = {**replay, "elapsedSeconds": 20}
        self.assertEqual(project(frozen, samples=[first, conflict])["eta"]["status"], "unknown")

    def test_current_measurement_duplicate_external_sample_counted_once(self):
        frozen = plan([unit("a"), unit("b")])
        measured = done(frozen, "a", elapsedSeconds=30, measurementValidated=True, timingSampleId="span-fixture")
        external = {**sample(frozen["units"][0], 30, "span-fixture"),
                    "workUnitId": p._completed_work_unit_id(frozen["runId"], "a", measured["attemptId"]),
                    "sourceRef": "span-fixture"}
        result = project(frozen, [measured], samples=[external])
        self.assertEqual(result["eta"]["sampleCount"], 1)
        self.assertEqual(result["eta"]["status"], "estimated")

    def test_active_units_cannot_exceed_observed_pool_or_run_before_gate(self):
        frozen = plan([unit("a"), unit("b")], capacity=1)
        def running(frozen, key):
            return p.status_receipt(frozen, key, event_id="running-" + key, attempt_id=key, sequence=1, observed_at=AT,
                                     executionStatus="running", phase="running", heartbeatStatus="fresh",
                                     heartbeatAgeSeconds=1, heartbeatTimeoutSeconds=30, activeElapsedSeconds=1)
        result = project(frozen, [running(frozen, "a"), running(frozen, "b")])
        self.assertEqual(result["eta"]["status"], "unknown")
        gated = plan([unit("a"), unit("b", ["a"])])
        self.assertEqual(project(gated, [running(gated, "b")])["eta"]["status"], "unknown")


class AdapterAndDurabilityTests(unittest.TestCase):
    def test_cli_null_unit_queue_writes_progress_and_unknown_eta(self):
        scenario = json.loads(FIXTURE.read_text())["scenarios"][1]
        frozen = plan([unit(row["id"], row["dependsOn"]) for row in scenario["units"]], scenario["capacity"])
        pending = p.status_receipt(frozen, "b", event_id="pending", attempt_id="b", sequence=1,
                                   observed_at=AT, queueRemainingSeconds=None)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            values = {"plan": frozen, "receipts": [done(frozen, "a"), pending],
                      "samples": [sample(frozen["units"][0])], "resource-state": pools(scenario["capacity"], scenario["queueSeconds"])}
            for name, value in values.items():
                (root / (name + ".json")).write_text(json.dumps(value))
            command = [sys.executable, "scripts/sermon_run_progress.py", "project", "--at", AT,
                       "--output", str(root / "progress.json")]
            for name in values:
                command += ["--" + name, str(root / (name + ".json"))]
            result = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            snapshot = json.loads((root / "progress.json").read_text())
            self.assertEqual(snapshot["plannedProcessedPercent"], 50)
            self.assertEqual(snapshot["eta"]["status"], "unknown")
            self.assertIn("unit_queue_unknown", snapshot["eta"]["reasonCodes"])

    def test_tracker_dependency_reuse_never_imports_complete_checkpoints(self):
        ledger = tracker.new_ledger("fixture-page", ["ko"])
        for row in ledger["steps"].values():
            row["status"] = "complete"
        specs = {key: unit(key) for key in ledger["steps"]}
        for row in specs.values():
            row.pop("id"); row.pop("dependsOn"); row.pop("stage"); row.pop("locale")
        frozen = p.plan_from_tracker(ledger, "fixture-plan", 1, "fixture-run", specs,
                                     {"api": {"capacity": 2, "resourceClass": "fixture-api"}}, dag_version="tracker-v1")
        index = {row["id"]: row for row in frozen["units"]}
        self.assertEqual(index["L2-02@ko"]["dependsOn"], ["L1-04", "L2-01@ko"])
        result = project(frozen)
        self.assertEqual(result["counts"]["done"], 0)
        self.assertEqual(result["plannedCompletionPercent"], 0)

    def test_accounting_explicit_bound_leaf_reuses_projector_and_grants_no_status(self):
        frozen = plan([unit("a")])
        base = {"schemaVersion": ACCOUNTING_SCHEMA, "runId": "accounting-run", "stage": "translation",
                "spanId": "span", "executorType": "production_model", "dependsOn": [], "workUnitId": "a", "attemptId": "one"}
        rows = [{**base, "event": "stage_started", "eventId": "start", "recordedAt": "2026-10-01T00:59:50Z", "startedAt": "2026-10-01T00:59:50Z"},
                {**base, "event": "stage_finished", "eventId": "end", "recordedAt": AT, "elapsedSeconds": 10, "status": "completed"},
                {**base, "event": "sdk_call_finished", "eventId": "call", "recordedAt": AT, "model": "fixture-model",
                 "invocationId": "sdk-fixture", "status": "completed", "usage": {}}]
        binding = {"span": {"accountingRunId": "accounting-run", "accountingWorkUnitId": "a", "unitId": "a",
                            "identitySha256": frozen["units"][0]["identitySha256"],
                            **{k: frozen["units"][0][k] for k in p.DIMENSIONS}}}
        original = copy.deepcopy(rows)
        result = p.samples_from_accounting(frozen, rows, binding)
        self.assertEqual(len(result["samples"]), 1)
        self.assertEqual(result["statusReceipts"], [])
        self.assertEqual(rows, original)
        self.assertEqual(p.samples_from_accounting(frozen, rows, {})["samples"], [])
        changed = copy.deepcopy(binding)
        changed["span"]["identitySha256"] = "b" * 64
        self.assertEqual(p.samples_from_accounting(frozen, rows, changed)["samples"], [])
        unbound = copy.deepcopy(binding)
        unbound["span"].pop("cacheClass")
        self.assertEqual(p.samples_from_accounting(frozen, rows, unbound)["samples"], [])

    def test_accounting_unknown_paid_outcome_cannot_seed_eta_history(self):
        frozen = plan([unit("a")])
        rows = [{"schemaVersion": ACCOUNTING_SCHEMA, "runId": "run", "eventId": "call", "event": "api_attempt_started",
                 "attemptId": "unknown", "stage": "translation", "model": "fixture-model", "recordedAt": AT}]
        binding = {"span": {"accountingRunId": "run", "accountingWorkUnitId": "a", "unitId": "a",
                            "identitySha256": frozen["units"][0]["identitySha256"],
                            **{k: frozen["units"][0][k] for k in p.DIMENSIONS}}}
        result = p.samples_from_accounting(frozen, rows, binding)
        self.assertEqual(result["samples"], [])
        self.assertIn("accounting_unknown_paid_outcome", result["reasonCodes"])

    def test_atomic_readable_snapshot_refuses_ledger_and_preserves_after_write_failure(self):
        frozen = plan([unit("a")])
        snapshot = project(frozen)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "progress.json"
            p.write_progress(path, snapshot)
            original = path.read_bytes()
            with patch.object(p.os, "replace", side_effect=OSError("fixture-crash")):
                with self.assertRaises(OSError):
                    p.write_progress(path, {**snapshot, "updatedAt": "2026-10-01T01:00:01Z"})
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(json.loads(original)["schemaVersion"], p.SCHEMA)
            path.write_text(json.dumps({"schemaVersion": "existing-run-ledger"}))
            preserved = path.read_bytes()
            with self.assertRaises(ValueError):
                p.write_progress(path, snapshot)
            self.assertEqual(path.read_bytes(), preserved)
            self.assertEqual(list(Path(folder).glob(".run-progress-*")), [])

    def test_versioned_atomic_write_and_older_snapshot_refused(self):
        first = plan([unit("a")])
        previous = project(first)
        second = plan([unit("a"), unit("b")], version=2, supersedes=first["planSha256"], migration_reason="new-unit")
        current = project(second, previous=previous)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "progress.json"
            p.write_progress(path, previous)
            p.write_progress(path, current)
            self.assertEqual(json.loads(path.read_text())["denominator"], "2")
            with self.assertRaises(ValueError):
                p.write_progress(path, previous)

    def test_cli_offline_json_and_inputs_unchanged(self):
        frozen = plan([unit("a")])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, value in (("plan.json", frozen), ("receipts.json", [done(frozen, "a")])):
                (root / name).write_text(json.dumps(value))
            before = {path: path.read_bytes() for path in root.iterdir()}
            command = [sys.executable, "scripts/sermon_run_progress.py", "project", "--plan", str(root / "plan.json"),
                       "--receipts", str(root / "receipts.json"), "--at", AT, "--output", str(root / "progress.json")]
            result = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads((root / "progress.json").read_text())["complete"])
            self.assertEqual({path: path.read_bytes() for path in before}, before)
            collision = command[:-1] + [str(root / "receipts.json")]
            self.assertEqual(subprocess.run(collision, capture_output=True).returncode, 2)

    def test_freeze_cli_is_exclusive_and_invalid_dag_fails(self):
        for invalid in ([unit("a", ["missing"])], [unit("a", ["b"]), unit("b", ["a"])], [unit("a"), unit("a")]):
            with self.assertRaises(ValueError):
                plan(invalid)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            spec = dict(plan_id="fixture", version=1, run_id="run", units=[unit("a")],
                        resources={"api": {"capacity": 2, "resourceClass": "fixture-api"}}, dag_version="v1")
            (root / "spec.json").write_text(json.dumps(spec))
            command = [sys.executable, "scripts/sermon_run_progress.py", "freeze", "--input", str(root / "spec.json"), "--output", str(root / "plan.json")]
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)
            before = (root / "plan.json").read_bytes()
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 2)
            self.assertEqual((root / "plan.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
