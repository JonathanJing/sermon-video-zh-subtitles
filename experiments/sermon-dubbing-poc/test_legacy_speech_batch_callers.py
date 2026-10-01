"""Exercise the actual legacy callers with frozen files and offline fake models."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import align_weekly_source as align
import screen_weekly_audio as screen
from poc import sha256, write_json
from speech_backend import ASR, ALIGNER
from spark_speech import ASR as SPARK_ASR, ALIGNER as SPARK_ALIGNER


class LegacySpeechBatchCallerTests(unittest.TestCase):
    def screen_fixture(self, root, count=5):
        (root / 'render').mkdir(); (root / 'audio').mkdir()
        job = {'inputs': {}, 'units': [{'blockId': i, 'text': '中文'} for i in range(count)]}
        write_json(root / 'job.json', job)
        job_hash = sha256(root / 'job.json')
        for index, unit in enumerate(job['units']):
            raw = root / f'render/unit-{index:04d}.wav'; raw.write_bytes(f'wave{index}'.encode())
            write_json(raw.with_suffix('.json'), {'unit': unit, 'sha256': sha256(raw), 'identity': {'jobSha256': job_hash}})
        write_json(root / 'render/report.json', {'jobSha256': job_hash, 'durationSeconds': 5,
                    'cues': [{'start': i, 'blockId': i} for i in range(count)]})
        mp3 = root / 'audio/zh-natural.mp3'; mp3.write_bytes(b'mp3')
        write_json(root / 'audio/library.json', {'tracks': [{'id': 'zh', 'sha256': sha256(mp3)}]})

    def fake_screen_model(self, calls, fail_after=None):
        class Model:
            def __init__(self, model):
                calls.append(('load', model))
            def generate_batch(self, requests, *, on_result, **kwargs):
                calls.append(('batch', [row['unitId'] for row in requests]))
                for index, row in enumerate(requests):
                    if fail_after is not None and index == fail_after:
                        raise subprocess.CalledProcessError(137, 'fixture')
                    on_result(row['unitId'], SimpleNamespace(text='中文', segments=[]),
                              {'model': SPARK_ASR[0], 'revision': SPARK_ASR[1], 'device': 'cuda'})
        return Model

    def screen_run(self, root, calls, fail_after=None):
        with patch.object(sys, 'argv', ['screen', '--work', str(root), '--speech-batch-size', '4']), patch.object(screen, 'SpeechModel', self.fake_screen_model(calls, fail_after)), patch.object(screen.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, stderr='{"input_i":"-18","input_tp":"-2"}')), patch('builtins.print'):
            screen.main()

    def test_screen_actual_entry_bounded_batches_short_tail_and_cache_only_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); self.screen_fixture(root); calls = []
            self.screen_run(root, calls)
            self.assertEqual([entry[1] for entry in calls if entry[0] == 'batch'], [[0, 1, 2, 3], [4]])
            self.assertEqual(len(list((root / 'audio/unit-screening').glob('unit-*.json'))), 5)
            self.assertEqual(json.loads((root / 'audio/asr-screening.json').read_text())['humanListeningStatus'], 'pending')
            calls.clear(); self.screen_run(root, calls)
            self.assertEqual(calls, [])

    def test_screen_prefix_cache_survives_failure_and_only_missing_units_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); self.screen_fixture(root); calls = []
            with self.assertRaises(subprocess.CalledProcessError): self.screen_run(root, calls, fail_after=2)
            first = root / 'audio/unit-screening/unit-0000.json'; first_hash = sha256(first)
            self.assertEqual(len(list(first.parent.glob('unit-*.json'))), 2)
            self.assertFalse((root / 'audio/asr-screening.json').exists())
            calls.clear(); self.screen_run(root, calls)
            self.assertEqual([entry[1] for entry in calls if entry[0] == 'batch'], [[2, 3, 4]])
            self.assertEqual(sha256(first), first_hash)

    def test_screen_corrupt_last_input_or_cache_stops_before_any_model(self):
        for corrupt_cache in (False, True):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); self.screen_fixture(root); calls = []
                if corrupt_cache:
                    self.screen_run(root, calls)
                    path = root / 'audio/unit-screening/unit-0004.json'
                    row = json.loads(path.read_text()); row['differences'] = [{'wrong': True}]; write_json(path, row)
                else:
                    (root / 'render/unit-0004.wav').write_bytes(b'changed')
                calls.clear()
                with self.assertRaises(ValueError): self.screen_run(root, calls)
                self.assertEqual(calls, [])

    def align_fixture(self, root, cached_asr=False, cached_alignment=False):
        folder = root / 'source-alignment'; folder.mkdir()
        audio = root / 'source.wav'; audio.write_bytes(b'original source')
        job = {'inputs': {'sourceAudio': {'path': str(audio), 'sha256': sha256(audio)}},
               'sourceDurationSeconds': 260, 'sourceStartSeconds': 600,
               'blocks': [{'id': 0, 'en': 'hello world'}]}
        write_json(root / 'job.json', job)
        for offset in range(0, 260, 50):
            wav = folder / f'window-{offset:04d}.wav'; wav.write_bytes(f'wave{offset}'.encode())
            if cached_asr:
                write_json(wav.with_suffix('.asr.json'), {'identity': {'audioSha256': sha256(wav),
                    'sourceSha256': sha256(audio), 'model': ASR[0], 'revision': ASR[1]}, 'text': 'hello world'})
            if cached_alignment:
                # A compatible legacy receipt binds its complete word coverage.
                write_json(wav.with_suffix('.alignment.json'), {'audioSha256': sha256(wav), 'model': ALIGNER[0], 'revision': ALIGNER[1],
                    'words': [{'text': 'hello', 'start': 0, 'end': .5}, {'text': 'world', 'start': 1, 'end': 1.5}]})
        return folder

    def align_run(self, root, calls, fail_after=None):
        class Model:
            def __init__(self, model):
                self.align = model == ALIGNER; calls.append(('load', model))
            def generate_batch(self, requests, *, on_result, **kwargs):
                calls.append(('align' if self.align else 'asr', [row['unitId'] for row in requests]))
                pair = SPARK_ALIGNER if self.align else SPARK_ASR
                for index, row in enumerate(requests):
                    if self.align and fail_after is not None and index == fail_after:
                        raise subprocess.TimeoutExpired('fixture', 1)
                    result = SimpleNamespace(text='hello world', segments=[{'text': 'hello', 'start': 0, 'end': .5}, {'text': 'world', 'start': 1, 'end': 1.5}])
                    on_result(row['unitId'], result, {'model': pair[0], 'revision': pair[1], 'device': 'cuda'})
        with patch.object(sys, 'argv', ['align', '--work', str(root), '--speech-batch-size', '4']), patch.object(align, 'SpeechModel', Model), patch.object(align.subprocess, 'run', side_effect=AssertionError('all windows already staged')), patch('builtins.print'):
            align.main()

    def test_align_real_entry_batches_both_models_and_reuses_cached_alignment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); folder = self.align_fixture(root); calls = []
            self.align_run(root, calls)
            self.assertEqual([entry[1] for entry in calls if entry[0] == 'asr'], [[0, 50, 100, 150], [200, 250]])
            self.assertEqual([entry[1] for entry in calls if entry[0] == 'align'], [[0, 50, 100, 150], [200, 250]])
            self.assertEqual(json.loads((folder / 'report.json').read_text())['humanReview'], 'pending')
            prior = sha256(folder / 'window-0000.alignment.json')
            (folder / 'report.json').unlink(); calls.clear(); self.align_run(root, calls)
            self.assertEqual(calls, [])
            self.assertEqual(sha256(folder / 'window-0000.alignment.json'), prior)

    def test_align_unknown_failure_keeps_prefix_and_resumes_only_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); folder = self.align_fixture(root, cached_asr=True); calls = []
            with self.assertRaises(subprocess.TimeoutExpired): self.align_run(root, calls, fail_after=2)
            prior = sha256(folder / 'window-0000.alignment.json')
            self.assertFalse((folder / 'report.json').exists())
            calls.clear(); self.align_run(root, calls)
            self.assertEqual([entry[1] for entry in calls if entry[0] == 'align'], [[100, 150, 200, 250]])
            self.assertFalse(any(entry[0] == 'asr' for entry in calls))
            self.assertEqual(sha256(folder / 'window-0000.alignment.json'), prior)

    def test_align_legacy_cache_compatible_but_corrupted_last_receipt_prevents_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); folder = self.align_fixture(root, cached_asr=True, cached_alignment=True); calls = []
            path = folder / 'window-0250.alignment.json'
            row = json.loads(path.read_text()); row['words'][0]['text'] = 'wrong'; write_json(path, row)
            with self.assertRaisesRegex(ValueError, 'frozen ASR text'): self.align_run(root, calls)
            self.assertEqual(calls, [])

    def test_both_callers_block_unresolved_dispatch_before_model_or_ffmpeg(self):
        import speech_backend as backend
        for is_align in (False, True):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); calls = []
                if is_align:
                    self.align_fixture(root)
                    folder = root / 'source-alignment/speech-dispatch'
                else:
                    self.screen_fixture(root)
                    folder = root / 'audio/unit-screening/speech-dispatch'
                backend.write_dispatch(folder / 'batch-unknown.json', {'schemaVersion': 'spark-speech-dispatch-v1', 'status': 'unknown'})
                with self.assertRaisesRegex(RuntimeError, 'reconcile'):
                    self.align_run(root, calls) if is_align else self.screen_run(root, calls)
                self.assertEqual(calls, [])
