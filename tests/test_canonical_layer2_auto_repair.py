"""Auto repair inside the canonical controller worker; all model replies are synthetic."""
import copy
import json
import unittest

from scripts import canonical_layer2_controller as subject
from scripts import layer2_auto_repair as auto_repair
from scripts import sermon_workflow_jobs as jobs
from tests import test_canonical_layer2_controller as controller_tests

API_IDENTITY = {"schemaVersion": "openai-layer2-budget-transport-identity-v1", "backend": "openai_api",
                "route": "dev", "budgetAuthorizationSha256": "b" * 64}


class ControllerAutoRepairTests(unittest.TestCase):
    def setUp(self):
        self.base = controller_tests.CanonicalLayer2ControllerTests(
            "test_default_shadow_is_read_only_and_never_loads_credentials_or_dispatches")
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.base.config_data["schemaVersion"] = subject.AUTO_REPAIR_SCHEMA
        self.base.config_data["layer2AutoRepair"] = dict(subject.AUTO_REPAIR_BINDING)
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
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(answer)}}]}

    def run_worker(self, caller):
        with self.base.active() as (config, code, key, _):
            return subject.execute(self.base.path, "zh-Hans", config.sha256, code, key,
                                   caller=caller, api_key="fixture-key"), config

    def group_ids(self):
        config = subject.load_configuration(self.base.path)
        source, anchor, policy = subject._inputs(config, "zh-Hans", subject.snapshot(config))
        request = subject.producer.prepare_request(source, anchor, policy)
        return [row["translationGroupId"] for row in subject.models.group_plan(request, anchor)]

    def test_configuration_binds_the_routing_version(self):
        self.assertTrue(subject.load_configuration(self.base.path).auto_repair)
        self.base.config_data["layer2AutoRepair"] = {"routingVersion": "other"}
        self.base.save_config()
        with self.assertRaisesRegex(ValueError, "invalid_execution_configuration"):
            subject.load_configuration(self.base.path)
        self.base.config_data["schemaVersion"] = subject.SCHEMA
        self.base.config_data["layer2AutoRepair"] = dict(subject.AUTO_REPAIR_BINDING)
        self.base.save_config()
        with self.assertRaisesRegex(ValueError, "invalid_execution_configuration"):
            subject.load_configuration(self.base.path)

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
