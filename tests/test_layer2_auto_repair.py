import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
    def test_repair_bound_uses_enforced_input_and_completion_limits(self):
        from scripts.canonical_layer2_budget import CURRENT_LIMITS, request_limits
        from scripts.sermon_provider_limits import DEFAULT_REQUEST_LIMITS
        with request_limits(DEFAULT_REQUEST_LIMITS):
            self.assertEqual(subject._repair_token_bound(),
                             DEFAULT_REQUEST_LIMITS["maxInputTokens"] + DEFAULT_REQUEST_LIMITS["maxCompletionTokens"])
        token = CURRENT_LIMITS.set(None)
        try:
            self.assertIsNone(subject._repair_token_bound())
        finally:
            CURRENT_LIMITS.reset(token)

    def test_negative_or_boolean_usage_is_unknown(self):
        for value in (-1, True):
            self.assertIsNone(subject._response_tokens({"usage": {"total_tokens": value}}))

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


class ReplayTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def test_saved_round_report_is_replayed_without_redispatch(self):
        out_root = self.root / "runs"
        out = out_root / "round-001"
        out.mkdir(parents=True)
        report = {"schemaVersion": subject.REPORT_SCHEMA, "routingVersion": subject.ROUTING_VERSION,
                  **REQUEST, "totalGroups": 2, "systemicThreshold": 3, "systemicStop": None,
                  "failures": [], "notDispatched": [], "humanApproval": False}
        (out / "group-failures.json").write_text(json.dumps(report), encoding="utf-8")

        def never_dispatch(*_args):
            raise AssertionError("a saved round report must not re-dispatch its groups")

        receipt = subject.drive(REQUEST, 2, never_dispatch, out_root, self.root / "state")
        self.assertEqual(receipt["status"], "repair_stopped")

    def test_saved_report_for_another_locale_is_refused(self):
        out_root = self.root / "runs"
        out = out_root / "round-001"
        out.mkdir(parents=True)
        other = dict(REQUEST, targetLocale="es")
        report = {"schemaVersion": subject.REPORT_SCHEMA, "routingVersion": subject.ROUTING_VERSION,
                  **other, "totalGroups": 2, "systemicThreshold": 3, "systemicStop": None,
                  "failures": [], "notDispatched": [], "humanApproval": False}
        (out / "group-failures.json").write_text(json.dumps(report), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "does not match this round"):
            subject.drive(REQUEST, 2, lambda *_args: None, out_root, self.root / "state")


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
        # Synthetic calls consume exactly 100 tokens; real dispatch obtains its
        # hard bound from the canonical provider request-limit context.
        bound = patch.object(subject, "_repair_token_bound", return_value=100)
        bound.start()
        self.addCleanup(bound.stop)

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

    def test_token_reservation_stops_before_a_passing_repair_can_dispatch(self):
        fleet = Fleet(self, 46, [{"g21": failing("quotationAttribution")}])
        # The next pair could use 1,000 tokens, while the initial 9,200
        # tokens permit only 920 for repairs, although the call cap has room.
        with patch.object(subject, "_repair_token_bound", return_value=500):
            receipt = self.drive(fleet)
        self.assertEqual(fleet.calls, ["all"])
        self.assertEqual(receipt["status"], "repair_stopped")
        self.assertEqual(receipt["repairSpend"], {"calls": 0, "tokens": 0})
        self.assertEqual(receipt["stoppedGroups"][0]["reasonCode"], "repair_spend_cap")

    def test_token_reservations_limit_concurrent_round_to_whole_pairs(self):
        fleet = Fleet(self, 46, [{"g2": failing("completeMeaning"), "g30": failing("completeMeaning")},
                                 {"g30": failing("completeMeaning")}])
        with patch.object(subject, "_repair_token_bound", return_value=300):
            receipt = self.drive(fleet)
        self.assertEqual(fleet.calls, ["all", ["g2"]])
        self.assertEqual(receipt["status"], "repair_stopped")
        self.assertEqual(receipt["stoppedGroups"][0]["translationGroupId"], "g30")

    def test_missing_initial_usage_or_provider_bounds_prevents_repair(self):
        class UnknownFleet(Fleet):
            def __call__(self, *args):
                try:
                    return super().__call__(*args)
                finally:
                    for path in args[0].glob("*.raw.json"):
                        value = json.loads(path.read_text())
                        value["response"].pop("usage")
                        path.write_text(json.dumps(value))
        fleet = UnknownFleet(self, 46, [{"g2": failing("completeMeaning")}])
        receipt = self.drive(fleet)
        self.assertEqual(fleet.calls, ["all"])
        self.assertEqual(receipt["stoppedGroups"][0]["reasonCode"], "repair_token_usage_unavailable")
        fleet = Fleet(self, 46, [{"g2": failing("completeMeaning")}])
        with patch.object(subject, "_repair_token_bound", return_value=None):
            receipt = self.drive(fleet, out="unbounded")
        self.assertEqual(fleet.calls, ["all"])
        self.assertEqual(receipt["stoppedGroups"][0]["reasonCode"], "repair_token_bound_unavailable")

    def test_passing_round_cannot_hide_transport_overspend(self):
        class OverspendingFleet(Fleet):
            def __call__(self, out, reuse_from, brief, collector):
                if brief:
                    self.tokens = 1000  # deliberately violate the injected bound
                return super().__call__(out, reuse_from, brief, collector)
        fleet = OverspendingFleet(self, 46, [{"g2": failing("completeMeaning")}])
        receipt = self.drive(fleet)
        self.assertEqual(fleet.calls, ["all", ["g2"]])
        self.assertEqual(receipt["status"], "repair_stopped")
        self.assertEqual(receipt["gatesPassed"], [])
        self.assertEqual(receipt["stoppedGroups"][0]["reasonCode"], "repair_spend_cap")

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

    def test_consecutive_same_failures_stop_dispatch_at_once(self):
        same = {f"g{i}": failing("negationsNumbersNames") for i in (2, 3, 4, 12)}
        fleet = Fleet(self, 46, [same])
        receipt = self.drive(fleet)
        self.assertEqual(fleet.calls, ["all"])
        self.assertEqual(receipt["repairSpend"]["calls"], 0)
        reasons = {row["reasonCode"] for row in receipt["stoppedGroups"]}
        self.assertEqual(reasons, {"systemic_rule_or_policy_issue", "not_dispatched_after_systemic_stop"})
        # Dispatch stopped after the third consecutive failure (group 4): groups 5..46 never ran.
        self.assertEqual(receipt["initialSpend"]["calls"], 4 * 2)

    def test_scattered_same_failures_run_to_the_end_then_count_as_systemic(self):
        same = {f"g{i}": failing("completeMeaning") for i in (2, 5, 9, 12)}
        fleet = Fleet(self, 46, [same])
        receipt = self.drive(fleet)
        self.assertEqual(fleet.calls, ["all"])
        self.assertEqual(receipt["initialSpend"]["calls"], 46 * 2)
        self.assertEqual({row["reasonCode"] for row in receipt["stoppedGroups"]}, {"systemic_rule_or_policy_issue"})
        self.assertEqual(receipt["gatesPassed"], [])
        self.assertEqual(receipt["releaseAuthority"], "none")

    def test_scattered_umbrella_failures_are_repaired_not_systemic(self):
        # negation_number_name_error lumps unrelated defects, so it never counts as
        # systemic at the end of a round; each group takes its own repair.
        same = {f"g{i}": failing("negationsNumbersNames") for i in (2, 5, 9, 12)}
        fleet = Fleet(self, 46, [same])
        receipt = self.drive(fleet)
        self.assertEqual(fleet.calls[0], "all")
        self.assertEqual(sorted(fleet.calls[1]), ["g12", "g2", "g5", "g9"])
        self.assertEqual(len(fleet.calls), 2)
        self.assertEqual(receipt["status"], "all_groups_passed")

    def test_two_scattered_failures_are_repaired_not_systemic(self):
        fleet = Fleet(self, 46, [{"g2": failing("completeMeaning"), "g30": failing("completeMeaning")}])
        receipt = self.drive(fleet)
        self.assertEqual(fleet.calls, ["all", ["g2", "g30"]])
        self.assertEqual(receipt["status"], "all_groups_passed")
        self.assertEqual(receipt["gatesPassed"], ["independent_review", "language_plugin"])

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
        # 20 groups -> 40 initial calls -> cap max(4, 4) = 4 calls: two groups fit, the third does not.
        fleet = Fleet(self, 20, [{f"g{i}": failing(name) for i, name in
                                  zip((1, 2, 3), ("completeMeaning", "noAddedMeaning", "quotationAttribution"))},
                                 {"g3": failing("quotationAttribution")}])
        receipt = self.drive(fleet, out="capped")
        self.assertEqual(fleet.calls, ["all", ["g1", "g2"]])
        self.assertEqual([(row["translationGroupId"], row["reasonCode"]) for row in receipt["stoppedGroups"]],
                         [("g3", "repair_spend_cap")])

    def test_failures_carried_from_earlier_rounds_are_not_systemic(self):
        fleet = Fleet(self, 46, [
            {"g2": failing("completeMeaning"), "g30": failing("completeMeaning"), "g10": failing("noAddedMeaning")},
            {"g2": failing("completeMeaning"), "g30": failing("completeMeaning"), "g10": failing("completeMeaning")},
            {"g2": failing("completeMeaning"), "g30": failing("completeMeaning")}])
        receipt = self.drive(fleet)
        self.assertEqual(fleet.calls, ["all", ["g10", "g2", "g30"], ["g10"]])
        self.assertEqual(sorted((row["translationGroupId"], row["reasonCode"]) for row in receipt["stoppedGroups"]),
                         [("g2", "repeated_failure_without_progress"), ("g30", "repeated_failure_without_progress")])

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

    def test_corrupt_terminal_receipt_refuses_resume_without_dispatch(self):
        fleet = Fleet(self, 46, [{"g7": failing("completeMeaning")}])
        first = self.drive(fleet)
        path = self.root / "runs" / f"auto-repair-receipt-{first['rounds']:03d}.json"
        path.write_text('{"status":', encoding="utf-8")
        before = subject.load_ledger(self.root / "state-runs", subject.lineage(REQUEST))
        restarted = Fleet(self, 46, [])
        with self.assertRaisesRegex(ValueError, "Saved auto-repair receipt is corrupt"):
            self.drive(restarted)
        self.assertEqual(restarted.calls, [])
        self.assertEqual(subject.load_ledger(self.root / "state-runs", subject.lineage(REQUEST)), before)
        self.assertEqual(path.read_text(), '{"status":')

    def test_mismatching_terminal_receipt_refuses_resume_without_dispatch(self):
        for field, value in (("ledgerHeadSha256", "0" * 64), ("status", "repair_stopped"),
                             ("humanApproval", True)):
            with self.subTest(field=field):
                directory = f"mismatch-{field}"
                first = self.drive(Fleet(self, 46, []), out=directory)
                path = self.root / directory / "auto-repair-receipt-001.json"
                changed = {**first, field: value}
                path.write_text(json.dumps(changed), encoding="utf-8")
                restarted = Fleet(self, 46, [])
                with self.assertRaisesRegex(ValueError, "does not match the terminal ledger"):
                    self.drive(restarted, out=directory)
                self.assertEqual(restarted.calls, [])
                self.assertEqual(json.loads(path.read_text()), changed)

    def test_matching_terminal_receipt_is_verified_and_reused_without_dispatch(self):
        first = self.drive(Fleet(self, 46, []))
        path = self.root / "runs" / "auto-repair-receipt-001.json"
        path.write_text(json.dumps(first, indent=4), encoding="utf-8")
        restarted = Fleet(self, 46, [])
        self.assertEqual(self.drive(restarted), first)
        self.assertEqual(restarted.calls, [])

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
        # Two-group fixture has no production-scale initial token baseline.
        # Widen its test-only fraction so these tests exercise cache repair.
        for mocked in (patch.object(subject, "_repair_token_bound", return_value=100),
                       patch.object(subject, "SPEND_FRACTION", 2)):
            mocked.start()
            self.addCleanup(mocked.stop)

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
                "usage": {"total_tokens": 100},
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

    def test_collection_runs_groups_concurrently_with_a_plugin(self):
        import threading
        import time
        f = self.fixture
        self.failed_id = runner.group_plan(f.request, f.anchor)[0]["translationGroupId"]
        active, peak, lock = [0], [0], threading.Lock()

        def slow(api_key, payload):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.05)
            try:
                return self._quote_fail(api_key, payload)
            finally:
                with lock:
                    active[0] -= 1
        collector = subject.FailureCollector(2, group_workers=2)
        with self.assertRaises(subject.GroupFailuresCollected) as raised:
            self.production_run(f.source, f.anchor, f.policy, self.out, "fixture-key", slow,
                                failure_collector=collector)
        self.assertEqual(peak[0], 2)
        self.assertEqual([row["translationGroupId"] for row in raised.exception.report["failures"]],
                         [self.failed_id])
        with self.assertRaisesRegex(ValueError, "Group workers must be 1..16"):
            subject.FailureCollector(2, group_workers=17)

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

    def test_loop_stops_a_stubborn_group_and_keeps_the_repaired_one(self):
        f = self.fixture
        plan = runner.group_plan(f.request, f.anchor)
        stubborn, once = plan[0]["translationGroupId"], plan[1]["translationGroupId"]

        def caller(api_key, payload):
            response = self.fake_call(api_key, payload)
            data = json.loads(payload["messages"][1]["content"])
            fail = (data["translationGroupId"] == stubborn
                    or data["translationGroupId"] == once and "partialRepair" not in data)
            if payload["reasoning_effort"] == "medium" and fail:
                result = json.loads(response["choices"][0]["message"]["content"])
                result["semanticReview"]["status"] = "fail"
                result["semanticReview"]["checks"]["completeMeaning"] = "fail"
                result["semanticReview"]["issues"] = ["Dropped the second clause"]
                response["choices"][0]["message"]["content"] = json.dumps(result)
            return response

        def run_round(out, reuse_from, brief, collector):
            return self.production_run(f.source, f.anchor, f.policy, out, "fixture-key", caller,
                                       reuse_from=reuse_from, partial_repair_brief=brief,
                                       failure_collector=collector)

        receipt = subject.drive(f.request, 2, run_round, self.out.parent / "rounds", self.out.parent / "state")
        self.assertEqual(receipt["status"], "repair_stopped")
        self.assertEqual(receipt["rounds"], 2)
        self.assertEqual(len(self.calls), 8)  # 4 initial, then both groups repaired once
        self.assertEqual([(row["translationGroupId"], row["reasonCode"]) for row in receipt["stoppedGroups"]],
                         [(stubborn, "repeated_failure_without_progress")])
        self.assertIsNone(receipt["evidenceSha256"])
        self.assertFalse((Path(receipt["finalRunDirectory"]) / "evidence.json").exists())

    def test_collector_group_count_must_match_the_plan(self):
        f = self.fixture
        with self.assertRaisesRegex(ValueError, "group count differs"):
            self.production_run(f.source, f.anchor, f.policy, self.out, "fixture-key", self.fake_call,
                                failure_collector=subject.FailureCollector(3))
        self.assertEqual(self.calls, [])

    def test_third_round_reuses_caches_repaired_in_the_second(self):
        from unittest.mock import patch
        f = self.fixture
        plan = runner.group_plan(f.request, f.anchor)
        fixed_once, fixed_twice = plan[0]["translationGroupId"], plan[1]["translationGroupId"]
        reviews = {fixed_once: ["completeMeaning", None],
                   fixed_twice: ["completeMeaning", "quotationAttribution", None]}

        def caller(api_key, payload):
            response = self.fake_call(api_key, payload)
            if payload["reasoning_effort"] != "medium":
                return response
            group_id = json.loads(payload["messages"][1]["content"])["translationGroupId"]
            check = reviews[group_id].pop(0)
            if check is not None:
                result = json.loads(response["choices"][0]["message"]["content"])
                result["semanticReview"]["status"] = "fail"
                result["semanticReview"]["checks"][check] = "fail"
                result["semanticReview"]["issues"] = [f"{check} failed"]
                response["choices"][0]["message"]["content"] = json.dumps(result)
            return response

        def run_round(out, reuse_from, brief, collector):
            return self.production_run(f.source, f.anchor, f.policy, out, "fixture-key", caller,
                                       reuse_from=reuse_from, partial_repair_brief=brief,
                                       failure_collector=collector)

        with patch.object(subject, "MINIMUM_REPAIR_CALLS", 100):
            receipt = subject.drive(f.request, 2, run_round, self.out.parent / "rounds", self.out.parent / "state")
        self.assertEqual(receipt["status"], "all_groups_passed")
        self.assertEqual(receipt["rounds"], 3)
        # 4 initial calls, both groups repaired in round 2, only the second in round 3.
        self.assertEqual(len(self.calls), 4 + 4 + 2)
        final = Path(receipt["finalRunDirectory"])
        self.assertTrue((final / "evidence.json").exists())
        effective = json.loads((final / "effective-repairs.json").read_text())
        self.assertEqual(set(effective), {fixed_once, fixed_twice})
        self.assertIn("quotation", effective[fixed_twice]["instruction"].lower())
        # Resuming a finished chain makes no calls.
        before = len(self.calls)
        again = subject.drive(f.request, 2, run_round, self.out.parent / "rounds", self.out.parent / "state")
        self.assertEqual(again["rounds"], 3)
        self.assertEqual(len(self.calls), before)

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
