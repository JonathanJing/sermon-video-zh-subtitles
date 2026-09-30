import copy
import json
import os
from pathlib import Path
import tempfile
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
                self.assertIsNone(run['endToEndWallSeconds']);self.assertIsNone(run['criticalPath'])
                self.assertIn('utc_clock_discontinuity_local_duration_preserved',run['diagnostics'])
                self.assertEqual(len(run['workUnits']),4)
                safe_export.export(source.root,source.root/'export')
                self.assertEqual(weekly.project(source.root/'export')['runs'][0],run)
                payload,diag=otlp.export(source.root)
                stage=next(s for s in payload['resourceSpans'][0]['scopeSpans'][0]['spans'] if s['spanId']==otlp.span_id(('run','stage','source')))
                self.assertEqual(int(stage['endTimeUnixNano'])-int(stage['startTimeUnixNano']),2_000_000_000)
                attrs={a['key']:a['value'] for a in stage['attributes']}
                self.assertEqual(attrs['sermon.exportEndTimeBasis'],{'stringValue':'monotonic_anchored_estimate'})

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
