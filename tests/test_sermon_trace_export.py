import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.export_sermon_trace import export, nanos, span_id, trace_id
from scripts.sermon_accounting import SCHEMA


class SermonTraceExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.events = []

    def event(self, kind, *, run="run-one", time="2026-09-06T08:00:00+00:00", **fields):
        row = {"schemaVersion": SCHEMA, "eventId": str(len(self.events)), "runId": run,
               "recordedAt": time, "workflowId": "workflow-one", **fields, "event": kind}
        self.events.append(row)
        return row

    def fixture(self, run="run-one"):
        self.event("run_started", run=run, workflow="weekly_dubbing")
        self.event("workflow_started", run=run, workflow="weekly_dubbing", metadata={"jobSha256": "a" * 64})
        for stage, parent in (("render", None), ("assemble", "render")):
            self.event("stage_started", run=run, spanId=stage, parentSpanId=parent, stage=stage, startedAt="2026-09-06T08:00:00.123456+00:00")
            self.event("stage_finished", run=run, spanId=stage, parentSpanId=parent, stage=stage, status="completed", cacheHit=False, billing="local", elapsedSeconds=1, time="2026-09-06T08:00:01.123456+00:00")
        self.event("workflow_finished", run=run, workflow="weekly_dubbing", status="completed", time="2026-09-06T08:00:02+00:00")
        self.event("run_finished", run=run, workflow="weekly_dubbing", status="completed", time="2026-09-06T08:00:03+00:00")

    def write(self):
        path = self.work / "events.jsonl"
        path.write_text("".join(json.dumps(row) + "\n" for row in self.events))
        return path

    def result(self):
        self.write()
        payload, diagnostics = export(self.work)
        spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
        return payload, diagnostics, {s["spanId"]: s for s in spans}

    def test_exact_otlp_shape_parent_tree_and_integer_timestamp_strings(self):
        self.fixture()
        payload, diag, spans = self.result()
        self.assertEqual(set(payload), {"resourceSpans"})
        self.assertEqual(diag["status"], "exported")
        self.assertEqual(diag["exportedSpans"], 4)
        stage = spans[span_id(("run-one", "stage", "assemble"))]
        self.assertEqual(stage["parentSpanId"], span_id(("run-one", "stage", "render")))
        render = spans[span_id(("run-one", "stage", "render"))]
        self.assertEqual(render["parentSpanId"], span_id(("run-one", "workflow", "workflow-one")))
        self.assertEqual(render["startTimeUnixNano"], str(nanos("2026-09-06T08:00:00.123456+00:00")))
        self.assertTrue(render["startTimeUnixNano"].endswith("123456000"))
        for span in spans.values():
            self.assertRegex(span["traceId"], r"^[0-9a-f]{32}$")
            self.assertRegex(span["spanId"], r"^[0-9a-f]{16}$")
            self.assertEqual(span["kind"], 1)
            self.assertEqual(span["status"]["code"], 1)
            self.assertIsInstance(span["endTimeUnixNano"], str)

    def test_identical_source_ids_in_different_runs_never_join(self):
        self.fixture("run-one")
        self.fixture("run-two")
        _, diag, spans = self.result()
        self.assertEqual(diag["traceCount"], 2)
        self.assertEqual(len(spans), 8)
        for span in spans.values():
            if "parentSpanId" in span:
                self.assertEqual(span["traceId"], spans[span["parentSpanId"]]["traceId"])
        self.assertNotEqual(trace_id("run-one"), trace_id("run-two"))

    def test_missing_end_unknown_status_and_bad_line_are_partial_not_fake_duration(self):
        self.fixture()
        self.events = [e for e in self.events if not (e["event"] == "stage_finished" and e["spanId"] == "render")]
        self.events[-1]["status"] = "still_running"
        path = self.write()
        with path.open("a") as stream:
            stream.write('{"secret":"UNFINISHED_SECRET"')
        payload, diag = export(self.work)
        spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
        self.assertEqual(diag["status"], "partial")
        self.assertNotIn(span_id(("run-one", "stage", "render")), [s["spanId"] for s in spans])
        self.assertTrue({"unfinished_span", "unknown_finished_status", "parent_not_exported", "damaged_event"} <= {d["code"] for d in diag["diagnostics"]})
        self.assertNotIn("UNFINISHED_SECRET", json.dumps((payload, diag)))

    def test_failed_status_and_usage_counts_without_messages_paths_or_labels(self):
        self.fixture()
        secret = "SECRET_TEST_TOKEN"
        for event in self.events:
            event.update(command=[secret], prompt=secret, text=secret, path="/private/" + secret,
                         error={"message": secret, "frames": [{"path": secret}]})
            if event["event"] == "stage_finished":
                event["status"] = "failed"
            if event["event"].startswith("workflow_") or event["event"].startswith("run_"):
                event["workflow"] = secret
        usage = dict.fromkeys(("inputTokens", "outputTokens", "cachedInputTokens", "cacheWriteTokens", "reasoningTokens"), None)
        usage.update(inputTokens=11, outputTokens=5)
        self.event("api_attempt", stage="render", spanId="render", status="failed", usage=usage, cost={"estimatedUsd": None}, elapsedSeconds=1, errorType=secret)
        payload, diag, spans = self.result()
        self.assertNotIn(secret, json.dumps((payload, diag)))
        render = spans[span_id(("run-one", "stage", "render"))]
        self.assertEqual(render["status"], {"code": 2})
        attrs = {a["key"]: a["value"] for a in render["attributes"]}
        self.assertEqual(attrs["sermon.inputTokens"], {"intValue": "11"})
        self.assertEqual(attrs["sermon.failedApiAttempts"], {"intValue": "1"})
        self.assertEqual(diag["qaAcceptance"], "not_evaluated")
        self.assertEqual(diag["costCompleteness"], "not_evaluated")

    def test_backward_clock_duplicate_and_old_schema_reported(self):
        self.fixture()
        self.events[3]["recordedAt"] = "2026-09-05T00:00:00+00:00"
        self.events.append(dict(self.events[0]))
        old = dict(self.events[0], eventId="old", schemaVersion="old-v1")
        self.events.append(old)
        _, diag, _ = self.result()
        self.assertTrue({"invalid_span_time", "duplicate_event_id", "unsupported_event_schema"} <= {d["code"] for d in diag["diagnostics"]})

    def test_cli_separate_diagnostics_and_no_source_overwrite(self):
        self.fixture()
        source = self.write()
        original = source.read_bytes()
        out, diagnostics = self.work / "otlp.json", self.work / "diagnostics.json"
        command = [sys.executable, "-m", "scripts.export_sermon_trace", "--accounting-dir", str(self.work), "--out", str(out), "--diagnostics", str(diagnostics)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(set(json.loads(out.read_text())), {"resourceSpans"})
        command[command.index("--out") + 1] = str(source)
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(source.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
