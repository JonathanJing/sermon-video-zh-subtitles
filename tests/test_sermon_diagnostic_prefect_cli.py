"""Explicit live CLI wiring only: no credential discovery or real dispatch."""
from copy import deepcopy
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import sermon_accounting as accounting
from scripts import sermon_diagnostic_prefect_flow as flow
from scripts import sermon_provider_http as http
from scripts import sermon_review_budget as budget
from scripts import sermon_review_contracts as c
from scripts import sermon_public_snapshot as public
from scripts import sermon_preview_checkpoint_manifest as checkpoint
from tests.diagnostic_dag_fixture import DiagnosticDAGFixture


class DiagnosticCLITests(unittest.TestCase):
    def setUp(self):
        self.f = DiagnosticDAGFixture(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.enterContext(patch.object(accounting, 'execution_identity', return_value=self.f.execution_identity))
        self.config = {'schemaVersion': flow.SCHEMA, 'locales': {'zh-Hans': {
            'localeSpec': deepcopy(self.f.locale_specs['zh-Hans']),
            'previewSpec': deepcopy(self.f.preview_specs['zh-Hans'])}}}
        self.config['locales']['zh-Hans']['previewSpec']['execute'] = True
        self.spec = self.f.root/'flow.json'
        self.spec.write_text(json.dumps(self.config))
        self.args = ['--plan', str(self.f.root/'run-plan.json'), '--continuation',
                     str(self.f.root/'continuation.json'), '--spec', str(self.spec),
                     '--execute', '--key-fd', '9']

    def inspection_only_runtime_and_checkpoint(self):
        # CLI preflight freezes named static inputs. This explicit inert runtime
        # fixture cannot pass the native worker's runtime/process guard and is
        # never executed; native runtime validation has its own real-path suite.
        runtime_file = self.f.root/'inspect-only-inert-runtime-binding'
        runtime_file.write_bytes(b'never execute or import this synthetic runtime')
        runtime = self.f.root/'inspect-only-runtime-manifest.json'
        public.save_once(runtime, {'fixture': 'static_inventory_only_not_native_execution',
            'productionEligible': False, 'files': [{'path': str(runtime_file),
                'sha256': c.bytes_sha256(runtime_file.read_bytes())}]})
        preview = self.config['locales']['zh-Hans']['previewSpec']
        mapping, _ = public.read_snapshot(preview['checkpoint_map_path'])
        selected = mapping['checkpoints'][0]; root = Path(selected['path'])
        # Use the actual complete-tree/declaration validators over inert weights.
        # Keep the primary fixture hash/voice conditioning already bound above.
        for name in checkpoint.REQUIRED_FILES:
            path = root/name
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'{}' if path.suffix == '.json' else b'inert synthetic checkpoint file')
        binding = checkpoint.build(root, self.f.root/'inspect-only-checkpoint-manifest',
            checkpoint_ref=selected['checkpointRef'], conditioning_sha256=checkpoint.sha(root/'model.safetensors'))
        manifest = Path(binding['checkpointManifest']['path'])
        declaration = self.f.root/'stage-declarations/preview.checkpoint.json'
        declaration.parent.mkdir()
        public.save_once(declaration, {'schemaVersion': 'sermon-stage-code-declaration-v1',
            'originalPlanSha256': c.canonical_sha256(self.f.plan), 'stageId': 'preview.checkpoint',
            'moduleAdditions': {}, 'externalRuntimeSha256': {
                'previewCheckpointManifest': binding['checkpointManifest']['fileBytesSha256'],
                'previewCheckpointTree': binding['treeSha256']}})
        checkpoint.validate_declaration(self.f.root, declaration, binding, self.f.context)
        preview.update(runtime_manifest_path=str(runtime), checkpoint_manifest_path=str(manifest),
            checkpoint_stage_declaration_path=str(declaration))
        self.spec.write_bytes(c.canonical_bytes(self.config))
        return (runtime, runtime_file, manifest, Path(binding['checkpointInventory']['path']), declaration)

    def test_live_fixture_refusal_happens_before_credential_read(self):
        with patch.object(flow, '_read_key_fd') as read_key, self.assertRaisesRegex(
                ValueError, 'fixture_cannot_become_live'):
            flow.main(self.args)
        read_key.assert_not_called()
        self.assertEqual(len(self.f.transport.observations), 2)

    def test_expired_original_window_and_invalid_locale_preflight_precede_key(self):
        (self.f.root/'offline-business-scope.json').unlink()
        path = self.f.root/'budget'/budget.STORE_ID/'provider-run/state.json'
        before = path.read_bytes()
        state = json.loads(before)
        state['startedMonotonic'] -= state['config']['totalWallSeconds'] + 1
        path.write_text(json.dumps(state))
        with patch.object(flow, '_read_key_fd') as read_key, self.assertRaises(ValueError):
            flow.main(self.args)
        read_key.assert_not_called()
        path.write_bytes(before)
        policy = Path(self.config['locales']['zh-Hans']['localeSpec']['policy'])
        value = json.loads(policy.read_text()); value['sourceScope']['englishSourcePackageJsonSha256'] = '0'*64
        policy.write_text(json.dumps(value))
        with patch.object(flow, '_read_key_fd') as read_key, self.assertRaises(ValueError):
            flow.main(self.args)
        read_key.assert_not_called()
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(len(self.f.transport.observations), 2)

    def test_missing_live_manifest_and_invalid_config_reject_before_key_or_run(self):
        (self.f.root/'offline-business-scope.json').unlink()
        before = (self.f.root/'budget'/budget.STORE_ID/'provider-run/state.json').read_bytes()
        with patch.object(flow, '_read_key_fd') as read_key, patch.object(flow, 'run') as execute, \
                self.assertRaisesRegex(ValueError, 'diagnostic_flow_preview_runtime_manifest_required'):
            flow.main(self.args)
        read_key.assert_not_called(); execute.assert_not_called()
        self.inspection_only_runtime_and_checkpoint()
        valid = deepcopy(self.config)
        for changed, reason in (({'schemaVersion': 'unknown', 'locales': valid['locales']}, 'diagnostic_flow_config_invalid'),
                (deepcopy(valid), 'diagnostic_flow_preview_checkpoint_manifest_required')):
            if reason.endswith('checkpoint_manifest_required'):
                changed['locales']['zh-Hans']['previewSpec'].pop('checkpoint_stage_declaration_path')
            self.spec.write_bytes(c.canonical_bytes(changed))
            with self.subTest(reason=reason), patch.object(flow, '_read_key_fd') as read_key, \
                    patch.object(flow, 'run') as execute, self.assertRaisesRegex(ValueError, reason):
                flow.main(self.args)
            read_key.assert_not_called(); execute.assert_not_called()
        self.assertEqual((self.f.root/'budget'/budget.STORE_ID/'provider-run/state.json').read_bytes(), before)
        self.assertEqual(len(self.f.transport.observations), 2)

    def test_valid_live_wiring_uses_bounded_default_executor_and_does_not_log_key(self):
        # Test-only conversion of an entirely synthetic store, never real data.
        (self.f.root/'offline-business-scope.json').unlink()
        static_inputs = self.inspection_only_runtime_and_checkpoint()
        def inspect_only(session, config):
            self.assertFalse(session.offline_fixture)
            self.assertEqual(session.evidence_mode, 'current_execution')
            self.assertIs(session.subject.executor, http.execute)
            self.assertEqual(session.subject.store.store_sha256, self.f.store.store_sha256)
            self.assertEqual(session.deadline, self.f.state['startedMonotonic'] + self.f.config['totalWallSeconds'])
            self.assertNotIn('fixture-private-key', json.dumps(session.binding))
            frozen = flow._inventory(config, session)
            for path in static_inputs:
                self.assertEqual(frozen[str(path)], c.bytes_sha256(path.read_bytes()))
            self.assertEqual(config, self.config)
            return {'status': 'wiring_checked_without_execution'}
        with patch.object(flow, '_read_key_fd', return_value='fixture-private-key'), \
                patch.object(flow, 'run', side_effect=inspect_only) as execute, \
                patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('network forbidden')) as network, \
                patch('sys.stdout', new=io.StringIO()) as output:
            flow.main(self.args)
        execute.assert_called_once()
        network.assert_not_called()
        self.assertNotIn('fixture-private-key', output.getvalue())
        self.assertEqual(len(self.f.transport.observations), 2)


if __name__ == '__main__':
    unittest.main()
