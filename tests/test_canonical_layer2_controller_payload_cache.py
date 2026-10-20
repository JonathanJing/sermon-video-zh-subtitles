"""Canonical Layer 2 v6 payload-cache wiring; all model replies are synthetic."""
from contextlib import contextmanager
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import canonical_durable_jobs as durable
from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.text import controller as subject
from tongxing_production.review import review_budget
from tongxing_production.orchestration import jobs
from tests import test_canonical_layer2_controller as controller_fixtures


API_IDENTITY = {
    "schemaVersion": "openai-layer2-budget-transport-identity-v3",
    "backend": "openai_api",
    "runtimeIdentity": {"route": "fixture", "credentialSha256": "a" * 64},
}


class CanonicalLayer2PayloadCacheTests(unittest.TestCase):
    def setUp(self):
        self.base = controller_fixtures.CanonicalLayer2ControllerTests(
            "test_default_shadow_is_read_only_and_never_loads_credentials_or_dispatches")
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.root = self.base.root
        self.prior = self.root / "prior-success"

    def api_caller(self, *, forbidden=False):
        owner = self

        def call(key, payload):
            if forbidden:
                raise AssertionError("exact v6 cache hit must not dispatch")
            return owner.base.fake_call(key, payload)

        call.execution_identity = dict(API_IDENTITY)
        call.verifications = 0

        def verify(_key):
            call.verifications += 1

        call.verify_execution = verify
        return call

    def make_prior(self):
        config = subject.load_configuration(self.base.path)
        view = subject.package_view(config)
        source, anchor, policy = subject._inputs(config, "zh-Hans", view)
        caller = self.api_caller()
        subject.models.run_accounted(
            source, anchor, policy, self.prior, "fixture-key", caller, None,
            config.lanes["zh-Hans"]["plugin"], None, None,
            emit_payload_cache_success=True)
        self.assertEqual(len(list(self.prior.glob("*-payload-cache-success.json"))), 2)
        self.base.calls.clear()

    def enable_v6(self):
        self.base.config_data.update({
            "schemaVersion": subject.PAYLOAD_CACHE_SCHEMA,
            "layer2AutoRepair": {
                "routingVersion": subject.auto_repair.ROUTING_VERSION,
                "groupWorkers": 1,
                "maxActiveLocales": 1,
            },
            "layer2PayloadCache": {
                "schemaVersion": subject.PAYLOAD_CACHE_CONFIG_SCHEMA,
                "emitSuccess": True,
                "priorSuccessRoots": {"zh-Hans": str(self.prior)},
            },
        })
        self.base.save_config()

    def enable_v7_partial_recovery(self):
        self.enable_v6()
        self.base.config_data["schemaVersion"] = subject.PARTIAL_RECOVERY_SCHEMA
        self.base.config_data["layer2AutoRepair"]["groupWorkers"] = 1
        failed_jobs = self.root / "failed-jobs"
        identity = {"schemaVersion": "fixture-failed-layer2-v1", "locale": "zh-Hans"}
        failed_job_id = jobs._digest(identity)
        command = ["python", "canonical_layer2_controller.py", "worker", "--config", "old.json",
                   "--locale", "zh-Hans", "--expected-job", failed_job_id]
        request = {"schemaVersion": jobs.SCHEMA, "jobId": failed_job_id,
                   "identity": identity, "command": command,
                   "commandSha256": jobs._digest(command)}
        folder = failed_jobs / failed_job_id
        folder.mkdir(parents=True)
        jobs._persist(folder / "request.json", request)
        jobs._persist(folder / "state.json", {"schemaVersion": jobs.SCHEMA,
            "jobId": failed_job_id, "status": "failed",
            "requestSha256": jobs._digest(request), "returnCode": 1})
        budget_root = self.root / "direct-budget"
        bounds = dict.fromkeys(review_budget.METRICS, 10_000)
        authority = {"approvalSha256": "a" * 64, "globalBounds": bounds,
                     "unitBounds": bounds, "limits": {"contentRevisions": 2,
                     "reviewAttemptsPerRevision": 2, "decisionProposals": 1}}
        store = review_budget.BudgetStore(budget_root, authority)
        chain = review_budget.chain_identity({
            "sourceIdentitySha256": "1" * 64, "sourcePackageSha256": "2" * 64,
            "anchorSha256": "3" * 64, "policySha256": "4" * 64,
            "rubricSha256": "5" * 64, "targetLocale": "zh-Hans",
            "workUnitId": "l2.zh-Hans.call-" + "6" * 64})
        reserved = store.reserve(chain, operation_id="model." + "6" * 64,
            kind="initial_generation", revision_id="initial", revision_number=1,
            input_sha256="6" * 64, bounds=dict.fromkeys(review_budget.METRICS, 1))
        store.mark_request(reserved["reservationId"])
        store.record_result(reserved["reservationId"], {
            "executionStatus": "succeeded", "contentStatus": "not_assessed",
            "receiptSha256": "7" * 64, "usage": dict.fromkeys(review_budget.METRICS, 1)})
        self.base.config_data["layer2PartialRecovery"] = {
            "schemaVersion": subject.PARTIAL_RECOVERY_CONFIG_SCHEMA,
            "locales": {"zh-Hans": {"failedJobRoot": str(failed_jobs),
                "failedJobId": failed_job_id, "roundRoot": str(self.prior),
                "directPaidBudgetRoot": str(budget_root)}}}
        self.base.save_config()
        return failed_jobs, failed_job_id, budget_root

    @contextmanager
    def active(self):
        config = subject.load_configuration(self.base.path)
        view = subject.package_view(config)
        ident = durable.identity(view, config.run_id, "text.zh-Hans")
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
            yield config, code, key, command

    def test_v6_snapshot_enters_configuration_package_and_durable_identity(self):
        self.make_prior()
        old = subject.load_configuration(self.base.path)
        old_identity = durable.identity(subject.package_view(old), old.run_id, "text.zh-Hans")
        self.enable_v6()
        config = subject.load_configuration(self.base.path)
        view = subject.package_view(config)
        cache = config.payload_cache["zh-Hans"]
        self.assertEqual(cache["root"], self.prior.resolve())
        self.assertEqual(cache["snapshot"]["successfulGroups"], 2)
        self.assertEqual(view["packageIdentities"]["payloadCache.zh-Hans"], cache["identity"])
        current = durable.identity(view, config.run_id, "text.zh-Hans")
        self.assertNotEqual(current["inputIdentitySha256"], old_identity["inputIdentitySha256"])
        command = subject._worker_command(config, "zh-Hans", jobs._digest(current), "c" * 64)
        self.assertEqual(subject._command_option(command, "--expected-payload-cache"), cache["identity"])
        self.assertTrue(str(cache["root"]).startswith(str(self.root.resolve())))

    def test_v7_partial_round_binds_failed_job_round_budget_and_successor_command(self):
        self.make_prior()
        failed_jobs, failed_job_id, budget_root = self.enable_v7_partial_recovery()
        config = subject.load_configuration(self.base.path)
        recovery = config.partial_recovery["zh-Hans"]
        self.assertEqual(recovery["failedJobId"], failed_job_id)
        self.assertEqual(recovery["budgetRoot"], budget_root.resolve())
        self.assertGreater(recovery["snapshot"]["directBudgetReservations"], 0)
        view = subject.package_view(config)
        self.assertEqual(view["packageIdentities"]["partialRecovery.zh-Hans"],
                         recovery["identity"])
        successor = jobs._digest(durable.identity(view, config.run_id, "text.zh-Hans"))
        command = subject._worker_command(config, "zh-Hans", successor, "c" * 64)
        self.assertEqual(subject._command_option(command, "--expected-partial-recovery"),
                         recovery["identity"])
        old_state = jobs._read(failed_jobs / failed_job_id / "state.json")
        self.assertEqual(old_state["status"], "failed")

    def test_v7_partial_round_rejects_nonfailed_or_unknown_predecessor(self):
        self.make_prior()
        failed_jobs, failed_job_id, _ = self.enable_v7_partial_recovery()
        state_path = failed_jobs / failed_job_id / "state.json"
        state = jobs._read(state_path)
        state["status"] = "running"
        jobs._persist(state_path, state)
        with self.assertRaisesRegex(ValueError, "requires_failed_bound_job"):
            subject.load_configuration(self.base.path)
        state["status"] = "failed"
        jobs._persist(state_path, state)
        marker = self.prior / "group-9999-astra.started.json"
        marker.write_text(json.dumps({"status": "unknown"}))
        with self.assertRaisesRegex(ValueError, "unknown_paid_outcome"):
            subject.load_configuration(self.base.path)

    def test_v7_partial_round_success_writes_bound_recovery_receipt_and_keeps_old_failed(self):
        self.make_prior()
        failed_jobs, failed_job_id, _ = self.enable_v7_partial_recovery()
        caller = self.api_caller(forbidden=True)
        caller.validate_recovery_source = lambda *_: None
        with patch.object(subject, "code_identity", return_value="c" * 64), \
             self.active() as (config, code, key, _):
            recovery = config.partial_recovery["zh-Hans"]
            result = subject.execute(
                config.path, "zh-Hans", config.sha256, code, key,
                caller=caller, api_key="fixture-key",
                expected_payload_cache=config.payload_cache["zh-Hans"]["identity"],
                expected_partial_recovery=recovery["identity"])
        self.assertEqual(result["status"], "machine_review_pass_human_review_pending")
        receipt = jobs._read(self.base.output / "partial-round-recovery-receipt.json")
        self.assertEqual(receipt["schemaVersion"], subject.PARTIAL_RECOVERY_RECEIPT_SCHEMA)
        self.assertEqual(receipt["predecessorFailedJobId"], failed_job_id)
        self.assertEqual(receipt["successorJobId"], key)
        self.assertFalse(receipt["humanApproval"])
        self.assertEqual(jobs._read(failed_jobs / failed_job_id / "state.json")["status"], "failed")

    def test_prior_bytes_change_after_admission_blocks_before_model(self):
        self.make_prior()
        self.enable_v6()
        with patch.object(subject, "code_identity", return_value="c" * 64), self.active() as (config, code, key, _):
            receipt = next(self.prior.glob("*-payload-cache-success.json"))
            value = json.loads(receipt.read_text())
            value["humanApproval"] = True
            receipt.write_text(json.dumps(value))
            caller = self.api_caller(forbidden=True)
            with self.assertRaisesRegex(ValueError, "worker_configuration_or_code_changed"):
                subject.execute(config.path, "zh-Hans", config.sha256, code, key,
                                caller=caller, api_key="fixture-key",
                                expected_payload_cache=config.payload_cache["zh-Hans"]["identity"])
        self.assertEqual(caller.verifications, 0)

    def test_unknown_prior_outcome_and_overlapping_root_fail_before_dispatch(self):
        self.make_prior()
        (self.prior / "group-9999-astra.started.json").write_text(json.dumps({"status": "unknown"}))
        self.enable_v6()
        with self.assertRaisesRegex(ValueError, "payload_cache_unknown_paid_outcome"):
            subject.load_configuration(self.base.path)
        (self.prior / "group-9999-astra.started.json").unlink()
        self.base.config_data["locales"]["zh-Hans"]["outputDirectory"] = "prior-success/new-output"
        self.base.save_config()
        with self.assertRaisesRegex(ValueError, "execution_paths_overlap"):
            subject.load_configuration(self.base.path)

    def test_prior_root_cannot_contain_a_plugin_or_other_registered_input(self):
        self.make_prior()
        plugin = Path(self.base.config_data["locales"]["zh-Hans"]["plugin"])
        nested = self.prior / "registered-plugin.py"
        nested.write_bytes(plugin.read_bytes())
        self.enable_v6()
        self.base.config_data["locales"]["zh-Hans"]["plugin"] = str(nested)
        self.base.save_config()
        with self.assertRaisesRegex(ValueError, "execution_paths_overlap"):
            subject.load_configuration(self.base.path)

    def test_exact_v6_hit_runs_real_controller_path_without_provider_calls(self):
        self.make_prior()
        self.enable_v6()
        caller = self.api_caller(forbidden=True)
        with patch.object(subject, "code_identity", return_value="c" * 64), self.active() as (config, code, key, _):
            result = subject.execute(config.path, "zh-Hans", config.sha256, code, key,
                                     caller=caller, api_key="fixture-key",
                                     expected_payload_cache=config.payload_cache["zh-Hans"]["identity"])
        self.assertEqual(result["status"], "machine_review_pass_human_review_pending")
        self.assertEqual(self.base.calls, [])
        self.assertEqual(caller.verifications, 4)
        current = self.base.output / "repair-rounds" / "round-001"
        self.assertEqual(len(list(current.glob("*-payload-cache-success.json"))), 2)

    # Cache hits pass through without a per-hit binding recheck: drift is caught when
    # a group is read, before any paid dispatch, or at post_model_binding.
    def drifting_run(self, drift, *, at=3):
        """Run the worker on cache hits, calling ``drift`` at the ``at``-th model call."""
        caller = self.api_caller(forbidden=True)

        def verify(_key):
            caller.verifications += 1
            if caller.verifications == at:
                drift()

        caller.verify_execution = verify
        code = {"value": "c" * 64}
        with patch.object(subject, "code_identity", side_effect=lambda: code["value"]), \
                self.active() as (config, expected_code, key, _):
            self.drift_code = lambda: code.update(value="d" * 64)
            with self.assertRaises(ValueError) as raised:
                subject.execute(config.path, "zh-Hans", config.sha256, expected_code, key,
                                caller=caller, api_key="fixture-key",
                                expected_payload_cache=config.payload_cache["zh-Hans"]["identity"])
        self.assertEqual(self.base.calls, [])
        self.assertFalse((self.base.output / "candidate.json").exists())
        return str(raised.exception), caller.verifications, config

    @staticmethod
    def flip_last_digit(path):
        data = path.read_bytes()
        index = max(i for i, c in enumerate(data) if 48 <= c <= 57)
        path.write_bytes(data[:index] + (b"1" if data[index:index + 1] == b"0" else b"0") + data[index + 1:])

    def test_edit_of_an_unread_prior_group_fails_closed_when_that_group_is_read(self):
        self.make_prior()
        self.enable_v6()
        receipt = self.prior / "group-0002-payload-cache-success.json"
        error, verifications, _ = self.drifting_run(lambda: self.flip_last_digit(receipt), at=1)
        self.assertRegex(error, "Prior payload cache success identity changed|Prior payload cache files changed")
        self.assertLess(verifications, 4)

    def test_edit_of_a_consumed_prior_group_is_rejected_at_the_end_binding(self):
        self.make_prior()
        self.enable_v6()
        receipt = self.prior / "group-0001-payload-cache-success.json"
        error, verifications, _ = self.drifting_run(lambda: self.flip_last_digit(receipt))
        self.assertEqual(error, "worker_configuration_or_code_changed_during_models")
        self.assertEqual(verifications, 4)  # the hits after the edit ran; the end check refused

    def test_configuration_edit_during_hits_is_rejected_at_the_end_binding(self):
        self.make_prior()
        self.enable_v6()

        def drift():
            self.base.config_data["layer2PayloadCache"]["cacheRequired"] = False
            self.base.save_config()

        error, verifications, _ = self.drifting_run(drift, at=2)
        self.assertEqual(error, "worker_configuration_or_code_changed_during_models")
        self.assertEqual(verifications, 4)

    def test_code_edit_during_hits_is_rejected_at_the_end_binding(self):
        self.make_prior()
        self.enable_v6()
        error, verifications, _ = self.drifting_run(lambda: self.drift_code())
        self.assertEqual(error, "worker_configuration_or_code_changed_during_models")
        self.assertEqual(verifications, 4)

    def drift_during_candidate_write(self, drift):
        self.make_prior()
        self.enable_v6()
        caller = self.api_caller(forbidden=True)
        code = {"value": "c" * 64}
        self.drift_code = lambda: code.update(value="d" * 64)
        original = subject.models.save_new

        def save_new(path, value, *args, **kwargs):
            result = original(path, value, *args, **kwargs)
            if Path(path).name == "candidate.json":
                drift()
            return result

        with patch.object(subject, "code_identity", side_effect=lambda: code["value"]), \
                patch.object(subject.models, "save_new", side_effect=save_new), \
                self.active() as (config, expected_code, key, _):
            with self.assertRaises(ValueError) as raised:
                subject.execute(config.path, "zh-Hans", config.sha256, expected_code, key,
                                caller=caller, api_key="fixture-key",
                                expected_payload_cache=config.payload_cache["zh-Hans"]["identity"])
        self.assertEqual(self.base.calls, [])
        return str(raised.exception)

    def test_configuration_edit_during_candidate_writes_fails_final_validation(self):
        def drift():
            self.base.config_data["layer2PayloadCache"]["cacheRequired"] = False
            self.base.save_config()

        self.assertEqual(self.drift_during_candidate_write(drift),
                         "worker_configuration_or_code_changed_during_models")

    def test_code_edit_during_candidate_writes_fails_final_validation(self):
        self.assertEqual(self.drift_during_candidate_write(lambda: self.drift_code()),
                         "worker_configuration_or_code_changed_during_models")

    def test_paid_dispatch_after_drift_is_blocked_before_the_call(self):
        self.make_prior()
        for path in self.prior.glob("group-0002-*"):
            path.unlink()  # group 0002 is a cache miss and needs a paid call
        self.enable_v6()

        def drift():
            self.base.config_data["layer2PayloadCache"]["cacheRequired"] = False
            self.base.save_config()

        error, verifications, _ = self.drifting_run(drift, at=1)
        # The forbidden caller was never reached: bound_call's check refused first.
        self.assertEqual(error, "worker_configuration_or_code_changed_during_models")
        self.assertEqual(verifications, 3)

    def test_writes_under_a_stale_binding_bind_only_admitted_inputs_and_exact_paid_bytes(self):
        self.make_prior()
        self.enable_v6()

        def drift():
            self.base.config_data["layer2PayloadCache"]["cacheRequired"] = False
            self.base.save_config()

        self.drifting_run(drift, at=2)
        written = self.base.output / "repair-rounds" / "round-001"
        admitted = subject.models._request_cache_binding(jobs._read(written / "request.json"))
        for stem in ("group-0001", "group-0002"):
            receipt = jobs._read(written / f"{stem}-payload-cache-success.json")
            prior = jobs._read(self.prior / f"{stem}-payload-cache-success.json")
            # Bound to the inputs admitted in memory, carrying the prior's exact paid responses.
            self.assertEqual(receipt["requestBinding"], admitted)
            self.assertFalse(receipt["humanApproval"])
            for role in ("translator", "reviewer"):
                self.assertEqual(receipt["roles"][role]["rawSha256"], prior["roles"][role]["rawSha256"])
                self.assertEqual(receipt["roles"][role]["payloadSha256"], prior["roles"][role]["payloadSha256"])
            # A later run on any other source, anchor or policy refuses these receipts.
            group = {"translationGroupId": receipt["translationGroupId"], "sourceUnitIds": receipt["sourceUnitIds"]}
            request = jobs._read(written / "request.json")
            for key in ("englishSourcePackageJsonSha256", "anchorManifestSha256", "translationPolicySha256"):
                changed = {**request, key: "0" * 64} if key in request else None
                if changed is None:
                    continue
                with self.subTest(stem=stem, key=key), self.assertRaisesRegex(ValueError, "identity changed"):
                    subject.models._successful_payload_cache(
                        written, stem, "translator", receipt["roles"]["translator"]["payloadSha256"],
                        changed, group)

    def test_auto_repair_uses_prior_only_on_fresh_round_and_always_emits(self):
        self.make_prior()
        self.enable_v6()
        self.base.config_data["layer2PayloadCache"]["cacheRequired"] = True
        self.base.save_config()
        config = subject.load_configuration(self.base.path)
        lane = config.lanes["zh-Hans"]
        view = subject.package_view(config)
        source, anchor, policy = subject._inputs(config, "zh-Hans", view)
        calls = []

        def run_accounted(*args, **kwargs):
            calls.append(kwargs)
            return {"groups": []}

        final = lane["output"] / "repair-rounds" / "round-002"
        final.mkdir(parents=True)
        (final / "evidence.json").write_text(json.dumps({"groups": []}))

        def drive(_request, _total, run_round, out_root, _ledger_root, **_kwargs):
            run_round(Path(out_root) / "round-001", None, None, object())
            run_round(final, Path(out_root) / "round-001", {"groups": []}, object())
            evidence = json.loads((final / "evidence.json").read_text())
            return {"status": "all_groups_passed", "finalRunDirectory": str(final),
                    "evidenceSha256": subject.auto_repair.json_sha256(evidence)}

        with patch.object(subject.models, "run_accounted", side_effect=run_accounted), \
             patch.object(subject.auto_repair, "drive", side_effect=drive):
            subject._run_auto_repair(config, lane, source, anchor, policy, "fixture-key", lambda *_: None,
                                     lambda *_: None, "span", [])
        self.assertEqual(calls[0]["payload_cache_from"], self.prior.resolve())
        self.assertIsNone(calls[1]["payload_cache_from"])
        self.assertTrue(all(row["emit_payload_cache_success"] for row in calls))
        self.assertTrue(calls[0]["payload_cache_required"])
        self.assertFalse(calls[1]["payload_cache_required"])

    def test_cache_required_is_bound_and_forwarded_only_for_fresh_round(self):
        self.make_prior()
        self.enable_v6()
        self.base.config_data["layer2PayloadCache"]["cacheRequired"] = True
        self.base.save_config()
        config = subject.load_configuration(self.base.path)
        self.assertTrue(config.payload_cache["zh-Hans"]["required"])
        identity = config.payload_cache["zh-Hans"]["identity"]
        self.base.config_data["layer2PayloadCache"]["cacheRequired"] = False
        self.base.save_config()
        optional = subject.load_configuration(self.base.path)
        self.assertNotEqual(identity, optional.payload_cache["zh-Hans"]["identity"])

        self.base.config_data["layer2PayloadCache"].update(cacheRequired=True, priorSuccessRoots={})
        self.base.save_config()
        with self.assertRaisesRegex(ValueError, "required_payload_cache_needs_prior_root_per_locale"):
            subject.load_configuration(self.base.path)

    def test_v6_is_openai_only_and_old_schema_rejects_new_field(self):
        self.make_prior()
        self.enable_v6()
        with patch.object(subject.models, "production_backend", return_value="claude_cli_opus"):
            with self.assertRaisesRegex(ValueError, "payload_cache_requires_openai_api"):
                subject.load_configuration(self.base.path)
        self.base.config_data["schemaVersion"] = subject.AUTO_REPAIR_SCHEMA
        self.base.save_config()
        with self.assertRaisesRegex(ValueError, "invalid_execution_configuration"):
            subject.load_configuration(self.base.path)


if __name__ == "__main__":
    unittest.main()
