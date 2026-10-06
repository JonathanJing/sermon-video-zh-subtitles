import copy
import hashlib

from contextvars import ContextVar
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from scripts import run_target_language_models as subject
from scripts import four_layer_measure as measure
from scripts import four_layer_progress as progress
from scripts import sermon_accounting as accounting
from scripts import produce_target_language_candidate as producer
from scripts import target_language_policy as policy_tools
from tests import test_produce_target_language_candidate as fixture_module


class RunTargetLanguageModelsTests(unittest.TestCase):
    def test_strict_budget_uses_approved_default_tier_for_sol(self):
        from scripts import sermon_provider_limits as limits
        policy = {'translator': {'model': 'gpt-6.1-sol', 'reasoningEffort': 'high'}}
        prompt = {'instruction': 'Return JSON.', 'input': {'sample': 'synthetic'}}
        standalone = subject.model_payload('translator', prompt, policy)
        strict = subject.model_payload('translator', prompt, policy, limits.DEFAULT_REQUEST_LIMITS)
        self.assertEqual(standalone['service_tier'], 'fast')
        self.assertEqual(strict['service_tier'], 'default')
        self.assertEqual(strict['max_completion_tokens'], 4096)

    def test_korean_spoken_revision_can_close_a_complete_clause(self):
        instruction = subject.revision_boundary_instruction("ko", revising=True)
        self.assertIn("complete polite predicate", instruction)
        self.assertIn("next English unit begins with 'because'", instruction)
        self.assertIn("Do not force a trailing comma", instruction)
        self.assertEqual("", subject.revision_boundary_instruction("ko", revising=False))
        self.assertEqual("", subject.revision_boundary_instruction("es", revising=True))

    def test_reference_only_rule_is_system_level_for_both_model_roles(self):
        policy = {"scripture": {"quoteCheckPolicy": "references_only"}}
        instruction = subject.scripture_prompt_instruction(policy)
        self.assertIn("paraphrase the speaker's meaning", instruction)
        self.assertIn("Do not present the text as an exact quotation", instruction)

    def test_context_keeps_three_prior_units_for_elliptical_repeat(self):
        rows = [{"sourceUnitId": f"u{i}", "english": f"sentence {i}"}
                for i in range(1, 7)]
        request = {"sourceUnits": rows}
        plan = [{"sourceUnitIds": [row["sourceUnitId"]]} for row in rows]
        context = subject.surrounding_context(request, plan, 4)
        self.assertEqual([row["sourceUnitId"] for row in context["before"]],
                         ["u2", "u3", "u4"])
        self.assertEqual([row["sourceUnitId"] for row in context["after"]], ["u6"])

    def setUp(self):
        self.fixture = fixture_module.ProduceTargetLanguageCandidateTests(
            methodName="test_compiles_valid_candidate_without_human_approval")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.out = Path(temp.name) / "run"
        self.calls = []

    def fake_call(self, api_key, payload):
        self.assertEqual(api_key, "fixture-key")
        self.calls.append(payload)
        index = (len(self.calls) + 1) // 2
        group = self.fixture.evidence["groups"][index - 1]
        input_group = json.loads(payload["messages"][1]["content"])
        if payload["reasoning_effort"] == "high":
            result = {key: copy.deepcopy(group[key]) for key in
                      ("translationGroupId", "sourceUnitIds", "targetUtterances", "coverage")}
        else:
            result = {key: copy.deepcopy(group[key]) for key in
                      ("translationGroupId", "sourceUnitIds", "targetUtterances", "coverage",
                       "semanticReview")}
        result["translationGroupId"] = input_group["translationGroupId"]
        return {"id": f"response-{len(self.calls)}", "model": payload["model"],
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}]}

    def simulation_configuration_fixture(self):
        from scripts.codex_layer2_transport import TEST_CONFIGURATION
        policy = copy.deepcopy(self.fixture.policy)
        policy['simulationModelConfiguration'] = copy.deepcopy(TEST_CONFIGURATION)
        for role in subject.MODEL_ROLES:
            settings = TEST_CONFIGURATION[role]
            policy[role].update(model=settings['model'], reasoningEffort=settings['reasoningEffort'])
            policy['componentSha256'][role] = policy_tools.canonical_sha256(policy[role])
        request = copy.deepcopy(self.fixture.request)
        request.update(schemaVersion='sermon-dry-run-layer2-request-v1', simulationOnly=True,
                       simulationModelConfiguration=copy.deepcopy(TEST_CONFIGURATION),
                       translationPolicySha256=policy_tools.canonical_sha256(policy))
        test = self
        class Caller:
            execution_identity = {'backend': 'codex_cli', 'simulationModelConfiguration': copy.deepcopy(TEST_CONFIGURATION)}
            def __call__(inner, key, payload):
                test.assertEqual(key, '')
                test.calls.append(payload)
                group = test.fixture.evidence['groups'][(len(test.calls) - 1) // 2]
                result = copy.deepcopy(group)
                result['translationGroupId'] = json.loads(payload['messages'][1]['content'])['translationGroupId']
                return {'id': 'test-' + str(len(test.calls)), 'model': payload['model'],
                        'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(result)}}]}
        return policy, request, Caller()

    def test_sol61_override_isolated_calls_and_cache_bind_actual_configuration(self):
        policy, request, caller = self.simulation_configuration_fixture()
        evidence = subject._run_prepared_groups(request, self.fixture.anchor, policy, self.out, '', caller,
                                                simulation_only=True)
        self.assertEqual([p['model'] for p in self.calls], ['gpt-6.1-sol', 'gpt-6.1-sol'] * 2)
        self.assertEqual([p['reasoning_effort'] for p in self.calls], ['high', 'medium'] * 2)
        self.assertEqual([p['service_tier'] for p in self.calls], ['fast'] * 4)
        self.assertEqual(evidence['generation']['translator']['model'], 'gpt-6.1-sol')
        self.assertEqual(json.loads((self.out / 'group-0001-astra.json').read_text())['model'], 'gpt-6.1-sol')
        subject._run_prepared_groups(request, self.fixture.anchor, policy, self.out, '', caller, simulation_only=True)
        self.assertEqual(len(self.calls), 4)
        caller.execution_identity = {**caller.execution_identity, 'runtime': 'changed'}
        with self.assertRaisesRegex(ValueError, 'another source, policy, or group plan'):
            subject._run_prepared_groups(request, self.fixture.anchor, policy, self.out, '', caller, simulation_only=True)
        self.assertEqual(len(self.calls), 4)

    def test_simulation_model_override_rejected_in_formal_and_unbound_paths(self):
        policy, request, caller = self.simulation_configuration_fixture()
        formal = {key: value for key, value in request.items() if key != 'simulationOnly'}
        with self.assertRaisesRegex(ValueError, 'cannot enter formal production'):
            subject._run_prepared_groups(formal, self.fixture.anchor, policy, self.out, '', caller)
        del request['simulationModelConfiguration']
        with self.assertRaisesRegex(ValueError, 'matching request and CLI transport identity'):
            subject._run_prepared_groups(request, self.fixture.anchor, policy, self.out, '', caller, simulation_only=True)
        self.assertFalse(self.out.exists())
        self.assertEqual(self.calls, [])

    def test_resource_capacity_busy_does_not_write_unknown_call_marker(self):
        from scripts.sermon_unified.contracts import ContractError
        class Caller:
            def admit_resource(inner,payload):raise ContractError('resource_capacity_busy')
            def __call__(inner,*args):raise AssertionError('busy must not dispatch')
        with self.assertRaisesRegex(ContractError,'resource_capacity_busy'):
            subject.run(self.fixture.source,self.fixture.anchor,self.fixture.policy,
                        self.out,'fixture-key',Caller())
        self.assertFalse(any(self.out.glob('group-*.started.json')))
        self.assertEqual(self.calls,[])
        evidence=subject.run(self.fixture.source,self.fixture.anchor,self.fixture.policy,
                             self.out,'fixture-key',self.fake_call)
        self.assertEqual(len(evidence['groups']),2)
        self.assertEqual(len(self.calls),4)

    def test_astra_then_sol_each_group_and_admit_human_pending(self):
        f = self.fixture
        evidence = subject.run(f.source, f.anchor, f.policy, self.out,
                               "fixture-key", self.fake_call)
        self.assertEqual([call["model"] for call in self.calls],
                         ["gpt-6.1-sol", "gpt-6.1-sol"] * 2)
        self.assertEqual([call["reasoning_effort"] for call in self.calls],
                         ["high", "medium"] * 2)
        self.assertTrue(all("never invent it" in call["messages"][0]["content"]
                            for call in self.calls))
        self.assertTrue(all("elliptical repetitions" in call["messages"][0]["content"]
                            for call in self.calls))
        self.assertEqual(evidence["generation"]["translator"]["requestIds"],
                         ["response-1", "response-3"])
        self.assertEqual(evidence["generation"]["reviewer"]["requestIds"],
                         ["response-2", "response-4"])
        receipt = producer.run_language_plugin(f.source, f.anchor, f.policy,
                                               f.request, evidence, f.plugin_path, f.plugin_sha)
        candidate = producer.admit_evidence(f.source, f.anchor, f.policy,
                                            f.request, evidence, receipt,
                                            f.plugin_path, f.plugin_sha)
        self.assertEqual(candidate["status"], "machine_review_pass_human_review_pending")
        self.assertFalse(candidate["releaseEligible"])
        self.assertEqual(candidate["humanReview"]["translation"], "pending")
        self.calls.clear()
        self.assertEqual(subject.run(f.source, f.anchor, f.policy, self.out,
                                     "fixture-key", self.fake_call), evidence)
        self.assertEqual(self.calls, [])

    def test_incoherent_ready_source_never_reaches_model_or_creates_paid_cache(self):
        mutations = {
            "missing-media": lambda s: s["source"].update(media=None),
            "negative-window": lambda s: s["source"]["approvedWindow"].update(startSeconds=-1),
            "reversed-window": lambda s: s["source"]["approvedWindow"].update(endSeconds=0),
            "window-beyond-media": lambda s: s["source"]["approvedWindow"].update(endSeconds=301),
            "changed-media": lambda s: s["source"]["media"].update(sha256="f" * 64),
            "stale-derived-identity": lambda s: s.update(downstreamInvalidationKey="f" * 64),
            "stale-package-id": lambda s: s.update(packageId="english-source-other"),
            "candidate-not-eligible": lambda s: s.update(candidateTranslationEligible=False),
        }
        f = self.fixture
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                source = copy.deepcopy(f.source)
                mutate(source)
                # Coherently refresh policy scope so rejection proves source
                # admission, rather than merely a stale downstream policy hash.
                policy = copy.deepcopy(f.policy)
                policy.pop("componentSha256")
                policy["sourceScope"]["englishSourcePackageJsonSha256"] = producer.interpretation.json_sha256(source)
                policy = policy_tools.freeze_policy(policy)
                with self.assertRaises(ValueError):
                    subject.run(source, f.anchor, policy, self.out, "fixture-key", self.fake_call)
                self.assertEqual(self.calls, [])
                self.assertFalse(self.out.exists())

    def test_known_runner_identities_resume_paid_cache_but_unknown_identity_fails(self):
        f = self.fixture
        parent_hash = "1922f23b881363ac4f1a32a99de7184fecd1ae445befde5f2282d400bd762e40"
        self.assertEqual(subject.RUNNER_PRODUCTION_IDENTITY_SHA256, parent_hash)
        evidence = subject.run(f.source, f.anchor, f.policy, self.out,
                               "fixture-key", self.fake_call)
        request = producer.prepare_request(f.source, f.anchor, f.policy)
        plan = subject.group_plan(request, f.anchor)
        manifest = self.out / "run-identity.json"
        for implementation_hash in (parent_hash, *subject.COMPATIBLE_RUNNER_IDENTITIES):
            digest = policy_tools.canonical_sha256({
                "request": request, "groupPlan": plan,
                "runnerImplementationSha256": implementation_hash})
            manifest.write_text(json.dumps({"sha256": digest}))
            self.assertEqual(subject.run(
                f.source, f.anchor, f.policy, self.out, "fixture-key",
                lambda *_: self.fail("verified paid calls must be reused")), evidence)
        manifest.write_text(json.dumps({"sha256": "0" * 64}))
        with self.assertRaisesRegex(ValueError, "Output directory belongs"):
            subject.run(f.source, f.anchor, f.policy, self.out, "fixture-key",
                        lambda *_: self.fail("unknown identity must fail before paid calls"))

    def test_progress_ledger_tracks_translation_and_review_groups_separately(self):
        f = self.fixture
        ledger_path = self.out.parent / "four-layer-progress.json"
        from scripts import four_layer_measure as measure
        from scripts import four_layer_progress as progress
        from scripts import sermon_accounting as accounting
        progress.save(ledger_path, progress.new_ledger("test-page", ["ko"]))
        step = "L2-02@ko"
        with measure.producer_step(ledger_path, step, locale="ko"):
            plan = subject.group_plan(producer.prepare_request(f.source, f.anchor, f.policy), f.anchor)
            accounting.record_workload(measure.stage_name(step), {"translationGroups": len(plan)})
            subject.run(f.source, f.anchor, f.policy, self.out,
                        "fixture-key", self.fake_call)
        events, damaged = accounting.read_events(ledger_path.parent / "accounting")
        self.assertFalse(damaged)
        row = next(row for row in measure.timing_audit(progress.load(ledger_path), events)["rows"]
                   if row["step"] == step)
        substages = {child["id"]: child for child in row["subStages"]}
        self.assertEqual(substages["initial_translation"]["completedUnits"], len(plan))
        self.assertEqual(substages["independent_review"]["completedUnits"], len(plan))
        self.assertEqual(progress.load(ledger_path)["steps"][step]["status"], "pending")
    def test_each_group_and_model_role_has_measured_attempts_on_resume(self):
        f = self.fixture
        with accounting.accounting_session(self.out / "accounting", "layer2_models",
                                           {"targetLocale": f.policy["targetLocale"]}):
            subject.run(f.source, f.anchor, f.policy, self.out,
                        "fixture-key", self.fake_call)
            subject.run(f.source, f.anchor, f.policy, self.out,
                        "fixture-key", lambda *_: self.fail("must reuse"))
        attempts = accounting.summarize(self.out / "accounting")["stageAttempts"]
        unit_attempts = [row for row in attempts if row["stage"].startswith("layer2.")]
        events, damaged = accounting.read_events(self.out / "accounting")
        self.assertFalse(damaged)
        roles = [e for e in events if e['event'] == 'stage_started' and
                 (e['stage'].startswith('layer2.translator.') or e['stage'].startswith('layer2.reviewer.'))]
        by_span = {e['spanId']: e for e in events if e['event'] == 'stage_started'}
        for role in roles:
            self.assertEqual(role['executorType'], 'deterministic_program' if role['cacheHit'] else 'production_model')
            self.assertIsNotNone(role['workUnitId'])
            self.assertEqual(len(role['dependsOn']), 1)
            predecessor = by_span[role['dependsOn'][0]]
            if '.reviewer.' in role['stage']:
                self.assertEqual(predecessor['stage'].replace('.draft_validation.', '.reviewer.'), role['stage'])
                translator = by_span[predecessor['dependsOn'][0]]
                self.assertEqual(translator['stage'].replace('.translator.', '.reviewer.'), role['stage'])
            else:
                self.assertEqual(predecessor['stage'].replace('.prepare.', '.translator.'), role['stage'])
        self.assertEqual(len(unit_attempts), 30)
        self.assertEqual(sum(row["cacheHit"] for row in unit_attempts), 4)
        self.assertTrue(all(row["finishedAt"] and row["elapsedSeconds"] is not None
                            for row in unit_attempts))

    def test_model_groups_share_the_canonical_layer2_timing_ledger(self):
        f = self.fixture
        ledger_path = self.out.parent / "four-layer-progress.json"
        progress.save(ledger_path, progress.new_ledger("test-page", ["zh-Hans"]))
        result = subject.run_accounted(
            f.source, f.anchor, f.policy, self.out, "fixture-key", self.fake_call,
            None, f.plugin_path, None, None, progress_ledger=ledger_path)
        self.assertEqual(len(result["groups"]), 2)
        events, damaged = accounting.read_events(ledger_path.parent / "accounting")
        self.assertFalse(damaged)
        report = measure.timing_audit(progress.load(ledger_path), events)
        row = next(row for row in report["rows"] if row["step"] == "L2-02@zh-Hans")
        self.assertEqual(row["executionAttempts"], 1)
        self.assertEqual(row["attemptHistory"][0]["workload"]["doneUnits"], 2)
        substages = {child["id"]: child for child in row["subStages"]}
        self.assertEqual(substages["initial_translation"]["completedUnits"], 2)
        self.assertEqual(substages["independent_review"]["completedUnits"], 2)
        parent = next(event for event in events if event["event"] == "stage_started"
                      and event["stage"] == "four_layer.L2-02:zh-Hans")
        child = next(event for event in events if event["event"] == "stage_started"
                     and event["stage"] == "layer2_models")
        self.assertEqual(child["parentSpanId"], parent["spanId"])
        self.assertTrue(any(event["event"] == "stage_finished"
                            and event["stage"].startswith("layer2.group.") for event in events))

    def test_two_workers_overlap_groups_but_review_each_after_its_draft(self):
        f = self.fixture
        policy = copy.deepcopy(f.policy)
        policy["batching"]["workers"] = 2
        policy["componentSha256"]["batching"] = policy_tools.canonical_sha256(policy["batching"])
        barrier = threading.Barrier(2)
        lock = threading.Lock()
        events = []
        group_ids = [row["translationGroupId"] for row in subject.group_plan(
            producer.prepare_request(f.source, f.anchor, policy), f.anchor)]
        def concurrent_call(api_key, payload):
            data = json.loads(payload["messages"][1]["content"])
            group_id = data["translationGroupId"]
            role = "translator" if payload["reasoning_effort"] == "high" else "reviewer"
            if role == "translator":
                barrier.wait(timeout=3)
            else:
                self.assertIn("astraDraft", data)
            with lock:
                events.append((group_id, role))
            group = next(row for row in f.evidence["groups"]
                         if row["sourceUnitIds"] == data["sourceUnitIds"])
            keys = ("translationGroupId", "sourceUnitIds", "targetUtterances", "coverage")
            result = {key: copy.deepcopy(group[key]) for key in keys}
            result["translationGroupId"] = group_id
            if role == "reviewer":
                result["semanticReview"] = copy.deepcopy(group["semanticReview"])
            return {"id": group_id + "-" + role, "model": payload["model"],
                    "choices": [{"finish_reason": "stop",
                                 "message": {"content": json.dumps(result)}}]}
        evidence = subject.run(f.source, f.anchor, policy, self.out,
                               "fixture-key", concurrent_call)
        self.assertEqual(group_ids, [row["translationGroupId"] for row in evidence["groups"]])
        self.assertEqual([group_id + "-translator" for group_id in group_ids],
                         evidence["generation"]["translator"]["requestIds"])
        self.assertEqual([group_id + "-reviewer" for group_id in group_ids],
                         evidence["generation"]["reviewer"]["requestIds"])
        for group_id in group_ids:
            self.assertLess(events.index((group_id, "translator")),
                            events.index((group_id, "reviewer")))
        receipt = producer.run_language_plugin(f.source, f.anchor, policy,
                                               producer.prepare_request(f.source, f.anchor, policy),
                                               evidence, f.plugin_path, f.plugin_sha)
        candidate = producer.admit_evidence(
            f.source, f.anchor, policy,
            producer.prepare_request(f.source, f.anchor, policy),
            evidence, receipt, f.plugin_path, f.plugin_sha)
        self.assertEqual("machine_review_pass_human_review_pending", candidate["status"])
        subject.run(f.source, f.anchor, policy, self.out, "fixture-key",
                    lambda *_: self.fail("completed requests must be reused"))

    def test_worker_limit_is_checked_before_paid_calls(self):
        policy = copy.deepcopy(self.fixture.policy)
        policy["batching"]["workers"] = 25
        policy["componentSha256"]["batching"] = policy_tools.canonical_sha256(policy["batching"])
        with self.assertRaisesRegex(ValueError, "maximum of 16"):
            subject.run(self.fixture.source, self.fixture.anchor, policy,
                        self.out, "fixture-key", self.fake_call)
        self.assertEqual([], self.calls)

    def test_parallel_failure_does_not_start_later_groups(self):
        barrier = threading.Barrier(2)
        started = []
        lock = threading.Lock()
        def worker(index):
            with lock:
                started.append(index)
            if index < 2:
                barrier.wait(timeout=3)
            if index == 0:
                raise ValueError("first group failed")
            if index == 1:
                time.sleep(0.03)
            return index
        with self.assertRaisesRegex(ValueError, "first group failed"):
            subject.ordered_group_results([0, 1, 2], worker, 2)
        self.assertEqual({0, 1}, set(started))

    def test_parallel_workers_keep_accounting_context(self):
        context = ContextVar("layer2_test_identity")
        token = context.set("page-and-locale")
        try:
            self.assertEqual(["page-and-locale"] * 3,
                             subject.ordered_group_results(
                                 [0, 1, 2], lambda _: context.get(), 2))
        finally:
            context.reset(token)

    def test_wrong_role_model_or_coverage_blocks_before_paid_call(self):
        f = self.fixture
        wrong = copy.deepcopy(f.policy)
        wrong["reviewer"]["model"] = "gpt-6-astra"
        wrong["componentSha256"]["reviewer"] = policy_tools.canonical_sha256(wrong["reviewer"])
        with self.assertRaisesRegex(ValueError, "Production reviewer model"):
            subject.run(f.source, f.anchor, wrong, self.out, "fixture-key", self.fake_call)
        wrong_batch = copy.deepcopy(f.policy)
        wrong_batch["batching"]["batchSize"] = 15
        wrong_batch["componentSha256"]["batching"] = policy_tools.canonical_sha256(
            wrong_batch["batching"])
        with self.assertRaisesRegex(ValueError, "batchSize=1"):
            subject.run(f.source, f.anchor, wrong_batch, self.out,
                        "fixture-key", self.fake_call)
        with self.assertRaisesRegex(ValueError, "cover source units"):
            subject.run(f.source, f.anchor, f.policy, self.out, "fixture-key", self.fake_call,
                        [{"translationGroupId": "partial", "sourceUnitIds": ["block-1-u001"]}])
        self.assertFalse(self.calls)

    def test_sol_failure_keeps_group_evidence_and_blocks_candidate(self):
        f = self.fixture
        def failing(api_key, payload):
            response = self.fake_call(api_key, payload)
            if payload["reasoning_effort"] == "medium":
                import json
                result = json.loads(response["choices"][0]["message"]["content"])
                result["semanticReview"]["status"] = "fail"
                result["semanticReview"]["issues"] = ["Unresolved omission"]
                response["choices"][0]["message"]["content"] = json.dumps(result)
            return response
        with self.assertRaisesRegex(ValueError, "Sol flagged group"):
            subject.run(f.source, f.anchor, f.policy, self.out, "fixture-key", failing)
        self.assertTrue((self.out / "group-0001-sol.json").exists())
        self.assertFalse((self.out / "evidence.json").exists())
        self.assertEqual(len(self.calls), 2)

    def test_sol_boolean_checks_are_normalized_without_rewriting_raw_response(self):
        f = self.fixture
        def boolean_checks(api_key, payload):
            response = self.fake_call(api_key, payload)
            if payload["reasoning_effort"] == "medium":
                result = json.loads(response["choices"][0]["message"]["content"])
                semantic = result["semanticReview"]
                semantic["checks"] = {key: True for key in semantic["checks"]}
                semantic["uncertainty"] = False
                response["choices"][0]["message"]["content"] = json.dumps(result)
            return response
        evidence = subject.run(f.source, f.anchor, f.policy, self.out,
                               "fixture-key", boolean_checks)
        self.assertEqual(set(evidence["groups"][0]["semanticReview"]["checks"].values()),
                         {"pass"})
        self.assertEqual(evidence["groups"][0]["semanticReview"]["uncertainty"], [])
        raw = json.loads((self.out / "group-0001-sol.json").read_text())["result"]
        self.assertTrue(raw["semanticReview"]["checks"]["completeMeaning"])

    def test_sol_boolean_uncertainty_still_blocks(self):
        f = self.fixture
        def uncertain(api_key, payload):
            response = self.fake_call(api_key, payload)
            if payload["reasoning_effort"] == "medium":
                result = json.loads(response["choices"][0]["message"]["content"])
                result["semanticReview"]["uncertainty"] = True
                response["choices"][0]["message"]["content"] = json.dumps(result)
            return response
        with self.assertRaisesRegex(ValueError, "Sol flagged group"):
            subject.run(f.source, f.anchor, f.policy, self.out,
                        "fixture-key", uncertain)

    def test_sol_null_empty_fields_normalize_to_empty_lists(self):
        self.assertEqual(subject.normalize_semantic_review({"uncertainty": None,
                                                            "issues": None}),
                         {"uncertainty": [], "issues": []})

    def test_sol_evidence_lines_normalize_without_changing_raw_response(self):
        self.assertEqual(subject.normalize_semantic_review({"evidence": [" first ", "second"],
                                                            "issues": []})["evidence"],
                         "first\nsecond")
        self.assertEqual(subject.normalize_semantic_review({"evidence": ["", "second"]})["evidence"],
                         ["", "second"])

    def test_structured_utterances_require_matching_source_ids(self):
        rows = [{'sourceUnitIds': ['u1'], 'targetText': '第一句', 'reviewStatus': 'pending'},
                {'sourceUnitIds': ['u2'], 'targetText': '第二句'}]
        self.assertEqual(subject._utterances(rows, ['u1', 'u2']), ['第一句', '第二句'])
        with self.assertRaisesRegex(ValueError, 'nonempty targetUtterances'):
            subject._utterances(rows, ['u2', 'u1'])

    def test_unconfirmed_request_blocks_automatic_paid_retry(self):
        f = self.fixture
        def interrupted(api_key, payload):
            raise TimeoutError("Response status unknown")
        with self.assertRaises(TimeoutError):
            subject.run(f.source, f.anchor, f.policy, self.out, "fixture-key", interrupted)
        self.assertTrue((self.out / "group-0001-astra.started.json").exists())
        with self.assertRaisesRegex(ValueError, "Uncertain paid translator call"):
            subject.run(f.source, f.anchor, f.policy, self.out,
                        "fixture-key", self.fake_call)
        self.assertFalse(self.calls)

    def test_invalid_completed_response_is_saved_before_validation(self):
        f = self.fixture
        def malformed(api_key, payload):
            response = self.fake_call(api_key, payload)
            response["model"] = "unexpected-model"
            return response
        with self.assertRaisesRegex(ValueError, "exact model"):
            subject.run(f.source, f.anchor, f.policy, self.out,
                        "fixture-key", malformed)
        raw_path = self.out / "group-0001-astra.raw.json"
        self.assertTrue(raw_path.exists())
        self.assertEqual(json.loads(raw_path.read_text())["response"]["id"], "response-1")
        self.calls.clear()
        with self.assertRaisesRegex(ValueError, "exact model"):
            subject.run(f.source, f.anchor, f.policy, self.out,
                        "fixture-key", self.fake_call)
        self.assertFalse(self.calls)

    def test_saved_raw_response_can_rebuild_validated_cache_without_api(self):
        f = self.fixture
        subject.run(f.source, f.anchor, f.policy, self.out, "fixture-key", self.fake_call)
        (self.out / "group-0001-astra.json").unlink()
        self.calls.clear()
        subject.run(f.source, f.anchor, f.policy, self.out, "fixture-key", self.fake_call)
        self.assertFalse(self.calls)
        self.assertTrue((self.out / "group-0001-astra.json").exists())

    def test_stale_group_cache_and_source_change_fail_closed(self):
        f = self.fixture
        subject.run(f.source, f.anchor, f.policy, self.out, "fixture-key", self.fake_call)
        changed = copy.deepcopy(f.anchor)
        changed["sourceUnits"][0]["english"] = "Different source."
        with self.assertRaises(ValueError):
            subject.run(f.source, changed, f.policy, self.out,
                        "fixture-key", self.fake_call)
        cache = self.out / "group-0001-astra.json"
        saved = json.loads(cache.read_text())
        saved["model"] = "gpt-6-sol"
        cache.write_text(json.dumps(saved))
        self.calls.clear()
        with self.assertRaisesRegex(ValueError, "Cached translator response"):
            subject.run(f.source, f.anchor, f.policy, self.out,
                        "fixture-key", self.fake_call)
        self.assertFalse(self.calls)

    def test_group_revision_reuses_unchanged_calls_and_invalidates_changed_payloads(self):
        f = self.fixture
        previous = self.out.parent / "previous"
        old = subject.run(f.source, f.anchor, f.policy, previous,
                          "fixture-key", self.fake_call)
        self.calls.clear()
        changed = old["groups"][1]
        prior_text = "".join(changed["targetUtterances"])
        brief = {
            "schemaVersion": subject.REVISION_BRIEF_SCHEMA,
            "targetLocale": f.request["targetLocale"],
            "englishSourcePackageJsonSha256": f.request["englishSourcePackageJsonSha256"],
            "anchorManifestSha256": f.request["anchorManifestSha256"],
            "translationPolicySha256": f.request["translationPolicySha256"],
            "groups": [{
                "translationGroupId": changed["translationGroupId"],
                "sourceUnitIds": changed["sourceUnitIds"],
                "priorTargetTextSha256": hashlib.sha256(prior_text.encode()).hexdigest(),
                "proposedTargetText": "A shorter, still complete translation.",
            }],
        }

        def revised_call(api_key, payload):
            self.assertEqual(api_key, "fixture-key")
            self.calls.append(payload)
            model_input = json.loads(payload["messages"][1]["content"])
            self.assertEqual(model_input["translationGroupId"], changed["translationGroupId"])
            self.assertEqual(model_input["revisionBrief"]["proposedTargetText"],
                             "A shorter, still complete translation.")
            instruction = payload["messages"][0]["content"]
            self.assertIn("shorter spoken", instruction)
            self.assertIn("parenthetical verse citations", instruction)
            self.assertIn("unspoken book or chapter", instruction)
            self.assertIn("unfinished", instruction)
            if payload["reasoning_effort"] == "high":
                self.assertIn("proposal's length", instruction)
            else:
                self.assertIn("proposedTargetText", instruction)
            if payload["reasoning_effort"] == "high":
                fields = ("translationGroupId", "sourceUnitIds", "targetUtterances", "coverage")
            else:
                fields = ("translationGroupId", "sourceUnitIds", "targetUtterances", "coverage",
                          "semanticReview")
            result = {key: copy.deepcopy(changed[key]) for key in fields}
            return {"id": f"new-response-{len(self.calls)}", "model": payload["model"],
                    "choices": [{"finish_reason": "stop",
                                 "message": {"content": json.dumps(result)}}]}

        updated = subject.run(f.source, f.anchor, f.policy, self.out,
                              "fixture-key", revised_call,
                              revision_brief=brief, reuse_from=previous)
        self.assertEqual([call["model"] for call in self.calls],
                         ["gpt-6.1-sol", "gpt-6.1-sol"])
        self.assertEqual(updated["groups"][0], old["groups"][0])
        for role in ("astra", "sol"):
            self.assertEqual((self.out / f"group-0001-{role}.json").read_bytes(),
                             (previous / f"group-0001-{role}.json").read_bytes())
            self.assertNotEqual(
                json.loads((self.out / f"group-0002-{role}.json").read_text())["payloadSha256"],
                json.loads((previous / f"group-0002-{role}.json").read_text())["payloadSha256"])

    def test_group_revision_rejects_changed_source_group_and_prior_text_before_calls(self):
        f = self.fixture
        previous = self.out.parent / "previous"
        old = subject.run(f.source, f.anchor, f.policy, previous,
                          "fixture-key", self.fake_call)
        self.calls.clear()
        changed = old["groups"][1]
        brief = {
            "schemaVersion": subject.REVISION_BRIEF_SCHEMA,
            "targetLocale": f.request["targetLocale"],
            "englishSourcePackageJsonSha256": f.request["englishSourcePackageJsonSha256"],
            "anchorManifestSha256": f.request["anchorManifestSha256"],
            "translationPolicySha256": f.request["translationPolicySha256"],
            "groups": [{"translationGroupId": changed["translationGroupId"],
                        "sourceUnitIds": changed["sourceUnitIds"],
                        "priorTargetTextSha256": "0" * 64,
                        "proposedTargetText": "A shorter translation."}],
        }
        with self.assertRaisesRegex(ValueError, "prior target text"):
            subject.run(f.source, f.anchor, f.policy, self.out,
                        "fixture-key", self.fake_call,
                        revision_brief=brief, reuse_from=previous)
        brief["groups"][0]["priorTargetTextSha256"] = hashlib.sha256(
            "".join(changed["targetUtterances"]).encode()).hexdigest()
        brief["groups"][0]["sourceUnitIds"] = ["wrong-unit"]
        with self.assertRaisesRegex(ValueError, "revision group"):
            subject.run(f.source, f.anchor, f.policy, self.out,
                        "fixture-key", self.fake_call,
                        revision_brief=brief, reuse_from=previous)
        brief["groups"][0]["sourceUnitIds"] = changed["sourceUnitIds"]
        brief["englishSourcePackageJsonSha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "source or policy changed"):
            subject.run(f.source, f.anchor, f.policy, self.out,
                        "fixture-key", self.fake_call,
                        revision_brief=brief, reuse_from=previous)
        self.assertFalse(self.calls)
        self.assertFalse(self.out.exists())

    def test_partial_repair_reuses_successful_cache_from_incomplete_run(self):
        f = self.fixture
        previous = self.out.parent / "incomplete"
        failed_id = subject.group_plan(f.request, f.anchor)[1]["translationGroupId"]

        def failing(api_key, payload):
            response = self.fake_call(api_key, payload)
            group_id = json.loads(payload["messages"][1]["content"])["translationGroupId"]
            if payload["reasoning_effort"] == "medium" and group_id == failed_id:
                result = json.loads(response["choices"][0]["message"]["content"])
                result["semanticReview"]["status"] = "fail"
                result["semanticReview"]["checks"]["quotationAttribution"] = "fail"
                result["semanticReview"]["issues"] = ["Misread a paraphrase as a quote"]
                response["choices"][0]["message"]["content"] = json.dumps(result)
            return response

        with self.assertRaisesRegex(ValueError, "Sol flagged group"):
            subject.run(f.source, f.anchor, f.policy, previous,
                        "fixture-key", failing)
        self.assertFalse((previous / "evidence.json").exists())
        old_failed_bytes = (previous / "group-0002-sol.json").read_bytes()
        brief = {
            "schemaVersion": subject.PARTIAL_REPAIR_SCHEMA,
            "targetLocale": f.request["targetLocale"],
            "englishSourcePackageJsonSha256": f.request["englishSourcePackageJsonSha256"],
            "anchorManifestSha256": f.request["anchorManifestSha256"],
            "translationPolicySha256": f.request["translationPolicySha256"],
            "groups": [{
                "translationGroupId": failed_id,
                "sourceUnitIds": f.evidence["groups"][1]["sourceUnitIds"],
                "failedRole": "reviewer",
                "failedCacheSha256": hashlib.sha256(old_failed_bytes).hexdigest(),
                "failureReason": "Sol confused indirect description with a direct quote",
                "instruction": "Treat this sentence as the speaker's paraphrase.",
            }],
        }
        calls = []

        def repaired(api_key, payload):
            self.assertEqual(api_key, "fixture-key")
            calls.append(payload)
            data = json.loads(payload["messages"][1]["content"])
            self.assertEqual(data["translationGroupId"], failed_id)
            self.assertEqual(data["partialRepair"]["instruction"],
                             "Treat this sentence as the speaker's paraphrase.")
            self.assertIn("speaker's paraphrase", payload["messages"][0]["content"])
            group = f.evidence["groups"][1]
            keys = ["translationGroupId", "sourceUnitIds", "targetUtterances", "coverage"]
            if payload["reasoning_effort"] == "medium":
                keys.append("semanticReview")
            result = {key: copy.deepcopy(group[key]) for key in keys}
            result["translationGroupId"] = failed_id
            return {"id": f"repaired-{len(calls)}", "model": payload["model"],
                    "choices": [{"finish_reason": "stop",
                                 "message": {"content": json.dumps(result)}}]}

        evidence = subject.run(f.source, f.anchor, f.policy, self.out,
                               "fixture-key", repaired,
                               reuse_from=previous, partial_repair_brief=brief)
        self.assertEqual([call["model"] for call in calls],
                         ["gpt-6.1-sol", "gpt-6.1-sol"])
        self.assertEqual((previous / "group-0002-sol.json").read_bytes(), old_failed_bytes)
        for role in ("astra", "sol"):
            self.assertEqual((self.out / f"group-0001-{role}.json").read_bytes(),
                             (previous / f"group-0001-{role}.json").read_bytes())
            self.assertNotEqual(
                json.loads((self.out / f"group-0002-{role}.json").read_text())["payloadSha256"],
                json.loads((previous / f"group-0002-{role}.json").read_text())["payloadSha256"])
        self.assertEqual(len(evidence["groups"]), 2)
        self.assertTrue((self.out / "evidence.json").exists())

    def test_partial_repair_rejects_stale_failed_cache_before_calls(self):
        f = self.fixture
        previous = self.out.parent / "incomplete"
        with self.assertRaisesRegex(ValueError, "Sol flagged group"):
            subject.run(f.source, f.anchor, f.policy, previous,
                        "fixture-key", lambda key, payload: self._first_group_fail(key, payload))
        self.calls.clear()
        first = subject.group_plan(f.request, f.anchor)[0]
        brief = {
            "schemaVersion": subject.PARTIAL_REPAIR_SCHEMA,
            "targetLocale": f.request["targetLocale"],
            "englishSourcePackageJsonSha256": f.request["englishSourcePackageJsonSha256"],
            "anchorManifestSha256": f.request["anchorManifestSha256"],
            "translationPolicySha256": f.request["translationPolicySha256"],
            "groups": [{"translationGroupId": first["translationGroupId"],
                        "sourceUnitIds": first["sourceUnitIds"],
                        "failedRole": "reviewer", "failedCacheSha256": "0" * 64,
                        "failureReason": "old machine failure",
                        "instruction": "Review the English source again."}],
        }
        with self.assertRaisesRegex(ValueError, "failed cache is missing or changed"):
            subject.run(f.source, f.anchor, f.policy, self.out,
                        "fixture-key", self.fake_call,
                        reuse_from=previous, partial_repair_brief=brief)
        self.assertFalse(self.calls)
        self.assertFalse(self.out.exists())

    def test_partial_repair_continues_groups_missing_from_prior_run(self):
        f = self.fixture
        previous = self.out.parent / "incomplete"
        with self.assertRaisesRegex(ValueError, "Sol flagged group"):
            subject.run(f.source, f.anchor, f.policy, previous,
                        "fixture-key", self._first_group_fail)
        self.assertFalse((previous / "group-0002-astra.json").exists())
        failed = previous / "group-0001-sol.json"
        first = subject.group_plan(f.request, f.anchor)[0]
        brief = {
            "schemaVersion": subject.PARTIAL_REPAIR_SCHEMA,
            "targetLocale": f.request["targetLocale"],
            "englishSourcePackageJsonSha256": f.request["englishSourcePackageJsonSha256"],
            "anchorManifestSha256": f.request["anchorManifestSha256"],
            "translationPolicySha256": f.request["translationPolicySha256"],
            "groups": [{"translationGroupId": first["translationGroupId"],
                        "sourceUnitIds": first["sourceUnitIds"],
                        "failedRole": "reviewer",
                        "failedCacheSha256": hashlib.sha256(failed.read_bytes()).hexdigest(),
                        "failureReason": "old machine failure",
                        "instruction": "Review the English source again."}],
        }
        self.calls.clear()
        result = subject.run(f.source, f.anchor, f.policy, self.out,
                             "fixture-key", self.fake_call,
                             reuse_from=previous, partial_repair_brief=brief)
        self.assertEqual([call["model"] for call in self.calls],
                         ["gpt-6.1-sol", "gpt-6.1-sol"] * 2)
        self.assertEqual(len(result["groups"]), 2)
        self.assertTrue((self.out / "evidence.json").exists())

    def test_partial_repair_carries_previous_revision_and_resumes_paid_attempt(self):
        f = self.fixture
        base = self.out.parent / "base"
        first = subject.run(f.source, f.anchor, f.policy, base,
                            "fixture-key", self.fake_call)
        first_group = first["groups"][0]
        revision = {
            "schemaVersion": subject.REVISION_BRIEF_SCHEMA,
            "targetLocale": f.request["targetLocale"],
            "englishSourcePackageJsonSha256": f.request["englishSourcePackageJsonSha256"],
            "anchorManifestSha256": f.request["anchorManifestSha256"],
            "translationPolicySha256": f.request["translationPolicySha256"],
            "groups": [{"translationGroupId": first_group["translationGroupId"],
                        "sourceUnitIds": first_group["sourceUnitIds"],
                        "priorTargetTextSha256": hashlib.sha256(
                            "".join(first_group["targetUtterances"]).encode()).hexdigest(),
                        "proposedTargetText": "A source-bound revised draft."}],
        }
        calls = []

        def by_input(api_key, payload):
            calls.append(payload)
            model_input = json.loads(payload["messages"][1]["content"])
            group = next(row for row in f.evidence["groups"]
                         if row["sourceUnitIds"] == model_input["sourceUnitIds"])
            keys = ["translationGroupId", "sourceUnitIds", "targetUtterances", "coverage"]
            if payload["reasoning_effort"] == "medium":
                keys.append("semanticReview")
            result = {key: copy.deepcopy(group[key]) for key in keys}
            result["translationGroupId"] = model_input["translationGroupId"]
            return {"id": f"later-{len(calls)}", "model": payload["model"],
                    "choices": [{"finish_reason": "stop",
                                 "message": {"content": json.dumps(result)}}]}

        prior = self.out.parent / "prior-revised"
        subject.run(f.source, f.anchor, f.policy, prior,
                    "fixture-key", by_input, revision_brief=revision, reuse_from=base)
        self.assertEqual(len(calls), 2)
        second_group = first["groups"][1]
        failed_cache = prior / "group-0002-sol.json"
        repair = {
            "schemaVersion": subject.PARTIAL_REPAIR_SCHEMA,
            "targetLocale": f.request["targetLocale"],
            "englishSourcePackageJsonSha256": f.request["englishSourcePackageJsonSha256"],
            "anchorManifestSha256": f.request["anchorManifestSha256"],
            "translationPolicySha256": f.request["translationPolicySha256"],
            "groups": [{"translationGroupId": second_group["translationGroupId"],
                        "sourceUnitIds": second_group["sourceUnitIds"],
                        "failedRole": "reviewer",
                        "failedCacheSha256": hashlib.sha256(failed_cache.read_bytes()).hexdigest(),
                        "failureReason": "Language plugin found a numeral format issue",
                        "instruction": "Keep the source number as digits."}],
        }
        attempt = self.out.parent / "paid-attempt"
        subject.run(f.source, f.anchor, f.policy, attempt,
                    "fixture-key", by_input,
                    reuse_from=prior, partial_repair_brief=repair)
        self.assertEqual(len(calls), 4)
        recovered = subject.run(
            f.source, f.anchor, f.policy, self.out, "fixture-key",
            lambda *_: self.fail("completed paid responses must be reused"),
            reuse_from=prior, partial_repair_brief=repair,
            resume_cache_from=attempt)
        self.assertEqual(len(recovered["groups"]), 2)
        for role in ("astra", "sol"):
            self.assertEqual((self.out / f"group-0001-{role}.json").read_bytes(),
                             (prior / f"group-0001-{role}.json").read_bytes())
            self.assertEqual((self.out / f"group-0002-{role}.json").read_bytes(),
                             (attempt / f"group-0002-{role}.json").read_bytes())

    def _first_group_fail(self, api_key, payload):
        response = self.fake_call(api_key, payload)
        if payload["reasoning_effort"] == "medium":
            result = json.loads(response["choices"][0]["message"]["content"])
            result["semanticReview"]["status"] = "fail"
            result["semanticReview"]["issues"] = ["Unresolved concern"]
            response["choices"][0]["message"]["content"] = json.dumps(result)
        return response

    def test_coverage_tolerates_only_whitespace_at_utterance_boundary(self):
        self.assertTrue(subject._coverage_substring(
            "다시 데웁니다. 차가운 것이", "다시 데웁니다.차가운 것이"))
        self.assertFalse(subject._coverage_substring(
            "다시 데웁니다. 뜨거운 것이", "다시 데웁니다.차가운 것이"))


if __name__ == "__main__":
    unittest.main()
