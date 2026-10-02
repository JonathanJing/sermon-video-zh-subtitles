import copy
import unittest
from experiments.local_experiment_log.tests.fixtures import fixture
from experiments.local_experiment_log.audit_logs import audit
from experiments.local_experiment_log.contract import digest


class ContractAuditTests(unittest.TestCase):
    def report(self, change=None, mode="fixed_sample", warm=False):
        manifest, events = fixture(mode, warm)
        if change:
            change(manifest, events)
        return audit(manifest, events)

    def test_successful_synthetic_fixed_sample(self):
        r = self.report()
        self.assertEqual(r["errors"], [])
        self.assertEqual(r["warnings"], [])
        self.assertTrue(r["trials"][0]["eligible"])
        self.assertEqual(r["trials"][0]["metrics"]["request_seconds"], 7)
        self.assertEqual(r["trials"][0]["metrics"]["inference_seconds"], 2)
        self.assertEqual(r["evidence_kind"], "synthetic")
        self.assertFalse(r["hardware_execution_independently_verified"])

    def test_successful_preload_reference(self):
        r = self.report(warm=True)
        self.assertTrue(r["trials"][0]["eligible"], r)
        self.assertEqual(r["trials"][0]["model_load_span"]["trace_id"], "synthetic-session")

    def test_successful_wall_budget(self):
        r = self.report(mode="wall_budget")
        self.assertTrue(r["trials"][0]["eligible"], r)
        self.assertAlmostEqual(r["trials"][0]["metrics"]["units_per_second"], 4 / 180)

    def test_identical_event_recollection_deduplicates(self):
        r = self.report(lambda m, es: es.append(copy.deepcopy(es[0])))
        self.assertTrue(r["trials"][0]["eligible"])
        self.assertEqual(r["duplicate_event_count"], 1)

    def test_conflicting_duplicate_fails(self):
        def mutate(m, es):
            duplicate = copy.deepcopy(es[0]); duplicate["timestamp_utc"] = "2026-10-03T00:00:00Z"; es.append(duplicate)
        self.assertTrue(self.report(mutate)["errors"])

    def test_mixed_evidence_fails(self):
        self.assertTrue(self.report(lambda m, es: es[0].update(evidence_kind="real"))["errors"])

    def test_span_cross_clock_fails(self):
        def mutate(m, es):
            next(e for e in es if e["event"] == "span.ended")["clock_id"] = "reboot-clock"
        self.assertTrue(self.report(mutate)["errors"])

    def test_gap_excludes_results(self):
        def mutate(m, es):
            es.remove(next(e for e in es if e["event"] == "resource.sampled" and e["host_role"] == "spark"))
        r = self.report(mutate)
        self.assertTrue(r["warnings"])
        self.assertEqual(r["groups"], [])

    def test_missing_terminal_excludes_results(self):
        r = self.report(lambda m, es: es.pop())
        self.assertFalse(r["trials"][0]["eligible"])

    def test_hash_mismatch_excludes_results(self):
        def mutate(m, es):
            next(e for e in es if e["event"] == "artifact.verified")["payload"]["sha256"] = "f" * 64
        self.assertIn("artifact_bytes_missing_or_mismatch", self.report(mutate)["trials"][0]["reasons"])

    def test_quality_failure_excludes_results(self):
        def mutate(m, es):
            next(e for e in es if e["event"] == "quality.checked")["payload"]["truncation_detected"] = True
        self.assertFalse(self.report(mutate)["trials"][0]["eligible"])

    def test_rejected_admission_excludes_results(self):
        def mutate(m, es):
            next(e for e in es if e["event"] == "admission.decided")["payload"]["decision"] = "rejected"
        self.assertIn("missing_admitted_job", self.report(mutate)["trials"][0]["reasons"])

    def test_admission_alone_cannot_bind_unidentified_execution(self):
        def mutate(m, es):
            for e in es:
                if e["event"] != "admission.decided":
                    e.update(job_id=None, attempt=None)
        self.assertIn("applicable_trial_evidence_missing_job_attempt", self.report(mutate)["trials"][0]["reasons"])

    def test_returned_bytes_must_carry_admitted_job_attempt(self):
        def mutate(m, es):
            next(e for e in es if e["event"] == "artifact.verified").update(job_id=None, attempt=None)
        self.assertIn("applicable_trial_evidence_missing_job_attempt", self.report(mutate)["trials"][0]["reasons"])

    def test_actual_batch_not_matching_config_excluded(self):
        def mutate(m, es):
            c = es[0]["payload"]["config"]; c["batch_size"] = 4
            for e in es:
                e["config_sha256"] = digest(c)
        self.assertIn("configured_batch_not_applied_to_frozen_units", self.report(mutate)["trials"][0]["reasons"])

    def test_cuda_submission_only_timing_excluded(self):
        def mutate(m, es):
            for e in es:
                if e["payload"].get("name") == "batch.inference":
                    e["payload"]["cuda_synchronized"] = False
        self.assertFalse(self.report(mutate)["trials"][0]["eligible"])

    def test_worker_pid_changed_excludes_preload(self):
        def mutate(m, es):
            for e in es:
                if e["payload"].get("name") == "batch.inference":
                    e["payload"]["worker_pid"] = 1000
        self.assertIn("batch_does_not_use_loaded_worker", self.report(mutate, warm=True)["trials"][0]["reasons"])

    def test_batch_terminal_pid_changed_excludes_preload(self):
        def mutate(m, es):
            for e in es:
                if e["event"] == "span.ended" and e["payload"].get("name") == "batch.inference":
                    e["payload"]["worker_pid"] = 1000
        self.assertIn("batch_does_not_use_loaded_worker", self.report(mutate, warm=True)["trials"][0]["reasons"])

    def test_template_values_are_not_events(self):
        r = self.report(lambda m, es: es[0].update(event_id=None))
        self.assertTrue(r["errors"])

    def test_missing_required_business_layers_excluded(self):
        def mutate(m, es):
            m["required_layers"] = ["L1", "L2", "L3", "L4"]
            m["layer_component_mapping"].update({"source": "L1", "text": "L2", "delivery": "L4"})
        self.assertIn("required_logical_layer_trace_incomplete", self.report(mutate)["trials"][0]["reasons"])

    def test_budget_late_batch_not_credited(self):
        def mutate(m, es):
            q = [e for e in es if e["event"] == "quality.checked"][-1]
            q["monotonic_ns"] = 183_100_000_000
            # Preserve the actual timer expiry order after delayed validation.
            worker_es = [e for e in es if e["host_role"] == "spark"]
            for i, e in enumerate(sorted(worker_es, key=lambda e: e["monotonic_ns"]), 1):
                e["sequence"] = i
        r = self.report(mutate, mode="wall_budget")
        self.assertTrue(r["trials"][0]["eligible"], r)
        self.assertEqual(r["trials"][0]["metrics"]["completed_units"], 2)
        self.assertEqual(r["trials"][0]["metrics"]["inference_seconds"], 1)
        self.assertEqual(r["trials"][0]["metrics"]["inference_seconds_all_observed_batches"], 2)

    def test_shortened_wall_budget_excluded(self):
        def mutate(m, es):
            e = next(e for e in es if e["event"] == "span.ended" and e["payload"]["name"] == "workload.budget")
            e["monotonic_ns"] = 6_000_000_000
        r = self.report(mutate, mode="wall_budget")
        self.assertIn("budget_span_does_not_match_fixed_duration", r["trials"][0]["reasons"])

    def test_nonfinite_payload_rejected(self):
        r = self.report(lambda m, es: es[0]["payload"]["config"]["generation"].update(temperature=float("nan")))
        self.assertTrue(r["errors"])

    def test_parent_cycle_rejected(self):
        def mutate(m, es):
            for e in es:
                if e["span_id"] == "request":
                    e["parent_span_id"] = "request"
        self.assertTrue(self.report(mutate)["errors"])

    def test_timeout_terminal_retained_and_excluded(self):
        r = self.report(lambda m, es: es[-1]["payload"].update(status="timeout"))
        self.assertFalse(r["trials"][0]["eligible"])
        self.assertEqual(r["groups"], [])


if __name__ == "__main__":
    unittest.main()
