"""The read-only drain check that code-moving batches attach (workflows/compute design §5)."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import api_cli_outcomes, check_run_start as subject
from scripts import tongxing_host  # noqa: F401  binds the layer backends the port test reads
from tongxing_production import ports
from tongxing_production.source import backend as source


def write(path, value=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value or {}), encoding='utf-8')


CODEX = {'schemaVersion': 'sermon-codex-call-v1', 'backend': 'codex_cli'}
LAYER2_MARKER = {'role': 'translator', 'payloadSha256': 'a' * 64}


class DrainCheckTests(unittest.TestCase):
    def test_settled_roots_pass_and_list_what_is_not_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write(root / 'lane/group-001.started.json', LAYER2_MARKER); write(root / 'lane/group-001.raw.json')
            write(root / 'run/api-cli-outcomes/abc/outcome.json', {'status': 'returned'})
            write(root / 'run/api-cli-outcomes/fail/outcome.json', {'status': 'terminal_failure'})
            write(root / 'calls/c1/identity.json', CODEX); write(root / 'calls/c1/started.json')
            write(root / 'calls/c1/outcome.json', {'status': 'completed'})
            # Never dispatched: no-capacity outcome and no started marker.
            write(root / 'calls/busy/identity.json', CODEX)
            write(root / 'calls/busy/outcome.json', {'status': 'not_dispatched_resource_busy'})
            # Not Codex calls and not Layer 2 markers: other evidence with the same names.
            write(root / 'spark/dispatch.started.json', {'phase': 'render'}); write(root / 'spark/dispatch.result.json')
            write(root / 'audio/render/identity.json', {'schemaVersion': 'sermon-l3-render-identity-v1'})
            report = subject.check_drain([root])
        self.assertEqual(report['status'], 'pass', report)
        self.assertEqual(report['unknownOutcomes'], [])
        self.assertTrue(report['notChecked'])

    def test_each_unknown_outcome_kind_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write(root / 'lane/group-002.started.json', LAYER2_MARKER)
            for name, status in (('def', 'unknown'), ('ghi', 'started'), ('jkl', 'received')):
                write(root / f'run/api-cli-outcomes/{name}/outcome.json', {'status': status})
            write(root / 'calls/c2/identity.json', CODEX); write(root / 'calls/c2/started.json')
            write(root / 'calls/c3/identity.json', CODEX); write(root / 'calls/c3/outcome.json', {'status': 'unknown_outcome'})
            # A later dispatch after a no-capacity outcome, killed before its outcome was written.
            write(root / 'calls/c4/identity.json', CODEX); write(root / 'calls/c4/started.json')
            write(root / 'calls/c4/outcome.json', {'status': 'not_dispatched_resource_busy'})
            before = sorted(str(p) for p in root.rglob('*'))
            report = subject.check_drain([root, root / 'missing'])
            self.assertEqual(before, sorted(str(p) for p in root.rglob('*')))  # read-only
        self.assertEqual(report['status'], 'fail')
        self.assertEqual(sorted(row['kind'] for row in report['unknownOutcomes']), [
            'api_cli_outcome_received', 'api_cli_outcome_started', 'api_cli_outcome_unknown',
            'codex_call_not_dispatched_resource_busy', 'codex_call_started_without_outcome',
            'codex_call_unknown_outcome', 'layer2_started_without_raw', 'missing_root'])


class OutcomesPortTests(unittest.TestCase):
    def test_outcomes_port_is_named_and_binds_late(self):
        port = source.current().provider.outcomes
        self.assertIsInstance(port, ports.Outcomes)
        with patch.object(api_cli_outcomes, 'request_identity', return_value='identity') as target:
            self.assertEqual(port.request_identity('caller', ('a',), {}, 'purpose'), 'identity')
            target.assert_called_once_with('caller', ('a',), {}, 'purpose')
        with patch.object(api_cli_outcomes, 'receipt_root', return_value=Path('/r')) as target:
            self.assertEqual(port.receipt_root(), Path('/r'))
            target.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
