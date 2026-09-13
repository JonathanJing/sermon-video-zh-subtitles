"""Run the launcher with disposable children, without real models or network ports."""
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest


class RunLocalSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'scripts').mkdir()
        self.bin = self.root / '.venv/bin'
        self.bin.mkdir(parents=True)
        (self.root / 'model').mkdir()
        shutil.copyfile(Path(__file__).resolve().parents[2] / 'scripts/run-local.sh',
                        self.root / 'scripts/run-local.sh')
        self.executable('python', '''
import os, pathlib, sys, time
root = pathlib.Path.cwd()
if sys.argv[1] == '-c':
    if (root / 'fail_once').exists():
        (root / 'fail_once').unlink()
        (root / 'probe_failed').touch()
        sys.exit(1)
    sys.exit(0 if (root / 'ready').exists() else 1)
with (root / 'gateways').open('a') as f: f.write(str(os.getpid()) + '\\n')
while True:
    if (root / 'restart').exists():
        (root / 'restart').unlink()
        sys.exit(75)
    time.sleep(.02)
''')
        self.executable('mlx_audio.server', '''
import os, pathlib, signal, time
root = pathlib.Path.cwd()
signal.signal(signal.SIGTERM, signal.SIG_IGN)
with (root / 'models').open('a') as f: f.write(str(os.getpid()) + '\\n')
if not (root / 'never_ready').exists(): (root / 'ready').touch()
while True: time.sleep(.05)
''')
        self.executable('npm', 'import time\nwhile True: time.sleep(.05)\n')
        self.process = None

    def executable(self, name, body):
        path = self.bin / name
        path.write_text(f'#!{sys.executable}\n' + body)
        path.chmod(0o755)

    def start(self):
        env = dict(os.environ, PATH=f'{self.bin}:{os.environ["PATH"]}',
                   LOCAL_LIVE_ASR_PROVIDER='qwen-mlx-websocket',
                   LOCAL_LIVE_QWEN_ASR_MODEL=str(self.root / 'model'),
                   LOCAL_LIVE_RUNTIME_LOG_ROOT=str(self.root / 'logs'),
                   TMPDIR=str(self.root))
        self.output = (self.root / 'output').open('w')
        self.process = subprocess.Popen(['bash', 'scripts/run-local.sh'], cwd=self.root,
                                        env=env, start_new_session=True,
                                        stdout=self.output, stderr=subprocess.STDOUT)

    def lines(self, name):
        path = self.root / name
        return path.read_text().splitlines() if path.exists() else []

    def until(self, predicate, timeout=6):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate(): return
            time.sleep(.05)
        self.fail((self.root / 'output').read_text())

    def tearDown(self):
        if self.process is not None:
            # Kill only the disposable fixture process group.
            try: os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            self.process.wait(timeout=5)
            self.output.close()
        self.temp.cleanup()

    def test_gateway_restarts_while_owned_model_is_alive_but_unreachable(self):
        self.start()
        self.until(lambda: len(self.lines('gateways')) == 1)
        first_model = int(self.lines('models')[0])
        (self.root / 'never_ready').touch()
        (self.root / 'ready').unlink()
        (self.root / 'restart').touch()
        self.until(lambda: len(self.lines('gateways')) == 2, timeout=4)
        os.kill(first_model, 0)
        self.until(lambda: len(self.lines('models')) == 2, timeout=13)
        # The replacement is still warming up: Gateway restart stays independent.
        (self.root / 'restart').touch()
        self.until(lambda: len(self.lines('gateways')) == 3, timeout=4)
        (self.root / 'ready').touch()
        self.until(lambda: 'MLX Audio recovered.' in (self.root / 'output').read_text())
        with self.assertRaises(ProcessLookupError): os.kill(first_model, 0)
        self.assertIsNone(self.process.poll())

    def test_one_failed_probe_does_not_restart_owned_model(self):
        self.start()
        self.until(lambda: len(self.lines('gateways')) == 1)
        (self.root / 'fail_once').touch()
        self.until(lambda: (self.root / 'probe_failed').exists())
        self.until(lambda: 'MLX Audio recovered.' in (self.root / 'output').read_text())
        self.assertEqual(len(self.lines('models')), 1)
        os.kill(int(self.lines('models')[0]), 0)
        self.assertNotIn('stopping it before recovery', (self.root / 'output').read_text())

    def test_external_model_outage_does_not_spawn_or_kill_a_model(self):
        (self.root / 'ready').touch()
        self.start()
        self.until(lambda: len(self.lines('gateways')) == 1)
        (self.root / 'ready').unlink()
        (self.root / 'restart').touch()
        self.until(lambda: len(self.lines('gateways')) == 2, timeout=4)
        self.until(lambda: 'External MLX Audio unavailable' in (self.root / 'output').read_text())
        self.assertEqual(self.lines('models'), [])
        (self.root / 'ready').touch()
        self.until(lambda: 'MLX Audio recovered.' in (self.root / 'output').read_text())
        self.assertIsNone(self.process.poll())

    def test_startup_timeout_cleans_up_unresponsive_owned_model(self):
        # Accelerate sleep only: retain all 120 startup probes and real cleanup.
        self.executable('sleep', 'import time\ntime.sleep(.001)\n')
        (self.root / 'never_ready').touch()
        self.start()
        self.until(lambda: self.process.poll() is not None, timeout=15)
        self.assertEqual(self.process.returncode, 1)
        self.assertEqual(self.lines('gateways'), [])
        self.assertEqual(len(self.lines('models')), 1)
        with self.assertRaises(ProcessLookupError): os.kill(int(self.lines('models')[0]), 0)
        self.assertIn('did not become ready', (self.root / 'output').read_text())


if __name__ == '__main__':
    unittest.main()
