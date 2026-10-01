"""Offline route tests; production media/cache validation stays independently tested."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import run_weekly_dubbing as runner
import test_weekly_accounting as accounting_tests


class SparkFirstTTSTests(unittest.TestCase):
    setUp = accounting_tests.WeeklyAccountingTests.setUp
    fixture = accounting_tests.WeeklyAccountingTests.fixture

    def local_checkpoint(self, tmp):
        checkpoint = Path(tmp) / 'checkpoint'; checkpoint.mkdir()
        (checkpoint / 'model.safetensors').write_bytes(b'weights')
        sys.argv += ['--local-checkpoint', str(checkpoint), '--local-python', '/fixture/local-python']
        return checkpoint

    def local_command(self, f, argv, **kwargs):
        if len(argv) > 1 and Path(argv[1]).name == 'render_weekly_audio.py':
            out = Path(argv[argv.index('--out') + 1]); out.mkdir(exist_ok=True)
            job = runner.read(f.work / 'job.json')
            identity = runner.render_identity(f.work / 'job.json', job['voice']['checkpointSha256'], device='mps')
            runner.write_json(out / 'identity.json', identity)
            for i, unit in enumerate(job['units']):
                wav = out / f'unit-{i:04d}.wav'; wav.write_bytes(b'fake local WAV')
                runner.write_json(wav.with_suffix('.json'), {'unit': unit, 'identity': identity, 'sha256': runner.sha256(wav), 'durationSeconds': 1})
            raw = out / 'chinese.raw.wav'; raw.write_bytes(b'fake local track')
            runner.write_json(out / 'report.json', {**identity, 'status': 'complete_candidate_render', 'sha256': runner.sha256(raw), 'generationSeconds': 3})
            return subprocess.CompletedProcess(argv, 0)
        return f.command(argv, **kwargs)

    def hash_mock(self):
        original = runner.sha256
        return patch.object(runner, 'sha256', side_effect=lambda path: 'fixture-checkpoint' if Path(path).name == 'model.safetensors' else original(path))

    def test_default_healthy_spark_never_runs_available_mac(self):
        with tempfile.TemporaryDirectory() as tmp, self.fixture(tmp) as f:
            self.local_checkpoint(tmp)
            runner.main()
            self.assertFalse(any(len(row['argv']) > 1 and Path(row['argv'][1]).name == 'render_weekly_audio.py' for row in f.commands))
            receipt = runner.read(f.work / 'accounting/tts-routing.json')
            self.assertEqual(receipt['executionBackend'], 'dgx_spark_cuda')

    def test_connection_failure_before_model_falls_back_to_isolated_mps(self):
        with tempfile.TemporaryDirectory() as tmp, self.fixture(tmp) as f, self.hash_mock():
            self.local_checkpoint(tmp)
            failed = False
            def command(argv, **kwargs):
                nonlocal failed
                if 'docker ps' in argv[-1] and not failed:
                    failed = True
                    raise subprocess.CalledProcessError(255, argv)
                return self.local_command(f, argv, **kwargs)
            f.process.side_effect = command
            runner.main()
            route = runner.read(f.work / 'accounting/tts-routing.json')
            self.assertEqual(route['executionBackend'], 'macbook_mps')
            self.assertIn('Spark', route['fallbackReason'])
            self.assertFalse((f.work / 'local-render-mps').exists())

    def test_confirmed_idle_runtime75_can_fallback_but_quality_failure_cannot(self):
        for code in (75, 1):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as tmp, self.fixture(tmp) as f, self.hash_mock():
                self.local_checkpoint(tmp)
                def command(argv, **kwargs):
                    if '/work/render_weekly_audio.py' in argv[-1]:
                        raise subprocess.CalledProcessError(code, argv)
                    return self.local_command(f, argv, **kwargs)
                f.process.side_effect = command
                if code == 75:
                    runner.main()
                    self.assertEqual(runner.read(f.work / 'accounting/tts-routing.json')['executionBackend'], 'macbook_mps')
                else:
                    with self.assertRaises(subprocess.CalledProcessError):
                        runner.main()
                    self.assertFalse((f.work / 'local-render-mps').exists())

    def test_remote_disconnect_after_dispatch_never_starts_mac(self):
        with tempfile.TemporaryDirectory() as tmp, self.fixture(tmp) as f:
            self.local_checkpoint(tmp)
            def command(argv, **kwargs):
                if '/work/render_weekly_audio.py' in argv[-1]:
                    raise subprocess.CalledProcessError(255, argv)
                return f.command(argv, **kwargs)
            f.process.side_effect = command
            with self.assertRaises(runner.RemoteOutcomeUnknown):
                runner.main()
            self.assertFalse((f.work / 'local-render-mps').exists())

    def test_forced_spark_outage_never_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp, self.fixture(tmp) as f:
            self.local_checkpoint(tmp); sys.argv += ['--tts-backend', 'spark']
            f.process.side_effect = subprocess.CalledProcessError(255, 'ssh')
            with self.assertRaises(subprocess.CalledProcessError):
                runner.main()
            self.assertFalse((f.work / 'local-render-mps').exists())

    def test_forced_mac_never_contacts_spark(self):
        with tempfile.TemporaryDirectory() as tmp, self.fixture(tmp) as f, self.hash_mock():
            self.local_checkpoint(tmp); sys.argv += ['--tts-backend', 'macbook']
            f.process.side_effect = lambda argv, **kwargs: self.local_command(f, argv, **kwargs)
            runner.main()
            self.assertFalse(any(row['argv'][0] in ('ssh', 'scp') for row in f.commands))
            self.assertEqual(runner.read(f.work / 'accounting/tts-routing.json')['executionBackend'], 'macbook_mps')

    def test_cuda_partial_prevents_mac_fallback(self):
        with tempfile.TemporaryDirectory() as tmp, self.fixture(tmp) as f:
            self.local_checkpoint(tmp)
            out = f.work / 'render'; out.mkdir()
            job = runner.read(f.work / 'job.json')
            runner.write_json(out / 'identity.json', runner.render_identity(f.work / 'job.json', job['voice']['checkpointSha256']))
            f.process.side_effect = subprocess.CalledProcessError(255, 'ssh')
            with self.assertRaises(subprocess.CalledProcessError):
                runner.main()
            self.assertFalse((f.work / 'local-render-mps').exists())
            self.assertTrue((out / 'identity.json').exists())

    def test_changed_job_prevents_mac_fallback(self):
        with tempfile.TemporaryDirectory() as tmp, self.fixture(tmp) as f:
            self.local_checkpoint(tmp)
            def command(argv, **kwargs):
                if 'docker ps' in argv[-1]:
                    (f.work / 'job.json').write_text('{}')
                    raise subprocess.CalledProcessError(255, argv)
                return f.command(argv, **kwargs)
            f.process.side_effect = command
            with self.assertRaisesRegex(ValueError, 'job changed'):
                runner.main()
            self.assertFalse((f.work / 'local-render-mps').exists())

    def test_oom_after_cuda_unit_preserves_backend_and_never_starts_mac(self):
        with tempfile.TemporaryDirectory() as tmp, self.fixture(tmp) as f:
            self.local_checkpoint(tmp)
            def command(argv, **kwargs):
                if '/work/render_weekly_audio.py' in argv[-1]:
                    raise subprocess.CalledProcessError(75, argv)
                if " -maxdepth 1 -name 'unit-*'" in argv[-1]:
                    return subprocess.CompletedProcess(argv, 0, stdout='/remote/render/unit-0000.json\n')
                return f.command(argv, **kwargs)
            f.process.side_effect = command
            with self.assertRaisesRegex(ValueError, 'CUDA unit artifacts'):
                runner.main()
            self.assertFalse((f.work / 'local-render-mps').exists())
            state = runner.read(f.work / 'accounting/harness/remote-attempt.json')
            self.assertEqual(state['status'], 'runtime_failed_preserve_partial')

    def test_partial_probe_disconnect_is_unknown_and_never_starts_mac(self):
        with tempfile.TemporaryDirectory() as tmp, self.fixture(tmp) as f:
            self.local_checkpoint(tmp)
            def command(argv, **kwargs):
                if '/work/render_weekly_audio.py' in argv[-1]:
                    raise subprocess.CalledProcessError(75, argv)
                if " -maxdepth 1 -name 'unit-*'" in argv[-1]:
                    raise subprocess.CalledProcessError(255, argv)
                return f.command(argv, **kwargs)
            f.process.side_effect = command
            with self.assertRaises(subprocess.CalledProcessError):
                runner.main()
            self.assertFalse((f.work / 'local-render-mps').exists())

    def test_remote_cuda_partial_state_blocks_forced_mac_on_resume(self):
        with tempfile.TemporaryDirectory() as tmp, self.fixture(tmp) as f:
            self.local_checkpoint(tmp); sys.argv += ['--tts-backend', 'macbook']
            state = f.work / 'accounting/harness/remote-attempt.json'
            state.parent.mkdir(parents=True, exist_ok=True)
            runner.atomic_json(state, {'jobSha256': runner.sha256(f.work / 'job.json'),
                                      'status': 'runtime_failed_preserve_partial'})
            with self.assertRaisesRegex(ValueError, 'remote CUDA units'):
                runner.main()
            self.assertFalse((f.work / 'local-render-mps').exists())
            self.assertEqual(f.commands, [])
