import argparse
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import mfa_backend as backend

LOCAL = {'schemaVersion': 1, 'backend': 'macbook-local', 'runtime': {'version': 'fixture'}}
REMOTE = {'schemaVersion': 1, 'backend': 'dgx-spark-ssh', 'runtime': {'version': 'fixture'}}


class MFABackendTests(unittest.TestCase):
    def test_default_preflight_never_loads_mac(self):
        with patch.object(backend, 'local_identity') as local, patch.object(backend.spark, 'preflight', return_value=REMOTE):
            self.assertEqual(backend.preflight(local_options={}, spark_options={}), REMOTE)
        local.assert_not_called()

    def test_connection_failure_uses_mac_and_records_reason(self):
        with patch.object(backend.spark, 'preflight', side_effect=subprocess.CalledProcessError(255, 'ssh')), patch.object(backend, 'local_identity', return_value=LOCAL):
            result = backend.preflight(local_options={}, spark_options={})
        self.assertEqual(result['backend'], LOCAL['backend'])
        self.assertEqual(result['fallbackReason']['phase'], 'preflight')

    def test_explicit_spark_never_falls_back(self):
        with patch.object(backend.spark, 'preflight', side_effect=subprocess.TimeoutExpired('ssh', 1)), patch.object(backend, 'local_identity') as local:
            with self.assertRaises(subprocess.TimeoutExpired):
                backend.preflight(local_options={}, spark_options={}, backend='spark')
        local.assert_not_called()

    def test_explicit_mac_and_disabled_spark_never_contact_network(self):
        for kwargs in ({'backend': 'macbook'}, {'allow_spark_fallback': False}):
            with patch.object(backend, 'local_identity', return_value=LOCAL), patch.object(backend.spark, 'preflight') as remote:
                self.assertEqual(backend.preflight(local_options={}, spark_options={}, **kwargs), LOCAL)
            remote.assert_not_called()

    def test_forced_spark_conflicts_with_disabled_spark(self):
        with self.assertRaises(ValueError):
            backend.preflight(local_options={}, spark_options={}, backend='spark', allow_spark_fallback=False)

    def test_parser_default_and_explicit_routing(self):
        parser = argparse.ArgumentParser()
        backend.add_arguments(parser)
        self.assertEqual(parser.parse_args([]).mfa_backend, 'auto')
        self.assertEqual(parser.parse_args(['--mfa-backend', 'macbook']).mfa_backend, 'macbook')

    def test_bad_spoken_forms_never_contacts_spark(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'forms.json'; path.write_text('{"73:16.":[]}')
            with patch.object(backend.spark, 'preflight') as remote:
                with self.assertRaises(ValueError):
                    backend.preflight(local_options={'spoken_forms_path': path}, spark_options={})
            remote.assert_not_called()

    def test_invalid_reference_is_rejected_before_backend_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            clip = Path(directory) / 'audio'; clip.write_bytes(b'audio')
            with patch.object(backend, 'preflight') as select:
                with self.assertRaisesRegex(ValueError, 'Ambiguous numeric'):
                    backend.align_reference_chunks([{'text': '73:16.', 'start': 0, 'end': 1}], clip, Path(directory) / 'out', local_options={}, spark_options={})
            select.assert_not_called()

    def test_content_or_identity_failures_never_fall_back(self):
        for failure in (ValueError('Unknown phone'), RuntimeError('identity mismatch'), subprocess.CalledProcessError(1, 'mfa', stderr=b'ValueError: cached hash changed')):
            with tempfile.TemporaryDirectory() as directory:
                clip = Path(directory) / 'audio'; clip.write_bytes(b'audio')
                with patch.object(backend.spark, 'preflight', return_value=REMOTE), patch.object(backend.spark, 'align_reference_chunks', side_effect=failure), patch.object(backend, 'local_identity') as local:
                    with self.assertRaises(type(failure)):
                        backend.align_reference_chunks([{'text': 'Hello.', 'start': 0, 'end': 1}], clip, Path(directory) / 'out', local_options={}, spark_options={})
                local.assert_not_called()

    def test_known_remote_resource_exit_falls_back_and_records_actual_mac(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); clip = root / 'audio'; clip.write_bytes(b'audio')
            with patch.object(backend.spark, 'preflight', return_value=REMOTE), patch.object(backend.spark, 'align_reference_chunks', side_effect=subprocess.CalledProcessError(137, 'ssh')), patch.object(backend, 'local_identity', return_value=LOCAL), patch.object(backend.local, 'align_reference_chunks', return_value=[{'text': 'Hello.'}]):
                result = backend.align_reference_chunks([{'text': 'Hello.', 'start': 0, 'end': 1}], clip, root / 'out', local_options={}, spark_options={})
            self.assertEqual(result[0]['alignmentExecutionBackend'], 'macbook-local')
            receipt = json.loads((root / 'out/backend.json').read_text())
            self.assertEqual(receipt['fallbackReason']['phase'], 'alignment')

    def test_remote_success_uses_actual_alignment_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); clip = root / 'audio'; clip.write_bytes(b'audio')
            actual = {**REMOTE, 'runtime': {'version': 'actual'}}
            (root / 'spark-runtime.json').write_text(json.dumps(actual))
            with patch.object(backend.spark, 'preflight', return_value=REMOTE), patch.object(backend.spark, 'align_reference_chunks', return_value=[{'mfaManifest': str(root / 'manifest.json')}]), patch.object(backend, 'local_identity') as local:
                backend.align_reference_chunks([{'text': 'Hello.', 'start': 0, 'end': 1}], clip, root / 'out', local_options={}, spark_options={})
            self.assertEqual(json.loads((root / 'out/backend.json').read_text())['runtime'], actual['runtime'])
            local.assert_not_called()

    def test_native_runtime_change_uses_separate_inner_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); clip = root / 'audio'; clip.write_bytes(b'audio')
            updated = {**LOCAL, 'runtime': {'version': 'changed'}}
            with patch.object(backend, 'local_identity', side_effect=[LOCAL, updated]), patch.object(backend.local, 'align_reference_chunks', return_value=[{'text': 'Hello.'}]) as align:
                for _ in range(2):
                    backend.align_reference_chunks([{'text': 'Hello.', 'start': 0, 'end': 1}], clip, root / 'out', local_options={}, spark_options={}, backend='macbook')
            self.assertNotEqual(align.call_args_list[0].args[2], align.call_args_list[1].args[2])

    def test_modified_audio_prevents_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); clip = root / 'audio'; clip.write_bytes(b'audio')
            def fail(*args, **kwargs):
                clip.write_bytes(b'changed')
                raise subprocess.CalledProcessError(137, 'ssh')
            with patch.object(backend.spark, 'preflight', return_value=REMOTE), patch.object(backend.spark, 'align_reference_chunks', side_effect=fail), patch.object(backend, 'local_identity') as local:
                with self.assertRaisesRegex(ValueError, 'inputs changed'):
                    backend.align_reference_chunks([{'text': 'Hello.', 'start': 0, 'end': 1}], clip, root / 'out', local_options={}, spark_options={})
            local.assert_not_called()

    def test_remote_missing_dependency_is_runtime_failure_but_unknown_phone_is_not(self):
        for text, expected in ((b'ModuleNotFoundError: no kalpy', True), (b'ValueError: MFA acoustic model must be an existing local file (no automatic downloads): /missing', True), (b'ValueError: Unknown phone', False)):
            self.assertEqual(backend._runtime_failure(subprocess.CalledProcessError(1, 'ssh', stderr=text)), expected)

    def test_remote_alignment_unknown_outcome_never_retries_mac(self):
        for failure in (subprocess.TimeoutExpired('ssh', 1), subprocess.CalledProcessError(255, 'ssh', stderr=b'Connection closed by remote host')):
            with tempfile.TemporaryDirectory() as directory:
                clip = Path(directory) / 'audio'; clip.write_bytes(b'audio')
                with patch.object(backend.spark, 'preflight', return_value=REMOTE), patch.object(backend.spark, 'align_reference_chunks', side_effect=failure), patch.object(backend, 'local_identity') as local:
                    with self.assertRaises(type(failure)):
                        backend.align_reference_chunks([{'text': 'Hello.', 'start': 0, 'end': 1}], clip, Path(directory) / 'out', local_options={}, spark_options={})
                local.assert_not_called()

    def test_input_changed_during_preflight_never_dispatches(self):
        with tempfile.TemporaryDirectory() as directory:
            clip = Path(directory) / 'audio'; clip.write_bytes(b'audio')
            def select(**kwargs):
                clip.write_bytes(b'changed')
                return REMOTE
            with patch.object(backend.spark, 'preflight', side_effect=select), patch.object(backend.spark, 'align_reference_chunks') as align:
                with self.assertRaisesRegex(ValueError, 'before alignment dispatch'):
                    backend.align_reference_chunks([{'text': 'Hello.', 'start': 0, 'end': 1}], clip, Path(directory) / 'out', local_options={}, spark_options={})
            align.assert_not_called()
