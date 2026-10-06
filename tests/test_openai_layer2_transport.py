import os
from pathlib import Path
import tempfile
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import openai_layer2_transport as transport
from scripts import sermon_pipeline
from scripts import run_target_language_models as models


class OpenAILayer2TransportTests(unittest.TestCase):
    def test_requires_explicit_project_and_single_attempt(self):
        environment = {
            'SERMON_OPENAI_ENVIRONMENT': 'dev',
            'SERMON_OPENAI_CREDENTIAL_ALIAS': 'tongxing-dev-runtime',
            'OPENAI_PROJECT_ID': 'proj_testdev',
            'OPENAI_API_KEY': 'synthetic-test-key',
        }
        with patch.dict(os.environ, environment, clear=True), \
                patch.object(sermon_pipeline, 'json_request', return_value={'id': 'response'}) as request:
            caller = transport.OpenAILayer2Transport()
            self.assertEqual(caller.execution_identity['backend'], 'openai_api')
            self.assertEqual(caller.execution_identity['route']['projectId'], 'proj_testdev')
            with self.assertRaisesRegex(ValueError, 'selected_openai_credential_override'):
                caller('different', {'model': 'gpt-6.1-sol'})
            with self.assertRaisesRegex(ValueError, 'fast_tier_lacks_worst_case_authorization'):
                caller('synthetic-test-key', {'model': 'gpt-6.1-sol', 'service_tier': 'fast'})
            request.assert_not_called()

    def test_unbound_environment_blocks_before_request(self):
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(sermon_pipeline, 'json_request', side_effect=AssertionError('no dispatch')) as request:
            with self.assertRaisesRegex(ValueError, 'openai_layer2_requires_explicit_dev_or_prod_launcher'):
                transport.OpenAILayer2Transport()
            request.assert_not_called()

    def test_refused_standalone_call_leaves_no_uncertain_marker(self):
        environment = {
            'SERMON_OPENAI_ENVIRONMENT': 'dev',
            'SERMON_OPENAI_CREDENTIAL_ALIAS': 'tongxing-dev-runtime',
            'OPENAI_PROJECT_ID': 'proj_testdev',
            'OPENAI_API_KEY': 'synthetic-test-key',
        }
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, environment, clear=True), \
                patch.object(sermon_pipeline, 'json_request', side_effect=AssertionError('no dispatch')) as request:
            caller = transport.OpenAILayer2Transport()
            output = Path(directory) / 'translation.json'
            for _ in range(2):
                with self.assertRaisesRegex(ValueError, 'fast_tier_lacks_worst_case_authorization'):
                    models._model_call('translator', {'instruction': 'Return JSON.', 'input': {}},
                        {'translator': {'model': 'gpt-6.1-sol', 'reasoningEffort': 'high'}},
                        output, caller.key, caller)
                self.assertFalse(output.with_suffix('.started.json').exists())
            request.assert_not_called()

    def test_shared_text_call_refuses_uncapped_sol_before_request(self):
        payload = {'model': 'gpt-6.1-sol', 'reasoning_effort': 'high', 'service_tier': 'fast'}
        with patch.object(sermon_pipeline, 'json_request', side_effect=AssertionError('dispatched')) as request:
            with self.assertRaisesRegex(ValueError, 'unsupported_budget_capability'):
                sermon_pipeline._chat_json('synthetic-test-key', payload)
            request.assert_not_called()

    def test_bound_standalone_uses_canonical_dispatch_and_rejects_input_override(self):
        from tests.test_produce_target_language_candidate import ProduceTargetLanguageCandidateTests
        fixture = ProduceTargetLanguageCandidateTests('test_compiles_valid_candidate_without_human_approval')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        root = Path('/bound-run')
        config = SimpleNamespace(path=root / 'execution.json', inspection_root=root,
            inspection={'source': 'source.json', 'anchor': 'anchor.json'}, lanes={
                fixture.policy['targetLocale']: {'policy': root / 'policy.json',
                    'plugin': fixture.plugin_path, 'output': root / 'models'}})
        argv = ['layer2', '--english-source-package', str(root / 'source.json'),
                '--anchor', str(root / 'anchor.json'), '--policy', str(root / 'policy.json'),
                '--plugin', str(fixture.plugin_path), '--out-dir', str(root / 'models'),
                '--budget-config', str(config.path), '--budget-authorization', str(root / 'budget.json')]
        for mismatch in (None, '--english-source-package', '--anchor', '--policy', '--plugin', '--out-dir'):
            selected = list(argv)
            if mismatch:
                selected[selected.index(mismatch) + 1] = str(root / 'other-input')
            with self.subTest(mismatch=mismatch), patch.object(sys, 'argv', selected), patch.object(
                    models.producer, '_load', side_effect=[fixture.source, fixture.anchor, fixture.policy]), patch(
                    'scripts.run_target_language_models.require_plugin_identity'), patch(
                    'scripts.run_target_language_models.rule_preflight.preflight'), patch(
                    'scripts.production_spark_admission.require_session'), patch(
                    'scripts.canonical_layer2_controller.load_configuration', return_value=config), patch(
                    'scripts.canonical_layer2_controller.drive', return_value={'status': 'waiting'}) as drive, patch.object(
                    transport, 'OpenAILayer2Transport') as factory:
                if mismatch:
                    with self.assertRaisesRegex(ValueError, 'standalone_budget_inputs_not_registered'):
                        models.main()
                    drive.assert_not_called()
                else:
                    models.main()
                    drive.assert_called_once_with(config.path, fixture.policy['targetLocale'],
                                                  budget_authorization=root / 'budget.json')
                factory.assert_not_called()

    def test_standalone_requires_both_budget_binding_arguments(self):
        argv = ['layer2', '--english-source-package', 'source.json', '--anchor', 'anchor.json',
                '--policy', 'policy.json', '--plugin', 'plugin.py', '--out-dir', 'models']
        for option in ('--budget-config', '--budget-authorization'):
            with self.subTest(option=option), patch.object(sys, 'argv', argv + [option, 'bound.json']), \
                    patch.object(models.producer, '_load') as load:
                with self.assertRaisesRegex(ValueError, 'must be supplied together'):
                    models.main()
                load.assert_not_called()


if __name__ == '__main__':
    unittest.main()
