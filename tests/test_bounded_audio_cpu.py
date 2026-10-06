import threading
import time
import unittest

from scripts.bounded_audio_cpu import BoundedAudioCPU
from tests import test_formal_audio_batching as batch_fixtures
from scripts import render_formal_target_language_speech as renderer
from unittest.mock import patch
BatchEngine = batch_fixtures.BatchEngine


class AudioCPUExecutorTests(unittest.TestCase):
    def test_four_actual_workers_and_bounded_pending(self):
        pipeline = BoundedAudioCPU(4, 4)
        barrier = threading.Barrier(4)
        threads = set()
        def work(index):
            threads.add(threading.get_ident())
            barrier.wait(timeout=3)
            time.sleep(.01)
            return index
        try:
            futures = [pipeline.submit(work, index) for index in range(8)]
            self.assertEqual([future.result() for future in futures], list(range(8)))
        finally:
            pipeline.close()
        report = pipeline.report()
        self.assertEqual(len(threads), 4)
        self.assertEqual(report['peakActiveWorkers'], 4)
        self.assertLessEqual(report['peakPendingUnits'], 4)
        self.assertEqual(report['completedUnits'], 8)
        self.assertEqual(report['modelCallsInWorkers'], 0)

    def test_invalid_bounds_and_failure_observation(self):
        for workers, queue in ((True, 8), (8, 8), (4, 17), (4, 0)):
            with self.assertRaises(ValueError):
                BoundedAudioCPU(workers, queue)
        pipeline = BoundedAudioCPU(0, 1)
        def fail():
            raise RuntimeError('cpu failed')
        future = pipeline.submit(fail)
        with self.assertRaisesRegex(RuntimeError, 'cpu failed'):
            future.result()
        with self.assertRaisesRegex(RuntimeError, 'cpu failed'):
            pipeline.submit(lambda: None)
        pipeline.close()
        self.assertTrue(pipeline.report()['failed'])


class FormalAudioCPU4Tests(unittest.TestCase):
    setUp = batch_fixtures.FormalTTSBatchTests.setUp
    setup_units = batch_fixtures.FormalTTSBatchTests.setup_units
    render = batch_fixtures.FormalTTSBatchTests.render
    remove_commit = batch_fixtures.FormalTTSBatchTests.remove_commit

    def test_cpu4_prepares_real_pcm_and_commits_parent_order_with_short_tail(self):
        self.setup_units(10)
        barrier = threading.Barrier(4)
        completed, committed = [], []
        parent = threading.get_ident()
        original_prepare, original_save = renderer._prepare_cpu_audio, renderer.write_json_atomic
        def prepare(path, samples, rate):
            index = int(path.name.split('-')[1].split('.')[0])
            if index < 8:
                barrier.wait(timeout=4)
                time.sleep((3 - index % 4) * .02)
            result = original_prepare(path, samples, rate)
            completed.append(index)
            return result
        def save(path, value):
            if path.name.endswith('.render.json'):
                self.assertEqual(threading.get_ident(), parent)
                committed.append(value['identity']['unitIndex'])
            original_save(path, value)
        with patch.object(renderer, '_prepare_cpu_audio', side_effect=prepare), \
             patch.object(renderer, 'write_json_atomic', side_effect=save):
            rows = self.render(8, cpu_workers=4, cpu_queue_units=8)
        self.assertEqual(committed, list(range(10)))
        self.assertNotEqual(completed[:8], list(range(8)))
        report = renderer.package.read_object(self.root / 'cpu-runtime.json')
        self.assertEqual(report['workers'], report['peakActiveWorkers'])
        self.assertEqual(report['workers'], 4)
        self.assertEqual(report['submittedUnits'], 10)
        self.assertEqual([call[:2] for call in BatchEngine.calls],
                         [([0, 1, 2, 3, 4, 5, 6, 7], 42), ([8, 9], 50)])
        self.assertEqual(len(rows), 10)
        self.assertFalse(list(self.root.rglob('*.partial.wav')))

    def test_cpu4_mixed_cache_replays_without_replacing_successful_neighbors(self):
        self.setup_units(8)
        rows = self.render(8)
        cached = {path: path.read_bytes() for path in self.root.rglob('*')
                  if path.is_file() and any(f'{index:04d}' in path.name for index in (0, 2, 4, 6))}
        for index in (1, 3, 5, 7):
            self.remove_commit(index)
        BatchEngine.calls.clear()
        resumed = self.render(8, cpu_workers=4)
        self.assertEqual([row['audio']['sha256'] for row in resumed], [row['audio']['sha256'] for row in rows])
        self.assertEqual(BatchEngine.calls[0][0], list(range(8)))
        self.assertTrue(all(path.read_bytes() == data for path, data in cached.items()))
        self.assertEqual(renderer.package.read_object(self.root / 'cpu-runtime.json')['submittedUnits'], 4)

    def test_exact_parent_batch_identity_resumes_without_model_with_cpu4(self):
        self.setup_units(8)
        original = self.render(8)
        for index in range(8):
            intent_path = self.root / f'receipts/unit-{index:04d}.intent.json'
            commit_path = self.root / f'receipts/unit-{index:04d}.render.json'
            intent = renderer.package.read_object(intent_path)
            intent['batchImplementationSha256'] = '4232cfeee91c4cac5142ec7f1035aed04f79ca4c5da77f79bad9149680090076'
            renderer.write_json_atomic(intent_path, intent)
            commit = renderer.package.read_object(commit_path)
            commit['identity'] = intent
            renderer.write_json_atomic(commit_path, commit)
        before = {path: path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        BatchEngine.calls.clear()
        self.assertEqual(self.render(8, cpu_workers=4), original)
        self.assertEqual(BatchEngine.calls, [])
        self.assertTrue(all(path.read_bytes() == value for path, value in before.items()))

    def test_decode_failure_keeps_failed_unit_uncommitted_and_lock_until_workers_drain(self):
        self.setup_units(8)
        original = renderer._prepare_cpu_audio
        def prepare(path, samples, rate):
            if '0001' in path.name:
                raise ValueError('injected full decode failure')
            return original(path, samples, rate)
        with patch.object(renderer, '_prepare_cpu_audio', side_effect=prepare):
            with self.assertRaisesRegex(ValueError, 'injected full decode failure'):
                self.render(8, cpu_workers=4)
        self.assertFalse((self.root / 'receipts/unit-0001.render.json').exists())
        self.assertFalse((self.root / self.context['job']['units'][1]['outputRelativePath']).exists())
        self.assertTrue(renderer.package.read_object(self.root / 'cpu-runtime.json')['failed'])

    def test_broken_partial_symlink_never_writes_outside_root(self):
        self.setup_units(8)
        partial = (self.root / self.context['job']['units'][1]['outputRelativePath']).with_suffix('.partial.wav')
        partial.parent.mkdir(parents=True, exist_ok=True)
        outside = self.root.parent / 'must-not-create.wav'
        partial.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'escapes render root'):
            self.render(8, cpu_workers=4)
        self.assertFalse(outside.exists())
        self.assertEqual(BatchEngine.calls, [])
