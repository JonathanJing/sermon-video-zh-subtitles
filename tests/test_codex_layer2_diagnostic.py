import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import codex_layer2_diagnostic as subject
from scripts import run_codex_layer2_test as command
from scripts import build_english_source_package as english
from scripts import sermon_diagnostic_context as diagnostic
from scripts import target_language_policy as policies
from scripts import run_target_language_models as runner
from scripts.codex_layer2_transport import CodexLayer2Transport, TEST_CONFIGURATION
from tests import test_run_target_language_models as fixtures


class DiagnosticChainTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.RunTargetLanguageModelsTests()
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.data = self.f.fixture
        (subject.ROOT / 'artifacts').mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=subject.ROOT / 'artifacts', prefix='test-cli-diagnostic-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.fixture = self.root / 'fixture'
        self.out = self.root / 'run'
        self.source = copy.deepcopy(self.data.source)
        self.anchor = copy.deepcopy(self.data.anchor)
        self.policy = copy.deepcopy(self.data.policy)
        self.source.update(status='blocked', translationEligible=False, candidateTranslationEligible=False)
        self.source['review'].update(humanApproval=False, reviewedBy=None, reviewedAt=None,
            reviewedSourceUnitIds=[], evidence=None, checks={k: 'pending' for k in diagnostic.PENDING_CHECKS})
        self.source['source']['approvedWindow'].update(status='pending', humanApproval=False, evidence=None)
        self.source['transcript']['completenessReview'] = 'pending'
        self.source['evidence']['machineJudge'] = None
        self.source['issues'] = [{'stage': 'source', 'type': 'approved_sermon_window_missing'}] + [
            {'stage': 'review', 'type': name + '_review_pending'} for name in diagnostic.PENDING_CHECKS]
        self.rebind()
        self.plan = [{'translationGroupId': 'g1', 'sourceUnitIds': [self.anchor['sourceUnits'][0]['sourceUnitId']]},
                     {'translationGroupId': 'g2', 'sourceUnitIds': [self.anchor['sourceUnits'][1]['sourceUnitId']]}]
        self.calls = []

    def rebind(self):
        self.source['anchors']['artifact']['jsonSha256'] = policies.canonical_sha256(self.anchor)
        identity = english.source_identity(self.source['source'], self.source['transcript']['artifact'],
            self.source['anchors']['artifact'], self.source['review'], None, self.source['implementation'])
        self.source.update(downstreamInvalidationKey=identity, packageId='english-source-' + identity[:24])
        self.policy['sourceScope']['englishSourcePackageJsonSha256'] = policies.canonical_sha256(self.source)
        self.policy['sourceScope']['anchorManifestSha256'] = policies.canonical_sha256(self.anchor)
        self.policy['componentSha256']['sourceScope'] = policies.canonical_sha256(self.policy['sourceScope'])

    def freeze(self, *, sol=True, **kwargs):
        return subject.freeze_fixture(self.source, self.anchor, self.policy, self.plan, self.data.plugin_path,
            self.fixture, authorization_ref='user-authorized isolated test', code_commit='a' * 40,
            translator_model='gpt-6.1-sol' if sol else None, **kwargs)

    def transport(self):
        transport = CodexLayer2Transport.__new__(CodexLayer2Transport)
        transport.cli_path = self.root / 'unused-codex'
        transport.timeout_seconds = 10
        transport.receipts_dir = self.out / '_cli_calls'
        transport.env = {'PATH': '/fixture'}
        transport.resource_policy = None
        transport.models = {role: TEST_CONFIGURATION[role]['model'] for role in ('translator', 'reviewer')}
        transport.tiers = {'translator': 'fast', 'reviewer': 'fast'}
        transport.simulation_model_configuration = copy.deepcopy(TEST_CONFIGURATION)
        transport.execution_identity = {'backend': 'codex_cli', 'fixture': True,
                                       'simulationModelConfiguration': copy.deepcopy(TEST_CONFIGURATION)}
        return transport

    def process(self, argv, **kwargs):
        task = json.loads(kwargs['input'].split('\nINPUT:\n')[1])
        model = argv[argv.index('-m') + 1]
        self.calls.append((model, copy.deepcopy(task)))
        group = next(row for row in self.data.evidence['groups'] if row['sourceUnitIds'] == task['sourceUnitIds'])
        result = {key: copy.deepcopy(group[key]) for key in ('translationGroupId', 'sourceUnitIds', 'targetUtterances', 'coverage')}
        result['translationGroupId'] = task['translationGroupId']
        if 'model_reasoning_effort="medium"' in argv:
            result['semanticReview'] = copy.deepcopy(group['semanticReview'])
            self.assertEqual(task['astraDraft']['targetUtterances'], result['targetUtterances'])
        content = json.dumps(result)
        Path(argv[argv.index('-o') + 1]).write_text(content)
        rows = [{'type': 'thread.started', 'thread_id': 'fixture-' + str(len(self.calls))},
                {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': content}},
                {'type': 'turn.completed', 'usage': {'input_tokens': 100, 'cached_input_tokens': 10, 'output_tokens': 20}}]
        return subprocess.CompletedProcess(argv, 0, stdout='\n'.join(json.dumps(row) for row in rows), stderr='')

    def invoke(self, *, transport=None, process=None, resource_policy_path=None):
        real_run = subprocess.run
        cli_process = process or self.process
        def dispatch(argv, **kwargs):
            if Path(argv[0]).name == 'unused-codex':
                return cli_process(argv, **kwargs)
            return real_run(argv, **kwargs)
        with patch.object(command, 'CodexLayer2Transport', return_value=transport or self.transport()), \
             patch('scripts.codex_layer2_transport.subprocess.run', side_effect=dispatch), \
             patch.object(runner.sermon_pipeline, 'chat_json', side_effect=AssertionError('API forbidden')), patch('builtins.print'):
            return command.run_test(self.fixture, None, self.out, cli_path=self.root / 'unused', diagnostic_fixture=True, resource_policy_path=resource_policy_path, session_verifier=lambda: {"status":"offline_test"})

    def test_fake_cli_plugin_candidate_share_rules_and_same_run_resume_without_calls(self):
        self.freeze()
        with patch.object(runner.producer, 'run_language_plugin', wraps=runner.producer.run_language_plugin) as plugin, \
             patch.object(runner.producer, 'admit_evidence', wraps=runner.producer.admit_evidence) as admission:
            report = self.invoke()
        self.assertEqual(plugin.call_count, 2)  # Independent plugin execution plus admission readback.
        self.assertEqual(admission.call_count, 1)
        self.assertEqual(len(self.calls), 4)
        self.assertEqual(report['canonicalCandidateAdmission'], 'executed_diagnostic_only')
        self.assertFalse(report['productionEligible'] or report['humanApproval'])
        receipt = json.loads((self.out / 'rule-preflight.json').read_text())
        for call in [*plugin.call_args_list, *admission.call_args_list]:
            self.assertEqual(call.kwargs['rule_preflight_receipt'], receipt)
            self.assertFalse(call.kwargs['diagnostic_context']['productionEligible'])
        for _, task in self.calls:
            self.assertEqual(task['modelRules']['ruleBundleSha256'], receipt['ruleBundleSha256'])
        envelope = json.loads((self.out / 'diagnostic-candidate.json').read_text())
        self.assertFalse(envelope['actualHumanApproval'] or envelope['productionEligible'] or envelope['releaseEligible'])
        self.assertEqual(envelope['candidate']['humanReview']['translation'], 'pending')
        self.assertEqual(envelope['rulePreflightSha256'], report['rulePreflightSha256'])
        self.assertEqual(self.invoke(process=lambda *_a, **_kw: self.fail('resume repaid')), report)
        self.assertEqual(len(self.calls), 4)

    def test_raw_recovery_resumes_without_repaying_completed_cli_turn(self):
        self.freeze()
        original = runner.save_new
        def interrupt(path, value, **kwargs):
            if path.name == 'group-0001-sol.json':
                raise OSError('fixture interruption after returned raw')
            return original(path, value, **kwargs)
        with patch.object(runner, 'save_new', side_effect=interrupt):
            with self.assertRaisesRegex(OSError, 'fixture interruption'):
                self.invoke()
        self.assertEqual(len(self.calls), 2)
        self.assertTrue((self.out / 'group-0001-sol.raw.json').exists())
        self.invoke()
        self.assertEqual(len(self.calls), 4)

    def test_unknown_cli_outcome_blocks_resume_without_retry(self):
        self.freeze()
        with self.assertRaises(subprocess.TimeoutExpired):
            self.invoke(process=lambda *_a, **_kw: (_ for _ in ()).throw(subprocess.TimeoutExpired('unused', 10)))
        with self.assertRaisesRegex(ValueError, 'Uncertain|Unreconciled'):
            self.invoke(process=lambda *_a, **_kw: self.fail('unknown outcome retried'))
        self.assertFalse((self.out / 'diagnostic-candidate.json').exists())

    def test_actual_plugin_failure_prevents_candidate_and_does_not_retranslate(self):
        self.freeze()
        self.data.evidence['groups'][0]['targetUtterances'] = ['禁。']
        self.data.evidence['groups'][0]['coverage'][0]['targetText'] = '禁。'
        with self.assertRaisesRegex(ValueError, 'Language plugin rejected'):
            self.invoke()
        self.assertEqual(len(self.calls), 4)
        self.assertFalse((self.out / 'diagnostic-candidate.json').exists())
        with self.assertRaisesRegex(ValueError, 'Language plugin rejected'):
            self.invoke(process=lambda *_a, **_kw: self.fail('plugin failure retranslates'))

    def test_frozen_input_tampering_is_rejected_before_constructing_cli(self):
        self.freeze()
        path = self.fixture / 'anchor.json'
        value = json.loads(path.read_text()); value['sourceUnits'][0]['english'] += ' Added.'
        path.write_text(json.dumps(value))
        with patch.object(command, 'CodexLayer2Transport') as transport:
            with self.assertRaisesRegex(ValueError, 'fixture file changed'):
                command.run_test(self.fixture, None, self.out, cli_path=self.root / 'unused', diagnostic_fixture=True)
            transport.assert_not_called()
        self.assertFalse(self.out.exists())

    def test_diagnostic_source_and_sol_configuration_cannot_enter_formal_entry(self):
        self.freeze()
        source, anchor, policy, *_ = subject.load_fixture(self.fixture)
        with self.assertRaises(ValueError):
            policies.validate_policy(policy)
        with self.assertRaisesRegex(ValueError, 'Approved English Source'):
            runner.producer.prepare_request(source, anchor, policy)
        with self.assertRaisesRegex(ValueError, 'Diagnostic group loop'):
            inputs = subject.load_fixture(self.fixture)
            runner._run_prepared_groups(inputs[5], anchor, policy, self.out, '', self.transport(),
                self.plan, self.data.plugin_path, diagnostic_context=inputs[7])
        self.assertFalse(self.out.exists())

    def test_context_authorization_change_is_rejected_before_cli_construction(self):
        self.freeze()
        path = self.fixture / 'diagnostic-context.json'
        value = json.loads(path.read_text()); value['simulationAuthorizationRef'] = 'f' * 64
        path.write_text(json.dumps(value))
        with patch.object(command, 'CodexLayer2Transport') as transport:
            with self.assertRaisesRegex(ValueError, 'context binding changed'):
                command.run_test(self.fixture, None, self.out, cli_path=self.root / 'unused', diagnostic_fixture=True)
            transport.assert_not_called()

    def test_cli_backend_flag_reaches_api_transport_and_never_constructs_codex(self):
        self.freeze()
        argv = ['run_codex_layer2_test', '--fixture-dir', str(self.fixture), '--out-dir', str(self.out),
                '--diagnostic-fixture', '--backend', 'openai_api']
        with patch('sys.argv', argv), patch.object(command, 'CodexLayer2Transport') as transport, \
             patch('scripts.outcome_marker.run_with_outcome', side_effect=lambda _path, _name, fn: fn()), \
             patch.object(command.spark_admission, 'require_session'):
            with self.assertRaisesRegex(ValueError, 'openai_diagnostic_shared_resource_policy_required'):
                command.main()
            transport.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'openai_api_backend_requires_diagnostic_fixture'):
            command.run_test(self.fixture, None, self.out, cli_path=self.root / 'unused', backend='openai_api')

    def test_diagnostic_cannot_reuse_another_run_cache(self):
        self.freeze()
        inputs = subject.load_fixture(self.fixture)
        with self.assertRaisesRegex(ValueError, 'Diagnostic group loop'):
            runner._run_prepared_groups(inputs[5], inputs[1], inputs[2], self.out, '', self.transport(),
                self.plan, self.data.plugin_path, simulation_only=True, diagnostic_context=inputs[7],
                reuse_from=self.root / 'another-run')
        self.assertFalse(self.out.exists())

    def structural_policy(self):
        from scripts.language_review_plugins import diagnostic_structural as plugin
        self.data.plugin_path = Path(plugin.__file__)
        self.policy['languageReview'].update(pluginId=plugin.PLUGIN_ID, requiredChecks=plugin.REQUIRED,
            pluginImplementationSha256=runner.producer.plugin_implementation_sha256(self.data.plugin_path))
        self.policy['scripture'].update(editionId=None, quoteCheckPolicy='references_only')
        for key in ('languageReview', 'scripture'):
            self.policy['componentSha256'][key] = policies.canonical_sha256(self.policy[key])

    def test_unquoted_verse_intro_is_rejected_even_if_no_direct_quote_declared(self):
        self.structural_policy()
        self.anchor['sourceUnits'][0]['english'] = 'Verse 2 and 3, John says, Immediately I was in the Spirit.'
        self.rebind()
        with self.assertRaisesRegex(ValueError, 'does not support direct'):
            self.freeze(scripture_classification='no_direct_quotations')
        self.assertFalse(self.fixture.exists())

    def test_structural_unreviewed_scripture_scope_is_rejected_before_freeze(self):
        self.structural_policy()
        with self.assertRaisesRegex(ValueError, 'does not support direct or unreviewed'):
            self.freeze()
        self.assertFalse(self.fixture.exists())

    def test_structural_plugin_rejects_bound_direct_scripture_before_any_call(self):
        self.structural_policy()
        with self.assertRaisesRegex(ValueError, 'does not support direct'):
            self.freeze(scripture_classification='contains_direct_quotations',
                        source_quotation_units=[self.anchor['sourceUnits'][0]['sourceUnitId']])
        self.assertFalse(self.fixture.exists())
        self.freeze(scripture_classification='no_direct_quotations')
        report = self.invoke()
        self.assertEqual(report['qualityScope'], 'structural_only_no_direct_scripture_acceptance')
        self.assertEqual(len(self.calls), 4)


if __name__ == '__main__':
    unittest.main()
