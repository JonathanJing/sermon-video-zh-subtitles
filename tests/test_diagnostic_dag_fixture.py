"""Fixture qualification: real validators and ledgers, fixed synthetic transport."""
from copy import deepcopy
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from scripts import run_bounded_diagnostic_continuation as entry
from scripts import sermon_accounting as accounting
from scripts import sermon_diagnostic_dag_session as session_module
from scripts import sermon_diagnostic_source_evidence as source_evidence
from scripts import sermon_diagnostic_prefect_flow as flow
from scripts import sermon_review_contracts as c
from scripts import render_speculative_target_language_speech as preview
from tests.diagnostic_dag_fixture import DiagnosticDAGFixture
from tests.test_render_speculative_target_language_speech import FakeSynth


class DiagnosticDAGFixtureTests(unittest.TestCase):
    def setUp(self):
        self.f = DiagnosticDAGFixture(); self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def test_original_receipts_and_pending_findings_pass_real_validator(self):
        f = self.f
        self.assertEqual(len(f.transport.observations), 2)
        before = {p: p.read_bytes() for p in f.root.rglob('*.json')}
        result = source_evidence.validate_prior_source_evidence(f.root, f.state, f.context)
        self.assertEqual(result, f.source_evidence)
        self.assertEqual(before, {p: p.read_bytes() for p in f.root.rglob('*.json')})
        self.assertEqual(len(f.request['machineIssues']), 4)
        self.assertFalse(f.source['review']['humanApproval'])
        self.assertFalse(f.source['translationEligible'])
        self.assertTrue(all(row['reviewStatus']=='human_pending' for row in f.request['machineIssues']))
        self.assertTrue(all(row['state']=='returned' for row in f.state['requests'].values()))
        self.assertGreater(f.state['startedMonotonic'], 0.)
        self.assertLessEqual(f.state['startedMonotonic'], time.monotonic())
        self.assertEqual(f.state['clockDomain'], f.subject.domain())

    def test_real_continuation_locale_and_preview_inputs_without_new_source_calls(self):
        f = self.f
        # Only the clean-code identity guard is substituted while developing
        # uncommitted fixture files. Source/provider/gate validators stay real.
        with patch.object(accounting, 'execution_identity', return_value=f.execution_identity):
            session = session_module.DiagnosticSession(f.plan, f.continuation, offline_transport=f.transport, request_limits=f.request_limits)
            with f.session():
                session.inspect_source()
                result = session.run_locale('zh-Hans', f.locale_specs['zh-Hans'])
                self.assertEqual(result['status'], 'waiting_human', result)
                spec = deepcopy(f.preview_specs['zh-Hans'])
                paths = {k: Path(v) for k, v in spec['paths'].items()}
                paths['candidate'] = Path(result['output'])/'candidate.json'
                # Actual checkpoint hash/voice/policy/Source validators, inert
                # checkpoint bytes and explicit FakeSynth; no model loading.
                rendered = preview.render(paths, Path(spec['checkpoint_map_path']),
                    Path(spec['operation_policies_path']), Path(spec['out']),
                    strict_rubric=f.rubric, diagnostic_context=f.context,
                    deadline_monotonic=session.deadline, synth_factory=FakeSynth, device='cpu')
                self.assertEqual(rendered['status'], 'preview_only')
                self.assertEqual(len(FakeSynth.calls), f.expected_preview_calls)
                replay = session.run_locale('zh-Hans', f.locale_specs['zh-Hans'])
                self.assertEqual(replay['candidateSha256'], result['candidateSha256'])
        self.assertEqual(len(f.transport.observations), f.expected_prior_calls+f.expected_new_locale_calls)
        with f.subject._locked() as (_, state):
            self.assertEqual(state['startedMonotonic'], f.state['startedMonotonic'])
            self.assertEqual(state['clockDomain'], f.state['clockDomain'])
            self.assertEqual(sum(r['operationId']=='source.initial' for r in state['requests'].values()), 1)
            self.assertEqual(sum(r['operationId']=='transcription.initial' for r in state['requests'].values()), 1)

    def test_complete_flow_inventory_keeps_original_evidence_inside_fixture(self):
        f = self.f
        config = {'schemaVersion': flow.SCHEMA, 'locales': {locale: {
            'localeSpec': f.locale_specs[locale], 'previewSpec': f.preview_specs[locale]}
            for locale in f.locale_specs}}
        with patch.object(accounting, 'execution_identity', return_value=f.execution_identity):
            session = session_module.DiagnosticSession(f.plan, f.continuation, offline_transport=f.transport, request_limits=f.request_limits)
            dag = flow.DiagnosticDAG(session, config)
        self.assertTrue(dag.binding['inputFiles'])
        self.assertTrue(all(Path(path).is_relative_to(f.root) for path in dag.binding['inputFiles']))
        summary = f.source['evidence']['pipelineSummary']
        self.assertEqual(dag.binding['inputFiles'][summary['path']], summary['sha256'])
        self.assertEqual(len(f.transport.observations), f.expected_prior_calls)


if __name__ == '__main__':
    unittest.main()
