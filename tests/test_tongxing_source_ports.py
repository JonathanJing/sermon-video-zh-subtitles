"""S0 of the L1 move: the source layer's ports are bound late to the scripts implementations."""
import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import tongxing_host as host
from scripts import sermon_pipeline
from tongxing_production.compute import openai_runtime as sermon_openai_runtime
from tongxing_production.text import controller
from scripts import build_english_source_package as builder
from scripts import judge_english_source_for_translation as judge
from scripts import run_sentence_interpretation_models as anchors_runner
from tongxing_production.source import sentence_interpretation as anchors
from scripts import sermon_unified_source as stage
from scripts import mfa_alignment
from tongxing_production import ports
from tongxing_production.source import backend as source


class SourcePortsTests(unittest.TestCase):
    def test_host_binds_a_complete_backend(self):
        backend = source.current()
        self.assertIsInstance(backend, source.SourceBackend)
        for record, kind in ((backend.core, ports.Core), (backend.provider, ports.Provider),
                             (backend.code, ports.Code), (backend.mfa, ports.Mfa)):
            self.assertIsInstance(record, kind)
        self.assertEqual(backend.core.repo_root, host.ROOT)
        self.assertEqual(backend.core.artifact_root, host.ROOT / 'artifacts')

    def test_provider_ports_bind_late_so_patches_on_the_implementation_still_intercept(self):
        with patch.object(sermon_pipeline, 'chat_json', return_value={'ok': 1}) as chat:
            self.assertEqual(judge.chat_json('key', {'p': 1}, 2, session_verifier='v'), {'ok': 1})
            chat.assert_called_once_with('key', {'p': 1}, 2, session_verifier='v')
            self.assertEqual(anchors_runner.chat_json('key', {'p': 2}), {'ok': 1})
        with patch.object(sermon_pipeline, 'request_json', return_value={'r': 1}) as request:
            self.assertEqual(source.current().provider.request_json('req', 1, response_observer='o', request_executor='x'), {'r': 1})
            request.assert_called_once_with('req', 1, response_observer='o', request_executor='x')
        with patch.object(sermon_openai_runtime, 'reject_secret_override') as reject:
            source.current().provider.reject_secret_override('secret')
            reject.assert_called_once_with('secret')
        with patch.object(sermon_pipeline, 'mfa_options', return_value={'m': 1}) as options:
            self.assertEqual(source.current().mfa.options('args'), {'m': 1})
            options.assert_called_once_with('args')

    def test_patching_the_module_attribute_still_works_for_existing_tests(self):
        with patch.object(judge, 'chat_json', side_effect=AssertionError('no API')):
            with self.assertRaisesRegex(AssertionError, 'no API'):
                judge.chat_json('key', {})

    def test_code_ports_record_the_same_values_as_before(self):
        code = source.current().code
        for module in (builder, judge, anchors, mfa_alignment):
            path = Path(module.__file__).resolve()
            self.assertEqual(code.module_path(module), path)
            self.assertEqual(code.module_sha256(module), hashlib.sha256(path.read_bytes()).hexdigest())
        with patch.object(controller, 'code_identity', return_value='c' * 64):
            self.assertEqual(code.code_identity(), 'c' * 64)
            self.assertEqual(stage.code.code_identity(), 'c' * 64)

    def test_package_source_layer_imports_no_host(self):
        root = Path(__file__).resolve().parents[1] / 'packages/production/src/tongxing_production'
        for name in ('ports.py', 'source/backend.py', 'source/__init__.py'):
            text = (root / name).read_text(encoding='utf-8')
            self.assertNotIn('scripts', text.replace('scripts/', ''), name)
            self.assertNotIn('__file__', text, name)

    def test_unbound_layer_fails_clearly(self):
        previous = source._current
        try:
            source._current = None
            with self.assertRaises(ports.Unbound):
                source.current()
        finally:
            source._current = previous


if __name__ == '__main__':
    unittest.main()
