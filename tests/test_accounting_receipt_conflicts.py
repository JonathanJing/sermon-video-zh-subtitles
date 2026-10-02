"""Receipt imports may duplicate equivalent facts, never pick a conflicting winner."""
import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest

from scripts import sermon_accounting as accounting
from scripts import sermon_logs
from tests.test_sermon_accounting import response


class ReceiptConflictTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        with accounting.accounting_session(self.root, 'receipt-fixture'):
            with accounting.stage('translation', billing='api'):
                accounting.record_api_attempt('gpt-6-astra', response('same'), .1)
        self.events, damaged = accounting.read_events(self.root)
        self.assertFalse(damaged)
        self.api = next(e for e in self.events if e['event'] == 'api_attempt')

    def write(self, events):
        (self.root/'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))

    def duplicate(self, **fields):
        return {**copy.deepcopy(self.api), 'eventId': 'imported-event', 'attemptId': 'imported-attempt', **fields}

    def summarize(self, events):
        self.write(events)
        before = (self.root/'events.jsonl').read_bytes()
        result = accounting.summarize(self.root)
        self.assertEqual((self.root/'events.jsonl').read_bytes(), before)
        return result

    def test_conflicting_usage_has_no_order_dependent_trusted_total(self):
        other = self.duplicate(usage={**self.api['usage'], 'inputTokens': 2000})
        reports = [self.summarize(events) for events in
                   ([*self.events, other], [other, *self.events])]
        for report in reports:
            self.assertEqual(report['ledgerIntegrity']['status'], 'conflicting_receipts')
            self.assertTrue(report['receiptIntegrity']['conflicts'])
            row = next(r for r in report['stages'] if r['stage'] == 'translation')
            self.assertEqual(row['tokenStatus'], 'conflicted')
            self.assertIsNone(row['inputTokens']); self.assertIsNone(row['knownEstimatedUsd'])
            self.assertIsNone(row['apiAttempts']); self.assertIsNone(report['runs'][0]['apiAttempts'])
            self.assertIsNone(report['runs'][0]['knownEstimatedUsd'])
            self.assertEqual(report['runs'][0]['overallCostStatus'], 'conflicted')
        self.assertEqual(reports[0]['receiptIntegrity'], reports[1]['receiptIntegrity'])

    def test_status_model_cost_latency_and_executor_conflicts_are_not_equivalent(self):
        variants = ({'status': 'failed'}, {'model': 'gpt-6-sol'},
                    {'cost': {**self.api['cost'], 'estimatedUsd': 999}}, {'elapsedSeconds': 99})
        for changes in variants:
            with self.subTest(changes=changes):
                report = self.summarize([*self.events, self.duplicate(**changes)])
                self.assertEqual(report['receiptIntegrity']['status'], 'conflicted')
        stage = copy.deepcopy(next(e for e in self.events if e['event'] == 'stage_started' and e['stage'] == 'translation'))
        stage.update(eventId='other-stage-event', spanId='other-span', executorType='decision_agent')
        report = self.summarize([*self.events, stage, self.duplicate(spanId='other-span')])
        self.assertEqual(report['receiptIntegrity']['status'], 'conflicted')

    def test_equal_receipts_deduplicate_but_distinct_providers_count_separately(self):
        report = self.summarize([*self.events, self.duplicate()])
        self.assertEqual(report['runs'][0]['apiAttempts'], 1)
        self.assertEqual(report['receiptIntegrity']['equivalentDuplicatesIgnored'], 1)
        self.assertEqual(report['receiptIntegrity']['status'], 'consistent')
        report = self.summarize([*self.events, self.duplicate(provider='different-provider')])
        self.assertEqual(report['runs'][0]['apiAttempts'], 2)
        self.assertEqual(report['stages'][0]['inputTokens'], 2000)

    def test_equivalent_cross_run_import_has_stable_attribution(self):
        other = self.duplicate(runId='imported-run', recordedAt='2026-10-01T00:00:00+00:00', spanId='imported-span')
        stage = copy.deepcopy(next(e for e in self.events if e['event'] == 'stage_started' and e['stage'] == 'translation'))
        stage.update(runId='imported-run',eventId='imported-stage',spanId='imported-span')
        # The canonical representative is chosen by receipt timestamp, not line order.
        original = {**self.api, 'recordedAt':'2026-09-30T00:00:00+00:00'}
        base = [original if e is self.api else e for e in self.events]
        first = self.summarize([*base, stage, other])
        second = self.summarize([stage, other, *base])
        def counts(report): return {r['runId']: r['apiAttempts'] for r in report['runs']}
        self.assertEqual(first['receiptIntegrity']['status'], 'consistent')
        self.assertEqual(first['receiptIntegrity']['equivalentDuplicatesIgnored'], 1)
        self.assertEqual(counts(first), counts(second))
        self.assertEqual(counts(first)['imported-run'], 0)

    def test_sdk_conflicts_remain_separate_from_direct_receipts(self):
        with accounting.accounting_session(self.root, 'sdk-fixture'):
            with accounting.sdk_invocation('gpt-6-sol') as receipt:
                receipt['usage'] = {'requests':1,'input_tokens':50,'output_tokens':5,'total_tokens':55}
        events, _ = accounting.read_events(self.root)
        original = next(e for e in events if e['event']=='sdk_call_finished')
        other = {**copy.deepcopy(original),'eventId':'sdk-import','usage':{**original['usage'],'input_tokens':500}}
        for rows in ([*events,other], [other,*events]):
            report = self.summarize(rows)
            run = next(r for r in report['runs'] if r['runId']==original['runId'])
            self.assertEqual(run['sdkCalls'][0]['status'], 'usage_conflict')
            self.assertIsNone(run['sdkCalls'][0]['usage']['input_tokens'])
            self.assertEqual(run['overallCostStatus'], 'conflicted')
            direct = next(r for r in report['runs'] if r['runId']==self.api['runId'])
            self.assertEqual(direct['apiAttempts'], 1)
            self.assertAlmostEqual(direct['knownEstimatedUsd'], .0201)

    def test_sdk_cross_run_import_deduplicates_or_conflicts_on_the_same_invocation(self):
        with accounting.accounting_session(self.root, 'sdk-origin'):
            with accounting.sdk_invocation('gpt-6-sol') as receipt:
                receipt['usage'] = {'requests':1,'input_tokens':50,'output_tokens':5,'total_tokens':55}
        events, _ = accounting.read_events(self.root)
        original = next(e for e in events if e['event']=='sdk_call_finished')
        imported = {**copy.deepcopy(original), 'eventId':'sdk-cross-run-import',
                    'runId':'imported-sdk-run', 'recordedAt':
                        (datetime.fromisoformat(original['recordedAt']) + timedelta(seconds=1)).isoformat()}
        parent = next(e for e in events if e['event']=='stage_started' and e['spanId']==original['spanId'])
        events.append({**copy.deepcopy(parent), 'runId':'imported-sdk-run', 'eventId':'imported-sdk-stage'})
        report = self.summarize([imported, *events])
        copied = next(r for r in report['runs'] if r['runId']=='imported-sdk-run')
        self.assertEqual(report['receiptIntegrity']['equivalentDuplicatesIgnored'], 1)
        self.assertEqual(copied['sdkCalls'][0]['status'], 'duplicate_import')
        self.assertIsNone(copied['sdkCalls'][0]['usage']['input_tokens'])
        self.assertEqual(copied['unpricedSdkInvocations'], 0)
        imported['usage']['input_tokens'] = 500
        report = self.summarize([*events, imported])
        for run in report['runs']:
            if run['runId'] in (original['runId'], 'imported-sdk-run'):
                self.assertEqual(run['overallCostStatus'], 'conflicted')
                self.assertEqual(run['sdkCalls'][0]['status'], 'usage_conflict')

    def test_legacy_sdk_nonfinite_usage_stays_unknown_without_breaking_summary(self):
        with accounting.accounting_session(self.root, 'legacy-sdk'):
            with accounting.sdk_invocation('gpt-6-sol'):
                pass
        events, _ = accounting.read_events(self.root)
        event = next(e for e in events if e['event'] == 'sdk_call_finished')
        event['usage']['input_tokens'] = float('nan')
        report = self.summarize(events)
        run = next(r for r in report['runs'] if r['runId'] == event['runId'])
        self.assertIsNone(run['sdkCalls'][0]['usage']['input_tokens'])
        json.dumps(report, allow_nan=False)

    def test_readonly_log_check_reports_conflicts_without_writing_summary(self):
        self.write([*self.events, self.duplicate(usage={**self.api['usage'],'inputTokens':2000})])
        before = {p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        result = sermon_logs.inspect_logs(self.root, run_id='all')
        self.assertEqual(result['status'], 'needs_attention')
        self.assertEqual(result['ledgerIntegrity'], 'conflicting_receipts')
        self.assertEqual({p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()}, before)


if __name__ == '__main__': unittest.main()
