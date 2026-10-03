"""Formal admission, commit and resume under the eight-replica dispatcher."""
import fcntl
from unittest.mock import patch
import unittest

from scripts import render_formal_target_language_speech as tts
from tests import test_formal_audio_batching as batch_fixtures
BatchEngine = batch_fixtures.BatchEngine


class FixturePool:
    instances = []

    def __init__(self, checkpoint, factory, engine_kwargs, *, replicas, telemetry):
        self.replicas = replicas
        self.engine = factory(checkpoint, **engine_kwargs)
        self.telemetry = telemetry
        self.outputs = {}
        self.closed = False
        self.peak = 0
        self.instances.append(self)

    def start(self):
        self.telemetry({'kind': 'pool_ready', 'replicas': self.replicas})

    def submit(self, index, requests, *, seed):
        assert len(self.outputs) < self.replicas
        self.outputs[index] = self.engine.batch(requests, seed=seed)
        self.peak = max(self.peak, len(self.outputs))

    def result(self, index):
        return self.outputs.pop(index)

    def close(self):
        self.closed = True


class SparkProductionTests(unittest.TestCase):
    setUp = batch_fixtures.FormalTTSBatchTests.setUp
    setup_units = batch_fixtures.FormalTTSBatchTests.setup_units
    remove_commit = batch_fixtures.FormalTTSBatchTests.remove_commit

    def render(self, **kwargs):
        with patch.object(tts.replica_pool, 'ReplicaPool', FixturePool), \
                patch.object(tts.integrity, 'probe_full_decode',
                             return_value={'fullDecode': 'pass', 'durationSeconds': .08}):
            return tts.render_units(self.context, self.paths, self.root,
                self.root / 'checkpoint-map.json', replicas=8, batch_size=8,
                synth_factory=BatchEngine, **kwargs)

    def test_419_units_bounded_windows_tail_seed_and_cached_resume(self):
        self.setup_units(419)
        FixturePool.instances = []
        rows = self.render()
        self.assertEqual(len(rows), 419)
        self.assertEqual(len(BatchEngine.calls), 53)
        self.assertEqual(BatchEngine.calls[-1][:2], ([416, 417, 418], 458))
        self.assertEqual(FixturePool.instances[0].peak, 8)
        self.assertTrue(FixturePool.instances[0].closed)
        hashes = [r['audio']['sha256'] for r in rows]
        self.remove_commit(73)
        BatchEngine.calls = []
        resumed = self.render()
        self.assertEqual(BatchEngine.calls[0][:2], (list(range(72, 80)), 114))
        self.assertEqual(len(BatchEngine.calls), 1)
        self.assertEqual([r['audio']['sha256'] for r in resumed], hashes)
        BatchEngine.calls = []
        pool_count = len(FixturePool.instances)
        self.assertEqual(self.render(), rows)
        self.assertEqual(len(FixturePool.instances), pool_count)
        intent = tts.package.read_object(self.root / 'receipts/unit-0073.intent.json')
        self.assertEqual(intent['replicaCount'], 8)
        self.assertEqual(len(intent['replicaImplementationSha256']), 64)

    def test_future_bad_identity_fails_before_pool_creation(self):
        self.setup_units(9)
        self.render()
        self.remove_commit(0)
        path = self.root / 'receipts/unit-0008.intent.json'
        value = tts.package.read_object(path)
        value['checkpointSha256'] = '0' * 64
        tts.write_json_atomic(path, value)
        count = len(FixturePool.instances)
        with self.assertRaisesRegex(ValueError, 'Cached render identity'):
            self.render()
        self.assertEqual(len(FixturePool.instances), count)

    def test_bad_window_outputs_close_pool_and_commit_nothing(self):
        self.setup_units(9)
        BatchEngine.failure = staticmethod(lambda rows: [])
        with self.assertRaisesRegex(ValueError, 'cardinality'):
            self.render()
        self.assertTrue(FixturePool.instances[-1].closed)
        self.assertFalse(list((self.root / 'receipts').glob('*.render.json')))

    def test_failure_preserves_commits_and_resume_replays_the_complete_window(self):
        self.setup_units(9)
        original = tts.write_pcm16
        def interrupted(path, wave, rate):
            if path.name == 'unit-0003.partial.wav':
                raise RuntimeError('fixture write failure')
            return original(path, wave, rate)
        with patch.object(tts, 'write_pcm16', side_effect=interrupted):
            with self.assertRaisesRegex(RuntimeError, 'write failure'):
                self.render()
        self.assertEqual(len(list((self.root / 'receipts').glob('*.render.json'))), 3)
        self.assertTrue(FixturePool.instances[-1].closed)
        saved = [(self.root / self.context['job']['units'][i]['outputRelativePath']).read_bytes()
                 for i in range(3)]
        BatchEngine.calls = []
        self.assertEqual(len(self.render()), 9)
        self.assertEqual([call[:2] for call in BatchEngine.calls],
                         [(list(range(8)), 42), ([8], 50)])
        self.assertEqual(saved,
            [(self.root / self.context['job']['units'][i]['outputRelativePath']).read_bytes()
             for i in range(3)])

    def test_production_cli_selects_eight_by_eight_and_rejects_dev_profile(self):
        args = []
        for name in ('source', 'anchor', 'candidate', 'job', 'adapter', 'policy',
                     'human-review-receipt', 'speaker-registry', 'source-voice-authorization',
                     'clip-timeline-map', 'checkpoint-map', 'audio-operation-policies'):
            args.extend(['--' + name, str(self.paths['job'])])
        with patch.object(tts, 'render_accounted', return_value={'targetLocale': 'ko'}) as render:
            tts.main(args + ['--spark-production'])
            self.assertEqual(render.call_args.kwargs['replicas'], 8)
            self.assertEqual(render.call_args.kwargs['batch_size'], 8)
            for flags in (['--dev-test'], ['--batch-size', '4'], ['--replicas', '1']):
                with self.assertRaisesRegex(ValueError, 'Spark production'):
                    tts.main(args + ['--spark-production'] + flags)

    def test_single_writer_lock_blocks_duplicate_dispatch(self):
        self.setup_units(9)
        count = len(FixturePool.instances)
        with (self.root / '.formal-render.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError, 'already in use'):
                self.render()
        self.assertEqual(len(FixturePool.instances), count)

    def test_unsafe_configuration_fails_before_pool_creation(self):
        self.setup_units(1)
        count = len(FixturePool.instances)
        for option in ({'device': 'mps'}, {'dtype': 'float32'}, {'attention': None}):
            with self.subTest(option=option), self.assertRaisesRegex(ValueError, 'Spark production'):
                self.render(**option)
        self.assertEqual(len(FixturePool.instances), count)


if __name__ == '__main__':
    unittest.main()
