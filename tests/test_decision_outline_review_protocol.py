"""Synthetic-only tests of source isolation, human preflight, and timing bounds."""
import copy
import unittest
from scripts.experiments import decision_outline_review_protocol as p


def cases():
    return [{"caseId": f"c{i}", "sourceId": f"s{i}", "payloadSha256": f"fixture-{i}",
             "authorId": "writer", "family": "secret", "expected": "unsupported",
             "sharedEvidence": {"sourceUnits": [{"sourceUnitId": "u1", "text": "Some may find comfort."}],
                                "outline": "Everyone is guaranteed comfort.", "expected": "unsupported"}}
            for i in range(6)]


def gold(case, reviewer="g1"):
    return {"caseId": case["caseId"], "sourceId": case["sourceId"], "payloadSha256": case["payloadSha256"],
            "reviewerId": reviewer, "status": "completed", "framingLabel": "misleading", "severity": "severe",
            "claims": [{"span": "Everyone is guaranteed comfort.", "windowLabel": "unsupported",
                        "wholeSourceLabel": "unsupported", "evidence": [{"sourceUnitId": "u1", "textSpan": "Some may"}]}]}


def humans():
    return {i: {"kind": "human"} for i in ["g1", "g2", "g3", "t1", "t2", "writer"]}


class OutlineReviewProtocolTests(unittest.TestCase):
    def test_allocation_is_reproducible_balanced_source_crossing(self):
        data = cases()
        allocation = p.allocate_timed_reviews(data, ["t1", "t2"])
        self.assertEqual(allocation, p.allocate_timed_reviews(list(reversed(data)), ["t1", "t2"]))
        for reviewer in ("t1", "t2"):
            rows = [r for r in allocation if r["reviewerId"] == reviewer]
            self.assertEqual(sum(r["arm"] == "A" for r in rows), 3)
            self.assertEqual(sum(r["arm"] == "B" for r in rows), 3)
        for c in data:
            self.assertEqual({r["arm"] for r in allocation if r["caseId"] == c["caseId"]}, {"A", "B"})
        with self.assertRaisesRegex(ValueError, "explicit_distinct"):
            p.allocate_timed_reviews(data, [])

    def test_templates_blind_and_pending_no_fabricated_identities(self):
        template = p.make_gold_templates(cases(), ["g1", "g2"])[0]
        self.assertNotIn("expected", template)
        self.assertNotIn("expected", template["sharedEvidence"])
        self.assertNotIn("family", template)
        self.assertNotIn("authorId", template)
        self.assertEqual(template["status"], "pending")
        report = p.validate_gold(cases(), [], {})
        self.assertEqual(report["completeCases"], 0)
        self.assertFalse(report["productionApproval"])

    def test_gold_independent_humans_hashes_and_exact_source_spans(self):
        c = cases()[0]
        rows = [gold(c, "g1"), gold(c, "g2")]
        self.assertEqual(p.validate_gold([c], rows, humans())["status"], "ready")
        for field, value, expected in [("payloadSha256", "wrong", "gold_identity_mismatch"),
                                      ("reviewerId", "writer", "author_gold_same_source")]:
            altered = copy.deepcopy(rows)
            altered[0][field] = value
            self.assertIn(expected, str(p.validate_gold([c], altered, humans())["errors"]))
        identities = humans()
        identities["g1"] = {"kind": "agent"}
        self.assertIn("configured_human_gold_required", str(p.validate_gold([c], rows, identities)))
        identities["g1"] = {"kind": "human", "role": "model"}
        self.assertIn("configured_human_gold_required", str(p.validate_gold([c], rows, identities)))
        changed = copy.deepcopy(rows)
        changed[0]["claims"][0]["evidence"][0]["textSpan"] = "fabricated text"
        self.assertIn("source_span_not_bound", str(p.validate_gold([c], changed, humans())))
        changed[0]["claims"][0]["evidence"][0] = {"sourceUnitId": "missing", "textSpan": "Some may"}
        self.assertIn("source_span_not_bound", str(p.validate_gold([c], changed, humans())))

    def test_runner_source_excerpts_and_exact_complete_claim_coverage(self):
        c = cases()[0]
        evidence = c["sharedEvidence"]
        evidence["sourceExcerpts"] = [{"sourceUnitId": "u1", "textEn": "Some may find comfort.", "textZh": "有些人或许得到安慰。"}]
        del evidence["sourceUnits"]
        evidence["claims"] = [{"id": "title", "span": "Everyone is guaranteed comfort."},
                              {"id": "p1", "span": "Some may find comfort."}]
        rows = [gold(c, "g1"), gold(c, "g2")]
        self.assertIn("gold_claim_coverage_mismatch", str(p.validate_gold([c], rows, humans())))
        for row in rows:
            additional = copy.deepcopy(row["claims"][0])
            additional["span"] = "Some may find comfort."
            row["claims"].append(additional)
        self.assertEqual(p.validate_gold([c], rows, humans())["status"], "ready")
        duplicate = copy.deepcopy(rows)
        duplicate[0]["claims"].append(copy.deepcopy(duplicate[0]["claims"][0]))
        self.assertIn("gold_claim_coverage_mismatch", str(p.validate_gold([c], duplicate, humans())))
        wrong = copy.deepcopy(rows)
        wrong[0]["claims"][1]["span"] = "Something else."
        self.assertIn("gold_claim_coverage_mismatch", str(p.validate_gold([c], wrong, humans())))
        del evidence["sourceExcerpts"]
        self.assertIn("source_units_required_for_gold", str(p.validate_gold([c], rows, humans())))

    def test_same_source_roles_do_not_overlap_even_on_different_items(self):
        c = cases()[0]
        rows = [gold(c, "g1"), gold(c, "g2")]
        other = {**c, "caseId": "different-item"}
        data = [c, other]
        assignments = [{"caseId": other["caseId"], "sourceId": c["sourceId"],
                        "payloadSha256": other["payloadSha256"], "reviewerId": "g1", "arm": "A"}]
        self.assertIn("gold_timed_same_source", str(p.validate_gold(data, rows, humans(), assignments)))
        assignments[0]["reviewerId"] = "writer"
        self.assertIn("author_timed_same_source", str(p.validate_gold(data, rows, humans(), assignments)))

    def test_timed_assignment_identity_cannot_hide_source_role_overlap(self):
        c = cases()[0]
        rows = [gold(c, "g1"), gold(c, "g2")]
        assignment = {"caseId": c["caseId"], "sourceId": c["sourceId"],
                      "payloadSha256": c["payloadSha256"], "reviewerId": "g1", "arm": "A"}
        for key, value in (("sourceId", "invented-source"), ("payloadSha256", "wrong"),
                           ("caseId", "unknown-case"), ("reviewerId", ""), ("arm", "X")):
            with self.subTest(key=key):
                result = p.validate_gold([c], rows, humans(), [{**assignment, key: value}])
                self.assertEqual(result["status"], "incomplete")
                self.assertIn("timed_assignment_", str(result["errors"]))
        self.assertIn("gold_timed_same_source", str(p.validate_gold([c], rows, humans(), [assignment])))

    def test_completed_without_timed_interval_is_not_success(self):
        data = cases()
        assignments = p.allocate_timed_reviews(data, ["t1", "t2"])
        event = {**assignments[0], "type": "completed", "timestampSeconds": 10}
        with self.assertRaisesRegex(ValueError, "completed_requires_closed_active_interval"):
            p.summarize_timing(data, assignments, [event])
        # Explicitly incomplete, untimed reviews remain in the denominator.
        result = p.summarize_timing(data, assignments, [{**event, "type": "incomplete"}])
        self.assertFalse(result["assignments"][0]["completed"])
        self.assertTrue(result["assignments"][0]["censored"])

    def test_disagreement_needs_third_independent_human_adjudication(self):
        c = cases()[0]
        rows = [gold(c, "g1"), gold(c, "g2")]
        rows[1]["claims"][0]["windowLabel"] = "needs_more_evidence"
        self.assertIn("independent_human_adjudication_required", str(p.validate_gold([c], rows, humans())))
        self.assertEqual(p.validate_gold([c], rows, humans(), adjudications=[gold(c, "g3")])["status"], "ready")
        self.assertIn("independent_human_adjudication_required", str(p.validate_gold([c], rows, humans(), adjudications=[gold(c)])))

    def test_timing_excludes_pauses_retains_missing_and_caps_overlimit(self):
        data = cases()
        assignments = p.allocate_timed_reviews(data, ["t1", "t2"])
        first = assignments[0]
        def ev(kind, t):
            return {**first, "type": kind, "timestampSeconds": t}
        result = p.summarize_timing(data, assignments, [ev("start", 10), ev("stop", 40),
                                  ev("start", 100), ev("stop", 130), ev("completed", 131)])
        row = result["assignments"][0]
        self.assertEqual(row["observedClosedActiveSeconds"], 60)
        self.assertEqual(row["wallSeconds"], 121)
        self.assertTrue(row["completed"])
        self.assertEqual(sum(a["denominator"] for a in result["arms"].values()), 12)
        self.assertEqual(sum(a["completed"] for a in result["arms"].values()), 1)
        self.assertTrue(result["assignments"][1]["censored"])
        result = p.summarize_timing(data, assignments, [ev("start", 0), ev("stop", 500), ev("completed", 500)])
        self.assertEqual(result["assignments"][0]["restrictedActiveSeconds"], 480)
        self.assertFalse(result["assignments"][0]["completed"])

    def test_timing_rejects_unpaired_or_reversed_or_unbound_events(self):
        data = cases()
        assignments = p.allocate_timed_reviews(data, ["t1", "t2"])
        first = assignments[0]
        for events, expected in [([{**first, "type": "stop", "timestampSeconds": 0}], "stop_without_start"),
                                ([{**first, "type": "start", "timestampSeconds": 10},
                                  {**first, "type": "stop", "timestampSeconds": 9}], "timestamp_invalid"),
                                ([{**first, "type": "start", "timestampSeconds": 0},
                                  {**first, "type": "completed", "timestampSeconds": 5}], "stopped_active_timer"),
                                ([{**first, "type": "start", "timestampSeconds": 0, "payloadSha256": "wrong"}], "identity_mismatch")]:
            with self.assertRaisesRegex(ValueError, expected):
                p.summarize_timing(data, assignments, events)
        bad = copy.deepcopy(assignments)
        bad.append({**first, "caseId": data[1]["caseId"], "sourceId": first["sourceId"], "arm": "B"})
        with self.assertRaises(ValueError):
            p.summarize_timing(data, bad, [])


if __name__ == "__main__":
    unittest.main()
