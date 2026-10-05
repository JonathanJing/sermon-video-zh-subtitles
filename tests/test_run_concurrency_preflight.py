import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from scripts.experiments import run_concurrency_preflight as subject
from scripts.production_concurrency_profile import profile_v1
from scripts.sermon_unified import resources


class DiagnosticCommandDAGTests(unittest.TestCase):
    def setUp(self):
        self.session = MagicMock()
        self.session.environment = {'SPARK_EXCLUSIVE_SESSION_ID': 'fixture-session',
                                    'SPARK_EXCLUSIVE_SESSION_OWNER': 'fixture-owner'}
        self.session.start_job.return_value = {'jobId': 'fixture-job'}
        session_patch = patch.object(subject, '_spark_session', return_value=self.session)
        session_patch.start(); self.addCleanup(session_patch.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.patch = patch.object(subject, 'ROOT', self.root)
        self.patch.start(); self.addCleanup(self.patch.stop)
        self.script = self.root / 'scripts/experiments/fake_diagnostic.py'
        self.script.parent.mkdir(parents=True)
        self.script.write_text('synthetic executor fixture; never execute this file')
        self.out = self.root / 'artifacts/batch'
        self.policy = {'schemaVersion': resources.POLICY_VERSION, 'brokerRoot': str(self.root / 'broker'),
            'capacities': {'cpu': 4, 'online_api': 4, 'codex_cli': 24, 'spark_tts': 1, 'publisher': 1}}
        self.commands = {}

    def node(self, name, kind='study_outline', deps=(), locale=None, inputs=(), manual=False):
        output = self.root / f'artifacts/outputs/{name}.json'
        self.commands[name] = output
        result = {'id': name, 'kind': kind, 'dependsOn': list(deps),
            'command': None if manual else [str(Path(subject.sys.executable)), str(self.script), name],
            'inputs': [str(x) for x in inputs], 'outputs': [str(output)]}
        if locale is not None:
            result['locale'] = locale
        return result

    def prepare(self, nodes):
        return subject.prepare({'profile': profile_v1(), 'resourcePolicy': self.policy, 'nodes': nodes}, self.out)

    def executor(self, command, **kwargs):
        name = command[-1]
        path = self.commands[name]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'node': name}))
        return {'returncode': 0, 'stdout': 'fixture', 'stderr': ''}

    def test_prepare_preflight_and_default_run_never_execute_or_claim_broker(self):
        self.prepare([self.node('source', kind='source')])
        with patch.object(subject.subprocess, 'run') as forbidden:
            result = subject.run(self.out)
            self.assertEqual(result['status'], 'ready')
            self.assertEqual(subject.preflight(self.out), result)
            forbidden.assert_not_called()
        self.assertFalse((self.root / 'broker').exists())
        self.assertFalse((self.out / 'nodes').exists())
        self.assertFalse(result['productionEligible'])

    def test_four_branches_two_study_nodes_dependencies_order_and_cached_resume(self):
        source = self.node('source', kind='source')
        locales = [self.node('l2-' + locale, kind='layer2', deps=('source',), locale=locale,
                            inputs=(self.commands['source'],)) for locale in ('zh-Hans', 'es', 'ko')]
        study = [self.node('study-' + str(i), deps=('source',), inputs=(self.commands['source'],)) for i in range(4)]
        audio = self.node('audio', kind='audio', deps=('l2-es',), locale='es', inputs=(self.commands['l2-es'],))
        self.prepare([source, *locales, *study, audio])
        lock = threading.Lock()
        live = {'all': 0, 'study': 0, 'peak': 0, 'studyPeak': 0}
        calls, completed = [], set()
        def executor(command, **kwargs):
            name = command[-1]
            with lock:
                if name != 'source':
                    self.assertIn('source', completed)
                if name == 'audio':
                    self.assertIn('l2-es', completed)
                live['all'] += 1
                live['study'] += name.startswith('study')
                live['peak'] = max(live['peak'], live['all'])
                live['studyPeak'] = max(live['studyPeak'], live['study'])
                calls.append(name)
            time.sleep(.025)
            response = self.executor(command, **kwargs)
            with lock:
                completed.add(name)
                live['all'] -= 1
                live['study'] -= name.startswith('study')
            return response
        result = subject.run(self.out, execute=True, executor=executor)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(live['peak'], 4)
        self.assertEqual(live['studyPeak'], 2)
        self.assertEqual(result['peakBranches'], 4)
        self.assertEqual(result['peakStudyBranches'], 2)
        before = len(calls)
        resumed = subject.run(self.out, execute=True, executor=executor)
        self.assertEqual(resumed['status'], 'completed')
        self.assertEqual(len(calls), before)
        self.commands['audio'].write_text('tampered')
        with self.assertRaisesRegex(ValueError, 'completed_output_changed'):
            subject.run(self.out, execute=True, executor=executor)
        self.assertEqual(len(calls), before)

    def test_unknown_stops_new_admission_drains_live_and_never_reissues(self):
        nodes = [self.node('l2-' + locale, kind='layer2', locale=locale) for locale in ('zh-Hans', 'es', 'ko')]
        nodes += [self.node('study-one'), self.node('study-two')]
        self.prepare(nodes)
        calls = []
        def executor(command, **kwargs):
            name = command[-1]
            calls.append(name)
            if name == 'l2-zh-Hans':
                time.sleep(.005)
                raise TimeoutError('unknown fixture')
            time.sleep(.03)
            return self.executor(command, **kwargs)
        result = subject.run(self.out, execute=True, executor=executor)
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(len(calls), 4)
        self.assertNotIn('study-two', calls)
        self.assertEqual(result['nodes']['l2-zh-Hans']['status'], 'unknown_outcome')
        self.assertEqual(sum(n['status'] == 'completed' for n in result['nodes'].values()), 3)
        before = list(calls)
        self.assertEqual(subject.run(self.out, execute=True, executor=executor)['reason'], 'reconciliation_required')
        self.assertEqual(calls, before)

    def test_manual_nodes_are_reported_blocked_and_do_not_run(self):
        prepared = self.prepare([self.node('unknown-study', manual=True)])
        self.assertEqual(prepared['status'], 'blocked')
        self.assertEqual(prepared['nodes']['unknown-study']['status'], 'prepared_manual')
        result = subject.run(self.out, execute=True, executor=lambda *a, **k: self.fail('Must not dispatch'))
        self.assertEqual(result['status'], 'blocked')
        self.assertFalse((self.out / 'nodes').exists())

    def test_command_whitelist_cycle_and_owner_lock(self):
        invalid = self.node('unsafe')
        invalid['command'] = ['/bin/sh', '-c', 'echo not permitted']
        self.assertEqual(self.prepare([invalid])['status'], 'blocked')
        other = self.root / 'artifacts/cycle'
        nodes = [self.node('a', deps=('b',)), self.node('b', deps=('a',))]
        with self.assertRaisesRegex(ValueError, 'dependency_cycle'):
            subject.prepare({'profile': profile_v1(), 'resourcePolicy': self.policy, 'nodes': nodes}, other)
        import fcntl
        with (self.out / 'owner.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError, 'already_running'):
                subject.run(self.out, execute=True, executor=self.executor)

    def test_changed_command_or_frozen_input_cannot_dispatch(self):
        source = self.root / 'artifacts/input.json'
        source.parent.mkdir(parents=True); source.write_text('frozen')
        self.prepare([self.node('study', inputs=(source,))])
        source.write_text('changed')
        with self.assertRaisesRegex(ValueError, 'input_identity_changed'):
            subject.run(self.out, execute=True, executor=lambda *a, **k: self.fail('Must not dispatch'))
        source.write_text('frozen'); self.script.write_text('changed implementation')
        with self.assertRaisesRegex(ValueError, 'command_identity_changed'):
            subject.preflight(self.out)

    def test_session_rejection_precedes_any_child_started_or_subprocess(self):
        self.prepare([self.node('source', kind='source')])
        self.session.require_ready.side_effect = ValueError('spark_exclusive_session_required')
        executor = MagicMock()
        with self.assertRaisesRegex(ValueError, 'spark_exclusive_session_required'):
            subject.run(self.out, execute=True, executor=executor)
        executor.assert_not_called()
        self.session.start_job.assert_not_called()
        self.assertFalse((self.out / 'nodes').exists())

    def test_session_token_forwarded_root_hold_released_only_known_terminal(self):
        self.prepare([self.node('source', kind='source')])
        seen = []
        def executor(command, **kwargs):
            seen.append(kwargs['env'])
            self.session.end_job.assert_not_called()
            return self.executor(command, **kwargs)
        subject.run(self.out, execute=True, executor=executor)
        self.assertEqual(seen[0]['SPARK_EXCLUSIVE_SESSION_ID'], 'fixture-session')
        self.assertEqual(seen[0]['SPARK_EXCLUSIVE_SESSION_OWNER'], 'fixture-owner')
        self.session.end_job.assert_called_once_with({'jobId': 'fixture-job'}, process_exited=True,
                                                   outcome='known_terminal')

    def test_root_hold_purpose_uses_session_identifier_charset(self):
        self.prepare([self.node('source', kind='source')])
        subject.run(self.out, execute=True, executor=self.executor)
        purpose = self.session.start_job.call_args.args[0]
        from scripts.spark_exclusive_session import IDENTIFIER
        self.assertRegex(purpose, IDENTIFIER)

    def test_unknown_child_keeps_root_host_hold(self):
        self.prepare([self.node('source', kind='source')])
        subject.run(self.out, execute=True, executor=MagicMock(side_effect=TimeoutError('fixture unknown')))
        self.session.start_job.assert_called_once()
        self.session.end_job.assert_not_called()
