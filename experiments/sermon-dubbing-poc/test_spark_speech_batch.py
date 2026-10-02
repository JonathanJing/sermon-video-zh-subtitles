"""Offline batch transport/residency tests; never launch SSH or actual models."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import spark_speech as client
import spark_speech_worker as worker
import speech_backend as backend


class FakeAudio:
    ndim = 1

    def __len__(self):
        return 2


class BatchFixture(unittest.TestCase):
    def inputs(self, folder, count=3, align=False):
        rows = []
        for index in range(count):
            path = Path(folder) / f'{index}.wav'; path.write_bytes(bytes([index + 1]))
            row = {'unitId': index, 'path': path, 'language': 'English', 'max_tokens': 1024, 'locale': 'en'}
            if align:
                row['text'] = 'hello world'
            rows.append(row)
        return rows

    def response(self, request, *, index=0):
        row = request['requests'][index]
        return {'event': 'unit_result', 'batchSha256': request['batchSha256'], 'unitId': row['unitId'],
                'identity': row['identity'], 'executionHost': 'dgx-spark', 'device': 'cuda',
                'modelFilesSha256': {'model.safetensors': 'hash'},
                'workerSha256': hashlib.sha256(Path(worker.__file__).read_bytes()).hexdigest(),
                'text': f'unit-{index}', 'words': []}

    def output(self, request):
        rows = [self.response(request, index=index) for index in range(len(request['requests']))]
        rows.append({'event': 'batch_complete', 'batchSha256': request['batchSha256'], 'count': len(request['requests'])})
        return rows


class BatchTransportTests(BatchFixture):
    def test_one_remote_command_order_and_per_unit_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = self.inputs(tmp)
            def run(argv, **kwargs):
                request = json.loads(kwargs['input'])
                self.assertEqual(len(request['requests']), 3)
                return subprocess.CompletedProcess(argv, 0, stdout='\n'.join(map(json.dumps, self.output(request))))
            receipts = []
            with patch.object(client.subprocess, 'run', side_effect=run) as dispatch:
                model = client.SparkModel(client.ASR)
                results = model.generate_batch(rows, on_result=lambda unit, result, receipt: receipts.append((unit, receipt)))
            self.assertEqual(dispatch.call_count, 1)
            self.assertEqual([result.text for result in results], ['unit-0', 'unit-1', 'unit-2'])
            self.assertEqual([unit for unit, _ in receipts], [0, 1, 2])
            self.assertEqual(receipts[1][1]['identity']['locale'], 'en')

    def test_bad_order_identity_count_and_termination_fail_closed(self):
        for mutation in ('reverse', 'identity', 'extra', 'missing', 'count'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                rows = self.inputs(tmp)
                def run(argv, **kwargs):
                    request = json.loads(kwargs['input']); events = self.output(request)
                    if mutation == 'reverse': events[0], events[1] = events[1], events[0]
                    if mutation == 'identity': events[0]['identity']['audioSha256'] = 'wrong'
                    if mutation == 'extra': events.insert(-1, events[0])
                    if mutation == 'missing': events.pop()
                    if mutation == 'count': events[-1]['count'] = 1
                    return subprocess.CompletedProcess(argv, 0, stdout='\n'.join(map(json.dumps, events)))
                with patch.object(client.subprocess, 'run', side_effect=run), self.assertRaises(ValueError):
                    client.SparkModel(client.ASR).generate_batch(rows)

    def test_bounded_size_duplicate_ids_and_missing_input_before_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = self.inputs(tmp, 9)
            with patch.object(client.subprocess, 'run') as dispatch:
                for request in (rows, [rows[0], rows[0]], [{**rows[0], 'path': Path(tmp) / 'missing'}]):
                    with self.assertRaises((ValueError, FileNotFoundError)):
                        client.SparkModel(client.ASR).generate_batch(request)
                with patch.object(client, 'MAX_BATCH_AUDIO_BYTES', 1), self.assertRaises(ValueError):
                    client.SparkModel(client.ASR).generate_batch(rows[:2])
            dispatch.assert_not_called()

    def test_failed_batch_retains_valid_prefix_and_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipts = []
            def run(argv, **kwargs):
                request = json.loads(kwargs['input'])
                return subprocess.CompletedProcess(argv, 137, stdout=json.dumps(self.response(request)), stderr='killed')
            with patch.object(client.subprocess, 'run', side_effect=run), self.assertRaises(subprocess.CalledProcessError):
                client.SparkModel(client.ASR).generate_batch(self.inputs(tmp), on_result=lambda unit, result, receipt: receipts.append(unit))
            self.assertEqual(receipts, [0])

    def test_timeout_retains_complete_prefix_but_unknown_is_not_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipts = []
            def run(argv, **kwargs):
                request = json.loads(kwargs['input'])
                raise subprocess.TimeoutExpired(argv, 1, output=(json.dumps(self.response(request)) + '\n').encode())
            with patch.object(client.subprocess, 'run', side_effect=run), self.assertRaises(subprocess.TimeoutExpired):
                client.SparkModel(client.ASR).generate_batch(self.inputs(tmp), on_result=lambda unit, result, receipt: receipts.append(unit))
            self.assertEqual(receipts, [0])


class ResidentWorkerTests(BatchFixture):
    def environment(self, snapshot, fail_decode=False, fail_second=False):
        asr, aligner = MagicMock(), MagicMock()
        heard = 0
        def transcribe(**kwargs):
            nonlocal heard
            heard += 1
            if fail_second and heard == 2:
                raise RuntimeError('unit inference failed')
            return [SimpleNamespace(text='heard')]
        asr.from_pretrained.return_value.transcribe.side_effect = transcribe
        aligner.from_pretrained.return_value.align.side_effect = lambda **kwargs: [[SimpleNamespace(text=word, start_time=index, end_time=index + .5) for index, word in enumerate(kwargs['text'].split())]]
        def decode(stream, **kwargs):
            if fail_decode and stream.read() == b'\x03':
                raise ValueError('bad last input')
            return FakeAudio(), 16000
        sf = SimpleNamespace(read=decode)
        torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True), bfloat16='bf16', __version__='fixture')
        hub = MagicMock(); hub.snapshot_download.return_value = str(snapshot)
        modules = {'torch': torch, 'soundfile': sf, 'huggingface_hub': hub,
                   'qwen_asr': SimpleNamespace(Qwen3ASRModel=asr, Qwen3ForcedAligner=aligner),
                   'numpy': SimpleNamespace(isfinite=lambda audio: SimpleNamespace(all=lambda: True))}
        return modules, asr, aligner, hub

    def test_batch_asr_and_aligner_hash_load_once_and_preserve_short_batch(self):
        for align in (False, True):
            with self.subTest(align=align), tempfile.TemporaryDirectory() as tmp:
                snapshot = Path(tmp) / 'snapshot'; snapshot.mkdir(); weights = snapshot / 'model.safetensors'; weights.write_bytes(b'weights')
                model = client.ALIGNER if align else client.ASR
                frozen = client.freeze_requests(self.inputs(tmp, 3, align=align), model)
                request = {'schemaVersion': client.BATCH_SCHEMA, 'batchSha256': client.batch_sha256(frozen), 'requests': frozen}
                modules, asr, aligner, hub = self.environment(snapshot)
                events, reads = [], []
                original = Path.open
                def counted(path, *args, **kwargs):
                    if path == weights: reads.append(path)
                    return original(path, *args, **kwargs)
                with patch.dict(sys.modules, modules), patch.object(worker.platform, 'system', return_value='Linux'), patch.object(worker.platform, 'machine', return_value='aarch64'), patch('importlib.metadata.version', return_value='fixture'), patch.object(sys, 'argv', ['worker', 'fixture-code']), patch.object(Path, 'open', counted):
                    worker.execute(request, events.append)
                self.assertEqual((aligner if align else asr).from_pretrained.call_count, 1)
                self.assertEqual(hub.snapshot_download.call_count, 1)
                self.assertEqual(reads, [weights])
                self.assertEqual([event['unitId'] for event in events[:-1]], [0, 1, 2])
                self.assertEqual(events[-1]['count'], 3)

    def test_decode_all_inputs_before_load_or_emitting_any_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = Path(tmp) / 'snapshot'; snapshot.mkdir(); (snapshot / 'weights').write_bytes(b'weights')
            frozen = client.freeze_requests(self.inputs(tmp), client.ASR)
            modules, asr, _, _ = self.environment(snapshot, fail_decode=True)
            events = []
            with patch.dict(sys.modules, modules), patch.object(worker.platform, 'system', return_value='Linux'), patch.object(worker.platform, 'machine', return_value='aarch64'), self.assertRaises(ValueError):
                worker.execute({'schemaVersion': client.BATCH_SCHEMA, 'batchSha256': client.batch_sha256(frozen), 'requests': frozen}, events.append)
            asr.from_pretrained.assert_not_called()
            self.assertEqual(events, [])

    def test_worker_partial_failure_flushes_prefix_without_completion_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = Path(tmp) / 'snapshot'; snapshot.mkdir(); (snapshot / 'weights').write_bytes(b'weights')
            frozen = client.freeze_requests(self.inputs(tmp), client.ASR)
            modules, asr, _, _ = self.environment(snapshot, fail_second=True)
            events = []
            with patch.dict(sys.modules, modules), patch.object(worker.platform, 'system', return_value='Linux'), patch.object(worker.platform, 'machine', return_value='aarch64'), patch('importlib.metadata.version', return_value='fixture'), patch.object(sys, 'argv', ['worker', 'fixture']), self.assertRaises(RuntimeError):
                worker.execute({'schemaVersion': client.BATCH_SCHEMA, 'batchSha256': client.batch_sha256(frozen), 'requests': frozen}, events.append)
            self.assertEqual(asr.from_pretrained.call_count, 1)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]['event'], 'unit_result')

    def test_single_request_protocol_compatibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = Path(tmp) / 'snapshot'; snapshot.mkdir(); (snapshot / 'weights').write_bytes(b'weights')
            frozen = client.freeze_requests(self.inputs(tmp, 1), client.ASR)[0]
            modules, _, _, _ = self.environment(snapshot)
            events = []
            with patch.dict(sys.modules, modules), patch.object(worker.platform, 'system', return_value='Linux'), patch.object(worker.platform, 'machine', return_value='aarch64'), patch('importlib.metadata.version', return_value='fixture'), patch.object(sys, 'argv', ['worker', 'fixture']):
                worker.execute({key: frozen[key] for key in ('identity', 'audio')}, events.append)
            self.assertEqual(len(events), 1)
            self.assertNotIn('event', events[0])
            self.assertEqual(events[0]['identity'], frozen['identity'])


class BackendBatchTests(BatchFixture):
    def local_modules(self, local):
        return {'huggingface_hub': SimpleNamespace(snapshot_download=lambda **kwargs: '/cached'),
                'mlx_audio.stt.utils': SimpleNamespace(load_model=lambda path: local),
                'mlx.core': SimpleNamespace(clear_cache=lambda: None),
                'mlx': SimpleNamespace(core=SimpleNamespace(clear_cache=lambda: None))}

    def test_known_resource_failure_falls_back_only_remaining_frozen_units(self):
        with tempfile.TemporaryDirectory() as tmp:
            requests = self.inputs(tmp)
            remote, local = MagicMock(), MagicMock()
            def generate(rows, *, on_result):
                bound = client.freeze_requests(rows, client.ASR)
                on_result(rows[0]['unitId'], SimpleNamespace(text='spark', segments=[]), {'identity': bound[0]['identity'], 'device': 'cuda'})
                raise subprocess.CalledProcessError(137, 'ssh')
            remote.generate_batch.side_effect = generate
            local.generate.return_value = SimpleNamespace(text='mac', segments=[])
            receipts = []
            with patch.dict(os.environ, {'SERMON_SPEECH_BACKEND': 'auto'}), patch.object(backend, 'SparkModel', return_value=remote), patch.dict(sys.modules, self.local_modules(local)):
                model = backend.SpeechModel(backend.ASR)
                results = model.generate_batch(requests, on_result=lambda unit, result, receipt: receipts.append(receipt))
            self.assertEqual([result.text for result in results], ['spark', 'mac', 'mac'])
            self.assertEqual(local.generate.call_count, 2)
            self.assertEqual(local.generate.call_args_list[0].args[0], requests[1]['path'])
            self.assertEqual(receipts[0]['model'], client.ASR[0])
            self.assertEqual(receipts[1]['model'], backend.ASR[0])
            self.assertIn('Spark', receipts[1]['fallbackReason'])

    def test_timeout_disconnect_and_corrupt_response_never_load_mac(self):
        for failure in (subprocess.TimeoutExpired('ssh', 1), subprocess.CalledProcessError(255, 'ssh', stderr='Connection closed'), ValueError('identity changed')):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'SERMON_SPEECH_BACKEND': 'auto'}), patch.object(backend, 'SparkModel') as remote, patch.object(backend.SpeechModel, '_macbook') as local:
                remote.return_value.generate_batch.side_effect = failure
                with self.assertRaises(type(failure)):
                    backend.SpeechModel(backend.ASR).generate_batch(self.inputs(tmp))
                local.assert_not_called()

    def test_input_mutation_and_cache_callback_failure_never_load_mac(self):
        for mutate in (True, False):
            with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'SERMON_SPEECH_BACKEND': 'auto'}), patch.object(backend, 'SparkModel') as remote, patch.object(backend.SpeechModel, '_macbook') as local:
                rows = self.inputs(tmp)
                def generate(requests, *, on_result):
                    if mutate:
                        rows[1]['path'].write_bytes(b'changed')
                        raise subprocess.CalledProcessError(137, 'ssh')
                    frozen = client.freeze_requests(requests, client.ASR)
                    on_result(0, SimpleNamespace(text='ok'), {'identity': frozen[0]['identity']})
                remote.return_value.generate_batch.side_effect = generate
                with self.assertRaises((ValueError, OSError)):
                    backend.SpeechModel(backend.ASR).generate_batch(rows, on_result=lambda *args: (_ for _ in ()).throw(OSError('cache write failed')))
                local.assert_not_called()

    def test_short_bounded_batches_and_cli_defaults(self):
        import argparse
        parser = argparse.ArgumentParser()
        with patch.dict(os.environ, {'SERMON_SPEECH_BATCH_SIZE': '4'}): backend.add_batch_argument(parser)
        self.assertEqual(parser.parse_args([]).speech_batch_size, 4)
        self.assertEqual(list(map(len, backend.bounded_batches(list(range(9)), 4))), [4, 4, 1])

class DispatchJournalTests(BatchFixture):
    def test_unknown_transport_survives_prefix_callback_error_and_blocks_next_dispatch(self):
        for timeout in (True, False):
            with self.subTest(timeout=timeout), tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'SERMON_SPEECH_BACKEND': 'auto'}):
                rows = self.inputs(tmp); journal = Path(tmp) / 'dispatch'
                def run(argv, **kwargs):
                    request = json.loads(kwargs['input']); output = json.dumps(self.response(request)) + '\n'
                    if timeout:
                        raise subprocess.TimeoutExpired(argv, 1, output=output.encode())
                    return subprocess.CompletedProcess(argv, 255, stdout=output, stderr='Connection closed by remote host')
                with patch.object(client.subprocess, 'run', side_effect=run) as dispatch, patch.object(backend.SpeechModel, '_macbook') as local:
                    model = backend.SpeechModel(backend.ASR)
                    with self.assertRaises((subprocess.TimeoutExpired, subprocess.CalledProcessError)) as raised:
                        model.generate_batch(rows, dispatch_dir=journal, job_sha256='job', on_result=lambda *args: (_ for _ in ()).throw(OSError('receipt disk failed')))
                    self.assertIsInstance(raised.exception.__cause__, OSError)
                    marker = json.loads(next(journal.glob('batch-*.json')).read_text())
                    self.assertEqual(marker['status'], 'unknown')
                    with self.assertRaisesRegex(RuntimeError, 'reconcile'):
                        backend.SpeechModel(backend.ASR).generate_batch(rows[1:], dispatch_dir=journal, job_sha256='job')
                    self.assertEqual(dispatch.call_count, 1)
                    local.assert_not_called()

    def test_unknown_after_valid_prefix_remains_durable(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'SERMON_SPEECH_BACKEND': 'auto'}):
            rows = self.inputs(tmp); journal = Path(tmp) / 'dispatch'; accepted = []
            def run(argv, **kwargs):
                request = json.loads(kwargs['input'])
                raise subprocess.TimeoutExpired(argv, 1, output=(json.dumps(self.response(request)) + '\n').encode())
            with patch.object(client.subprocess, 'run', side_effect=run) as dispatch:
                with self.assertRaises(subprocess.TimeoutExpired):
                    backend.SpeechModel(backend.ASR).generate_batch(rows, dispatch_dir=journal, on_result=lambda unit, *args: accepted.append(unit))
                marker = json.loads(next(journal.glob('batch-*.json')).read_text())
                self.assertEqual(marker['completedUnitIds'], [0])
                with self.assertRaises(RuntimeError):
                    backend.SpeechModel(backend.ASR).generate_batch(rows[1:], dispatch_dir=journal)
                self.assertEqual(dispatch.call_count, 1)
            self.assertEqual(accepted, [0])

    def test_lease_prevents_second_model_dispatch_and_stale_committed_claim(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'SERMON_SPEECH_BACKEND': 'spark'}):
            rows = self.inputs(tmp); journal = Path(tmp) / 'dispatch'
            first, second = backend.SpeechModel(backend.ASR), backend.SpeechModel(backend.ASR)
            def run(argv, **kwargs):
                request = json.loads(kwargs['input'])
                return subprocess.CompletedProcess(argv, 0, stdout='\n'.join(map(json.dumps, self.output(request))))
            def save(*args):
                with self.assertRaisesRegex(RuntimeError, 'owns'):
                    second.generate_batch(rows, dispatch_dir=journal)
            with patch.object(client.subprocess, 'run', side_effect=run) as dispatch:
                first.generate_batch(rows, dispatch_dir=journal, on_result=save)
                self.assertEqual(dispatch.call_count, 1)
                with self.assertRaisesRegex(ValueError, 'already committed'):
                    second.generate_batch(rows, dispatch_dir=journal)
                self.assertEqual(dispatch.call_count, 1)
            self.assertEqual(json.loads(next(journal.glob('batch-*.json')).read_text())['status'], 'complete')

    def test_confirmed_terminal_failure_can_resume_only_uncommitted_units(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'SERMON_SPEECH_BACKEND': 'spark'}):
            rows = self.inputs(tmp); journal = Path(tmp) / 'dispatch'
            def run(argv, **kwargs):
                request = json.loads(kwargs['input'])
                return subprocess.CompletedProcess(argv, 137, stdout=json.dumps(self.response(request)), stderr='killed')
            with patch.object(client.subprocess, 'run', side_effect=run):
                with self.assertRaises(subprocess.CalledProcessError):
                    backend.SpeechModel(backend.ASR).generate_batch(rows, dispatch_dir=journal)
            marker = json.loads(next(journal.glob('batch-*.json')).read_text())
            self.assertEqual(marker['status'], 'confirmed_terminal')
            def success(argv, **kwargs):
                request = json.loads(kwargs['input'])
                return subprocess.CompletedProcess(argv, 0, stdout='\n'.join(map(json.dumps, self.output(request))))
            with patch.object(client.subprocess, 'run', side_effect=success) as dispatch:
                backend.SpeechModel(backend.ASR).generate_batch(rows[1:], dispatch_dir=journal)
            self.assertEqual(dispatch.call_count, 1)

    def test_ssh255_with_prefix_is_unknown_even_when_stderr_mentions_connect_failure(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'SERMON_SPEECH_BACKEND': 'auto'}):
            rows = self.inputs(tmp); journal = Path(tmp) / 'dispatch'
            def run(argv, **kwargs):
                request = json.loads(kwargs['input'])
                return subprocess.CompletedProcess(argv, 255, stdout=json.dumps(self.response(request)),
                                                    stderr='ssh: connect to host spark port 22: Connection refused')
            with patch.object(client.subprocess, 'run', side_effect=run), patch.object(backend.SpeechModel, '_macbook') as mac:
                with self.assertRaises(subprocess.CalledProcessError):
                    backend.SpeechModel(backend.ASR).generate_batch(rows, dispatch_dir=journal)
                mac.assert_not_called()
            self.assertEqual(json.loads(next(journal.glob('batch-*.json')).read_text())['status'], 'unknown')
