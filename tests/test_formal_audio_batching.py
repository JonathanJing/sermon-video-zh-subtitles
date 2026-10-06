"""Frozen-input and partial-resume checks with synthetic audio, no model runtime."""
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from scripts import render_formal_target_language_speech as tts
from scripts import screen_target_language_audio_units as asr
from tests import test_render_formal_target_language_speech as render_fixtures
from tests import test_screen_target_language_audio_units as screen_fixtures


class BatchEngine:
    loads = 0
    calls = []
    failure = None

    def __init__(self, *args, **kwargs):
        type(self).loads += 1

    def batch(self, requests, *, seed):
        indices = [row['identity']['unitIndex'] for row in requests]
        self.calls.append((indices, seed, [row['instruct'] for row in requests]))
        if self.failure:
            return self.failure(requests)
        return [{'identity': row['identity'], 'wave': [0.02 + index * .001] * 1280,
                 'sampleRate': 16000} for index, row in zip(indices, requests)]


class FormalTTSBatchTests(unittest.TestCase):
    setUp = render_fixtures.FormalRenderTests.setUp

    def setup_units(self, count=5):
        original = self.context['job']['units'][0]
        original_group = self.context['candidate']['groups'][0]
        self.context['job']['units'] = []
        self.context['candidate']['groups'] = []
        for index in range(count):
            unit = copy.deepcopy(original)
            unit['translationGroupId'] = f'batch-{index}'
            unit['outputRelativePath'] = f'languages/ko/audio/unit-{index:04d}.wav'
            self.context['job']['units'].append(unit)
            group = copy.deepcopy(original_group)
            group['translationGroupId'] = unit['translationGroupId']
            self.context['candidate']['groups'].append(group)
        self.paths['job'].write_text(json.dumps(self.context['job']))
        self.paths['candidate'].write_text(json.dumps(self.context['candidate']))
        BatchEngine.loads, BatchEngine.calls, BatchEngine.failure = 0, [], None
        build = patch.object(tts.integrity, 'build_receipt', return_value={'durationSeconds': .08})
        validate = patch.object(tts.integrity, 'validate_receipt')
        build.start(); validate.start()
        self.addCleanup(build.stop); self.addCleanup(validate.stop)

    def render(self, batch_size=4, **kwargs):
        return tts.render_units(self.context, self.paths, self.root,
            self.root / 'checkpoint-map.json', batch_size=batch_size,
            synth_factory=BatchEngine, **kwargs)

    def remove_commit(self, index):
        (self.root / self.context['job']['units'][index]['outputRelativePath']).unlink()
        for suffix in ('render.json', 'json'):
            (self.root / f'receipts/unit-{index:04d}.{suffix}').unlink()

    def test_short_tail_one_load_full_order_and_zero_calls_on_cache(self):
        self.setup_units()
        rows = self.render()
        self.assertEqual([row['textGroupId'] for row in rows], [f'batch-{i}' for i in range(5)])
        self.assertEqual([call[:2] for call in BatchEngine.calls], [([0, 1, 2, 3], 42), ([4], 46)])
        self.assertEqual(BatchEngine.loads, 1)
        intent = tts.package.read_object(self.root / 'receipts/unit-0004.intent.json')
        self.assertEqual(intent['batchSize'], 4)
        self.assertEqual(intent['batchWindowUnitIndices'], [4])
        self.assertEqual(intent['batchSeedPolicy'], tts.BATCH_SEED_POLICY)
        BatchEngine.calls.clear()
        self.assertEqual(self.render(), rows)
        self.assertEqual(BatchEngine.calls, [])
        self.assertEqual(BatchEngine.loads, 1)

    def test_mixed_cached_window_replays_full_bound_batch_without_replacing_commits(self):
        self.setup_units()
        rows = self.render()
        hashes = [row['audio']['sha256'] for row in rows]
        self.remove_commit(1); self.remove_commit(3)
        BatchEngine.calls.clear()
        resumed = self.render()
        self.assertEqual([call[:2] for call in BatchEngine.calls], [([0, 1, 2, 3], 42)])
        self.assertEqual([row['audio']['sha256'] for row in resumed], hashes)
        commit = tts.package.read_object(self.root / 'receipts/unit-0003.render.json')
        self.assertEqual(commit['generationBatch']['unitIndices'], [0, 1, 2, 3])

    def test_resume_replays_full_batch_when_neighbor_audio_is_reused(self):
        self.setup_units(4)
        original = self.render()
        legacy_hash = 'a86c470ed8f2efb7b94f62cc5451e0f3e6af9a15d13110d86086489daeedd58c'
        for index in range(4):
            intent_path = self.root / f'receipts/unit-{index:04d}.intent.json'
            commit_path = self.root / f'receipts/unit-{index:04d}.render.json'
            intent = tts.package.read_object(intent_path)
            intent['batchImplementationSha256'] = legacy_hash
            intent['batchSeedPolicy'] = tts.LEGACY_BATCH_SEED_POLICY
            intent['batchCachedUnitPolicy'] = tts.LEGACY_BATCH_CACHED_UNIT_POLICY
            intent_path.write_text(json.dumps(intent))
            commit = tts.package.read_object(commit_path)
            commit['identity'] = intent
            commit['generationBatch']['seedPolicy'] = tts.LEGACY_BATCH_SEED_POLICY
            commit_path.write_text(json.dumps(commit))
        self.remove_commit(1)
        (self.root / 'receipts/unit-0001.intent.json').unlink()

        next_root = self.root.parent / 'batch-resume-with-reuse'
        next_root.mkdir()
        BatchEngine.calls.clear()
        with patch.object(tts.integrity, 'probe_full_decode',
                          return_value={'fullDecode': 'pass', 'durationSeconds': 0.08}):
            resumed = tts.render_units(self.context, self.paths, next_root,
                next_root / 'checkpoint-map.json', batch_size=4, reuse_from=self.root,
                synth_factory=BatchEngine)
        self.assertEqual([call[:2] for call in BatchEngine.calls], [([0, 1, 2, 3], 42)])
        self.assertEqual([row['audio']['sha256'] for row in resumed],
                         [row['audio']['sha256'] for row in original])
        commit = tts.package.read_object(next_root / 'receipts/unit-0001.render.json')
        self.assertEqual(commit['generationBatch']['unitIndices'], [0, 1, 2, 3])

    def test_cached_subset_generation_is_rejected_as_unbound_audio(self):
        self.setup_units(4)
        self.render()
        commit_path = self.root / 'receipts/unit-0001.render.json'
        commit = tts.package.read_object(commit_path)
        commit['generationBatch']['unitIndices'] = [1, 3]
        commit_path.write_text(json.dumps(commit))
        BatchEngine.calls.clear(); BatchEngine.loads = 0
        with self.assertRaisesRegex(ValueError, 'did not preserve its full window'):
            self.render()
        self.assertEqual(BatchEngine.loads, 0)
        self.assertEqual(BatchEngine.calls, [])

    def test_batch_configuration_changes_do_not_rewrite_cache(self):
        self.setup_units()
        self.render()
        before = (self.root / 'receipts/unit-0000.intent.json').read_bytes()
        BatchEngine.calls.clear()
        for size in (1, 2, 8):
            with self.assertRaisesRegex(ValueError, 'Cached render identity differs'):
                self.render(size)
        self.assertEqual(BatchEngine.calls, [])
        self.assertEqual((self.root / 'receipts/unit-0000.intent.json').read_bytes(), before)

    def test_all_supported_batch_sizes_and_invalid_size(self):
        self.setup_units(2)
        for invalid in (3, True, 4.0):
            with self.assertRaisesRegex(ValueError, 'batch size'):
                self.render(invalid)
        self.render(8)
        self.assertEqual(BatchEngine.calls[0][0], [0, 1])

    def test_bad_cardinality_and_wrong_unit_order_commit_nothing(self):
        for failure in ('short', 'reverse'):
            with self.subTest(failure=failure):
                # Intent files are immutable but an uncommitted attempt can retry.
                self.setup_units()
                def bad(requests):
                    rows = [{'identity': row['identity'], 'wave': [.02] * 1280,
                             'sampleRate': 16000} for row in requests]
                    return rows[:-1] if failure == 'short' else list(reversed(rows))
                BatchEngine.failure = staticmethod(bad)
                with self.assertRaisesRegex(ValueError, 'cardinality|identity/order'):
                    self.render()
                self.assertFalse(list((self.root / 'receipts').glob('*.render.json')))
        BatchEngine.failure = None
        self.assertEqual(len(self.render()), 5)

    def test_second_window_exception_resumes_only_uncommitted_tail(self):
        self.setup_units()
        def failing(requests):
            if requests[0]['identity']['unitIndex'] == 4:
                raise RuntimeError('fixture OOM')
            return [{'identity': row['identity'], 'wave': [.02] * 1280,
                     'sampleRate': 16000} for row in requests]
        BatchEngine.failure = staticmethod(failing)
        with self.assertRaisesRegex(RuntimeError, 'OOM'):
            self.render()
        self.assertEqual(len(list((self.root / 'receipts').glob('*.render.json'))), 4)
        BatchEngine.failure, BatchEngine.calls = None, []
        self.assertEqual(len(self.render()), 5)
        self.assertEqual(BatchEngine.calls[0][0], [4])

    def test_future_cached_hash_error_fails_before_any_model_load(self):
        self.setup_units()
        self.render()
        self.remove_commit(0)
        future = self.root / self.context['job']['units'][4]['outputRelativePath']
        future.write_bytes(future.read_bytes() + b'changed')
        BatchEngine.calls.clear(); BatchEngine.loads = 0
        with self.assertRaisesRegex(ValueError, 'audio identity or hash'):
            self.render()
        self.assertEqual(BatchEngine.loads, 0)

    def test_future_real_unit_receipt_error_fails_before_any_model_load(self):
        # Keep the original approved fixture and the real receipt validator.
        BatchEngine.loads, BatchEngine.calls, BatchEngine.failure = 0, [], None
        self.render(2)
        self.remove_commit(0)
        path = self.root / 'receipts/unit-0001.json'
        value = tts.package.read_object(path)
        value['audioSha256'] = '0' * 64
        path.write_text(json.dumps(value))
        BatchEngine.loads, BatchEngine.calls = 0, []
        with self.assertRaisesRegex(ValueError, 'receipt belongs'):
            self.render(2)
        self.assertEqual(BatchEngine.loads, 0)
        self.assertEqual(BatchEngine.calls, [])

    def test_each_unit_instruction_is_passed_in_the_batch(self):
        self.setup_units(2)
        self.render(2, instructions_by_group={'batch-1': {'instruction': 'pause briefly'}})
        self.assertEqual(BatchEngine.calls[0][2], [None, 'pause briefly'])

    def test_neighbor_instruction_changes_the_entire_batch_sound_identity(self):
        self.setup_units(2)
        self.render(2)
        old = tts.package.read_object(self.root / 'receipts/unit-0000.intent.json')
        BatchEngine.calls.clear()
        with self.assertRaisesRegex(ValueError, 'Cached render identity differs'):
            self.render(2, instructions_by_group={'batch-1': {'instruction': 'pause briefly'}})
        self.assertEqual(BatchEngine.calls, [])
        self.assertEqual(tts.package.read_object(self.root / 'receipts/unit-0000.intent.json'), old)

    def test_batch_one_intent_keeps_the_existing_sound_contract(self):
        self.setup_units(2)
        intent = tts._intent(self.context, self.paths, 0, seed=42,
            dtype='bfloat16', attention='sdpa', instruct=None)
        explicit = tts._intent(self.context, self.paths, 0, seed=42,
            dtype='bfloat16', attention='sdpa', instruct=None, batch_size=1, device='mps')
        self.assertEqual(intent, explicit)
        self.assertFalse(any(key.startswith('batch') for key in intent))
        self.assertEqual(intent['rendererSha256'], tts.RENDERER_SOUND_IDENTITY_SHA256)

    def test_adapter_list_api_maps_each_output_and_instruction(self):
        synth = tts.QwenSynthesizer.__new__(tts.QwenSynthesizer)
        synth.torch = SimpleNamespace(manual_seed=MagicMock(),
            cuda=SimpleNamespace(is_available=lambda: False))
        synth.model = MagicMock()
        synth.model.generate_custom_voice.return_value = ([[.02], [.03]], 16000)
        requests = [{'identity': {'unitIndex': index}, 'text': str(index),
                     'language': 'Korean', 'speaker': 'fixture',
                     'instruct': None if index == 0 else 'pause'} for index in range(2)]
        values = synth.batch(requests, seed=42)
        self.assertEqual([value['identity']['unitIndex'] for value in values], [0, 1])
        self.assertEqual(synth.model.generate_custom_voice.call_args.kwargs['instruct'], ['', 'pause'])
        synth.model.generate_custom_voice.return_value = ([[.02]], 16000)
        with self.assertRaisesRegex(ValueError, 'cardinality'):
            synth.batch(requests, seed=42)


class FormalASRBatchTests(unittest.TestCase):
    setUp = screen_fixtures.FormalAudioScreenTests.setUp

    def setup_units(self, count=5):
        original_unit, original_row = self.job['units'][0], self.manifest['units'][0]
        original_audio = self.root / original_unit['outputRelativePath']
        self.job['units'], self.manifest['units'] = [], []
        for index in range(count):
            unit, row = copy.deepcopy(original_unit), copy.deepcopy(original_row)
            unit['translationGroupId'] = f'g{index}'
            unit['outputRelativePath'] = f'languages/ko/audio/unit-{index:04d}.wav'
            path = self.root / unit['outputRelativePath']
            path.write_bytes(original_audio.read_bytes())
            row.update(textGroupId=unit['translationGroupId'])
            row['audio'] = {'path': unit['outputRelativePath'], 'sha256': asr.file_sha(path)}
            self.job['units'].append(unit); self.manifest['units'].append(row)
        self.manifest['targetLanguageSpeechJobJsonSha256'] = asr.identity.json_sha256(self.job)
        self.calls = []

    def transcribe(self, requests):
        self.calls.append([row['identity']['unitIndex'] for row in requests])
        return [{'identity': row['identity'],
                 'recognized': self.job['units'][row['identity']['unitIndex']]['text']}
                for row in requests]

    def screen(self, **kwargs):
        options = {'batch_size': 4, 'transcribe_batch': self.transcribe,
                   'unit_cache': self.root / 'asr-cache'}
        options.update(kwargs)
        return asr.screen(self.job, self.manifest, self.root, None,
            model='fixture', model_revision='fixture-v1', **options)

    def test_short_tail_full_coverage_pending_and_cached_mixed_batch(self):
        self.setup_units()
        receipt, _ = self.screen()
        self.assertEqual(self.calls, [[0, 1, 2, 3], [4]])
        self.assertEqual(receipt['coverage'], 1)
        self.assertEqual(receipt['humanListeningStatus'], 'pending')
        self.assertEqual(receipt['transcriptionBatchSize'], 4)
        self.calls.clear()
        self.assertEqual(self.screen()[0], receipt)
        self.assertEqual(self.calls, [])
        (self.root / 'asr-cache/unit-0001.json').unlink()
        (self.root / 'asr-cache/unit-0003.json').unlink()
        self.screen()
        self.assertEqual(self.calls, [[1, 3]])

    def test_wrong_order_or_cardinality_does_not_create_unit_receipts(self):
        self.setup_units()
        for kind in ('short', 'reverse'):
            def bad(requests):
                values = self.transcribe(requests)
                return values[:-1] if kind == 'short' else list(reversed(values))
            with self.assertRaisesRegex(ValueError, 'cardinality|identity/order'):
                self.screen(transcribe_batch=bad)
            self.assertFalse((self.root / 'asr-cache').exists())

    def test_exception_retains_first_batch_for_missing_tail_resume(self):
        self.setup_units()
        def fail(requests):
            if requests[0]['identity']['unitIndex'] == 4:
                raise RuntimeError('fixture resource failure')
            return self.transcribe(requests)
        with self.assertRaisesRegex(RuntimeError, 'resource failure'):
            self.screen(transcribe_batch=fail)
        self.calls.clear()
        self.screen()
        self.assertEqual(self.calls, [[4]])

    def test_changed_batch_identity_fails_without_transcription_or_cache_rewrite(self):
        self.setup_units()
        self.screen()
        before = (self.root / 'asr-cache/unit-0000.json').read_bytes()
        self.calls.clear()
        with self.assertRaisesRegex(ValueError, 'cached unit identity'):
            self.screen(batch_size=2)
        self.assertEqual(self.calls, [])
        self.assertEqual((self.root / 'asr-cache/unit-0000.json').read_bytes(), before)

    def test_future_audio_hash_is_checked_before_first_transcription(self):
        self.setup_units()
        path = self.root / self.job['units'][4]['outputRelativePath']
        path.write_bytes(path.read_bytes() + b'changed')
        with self.assertRaisesRegex(ValueError, 'audio hash mismatch'):
            self.screen()
        self.assertEqual(self.calls, [])

    def test_invalid_batch_size_never_calls_transcriber(self):
        self.setup_units()
        for invalid in (3, True, 4.0):
            with self.assertRaisesRegex(ValueError, 'batch size'):
                self.screen(batch_size=invalid)
        self.assertEqual(self.calls, [])

    def test_callback_audio_mutation_does_not_cache_a_false_success(self):
        self.setup_units()
        def mutate(requests):
            values = self.transcribe(requests)
            requests[0]['path'].write_bytes(b'changed')
            return values
        with self.assertRaisesRegex(ValueError, 'inputs changed'):
            self.screen(transcribe_batch=mutate)
        self.assertFalse((self.root / 'asr-cache').exists())

    def test_empty_transcription_stays_requires_review(self):
        self.setup_units()
        def empty(requests):
            return [{'identity': row['identity'], 'recognized': ''} for row in requests]
        receipt, manifest = self.screen(transcribe_batch=empty)
        self.assertEqual(receipt['status'], 'requires_review')
        self.assertEqual(manifest['machineScreening']['status'], 'requires_review')
        self.assertEqual(receipt['humanListeningStatus'], 'pending')

    def test_changed_cached_transcript_hash_fails_before_model(self):
        self.setup_units()
        self.screen()
        path = self.root / 'asr-cache/unit-0000.json'
        value = asr.load(path); value['recognized'] = 'changed'
        path.write_text(json.dumps(value))
        self.calls.clear()
        with self.assertRaisesRegex(ValueError, 'result hash'):
            self.screen()
        self.assertEqual(self.calls, [])

    def test_atomic_cache_publish_never_overwrites_a_concurrent_receipt(self):
        path = self.root / 'asr-cache/unit-0000.json'
        asr.write_atomic(path, {'recognized': 'first'})
        before = path.read_bytes()
        with self.assertRaises(FileExistsError):
            asr.write_atomic(path, {'recognized': 'replacement'})
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(path.parent.iterdir()), [path])

    def test_cli_batch_loads_once_and_transcribes_list_with_short_tail(self):
        self.setup_units()
        job_path, manifest_path = self.root / 'job.json', self.root / 'manifest.json'
        job_path.write_text(json.dumps(self.job)); manifest_path.write_text(json.dumps(self.manifest))
        weights = self.root / 'model/model.safetensors'
        weights.parent.mkdir(); weights.write_bytes(b'fixture-weights')
        model_type, engine = MagicMock(), MagicMock()
        model_type.from_pretrained.return_value = engine
        engine.transcribe.side_effect = lambda **kwargs: [SimpleNamespace(text=self.job['units'][0]['text'])
                                                          for _ in kwargs['audio']]
        modules = {'torch': SimpleNamespace(bfloat16='fixture-bf16'),
                   'soundfile': SimpleNamespace(read=lambda *a, **kw: ([.02], 16000)),
                   'qwen_asr': SimpleNamespace(Qwen3ASRModel=model_type)}
        argv = ['screen', '--job', str(job_path), '--render-manifest', str(manifest_path),
                '--artifact-root', str(self.root), '--model-path', str(weights.parent),
                '--model-revision', f'model.safetensors:sha256:{asr.file_sha(weights)}',
                '--batch-size', '4', '--out-receipt', str(self.root / 'screening.json'),
                '--out-manifest', str(self.root / 'screened.json')]
        with patch.dict(sys.modules, modules), patch.object(sys, 'argv', argv):
            asr.main()
        model_type.from_pretrained.assert_called_once()
        self.assertEqual(model_type.from_pretrained.call_args.kwargs['max_inference_batch_size'], 4)
        self.assertEqual([len(call.kwargs['audio']) for call in engine.transcribe.call_args_list], [4, 1])
        self.assertEqual(asr.load(self.root / 'screening.json')['humanListeningStatus'], 'pending')


if __name__ == '__main__':
    unittest.main()
