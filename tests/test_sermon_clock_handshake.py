"""Real local processes only; no API, model, media or transport calls."""
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import sermon_accounting as accounting
from scripts import sermon_clock_evidence as clock
from scripts import sermon_log_profile as profile
from scripts import sermon_dag_evidence as evidence
from scripts import weekly_pipeline_report as report


CHILD = '''
import json,sys
from pathlib import Path
from scripts import sermon_accounting as accounting
from scripts import sermon_clock_evidence as clock
launch,dependency=json.loads(Path(sys.argv[1]).read_text())
with accounting.accounting_session(Path(sys.argv[2]),'clock.child'):
    started=clock.worker_started(launch)
    with accounting.stage('clock.child.work',depends_on=[dependency],work_unit_id='child.work'):
        sum(range(100))
    finished=clock.worker_finished(started)
    Path(sys.argv[3]).write_text(json.dumps(finished))
'''


class ClockHandshakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def execute(self, join=True):
        with profile.session(self.root / 'logs', 'clock.parent', work_kind='control',
                             evidence_mode='synthetic') as session:
            with accounting.stage('clock.source', depends_on=[], work_unit_id='source') as source:
                pass
            with accounting.stage('clock.launcher', depends_on=[source], work_unit_id='worker') as launcher:
                launch = clock.worker_launch(launcher)
                request = self.root / 'request.json'; request.write_text(json.dumps([launch, source]))
                output = self.root / 'result.json'
                subprocess.run([sys.executable, '-c', CHILD, str(request), str(self.root / 'logs'), str(output)],
                               env=accounting.subprocess_environment(), check=True, timeout=30)
                finished = json.loads(output.read_text())
                joined = clock.worker_joined(launch, finished) if join else None
            terminal = evidence.current_terminal_leaves(launcher)
        return session, launch, finished, joined, terminal

    def test_real_subprocess_comparable_without_merging_process_domains(self):
        session, launch, finished, joined, terminal = self.execute()
        self.assertNotEqual(launch['clockParentDomainSha256'], finished['clockChildDomainSha256'])
        self.assertEqual(clock.validate_worker_handshake(launch, finished, joined), joined)
        events, errors = accounting.read_events(self.root / 'logs'); self.assertFalse(errors)
        self.assertEqual(len(clock.handshake_windows(events, session['runId'])), 1)
        self.assertEqual(len(terminal), 1)
        starts = {row['spanId']: row for row in events if row['event'] == 'stage_started'}
        self.assertEqual(starts[terminal[0]]['stage'], 'clock.child.work')
        result = report.project(self.root / 'logs')
        self.assertEqual(result['status'], 'projected', result['runs'][0]['diagnostics'])
        self.assertIsNotNone(result['runs'][0]['criticalPath'])

    def test_real_handshake_utc_jump_preserves_independent_monotonic_path_only(self):
        session,_,_,_,_=self.execute()
        events,errors=accounting.read_events(self.root/'logs');self.assertFalse(errors)
        end=next(e for e in events if e['event']=='stage_finished' and e['stage']=='clock.source')
        end['recordedAt']=(datetime.fromisoformat(end['recordedAt'])-timedelta(seconds=30)).isoformat().replace('+00:00','Z')
        run=report.project_run(session['runId'],events)
        self.assertEqual(run['status'],'partial')
        self.assertIsNone(run['endToEndWallSeconds'])
        self.assertIn('utc_clock_discontinuity_local_duration_preserved',run['diagnostics'])
        self.assertEqual(run['criticalPath']['durationBasis'],'verified_monotonic_dag')
        cross=run['telemetryEvidence']['cross']
        self.assertEqual(cross['status'],'verified_recorded_edges')
        self.assertGreater(cross['recordedCrossProcessEdges'],0)
        self.assertEqual(cross['verifiedCrossProcessEdges'],cross['recordedCrossProcessEdges'])
        self.assertEqual(run['telemetryEvidence']['queue']['resourceQueueStatus'],'not_established')
        for missing_phase in ('clock.worker_launch_v1','clock.worker_started_v1','clock.worker_finished_v1','clock.worker_joined_v1'):
            changed=[e for e in events if e.get('stage')!=missing_phase]
            failed=report.project_run(session['runId'],changed)
            self.assertIsNone(failed['criticalPath'])
            self.assertIn('cross_clock_dependency_timing_unknown',failed['diagnostics'])
            self.assertNotEqual(failed['telemetryEvidence']['cross']['status'],'verified_recorded_edges')

    def test_missing_join_preserves_unknown_cross_clock(self):
        self.execute(join=False)
        run = report.project(self.root / 'logs')['runs'][0]
        self.assertIsNone(run['criticalPath'])
        self.assertIn('cross_clock_parent_timing_unknown', run['diagnostics'])

    def test_changed_or_inverted_proofs_rejected_and_replay_is_pure(self):
        _, launch, finished, joined, _ = self.execute()
        with patch.object(clock.time, 'monotonic_ns', side_effect=AssertionError('replay cannot sample clock')):
            self.assertEqual(clock.validate_worker_handshake(launch, finished, joined), joined)
        for changed in ({**finished, 'clockIdentitySha256': '0'*64},
                        {**finished, 'clockChildEndNs': 0}, {**finished, 'extra': 'unsafe'}):
            with self.assertRaises(ValueError): clock.validate_worker_handshake(launch, changed, joined)

    def test_conflicting_or_cross_run_fact_confers_no_trust(self):
        session, _, _, _, _ = self.execute()
        rows, _ = accounting.read_events(self.root / 'logs')
        joined = next(row for row in rows if row.get('stage') == 'clock.worker_joined_v1')
        conflict = {**joined, 'metrics': {**joined['metrics'], 'clockParentEndNs': joined['metrics']['clockParentEndNs'] + 1}}
        self.assertFalse(clock.handshake_windows([*rows, conflict], session['runId']))
        invalid = {**joined, 'metrics': {**joined['metrics'], 'clockParentEndNs': 'invalid'}}
        self.assertFalse(clock.handshake_windows([*rows, invalid], session['runId']))
        self.assertFalse(clock.handshake_windows(rows, 'another-run'))


class TerminalLeafTests(unittest.TestCase):
    def rows(self):
        starts = [dict(runId='run', spanId='wrapper', parentSpanId=None, event='stage_started',
                       stage='wrapper', dependsOn=[], executorType='deterministic_program'),
                  dict(runId='run', spanId='a', parentSpanId='wrapper', event='stage_started',
                       stage='a', dependsOn=[], executorType='deterministic_program'),
                  dict(runId='run', spanId='b', parentSpanId='wrapper', event='stage_started',
                       stage='b', dependsOn=['a'], executorType='deterministic_program')]
        return starts + [{**row, 'event': 'stage_finished', 'status': 'completed'} for row in starts]

    def test_only_actual_terminal_leaf_not_wrapper(self):
        self.assertEqual(evidence.terminal_leaves(self.rows(), 'run', 'wrapper'), ['b'])

    def test_incomplete_failed_or_uninstrumented_leaf_not_completion(self):
        rows = self.rows()
        for changed in (rows[:-1], [dict(row, status='failed') if row.get('event') == 'stage_finished' else row for row in rows],
                        [dict(row, dependsOn=None) if row['spanId'] == 'b' else row for row in rows]):
            with self.assertRaises(ValueError): evidence.terminal_leaves(changed, 'run', 'wrapper')
