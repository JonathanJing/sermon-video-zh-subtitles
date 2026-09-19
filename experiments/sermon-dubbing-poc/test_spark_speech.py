import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from spark_speech import ASR, SparkModel, remote_command
from spark_transport import dispatch


class SparkSpeechTests(unittest.TestCase):
    def test_default_remote_route_and_no_local_model(self):
        with patch.dict(os.environ, {}, clear=True):
            command = remote_command()
        self.assertEqual(command[0], 'ssh')
        self.assertIn('jonyopenclaw@100.73.116.52', command)
        self.assertIn('achillesjing@192.168.1.152', command[-1])
        self.assertIn('HF_HUB_OFFLINE=1', command[-1])
        self.assertIn('--gpus', command[-1])

    def test_remote_response_must_bind_audio_and_cuda(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / 'clip.wav'; audio.write_bytes(b'audio')
            def run(argv, **kw):
                request = json.loads(kw['input'])
                return subprocess.CompletedProcess(argv, 0, json.dumps({'identity': request['identity'], 'executionHost': 'dgx-spark', 'device': 'cpu'}))
            with patch('spark_speech.subprocess.run', side_effect=run):
                with self.assertRaisesRegex(ValueError, 'identity/device'):
                    SparkModel(ASR).generate(audio, language='English')

    def test_ssh_and_upload_use_mini_credentials(self):
        calls = []
        def run(argv, **kwargs):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0)
        with patch.dict(os.environ, {}, clear=True):
            dispatch(['ssh', '-o', 'BatchMode=yes', 'spark', 'true'], run)
            dispatch(['scp', '-q', '-o', 'BatchMode=yes', '/tmp/file', 'spark:/tmp/out/'], run, check=True)
        self.assertTrue(all('jonyopenclaw@100.73.116.52' in str(c) for c in calls))
        self.assertIn('scp', calls[-2][-1])
        self.assertIn('spark:/tmp/out/', calls[-2][-1])

    def test_download_stages_and_preserves_destination(self):
        calls = []
        def run(argv, **kwargs):
            calls.append(argv); return subprocess.CompletedProcess(argv, 0)
        with patch.dict(os.environ, {}, clear=True):
            dispatch(['scp', '-r', 'spark:/work/render', '/local/quarantine'], run, check=True)
        self.assertEqual(calls[-2][-1], '/local/quarantine')
        self.assertIn('/render', calls[-2][-2])

if __name__ == '__main__':
    unittest.main()

class MacBookFallbackTests(unittest.TestCase):
    def test_infrastructure_filter_does_not_accept_bad_input(self):
        from speech_backend import infrastructure_error
        self.assertTrue(infrastructure_error(ImportError('mlx missing')))
        self.assertTrue(infrastructure_error(RuntimeError('Metal out of memory')))
        self.assertFalse(infrastructure_error(ValueError('bad audio input')))
        self.assertFalse(infrastructure_error(RuntimeError('nonfinite output')))

    def test_macbook_mode_never_constructs_spark(self):
        from speech_backend import SpeechModel, ASR
        with patch.dict(os.environ, {'SERMON_SPEECH_BACKEND': 'macbook'}), patch.dict('sys.modules', {'mlx_audio.stt.utils': None}), patch('speech_backend.SparkModel') as remote:
            with self.assertRaises(ImportError):
                SpeechModel(ASR)
            remote.assert_not_called()

    def test_explicit_spark_records_reason(self):
        from speech_backend import SpeechModel, ASR
        with patch.dict(os.environ, {'SERMON_SPEECH_BACKEND': 'spark'}), patch('speech_backend.SparkModel') as remote:
            model = SpeechModel(ASR)
            self.assertEqual(model.fallback_reason, 'explicit_spark_selection')
            remote.assert_called_once()

class RendererBackendIdentityTests(unittest.TestCase):
    def test_mps_and_cuda_cache_identities_are_distinct(self):
        from render_weekly_audio import render_identity
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp) / 'job.json'; job.write_text('{}')
            mps = render_identity(job, 'checkpoint', device='mps')
            cuda = render_identity(job, 'checkpoint', device='cuda:0')
            self.assertNotEqual(mps, cuda)
            self.assertEqual(mps['precision'], 'float32')
            self.assertEqual(cuda['precision'], 'bfloat16')

class ZeroDurationReviewTests(unittest.TestCase):
    def test_zero_duration_word_marks_corresponding_anchor_for_review(self):
        from align_weekly_source import attach_timing_issues
        from check_weekly_timing import reviewed_anchors
        anchors = [{'blockId': 1, 'start': 0, 'end': 10, 'issues': []}, {'blockId': 2, 'start': 11, 'end': 20, 'issues': []}]
        issues = []
        attach_timing_issues(anchors, issues, [{'reason': 'zero_duration_alignment_word', 'time': 15, 'word': 'to'}])
        self.assertEqual(issues[0]['blockId'], 2)
        reviewed = reviewed_anchors([{'id': 1}, {'id': 2}], anchors)
        self.assertEqual(reviewed[1]['issues'], ['zero_duration_alignment_word'])
        with self.assertRaisesRegex(ValueError, 'explicit review'):
            reviewed_anchors([{'id': 1}, {'id': 2}], anchors, {'blocks': []})

class LocalRenderDataGateTests(unittest.TestCase):
    def test_partial_audio_is_validated_before_missing_model_can_fallback(self):
        import sys
        import hashlib
        import render_weekly_audio as renderer
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); checkpoint = root / 'checkpoint'; checkpoint.mkdir()
            weights = checkpoint / 'model.safetensors'; weights.write_bytes(b'model')
            (checkpoint / 'config.json').write_text(json.dumps({'talker_config': {'spk_id': {'speaker': 0}}}))
            job = root / 'job.json'; job.write_text(json.dumps({'schemaVersion': 'sermon-weekly-dubbing-job-v1', 'voice': {'checkpointSha256': hashlib.sha256(b'model').hexdigest(), 'speakerKey': 'speaker'}, 'units': [{'text': 'test'}]}))
            out = root / 'render'; out.mkdir(); (out / 'unit-0000.wav').write_bytes(b'unreceipted')
            with patch.object(sys, 'argv', ['render', '--job', str(job), '--checkpoint', str(checkpoint), '--out', str(out), '--device', 'mps']), patch.dict('sys.modules', {'qwen_tts': None}):
                with self.assertRaisesRegex(ValueError, 'Unreceipted'):
                    renderer.main()
            self.assertFalse((out / 'runtime-unavailable.json').exists())

class SpeechInventoryTests(unittest.TestCase):
    def test_screening_summary_cannot_mislabel_actual_cached_model(self):
        from test_resume_integrity import candidate_fixture
        import run_weekly_dubbing as runner
        from weekly_dubbing import read
        from poc import write_json
        with tempfile.TemporaryDirectory() as tmp:
            work = candidate_fixture(Path(tmp))
            report = read(work / 'audio/asr-screening.json')
            report['modelIdentities'] = [['wrong-model', 'wrong-revision']]
            write_json(work / 'audio/asr-screening.json', report)
            with self.assertRaisesRegex(ValueError, 'model inventory'):
                runner.validate_screening(work, read(work / 'job.json'), read(work / 'render/report.json'), read(work / 'audio/library.json')['tracks'][0])
