import unittest

from scripts import four_layer_progress
from scripts.build_four_layer_timeline import dependencies, production_data, simulation_data


class FourLayerTimelineTest(unittest.TestCase):
    def test_status_interval_is_separate_from_execution_and_completion_only_is_point(self):
        ledger = four_layer_progress.new_ledger("week", ["ko"])
        ledger["history"] = [
            {"action": "update", "step": "L2-04@ko", "status": "waiting_review", "at": "2026-09-27T10:00:00Z"},
            {"action": "update", "step": "L2-04@ko", "status": "waiting_review", "at": "2026-09-27T10:02:00Z"},
            {"action": "update", "step": "L2-04@ko", "status": "complete", "at": "2026-09-27T10:05:00Z"},
            {"action": "update", "step": "L3-02@ko", "status": "complete", "at": "2026-09-27T10:06:00Z"},
        ]
        data = production_data(ledger, [])
        review = next(row for row in data["rows"] if row["id"] == "L2-04@ko")
        completion = next(row for row in data["rows"] if row["id"] == "L3-02@ko")
        self.assertEqual(len(review["intervals"]), 1)
        self.assertEqual(review["intervals"][0]["seconds"], 300)
        self.assertEqual(review["attempts"], [])
        self.assertEqual(completion["intervals"], [])
        self.assertIsNotNone(completion["completedAt"])
        self.assertEqual(data["coverage"]["missingCompleted"], 0)

    def test_dependencies_are_same_locale_and_cross_layer_gates(self):
        steps = four_layer_progress.new_ledger("week", ["ko", "es"])["steps"]
        graph = dependencies(steps)
        self.assertEqual(graph["L1-04"], ["L1-01", "L1-02", "L1-03"])
        self.assertEqual(graph["L2-02@ko"], ["L1-04", "L2-01@ko"])
        self.assertEqual(graph["L4-01@es"], ["L2-04@es", "L3-06@es"])
        self.assertNotIn("L2-04@ko", graph["L4-01@es"])

    def test_simulation_units_have_distinct_rows_and_do_not_gain_approval(self):
        log = {"schemaVersion": "sermon-dev-four-layer-timing-log-v1", "pageId": "clip", "events": [
            {"name": "layer2.unit", "locale": "ko", "unitId": "u1",
             "startedAt": "2026-09-28T10:00:00Z", "finishedAt": "2026-09-28T10:00:01Z"},
            {"name": "layer2.unit", "locale": "ko", "unitId": "u2",
             "startedAt": "2026-09-28T10:00:01Z", "finishedAt": "2026-09-28T10:00:02Z"},
        ]}
        data = simulation_data(log)
        self.assertEqual(len(data["rows"]), 2)
        self.assertEqual({row["id"] for row in data["rows"]}, {"layer2.unit@ko#u1", "layer2.unit@ko#u2"})
        self.assertTrue(all(row["status"] == "simulation_only" for row in data["rows"]))

    def test_nested_accounting_spans_attach_only_to_matching_step_identity(self):
        ledger = four_layer_progress.new_ledger("week", ["ko"])
        identity = four_layer_progress.ledger_identity(ledger)
        events = [
            {"event": "workflow_started", "workflowId": "w", "metadata":
             {"pageId": "week", "target": "dev", "ledgerIdentitySha256": identity}},
            {"event": "stage_started", "workflowId": "w", "stage": "four_layer.L2-02:ko",
             "spanId": "root", "startedAt": "2026-09-28T10:00:00Z"},
            {"event": "stage_started", "workflowId": "w", "stage": "layer2.group.ko.0001",
             "spanId": "group", "parentSpanId": "root", "startedAt": "2026-09-28T10:00:01Z"},
            {"event": "stage_started", "workflowId": "w", "stage": "layer2.translator.ko.group-0001",
             "spanId": "translator", "parentSpanId": "group", "startedAt": "2026-09-28T10:00:02Z"},
            {"event": "stage_finished", "workflowId": "w", "stage": "layer2.translator.ko.group-0001",
             "spanId": "translator", "recordedAt": "2026-09-28T10:00:05Z", "elapsedSeconds": 3,
             "status": "completed"},
            {"event": "stage_finished", "workflowId": "w", "stage": "layer2.group.ko.0001",
             "spanId": "group", "recordedAt": "2026-09-28T10:00:06Z", "elapsedSeconds": 5,
             "status": "completed"},
            {"event": "stage_finished", "workflowId": "w", "stage": "four_layer.L2-02:ko",
             "spanId": "root", "recordedAt": "2026-09-28T10:00:07Z", "elapsedSeconds": 7,
             "status": "completed"},
            {"event": "stage_started", "workflowId": "foreign", "stage": "layer2.reviewer.ko.group-0001",
             "spanId": "foreign", "parentSpanId": "other", "startedAt": "2026-09-28T10:00:02Z"},
            {"event": "stage_finished", "workflowId": "foreign", "stage": "layer2.reviewer.ko.group-0001",
             "spanId": "foreign", "recordedAt": "2026-09-28T10:00:08Z", "elapsedSeconds": 6,
             "status": "completed"},
        ]
        data = production_data(ledger, events)
        row = next(row for row in data["rows"] if row["id"] == "L2-02@ko")
        child = {item["id"]: item for item in row["substeps"]}
        self.assertEqual(child["L2-02@ko/group"]["attempts"][0]["seconds"], 5)
        self.assertEqual(child["L2-02@ko/translator"]["attempts"][0]["seconds"], 3)
        self.assertEqual(child["L2-02@ko/reviewer"]["attempts"], [])
        self.assertEqual(child["L2-02@ko/reviewer"]["dependsOn"],
                         ["L2-02@ko/translator"])
        self.assertEqual(data["coverage"]["measuredSubsteps"], 2)


if __name__ == "__main__":
    unittest.main()
