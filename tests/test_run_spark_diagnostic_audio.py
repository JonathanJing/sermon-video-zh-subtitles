"""Wrapper admission and dispatch construction, no SSH/container/model calls."""
import json
from pathlib import Path
import subprocess
import socket
import os
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch, MagicMock

from scripts.experiments import run_spark_diagnostic_audio as subject


class SparkAudioWrapperTests(unittest.TestCase):
    def setUp(self):
        self.session = MagicMock()
        self.session.environment = {'SPARK_EXCLUSIVE_SESSION_ID': 'fixture-session',
                                    'SPARK_EXCLUSIVE_SESSION_OWNER': 'fixture-owner'}
        self.session.start_job.return_value = {'jobId': 'fixture-job'}
        session_patch = patch.object(subject, '_spark_session', return_value=self.session)
        session_patch.start(); self.addCleanup(session_patch.stop)
        temp = tempfile.TemporaryDirectory(dir=subject.ROOT / 'artifacts', prefix='test-spark-wrapper-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.args = SimpleNamespace(fixture=self.root / 'fixture', layer2_out=self.root / 'layer2',
            out=self.root / 'audio', media=self.root / 'source.mp4', registry=subject.ROOT / 'config/speaker-voice-registry.json',
            remote_stage=Path('/home/achillesjing/dgx-spark-benchmark/results/next-concurrency-fixture'))
        self.args.fixture.mkdir(); self.args.layer2_out.mkdir()
        self.args.media.write_bytes(b'media')
        self.proof = {'status': 'ready_for_explicit_dispatch', 'targetLocale': 'zh-Hans',
            'sourceMediaSha256': subject.inputs.sha(self.args.media), 'sourceWindow': {'startSeconds': 0, 'endSeconds': 1},
            'groups': 1, 'sourceUnits': 1, 'checkpointSha256': 'a' * 64}

    def test_docker_argv_preserves_mac_path_shared_broker_gpu1_and_actual_profile(self):
        tts, asr = subject.docker_commands(self.args)
        self.assertIn(str(self.args.remote_stage) + ':' + str(subject.ROOT), tts)
        self.assertIn(subject.BROKER + ':/shared-gpu', tts)
        self.assertIn(subject.BROKER + ':/shared-gpu', asr)
        self.assertEqual(tts[tts.index('--replicas') + 1], '8')
        self.assertEqual(tts[tts.index('--cpu-workers') + 1], '4')
        self.assertEqual(asr[asr.index('--batch-size') + 1], '8')
        self.assertIn('PATH=/media-tools/bin:/usr/local/bin:/usr/bin:/bin', tts)
        self.assertIn('1000:1000', tts)
        self.assertEqual(tts[tts.index('--entrypoint') + 1], '/usr/bin/python')
        self.assertIn(subject.IMAGES['tts'], tts)
        self.assertIn(subject.IMAGES['asr'], asr)

    def test_pending_layer2_starts_no_remote_or_local_dispatch(self):
        with patch.object(subject, 'preflight', return_value={**self.proof, 'status': 'awaiting_layer2'}), \
             patch.object(subject, 'run') as remote:
            with self.assertRaisesRegex(ValueError, 'layer2_admission_required'):
                subject.execute(self.args)
        remote.assert_not_called()
        self.assertFalse(self.args.out.exists())

    def test_unknown_dispatch_refuses_before_network_or_releasing_resources(self):
        self.args.out.mkdir()
        (self.args.out / 'dispatch.started.json').write_text('{}')
        with patch.object(subject, 'preflight', return_value=self.proof), patch.object(subject, 'run') as remote:
            with self.assertRaisesRegex(ValueError, 'unknown_spark_dispatch_requires_reconciliation'):
                subject.execute(self.args)
        remote.assert_not_called()

    def test_staged_code_drift_blocks_before_model_dispatch(self):
        response = subprocess.CompletedProcess([], 0, stdout=json.dumps({'files': {
            'scripts/experiments/run_spark_diagnostic_audio.py': '0' * 64}}))
        with patch.object(subject, 'preflight', return_value=self.proof), \
             patch.object(subject, 'run', return_value=response) as remote:
            with self.assertRaisesRegex(ValueError, 'remote_code_differs'):
                subject.execute(self.args)
        self.assertEqual(remote.call_count, 1)
        self.assertFalse((self.args.out / 'dispatch.started.json').exists())

    def test_ssh_uncertainty_preserves_started_and_cannot_retry(self):
        code = {'scripts/experiments/run_spark_diagnostic_audio.py': subject.inputs.sha(Path(subject.__file__))}
        def run(argv, **kwargs):
            if kwargs.get('capture_output'):
                return subprocess.CompletedProcess(argv, 0, stdout=json.dumps({'files': code}))
            if 'whole-audio-dispatch.lock' in argv[-1]:
                raise subprocess.CalledProcessError(255, argv)
            return subprocess.CompletedProcess(argv, 0)
        with patch.object(subject, 'preflight', return_value=self.proof), patch.object(subject, 'run', side_effect=run):
            with self.assertRaises(subprocess.CalledProcessError):
                subject.execute(self.args)
        self.assertTrue((self.args.out / 'dispatch.started.json').exists())
        self.assertFalse((self.args.out / 'result.json').exists())
        with patch.object(subject, 'preflight', return_value=self.proof), patch.object(subject, 'run') as remote:
            with self.assertRaisesRegex(ValueError, 'unknown_spark_dispatch'):
                subject.execute(self.args)
        remote.assert_not_called()

    def test_session_rejection_precedes_remote_staging_and_docker(self):
        self.session.require_ready.side_effect = ValueError('spark_competition_not_released')
        with patch.object(subject, 'preflight', return_value=self.proof), patch.object(subject, 'run') as remote:
            with self.assertRaisesRegex(ValueError, 'spark_competition_not_released'):
                subject.execute(self.args)
        remote.assert_not_called()
        self.session.start_job.assert_not_called()
        self.assertFalse((self.args.out / 'dispatch.started.json').exists())

    def test_session_containers_carry_owner_and_job_labels(self):
        for command in subject.docker_commands(self.args, self.session, {'jobId': 'fixture-job'}):
            for label in ('tongxing.spark.session=fixture-session', 'tongxing.spark.owner=fixture-owner',
                          'tongxing.spark.job=fixture-job'):
                self.assertIn(label, command)

    def test_readonly_gateway_checks_live_admission_and_rejects_write_or_wrong_owner(self):
        self.session.require_ready.return_value = {'status': 'running', 'sessionId': 'fixture-session'}
        if not hasattr(socket, 'SO_PEERCRED') and not hasattr(socket.socket, 'getpeereid'):
            uid_patch = patch.object(subject.AdmissionGateway, 'peer_uid', return_value=os.getuid())
            uid_patch.start(); self.addCleanup(uid_patch.stop)
        gateway_temp = tempfile.TemporaryDirectory(prefix='spark-gw-', dir='/tmp')
        self.addCleanup(gateway_temp.cleanup)
        self.session.request.return_value = {'session': {'jobs': {'fixture-job': {'jobId': 'fixture-job',
            'status': 'active', 'sessionId': 'fixture-session', 'owner': 'fixture-owner',
            'processes': [{'pid': os.getpid(), 'startTicks': 42}]}}},
            'inventory': {'processes': [{'pid': os.getpid(), 'startTicks': 42}]}}
        gateway = subject.AdmissionGateway(Path(gateway_temp.name) / 'gateway', self.session, {'jobId': 'fixture-job'})
        self.addCleanup(gateway.close)
        def request(payload):
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as channel:
                channel.settimeout(5); channel.connect(str(gateway.path))
                channel.sendall(json.dumps(payload).encode() + b'\n')
                return json.loads(channel.makefile('rb').readline(65537))
        valid = {'action': 'require', 'session_id': 'fixture-session', 'owner': 'fixture-owner'}
        first = request(valid)['result']
        self.assertEqual(first['status'], 'running')
        self.assertEqual(first['jobId'], 'fixture-job')
        from scripts.spark_exclusive_session import Client
        with patch.dict(os.environ, {'SPARK_EXCLUSIVE_SOCKET': str(gateway.path)}), \
             patch('scripts.spark_exclusive_session.subprocess.run') as no_ssh:
            result = Client('fixture-session', 'fixture-owner').require_ready()
            self.assertEqual(result['status'], 'running')
            no_ssh.assert_not_called()
        self.assertEqual(self.session.require_ready.call_count, 2)
        self.assertIn('error', request({**valid, 'action': 'finish'}))
        self.assertIn('error', request({**valid, 'owner': 'other-owner'}))
        self.assertEqual(self.session.require_ready.call_count, 2)
        with patch.object(gateway, 'peer_uid', return_value=os.getuid() + 1):
            self.assertIn('error', request(valid))
        self.session.request.return_value['inventory']['processes'][0]['startTicks'] = 43
        self.assertIn('error', request(valid))
        self.assertEqual(self.session.require_ready.call_count, 2)
        self.session.request.return_value['inventory']['processes'][0]['startTicks'] = 42
        self.session.request.return_value['session']['jobs']['fixture-job']['status'] = 'terminal'
        self.assertIn('error', request(valid))
        self.assertEqual(self.session.require_ready.call_count, 2)
        self.session.request.return_value['session']['jobs']['fixture-job']['status'] = 'active'
        self.session.require_ready.side_effect = ValueError('external competition')
        self.assertIn('error', request(valid))

    def test_remote_runner_binds_host_pid_before_gateway_and_docker(self):
        compile(subject.REMOTE_RUNNER, '<frozen-remote-runner>', 'exec')
        self.assertLess(subject.REMOTE_RUNNER.index('session.bind_job'), subject.REMOTE_RUNNER.index('AdmissionGateway(c['))
        self.assertLess(subject.REMOTE_RUNNER.index('gateway=AdmissionGateway'), subject.REMOTE_RUNNER.index('subprocess.run(argv'))
        self.assertIn('finally:gateway.close()', subject.REMOTE_RUNNER)
        self.assertNotIn('session.end_job', subject.REMOTE_RUNNER)
