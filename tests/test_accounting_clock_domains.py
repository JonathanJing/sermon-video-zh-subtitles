import copy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from scripts import sermon_accounting as accounting
from scripts import sermon_clock_evidence as clocks
from scripts import export_observability_trace as safe_export
from scripts import export_sermon_trace as otlp
from scripts import weekly_pipeline_report as weekly
from tests import test_weekly_pipeline_report as fixtures


class ClockDomainTests(unittest.TestCase):
    def fixture(self):
        source=fixtures.WeeklyPipelineReportTests();source.setUp();self.addCleanup(source.doCleanups)
        for e in source.rows:
            if e['event'].startswith('stage_'):
                started=next(r for r in source.rows if r.get('spanId')==e['spanId'] and r['event']=='stage_started')
                e.update(clockDomainId='a'*32,monotonicStartNs=str(int(weekly.seconds(started['recordedAt'])*1e9)))
                if e['event']=='stage_finished':e['monotonicEndNs']=str(int(weekly.seconds(e['recordedAt'])*1e9))
        return source

    def test_utc_backward_and_forward_jumps_preserve_measured_subtotals_not_wall(self):
        for ended in ('2026-09-29T23:59:50+00:00','2026-09-30T00:00:32+00:00'):
            with self.subTest(ended=ended):
                source=self.fixture()
                next(e for e in source.rows if e['event']=='stage_finished' and e['spanId']=='source')['recordedAt']=ended
                run=source.result()['runs'][0]
                self.assertEqual(run['leafElapsedByExecutor']['deterministic_program'],3)
                self.assertEqual(run['leafElapsedByExecutor']['production_model'],8)
                self.assertIsNone(run['endToEndWallSeconds'])
                self.assertEqual(run['criticalPath']['activeSeconds'],8)
                self.assertEqual(run['criticalPath']['durationBasis'],'verified_monotonic_dag')
                self.assertIn('utc_clock_discontinuity_local_duration_preserved',run['diagnostics'])
                self.assertEqual(len(run['workUnits']),4)
                safe_export.export(source.root,source.root/'export')
                self.assertEqual(weekly.project(source.root/'export')['runs'][0],run)
                payload,diag=otlp.export(source.root)
                stage=next(s for s in payload['resourceSpans'][0]['scopeSpans'][0]['spans'] if s['spanId']==otlp.span_id(('run','stage','source')))
                self.assertEqual(int(stage['endTimeUnixNano'])-int(stage['startTimeUnixNano']),2_000_000_000)
                attrs={a['key']:a['value'] for a in stage['attributes']}
                self.assertEqual(attrs['sermon.exportEndTimeBasis'],{'stringValue':'monotonic_anchored_estimate'})

    def test_clock_jump_between_spans_invalidates_wall_without_losing_local_work(self):
        for delta in (30, -30):
            with self.subTest(delta=delta):
                source=self.fixture()
                for row in source.rows:
                    if row.get('spanId') in {'ko','zh','join'} or row['event']=='run_finished':
                        for key in ('recordedAt','startedAt'):
                            if key in row: row[key]=(datetime.fromisoformat(row[key])+timedelta(seconds=delta)).isoformat()
                run=source.result()['runs'][0]
                self.assertIsNone(run['endToEndWallSeconds'])
                self.assertIn('utc_clock_discontinuity_between_spans',run['diagnostics'])
                self.assertEqual(run['leafElapsedByExecutor']['production_model'],8)
                self.assertEqual(run['leafElapsedByExecutor']['deterministic_program'],3)
                self.assertEqual(len(run['workUnits']),4)
                self.assertEqual(run['criticalPath']['activeSeconds'],8)
                self.assertEqual(run['criticalPath']['durationBasis'],'verified_monotonic_dag')

    def test_utc_jump_does_not_exempt_missing_mixed_or_utc_only_clock_evidence(self):
        for fault in ('missing_dependency','mixed_clock','utc_only'):
            with self.subTest(fault=fault):
                source=self.fixture()
                next(e for e in source.rows if e['event']=='stage_finished' and e['spanId']=='source')['recordedAt']='2026-09-29T23:59:50+00:00'
                for row in source.rows:
                    if row.get('spanId')=='join' and fault=='missing_dependency':row['dependsOn']=['missing']
                    if row.get('spanId')=='join' and fault=='mixed_clock':row['clockDomainId']='b'*32
                    if fault=='utc_only':
                        for field in ('clockDomainId','monotonicStartNs','monotonicEndNs'):row.pop(field,None)
                run=source.result()['runs'][0]
                self.assertIsNone(run['criticalPath'])
                self.assertEqual(run['status'],'partial')

    def test_stable_monotonic_spans_do_not_forgive_corrupt_run_boundary_without_jump(self):
        source=self.fixture();source.rows[-1]['recordedAt']='2026-09-30T00:00:07+00:00'
        run=source.result()['runs'][0]
        self.assertIn('span_outside_run_interval',run['diagnostics'])
        self.assertIsNone(run['criticalPath'])

    def test_partial_monotonic_graph_cannot_rescue_utc_discontinuity(self):
        source=self.fixture()
        next(e for e in source.rows if e['event']=='stage_finished' and e['spanId']=='ko')['recordedAt']='2026-09-30T00:00:32+00:00'
        for row in source.rows:
            if row.get('spanId')=='source':
                for field in ('clockDomainId','monotonicStartNs','monotonicEndNs'):row.pop(field,None)
        run=source.result()['runs'][0]
        self.assertIsNone(run['criticalPath'])
        self.assertIn('cross_clock_dependency_timing_unknown',run['diagnostics'])

    def test_mismatched_domain_and_forged_duration_are_not_trusted(self):
        for field,value in [('clockDomainId','b'*32),('monotonicEndNs','1'),('elapsedSeconds',50)]:
            with self.subTest(field=field):
                source=self.fixture();end=next(e for e in source.rows if e['event']=='stage_finished' and e['spanId']=='source');end[field]=value
                run=source.result()['runs'][0]
                self.assertIn('invalid_interval',run['diagnostics']);self.assertEqual(len(run['workUnits']),3)

    def test_cross_process_dependency_clock_is_not_assumed_synchronized(self):
        source=self.fixture()
        for e in source.rows:
            if e.get('spanId')=='join':e['clockDomainId']='b'*32
        run=source.result()['runs'][0]
        self.assertIn('cross_clock_dependency_timing_unknown',run['diagnostics'])
        self.assertEqual(len(run['workUnits']),4);self.assertIsNone(run['criticalPath'])

    def test_writer_clock_identity_changes_after_process_restart(self):
        first=clocks.clock_domain()
        with patch.object(clocks.os,'getpid',return_value=os.getpid()+10000):
            self.assertNotEqual(clocks.clock_domain(),first)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with accounting.accounting_session(root,'clock_fixture'):
                with accounting.stage('measured',depends_on=[]):pass
            rows,_=accounting.read_events(root)
            start=next(e for e in rows if e['event']=='stage_started');end=next(e for e in rows if e['event']=='stage_finished' and e['spanId']==start['spanId'])
            self.assertIsNotNone(clocks.monotonic_interval(start,end))


class ClockPairingTests(unittest.TestCase):
    """Thread stalls between clock reads are not wall-clock steps; real steps still are."""
    STEP_DIAGNOSTICS = {'utc_clock_discontinuity_between_spans', 'utc_clock_discontinuity_local_duration_preserved',
                        'utc_clock_discontinuity_monotonic_anchored_export'}

    def session(self, spans=6, now=None, write_delay=0.0):
        root = Path(tempfile.mkdtemp()); self.addCleanup(__import__('shutil').rmtree, root, True)
        write = accounting._write_event
        def delayed_write(event):
            if event.get('event') == 'stage_finished':
                time.sleep(write_delay)  # a ledger lock or GIL wait after the endpoint
            return write(event)
        with patch.object(accounting, 'now', side_effect=now or accounting.now), \
                patch.object(accounting, '_write_event', side_effect=delayed_write):
            with accounting.accounting_session(root, 'clock_pairing'):
                previous = []
                for i in range(spans):
                    with accounting.stage('paired', depends_on=previous, work_unit_id='unit-%d' % i) as span:
                        previous = [span]
        exported = {row['code'] for row in otlp.export(root)[1]['diagnostics']}
        return set(weekly.project(root)['runs'][0]['diagnostics']) | exported

    def test_stall_between_monotonic_and_utc_reads_is_retried_not_reported(self):
        calls = [0]
        def stalled_now():
            calls[0] += 1
            if calls[0] % 2:
                time.sleep(0.03)  # a GIL hand-off between the two reads
            return datetime.now(timezone.utc).isoformat()
        self.assertFalse(self.session(now=stalled_now) & self.STEP_DIAGNOSTICS)

    def test_delayed_ledger_write_after_endpoint_is_not_a_utc_step(self):
        self.assertFalse(self.session(write_delay=0.03) & self.STEP_DIAGNOSTICS)

    def test_clock_pair_retries_a_split_read_and_keeps_the_tightest_bracket(self):
        # Wide first bracket (a stall), tight second: the second pair wins.
        reads = iter([0, 30_000_000, 40_000_000, 40_200_000])
        with patch.object(accounting.time, 'monotonic_ns', side_effect=lambda: next(reads)), \
                patch.object(accounting, 'now', side_effect=['stalled', 'paired']):
            self.assertEqual(accounting.clock_pair(), (40_100_000, 'paired'))
        # Every bracket wide: bounded retries, the narrowest is kept.
        widths = [9, 3, 7, 5, 8, 6, 4, 9]
        reads = iter([v for k, w in enumerate(widths) for v in (k * 100_000_000, k * 100_000_000 + w * 1_000_000)])
        with patch.object(accounting.time, 'monotonic_ns', side_effect=lambda: next(reads)), \
                patch.object(accounting, 'now', side_effect=['w%d' % k for k in range(8)]):
            self.assertEqual(accounting.clock_pair(), (101_500_000, 'w1'))

    def test_genuine_utc_step_between_spans_is_still_reported(self):
        for step in (30.0, -30.0, 0.05):
            with self.subTest(step=step):
                calls = [0]
                def stepped_now():
                    calls[0] += 1
                    shift = timedelta(seconds=step) if calls[0] > 6 else timedelta()
                    return (datetime.now(timezone.utc) + shift).isoformat()
                self.assertIn('utc_clock_discontinuity_between_spans', self.session(now=stepped_now))
