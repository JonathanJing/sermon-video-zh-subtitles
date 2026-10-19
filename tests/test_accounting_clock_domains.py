import copy
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
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


class ClockPairTests(unittest.TestCase):
    """A stage's monotonic and UTC readings must describe one instant."""

    def record(self, root, stages=12):
        with accounting.accounting_session(root,'clock_pair_fixture'):
            previous=None
            for index in range(stages):
                name=f'unit.{index}'
                with accounting.stage(name,work_unit_id=name,depends_on=[] if previous is None else [previous]) as span:pass
                previous=span
        return weekly.project(root)['runs']

    def assert_projected(self, runs):
        self.assertTrue(runs)
        for run in runs:
            self.assertNotIn('utc_clock_discontinuity_between_spans',run['diagnostics'])
            self.assertEqual(run['status'],'projected',run['diagnostics'])

    def test_switch_between_paired_reads_does_not_spread_utc_offset(self):
        # Virtual clocks: every other UTC read stalls 30 ms, as a thread or GIL
        # switch between the monotonic and UTC reads would on a saturated host.
        virtual=[0];calls=[0];epoch=datetime.fromisoformat('2026-10-19T00:00:00+00:00')
        def monotonic_ns():
            virtual[0]+=1_000;return virtual[0]
        def now():
            calls[0]+=1
            if calls[0]%2:virtual[0]+=30_000_000
            return (epoch+timedelta(microseconds=virtual[0]//1_000)).isoformat()
        fake_time=SimpleNamespace(monotonic_ns=monotonic_ns,monotonic=lambda:monotonic_ns()/1e9)
        with tempfile.TemporaryDirectory() as tmp, patch.object(accounting,'time',fake_time), \
                patch.object(accounting,'now',now):
            self.assert_projected(self.record(Path(tmp)))
        self.assertGreater(calls[0],0)

    def test_cpu_contention_does_not_spread_utc_offset(self):
        stop=threading.Event()
        def burn():
            while not stop.is_set():sum(i*i for i in range(1_000))
        burners=[threading.Thread(target=burn,daemon=True) for _ in range(4)]
        for thread in burners:thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                runs=self.record(Path(tmp),stages=4)
        finally:
            stop.set()
            for thread in burners:thread.join()
        self.assert_projected(runs)

    def test_wide_bracket_is_retried_and_tightest_pair_kept(self):
        readings=iter([0,5_000_000, 10_000_000,10_000_100])
        with patch.object(accounting,'time',SimpleNamespace(monotonic_ns=lambda:next(readings))), \
                patch.object(accounting,'now',side_effect=['first','second']):
            self.assertEqual(accounting.clock_pair(),(10_000_050,'second'))
