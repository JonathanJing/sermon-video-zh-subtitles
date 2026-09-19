import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import mfa_backend as backend

LOCAL = {'schemaVersion':1, 'backend':'macbook-local', 'runtime':{'version':'fixture'}}
REMOTE = {'schemaVersion':1, 'backend':'dgx-spark-ssh', 'runtime':{'version':'fixture'}}


class MFABackendTests(unittest.TestCase):
    def test_local_success_never_contacts_spark(self):
        with patch.object(backend, 'local_identity', return_value=LOCAL), patch.object(backend.spark, 'preflight') as remote:
            self.assertEqual(backend.preflight(local_options={}, spark_options={}), LOCAL)
        remote.assert_not_called()

    def test_missing_runtime_uses_configured_fallback(self):
        with patch.object(backend, 'local_identity', side_effect=backend.LocalRuntimeUnavailable('missing')), patch.object(backend.spark, 'preflight', return_value=REMOTE) as remote:
            self.assertEqual(backend.preflight(local_options={}, spark_options={'host':'spark'})['backend'], REMOTE['backend'])
        remote.assert_called_once_with(host='spark')

    def test_disabled_fallback_stops_without_network(self):
        with patch.object(backend, 'local_identity', side_effect=backend.LocalRuntimeUnavailable('missing')), patch.object(backend.spark, 'preflight') as remote:
            with self.assertRaises(backend.LocalRuntimeUnavailable):
                backend.preflight(local_options={}, spark_options={}, allow_spark_fallback=False)
        remote.assert_not_called()

    def test_bad_spoken_forms_never_falls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'forms.json'; path.write_text('{"73:16.":[]}')
            with patch.object(backend.spark, 'preflight') as remote:
                with self.assertRaises(ValueError):
                    backend.preflight(local_options={'spoken_forms_path':path, 'mfa_executable':'missing'}, spark_options={})
            remote.assert_not_called()

    def test_invalid_reference_is_rejected_before_backend_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            clip=Path(directory)/'audio'; clip.write_bytes(b'audio')
            with patch.object(backend,'preflight') as select:
                with self.assertRaisesRegex(ValueError,'Ambiguous numeric'):
                    backend.align_reference_chunks([{'text':'73:16.','start':0,'end':1}],clip,Path(directory)/'out',local_options={},spark_options={})
            select.assert_not_called()

    def test_alignment_quality_failure_never_falls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            clip=Path(directory)/'audio'; clip.write_bytes(b'audio')
            with patch.object(backend, 'local_identity', return_value=LOCAL), patch.object(backend.local, 'align_reference_chunks', side_effect=ValueError('Unknown phone')), patch.object(backend.spark, 'preflight') as remote:
                with self.assertRaisesRegex(ValueError,'Unknown phone'):
                    backend.align_reference_chunks([{'text':'Hello.','start':0,'end':1}],clip,Path(directory)/'out',local_options={},spark_options={})
            remote.assert_not_called()

    def test_runtime_timeout_falls_back_with_actual_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); clip=root/'audio'; clip.write_bytes(b'audio')
            manifest=root/'manifest.json'
            (root/'spark-runtime.json').write_text(json.dumps(REMOTE))
            failure=RuntimeError('MFA failed'); failure.__cause__=subprocess.TimeoutExpired('mfa',60)
            with patch.object(backend,'local_identity',return_value=LOCAL), patch.object(backend.local,'align_reference_chunks',side_effect=failure), patch.object(backend.spark,'preflight',return_value=REMOTE), patch.object(backend.spark,'align_reference_chunks',return_value=[{'text':'Hello.','mfaManifest':str(manifest)}]):
                result=backend.align_reference_chunks([{'text':'Hello.','start':0,'end':1}],clip,root/'out',local_options={},spark_options={})
            self.assertEqual(result[0]['alignmentExecutionBackend'],'dgx-spark-ssh')
            receipt=json.loads((root/'out/backend.json').read_text())
            self.assertEqual(receipt['runtime'],REMOTE['runtime'])
            self.assertEqual(receipt['fallbackReason']['phase'],'alignment')

    def test_native_runtime_change_uses_separate_inner_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); clip=root/'audio'; clip.write_bytes(b'audio')
            def result(*args,**kwargs):
                return [{'text':'Hello.','start':0,'end':1}]
            updated={**LOCAL, 'runtime':{'version':'fixture','nativeSha':'changed'}}
            with patch.object(backend,'local_identity',side_effect=[LOCAL,updated]), patch.object(backend.local,'align_reference_chunks',side_effect=result) as align:
                for _ in range(2):
                    backend.align_reference_chunks([{'text':'Hello.','start':0,'end':1}],clip,root/'out',local_options={},spark_options={})
            self.assertNotEqual(align.call_args_list[0].args[2],align.call_args_list[1].args[2])

    def test_generic_alignment_exit_is_not_runtime_failover(self):
        failure=RuntimeError('MFA failed'); failure.__cause__=subprocess.CalledProcessError(1,'mfa')
        self.assertFalse(backend._runtime_failure(failure))

    def test_modified_audio_prevents_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); clip=root/'audio'; clip.write_bytes(b'audio')
            def fail(*args,**kwargs):
                clip.write_bytes(b'changed')
                raise RuntimeError('MFA failed') from subprocess.TimeoutExpired('mfa',60)
            with patch.object(backend,'local_identity',return_value=LOCAL), patch.object(backend.local,'align_reference_chunks',side_effect=fail), patch.object(backend.spark,'preflight') as remote:
                with self.assertRaisesRegex(ValueError,'inputs changed'):
                    backend.align_reference_chunks([{'text':'Hello.','start':0,'end':1}],clip,root/'out',local_options={},spark_options={})
            remote.assert_not_called()
