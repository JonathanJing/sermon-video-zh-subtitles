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

    def test_v1_and_v2_events_remain_exportable(self):
        self.fixture()
        for index, event in enumerate(self.events):
            event["schemaVersion"] = "sermon-workflow-accounting-v1" if index % 2 else "sermon-workflow-accounting-v2"
        _, diag, spans = self.result()
        self.assertEqual(diag["status"], "exported")
        self.assertEqual(len(spans), 4)

    def test_dependency_extensions_reject_unsafe_imports_on_all_schemas(self):
        for schema in ('sermon-workflow-accounting-v1', 'sermon-workflow-accounting-v2', SCHEMA):
            for field, value in [('dependsOn', ['PRIVATE text']), ('blockedBy', ['x'] * 65),
                    ('dependsOn', ['same', 'same']), ('workUnitId', 'x' * 101),
                    ('decisionId', {'secret': 'PRIVATE'}), ('attemptId', 'PRIVATE\ntext'),
                    ('queuedAt', 'PRIVATE'), ('dependencyReadyAt', '2026-01-01'),
                    ('executorType', 'fixed_program')]:
                with self.subTest(schema=schema, field=field):
                    self.events = []
                    self.fixture()
                    for event in self.events:
                        event['schemaVersion'] = schema
                        if event['event'].startswith('stage_'):
                            event[field] = value
                    payload, diag, _ = self.result()
                    self.assertEqual(diag['status'], 'partial')
                    self.assertNotIn('PRIVATE', json.dumps((payload, diag)))

    def test_canonical_executor_and_dependency_timestamps_export(self):
        self.fixture()
        for event in self.events:
            if event['event'].startswith('stage_'):
                event.update(executorType='engineering_codex', dependsOn=['source'],
                             dependencyReadyAt='2026-09-06T07:59:59+00:00')
        _, diag, spans = self.result()
        self.assertEqual(diag['status'], 'exported')
        attrs = {a['key']: a['value'] for a in spans[span_id(('run-one', 'stage', 'render'))]['attributes']}
        self.assertEqual(attrs['sermon.executorType'], {'stringValue': 'engineering_codex'})
        self.assertIn('sermon.dependencyReadyAt', attrs)

    def test_changed_dependency_identity_between_edges_is_not_exported(self):
        self.fixture()
        self.events[2]['dependsOn'] = ['source-a']
        self.events[3]['dependsOn'] = ['source-b']
        _, diag, spans = self.result()
        self.assertIn('span_identity_mismatch', [d['code'] for d in diag['diagnostics']])
        self.assertNotIn(span_id(('run-one', 'stage', 'render')), spans)

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

class ReceiptExportTests(unittest.TestCase):
    setUp = SermonTraceExportTests.setUp
    event = SermonTraceExportTests.event
    fixture = SermonTraceExportTests.fixture
    write = SermonTraceExportTests.write
    result = SermonTraceExportTests.result

    def test_outbox_postappend_preack_replay_is_exported_once(self):
        from scripts import sermon_accounting as accounting
        from scripts import sermon_log_profile as profile
        import copy
        logdir=self.work/'profile-log'
        with profile.session(logdir,'export-replay-test',work_kind='production',evidence_mode='synthetic'):
            with accounting.accounting_session(logdir,'weekly_dubbing'):
                with accounting.stage('render'):
                    pass
        self.events,_=accounting.read_events(logdir)
        end=next(row for row in self.events if row['event']=='stage_finished' and row['stage']=='render')
        self.events.append(copy.deepcopy(end))
        _,diag,_=self.result()
        self.assertEqual(diag['status'],'exported')
        self.assertNotIn('duplicate_event_id',[row['code'] for row in diag['diagnostics']])
        self.events.append(dict(copy.deepcopy(end),status='failed'))
        _,diag,_=self.result()
        self.assertEqual(diag['status'],'partial')
        self.assertIn('incomplete_or_conflicting_profile_events',[row['code'] for row in diag['diagnostics']])

    def test_unfinished_attempts_keep_usage_partial_with_or_without_completed_receipts(self):
        import copy
        from scripts.export_sermon_trace import TOKEN_KEYS
        for with_completed in (False, True):
            with self.subTest(with_completed=with_completed):
                self.events = []
                self.fixture()
                # An interrupted request can outlive its failed containing stage.
                for event in self.events:
                    if event['event'] == 'stage_finished' and event['spanId'] == 'render':
                        event['status'] = 'failed'
                if with_completed:
                    self.event('api_attempt_started', stage='render', spanId='render', attemptId='completed')
                    self.event('api_attempt', stage='render', spanId='render', attemptId='completed',
                               status='completed', usage=dict(inputTokens=100, outputTokens=20,
                               cachedInputTokens=0, cacheWriteTokens=0, reasoningTokens=0),
                               cost={}, elapsedSeconds=1, responseId='completed-response')
                started = self.event('api_attempt_started', stage='render', spanId='render', attemptId='unknown')
                duplicate = copy.deepcopy(started)
                duplicate['eventId'] = 'reimported-start'
                self.events.append(duplicate)
                for reverse in (False, True):
                    if reverse:
                        self.events.reverse()
                    _, diag, spans = self.result()
                    attrs = {a['key']: a['value'] for a in spans[span_id(('run-one', 'stage', 'render'))]['attributes']}
                    self.assertEqual(diag['status'], 'partial')
                    self.assertIn('unfinished_api_attempts', [row['code'] for row in diag['diagnostics']])
                    self.assertEqual(attrs['sermon.usageCoverage'], {'stringValue': 'partial'})
                    self.assertEqual(attrs['sermon.apiAttempts'], {'intValue': '2' if with_completed else '1'})
                    self.assertEqual(attrs['sermon.unresolvedApiAttempts'], {'intValue': '1'})
                    for field in TOKEN_KEYS:
                        self.assertNotIn('sermon.' + field, attrs)
                        self.assertEqual(attrs['sermon.unknownCalls.' + field], {'intValue': '1'})
                    if with_completed:
                        self.assertEqual(attrs['sermon.knownSubtotal.inputTokens'], {'intValue': '100'})
                    else:
                        self.assertFalse(any(key.startswith('sermon.knownSubtotal.') for key in attrs))

    def test_replay_excluded_terminal_does_not_close_started_attempt(self):
        from unittest.mock import patch

        self.events = []
        self.fixture()
        self.event('api_attempt_started', stage='render', spanId='render', attemptId='call-1',
                   contractVersion='sermon-accounting-log-contract-v1', modelCallId='call-1',
                   producerId='profile-producer', sequence=1)
        terminal = self.event('api_attempt', stage='render', spanId='render', attemptId='call-1',
                              status='completed', usage=dict(inputTokens=100, outputTokens=20,
                              cachedInputTokens=0, cacheWriteTokens=0, reasoningTokens=0),
                              cost={}, elapsedSeconds=1, responseId='response-1',
                              contractVersion='sermon-accounting-log-contract-v1', modelCallId='call-1',
                              producerId='profile-producer', sequence=2, provider='openai',
                              providerScopeKey=None, providerResponseId='response-1')

        def replay_with_quarantined_terminal(events):
            excluded = {id(event) for event in events if event.get('eventId') == terminal['eventId']}
            selected = {id(event) for event in events
                        if 'contractVersion' in event and id(event) not in excluded}
            return {'status': 'partial', 'diagnostics': [], 'profileEventCount': 2,
                    '_excluded': excluded, '_selected': selected}

        with patch('scripts.export_sermon_trace.read_events', return_value=(self.events, [])), \
             patch('scripts.export_sermon_trace.profile_integrity', side_effect=replay_with_quarantined_terminal), \
             patch('scripts.sermon_accounting.profile_integrity', side_effect=replay_with_quarantined_terminal):
            payload, diagnostics = export(self.work)
        spans = {s['spanId']: s for s in payload['resourceSpans'][0]['scopeSpans'][0]['spans']}

        attrs = {a['key']: a['value'] for a in spans[span_id(('run-one', 'stage', 'render'))]['attributes']}
        self.assertIn('unfinished_api_attempts', [row['code'] for row in diagnostics['diagnostics']])
        self.assertEqual(attrs['sermon.unresolvedApiAttempts'], {'intValue': '1'})
        self.assertEqual(attrs['sermon.apiAttempts'], {'intValue': '1'})
        self.assertNotIn('sermon.inputTokens', attrs)
        self.assertEqual(attrs['sermon.unknownCalls.inputTokens'], {'intValue': '1'})

    def test_receipt_in_other_run_or_span_cannot_complete_started_attempt(self):
        for receipt_run, receipt_span in (('run-two', 'render'), ('run-one', 'assemble')):
            with self.subTest(receipt_run=receipt_run, receipt_span=receipt_span):
                self.events = []
                self.fixture()
                if receipt_run != 'run-one':
                    self.fixture(receipt_run)
                self.event('api_attempt_started', stage='render', spanId='render', attemptId='shared-label')
                self.event('api_attempt', run=receipt_run, stage=receipt_span, spanId=receipt_span,
                           attemptId='shared-label', status='completed', usage=dict(inputTokens=100,
                           outputTokens=20, cachedInputTokens=0, cacheWriteTokens=0, reasoningTokens=0),
                           cost={}, elapsedSeconds=1, responseId='other-response')
                _, _, spans = self.result()
                attrs = {a['key']: a['value'] for a in spans[span_id(('run-one', 'stage', 'render'))]['attributes']}
                self.assertEqual(attrs['sermon.usageCoverage'], {'stringValue': 'partial'})
                self.assertEqual(attrs['sermon.unresolvedApiAttempts'], {'intValue': '1'})

    def test_provider_receipts_are_reconciled_before_event_representatives(self):
        import copy
        for same_id in (False,True):
            for conflict in (False,True):
                for reverse in (False,True):
                    with self.subTest(same_id=same_id,conflict=conflict,reverse=reverse):
                        self.events=[];self.fixture()
                        usage=dict(inputTokens=100,outputTokens=20,cachedInputTokens=0,cacheWriteTokens=0,reasoningTokens=0)
                        first=self.event('api_attempt',stage='render',spanId='render',status='completed',usage=usage,cost={'estimatedUsd':None},elapsedSeconds=1,model='fixture',requestedModel='fixture',responseId='response-one')
                        other=copy.deepcopy(first)
                        if not same_id:other['eventId']='second-receipt'
                        if conflict:other['usage']['inputTokens']=200
                        self.events.append(other)
                        if reverse:self.events.reverse()
                        _,diag,spans=self.result()
                        attrs={a['key']:a['value'] for a in spans[span_id(('run-one','stage','render'))]['attributes']}
                        if conflict:
                            self.assertEqual(diag['receiptIntegrity']['status'],'conflicted')
                            self.assertNotIn('sermon.inputTokens',attrs)
                            self.assertEqual(attrs['sermon.usageCoverage'],{'stringValue':'conflicted'})
                        else:
                            self.assertEqual(diag['receiptIntegrity']['status'],'consistent')
                            self.assertEqual(attrs['sermon.inputTokens'],{'intValue':'100'})
                            self.assertEqual(attrs['sermon.apiAttempts'],{'intValue':'1'})

    def test_same_event_changed_response_or_attempt_quarantines_usage(self):
        import copy
        for changed in ('responseId', 'attemptId'):
            for reverse in (False, True):
                with self.subTest(changed=changed, reverse=reverse):
                    self.events = []; self.fixture()
                    first = self.event('api_attempt', stage='render', spanId='render', status='completed',
                        usage=dict(inputTokens=100, outputTokens=20, cachedInputTokens=0, cacheWriteTokens=0, reasoningTokens=0),
                        cost={'estimatedUsd': None}, elapsedSeconds=1, model='fixture', requestedModel='fixture',
                        responseId=None if changed == 'attemptId' else 'response-one', attemptId='attempt-one')
                    other = copy.deepcopy(first); other[changed] = 'changed-identity'; other['usage']['inputTokens'] = 200
                    self.events.append(other)
                    if reverse: self.events.reverse()
                    _, diagnostics, spans = self.result()
                    attrs = {a['key']: a['value'] for a in spans[span_id(('run-one','stage','render'))]['attributes']}
                    self.assertEqual(diagnostics['receiptIntegrity']['status'], 'conflicted')
                    self.assertEqual(attrs['sermon.usageCoverage'], {'stringValue': 'conflicted'})
                    self.assertNotIn('sermon.inputTokens', attrs)
                    self.assertNotIn('sermon.outputTokens', attrs)
