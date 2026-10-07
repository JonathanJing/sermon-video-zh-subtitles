"""Ordinary Fresh Source stage boundaries using original offline provider fixtures."""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import sermon_accounting as accounting
from scripts import sermon_fresh_diagnostic as fresh
from scripts import sermon_fresh_source_stages as stages
from scripts import sermon_log_profile as profile
from scripts import sermon_public_snapshot as public
from scripts import sermon_review_contracts as c
from tests import test_sermon_fresh_source_causality as fixtures


class FreshSourceStagesTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.FreshCausalityTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.enterContext(patch.object(accounting, 'execution_identity', return_value=self.f.plan['executionIdentity']))
        self.session = fresh.FreshDiagnosticSession(self.f.plan, offline_transport=self.f.f.f.transport)
        self.stages = stages.FreshSourceStages(self.session, self.f.recipe, self.f.f.authorization)

    def context(self):
        return profile.session(self.f.root/'stage-logs', 'fresh-source-stages-fixture', work_kind='engineering',
            evidence_mode='synthetic', production_run_id=self.session.subject.config['runId'])

    def test_independent_alignment_and_package_then_readonly_stage_repeat(self):
        before = len(self.f.f.f.transport.observations)
        results = []
        with self.context():
            self.stages.freeze()
            for name in stages.ORDER:
                result = self.stages.execute(name, results[-1] if results else None)
                results.append(result)
                if name != 'sourcePackage':
                    self.assertFalse((self.f.root/'source.json').exists())
                    self.assertIsNone(self.session.context)
                if name == 'alignment':
                    self.assertTrue((self.f.root/'aligned-segments.json').exists())
                    self.assertTrue((self.f.root/'fresh-source-stages/alignment.json').exists())
            self.assertEqual(len(self.f.f.f.transport.observations)-before, 2)
            files = {p: p.read_bytes() for p in self.stages.root.glob('*.json')}
            prior = None
            for name, expected in zip(stages.ORDER, results):
                prior = self.stages.execute(name, prior)
                self.assertEqual(prior, expected)
            self.assertEqual(files, {p: p.read_bytes() for p in files})
            self.assertEqual(len(self.f.f.f.transport.observations)-before, 2)
            self.assertEqual(self.session.inspect_source()['newASRCalls'], 0)
            self.assertFalse(self.session.context['productionEligible'])
            self.assertEqual(self.session.binding['sourceEvidence']['alignmentMode'], 'validated_prior_alignment_cache')
        causal = public.read_snapshot(self.f.root/'fresh-source-causality.json')[0]
        self.assertEqual(causal, results[-1]['causality'])
        self.assertEqual([causal['handles'][name]['stage'] for name in stages.ORDER],
            ['diagnostic.source_preflight', 'diagnostic.transcription', 'diagnostic.source_model',
             'diagnostic.alignment', 'diagnostic.source_package'])

    def test_missing_or_unmatched_predecessor_blocks_before_provider(self):
        before = len(self.f.f.f.transport.observations)
        with self.context():
            self.stages.freeze()
            with self.assertRaises((c.ContractError, FileNotFoundError)):
                self.stages.execute('sourceCheck')
            intake = self.stages.execute('intake')
            with self.assertRaisesRegex(c.ContractError, 'upstream_result_changed'):
                self.stages.execute('transcription', None)
            self.assertEqual(len(self.f.f.f.transport.observations), before)
            self.assertFalse(self.stages._path('transcription').exists())
            self.assertEqual(self.stages.execute('intake'), intake)

    def test_preflight_rejection_makes_no_provider_requests(self):
        path = Path(self.f.recipe['prior_source_path'])
        value = public.read_snapshot(path)[0]
        value['source']['serviceDate'] = 'invalid-date'
        path.write_bytes(c.canonical_bytes(value))
        selected = stages.FreshSourceStages(self.session, self.f.recipe, self.f.f.authorization)
        before = len(self.f.f.f.transport.observations)
        with self.context():
            selected.freeze()
            with self.assertRaisesRegex(c.ContractError, 'consumer_incompatible'):
                selected.execute('intake')
        self.assertEqual(len(self.f.f.f.transport.observations), before)
        self.assertFalse((self.f.root/'source.json').exists())
        self.assertFalse(selected._path('intake').exists())


if __name__ == '__main__':
    unittest.main()
