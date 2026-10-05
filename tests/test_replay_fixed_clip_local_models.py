"""Diagnostic worker checks without importing or executing model runtimes."""
import copy
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from scripts.experiments import replay_fixed_clip_local_models as worker


class FakeTTS:
    def __init__(self, *args, fail_batch=None, **kwargs):
        self.calls = []
        self.fail_batch = fail_batch

    def batch(self, requests, *, seed):
        self.calls.append(requests)
        if self.fail_batch == len(self.calls):
            raise RuntimeError('diagnostic injected failure')
        return [{'identity': row['identity'], 'wave': [0.2, -0.2], 'sampleRate': 24000}
                for row in requests]


class FakeASR:
    def __init__(self, *args, **kwargs):
        self.calls = []

    def batch(self, paths):
        self.calls.append(paths)
        return [SimpleNamespace(text='本地回听结果') for _ in paths]


def fake_writer(root, group, wave, sample_rate):
    name = group['groupId'] + '.wav'
    path = root / name
    path.write_bytes(group['text'].encode())
    return {**group, 'audioPath': name, 'audioSha256': worker.sha(path),
            'sampleRate': sample_rate, 'audioSeconds': 1.0}


class FixedClipReplayTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.media = self.root / 'source.mp4'
        self.media.write_bytes(b'frozen diagnostic media')
        source_units = [{'sourceUnitId': f'fresh-diagnostic-u{i:03d}', 'english': f'English {i}'}
                        for i in range(1, 40)]
        groups = []
        for group in range(13):
            selected = source_units[group * 3:group * 3 + 3]
            ids = [u['sourceUnitId'] for u in selected]
            texts = [f'诊断文字{group}-{i}。' for i in range(3)]
            groups.append({'translationGroupId': f'fresh-g{group + 1:03d}', 'sourceUnitIds': ids,
                           # Joined wording remains an original utterance; coverage is per source unit.
                           'targetUtterances': [''.join(texts)],
                           'coverage': [{'sourceUnitId': sid, 'targetText': text}
                                        for sid, text in zip(ids, texts)]})
        self.evidence = {'sourceLocale': 'en', 'targetLocale': 'zh-Hans', 'sourceUnits': source_units,
                         'englishSourcePackageJsonSha256': worker.SOURCE_PACKAGE_SHA,
                         'anchorManifestSha256': worker.ANCHOR_SHA, 'groups': groups}
        self.evidence_path = self.root / 'evidence.json'
        self.write(self.evidence_path, self.evidence)
        self.checkpoint = self.root / 'checkpoint'; self.checkpoint.mkdir()
        (self.checkpoint / 'model.safetensors').write_bytes(b'local speaker weights')
        self.write(self.checkpoint / 'config.json', {'talker_config': {'spk_id': {'eric_pilot': 0}}})
        self.registry = {'schemaVersion': 'sermon-speaker-voice-registry-v1', 'speakers': [
            {'speakerId': 'eric_geiger', 'speakerKey': 'eric_pilot',
             'authorization': {'status': 'authorized', 'purposes': ['chinese_dubbing'],
                               'evidence': ['diagnostic-test-voice-authorization']},
             'localeCapabilities': [{'targetLocale': 'zh-Hans', 'modelLanguage': 'Chinese', 'status': 'human_reviewed'}],
             'checkpoint': {'checkpointRef': 'speaker-voice://diagnostic',
                            'checkpointSha256': worker.sha(self.checkpoint / 'model.safetensors')}}]}
        self.registry_path = self.root / 'registry.json'; self.write(self.registry_path, self.registry)
        self.map_path = self.root / 'checkpoint-map.json'
        self.write(self.map_path, {'schemaVersion': 'sermon-speaker-checkpoint-map-v1', 'checkpoints': [
            {'speakerId': 'eric_geiger', 'checkpointRef': 'speaker-voice://diagnostic', 'path': str(self.checkpoint)}]})
        self.tts_args = SimpleNamespace(evidence=self.evidence_path, media=self.media,
            registry=self.registry_path, checkpoint_map=self.map_path, out=self.root / 'tts',
            seed=42, device='cuda:0', attention='sdpa')
        self.model_path = self.root / 'asr-model'; self.model_path.mkdir()
        self.write(self.model_path / 'config.json', {})
        (self.model_path / 'model.safetensors').write_bytes(b'local asr weights')
        self.asr_args = SimpleNamespace(tts_manifest=self.tts_args.out / 'manifest.json',
            model_path=self.model_path, out=self.root / 'asr', device='cuda:0')
        for name, value in [('MEDIA_SHA', worker.sha(self.media)),
                            ('SOURCE_UNITS_SHA', worker.digest(source_units))]:
            guard = patch.object(worker, name, value); guard.start(); self.addCleanup(guard.stop)
        guard = patch.dict(os.environ, {}, clear=True); guard.start(); self.addCleanup(guard.stop)

    @staticmethod
    def write(path, value):
        path.write_text(json.dumps(value, ensure_ascii=False))

    def tts(self, model=None):
        model = model or FakeTTS()
        factory = Mock(return_value=model)
        report = worker.render_tts(self.tts_args, factory=factory, writer=fake_writer)
        return report, model, factory

    def test_full_tts_batches_receipts_and_no_model_on_resume(self):
        report, model, _ = self.tts()
        self.assertEqual([len(r) for r in model.calls], [2, 2, 2, 2, 2, 2, 1])
        self.assertEqual(len(report['groups']), 13)
        self.assertEqual(report['groups'][0]['text'], ''.join(self.evidence['groups'][0]['targetUtterances']))
        self.assertEqual(report['voice']['checkpointSha256'], self.registry['speakers'][0]['checkpoint']['checkpointSha256'])
        for key, value in worker.FLAGS.items():
            self.assertEqual(report[key], value)
        self.assertIsNone(report['usage']['generationTokensPerSecond'])
        self.assertIsNone(report['usage']['totalTokens'])
        self.assertGreaterEqual(report['processWallSeconds'], report['inferenceSeconds'])
        for entry in report['batchReceipts']:
            self.assertEqual(entry['sha256'], worker.sha(self.tts_args.out / entry['path']))
            envelope = worker.read(self.tts_args.out / entry['path'])
            receipt = envelope['receipt']
            self.assertEqual(envelope['receiptSha256'], worker.digest(receipt))
            self.assertEqual(receipt['backend'], 'local')
            self.assertTrue(receipt['callId'])
            self.assertLessEqual(receipt['startedAt'], receipt['completedAt'])
        factory = Mock(side_effect=AssertionError('completed cache must not load a model'))
        manifest_sha = worker.sha(self.tts_args.out / 'manifest.json')
        resumed = worker.render_tts(self.tts_args, factory=factory, writer=fake_writer)
        self.assertEqual(resumed, report)
        self.assertEqual(worker.sha(self.tts_args.out / 'manifest.json'), manifest_sha)
        factory.assert_not_called()

    def test_unknown_batch_refuses_replay_before_model_loading(self):
        failed = FakeTTS(fail_batch=3)
        with self.assertRaisesRegex(RuntimeError, 'injected failure'):
            self.tts(failed)
        self.assertTrue((self.tts_args.out / 'batch-001.completed.json').is_file())
        self.assertTrue((self.tts_args.out / 'batch-002.started.json').is_file())
        factory = Mock(side_effect=AssertionError('unknown attempt must not load model'))
        with self.assertRaisesRegex(ValueError, 'unknown_batch_requires_reconciliation'):
            worker.render_tts(self.tts_args, factory=factory, writer=fake_writer)
        factory.assert_not_called()

    def test_completed_batches_resume_if_final_manifest_missing(self):
        first, _, _ = self.tts()
        (self.tts_args.out / 'manifest.json').unlink()
        factory = Mock(side_effect=AssertionError('do not repeat completed inference'))
        resumed = worker.render_tts(self.tts_args, factory=factory, writer=fake_writer)
        self.assertEqual(resumed['groups'], first['groups'])
        self.assertIsNone(resumed['modelLoadSeconds'])
        factory.assert_not_called()

    def test_changed_cache_audio_or_evidence_rejected(self):
        report, _, _ = self.tts()
        audio = self.tts_args.out / report['groups'][0]['audioPath']
        audio.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'completed_audio_missing_or_changed'):
            self.tts()
        audio.write_bytes(report['groups'][0]['text'].encode())
        changed = copy.deepcopy(self.evidence)
        changed['groups'][0]['targetUtterances'][0] += '新增文字'
        self.write(self.evidence_path, changed)
        with self.assertRaisesRegex(ValueError, 'diagnostic_resume_identity_changed'):
            self.tts()

    def test_fixed_source_group_coverage_and_media_gates(self):
        for mutation in ('media', 'unit', 'group', 'coverage'):
            with self.subTest(mutation=mutation):
                evidence = copy.deepcopy(self.evidence)
                media = self.media
                if mutation == 'media':
                    media = self.root / 'other.mp4'; media.write_bytes(b'other')
                elif mutation == 'unit':
                    evidence['sourceUnits'][0]['english'] = 'different'
                elif mutation == 'group':
                    evidence['groups'].pop()
                else:
                    evidence['groups'][0]['coverage'][0]['targetText'] = '不存在的覆盖文本'
                with self.assertRaises(ValueError):
                    worker.fixed_groups(evidence, media)

    def test_authorization_and_weight_hash_checked_before_factory(self):
        factory = Mock(side_effect=AssertionError('preflight must precede runtime'))
        self.registry['speakers'][0]['authorization']['purposes'] = ['unrelated']
        self.write(self.registry_path, self.registry)
        with self.assertRaisesRegex(ValueError, 'eric_chinese_voice_not_authorized'):
            worker.render_tts(self.tts_args, factory=factory)
        self.registry['speakers'][0]['authorization']['purposes'] = ['chinese_dubbing']
        self.write(self.registry_path, self.registry)
        (self.checkpoint / 'model.safetensors').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'Checkpoint hash differs'):
            worker.render_tts(self.tts_args, factory=factory)
        factory.assert_not_called()

    def test_asr_all_13_groups_batch4_resume_and_unknown_tokens(self):
        self.tts()
        model = FakeASR(); factory = Mock(return_value=model)
        report = worker.back_asr(self.asr_args, factory=factory)
        self.assertEqual([len(r) for r in model.calls], [4, 4, 4, 1])
        self.assertEqual(len(report['groups']), 13)
        self.assertEqual(report['usage']['usageStatus'], 'unavailable')
        self.assertIsNone(report['usage']['generationTokensPerSecond'])
        self.assertEqual(os.environ['HF_HUB_OFFLINE'], '1')
        factory = Mock(side_effect=AssertionError('cached ASR must not reload'))
        self.assertEqual(worker.back_asr(self.asr_args, factory=factory), report)
        factory.assert_not_called()

    def test_asr_empty_or_incomplete_output_leaves_unknown_receipt(self):
        self.tts()
        model = FakeASR(); model.batch = Mock(return_value=[SimpleNamespace(text='') for _ in range(4)])
        with self.assertRaisesRegex(ValueError, 'asr_text_missing'):
            worker.back_asr(self.asr_args, factory=Mock(return_value=model))
        factory = Mock(side_effect=AssertionError('do not retry unknown ASR'))
        with self.assertRaisesRegex(ValueError, 'unknown_batch_requires_reconciliation'):
            worker.back_asr(self.asr_args, factory=factory)
        factory.assert_not_called()

    def test_asr_requires_local_model_and_diagnostic_tts(self):
        self.tts()
        factory = Mock(side_effect=AssertionError('preflight must precede runtime'))
        (self.model_path / 'model.safetensors').unlink()
        with self.assertRaisesRegex(ValueError, 'local_model_weights_missing'):
            worker.back_asr(self.asr_args, factory=factory)
        source = worker.read(self.asr_args.tts_manifest); source['humanApproval'] = True
        self.write(self.asr_args.tts_manifest, source)
        with self.assertRaisesRegex(ValueError, 'tts_manifest_not_fixed_diagnostic'):
            worker.back_asr(self.asr_args, factory=factory)
        factory.assert_not_called()

    def test_output_lock_prevents_parallel_dispatch(self):
        with worker.output_lock(self.root / 'locked'):
            with self.assertRaisesRegex(ValueError, 'diagnostic_worker_already_running'):
                with worker.output_lock(self.root / 'locked'):
                    self.fail('second lock unexpectedly succeeded')


if __name__ == '__main__':
    unittest.main()
