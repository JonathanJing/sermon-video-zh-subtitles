"""Offline concurrency, crash recovery and frozen experiment regression tests."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from scripts import run_target_language_models as runner
from scripts import sermon_accounting as accounting
from scripts import target_language_policy as policies
from scripts import layer2_api_concurrency as api_concurrency
from scripts import weekly_pipeline_report as weekly
from scripts.experiments import layer2_concurrency as experiment
from tests import test_run_target_language_models as fixtures


class Layer2ConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RunTargetLanguageModelsTests("test_astra_then_sol_each_group_and_admit_human_pending")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.f, self.out = self.fixture.fixture, self.fixture.out
        self.policy = copy.deepcopy(self.f.policy)
        self.policy["batching"]["workers"] = 2
        self.policy["componentSha256"]["batching"] = policies.canonical_sha256(self.policy["batching"])
        self.calls = []
        self.lock = threading.Lock()

    def production_run(self, out, caller, **options):
        return runner.run(self.f.source, self.f.anchor, self.policy, out, "fixture-key", caller,
                          plugin_path=self.f.plugin_path, **options)

    def response(self, key, payload):
        self.assertEqual(key, "fixture-key")
        data = json.loads(payload["messages"][1]["content"])
        with self.lock:
            self.calls.append((data["translationGroupId"], payload["model"]))
        group = next(g for g in self.f.evidence["groups"] if g["sourceUnitIds"] == data["sourceUnitIds"])
        keys = ["sourceUnitIds", "targetUtterances", "coverage"]
        role = 'reviewer' if payload['reasoning_effort'] == self.policy['reviewer']['reasoningEffort'] else 'translator'
        if role == 'reviewer':
            keys.append("semanticReview")
        result = {k: copy.deepcopy(group[k]) for k in keys}
        result["translationGroupId"] = data["translationGroupId"]
        return {"id": data["translationGroupId"] + role, "model": payload["model"],
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}]}

    def test_three_worker_bound_reverse_completion_and_invalid_budgets(self):
        active = peak = 0
        lock = threading.Lock()
        barrier = threading.Barrier(3)
        def worker(index):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            if index < 3:
                barrier.wait(timeout=3)
            time.sleep(.003 * (3 - index % 3))
            with lock:
                active -= 1
            return index
        self.assertEqual(list(range(9)), runner.ordered_group_results(list(range(9)), worker, 3))
        self.assertEqual(peak, 3)
        for budget in (0, -1, 25, True, 1.5):
            with self.subTest(budget=budget), self.assertRaisesRegex(ValueError, "Group workers exceed versioned capacity"):
                runner.ordered_group_results([], lambda _: self.fail("invalid budget started work"), budget)

    def test_standalone_runner_keeps_legacy_three_worker_ceiling(self):
        policy = copy.deepcopy(self.policy)
        for workers in (1, 3):
            policy["batching"]["workers"] = workers
            runner.validate_standalone_worker_budget(policy)
        for workers in (4, 16):
            policy["batching"]["workers"] = workers
            with self.subTest(workers=workers), self.assertRaisesRegex(ValueError, "workers=1..3"):
                runner.validate_standalone_worker_budget(policy)

    def test_shared_api_slots_cap_run_requests_without_polluting_durable_job_tree(self):
        active = peak = 0
        lock = threading.Lock()
        with tempfile.TemporaryDirectory() as tmp:
            job_root = Path(tmp) / 'jobs'
            job_root.mkdir()

            def request():
                nonlocal active, peak
                with api_concurrency.request_slot(job_root):
                    with lock:
                        active += 1
                        peak = max(peak, active)
                    time.sleep(.02)
                    with lock:
                        active -= 1

            workers = [threading.Thread(target=request) for _ in range(80)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=5)
                self.assertFalse(worker.is_alive())
            self.assertGreater(peak, 1)
            self.assertLessEqual(peak, api_concurrency.MAX_IN_FLIGHT_API_CALLS)
            self.assertEqual(list(job_root.iterdir()), [])

    def test_parallel_failure_drains_success_and_repair_reuses_successful_cache(self):
        plan = runner.group_plan(runner.producer.prepare_request(self.f.source, self.f.anchor, self.policy), self.f.anchor)
        failed_id = plan[0]["translationGroupId"]
        def fail_review(key, payload):
            answer = self.response(key, payload)
            if payload['reasoning_effort'] == self.policy['reviewer']['reasoningEffort'] and json.loads(payload["messages"][1]["content"])["translationGroupId"] == failed_id:
                deadline = time.monotonic() + 5
                while not (self.out / "group-0002-sol.json").exists() and time.monotonic() < deadline:
                    time.sleep(.005)
                self.assertTrue((self.out / "group-0002-sol.json").exists())
                result = json.loads(answer["choices"][0]["message"]["content"])
                result["semanticReview"]["status"] = "fail"
                result["semanticReview"]["issues"] = ["Synthetic repair needed"]
                answer["choices"][0]["message"]["content"] = json.dumps(result)
            return answer
        with self.assertRaisesRegex(ValueError, "Sol flagged group"):
            self.production_run(self.out, fail_review)
        self.assertFalse((self.out / "evidence.json").exists())
        successful = {role: (self.out / f"group-0002-{role}.json").read_bytes() for role in ("astra", "sol")}
        request = runner.producer._load(self.out / "request.json")
        brief = {"schemaVersion": runner.PARTIAL_REPAIR_SCHEMA,
                 **{k: request[k] for k in ("targetLocale", "englishSourcePackageJsonSha256", "anchorManifestSha256", "translationPolicySha256")},
                 "groups": [{**plan[0], "failedRole": "reviewer",
                     "failedCacheSha256": hashlib.sha256((self.out / "group-0001-sol.json").read_bytes()).hexdigest(),
                     "failureReason": "Synthetic review issue", "instruction": "Resolve the source-bound issue."}]}
        self.calls.clear()
        repaired = self.out.parent / "repaired"
        evidence = self.production_run(repaired, self.response, reuse_from=self.out,
                                       partial_repair_brief=brief)
        self.assertEqual(self.calls, [(failed_id, self.policy['translator']['model']), (failed_id, self.policy['reviewer']['model'])])
        self.assertEqual([g["translationGroupId"] for g in evidence["groups"]], [g["translationGroupId"] for g in plan])
        for role, data in successful.items():
            self.assertEqual((repaired / f"group-0002-{role}.json").read_bytes(), data)

    def test_unknown_later_group_blocks_entire_resume_before_new_calls(self):
        self.production_run(self.out, self.response)
        # Simulate a durable identity with earlier work not yet requested and a
        # later transport outcome unknown. The original marker is never retired.
        (self.out / "evidence.json").unlink()
        for index in (1, 2):
            for suffix in ("astra.json", "astra.raw.json", "sol.json", "sol.raw.json"):
                (self.out / f"group-{index:04d}-{suffix}").unlink()
        marker = self.out / "group-0002-astra.started.json"
        runner.save_new(marker, {"status": "started_response_unconfirmed"})
        original = marker.read_bytes()
        with self.assertRaisesRegex(ValueError, "Uncertain paid translator call"), accounting.accounting_session(self.out / "accounting", "layer2_models"):
            self.production_run(self.out, lambda *_: self.fail("another group dispatched before unknown reconciliation"))
        self.assertEqual(marker.read_bytes(), original)
        events, damaged = accounting.read_events(self.out / "accounting")
        self.assertFalse(damaged)
        self.assertFalse(any((e.get("stage") or "").startswith("layer2.group.") for e in events))
        with self.assertRaisesRegex(ValueError, "Uncertain paid translator call"):
            runner.require_reconciled_requests(None, self.out)

    def test_returned_raw_under_started_marker_remains_recoverable(self):
        self.production_run(self.out, self.response)
        expected = runner.producer._load(self.out / "evidence.json")
        (self.out / "group-0002-sol.json").unlink()
        runner.save_new(self.out / "group-0002-sol.started.json", {"status": "started_response_unconfirmed"})
        self.assertEqual(self.production_run(self.out, lambda *_: self.fail("returned raw response must not be paid twice")), expected)
        self.assertFalse((self.out / "group-0002-sol.started.json").exists())

    def test_parallel_accounting_keeps_group_dependencies_and_source_order(self):
        barrier = threading.Barrier(2)
        def overlap(key, payload):
            if payload['reasoning_effort'] == self.policy['translator']['reasoningEffort']:
                barrier.wait(timeout=3)
            return self.response(key, payload)
        with accounting.accounting_session(self.out / "accounting", "layer2_models"):
            self.production_run(self.out, overlap)
        events, damaged = accounting.read_events(self.out / "accounting")
        self.assertFalse(damaged)
        starts = {e["spanId"]: e for e in events if e["event"] == "stage_started"}
        assembly = next(e for e in starts.values() if e["stage"].startswith("layer2.evidence_assembly."))
        self.assertEqual(len(assembly["dependsOn"]), 2)
        self.assertTrue(all(starts[s]["stage"].startswith("layer2.review_validation.") for s in assembly["dependsOn"]))
        for e in starts.values():
            if e["stage"].startswith("layer2.reviewer."):
                self.assertEqual(len(e["dependsOn"]), 1)
                self.assertTrue(starts[e["dependsOn"][0]]["stage"].startswith("layer2.draft_validation."))
        report = weekly.project(self.out / "accounting")["runs"][-1]
        self.assertEqual(report["status"], "projected", report["diagnostics"])
        self.assertIsNotNone(report["criticalPath"])

    def test_freeze_isolated_arms_preserves_source_policy_roles_and_human_gate(self):
        inputs = self.out.parent / "inputs"
        inputs.mkdir()
        for name, value in (("source", self.f.source), ("anchor", self.f.anchor), ("policy", self.f.policy)):
            runner.save_new(inputs / f"{name}.json", value)
        before = (inputs / "policy.json").read_bytes()
        manifest = experiment.freeze(inputs / "source.json", inputs / "anchor.json", inputs / "policy.json",
                                     self.f.plugin_path, self.out)
        self.assertFalse(manifest["dispatchEnabled"])
        self.assertEqual([a["workers"] for a in manifest["arms"]], [1, 2, 3])
        self.assertEqual(len({a["outputDirectory"] for a in manifest["arms"]}), 3)
        self.assertEqual((inputs / "policy.json").read_bytes(), before)
        self.assertEqual(len({a["translationPolicySha256"] for a in manifest["arms"]}), 3)
        report = experiment.inspect(self.out)
        self.assertTrue(all(a["status"] == "not_run" and not a["humanApproval"] and not a["releaseEligible"] for a in report["arms"]))
        arm = manifest["arms"][1]
        policy = runner.producer._load(self.out / arm["policy"])
        output = self.out / arm["outputDirectory"]
        runner.run_accounted(self.f.source, self.f.anchor, policy, output,
            "fixture-key", self.response, None, self.f.plugin_path, None, None)
        returned = experiment.inspect(self.out)["arms"][1]
        self.assertEqual(returned["status"], "model_evidence_returned")
        self.assertFalse(returned["humanApproval"])
        self.assertEqual(returned["accounting"]["runs"][-1]["status"], "projected")
        with self.assertRaisesRegex(ValueError, "new directory"):
            experiment.freeze(inputs / "source.json", inputs / "anchor.json", inputs / "policy.json", self.f.plugin_path, self.out)
        changed = self.out / "workers-3/policy.json"
        policy = runner.producer._load(changed)
        policy["reviewer"]["model"] = "gpt-6-astra"
        changed.write_text(json.dumps(policy))
        with self.assertRaisesRegex(ValueError, "beyond frozen worker budget"):
            experiment.inspect(self.out)

    def test_freeze_retains_explicit_group_plan_and_cli_has_no_execute_mode(self):
        from unittest.mock import patch
        inputs = self.out.parent / "inputs"
        inputs.mkdir()
        for name, value in (("source", self.f.source), ("anchor", self.f.anchor), ("policy", self.f.policy)):
            runner.save_new(inputs / f"{name}.json", value)
        plan = [{"translationGroupId": "reviewed-merged-group",
                 "sourceUnitIds": [u["sourceUnitId"] for u in self.f.request["sourceUnits"]]}]
        runner.save_new(inputs / "plan.json", plan)
        argv = ["layer2_concurrency", "freeze", "--english-source-package", str(inputs / "source.json"),
                "--anchor", str(inputs / "anchor.json"), "--policy", str(inputs / "policy.json"),
                "--plugin", str(self.f.plugin_path), "--group-plan", str(inputs / "plan.json"),
                "--out-dir", str(self.out)]
        with patch("sys.argv", argv), patch.object(runner.sermon_pipeline, "chat_json", side_effect=AssertionError("generator called API")):
            experiment.main()
        manifest = runner.producer._load(self.out / "experiment.json")
        self.assertEqual(manifest["translationGroups"], 1)
        self.assertTrue(all(arm["plannedFreshModelCalls"] == 2 for arm in manifest["arms"]))
        self.assertEqual(json.loads((self.out / "group-plan.json").read_text()), plan)
        self.assertEqual([a["status"] for a in experiment.inspect(self.out)["arms"]], ["not_run"] * 3)


if __name__ == "__main__":
    unittest.main()
