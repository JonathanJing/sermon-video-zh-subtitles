import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch


from scripts import sermon_accounting as accounting
from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.observability import profile
from tongxing_production.observability import accounting as accounting_impl
from tongxing_production.observability import model_call_observation as observation
from tools.ops import project_codex_credit_usage as projection


class CreditProjectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name); self.source = self.root/'source';self.receipts = self.root/'receipts'
        identity = accounting.execution_identity()
        self.modules = {f'scripts/synthetic_{i:04d}.py': f'{i:064x}' for i in range(800)}
        identity['loadedProjectCodeSha256'] = self.modules
        with patch.object(accounting_impl, 'execution_identity', return_value=identity):
            with profile.session(self.source, 'credit_fixture', work_kind='control', evidence_mode='synthetic'):
                with observation.invocation('gpt-6.1-sol', backend='agent_session', provider='codex',
                        role='production', usage_source='host_telemetry', timing_scope='agent_session_including_tools') as receipt:
                    receipt['usage'] = dict(input_tokens=100, cached_input_tokens=50, output_tokens=20)
        ledger = self.source/'events.jsonl'
        rows = [json.loads(line) for line in ledger.read_text().splitlines()]
        for row in rows:
            if row.get('code') == observation.CODE:
                row['fields'].pop('creditUsage'); row['fields']['schemaVersion'] = observation.SCHEMA
                call_id = row['fields']['callId']
        ledger.write_text(''.join(json.dumps(row)+'\n' for row in rows));self.original = ledger.read_bytes()
        self.response = dict(schemaVersion='codex-cli-layer2-response-v1', requestedModel='gpt-6.1-sol',
            requestedServiceTier='fast', serverModel=None, serverServiceTier=None, completed=True, exitCode=0,
            usage=receipt['usage'],content='这段文字只在私有 fixture 中')
        directory = self.receipts/('translator-'+call_id);directory.mkdir(parents=True)
        self.path = directory/'response.json';self.save()

    def save(self):
        self.path.write_text(json.dumps(self.response, ensure_ascii=False))
        digest = hashlib.sha256(json.dumps(self.response, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        (self.path.parent/'resource-outcome.json').write_text(json.dumps(dict(responseSha256=digest)))

    def test_projection_binds_legacy_receipts_without_new_calls_or_source_mutation(self):
        out = self.root/'derived'
        result = projection.project(self.source, self.receipts, out)
        self.assertEqual(result['matchedCalls'], 1)
        self.assertEqual(result['convertedObservationEvents'], 2)
        self.assertEqual(result['newModelCalls'], 0)
        self.assertEqual(result['modelCallReport']['creditUsage']['estimatedCreditsKnownSubtotal'], 0.01525)
        self.assertEqual((self.source/'events.jsonl').read_bytes(), self.original)
        self.assertNotIn(self.response['content'], (out/'events.jsonl').read_text())
        self.assertNotIn(self.response['content'], (out/'projection.json').read_text())
        self.assertEqual((out/'events.jsonl').stat().st_mode & 0o777, 0o600)
        reference = next(row['executionIdentity']['loadedProjectCodeManifestSha256']
                         for row in (json.loads(line) for line in self.original.splitlines())
                         if row['event'] == 'workflow_started')
        self.assertEqual(accounting_impl.load_execution_identity_sidecar(out, reference), self.modules)
        self.assertEqual((out/'.execution-identities').stat().st_mode & 0o777, 0o700)
        self.assertEqual((out/'.execution-identities'/(reference+'.json')).stat().st_mode & 0o777, 0o600)

    def test_direct_and_module_cli_write_identical_bound_projection(self):
        root = Path(__file__).resolve().parents[1]
        results = []
        for index, command in enumerate((
            [sys.executable, '-m', 'tools.ops.project_codex_credit_usage'],
            [sys.executable, 'tools/ops/project_codex_credit_usage.py'],
        )):
            output = self.root / f'derived-{index}'
            completed = subprocess.run(command + [
                '--accounting-dir', str(self.source),
                '--cli-receipts-dir', str(self.receipts),
                '--out-dir', str(output),
            ], cwd=root, check=True, capture_output=True, text=True)
            results.append((completed.stdout, (output/'events.jsonl').read_bytes(),
                            (output/'projection.json').read_bytes()))
            manifest = json.loads((output/'projection.json').read_text())
            self.assertEqual(manifest['sourceLedgerSha256'], hashlib.sha256(self.original).hexdigest())
            self.assertEqual(manifest['derivedLedgerSha256'], hashlib.sha256((output/'events.jsonl').read_bytes()).hexdigest())
            self.assertTrue(manifest['originalLedgerUnchanged'])
        self.assertEqual(results[0], results[1])
        self.assertEqual((self.source/'events.jsonl').read_bytes(), self.original)

    def test_refuses_overwrite_and_identity_or_usage_mismatch(self):
        for field, value in (('requestedModel','gpt-6-sol'), ('usage',dict(input_tokens=999,cached_input_tokens=50,output_tokens=20))):
            original=dict(self.response); self.response[field]=value;self.save()
            with self.assertRaisesRegex(ValueError, 'mismatch'):
                projection.project(self.source,self.receipts,self.root/'bad')
            self.assertFalse((self.root/'bad').exists())
            self.response=original;self.save()
        with self.assertRaisesRegex(ValueError, 'separate_output'):
            projection.project(self.source,self.receipts,self.source)

    def test_tampered_outcome_fails_before_creating_output(self):
        (self.path.parent/'resource-outcome.json').write_text('{"responseSha256":"wrong"}')
        with self.assertRaisesRegex(ValueError, 'outcome_mismatch'):
            projection.project(self.source,self.receipts,self.root/'bad')
        self.assertFalse((self.root/'bad').exists())

    def test_rejects_invalid_private_sidecar_before_creating_output(self):
        sidecar = next((self.source/'.execution-identities').glob('*.json'))
        sidecar.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'damaged_source_ledger'):
            projection.project(self.source, self.receipts, self.root/'bad')
        self.assertFalse((self.root/'bad').exists())

    def test_resource_call_identity_comes_from_binding_not_payload_folder(self):
        call_id=self.path.parent.name.partition('-')[2]
        folder=self.path.parent.with_name('translator-payload-hash');self.path.parent.rename(folder)
        self.path=folder/'response.json'
        binding=dict(operationId='codex-layer2:'+call_id, owner={'callId':call_id})
        (folder/'resource-binding.json').write_text(json.dumps(binding))
        outcome=json.loads((folder/'resource-outcome.json').read_text())
        outcome.update(binding,status='terminal')
        (folder/'resource-outcome.json').write_text(json.dumps(outcome))
        result=projection.project(self.source,self.receipts,self.root/'derived')
        self.assertEqual(result['matchedCalls'],1)


if __name__ == '__main__':
    unittest.main()
