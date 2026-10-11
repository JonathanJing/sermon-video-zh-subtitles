"""Auto repair inside the canonical controller worker; all model replies are synthetic."""
import copy
import json
import unittest
from unittest.mock import patch

from scripts import canonical_layer2_controller as subject
from scripts import layer2_auto_repair as auto_repair
from scripts import sermon_workflow_jobs as jobs
from tests import test_canonical_layer2_controller as controller_tests

BINDING = {"routingVersion": auto_repair.ROUTING_VERSION, "groupWorkers": 2, "maxActiveLocales": 3}
API_IDENTITY = {"schemaVersion": "openai-layer2-budget-transport-identity-v1", "backend": "openai_api",
                "route": "dev", "budgetAuthorizationSha256": "b" * 64}


class ControllerAutoRepairTests(unittest.TestCase):
    def setUp(self):
        self.base = controller_tests.CanonicalLayer2ControllerTests(
            "test_default_shadow_is_read_only_and_never_loads_credentials_or_dispatches")
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.base.config_data["schemaVersion"] = subject.AUTO_REPAIR_SCHEMA
        self.base.config_data["layer2AutoRepair"] = dict(BINDING)
        self.base.save_config()
        self.calls = []
        self.fail_first_review = set()

    def caller(self, key, payload):
        """Answer by source units; the listed groups fail their first review."""
        self.calls.append(payload)
        data = json.loads(payload["messages"][1]["content"])
        group = next(row for row in self.base.fixture.fixture.evidence["groups"]
                     if row["sourceUnitIds"] == data["sourceUnitIds"])
        fields = ["translationGroupId", "sourceUnitIds", "targetUtterances", "coverage"]
        if payload["reasoning_effort"] == "medium":
            fields.append("semanticReview")
        answer = {name: copy.deepcopy(group[name]) for name in fields}
        answer["translationGroupId"] = data["translationGroupId"]
        if payload["reasoning_effort"] == "medium" and "partialRepair" not in data \
                and data["translationGroupId"] in self.fail_first_review:
            answer["semanticReview"]["status"] = "fail"
            answer["semanticReview"]["checks"]["completeMeaning"] = "fail"
            answer["semanticReview"]["issues"] = ["Dropped the second clause"]
        return {"id": "fixture-response-" + str(len(self.calls)), "model": payload["model"],
                "usage": {"prompt_tokens": 60, "completion_tokens": 40},
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(answer)}}]}

    def run_worker(self, caller):
        # These two-group fixtures exercise controller/repair integration. Give
        # their repair pairs room under synthetic token bounds; production cap
        # enforcement has dedicated loop tests.
        with patch.object(auto_repair, 'SPEND_FRACTION', 1), \
                patch.object(auto_repair, '_repair_token_bound', return_value=100, create=True), \
                self.base.active() as (config, code, key, _):
            return subject.execute(self.base.path, "zh-Hans", config.sha256, code, key,
                                   caller=caller, api_key="fixture-key"), config

    def group_ids(self):
        config = subject.load_configuration(self.base.path)
        source, anchor, policy = subject._inputs(config, "zh-Hans", subject.snapshot(config))
        request = subject.producer.prepare_request(source, anchor, policy)
        return [row["translationGroupId"] for row in subject.models.group_plan(request, anchor)]

    def test_configuration_binds_routing_workers_and_locale_capacity(self):
        config = subject.load_configuration(self.base.path)
        self.assertEqual(config.auto_repair, BINDING)
        self.assertEqual(subject._locale_capacity(config), 3)
        for bad in ({**BINDING, "routingVersion": "other"}, {**BINDING, "groupWorkers": 17},
                    {**BINDING, "groupWorkers": 0}, {**BINDING, "maxActiveLocales": 4},
                    {**BINDING, "sourceMeaningNotes": 7}, {**BINDING, "sourceMeaningNotes": ""},
                    {"routingVersion": auto_repair.ROUTING_VERSION}):
            self.base.config_data["layer2AutoRepair"] = bad
            self.base.save_config()
            with self.assertRaisesRegex(ValueError, "invalid_execution_configuration"):
                subject.load_configuration(self.base.path)
        # The optional Layer 1 meaning notes resolve beside the configuration and count as an input.
        self.base.config_data["layer2AutoRepair"] = {**BINDING, "sourceMeaningNotes": "notes/meaning-notes.json"}
        self.base.save_config()
        config = subject.load_configuration(self.base.path)
        self.assertEqual(config.auto_repair["sourceMeaningNotes"],
                         str(subject._path(self.base.path.parent, "notes/meaning-notes.json")))
        self.base.config_data["schemaVersion"] = subject.SCHEMA
        self.base.config_data["layer2AutoRepair"] = dict(BINDING)
        self.base.save_config()
        with self.assertRaisesRegex(ValueError, "invalid_execution_configuration"):
            subject.load_configuration(self.base.path)

    def test_groups_run_concurrently_in_the_worker(self):
        import threading
        import time
        active, peak, lock = [0], [0], threading.Lock()

        def slow(key, payload):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.05)
            try:
                return self.caller(key, payload)
            finally:
                with lock:
                    active[0] -= 1
        result, _ = self.run_worker(slow)
        self.assertEqual(result["status"], "machine_review_pass_human_review_pending")
        self.assertEqual(peak[0], 2)

    def test_failed_job_with_unknown_nested_call_blocks_other_locales(self):
        controller = subject.Controller(self.base.path)
        controller.config.lanes['es'] = {'output': self.base.root / 'outputs' / 'es'}
        round_output = self.base.output / 'repair-rounds' / 'round-002'
        round_output.mkdir(parents=True)
        marker = round_output / 'group-0001-sol.started.json'
        marker.write_text('{}')
        view = {'durableJobInspection': {'jobs': [
            {'workUnitId': 'text.zh-Hans', 'status': 'failed'}]},
            'nodes': {'text.es': {'status': 'ready'}}}
        self.assertTrue(controller._capacity_full(view))
        self.assertIsNone(controller._choose(view, requested_locale='es'))

    def test_failed_job_with_confirmed_raw_or_cache_releases_capacity(self):
        controller = subject.Controller(self.base.path)
        controller.config.lanes['es'] = {'output': self.base.root / 'outputs' / 'es'}
        round_output = self.base.output / 'repair-rounds' / 'round-002'
        round_output.mkdir(parents=True)
        (round_output / 'group-0001-sol.started.json').write_text('{}')
        view = {'durableJobInspection': {'jobs': [
            {'workUnitId': 'text.zh-Hans', 'status': 'failed'}]},
            'nodes': {'text.es': {'status': 'ready'}}}
        for name in ('group-0001-sol.raw.json', 'group-0001-sol.json'):
            with self.subTest(response=name):
                response = round_output / name
                response.write_text('{}')
                self.assertFalse(controller._capacity_full(view))
                self.assertEqual(controller._choose(view, requested_locale='es'), 'es')
                response.unlink()

    def test_failed_group_is_repaired_inside_the_job_under_the_api_transport(self):
        failed = self.group_ids()[1]
        self.fail_first_review = {failed}

        def api_caller(key, payload):
            return self.caller(key, payload)
        api_caller.execution_identity = dict(API_IDENTITY)
        result, config = self.run_worker(api_caller)
        self.assertEqual(result["status"], "machine_review_pass_human_review_pending")
        self.assertFalse(result["releaseEligible"])
        self.assertEqual(len(self.calls), 6)  # 2 groups x 2 roles, then 1 repaired group x 2
        repaired = [json.loads(p["messages"][1]["content"]) for p in self.calls[4:]]
        self.assertEqual({row["translationGroupId"] for row in repaired}, {failed})
        candidate = json.loads(self.base.output.joinpath("candidate.json").read_text())
        self.assertEqual(result["candidateJsonSha256"], jobs._digest(candidate))
        rounds = self.base.output / "repair-rounds"
        receipt = json.loads((rounds / "auto-repair-receipt-002.json").read_text())
        self.assertEqual(receipt["status"], "all_groups_passed")
        self.assertFalse(receipt["humanApproval"])
        self.assertEqual(receipt["releaseAuthority"], "none")
        self.assertEqual(receipt["ledgerRoot"], str(subject.repair_ledger_root(config).resolve()))
        self.assertTrue((rounds / "round-002" / "evidence.json").is_file())
        self.assertFalse((self.base.output / "evidence.json").exists())

    def test_stopped_loop_fails_the_job_and_writes_no_candidate(self):
        self.fail_first_review = set(self.group_ids())

        def always_fails(key, payload):
            response = self.caller(key, payload)
            if payload["reasoning_effort"] == "medium":
                answer = json.loads(response["choices"][0]["message"]["content"])
                answer["semanticReview"]["status"] = "fail"
                answer["semanticReview"]["checks"]["completeMeaning"] = "fail"
                answer["semanticReview"]["issues"] = ["Dropped the second clause"]
                response["choices"][0]["message"]["content"] = json.dumps(answer)
            return response
        with self.assertRaisesRegex(ValueError, "layer2_auto_repair_stopped"):
            self.run_worker(always_fails)
        self.assertFalse((self.base.output / "candidate.json").exists())
        receipts = sorted((self.base.output / "repair-rounds").glob("auto-repair-receipt-*.json"))
        receipt = json.loads(receipts[-1].read_text())
        self.assertEqual(receipt["status"], "repair_stopped")
        self.assertEqual({row["reasonCode"] for row in receipt["stoppedGroups"]},
                         {"repeated_failure_without_progress"})

    def test_meaning_notes_reopen_a_failed_job_under_a_new_identity(self):
        failed = self.group_ids()[1]
        config = subject.load_configuration(self.base.path)
        source, anchor, policy = subject._inputs(config, "zh-Hans", subject.snapshot(config))
        request = subject.producer.prepare_request(source, anchor, policy)
        units = next(row["sourceUnitIds"] for row in subject.models.group_plan(request, anchor)
                     if row["translationGroupId"] == failed)
        marker = "Keep the frozen wording NOTE7731"
        notes = {units[0]: {"decision": "transcript_confirmed", "frozenTextSha256": "0" * 64,
                            "decidedBy": "test", "meaningNote": marker}}

        def reviewer(key, payload):
            """The failed group's attribution fails every review until a repair carries the meaning note."""
            response = self.caller(key, payload)
            data = json.loads(payload["messages"][1]["content"])
            if payload["reasoning_effort"] == "medium" and data["translationGroupId"] == failed \
                    and marker not in payload["messages"][1]["content"]:
                answer = json.loads(response["choices"][0]["message"]["content"])
                answer["semanticReview"]["status"] = "fail"
                answer["semanticReview"]["checks"]["quotationAttribution"] = "fail"
                answer["semanticReview"]["issues"] = ["Attributed to the speaker, not the verse"]
                response["choices"][0]["message"]["content"] = json.dumps(answer)
            return response
        with self.assertRaisesRegex(ValueError, "layer2_auto_repair_stopped"):
            self.run_worker(reviewer)
        first = jobs._digest(subject.durable.identity(subject.package_view(config), config.run_id, "text.zh-Hans"))
        folder = config.job_root / first
        jobs._persist(folder / "state.json", dict(jobs._read(folder / "state.json"), status="failed"))
        before = {path.name: path.read_bytes() for path in folder.iterdir() if path.is_file()}
        view = subject.snapshot(config)
        self.assertEqual(view["nodes"]["text.zh-Hans"]["reasonCode"], "failed_durable_job")
        with self.assertRaisesRegex(ValueError, "reopen_requires_source_meaning_notes"):
            subject.reopen_repair(self.base.path, "zh-Hans", view["stateRevision"])
        # The notes join the run's execution configuration and become a Layer 1 input of the text job.
        notes_path = self.base.root / "notes" / "meaning-notes.json"
        notes_path.parent.mkdir()
        notes_path.write_text(json.dumps({"units": sorted(notes)}), encoding="utf-8")
        self.base.config_data["layer2AutoRepair"] = {**BINDING, "sourceMeaningNotes": "notes/meaning-notes.json"}
        self.base.save_config()
        with patch.object(subject.source_meaning, "load_meaning_notes", return_value=notes) as loaded:
            config = subject.load_configuration(self.base.path)
            view = subject.snapshot(config)
            node = view["nodes"]["text.zh-Hans"]
            self.assertEqual((node["status"], node["reasonCode"]),
                             ("reconciliation_required", "unknown_or_changed_identity_job"))
            with self.assertRaisesRegex(ValueError, "stale_reopen_revision"):
                subject.reopen_repair(self.base.path, "zh-Hans", "f" * 64)
            result = subject.reopen_repair(self.base.path, "zh-Hans", view["stateRevision"])
            self.assertEqual((result["status"], result["jobId"], result["reopenedGroups"], result["modelCalls"]),
                             ("reopened", first, [failed], 0))
            self.assertEqual(loaded.call_args.kwargs, {"source": source, "anchor": anchor})
            following = subject.durable.identity(subject.package_view(config), config.run_id, "text.zh-Hans")
            self.assertEqual(result["nextJobId"], jobs._digest(following))
            receipt_path = folder / subject.durable.reopen_file(following)
            receipt = json.loads(receipt_path.read_text())
            self.assertEqual((receipt["schemaVersion"], receipt["identity"]["nodeIdentity"], receipt["reopenedGroups"]),
                             (subject.durable.REOPEN_SCHEMA, following["nodeIdentity"], [failed]))
            # The failed job keeps its outcome and history; only the receipt was added beside it.
            after = {path.name: path.read_bytes() for path in folder.iterdir() if path.is_file()}
            self.assertEqual({name: data for name, data in after.items() if name != receipt_path.name}, before)
            # The receipt is checked against the evidence it names before the failed job yields: another
            # ledger head, a group the notes do not reopen, or other notes need reconciliation instead.
            other = next(group for group in self.group_ids() if group != failed)
            written = receipt_path.read_bytes()
            for field, value in (("repairLedgerHeadSha256", "e" * 64), ("repairLedgerSequence", 1),
                                 ("reopenedGroups", [other]), ("reopenedGroups", sorted([failed, other])),
                                 ("meaningNotesSha256", "f" * 64)):
                with self.subTest(field=field, value=value):
                    receipt_path.write_text(json.dumps(dict(receipt, **{field: value})))
                    view = subject.snapshot(config)
                    self.assertEqual(view["nodes"]["text.zh-Hans"]["reasonCode"], "unbound_job_evidence")
                    self.assertEqual(view["durableJobInspection"]["diagnostics"], ["unverified_reopen_receipt"])
            receipt_path.write_bytes(written)
            view = subject.snapshot(config)
            self.assertEqual(view["nodes"]["text.zh-Hans"]["status"], "ready")
            row = next(row for row in view["durableJobInspection"]["jobs"] if row["jobId"] == first)
            self.assertEqual((row["status"], row["originalJobStatus"], row["supersededBy"]),
                             ("superseded", "failed", jobs._digest(following)))
            with self.assertRaisesRegex(ValueError, "one_failed_text_job_required"):
                subject.reopen_repair(self.base.path, "zh-Hans", view["stateRevision"])
            # The next job runs under the new identity and continues the same repair chain: only the noted
            # group is dispatched again, with its note, and the candidate is admitted.
            earlier = len(self.calls)
            result, config = self.run_worker(reviewer)
        self.assertEqual(result["status"], "machine_review_pass_human_review_pending")
        reopened = self.calls[earlier:]
        self.assertEqual({json.loads(p["messages"][1]["content"])["translationGroupId"] for p in reopened}, {failed})
        self.assertEqual(len(reopened), 2)
        self.assertTrue(all(marker in p["messages"][1]["content"] for p in reopened))
        ledger = auto_repair.load_ledger(subject.repair_ledger_root(config), auto_repair.lineage(request))
        self.assertEqual([entry["outcome"] for entry in ledger], ["repairing", "stopped", "repairing", "passed"])
        self.assertEqual(ledger[2]["reopenedBy"]["units"], [units[0]])
        # Once the reopened job has run, its receipt is held to the reopen entry its worker wrote.
        with patch.object(subject.source_meaning, "load_meaning_notes", return_value=notes):
            self.assertEqual(subject.snapshot(config)["durableJobInspection"]["diagnostics"], [])
            receipt_path.write_text(json.dumps(dict(receipt, reopenedGroups=[other])))
            view = subject.snapshot(config)
        self.assertEqual(view["durableJobInspection"]["diagnostics"], ["unverified_reopen_receipt"])
        # A receipt edited after the fact no longer binds the failed job: the run needs inspection.
        receipt["reopenedGroups"] = []
        receipt_path.write_text(json.dumps(receipt))
        with patch.object(subject.source_meaning, "load_meaning_notes", return_value=notes):
            view = subject.snapshot(config)
        self.assertEqual(view["nodes"]["text.zh-Hans"]["reasonCode"], "unbound_job_evidence")

    def test_api_transport_reuses_an_earlier_round_only_for_a_repair(self):
        failed = self.group_ids()[1]
        self.fail_first_review = {failed}

        def api_caller(key, payload):
            return self.caller(key, payload)
        api_caller.execution_identity = dict(API_IDENTITY)
        _, config = self.run_worker(api_caller)
        source, anchor, policy = subject._inputs(config, "zh-Hans", subject.snapshot(config))
        lane = config.lanes["zh-Hans"]
        with self.assertRaisesRegex(ValueError, "cross-run cache reuse is not enabled"):
            subject.models.run_accounted(source, anchor, policy, self.base.root / "plain-reuse", "fixture-key",
                                         api_caller, None, lane["plugin"], None,
                                         self.base.output / "repair-rounds" / "round-001")


if __name__ == "__main__":
    unittest.main()
