import copy
import unittest
from experiments.local_experiment_log.tests.canonical_fixtures import compatible_fixture
from experiments.local_experiment_log.canonical_bridge import accounting, convert, verify_pair
from experiments.local_experiment_log.audit_logs import audit


class CanonicalCompatibilityTests(unittest.TestCase):
    def converted(self, warm=False):
        manifest, events, contexts = compatible_fixture(warm)
        starts = {(e["trace_id"], e["span_id"]): e for e in events if e["event"] == "span.started"}
        rows = [convert(e, contexts[e["event_id"]], starts.get((e["trace_id"], e["span_id"]))) for e in events]
        return manifest, events, contexts, rows

    def test_existing_schema_and_canonical_replay_accept_all_events(self):
        manifest, events, contexts, rows = self.converted()
        for row, sidecar in zip(rows, events):
            verify_pair(row, sidecar)
            self.assertNotIn("experiment_id", row)
            self.assertEqual(row["runId"], contexts[sidecar["event_id"]]["runId"])
        self.assertEqual(accounting.replay_integrity(rows)["status"], "consistent")
        self.assertTrue(audit(manifest, events)["trials"][0]["eligible"])

    def test_preload_sidecar_preserves_canonical_run_trace_identity(self):
        _, events, _, rows = self.converted(warm=True)
        self.assertEqual(accounting.replay_integrity(rows)["status"], "consistent")
        self.assertEqual(len({r["runId"] for r in rows}), 2)
        for row, event in zip(rows, events):
            verify_pair(row, event)

    def test_context_identity_conflict_rejected(self):
        _, events, contexts = compatible_fixture()
        ctx = copy.deepcopy(contexts[events[0]["event_id"]]); ctx["runId"] = "changed"
        # runId is caller-owned; changing it is caught by replay's trace binding.
        ctx["eventId"] = "f" * 32
        with self.assertRaisesRegex(ValueError, "alias_conflict"):
            convert(events[0], ctx)

    def test_no_unknown_production_fields_allowed(self):
        _, events, contexts = compatible_fixture()
        ctx = copy.deepcopy(contexts[events[0]["event_id"]]); ctx["experimentId"] = "new-top-field"
        with self.assertRaisesRegex(ValueError, "context_incomplete_or_unknown"):
            convert(events[0], ctx)

    def test_run_trace_binding_cannot_change(self):
        _, events, contexts = compatible_fixture()
        ctx = copy.deepcopy(contexts[events[0]["event_id"]]); ctx["runId"] = "changed-run"
        with self.assertRaisesRegex(ValueError, "run_trace_binding_conflict"):
            convert(events[0], ctx)

    def test_sidecar_tampering_rejected(self):
        _, events, _, rows = self.converted()
        event = copy.deepcopy(events[0]); event["payload"]["config"]["generation"]["temperature"] = .9
        from experiments.local_experiment_log.contract import digest
        event["config_sha256"] = digest(event["payload"]["config"])
        with self.assertRaisesRegex(ValueError, "sidecar_hash_conflict"):
            verify_pair(rows[0], event)

    def test_hosts_cannot_be_used_as_production_layers(self):
        _, events, contexts = compatible_fixture()
        event = copy.deepcopy(events[0]); event["layer_id"] = "L1"
        with self.assertRaisesRegex(ValueError, "logical_layer_conflict"):
            convert(event, contexts[event["event_id"]])

    def test_job_alias_cannot_change_between_canonical_and_sidecar(self):
        _, events, _, rows = self.converted()
        row = copy.deepcopy(rows[0]); row["jobId"] = "different-job"
        with self.assertRaisesRegex(ValueError, "sidecar_job_conflict"):
            verify_pair(row, events[0])

    def test_existing_attempt_number_is_preserved(self):
        _, events, contexts = compatible_fixture()
        ctx = copy.deepcopy(contexts[events[0]["event_id"]]); ctx["attemptNumber"] = 2
        with self.assertRaisesRegex(ValueError, "attempt_number_conflict"):
            convert(events[0], ctx)

    def test_evidence_mode_cannot_be_promoted(self):
        _, events, _, rows = self.converted()
        row = copy.deepcopy(rows[0]); row["evidenceMode"] = "current_execution"
        with self.assertRaisesRegex(ValueError, "sidecar_evidence_conflict"):
            verify_pair(row, events[0])


if __name__ == "__main__":
    unittest.main()
