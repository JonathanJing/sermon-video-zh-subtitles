"""Integration over real durable mock subprocesses; never model/network calls."""
from copy import deepcopy
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import sermon_pilot_evidence as evidence
from scripts import sermon_prefect_dag as pilot
from scripts import sermon_dag_contract as contract
from scripts import sermon_log_profile as profile
from scripts.sermon_execution_harness import work_lock


class PilotEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)/'run'

    def execute(self, **kwargs):
        plan = contract.make_plan(run_id='1'*64, input_identity_sha256='2'*64, locales=('ko',), text_only=('ko',), **kwargs)
        with work_lock(self.root):
            pilot.initialize(self.root, plan)
            with profile.session(self.root/'accounting', 'pilot_evidence_test', work_kind='control', evidence_mode='synthetic'):
                runner, results = pilot.Runner(self.root, plan), {}
                for node in plan['nodes']:
                    results[node['id']] = runner.execute(node, [results[key] for key in node['dependsOn']])
        return plan, results

    def inspect_unchanged(self, **kwargs):
        before = {str(p): p.read_bytes() for p in Path(self.tmp.name).rglob('*') if p.is_file()}
        with patch.object(pilot.jobs, 'inspect_job', side_effect=AssertionError('mutating read')), \
             patch.object(pilot.jobs, 'start_job', side_effect=AssertionError('dispatch forbidden')):
            result = evidence.inspect(self.root, **kwargs)
        self.assertEqual(before, {str(p): p.read_bytes() for p in Path(self.tmp.name).rglob('*') if p.is_file()})
        return result

    def test_complete_original_receipts_and_simulated_gates_read_only(self):
        self.execute()
        result = self.inspect_unchanged(diagnose_offline=True)
        p = result['progress']
        self.assertEqual(p['plannedProcessedPercent'], 100)
        self.assertEqual(p['gateCompletionPercent'], 100)
        self.assertTrue(p['complete'])
        self.assertEqual(p['counts']['realHumanApproved'], 0)
        self.assertGreater(p['counts']['simulatedHumanApproved'], 0)
        self.assertFalse(result['productionEligible'])
        self.assertEqual(result['diagnostics'], {})
        self.assertEqual(p['cost']['knownSubtotalUsd'], None)
        self.assertTrue(all(r['measurementValidated'] for r in result['statusReceipts']))
        self.assertEqual(result['executionPlanSha256'], pilot.read(self.root/'plan.json')['planSha256'])

    def test_known_failure_counts_processing_not_gate_and_offline_diagnosis(self):
        self.execute(scenarios={'text.ko':'known_failure'})
        result = self.inspect_unchanged(diagnose_offline=True)
        self.assertEqual(result['progress']['plannedProcessedPercent'], 50)
        self.assertEqual(result['progress']['gateCompletionPercent'], 25)
        self.assertFalse(result['progress']['complete'])
        diagnostic = result['diagnostics']['text.ko']['result']
        self.assertEqual(diagnostic['status'], 'completed')
        self.assertFalse(diagnostic['provenance']['executionAuthorized'])
        self.assertIsNone(diagnostic['provenance']['costUsd'])
        self.assertEqual(result['diagnosticManifests']['text.ko']['events'][0]['usage'], None)

    def test_unknown_preserves_full_budget_no_reconciliation_claim(self):
        self.execute(scenarios={'text.ko':'outcome_unknown'})
        result = self.inspect_unchanged(diagnose_offline=True)
        self.assertIsNone(result['progress']['plannedProcessedPercent'])
        self.assertFalse(result['progress']['complete'])
        self.assertEqual(result['validatedNodeEvidence']['text.ko']['status'], 'outcome_unknown')
        self.assertEqual(result['progress']['reconciliationEvidence']['verifiedAttempts'], 0)
        self.assertTrue(all(not r['reconcilesAttemptIds'] for r in result['statusReceipts']))

    def test_snapshot_flags_cannot_grant_progress_or_clear_unknown(self):
        self.execute(scenarios={'text.ko':'outcome_unknown'})
        baseline = self.inspect_unchanged()
        (self.root/'snapshot.json').write_text(json.dumps({'complete':True,'evidenceValidated':True,
            'reconcilesAttemptIds':['mock-1'],'nodes':{}}))
        after = self.inspect_unchanged()
        self.assertEqual(baseline['validatedNodeEvidence'], after['validatedNodeEvidence'])
        self.assertIsNone(after['progress']['plannedProcessedPercent'])

    def test_corrupt_output_prevents_downstream_acceptance(self):
        self.execute()
        path = self.root/'nodes/text.ko/output.json'
        value = pilot.read(path); value['syntheticOutput'] = False
        path.write_text(json.dumps(value))
        result = self.inspect_unchanged()
        self.assertFalse(result['progress']['complete'])
        self.assertFalse(next(r for r in result['statusReceipts'] if r['unitId']=='text.ko')['evidenceValidated'])
        self.assertEqual(result['validatedNodeEvidence']['audio.ko']['status'], 'outcome_unknown')

    def test_abandoned_job_is_unknown_without_rewriting_it(self):
        self.execute()
        before = evidence.inspect(self.root)
        job = before['validatedNodeEvidence']['text.ko']['jobId']
        path = self.root/'jobs'/job/'state.json'
        value = pilot.read(path); value['status'] = 'running'
        path.write_text(json.dumps(value))
        result = self.inspect_unchanged()
        self.assertEqual(result['validatedNodeEvidence']['text.ko']['status'], 'outcome_unknown')
        self.assertEqual(pilot.read(path)['status'], 'running')

    def test_missing_real_human_approval_no_mock_grant(self):
        self.execute(simulated_human=False)
        result = self.inspect_unchanged(diagnose_offline=True)
        self.assertEqual(result['progress']['plannedProcessedPercent'], 0)
        self.assertEqual(result['progress']['counts']['realHumanApproved'], 0)
        self.assertEqual(result['progress']['counts']['simulatedHumanApproved'], 0)
        self.assertFalse(result['progress']['complete'])

    def test_active_writer_is_rejected_without_touching_files(self):
        self.execute()
        with work_lock(self.root), self.assertRaisesRegex(ValueError, 'writer_active'):
            evidence.inspect(self.root)

    def test_concurrent_evidence_change_refuses_report(self):
        self.execute()
        original = evidence.inventory
        count = 0
        def change(root):
            nonlocal count
            count += 1
            result = original(root)
            if count == 2:
                result['changed'] = 'f'*64
            return result
        with patch.object(evidence, 'inventory', side_effect=change), self.assertRaisesRegex(ValueError, 'changed_during'):
            evidence.inspect(self.root)

    def test_symlink_evidence_rejected(self):
        self.execute()
        path = self.root/'nodes/source/output.json'
        path.unlink(); path.symlink_to(self.root/'plan.json')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            evidence.inspect(self.root)


@unittest.skipUnless(os.environ.get('SERMON_TEST_PREFECT') == '1', 'optional real Prefect integration')
class PilotEngineEvidenceTests(unittest.TestCase):
    def test_engine_then_readonly_report_replay_and_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            for name, scenarios in [('complete', {}), ('failure', {'text.ko':'known_failure'})]:
                root = base/name
                plan = contract.make_plan(run_id=('3' if name=='complete' else '5')*64,
                    input_identity_sha256='4'*64, scenarios=scenarios, delay_seconds=.4)
                plan_path = base/(name+'.json');plan_path.write_text(json.dumps(plan))
                argv = [sys.executable, str(pilot.REPO/'scripts/run_sermon_prefect_dag.py'),
                        'mock', '--root', str(root), '--plan', str(plan_path)]
                first = subprocess.run(argv, capture_output=True, text=True, timeout=120)
                self.assertEqual(first.returncode, 0 if name=='complete' else 2, first.stderr[-4000:])
                original = evidence.inventory(root)
                report = evidence.inspect(root, diagnose_offline=True)
                self.assertEqual(original, evidence.inventory(root))
                self.assertEqual(report['progress']['plannedProcessedPercent'], 100 if name=='complete' else 80)
                self.assertEqual(report['progress']['gateCompletionPercent'], 100 if name=='complete' else 70)
                if name=='complete':
                    second = subprocess.run(argv, capture_output=True, text=True, timeout=120)
                    self.assertEqual(second.returncode, 0, second.stderr[-4000:])
                    replay = evidence.inspect(root)
                    self.assertEqual(report['validatedNodeEvidence'], replay['validatedNodeEvidence'])
                    self.assertEqual(report['progress']['counts'], replay['progress']['counts'])
                    for key, value in original.items():
                        if key.startswith(('nodes/', 'mock-budget/', 'jobs/')):
                            self.assertEqual(value, evidence.inventory(root)[key])
                else:
                    self.assertEqual(report['validatedNodeEvidence']['page.es']['status'], 'succeeded')
                    self.assertEqual(report['validatedNodeEvidence']['page.zh-Hans']['status'], 'succeeded')
                    self.assertFalse(report['diagnostics']['text.ko']['result']['provenance']['executionAuthorized'])


if __name__ == '__main__':
    unittest.main()
