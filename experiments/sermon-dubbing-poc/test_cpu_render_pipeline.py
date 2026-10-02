"""Offline overlap/recovery checks, with real PCM files and fake model calls."""
from concurrent.futures import ThreadPoolExecutor
import contextlib
import io
import json
import math
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import wave

from bounded_cpu_pipeline import BoundedCpuPipeline
import render_weekly_audio as renderer


class CpuQueueTests(unittest.TestCase):
    def test_cpu_write_overlaps_producer_and_drain_waits(self):
        started, release, finished = threading.Event(), threading.Event(), threading.Event()
        def save():
            started.set()
            if not release.wait(2):
                raise AssertionError("producer never ran during pending CPU work")
            finished.set()
        with BoundedCpuPipeline(workers=1, max_pending=2) as queue:
            queue.submit(save)
            self.assertTrue(started.wait(2))
            self.assertFalse(finished.is_set())
            # This is the producer/model slot running while the CPU task waits.
            release.set()
        self.assertTrue(finished.is_set())

    def test_pending_limit_applies_backpressure(self):
        started, release = threading.Event(), threading.Event()
        queue = BoundedCpuPipeline(workers=1, max_pending=1)
        def save():
            started.set()
            self.assertTrue(release.wait(2))
        with queue, ThreadPoolExecutor(max_workers=1) as producer:
            queue.submit(save)
            self.assertTrue(started.wait(2))
            second = producer.submit(queue.submit, lambda: 2)
            self.assertFalse(second.done())
            release.set()
            self.assertEqual(second.result(timeout=2).result(timeout=2), 2)
        self.assertEqual(queue.stats['peakPending'], 1)

    def test_cpu_failure_blocks_more_admission(self):
        failed = threading.Event()
        def fail():
            failed.set()
            raise ValueError('bad audio')
        with self.assertRaisesRegex(ValueError, 'bad audio'):
            with BoundedCpuPipeline(workers=1) as queue:
                first = queue.submit(fail)
                self.assertTrue(failed.wait(2))
                with self.assertRaises(ValueError):
                    first.result(timeout=2)
                queue.submit(lambda: self.fail('must not run'))

    def test_producer_failure_waits_for_running_write(self):
        ended = threading.Event()
        def save():
            time.sleep(.02)
            ended.set()
        with self.assertRaisesRegex(RuntimeError, 'model failed'):
            with BoundedCpuPipeline(workers=1) as queue:
                future = queue.submit(save)
                # Confirm running, so cancellation cannot erase this commit.
                while not future.running() and not future.done():
                    time.sleep(.001)
                raise RuntimeError('model failed')
        self.assertTrue(ended.is_set())

    def test_sync_mode_and_bounds(self):
        with BoundedCpuPipeline(workers=0) as queue:
            self.assertEqual(queue.submit(lambda: 7).result(), 7)
        for kwargs in [{'workers': True}, {'workers': 3}, {'max_pending': 0}, {'max_pending': 17}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                BoundedCpuPipeline(**kwargs)


class Signal(list):
    ndim = 1
    def reshape(self, *_):
        return self
    def copy(self):
        return Signal(self)


class PcmWriter:
    def __init__(self, path, *, samplerate, channels, **_):
        self.file = wave.open(str(path), 'wb')
        self.file.setnchannels(channels)
        self.file.setsampwidth(3)
        self.file.setframerate(samplerate)
    def write(self, signal):
        data = b''.join(int(max(-8388608, min(8388607, int(v * 8388608))))
                        .to_bytes(3, 'little', signed=True) for v in signal)
        self.file.writeframes(data)
    def __enter__(self):
        return self
    def __exit__(self, *_):
        self.file.close()


def pcm_write(path, signal, rate, **kwargs):
    with PcmWriter(path, samplerate=rate, channels=1, **kwargs) as out:
        out.write(signal)


def pcm_read(path, **_):
    with wave.open(str(path), 'rb') as audio:
        data = audio.readframes(audio.getnframes())
        return Signal(int.from_bytes(data[i:i+3], 'little', signed=True) / 8388608
                      for i in range(0, len(data), 3)), audio.getframerate()


NP = SimpleNamespace(float32='float32', asarray=lambda signal, **_: Signal(signal),
                     isfinite=lambda signal: SimpleNamespace(all=lambda: all(math.isfinite(x) for x in signal)),
                     zeros=lambda count, **_: Signal([0.] * count))
SF = SimpleNamespace(write=pcm_write, read=pcm_read, SoundFile=PcmWriter)


class RendererPipelineTests(unittest.TestCase):
    def fixture(self, root, count=5):
        checkpoint = root / 'checkpoint'; checkpoint.mkdir()
        (checkpoint / 'model.safetensors').write_bytes(b'fake model')
        (checkpoint / 'config.json').write_text(json.dumps({'talker_config': {'spk_id': {'fixture': 0}}}))
        job = {'schemaVersion': 'sermon-weekly-dubbing-job-v1',
               'voice': {'checkpointSha256': renderer.sha256(checkpoint / 'model.safetensors'), 'speakerKey': 'fixture'},
               'units': [{'id': i, 'blockId': i, 'text': f'unit {i}', 'gapAfterSeconds': .1} for i in range(count)]}
        job_path = root / 'job.json'; job_path.write_text(json.dumps(job))
        return job_path, checkpoint, job

    def invoke(self, job_path, checkpoint, out, model, workers=1):
        factory = Mock(return_value=model)
        torch = SimpleNamespace(bfloat16='bf16', float32='fp32', manual_seed=lambda _: None)
        modules = {'numpy': NP, 'soundfile': SF, 'torch': torch,
                   'qwen_tts': SimpleNamespace(Qwen3TTSModel=SimpleNamespace(from_pretrained=factory))}
        argv = ['render', '--job', str(job_path), '--checkpoint', str(checkpoint),
                '--out', str(out), '--batch-size', '2', '--cpu-workers', str(workers)]
        with patch('sys.argv', argv), patch.dict('sys.modules', modules), contextlib.redirect_stdout(io.StringIO()):
            renderer.main()
        return factory

    def model(self):
        def generate(**kwargs):
            return [Signal([.05 * (int(text.rsplit(' ', 1)[1]) + 1)] * 12000)
                    for text in kwargs['text']], 24000
        return SimpleNamespace(generate_custom_voice=Mock(side_effect=generate))

    def test_parallel_and_serial_pcm_and_cues_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); job_path, checkpoint, _ = self.fixture(root)
            serial, parallel = root / 'serial', root / 'parallel'
            self.invoke(job_path, checkpoint, serial, self.model(), workers=0)
            self.invoke(job_path, checkpoint, parallel, self.model(), workers=1)
            self.assertEqual((serial / 'chinese.raw.wav').read_bytes(), (parallel / 'chinese.raw.wav').read_bytes())
            a, b = [json.loads((p / 'report.json').read_text()) for p in [serial, parallel]]
            self.assertEqual(a['cues'], b['cues'])
            self.assertEqual(b['humanReviewStatus'], 'pending')
            self.assertLessEqual(b['cpuPipeline']['peakPending'], 4)

    def test_resume_only_synthesizes_uncommitted_units(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); job_path, checkpoint, job = self.fixture(root)
            out = root / 'render'; out.mkdir()
            identity = renderer.render_identity(job_path, job['voice']['checkpointSha256'], batch_size=2)
            renderer.write(out / 'identity.json', identity)
            raw = out / 'unit-0000.wav'; pcm_write(raw, Signal([.05] * 12000), 24000)
            renderer.write(raw.with_suffix('.json'), {'unit': job['units'][0], 'identity': identity,
                           'sha256': renderer.sha256(raw), 'durationSeconds': .5})
            old = raw.read_bytes(), raw.with_suffix('.json').read_bytes()
            model = self.model(); self.invoke(job_path, checkpoint, out, model)
            texts = [t for call in model.generate_custom_voice.call_args_list for t in call.kwargs['text']]
            self.assertEqual(texts, ['unit 1', 'unit 2', 'unit 3', 'unit 4'])
            self.assertEqual(old, (raw.read_bytes(), raw.with_suffix('.json').read_bytes()))

    def test_all_units_cached_assemble_without_model_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); job_path, checkpoint, _ = self.fixture(root)
            out = root / 'render'; self.invoke(job_path, checkpoint, out, self.model())
            (out / 'report.json').unlink(); (out / 'chinese.raw.wav').unlink()
            argv = ['render', '--job', str(job_path), '--checkpoint', str(checkpoint), '--out', str(out), '--batch-size', '2']
            with patch('sys.argv', argv), patch.dict('sys.modules', {'numpy': NP, 'soundfile': SF, 'qwen_tts': None, 'torch': None}), contextlib.redirect_stdout(io.StringIO()):
                renderer.main()
            self.assertEqual(json.loads((out / 'report.json').read_text())['cpuPipeline']['submitted'], 0)

    def test_bad_signal_never_completes_and_preserves_diagnostic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); job_path, checkpoint, _ = self.fixture(root, 2)
            out = root / 'render'
            model = SimpleNamespace(generate_custom_voice=Mock(return_value=([Signal([0.] * 100), Signal([.1] * 12000)], 24000)))
            with self.assertRaisesRegex(ValueError, 'Suspicious'):
                self.invoke(job_path, checkpoint, out, model)
            self.assertFalse((out / 'report.json').exists())
            self.assertTrue((out / 'failure.json').exists())
            self.assertFalse((out / 'unit-0000.json').exists())

    def test_old_diagnostic_does_not_replace_current_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); job_path, checkpoint, _ = self.fixture(root, 2)
            out = root / 'render'; out.mkdir()
            renderer.write(out / 'failure-0000.json', {'unit': 0, 'reason': 'previous_run'})
            model = SimpleNamespace(generate_custom_voice=Mock(return_value=([Signal([.1] * 12000), Signal([0.] * 100)], 24000)))
            with self.assertRaisesRegex(ValueError, 'Suspicious'):
                self.invoke(job_path, checkpoint, out, model)
            self.assertEqual(json.loads((out / 'failure.json').read_text())['unit'], 1)
            self.assertEqual(json.loads((out / 'failure-0000.json').read_text())['reason'], 'previous_run')

    def test_two_parallel_failures_can_be_repaired_in_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); job_path, checkpoint, job = self.fixture(root, 2)
            out = root / 'render'
            barrier = threading.Barrier(2)
            def parallel_bad_write(*args, **kwargs):
                pcm_write(*args, **kwargs)
                barrier.wait(timeout=2)
            bad = SimpleNamespace(generate_custom_voice=Mock(return_value=([Signal([0.] * 100)] * 2, 24000)))
            with patch.object(SF, 'write', parallel_bad_write), self.assertRaisesRegex(ValueError, 'Suspicious'):
                self.invoke(job_path, checkpoint, out, bad, workers=2)
            self.assertEqual(len(list(out.glob('failure-*.json'))), 2)
            identity = json.loads((out / 'identity.json').read_text())
            def repair(index):
                raw = out / f'unit-{index:04d}.wav'
                pcm_write(raw, Signal([.1] * 12000), 24000)
                renderer.write(raw.with_suffix('.json'), {'unit': job['units'][index], 'identity': identity,
                               'sha256': renderer.sha256(raw), 'durationSeconds': .5})
            repair(0)
            model = self.model()
            with self.assertRaisesRegex(ValueError, 'Suspicious synthesis in unit 1'):
                self.invoke(job_path, checkpoint, out, model)
            model.generate_custom_voice.assert_not_called()
            self.assertEqual(json.loads((out / 'failure.json').read_text())['unit'], 1)
            repair(1)
            self.invoke(job_path, checkpoint, out, model)
            model.generate_custom_voice.assert_not_called()
            self.assertTrue((out / 'report.json').exists())


if __name__ == '__main__':
    unittest.main()
