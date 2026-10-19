"""Layer 2 revision by group ID through the canonical worker; every model reply is synthetic.

No paid, remote or Spark stage runs here: the worker gets an injected caller and no budget.
"""
from contextlib import contextmanager
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.text import controller as subject
from scripts import canonical_durable_jobs as durable
from tools.ops import record_decision
from tongxing_production.orchestration import jobs
from scripts import build_english_source_package as english_source
from scripts import produce_target_language_candidate as producer
from tongxing_production.source import sentence_interpretation as interpretation
from scripts import target_language_policy as policy_tools
from tests import test_build_english_source_package as source_fixtures
from tongxing_production.text import auto_repair, group_revision, policy_preview

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = '''PLUGIN_ID = "zh-Hans-sermon-v1"
PLUGIN_VERSION = "{version}"

def review_group(policy, english_units, group):
    status = "fail" if any(mark in group["targetText"] for mark in {marks!r}) else "pass"
    return [{{"checkId": check, "status": status,
              "evidence": "Deterministic fixture check for " + group["translationGroupId"]}}
            for check in policy["languageReview"]["requiredChecks"]]
'''
PASSING_REVIEW = {"status": "pass", "checks": {"completeMeaning": "pass", "negationsNumbersNames": "pass",
                                               "quotationAttribution": "pass", "noAddedMeaning": "pass"},
                  "evidence": "Independent model review record for this group.", "uncertainty": [], "issues": []}


class RevisionFixture:
    """A frozen source of ``units`` sentences, its policy and a prior candidate, on disk."""

    def __init__(self, test, units, *, marks=("禁",), prior_texts=None):
        temporary = tempfile.TemporaryDirectory()
        test.addCleanup(temporary.cleanup)
        self.test, self.root = test, Path(temporary.name)
        self.plugin = self.root / "plugins" / "zh_review_plugin.py"
        self.plugin.parent.mkdir()
        self.plugin.write_text(PLUGIN.format(version="test-v1", marks=list(marks)), encoding="utf-8")
        source = source_fixtures.EnglishSourcePackageTests()
        source.setUp()
        test.addCleanup(source.doCleanups)
        segments = []
        for index in range(units):
            words = ["Remember", "the", "first", "love", "again", f"line{index}."]
            start = index * 3.0
            segments.append({"id": index, "referenceChunkId": "block-1", "text": " ".join(words),
                             "start": start, "end": start + len(words) * .3,
                             "sentenceBoundarySource": "frozen_reference_punctuation",
                             "wordTimes": [{"text": word, "start": start + n * .3, "end": start + (n + 1) * .3}
                                           for n, word in enumerate(words)]})
        source_fixtures.write_json(source.segments_path, segments)
        self.anchor = interpretation.build_anchor_manifest(segments, source_path=source.segments_path,
                                                           unit_policy=interpretation.UNIT_POLICY_V2)
        source_fixtures.write_json(source.manifest_path, self.anchor)
        review_path = source.root / "synthetic-review.json"
        source_fixtures.write_json(review_path, {
            "schemaVersion": english_source.REVIEW_SCHEMA_VERSION,
            "alignedSegmentsSha256": english_source.file_sha256(source.segments_path),
            "anchorManifestJsonSha256": interpretation.json_sha256(self.anchor),
            "humanApproval": True, "reviewedBy": "Synthetic fixture reviewer",
            "reviewedAt": "2026-09-30T00:00:00Z",
            "reviewedSourceUnitIds": [u["sourceUnitId"] for u in self.anchor["sourceUnits"]],
            "checks": {name: "approved" for name in english_source.APPROVED_CHECKS}})
        self.source = source.build(review_path=review_path)
        self.policy = self.freeze_policy()
        self.request = producer.prepare_request(self.source, self.anchor, self.policy)
        self.plan = subject.models.group_plan(self.request, self.anchor)
        self.prior_texts = prior_texts or {}
        evidence = copy.deepcopy(self.request)
        evidence["groups"] = [self.evidence_row(index, group) for index, group in enumerate(self.plan, 1)]
        evidence["generation"] = {role: {"model": self.policy[role]["model"],
                                         "promptVersion": self.policy[role]["promptVersion"],
                                         "requestIds": [row[f"{role}RequestId"] for row in evidence["groups"]]}
                                  for role in ("translator", "reviewer")}
        sha = producer.plugin_implementation_sha256(self.plugin)
        receipt = producer.run_language_plugin(self.source, self.anchor, self.policy, self.request, evidence,
                                               self.plugin, sha)
        self.prior = producer.admit_evidence(self.source, self.anchor, self.policy, self.request, evidence,
                                             receipt, self.plugin, sha)
        self.prior_path = self.root / "text" / "zh-Hans" / "candidate.json"
        self.prior_path.parent.mkdir(parents=True)
        self.prior_path.write_text(json.dumps(self.prior, ensure_ascii=False), encoding="utf-8")
        self.prior_rules_path = self.root / "text" / "zh-Hans" / "rule-preflight.json"
        self.prior_rules_path.write_text(json.dumps(subject.rule_preflight.preflight(
            self.request, self.policy, self.plugin, self.plan), ensure_ascii=False), encoding="utf-8")
        self.prior_policy_path = self.root / "text" / "zh-Hans" / "policy.json"
        self.prior_policy_path.write_text(json.dumps(self.policy, ensure_ascii=False), encoding="utf-8")
        self.write_inputs()

    def freeze_policy(self):
        policy = json.loads((ROOT / "config/target-language-policies/zh-Hans.json").read_text(encoding="utf-8"))
        policy.pop("componentSha256")
        policy["schemaVersion"] = policy_tools.POLICY_V2
        policy["sourceScope"] = {"englishSourcePackageJsonSha256": interpretation.json_sha256(self.source),
                                 "anchorManifestSha256": interpretation.json_sha256(self.anchor),
                                 "usedSeriesNames": [], "usedProperNames": [], "termApprovalEvidence": []}
        policy["languageReview"]["implementationStatus"] = "verified"
        policy["languageReview"]["pluginImplementationSha256"] = producer.plugin_implementation_sha256(self.plugin)
        return policy_tools.freeze_policy(policy)

    def text(self, index, group):
        return self.prior_texts.get(index, [f"第{index}组第{n}句。" for n in range(len(group["sourceUnitIds"]))])

    def evidence_row(self, index, group):
        utterances = self.text(index, group)
        if len(utterances) != len(group["sourceUnitIds"]):
            utterances = [utterances[0]] * len(group["sourceUnitIds"])
        return {"translationGroupId": group["translationGroupId"], "sourceUnitIds": group["sourceUnitIds"],
                "targetUtterances": utterances,
                "coverage": [{"sourceUnitId": unit, "targetText": text}
                             for unit, text in zip(group["sourceUnitIds"], utterances)],
                "semanticReview": copy.deepcopy(PASSING_REVIEW),
                "translatorRequestId": f"prior-translate-{index}", "reviewerRequestId": f"prior-review-{index}"}

    def write_inputs(self):
        for name, value in (("source", self.source), ("anchor", self.anchor), ("policy", self.policy)):
            (self.root / f"{name}.json").write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        (self.root / "inspection.json").write_text(json.dumps({
            "schemaVersion": subject.packages.SCHEMA, "source": "source.json", "anchor": "anchor.json",
            "locales": {"zh-Hans": {"policy": "policy.json"}}}), encoding="utf-8")

    def change_plugin(self, marks, version="test-v2"):
        """Freeze a new policy for a plugin that also rejects ``marks``: a plugin-only migration."""
        self.plugin.write_text(PLUGIN.format(version=version, marks=list(marks)), encoding="utf-8")
        self.policy = self.freeze_policy()
        self.write_inputs()

    def decide(self, governs=None):
        run = self.root / "run"
        row = record_decision.record(run, question="Which es/zh groups need revision?",
                                     choice="Revise the listed groups only", decided_by="Operator (chat)",
                                     governs=[str(governs or self.prior_path)],
                                     evidence=["operator listed group numbers"])
        return run / record_decision.FILE_NAME, policy_tools.canonical_sha256(row)

    def revision_request(self, groups, *, decision=None, **extra):
        decisions, row_sha = decision or self.decide()
        path = self.root / "revision" / "zh-Hans.json"
        path.parent.mkdir(exist_ok=True)
        value = {"schemaVersion": group_revision.REQUEST_SCHEMA, "targetLocale": "zh-Hans",
                 "priorCandidate": "../text/zh-Hans/candidate.json", "groups": groups,
                 "decision": {"decisionsFile": str(decisions), "rowSha256": row_sha}, **extra}
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return path

    def execution(self, *, workers=4):
        path = self.root / "execution.json"
        path.write_text(json.dumps({
            "schemaVersion": subject.GROUP_REVISION_SCHEMA, "productionRunId": "a" * 64,
            "inspectionConfig": "inspection.json", "jobRoot": "jobs",
            "locales": {"zh-Hans": {"outputDirectory": "text-r2/zh-Hans", "plugin": str(self.plugin)}},
            "layer2AutoRepair": {"routingVersion": auto_repair.ROUTING_VERSION, "groupWorkers": workers,
                                 "maxActiveLocales": 1},
            "layer2GroupRevision": {"zh-Hans": "revision/zh-Hans.json"}}), encoding="utf-8")
        return path

    @property
    def output(self):
        return self.root / "text-r2" / "zh-Hans"

    @contextmanager
    def active(self, path):
        config = subject.load_configuration(path)
        view = subject.package_view(config)
        ident = durable.identity(view, config.run_id, "text.zh-Hans")
        key, code = jobs._digest(ident), subject.code_identity()
        command = subject._worker_command(config, "zh-Hans", key, code)
        request = {"schemaVersion": jobs.SCHEMA, "jobId": key, "identity": ident, "command": command,
                   "commandSha256": jobs._digest(command), "timeoutSeconds": 21600.0,
                   "livenessPolicy": subject.LIVENESS_POLICY}
        with jobs._lock(config.job_root, key) as (folder, _, held):
            self.test.assertTrue(held)
            folder.mkdir()
            jobs._persist(folder / "request.json", request)
            jobs._persist(folder / "state.json", {"schemaVersion": jobs.SCHEMA, "jobId": key, "status": "running",
                                                  "requestSha256": jobs._digest(request)})
            yield config, code, key

    def run_worker(self, caller, path=None):
        path = path or self.execution()
        with patch.object(auto_repair, "_repair_token_bound", return_value=100), \
                self.active(path) as (config, code, key):
            return subject.execute(path, "zh-Hans", config.sha256, code, key, caller=caller, api_key="fixture-key")


class Models:
    """Synthetic translator/reviewer: listed groups get new text; ``fail_first`` fail one review."""

    def __init__(self, fail_first=(), hold_for=0):
        self.calls, self.lock = [], threading.Lock()
        self.fail_first, self.failed = set(fail_first), set()
        self.active = self.peak = 0
        self.overlapped = threading.Event()
        self.hold_for = hold_for

    def __call__(self, key, payload):
        data = json.loads(payload["messages"][1]["content"])
        with self.lock:
            self.calls.append(payload)
            self.active += 1
            self.peak = max(self.peak, self.active)
            if self.active >= 2:
                self.overlapped.set()
        if self.hold_for:
            self.overlapped.wait(self.hold_for)
        try:
            reviewer = payload["reasoning_effort"] == "medium"
            utterances = [f"修订{data['translationGroupId']}第{n}句。" for n in range(len(data["sourceUnitIds"]))]
            answer = {"translationGroupId": data["translationGroupId"], "sourceUnitIds": data["sourceUnitIds"],
                      "targetUtterances": utterances,
                      "coverage": [{"sourceUnitId": unit, "targetText": text}
                                   for unit, text in zip(data["sourceUnitIds"], utterances)]}
            if reviewer:
                answer["semanticReview"] = copy.deepcopy(PASSING_REVIEW)
                with self.lock:
                    fail = data["translationGroupId"] in self.fail_first - self.failed
                    if fail:
                        self.failed.add(data["translationGroupId"])
                if fail:
                    answer["semanticReview"]["status"] = "fail"
                    answer["semanticReview"]["checks"]["completeMeaning"] = "fail"
                    answer["semanticReview"]["issues"] = ["Dropped the second clause"]
            with self.lock:
                number = len(self.calls)
            return {"id": f"revision-response-{number}-{data['translationGroupId']}-{payload['reasoning_effort']}",
                    "model": payload["model"], "usage": {"prompt_tokens": 60, "completion_tokens": 40},
                    "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(answer)}}]}
        finally:
            with self.lock:
                self.active -= 1

    def groups(self):
        return [json.loads(p["messages"][1]["content"])["translationGroupId"] for p in self.calls]


class GroupIdInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = RevisionFixture(self, 6)

    def load(self, groups, **extra):
        return group_revision.load_request(self.fixture.revision_request(groups, **extra))

    def test_numbers_ids_and_notes_resolve_to_plan_groups(self):
        plan = self.fixture.plan
        loaded = self.load([5, {"group": plan[1]["translationGroupId"], "note": " 数字要按英文说 "}, {"group": 3}])
        rules = subject.rule_preflight.preflight(self.fixture.request, self.fixture.policy, self.fixture.plugin, plan)
        prepared = group_revision.prepare(loaded, self.fixture.source, self.fixture.anchor, self.fixture.policy,
                                          self.fixture.plugin, rules)
        self.assertEqual([(row["group"], row["note"]) for row in prepared["listed"]],
                         [(2, "数字要按英文说"), (3, None), (5, None)])
        self.assertEqual([row["translationGroupId"] for row in prepared["brief"]["revise"]],
                         [plan[1]["translationGroupId"], plan[2]["translationGroupId"], plan[4]["translationGroupId"]])
        self.assertEqual(len(prepared["brief"]["carry"]), len(plan) - 3)
        self.assertEqual(prepared["policyChange"]["classification"], "unchanged")

    def test_malformed_unknown_and_duplicate_groups_are_refused(self):
        for groups in ([], [0], [-1], [True], [{"group": 1, "extra": 1}], [{"group": 1, "note": ""}], ["",]):
            with self.subTest(groups=groups), self.assertRaisesRegex(ValueError, "invalid_group_revision_request"):
                self.load(groups)
        rules = subject.rule_preflight.preflight(self.fixture.request, self.fixture.policy, self.fixture.plugin,
                                                 self.fixture.plan)
        for groups, reason in (([7], "group_revision_unknown_group"), (["nope"], "group_revision_unknown_group"),
                               ([1, self.fixture.plan[0]["translationGroupId"]], "group_revision_duplicate_group")):
            with self.subTest(groups=groups), self.assertRaisesRegex(ValueError, reason):
                group_revision.prepare(self.load(groups), self.fixture.source, self.fixture.anchor,
                                       self.fixture.policy, self.fixture.plugin, rules)

    def test_decision_must_be_an_artifact_bound_row_for_the_prior_candidate(self):
        rules = subject.rule_preflight.preflight(self.fixture.request, self.fixture.policy, self.fixture.plugin,
                                                 self.fixture.plan)
        other = self.fixture.root / "other.json"
        other.write_text("{}")
        for decision, reason in ((self.fixture.decide(governs=other), "does_not_govern_prior_candidate"),
                                 ((self.fixture.decide()[0], "0" * 64), "group_revision_decision_row_missing")):
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                group_revision.prepare(self.load([1], decision=decision), self.fixture.source, self.fixture.anchor,
                                       self.fixture.policy, self.fixture.plugin, rules)
        unbound = record_decision.record(self.fixture.root / "run", question="q", choice="c", decided_by="me")
        with self.assertRaisesRegex(ValueError, "does_not_govern_prior_candidate"):
            group_revision.prepare(
                self.load([1], decision=(self.fixture.root / "run" / record_decision.FILE_NAME,
                                         policy_tools.canonical_sha256(unbound))),
                self.fixture.source, self.fixture.anchor, self.fixture.policy, self.fixture.plugin, rules)

    def test_runner_brief_must_list_or_carry_every_group_once(self):
        rules = subject.rule_preflight.preflight(self.fixture.request, self.fixture.policy, self.fixture.plugin,
                                                 self.fixture.plan)
        brief = group_revision.prepare(self.load([2]), self.fixture.source, self.fixture.anchor, self.fixture.policy,
                                       self.fixture.plugin, rules)["brief"]
        validate = subject.models.validate_operator_revision
        revise, carry = validate(brief, self.fixture.request, self.fixture.plan)
        self.assertEqual((len(revise), len(carry)), (1, 5))
        broken = []
        dropped = copy.deepcopy(brief)
        dropped["carry"].pop()
        broken.append(dropped)
        failing = copy.deepcopy(brief)
        failing["carry"][0]["semanticReview"]["issues"] = ["open"]
        broken.append(failing)
        both = copy.deepcopy(brief)
        both["carry"].append(dict(both["carry"][0], translationGroupId=both["revise"][0]["translationGroupId"],
                                  sourceUnitIds=both["revise"][0]["sourceUnitIds"]))
        broken.append(both)
        tampered = copy.deepcopy(brief)
        tampered["revise"][0]["priorTargetText"] += "x"
        broken.append(tampered)
        for value in broken:
            with self.assertRaises(ValueError):
                validate(value, self.fixture.request, self.fixture.plan)


class AllowanceTests(unittest.TestCase):
    POLICY = {"translator": {"model": "gpt-6.1-sol"}, "reviewer": {"model": "gpt-6.1-sol"}}
    LIMITS = {"schemaVersion": "provider-request-limits-v1", "maxInputTokens": 1000,
              "maxCompletionTokens": 1000, "wallTimeMs": 1000, "serviceTier": "default"}

    def setUp(self):
        from tongxing_production.compute import provider_limits
        self.LIMITS = dict(self.LIMITS, schemaVersion=provider_limits.SCHEMA)
        self.pair = sum(provider_limits._cost("gpt-6.1-sol", 1000, 1000) for _ in range(2))

    def test_sized_from_listed_groups_not_from_initial_calls(self):
        with patch.object(auto_repair, "_repair_token_bound", return_value=2000):
            allowance = group_revision.allowance(14, self.POLICY, None)
        self.assertEqual((allowance["pairs"], allowance["calls"], allowance["tokens"]), (28, 56, 112000))
        self.assertEqual(allowance["usdCap"], "not_bound")
        # The default 10% rule on a 14-group revision round (28 calls) would allow max(4, 3) calls: 2 groups.
        self.assertEqual(auto_repair.repair_caps({"calls": 28, "tokens": 2800}, 2000)[0], 4)
        self.assertEqual(auto_repair.repair_caps({"calls": 0, "tokens": 0}, 2000, allowance), (56, 112000))

    def test_usd_cap_from_the_authorization_bounds_the_allowance(self):
        from tongxing_production.text import budget
        with patch.object(auto_repair, "_repair_token_bound", return_value=2000), \
                budget.request_limits(self.LIMITS):
            ample = group_revision.allowance(3, self.POLICY, self.pair * 100)
            tight = group_revision.allowance(3, self.POLICY, self.pair * 5 + self.pair // 2)
            spent = group_revision.allowance(3, self.POLICY, self.pair * 2)
        self.assertEqual((ample["pairs"], ample["usdCap"]), (6, "budget_authorization"))
        self.assertEqual(tight["pairs"], 2)  # 5 affordable pairs, 3 reserved for the first revision
        self.assertEqual(spent["pairs"], 0)
        self.assertEqual(ample["worstCasePairCostMicrousd"], self.pair)
        with self.assertRaisesRegex(ValueError, "needs_bounded_cost"):
            group_revision.allowance(3, self.POLICY, 10)  # a USD cap without bound request limits


class PolicyChangeTests(unittest.TestCase):
    def test_only_plugin_and_approval_fields_may_change(self):
        fixture = RevisionFixture(self, 2)
        old = fixture.policy
        fixture.change_plugin(["禁", "糟"])
        self.assertEqual(policy_preview.classify_policy_change(old, fixture.policy)["classification"],
                         "plugin_only_migration")
        changed = copy.deepcopy(old)
        changed["translator"]["promptVersion"] = "other"
        self.assertEqual(policy_preview.classify_policy_change(old, changed)["classification"], "content_modified")
        self.assertEqual(policy_preview.classify_policy_change(old, old)["classification"], "unchanged")


class WorkerRevisionTests(unittest.TestCase):
    def test_plugin_change_gates_unlisted_failures_before_any_call(self):
        fixture = RevisionFixture(self, 8, prior_texts={3: ["这组很糟。"], 6: ["也糟。"]})
        old_policy = fixture.policy
        fixture.change_plugin(["禁", "糟"])
        models = Models()
        fixture.revision_request([3])
        path = fixture.execution()
        tick = subject.Controller(path).tick()  # read-only shadow
        self.assertEqual((tick["status"], tick["reasonCode"], tick["dispatched"]),
                         ("blocked", "group_revision_policy_changed_requires_prior_policy_and_rule_preflight", False))
        fixture.revision_request([3], priorPolicy="../text/zh-Hans/policy.json",
                                 priorRulePreflight="../text/zh-Hans/rule-preflight.json")
        for mode in subject.MODES:
            tick = subject.Controller(path, mode=mode).tick()
            self.assertEqual((tick["status"], tick["reasonCode"], tick["dispatched"]),
                             ("blocked", "group_revision_unlisted_groups_fail_current_checks", False))
            self.assertEqual(tick["groupRevision"]["unlistedFailures"],
                             [{"group": 6, "translationGroupId": fixture.plan[5]["translationGroupId"],
                               "reasons": ["language_plugin_failed"]}])
        self.assertFalse((fixture.root / "jobs").exists() and any((fixture.root / "jobs").iterdir()))
        # The worker repeats the gate before any call and leaves the report beside the lane.
        with self.assertRaisesRegex(ValueError, "group_revision_unlisted_groups_fail_current_checks: 6"):
            fixture.run_worker(models, path)
        self.assertEqual(models.calls, [])
        self.assertFalse((fixture.output / "candidate.json").exists())
        gate = json.loads((fixture.output / "group-revision-plugin-gate.json").read_text())
        self.assertEqual([(row["group"], row["listed"]) for row in gate["pluginFailures"]], [(3, True), (6, False)])
        self.assertEqual((gate["priorPolicySha256"], gate["modelCalls"]),
                         (policy_tools.canonical_sha256(old_policy), 0))
        # Production never reaches this failed job: the ticks above refuse dispatch. Start clean here.
        shutil_rmtree(fixture.root / "jobs")

        # The operator adds group 6: the revision now runs and binds both policy hashes honestly.
        fixture.revision_request([3, {"group": 6, "note": "去掉“糟”"}], priorPolicy="../text/zh-Hans/policy.json",
                                 priorRulePreflight="../text/zh-Hans/rule-preflight.json")
        shutil_rmtree(fixture.output)
        self.assertEqual(subject.Controller(path).tick()["reasonCode"], "shadow_only")
        result = fixture.run_worker(models, path)
        self.assertEqual(result["status"], "machine_review_pass_human_review_pending")
        self.assertEqual(sorted(set(models.groups())), [fixture.plan[2]["translationGroupId"],
                                                        fixture.plan[5]["translationGroupId"]])
        receipt = json.loads((fixture.output / "group-revision-receipt.json").read_text())
        self.assertEqual(receipt["policyChange"]["classification"], "plugin_only_migration")
        self.assertEqual(receipt["priorPolicySha256"], policy_tools.canonical_sha256(old_policy))
        self.assertEqual(receipt["translationPolicySha256"], policy_tools.canonical_sha256(fixture.policy))
        self.assertEqual(receipt["ruleChange"]["changedKeys"], [])
        note_prompt = next(json.loads(p["messages"][1]["content"]) for p in models.calls
                           if json.loads(p["messages"][1]["content"])["translationGroupId"]
                           == fixture.plan[5]["translationGroupId"])
        self.assertEqual(note_prompt["operatorRevision"]["note"], "去掉“糟”")
        self.assertEqual(note_prompt["operatorRevision"]["priorTargetText"], "也糟。")
        candidate = json.loads((fixture.output / "candidate.json").read_text())
        self.assertTrue(all(group["languageReview"]["policySha256"] != fixture.prior["groups"][0]["languageReview"]
                            ["policySha256"] for group in candidate["groups"]))

    def test_model_facing_policy_change_is_refused(self):
        fixture = RevisionFixture(self, 3)
        policy = copy.deepcopy(fixture.policy)
        policy.pop("componentSha256")
        policy["translator"]["promptVersion"] += "-changed"
        fixture.policy = policy_tools.freeze_policy(policy)
        fixture.write_inputs()
        fixture.revision_request([1], priorPolicy="../text/zh-Hans/policy.json",
                                 priorRulePreflight="../text/zh-Hans/rule-preflight.json")
        models = Models()
        with self.assertRaisesRegex(ValueError, "group_revision_model_facing_policy_changed"):
            fixture.run_worker(models)
        self.assertEqual(models.calls, [])

    def test_listed_groups_run_in_parallel_and_repairs_use_the_listed_allowance(self):
        fixture = RevisionFixture(self, 12)
        listed = [2, 5, 9]
        ids = [fixture.plan[index - 1]["translationGroupId"] for index in listed]
        fixture.revision_request(listed)
        # Every listed group fails its first review. The 10% rule would afford 2 of 3 repairs
        # (max(4, 10% of 6) calls); the allowance sized from the list affords all three.
        models = Models(fail_first=ids, hold_for=5)
        result = fixture.run_worker(models)
        self.assertEqual(result["status"], "machine_review_pass_human_review_pending")
        self.assertGreaterEqual(models.peak, 2)
        self.assertEqual(len(models.calls), 12)
        self.assertEqual(sorted(models.groups()), sorted(ids * 4))
        allowance = json.loads((fixture.output / "group-revision-allowance.json").read_text())
        self.assertEqual((allowance["pairs"], allowance["calls"]), (6, 12))
        repair = json.loads(sorted((fixture.output / "repair-rounds").glob("auto-repair-receipt-*.json"))[-1]
                            .read_text())
        self.assertEqual((repair["status"], repair["repairSpend"]["calls"]), ("all_groups_passed", 6))
        self.assertEqual(repair["repairAllowance"], allowance)
        self.assertIn("groupRevisionSha256", repair["lineage"])


class EndToEndTests(unittest.TestCase):
    def test_three_of_about_four_hundred_groups_are_revised_and_nothing_else_is_called(self):
        fixture = RevisionFixture(self, 402)
        self.assertGreaterEqual(len(fixture.plan), 380)
        listed = [24, 25, 86]
        ids = [fixture.plan[index - 1]["translationGroupId"] for index in listed]
        fixture.revision_request([24, {"group": 25, "note": "金额只说一次"}, 86])
        models = Models()
        result = fixture.run_worker(models, fixture.execution(workers=3))
        self.assertEqual(result["status"], "machine_review_pass_human_review_pending")
        self.assertFalse(result["releaseEligible"])
        # Exactly one translator and one reviewer call per listed group; zero for the other groups.
        self.assertEqual(len(models.calls), 6)
        self.assertEqual(sorted(models.groups()), sorted(ids * 2))
        candidate = json.loads((fixture.output / "candidate.json").read_text())
        self.assertEqual(result["candidateJsonSha256"], jobs._digest(candidate))
        self.assertEqual(candidate["schemaVersion"], "sermon-target-language-candidate-v2")
        self.assertEqual(candidate["status"], "machine_review_pass_human_review_pending")
        self.assertEqual(candidate["humanReview"], fixture.prior["humanReview"])
        prior = fixture.prior
        for index, (before, after) in enumerate(zip(prior["groups"], candidate["groups"]), 1):
            if index in listed:
                self.assertNotEqual(after["targetText"], before["targetText"])
            else:
                self.assertEqual(after, before)
        for role in ("translator", "reviewer"):
            new_ids, old_ids = candidate["generation"][role]["requestIds"], prior["generation"][role]["requestIds"]
            self.assertEqual([new for n, (new, old) in enumerate(zip(new_ids, old_ids), 1) if new != old],
                             [new_ids[index - 1] for index in listed])
        # The candidate passes the downstream validators with human approval still pending.
        subject.producer.handoff.validate_target_candidate(fixture.source, fixture.anchor, candidate,
                                                          require_human_approval=False)
        subject.producer.handoff.validate_policy_binding(candidate, fixture.policy)
        # The canonical package inspection validates it (the harness leaves its own durable job running).
        self.assertEqual(subject.package_view(subject.load_configuration(fixture.root / "execution.json"))
                         ["nodes"]["text.zh-Hans"]["status"], "validated")
        receipt = json.loads((fixture.output / "group-revision-receipt.json").read_text())
        self.assertEqual(result["groupRevisionReceiptSha256"], jobs._digest(receipt))
        self.assertEqual([row["group"] for row in receipt["revisedGroups"]], listed)
        self.assertEqual(len(receipt["carriedGroups"]), len(fixture.plan) - 3)
        self.assertEqual(receipt["priorCandidateJsonSha256"], policy_tools.canonical_sha256(prior))
        self.assertEqual(receipt["carriedFrom"]["modelCalls"], 0)
        carried = receipt["carriedGroups"][0]
        self.assertEqual(carried["priorGroupSha256"], policy_tools.canonical_sha256(prior["groups"][0]))
        self.assertEqual(receipt["revisedGroups"][1]["noteSha256"],
                         group_revision._text_sha256("金额只说一次"))
        decisions, row_sha = fixture.root / "run" / record_decision.FILE_NAME, receipt["operatorDecision"]["rowSha256"]
        self.assertEqual(policy_tools.canonical_sha256(json.loads(decisions.read_text().splitlines()[-1])), row_sha)
        self.assertEqual((receipt["humanApproval"], receipt["releaseEligible"]), (False, False))
        self.assertEqual(receipt["downstreamTextQc"], "required_on_final_candidate")
        # Only the listed groups left model files; carried groups wrote nothing in the round.
        round_files = sorted(path.name for path in (fixture.output / "repair-rounds" / "round-001").glob("group-*-sol.json"))
        self.assertEqual(round_files, [f"group-{index:04d}-sol.json" for index in listed])
        self.assertEqual(fixture.prior_path.read_text(), json.dumps(prior, ensure_ascii=False))


def shutil_rmtree(path):
    import shutil
    shutil.rmtree(path)


if __name__ == "__main__":
    unittest.main()
