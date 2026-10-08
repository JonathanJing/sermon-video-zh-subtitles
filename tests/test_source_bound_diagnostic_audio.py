"""Offline machine-gate and executable audio configuration checks; no GPU."""
import copy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from scripts.experiments import replay_fixed_clip_local_models as worker
from scripts.experiments import diagnostic_audio_inputs as inputs
from scripts.sermon_unified import resources
from tests import test_codex_layer2_diagnostic as chain_fixtures
from tests import test_replay_fixed_clip_local_models as audio_fixtures


class FakePool:
    replicas = 8
    failure = None
    instances = []
    def __init__(self, checkpoint, *, factory, engine_kwargs, replicas, telemetry):
        self.rows, self.calls, self.closed = {}, [], False
        self.replicas = replicas
        self.instances.append(self)
    def start(self):
        pass
    def submit(self, start, requests, *, seed):
        self.calls.append((start, len(requests), seed))
        self.rows[start] = [{'identity': row['identity'], 'wave': [.03] * 1600,
                            'sampleRate': 16000} for row in requests]
    def result(self, start):
        if start == self.failure:
            raise RuntimeError('fixture replica outcome unknown')
        return self.rows.pop(start)
    def generation_seconds(self, start):
        return 0.0
    def close(self):
        self.closed = True


class SourceBoundAudioTests(unittest.TestCase):
    def setUp(self):
        voice = audio_fixtures.FixedClipReplayTests()
        voice.setUp(); self.addCleanup(voice.doCleanups)
        self.voice = voice
        self.args = copy.copy(voice.tts_args)
        self.args.diagnostic_fixture = voice.root / 'fixture'
        self.args.diagnostic_candidate = voice.root / 'diagnostic-candidate.json'
        self.args.batch_size = 8
        self.args.cpu_workers = 4
        self.args.replicas = 8
        policy = {'schemaVersion': resources.POLICY_VERSION, 'brokerRoot': str(voice.root / 'broker'),
                  'capacities': {'cpu': 4, 'online_api': 0, 'codex_cli': 1, 'spark_tts': 1, 'publisher': 0}}
        self.args.resource_policy = voice.root / 'resource-policy.json'
        voice.write(self.args.resource_policy, policy)
        self.policy = policy
        FakePool.instances, FakePool.failure = [], None

    def fake_binding(self, count=46):
        units = 136 if count == 46 else count * 3
        groups = [{'groupId': f'g{i:03d}', 'sourceUnitIds': [f'u{j:03d}' for j in range(i * 3, min(i * 3 + 3, units))], 'text': f'诊断{i}。',
                   'textSha256': worker.hashlib.sha256(f'诊断{i}。'.encode()).hexdigest()} for i in range(count)]
        binding = {'sourceMediaSha256': worker.sha(self.args.media), 'sourceUnitCount': units,
                   'targetLocale': 'zh-Hans',
                   'groupCount': count, 'sourceWindow': {'startSeconds': 63.32, 'endSeconds': 668.820007},
                   'fixtureDirectory': str(self.args.diagnostic_fixture),
                   'candidatePath': str(self.args.diagnostic_candidate), 'evidencePath': str(self.args.evidence),
                   'mediaPath': str(self.args.media), 'inputFileSha256': {}}
        return groups, binding

    def test_fake_46_group_tts_8x8_cpu4_then_single_asr_batch8_and_cached_zero_calls(self):
        groups, binding = self.fake_binding()
        with patch.object(inputs, 'checked_inputs', return_value=(groups, binding)), \
             patch('scripts.spark_tts_replica_pool.ReplicaPool', FakePool), patch('builtins.print'):
            tts = worker.render_tts(self.args)
            self.assertEqual(FakePool.instances[0].calls, [(i, min(8, 46-i), 42+i) for i in range(0, 46, 8)])
            self.assertTrue(FakePool.instances[0].closed)
            self.assertEqual(tts['groupCount'], 46)
            self.assertEqual(tts['cpuRuntime']['workers'], 4)
            self.assertEqual(tts['cpuRuntime']['submittedUnits'], 46)
            self.assertEqual(len(tts['batchReceipts']), 6)
            factory = Mock(side_effect=AssertionError('cache must not load'))
            self.assertEqual(worker.render_tts(self.args, factory=factory), tts)
            factory.assert_not_called()
            asr_args = copy.copy(self.voice.asr_args)
            asr_args.batch_size = 8
            asr_args.resource_policy = self.args.resource_policy
            model = audio_fixtures.FakeASR()
            loader = Mock(return_value=model)
            asr = worker.back_asr(asr_args, factory=loader)
            loader.assert_called_once_with(self.voice.model_path.resolve(), device='cuda:0', batch_size=8, language='Chinese')
            self.assertEqual([len(call) for call in model.calls], [8, 8, 8, 8, 8, 6])
            self.assertEqual(asr['modelReplicas'], 1)
            self.assertEqual(asr['batchSize'], 8)
            self.assertFalse(asr['productionEligible'] or asr['releaseEligible'] or asr['humanApproval'])
            self.assertEqual(worker.back_asr(asr_args, factory=factory), asr)
            ledger = worker.read(self.voice.root / 'broker' / resources.BROKER_LOCK_ID / 'resources.json')
            self.assertTrue(all(row['status'] == 'released' for row in ledger['reservations'].values()))

    def test_replica_unknown_retains_shared_gpu_and_never_replays(self):
        groups, binding = self.fake_binding()
        FakePool.failure = 8
        with patch.object(inputs, 'checked_inputs', return_value=(groups, binding)), \
             patch('scripts.spark_tts_replica_pool.ReplicaPool', FakePool), patch('builtins.print'):
            with self.assertRaisesRegex(RuntimeError, 'outcome unknown'):
                worker.render_tts(self.args)
            self.assertFalse((self.args.out / 'manifest.json').exists())
            self.assertTrue((self.args.out / 'batch-001.started.json').exists())
            ledger = worker.read(self.voice.root / 'broker' / resources.BROKER_LOCK_ID / 'resources.json')
            self.assertEqual([row['status'] for row in ledger['reservations'].values()], ['held'])
            factory = Mock(side_effect=AssertionError('unknown cannot load'))
            with self.assertRaisesRegex(ValueError, 'unknown_batch_requires_reconciliation'):
                worker.render_tts(self.args, factory=factory)
            factory.assert_not_called()

    def test_busy_gpu_and_replica_without_policy_start_no_model(self):
        groups, binding = self.fake_binding()
        resources.reserve(self.policy, operation_id='other', owner='other', resource='spark_tts')
        factory = Mock(side_effect=AssertionError('no capacity'))
        with patch.object(inputs, 'checked_inputs', return_value=(groups, binding)):
            with self.assertRaisesRegex(Exception, 'resource_capacity_busy'):
                worker.render_tts(self.args, factory=factory)
            self.assertFalse(list(self.args.out.glob('batch-*.started.json')))
            self.args.resource_policy = None
            with self.assertRaisesRegex(ValueError, 'shared_gpu_policy'):
                worker.render_tts(self.args, factory=factory)
        factory.assert_not_called()

    def test_current_producer_admits_real_source_bound_fake_cli_candidate_and_tamper_blocks_audio(self):
        chain = chain_fixtures.DiagnosticChainTests()
        chain.setUp(); self.addCleanup(chain.doCleanups)
        chain.source['source']['media']['sha256'] = worker.sha(self.args.media)
        chain.rebind(); chain.freeze(); chain.invoke()
        self.args.diagnostic_fixture = chain.fixture
        self.args.diagnostic_candidate = chain.out / 'diagnostic-candidate.json'
        self.args.evidence = chain.out / 'evidence.json'
        groups, binding = inputs.checked_inputs(self.args)
        self.assertEqual(len(groups), 2)
        self.assertFalse(binding['productionEligible'] or binding['actualHumanApproval'])
        self.assertEqual(binding['sourceWindow'],
                         {k: chain.source['source']['approvedWindow'][k] for k in ('startSeconds', 'endSeconds')})
        inputs.check_frozen(binding)
        envelope = worker.read(self.args.diagnostic_candidate)
        envelope['productionEligible'] = True
        chain.out.joinpath('diagnostic-candidate.json').write_text(worker.json.dumps(envelope))
        factory = Mock(side_effect=AssertionError('tamper must fail before load'))
        with self.assertRaisesRegex(ValueError, 'candidate_scope_changed'):
            worker.render_tts(self.args, factory=factory)
        factory.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'frozen_input_changed'):
            inputs.check_frozen(binding)

    def test_local_asr_consumes_actual_max_inference_batch8(self):
        loader = Mock()
        with patch.dict(sys.modules, {'torch': SimpleNamespace(bfloat16='fake-bf16'),
                                     'qwen_asr': SimpleNamespace(Qwen3ASRModel=loader)}):
            worker.LocalASR(self.voice.model_path, device='cuda:0', batch_size=8, session_verifier=lambda: {'status':'offline_test'})
        self.assertEqual(loader.from_pretrained.call_args.kwargs['max_inference_batch_size'], 8)

    def test_explicit_frozen_profile_requires_actual_cpu4_and_asr8_consumption(self):
        from scripts.production_concurrency_profile import profile_v1
        groups, binding = self.fake_binding(8)
        binding['concurrencyProfile'] = profile_v1()
        self.args.cpu_workers = 0
        with patch.object(inputs, 'checked_inputs', return_value=(groups, binding)), \
             patch('scripts.spark_tts_replica_pool.ReplicaPool', FakePool), patch('builtins.print'):
            with self.assertRaisesRegex(ValueError, 'cpu_profile_not_consumed'):
                worker.render_tts(self.args)
            self.args.cpu_workers = 4
            worker.render_tts(self.args)
            asr_args = copy.copy(self.voice.asr_args)
            asr_args.batch_size = 4
            factory = Mock(side_effect=AssertionError('profile mismatch cannot load'))
            with self.assertRaisesRegex(ValueError, 'asr_profile_not_consumed'):
                worker.back_asr(asr_args, factory=factory)
            factory.assert_not_called()

    def test_registered_korean_spanish_voice_and_asr_language_are_consumed_without_approval(self):
        registry = worker.read(self.voice.registry_path)
        registry['speakers'][0]['authorization']['purposes'].append('multilingual_voice_demo')
        for locale, language in (('ko', 'Korean'), ('es', 'Spanish')):
            registry['speakers'][0]['localeCapabilities'].append(
                {'targetLocale': locale, 'modelLanguage': language, 'status': 'unverified_poc'})
        self.voice.write(self.voice.registry_path, registry)
        for locale, language in (('ko', 'Korean'), ('es', 'Spanish')):
            groups, binding = self.fake_binding(8)
            binding['targetLocale'] = locale
            args = copy.copy(self.args); args.out = self.voice.root / ('tts-' + locale)
            with patch.object(inputs, 'checked_inputs', return_value=(groups, binding)), \
                 patch('scripts.spark_tts_replica_pool.ReplicaPool', FakePool), patch('builtins.print'):
                tts = worker.render_tts(args)
                self.assertEqual(tts['voice']['modelLanguage'], language)
                self.assertFalse(tts['humanApproval'] or tts['productionEligible'])
                asr_args = copy.copy(self.voice.asr_args)
                asr_args.tts_manifest = args.out / 'manifest.json'
                asr_args.out = self.voice.root / ('asr-' + locale)
                asr_args.batch_size = 8; asr_args.resource_policy = self.args.resource_policy
                loader = Mock(return_value=audio_fixtures.FakeASR())
                asr = worker.back_asr(asr_args, factory=loader)
                self.assertEqual(loader.call_args.kwargs['language'], language)
                self.assertEqual(asr['targetLocale'], locale)
