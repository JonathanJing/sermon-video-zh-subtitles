"""Exercise public file interfaces and isolated bundles with synthetic data."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from experiments.local_experiment_log import deploy_tools

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / 'experiments/local_experiment_log'


class FileInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()

    def run_tool(self, script, *args):
        env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}
        env.pop('PYTHONPATH', None)
        return subprocess.run([sys.executable, str(script), *map(str, args)],
                              cwd=self.base, env=env, capture_output=True, text=True, timeout=30)

    def bridge(self, package=PACKAGE):
        output = self.base/'canonical.jsonl'
        result = self.run_tool(package/'canonical_bridge.py',
            '--measurements', package/'example/events.synthetic.jsonl',
            '--contexts', package/'example/contexts.synthetic.json', '--out', output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['replay_status'], 'consistent')
        return output

    def test_public_cli_round_trip_from_outside_repository(self):
        canonical = self.bridge()
        output = self.base/'audit.json'
        result = self.run_tool(PACKAGE/'audit_logs.py', '--manifest', PACKAGE/'example/manifest.json',
            '--logs', PACKAGE/'example/events.synthetic.jsonl', '--canonical', canonical, '--out', output)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(output.read_text())
        self.assertTrue(report['canonical_contract_verified'])
        self.assertEqual(report['evidence_kind'], 'synthetic')
        self.assertFalse(report['hardware_execution_independently_verified'])

    def test_conflicting_sidecar_cannot_publish_summary(self):
        canonical = self.bridge()
        events = [json.loads(line) for line in (PACKAGE/'example/events.synthetic.jsonl').read_text().splitlines()]
        events[0]['host_id'] = 'tampered-host'
        sidecar = self.base/'tampered.jsonl'
        sidecar.write_text(''.join(json.dumps(e)+'\n' for e in events))
        output = self.base/'audit.json'
        result = self.run_tool(PACKAGE/'audit_logs.py', '--manifest', PACKAGE/'example/manifest.json',
            '--logs', sidecar, '--canonical', canonical, '--out', output)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(output.exists())

    def test_real_measurements_require_canonical_facts(self):
        manifest = json.loads((PACKAGE/'example/manifest.json').read_text())
        manifest['evidence_kind'] = 'real'
        path = self.base/'manifest.json'; path.write_text(json.dumps(manifest))
        output = self.base/'audit.json'
        result = self.run_tool(PACKAGE/'audit_logs.py', '--manifest', path,
            '--logs', PACKAGE/'example/events.synthetic.jsonl', '--out', output)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(output.exists())

    def test_bridge_preserves_existing_output(self):
        output = self.base/'existing.jsonl'; output.write_text('keep-me')
        result = self.run_tool(PACKAGE/'canonical_bridge.py',
            '--measurements', PACKAGE/'example/events.synthetic.jsonl',
            '--contexts', PACKAGE/'example/contexts.synthetic.json', '--out', output)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(output.read_text(), 'keep-me')

    def test_template_export_is_new_and_explicitly_synthetic(self):
        output = self.base/'export'
        result = self.run_tool(PACKAGE/'export_contract.py', '--out-dir', output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads((output/'event.schema.json').read_text()),
                         json.loads((PACKAGE/'event.schema.json').read_text()))
        self.assertEqual(json.loads((output/'example/manifest.json').read_text())['required_layers'], ['L3'])
        second = self.run_tool(PACKAGE/'export_contract.py', '--out-dir', output)
        self.assertNotEqual(second.returncode, 0)

    def test_packaged_bridge_uses_bundled_shared_validator(self):
        bundle = self.base/'tools.tgz'
        deploy_tools.build(ROOT, bundle, 'a'*40)
        receipt = deploy_tools.install(bundle, self.base/'tools')
        release = self.base/'tools'/receipt['current_target']
        self.assertTrue((release/'scripts/sermon_log_contract.py').is_file())
        self.assertFalse((release/'canonical-reference').exists())
        self.bridge(release/'experiments/local_experiment_log')
