"""Execution v7 partial recovery with parallel groups; all model replies are synthetic.

One failed round is recovered twice through the real controller worker, with
groupWorkers 1 and 8. Both runs must produce the same candidate, evidence and
recovery receipt, pay for exactly the same never-dispatched calls, reuse the
same returned calls, replay every fully returned group before any paid call,
and keep paid calls inside the job root's shared API slots.
"""
from contextlib import contextmanager
import copy
import json
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch

from scripts import canonical_durable_jobs as durable
from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.compute import api_concurrency
from tongxing_production.orchestration import jobs
from tongxing_production.text import controller as subject
from tongxing_production.text import models
from tests import test_canonical_layer2_controller_payload_cache as cache_fixtures
from tests import test_layer2_large_fan_in as fan_in

GROUPS = 12
SIDECARLESS = {2, 4}          # both roles returned, the group's success sidecar is missing
TRANSLATOR_ONLY = {6}         # the reviewer was never dispatched
NEVER_DISPATCHED = {7, 8, 10, 11, 12}  # group 9 returned after them (a parallel predecessor)


class _Calls:
    """A thread-safe synthetic API transport with the controller's reuse hooks."""

    def __init__(self, answer, *, delay=0.0, forbidden=False):
        self.answer = answer
        self.delay = delay
        self.forbidden = forbidden
        self.lock = threading.Lock()
        self.events = []
        self.paid = []
        self.in_flight = 0
        self.max_in_flight = 0

    def caller(self):
        def call(key, payload):
            if self.forbidden:
                raise AssertionError("prior round must not dispatch here")
            data = json.loads(payload["messages"][1]["content"])
            with self.lock:
                self.in_flight += 1
                self.max_in_flight = max(self.max_in_flight, self.in_flight)
                self.events.append(("paid", data["translationGroupId"]))
                self.paid.append(models.policy_tools.canonical_sha256(payload))
            try:
                time.sleep(self.delay)
                return self.answer(key, payload)
            finally:
                with self.lock:
                    self.in_flight -= 1

        def provenance(_key, payload, response, *_root, policy_migration=None):
            return {"fixturePayload": models.policy_tools.canonical_sha256(payload),
                    "fixtureResponseId": response["id"]}

        def record_reuse(_key, payload, response, given):
            if given != provenance(_key, payload, response):
                raise AssertionError("paid provenance changed")
            group = json.loads(payload["messages"][1]["content"])["translationGroupId"]
            with self.lock:
                self.events.append(("reuse", group))

        call.execution_identity = dict(cache_fixtures.API_IDENTITY)
        call.verify_execution = lambda _key: None
        call.paid_response_provenance = provenance
        call.recover_returned_response = provenance
        call.validate_recovery_source = lambda *_: None
        call.record_reuse = record_reuse
        return call


class Layer2PartialRecoveryParallelTests(unittest.TestCase):
    def setUp(self):
        builder = fan_in.LargeLayer2FanInTests("test_65_group_worker_and_cache_only_recovery_preserve_every_dependency")
        self.addCleanup(builder.doCleanups)
        self.base, _, _, self.answer = builder.fixture(GROUPS)
        self.root = self.base.root
        self.prior = self.root / "failed-round"
        # The v7 configuration helpers of the payload-cache suite, on this fixture.
        self.helpers = cache_fixtures.CanonicalLayer2PayloadCacheTests(
            "test_v7_partial_round_binds_failed_job_round_budget_and_successor_command")
        self.helpers.base, self.helpers.root, self.helpers.prior = self.base, self.root, self.prior
        self.make_failed_round()
        self.helpers.enable_v7_partial_recovery()
        self.recovery_config = copy.deepcopy(self.base.config_data)

    def make_failed_round(self):
        config = subject.load_configuration(self.base.path)
        source, anchor, policy = subject._inputs(config, "zh-Hans", subject.package_view(config))
        models.run_accounted(source, anchor, policy, self.prior, "fixture-key",
                             _Calls(self.answer).caller(), None, config.lanes["zh-Hans"]["plugin"],
                             None, None, emit_payload_cache_success=True)
        (self.prior / "evidence.json").unlink()
        for index in range(1, GROUPS + 1):
            stem = f"group-{index:04d}"
            doomed = []
            if index in SIDECARLESS | TRANSLATOR_ONLY | NEVER_DISPATCHED:
                doomed.append(self.prior / f"{stem}-payload-cache-success.json")
            if index in TRANSLATOR_ONLY | NEVER_DISPATCHED:
                doomed += list(self.prior.glob(f"{stem}-sol*.json"))
            if index in NEVER_DISPATCHED:
                doomed += list(self.prior.glob(f"{stem}-astra*.json"))
            for path in doomed:
                path.unlink()

    def configure(self, name, workers):
        value = copy.deepcopy(self.recovery_config)
        value["layer2AutoRepair"]["groupWorkers"] = workers
        value["jobRoot"] = f"jobs-{name}"
        value["locales"]["zh-Hans"]["outputDirectory"] = f"outputs-{name}/zh-Hans"
        path = self.root / f"execution-{name}.json"
        path.write_text(json.dumps(value))
        return path

    @contextmanager
    def active(self, path):
        config = subject.load_configuration(path)
        ident = durable.identity(subject.package_view(config), config.run_id, "text.zh-Hans")
        key, code = jobs._digest(ident), "c" * 64
        command = subject._worker_command(config, "zh-Hans", key, code)
        request = {"schemaVersion": jobs.SCHEMA, "jobId": key, "identity": ident,
                   "command": command, "commandSha256": jobs._digest(command),
                   "timeoutSeconds": 21600.0, "livenessPolicy": subject.LIVENESS_POLICY}
        with jobs._lock(config.job_root, key) as (folder, _, held):
            self.assertTrue(held)
            folder.mkdir()
            jobs._persist(folder / "request.json", request)
            jobs._persist(folder / "state.json", {"schemaVersion": jobs.SCHEMA, "jobId": key,
                          "status": "running", "requestSha256": jobs._digest(request)})
            yield config, code, key

    def recover(self, name, workers, *, slots=api_concurrency.MAX_IN_FLIGHT_API_CALLS):
        path = self.configure(name, workers)
        calls = _Calls(self.answer, delay=0.05)
        with patch.object(subject, "code_identity", return_value="c" * 64), \
             patch.object(api_concurrency, "MAX_IN_FLIGHT_API_CALLS", slots), \
             self.active(path) as (config, code, key):
            self.assertEqual(config.auto_repair["groupWorkers"], workers)
            result = subject.execute(
                config.path, "zh-Hans", config.sha256, code, key,
                caller=calls.caller(), api_key="fixture-key",
                expected_payload_cache=config.payload_cache["zh-Hans"]["identity"],
                expected_partial_recovery=config.partial_recovery["zh-Hans"]["identity"])
        self.assertEqual(result["status"], "machine_review_pass_human_review_pending")
        output = self.root / f"outputs-{name}" / "zh-Hans"
        return result, calls, output

    def test_parallel_recovery_matches_serial_results_receipts_and_paid_calls(self):
        prior_files = {path.name: path.read_bytes() for path in self.prior.iterdir() if path.is_file()}
        serial, serial_calls, serial_out = self.recover("serial", 1)
        parallel, parallel_calls, parallel_out = self.recover("parallel", 8, slots=3)

        # Same candidate, evidence and per-group success receipts.
        self.assertEqual(parallel["candidateJsonSha256"], serial["candidateJsonSha256"])
        self.assertEqual((parallel_out / "candidate.json").read_bytes(),
                         (serial_out / "candidate.json").read_bytes())
        rounds = [out / "repair-rounds" / "round-001" for out in (serial_out, parallel_out)]
        self.assertEqual(*[(path / "evidence.json").read_bytes() for path in rounds])
        receipts = [{p.name: p.read_bytes() for p in path.glob("group-*-payload-cache-success.json")}
                    for path in rounds]
        self.assertEqual(len(receipts[0]), GROUPS)
        self.assertEqual(receipts[0], receipts[1])

        # The recovery receipt differs only in the successor job and configuration it names.
        serial_receipt, parallel_receipt = (
            jobs._read(out / "partial-round-recovery-receipt.json") for out in (serial_out, parallel_out))
        successor = {"successorJobId", "successorConfigurationSha256"}
        self.assertEqual({k: v for k, v in parallel_receipt.items() if k not in successor},
                         {k: v for k, v in serial_receipt.items() if k not in successor})
        self.assertFalse(parallel_receipt["humanApproval"])
        self.assertEqual(parallel["partialRecoveryReceiptSha256"], jobs._digest(parallel_receipt))

        # Exactly the never-dispatched roles are paid, once each, in both runs.
        expected_paid = 2 * len(NEVER_DISPATCHED) + len(TRANSLATOR_ONLY)
        self.assertEqual(len(serial_calls.paid), expected_paid)
        self.assertEqual(sorted(parallel_calls.paid), sorted(serial_calls.paid))
        self.assertEqual(len(set(parallel_calls.paid)), expected_paid)
        reused = [sorted(group for kind, group in calls.events if kind == "reuse")
                  for calls in (serial_calls, parallel_calls)]
        self.assertEqual(reused[0], reused[1])
        self.assertEqual(len(reused[0]), 2 * (GROUPS - len(NEVER_DISPATCHED)) - len(TRANSLATOR_ONLY))

        # Every fully returned group is replayed before the first paid call, in both runs.
        plan = [row["translationGroupId"] for row in
                json.loads((rounds[0] / "evidence.json").read_text())["groups"]]
        complete = {plan[index - 1] for index in range(1, GROUPS + 1)
                    if index not in TRANSLATOR_ONLY | NEVER_DISPATCHED}
        for calls in (serial_calls, parallel_calls):
            first_paid = next(n for n, (kind, _) in enumerate(calls.events) if kind == "paid")
            self.assertEqual({group for kind, group in calls.events[:first_paid] if kind == "reuse"} & complete,
                             complete)

        # Parallel groups really overlapped, and never beyond the shared API slots.
        self.assertEqual(serial_calls.max_in_flight, 1)
        self.assertGreater(parallel_calls.max_in_flight, 1)
        self.assertLessEqual(parallel_calls.max_in_flight, 3)

        # The failed round stays read-only.
        self.assertEqual({path.name: path.read_bytes() for path in self.prior.iterdir() if path.is_file()},
                         prior_files)

    def test_damaged_late_returned_call_stops_parallel_recovery_before_any_payment(self):
        # Group 6's translator returned but its reviewer never ran; earlier groups
        # 7-8 would pay first in source order. The preflight must refuse first.
        raw = self.prior / "group-0006-astra.raw.json"
        value = json.loads(raw.read_text())
        value["response"]["choices"][0]["message"]["content"] = json.dumps({"forged": True})
        raw.write_text(json.dumps(value))
        path = self.configure("damaged", 8)  # loading binds the round bytes as they are now
        calls = _Calls(self.answer)
        with patch.object(subject, "code_identity", return_value="c" * 64), self.active(path) as (config, code, key):
            with self.assertRaisesRegex(ValueError, "parsed result differs from raw response"):
                subject.execute(
                    config.path, "zh-Hans", config.sha256, code, key,
                    caller=calls.caller(), api_key="fixture-key",
                    expected_payload_cache=config.payload_cache["zh-Hans"]["identity"],
                    expected_partial_recovery=config.partial_recovery["zh-Hans"]["identity"])
        self.assertEqual(calls.paid, [])
        self.assertEqual(list((self.root / "outputs-damaged").rglob("*.started.json")), [])

    def test_v7_accepts_any_group_worker_count_and_v1_configurations_load_unchanged(self):
        for workers in (1, 8, api_concurrency.MAX_GROUP_WORKERS_PER_LOCALE):
            config = subject.load_configuration(self.configure(f"w{workers}", workers))
            self.assertEqual(config.auto_repair["groupWorkers"], workers)
            self.assertIn("zh-Hans", config.partial_recovery)
        with self.assertRaisesRegex(ValueError, "invalid_execution_configuration"):
            subject.load_configuration(self.configure("too-many", api_concurrency.MAX_GROUP_WORKERS_PER_LOCALE + 1))

    def test_a_paid_call_in_the_returned_group_phase_fails_before_its_marker(self):
        # Defence in depth: were a never-dispatched group ever classed as fully
        # returned, its first paid call stops the run with no started marker.
        preflight = models._require_partial_recovery_source
        misclassified = lambda *args: sorted(preflight(*args) + [7])
        path = self.configure("gate", 8)
        calls = _Calls(self.answer)
        with patch.object(models, "_require_partial_recovery_source", side_effect=misclassified), \
             patch.object(subject, "code_identity", return_value="c" * 64), self.active(path) as (config, code, key):
            with self.assertRaisesRegex(ValueError, "before its returned groups were verified"):
                subject.execute(
                    config.path, "zh-Hans", config.sha256, code, key,
                    caller=calls.caller(), api_key="fixture-key",
                    expected_payload_cache=config.payload_cache["zh-Hans"]["identity"],
                    expected_partial_recovery=config.partial_recovery["zh-Hans"]["identity"])
        self.assertEqual(calls.paid, [])
        self.assertEqual(list((self.root / "outputs-gate").rglob("*.started.json")), [])


class RecoveryOrderTests(unittest.TestCase):
    def test_returned_groups_run_first_and_merge_in_source_order(self):
        seen = []

        def run_groups(items):
            seen.append(([index for index, _ in items], models._RECOVERY_PAID_DISPATCH_CLOSED.get()))
            return [(index, None) for index, _ in items]

        merged = models._run_partial_recovery_groups(["a", "b", "c", "d", "e"], [2, 5], run_groups)
        self.assertEqual(seen, [([2, 5], True), ([1, 3, 4], False)])
        self.assertEqual([row for row, _ in merged], [1, 2, 3, 4, 5])
        self.assertFalse(models._RECOVERY_PAID_DISPATCH_CLOSED.get())


if __name__ == "__main__":
    unittest.main()
