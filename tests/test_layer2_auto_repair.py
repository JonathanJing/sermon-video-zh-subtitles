import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts import layer2_auto_repair as subject
from scripts import run_target_language_models as runner
from tests import test_run_target_language_models as runner_tests

PASS = {"status": "pass", "checks": {name: "pass" for name in subject.CHECK_CODES},
        "evidence": "ok", "uncertainty": [], "issues": []}
REQUEST = {"targetLocale": "ko", "englishSourcePackageJsonSha256": "a" * 64,
           "anchorManifestSha256": "b" * 64, "translationPolicySha256": "c" * 64}


def failing(*checks, uncertainty=(), issues=("problem",)):
    review = copy.deepcopy(PASS)
    review["status"] = "fail"
    for name in checks:
        review["checks"][name] = "fail"
    review["uncertainty"] = list(uncertainty)
    review["issues"] = list(issues)
    return review


class ClassificationTests(unittest.TestCase):
    def test_every_sol_failure_uncertainty_and_issue_starts_a_repair(self):
        self.assertEqual(subject.classify_review(failing("completeMeaning", "quotationAttribution")),
                         (["meaning_omission", "quotation_attribution_error"], "repair_translation"))
        self.assertEqual(subject.classify_review(failing("negationsNumbersNames")),
                         (["negation_number_name_error"], "repair_translation"))
        self.assertEqual(subject.classify_review(failing("completeMeaning", uncertainty=["unclear"])),
                         (["meaning_omission", "review_uncertainty"], "repair_translation"))
        self.assertEqual(subject.classify_review(failing()), (["review_issue_open"], "repair_translation"))

    def test_every_back_translation_qc_kind_has_a_repair_route(self):
        for kind, code in subject.QC_KIND_CODES.items():
            self.assertEqual(subject.ACTIONS[code], "repair_translation", kind)
            self.assertIn(code, subject.INSTRUCTIONS)

    def test_systemic_threshold_has_margin_over_isolated_errors(self):
        self.assertEqual(subject.systemic_threshold(46), 3)
        self.assertEqual(subject.systemic_threshold(474), 5)

    def test_shared_codes_route_like_the_repair_planner(self):
        from scripts import sermon_repair_planning as planning
        for code, action in subject.ACTIONS.items():
            if code in planning.FAILURE_ACTIONS:
                self.assertEqual(planning.FAILURE_ACTIONS[code], action, code)


class Fleet:
    """Synthetic runner: a script of per-round failures, with paid raw responses on disk."""

    def __init__(self, test, groups, script, tokens_per_call=100):
        self.test, self.groups, self.script = test, groups, script
        self.tokens = tokens_per_call
        self.calls = []

    def plan(self):
        return [{"translationGroupId": f"g{i}", "sourceUnitIds": [f"u{i}"]} for i in range(1, self.groups + 1)]

    def __call__(self, out, reuse_from, brief, collector):
        out.mkdir(parents=True)
        round_index = len(self.calls)
        repaired = {row["translationGroupId"] for row in brief["groups"]} if brief else None
        self.calls.append(sorted(repaired) if repaired is not None else "all")
        failures = self.script[round_index] if round_index < len(self.script) else {}
        for index, group in enumerate(self.plan(), 1):
            stem = f"group-{index:04d}"
            if reuse_from is not None and group["translationGroupId"] not in repaired:
                for suffix in ("-astra.raw.json", "-sol.raw.json", "-sol.json"):
                    (out / (stem + suffix)).write_bytes((reuse_from / (stem + suffix)).read_bytes())
            else:
                if collector.stopped():
                    collector.record_not_dispatched(index, group)
                    continue
                for role in ("astra", "sol"):
                    (out / f"{stem}-{role}.raw.json").write_text(json.dumps({
                        "response": {"id": f"{out.name}-{stem}-{role}", "usage": {"total_tokens": self.tokens}}}))
                (out / f"{stem}-sol.json").write_text(json.dumps({"round": out.name, "group": stem}))
            review = failures.get(group["translationGroupId"])
            if review == "plugin":
                collector.record_plugin_failure(index, group, {"checks": [
                    {"checkId": "number", "status": "fail", "evidence": "spelled number"}]}, out / f"{stem}-sol.json")
            elif review is not None:
                collector.record_review_failure(index, group, review, out / f"{stem}-sol.json")
        if collector.has_failures():
            collector.finish(out, REQUEST, self.plan())
        return {"groups": self.groups, "round": out.name}


class LoopTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def drive(self, fleet, out="runs"):
        return subject.drive(REQUEST, fleet.groups, fleet, self.root / out, self.root / f"state-{out}")

    def test_one_repair_then_release(self):
        fleet = Fleet(self, 46, [{"g21": failing("quotationAttribution")}])
        receipt = self.drive(fleet)
        self.assertEqual(receipt["status"], "all_groups_passed")
        self.assertEqual(fleet.calls, ["all", ["g21"]])
        self.assertEqual(receipt["repairSpend"]["calls"], 2)
        self.assertFalse(receipt["humanApproval"])
        self.assertEqual(receipt["ledgerRoot"], str((self.root / "state-runs").resolve()))

    def test_changing_failures_keep_repairing_while_they_shrink(self):
        fleet = Fleet(self, 46, [{"g1": failing("completeMeaning", "noAddedMeaning", "negationsNumbersNames")},
                                 {"g1": failing("completeMeaning", "quotationAttribution")},
                                 {"g1": failing("noAddedMeaning")}])
        receipt = self.drive(fleet)
        self.assertEqual(receipt["status"], "all_groups_passed")
        self.assertEqual(fleet.calls, ["all", ["g1"], ["g1"], ["g1"]])

    def test_repeated_fingerprint_stops_and_quotation_goes_to_source_review(self):
        fleet = Fleet(self, 46, [{"g21": failing("quotationAttribution")}] * 5)
        receipt = self.drive(fleet)
        self.assertEqual(receipt["status"], "repair_stopped")
        self.assertEqual(fleet.calls, ["all", ["g21"]])
        self.assertEqual(receipt["stoppedGroups"][0]["reasonCode"], "request_source_review")
        fleet = Fleet(self, 46, [{"g2": failing("completeMeaning")}] * 5)
        receipt = self.drive(fleet, out="other")
        self.assertEqual(receipt["stoppedGroups"][0]["reasonCode"], "repeated_failure_without_progress")

    def test_two_repairs_without_fewer_failures_stop(self):
        fleet = Fleet(self, 46, [{"g1": failing("completeMeaning")},
                                 {"g1": failing("noAddedMeaning")},
                                 {"g1": failing("negationsNumbersNames")},
                                 {"g1": failing("quotationAttribution")}])
        receipt = self.drive(fleet)
        self.assertEqual(fleet.calls, ["all", ["g1"], ["g1"]])
        self.assertEqual(receipt["stoppedGroups"][0]["reasonCode"], "no_fewer_failures_after_two_repairs")

    def test_systemic_failure_stops_dispatch_and_repairs_nothing(self):
        same = {f"g{i}": failing("negationsNumbersNames") for i in (2, 5, 9, 12)}
        fleet = Fleet(self, 46, [same])
        receipt = self.drive(fleet)
        self.assertEqual(fleet.calls, ["all"])
        self.assertEqual(receipt["repairSpend"]["calls"], 0)
        reasons = {row["reasonCode"] for row in receipt["stoppedGroups"]}
        self.assertEqual(reasons, {"systemic_rule_or_policy_issue", "not_dispatched_after_systemic_stop"})
        # Dispatch stopped after the third failure (group 9): groups 10..46 never ran.
        self.assertEqual(receipt["initialSpend"]["calls"], 9 * 2)

    def test_plugin_rejection_keeps_the_translation_and_costs_nothing(self):
        fleet = Fleet(self, 46, [{"g3": "plugin"}])
        receipt = self.drive(fleet)
        self.assertEqual(fleet.calls, ["all"])
        self.assertEqual(receipt["stoppedGroups"][0]["reasonCode"], "escalate_engineering")
        self.assertEqual(receipt["repairSpend"]["calls"], 0)

    def test_repeated_uncertainty_goes_to_a_person_and_spend_cap(self):
        fleet = Fleet(self, 46, [{"g4": failing(uncertainty=["which verse?"])}] * 3)
        receipt = self.drive(fleet)
        self.assertEqual(fleet.calls, ["all", ["g4"]])
        self.assertEqual(receipt["stoppedGroups"][0]["reasonCode"], "request_human_review")
        # 20 groups -> 40 initial calls -> cap max(4, 4) = 4 calls: two groups fit, three do not.
        fleet = Fleet(self, 20, [{f"g{i}": failing(name) for i, name in
                                  zip((1, 2, 3), ("completeMeaning", "noAddedMeaning", "quotationAttribution"))}])
        receipt = self.drive(fleet, out="capped")
        self.assertEqual(fleet.calls, ["all"])
        self.assertEqual({row["reasonCode"] for row in receipt["stoppedGroups"]}, {"repair_spend_cap"})

    def test_unknown_outcome_is_not_retried(self):
        def unknown(out, reuse_from, brief, collector):
            raise ValueError("Uncertain paid reviewer call; inspect before retry")
        with self.assertRaisesRegex(ValueError, "Uncertain paid"):
            subject.drive(REQUEST, 46, unknown, self.root / "runs", self.root / "state")
        self.assertEqual(subject.load_ledger(self.root / "state", subject.lineage(REQUEST)), [])

    def test_history_survives_a_new_output_directory(self):
        fleet = Fleet(self, 46, [{"g7": failing("completeMeaning")}])
        first = self.drive(fleet, out="first")
        self.assertEqual(first["status"], "all_groups_passed")
        # Another loop for the same source finds the chain already finished.
        again = Fleet(self, 46, [{"g7": failing("completeMeaning")}])
        receipt = subject.drive(REQUEST, 46, again, self.root / "second", self.root / "state-first")
        self.assertEqual(again.calls, [])
        self.assertEqual(receipt["rounds"], 2)
        # A broken chain is refused.
        folder = subject.ledger_directory(self.root / "state-first", subject.lineage(REQUEST))
        (folder / "round-000001.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "does not follow the chain"):
            subject.drive(REQUEST, 46, Fleet(self, 46, []), self.root / "third", self.root / "state-first")

    def test_regrouped_units_keep_their_fingerprints(self):
        value = subject.lineage(REQUEST)
        failure = {"translationGroupId": "renamed", "sourceUnitIds": ["u1", "u2"],
                   "failureCodes": ["meaning_omission"], "action": "repair_translation"}
        history = [{"round": 1, "repaired": True, "decisions": ["repairable_content_failure"],
                    "failureCodes": ["meaning_omission"],
                    "fingerprints": [subject.fingerprint(value, ["u1", "u2"], ["meaning_omission"])]}]
        self.assertEqual(subject.decide(failure, history, value)[0], "stop")


class RunnerCollectionTests(unittest.TestCase):
    """The real runner in failure-collection mode, on the two-group fixture."""

    def setUp(self):
        self.base = runner_tests.RunTargetLanguageModelsTests(methodName="test_formal_run_without_plugin_sends_nothing")
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.fixture, self.out, self.calls = self.base.fixture, self.base.out, self.base.calls
        self.production_run = self.base.production_run

    def fake_call(self, api_key, payload):
        """Answer by group id, so repair calls find their group too."""
        self.calls.append(payload)
        data = json.loads(payload["messages"][1]["content"])
        group = next(row for row in self.fixture.evidence["groups"]
                     if row["sourceUnitIds"] == data["sourceUnitIds"])
        keys = ["translationGroupId", "sourceUnitIds", "targetUtterances", "coverage"]
        if payload["reasoning_effort"] == "medium":
            keys.append("semanticReview")
        result = {key: copy.deepcopy(group[key]) for key in keys}
        result["translationGroupId"] = data["translationGroupId"]
        return {"id": f"response-{len(self.calls)}", "model": payload["model"],
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}]}

    def _quote_fail(self, api_key, payload):
        response = self.fake_call(api_key, payload)
        data = json.loads(payload["messages"][1]["content"])
        if payload["reasoning_effort"] == "medium" and data["translationGroupId"] == self.failed_id \
                and "partialRepair" not in data:
            result = json.loads(response["choices"][0]["message"]["content"])
            result["semanticReview"]["status"] = "fail"
            result["semanticReview"]["checks"]["quotationAttribution"] = "fail"
            result["semanticReview"]["issues"] = ["Misread a paraphrase as a quote"]
            response["choices"][0]["message"]["content"] = json.dumps(result)
        return response

    def test_collects_sol_failure_and_finishes_every_group(self):
        f = self.fixture
        self.failed_id = runner.group_plan(f.request, f.anchor)[0]["translationGroupId"]
        collector = subject.FailureCollector(2)
        with self.assertRaises(subject.GroupFailuresCollected) as raised:
            self.production_run(f.source, f.anchor, f.policy, self.out, "fixture-key", self._quote_fail,
                                failure_collector=collector)
        self.assertEqual(len(self.calls), 4)  # the second group still ran
        report = raised.exception.report
        self.assertEqual([row["failureCodes"] for row in report["failures"]], [["quotation_attribution_error"]])
        self.assertFalse((self.out / "evidence.json").exists())
        self.assertFalse((self.out / "plugin-group-stop.json").exists())

    def test_default_mode_still_stops_at_the_first_failure(self):
        f = self.fixture
        self.failed_id = runner.group_plan(f.request, f.anchor)[0]["translationGroupId"]
        with self.assertRaisesRegex(ValueError, "Sol flagged group"):
            self.production_run(f.source, f.anchor, f.policy, self.out, "fixture-key", self._quote_fail)
        self.assertEqual(len(self.calls), 2)

    def test_plugin_rejection_is_collected_without_a_stop_receipt(self):
        f = self.fixture
        blocked = runner.group_plan(f.request, f.anchor)[0]["translationGroupId"]

        def caller(api_key, payload):
            response = self.fake_call(api_key, payload)
            if json.loads(payload["messages"][1]["content"])["translationGroupId"] == blocked:
                body = json.loads(response["choices"][0]["message"]["content"])
                body["targetUtterances"] = [text + "禁" for text in body["targetUtterances"]]
                body["coverage"] = [{**row, "targetText": row["targetText"] + "禁"} for row in body["coverage"]]
                response["choices"][0]["message"]["content"] = json.dumps(body)
            return response

        with self.assertRaises(subject.GroupFailuresCollected) as raised:
            self.production_run(f.source, f.anchor, f.policy, self.out, "fixture-key", caller,
                                failure_collector=subject.FailureCollector(2))
        self.assertEqual(raised.exception.report["failures"][0]["action"], "escalate_engineering")
        self.assertFalse((self.out / "plugin-group-stop.json").exists())
        self.assertEqual(len(self.calls), 4)

    def test_loop_repairs_the_failed_group_end_to_end(self):
        f = self.fixture
        self.failed_id = runner.group_plan(f.request, f.anchor)[1]["translationGroupId"]
        state = self.out.parent / "state"

        def run_round(out, reuse_from, brief, collector):
            return self.production_run(f.source, f.anchor, f.policy, out, "fixture-key", self._quote_fail,
                                       reuse_from=reuse_from, partial_repair_brief=brief,
                                       failure_collector=collector)

        receipt = subject.drive(f.request, 2, run_round, self.out.parent / "rounds", state)
        self.assertEqual(receipt["status"], "all_groups_passed")
        self.assertEqual(receipt["rounds"], 2)
        self.assertEqual(receipt["repairSpend"]["calls"], 2)
        final = Path(receipt["finalRunDirectory"])
        self.assertTrue((final / "evidence.json").exists())
        repaired = json.loads((final / "group-0002-astra.json").read_text())
        self.assertEqual(len(self.calls), 6)
        self.assertIn("quotation", json.dumps(self.calls[-2]))
        self.assertTrue(repaired["payloadSha256"])


if __name__ == "__main__":
    unittest.main()
