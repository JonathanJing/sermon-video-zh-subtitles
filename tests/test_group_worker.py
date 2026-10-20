"""Per-group worker writes the T, R and P records the merge assembles (DEV-GRP-002)."""
from __future__ import annotations

import fcntl
import json
from pathlib import Path
import tempfile
import unittest

from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tests import test_produce_target_language_candidate as candidate_fixture
from tests.test_layer2_payload_cache_reuse import _Caller
from tongxing_production.orchestration import group_assembly
from tongxing_production.orchestration import group_pipeline
from tongxing_production.orchestration import group_records as records
from tongxing_production.orchestration import group_worker
from tongxing_production.text import models


class GroupWorkerTests(unittest.TestCase):
    def setUp(self):
        fixture = candidate_fixture.ProduceTargetLanguageCandidateTests(
            "test_compiles_valid_candidate_without_human_approval")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        # The runner names groups by the plan; the fixture uses short IDs.
        plan = models.group_plan(fixture.request, fixture.anchor)
        for row, group in zip(fixture.evidence["groups"], plan):
            row["translationGroupId"] = group["translationGroupId"]
        self.plan = plan
        self.config = {
            "source": fixture.source, "anchor": fixture.anchor, "policy": fixture.policy,
            "locale": fixture.request["targetLocale"],
            "plugin": fixture.plugin_path, "records": self.root / "records",
            "work": self.root / "work", "merge": self.root / "merge",
        }
        self.groups = {tuple(row["sourceUnitIds"]): row for row in fixture.evidence["groups"]}

    def run_group(self, group, caller):
        return group_worker.run_group(
            self.config, group, source=self.fixture.source, anchor=self.fixture.anchor,
            policy=self.fixture.policy, request=self.fixture.request, caller=caller, api_key="fixture-key")

    def records_for(self, group_id):
        store = records.RecordStore(self.root / "records")
        return {stage: store.records(self.config["locale"], group_id, stage)
                for stage in group_worker.PAID_STAGES}

    def test_runs_one_group_and_writes_terminal_records(self):
        caller = _Caller(self)
        outcome = self.run_group(self.plan[0], caller)
        self.assertEqual(outcome["group"], self.plan[0]["translationGroupId"])
        self.assertTrue(outcome["dispatched"])
        found = self.records_for(self.plan[0]["translationGroupId"])
        self.assertEqual([len(found[stage]) for stage in group_worker.PAID_STAGES], [1, 1, 1])
        for stage in group_worker.PAID_STAGES:
            record = found[stage][0]
            self.assertEqual(record["verdict"]["status"], "pass")
            self.assertEqual(record["provenance"]["derivation"], group_worker.DERIVATION)
            self.assertFalse(record["releaseEligible"])
            self.assertFalse(record["humanApproval"])
        self.assertEqual(records.RecordStore(self.root / "records").records(
            self.config["locale"], self.plan[1]["translationGroupId"], "T"), [])
        self.assertEqual(len(caller.calls), 2)

    def test_every_group_assembles_into_the_whole_path_candidate(self):
        caller = _Caller(self)
        for group in self.plan:
            self.run_group(group, caller)
        store = records.RecordStore(self.root / "records")
        payloads = group_assembly.PayloadStore(self.root / "records")
        assembled = group_assembly.assemble(
            self.fixture.source, self.fixture.anchor, self.fixture.policy, self.fixture.request, None,
            self.fixture.plugin_path, store, payloads)
        whole = self.fixture.admit(self.fixture.receipt())

        def without_response_ids(candidate):
            """The fixture and this worker use different synthetic provider response IDs."""
            value = json.loads(json.dumps(candidate))
            for row in value["groups"]:
                row.pop("translatorRequestId", None)
                row.pop("reviewerRequestId", None)
            generation = value.get("generation") or {}
            for role in generation.values():
                role.pop("requestIds", None)
            return value

        self.assertEqual(without_response_ids(assembled["candidate"]), without_response_ids(whole))
        self.assertEqual([row["translationGroupId"] for row in assembled["candidate"]["groups"]],
                         [group["translationGroupId"] for group in self.plan])

    def test_second_worker_on_a_locked_group_refuses_before_any_call(self):
        store = records.RecordStore(self.root / "records")
        lock = store.root / "_locks" / self.config["locale"]
        lock.mkdir(parents=True)
        handle = open(lock / f"{self.plan[0]['translationGroupId']}.lock", "a+")
        self.addCleanup(handle.close)
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        caller = _Caller(self, forbidden=True)
        with self.assertRaises(group_worker.GroupBusy):
            self.run_group(self.plan[0], caller)
        self.assertEqual(caller.calls, [])

    def test_semantic_review_failure_writes_terminal_fail_records(self):
        caller = _Caller(self, semantic_fail=True)
        with self.assertRaises(group_worker.GroupWorkerError) as caught:
            self.run_group(self.plan[0], caller)
        self.assertEqual(caught.exception.kind, "failed")
        found = self.records_for(self.plan[0]["translationGroupId"])
        self.assertEqual([len(found[stage]) for stage in group_worker.PAID_STAGES][:2], [1, 1])
        self.assertEqual(found["R"][0]["verdict"]["status"], "fail")
        self.assertEqual(found["P"], [])

    def test_transport_error_is_unknown_and_writes_no_record(self):
        class _Broken:
            billing = "api"
            execution_identity = {"schemaVersion": "test-layer2-transport-v1",
                                  "backend": "openai_api", "runtime": "runtime-a"}

            def verify_execution(self, _api_key):
                return None

            def __call__(self, api_key, payload):
                raise TimeoutError("socket closed after send")

        with self.assertRaises(group_worker.GroupWorkerError) as caught:
            self.run_group(self.plan[0], _Broken())
        self.assertEqual(caught.exception.kind, "unknown")
        found = self.records_for(self.plan[0]["translationGroupId"])
        self.assertEqual([len(found[stage]) for stage in group_worker.PAID_STAGES], [0, 0, 0])


if __name__ == "__main__":
    unittest.main()
