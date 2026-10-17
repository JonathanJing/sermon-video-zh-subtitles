"""The Jaeger verification replay must carry a referenced private identity."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import sermon_accounting as accounting
from scripts import build_tracker_dag_projection as tracker
from scripts import sermon_log_profile as profile
from scripts import verify_sermon_observability as verification
from tongxing_production.observability import accounting as accounting_impl


class VerificationSidecarTests(unittest.TestCase):
    def test_tracker_locked_snapshot_keeps_private_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'source'
            identity = accounting.execution_identity()
            modules = {f'scripts/synthetic_{i:04d}.py': f'{i:064x}' for i in range(800)}
            identity['loadedProjectCodeSha256'] = modules
            with patch.object(accounting_impl, 'execution_identity', return_value=identity):
                with profile.session(source, 'synthetic', work_kind='control', evidence_mode='synthetic'):
                    pass
            original = (source / 'events.jsonl').read_bytes()
            events, damaged, report = tracker._snapshot(source)
            self.assertFalse(damaged)
            self.assertTrue(events)
            self.assertTrue(report['runs'])
            self.assertEqual((source / 'events.jsonl').read_bytes(), original)
            sidecar = next((source / '.execution-identities').glob('*.json'))
            sidecar.chmod(0o644)
            events, damaged, report = tracker._snapshot(source)
            self.assertEqual(len(damaged), 1)
            self.assertEqual(damaged[0]['reason'], 'invalid_or_incomplete_event')
            self.assertIn('damaged_events', report['diagnostics'])
            sidecar.chmod(0o600)
            sidecar.write_bytes(b' ' * (512 * 1024 + 1))
            events, damaged, report = tracker._snapshot(source)
            self.assertEqual(len(damaged), 1)
            self.assertIn('damaged_events', report['diagnostics'])

    def test_real_ledger_snapshot_keeps_private_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, runtime = root / 'source', root / 'runtime'
            identity = accounting.execution_identity()
            modules = {f'scripts/synthetic_{i:04d}.py': f'{i:064x}' for i in range(800)}
            identity['loadedProjectCodeSha256'] = modules
            with patch.object(accounting_impl, 'execution_identity', return_value=identity):
                with profile.session(source, 'synthetic', work_kind='control', evidence_mode='synthetic'):
                    pass
            original = (source / 'events.jsonl').read_bytes()
            reference = next(row['executionIdentity']['loadedProjectCodeManifestSha256']
                             for row in (json.loads(line) for line in original.splitlines())
                             if row['event'] == 'workflow_started')

            def inspect_replay(directory):
                events, damaged = accounting.read_events(directory)
                self.assertFalse(damaged)
                self.assertTrue(events)
                self.assertEqual(accounting_impl.load_execution_identity_sidecar(directory, reference), modules)
                self.assertEqual((directory / 'events.jsonl').read_bytes(), original)
                sidecar = directory / '.execution-identities' / (reference + '.json')
                self.assertEqual(sidecar.stat().st_mode & 0o777, 0o600)
                return {'resourceSpans': []}, {'status': 'exported'}

            with patch.object(verification.observer, 'export', side_effect=inspect_replay) as export:
                receipt, _ = verification.run(runtime, source, expected_span_count=1)
            export.assert_called_once()
            self.assertEqual(receipt['implementationSha256']['scripts/sermon_identity_sidecars.py'],
                             verification.observer.sha(Path(verification.sidecars.__file__)))
            self.assertEqual(receipt['status'], 'failed')  # Deliberate stop before Jaeger work.
            self.assertEqual(receipt['failureCode'], 'unexpected_real_span_count')
            self.assertEqual((source / 'events.jsonl').read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
