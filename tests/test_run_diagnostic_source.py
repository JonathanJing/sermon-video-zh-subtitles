import json
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from unittest.mock import patch, MagicMock

from scripts.experiments import run_diagnostic_source as subject
from scripts.production_concurrency_profile import profile_v1
from scripts import sermon_workflow_jobs as jobs
from scripts import judge_english_source_for_translation as judge
from scripts import english_source_judge_cache as cache
from scripts.sermon_unified import resources


class DiagnosticSourceTests(unittest.TestCase):
    def setUp(self):
        self.session = MagicMock()
        self.session.environment = {'SPARK_EXCLUSIVE_SESSION_ID': 'fixture-session',
                                    'SPARK_EXCLUSIVE_SESSION_OWNER': 'fixture-owner'}
        self.session.start_job.return_value = {'jobId': 'fixture-job'}
        session_patch = patch.object(subject, '_spark_session', return_value=self.session)
        session_patch.start(); self.addCleanup(session_patch.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.root_patch = patch.object(subject, 'ROOT', self.root)
        self.root_patch.start(); self.addCleanup(self.root_patch.stop)
        self.out = self.root / 'artifacts/source-test'
        self.media = self.root / 'source.wav'
        with wave.open(str(self.media), 'wb') as handle:
            handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(16000)
            handle.writeframes(b'\0\0' * (16000 * 606))
        self.cli = self.root / 'fake-cli'
        self.cli.write_text('synthetic identity only; never executed')
        self.provenance = self.root / 'provenance.json'
        self.provenance.write_text(json.dumps({'diagnosticOnly': True, 'productionEligible': False,
            'humanApprovalCreated': False, 'parentMedia': {'path': str(self.media),
                'sha256': subject.source._sha(self.media), 'durationSeconds': 606},
            'actualCompleteSentenceWindow': {'startSeconds': 0, 'endSeconds': 605.5},
            'sourceUnitCount': 136, 'sourceSentenceCount': 114}))
        self.policy = {'schemaVersion': resources.POLICY_VERSION, 'brokerRoot': str(self.root / 'broker'),
            'capacities': {'cpu': 4, 'online_api': 4, 'codex_cli': 24, 'spark_tts': 1, 'publisher': 1}}
        self.mfa = {'backend': 'macbook', 'allowSparkFallback': False,
            'localOptions': {key: None for key in subject.source.LOCAL_MFA_FIELDS},
            'sparkOptions': {key: None for key in subject.source.SPARK_MFA_FIELDS}}

    def prepare(self):
        return subject.prepare(provenance_path=self.provenance, out_dir=self.out, profile=profile_v1(),
            resource_policy=self.policy, mfa=self.mfa, cli_path=self.cli)

    def align(self, references, clip, out, **kwargs):
        result = []
        for ref in references:
            count = 24 if ref['end'] - ref['start'] < 180 else 30
            for i in range(count):
                start = ref['start'] + i * 1.5
                words = [{'text': word, 'start': start + j * .2, 'end': start + j * .2 + .15}
                    for j, word in enumerate(('Jesus', 'is', 'worthy.'))]
                result.append({'id': len(result), 'referenceChunkId': ref['id'], 'text': 'Jesus is worthy.',
                    'start': start, 'end': words[-1]['end'], 'wordTimes': words,
                    'sentenceBoundarySource': 'frozen_reference_punctuation'})
        return result

    def cli_result(self, prompt, **options):
        request = json.loads(prompt.split('USER:\n', 1)[1].split('\nReturn only valid JSON.', 1)[0])
        rows = [{'sourceSentenceId': row['sourceSentenceId'],
            'sourceUnitIds': [u['sourceUnitId'] for u in row['units']], 'verdict': 'pass', 'risk': 'low',
            'checks': {name: 'pass' for name in judge.CHECKS}, 'evidence': 'Synthetic bound request.', 'unresolvedIssues': []}
            for row in request['sentences']]
        return {'id': 'codex:' + jobs._digest(request), 'completed': True, 'requestedModel': 'gpt-6.1-sol',
            'requestedReasoningEffort': 'high', 'requestedServiceTier': 'fast', 'toolCalls': 0,
            'content': json.dumps({'schemaVersion': judge.BATCH_SCHEMA, 'sentences': rows}),
            'usage': {'input_tokens': 100, 'output_tokens': 50, 'cached_input_tokens': 0}}

    def test_prepare_zero_model_calls_and_preserves_explicit_missing_hard_cli_cap(self):
        before = self.media.read_bytes()
        prepared = self.prepare()
        self.assertEqual(prepared['sourceChunkCount'], 4)
        self.assertFalse(prepared['productionEligible'])
        self.assertEqual(prepared['modelCalls'], 0)
        config = subject._configuration(prepared['configPath'])
        self.assertFalse(config['cliBudgetScope']['outputTokenCapEnforced'])
        self.assertFalse(config['cliBudgetScope']['invoiceCostCapEnforced'])
        self.assertEqual(config['apiAuthority']['globalBounds']['requests'], 4)
        self.assertEqual(config['apiAuthority']['globalBounds']['costMicrousd'], 49500)
        self.assertEqual(self.media.read_bytes(), before)
        self.assertFalse((self.root / 'broker').exists())

    def test_asr4_mfa_judge8_actual_dispatch_source_order_and_zero_call_resume(self):
        prepared = self.prepare()
        api_barrier, cli_barrier = threading.Barrier(4), threading.Barrier(8)
        counts = {'api': 0, 'cli': 0}
        lock = threading.Lock()
        def api(*args):
            with lock:
                counts['api'] += 1
            api_barrier.wait(timeout=10)
            return {'text': 'Jesus is worthy.'}
        def cli(prompt, **options):
            with lock:
                counts['cli'] += 1
            self.assertEqual((options['model'], options['reasoning'], options['service_tier']), ('gpt-6.1-sol', 'high', 'fast'))
            cli_barrier.wait(timeout=10)
            return self.cli_result(prompt, **options)
        options = dict(api_key='', api_transport=api, aligner=self.align,
                       mfa_preflight=lambda **k: {'fixture': True}, cli_call=cli)
        result = subject.execute(prepared['configPath'], **options)
        self.assertEqual(counts, {'api': 4, 'cli': 8})
        self.assertFalse(result['productionEligible'])
        self.assertTrue(result['requiresHumanSourceReview'])
        self.assertEqual(result['actualAnchorCounts'], {'sourceUnits': 114, 'sourceSentences': 114})
        self.assertEqual(result['baselineSampleCounts'], {'sourceUnits': 136, 'sourceSentences': 114})
        finals = [json.loads(p.read_text()) for p in sorted((self.out / 'chunks').glob('*.asr-final.json'))]
        self.assertEqual([f['chunkIndex'] for f in finals], list(range(4)))
        before = {p: p.read_bytes() for p in self.out.rglob('*') if p.is_file() and p.suffix != '.lock'
                  and 'accounting' not in p.parts}
        resumed = subject.execute(prepared['configPath'], **options)
        self.assertEqual(resumed, result)
        self.assertEqual(counts, {'api': 4, 'cli': 8})
        self.assertTrue(all(p.read_bytes() == raw for p, raw in before.items()))
        ledger = jobs._read(next((self.root / 'broker').rglob('resources.json')))
        self.assertEqual(len(ledger['reservations']), 12)
        self.assertTrue(all(row['status'] == 'released' for row in ledger['reservations'].values()))
        source = json.loads(Path(result['sourcePath']).read_text())
        self.assertFalse(source['translationEligible'])
        self.assertFalse(source['review']['humanApproval'])

    def test_unknown_cli_keeps_slot_and_outer_cache_blocks_reissue(self):
        prepared = self.prepare()
        value = subject._configuration(prepared['configPath'])
        calls = []
        def fail(*a, **k):
            calls.append(1)
            raise TimeoutError('synthetic unknown')
        caller = subject.DiagnosticJudgeCaller(value, cli_call=fail)
        payload = judge._payload([], manifest_hash='b' * 64, anchor_policy={}, model='gpt-6.1-sol', effort='high')
        options = dict(out=self.out / 'judge-test', stage='english-source-judge-000', payload=payload,
                       api_key='', requested_model='gpt-6.1-sol', caller=caller)
        with self.assertRaises(TimeoutError):
            cache.cached_call(**options)
        with self.assertRaisesRegex(ValueError, 'Unknown L1 request outcome'):
            cache.cached_call(**options)
        self.assertEqual(len(calls), 1)
        rows = jobs._read(next((self.root / 'broker').rglob('resources.json')))['reservations'].values()
        self.assertEqual(sum(r['status'] == 'held' for r in rows), 1)

    def test_frozen_anchor_judge_mode_reports_zero_asr_and_does_not_dispatch_mfa(self):
        prepared = self.prepare()
        subject.execute(prepared['configPath'], api_key='', api_transport=lambda *a: {'text': 'Jesus is worthy.'},
            aligner=self.align, mfa_preflight=lambda **k: {'fixture': True}, cli_call=self.cli_result)
        # The real frozen sample uses formatted JSON. Equivalent reserialization
        # must not alter the file hash bound by its anchor manifest.
        aligned_path, anchor_path, source_path = (self.out / name for name in ('aligned-segments.json', 'anchor.json', 'source.json'))
        aligned_path.write_text(json.dumps(json.loads(aligned_path.read_text()), indent=2))
        anchor = json.loads(anchor_path.read_text())
        anchor['input']['mfaSegmentsSha256'] = subject.source._sha(aligned_path)
        anchor_path.write_text(json.dumps(anchor, indent=2))
        package = json.loads(source_path.read_text())
        package['anchors']['artifact']['sha256'] = subject.source._sha(anchor_path)
        package['transcript']['artifact']['sha256'] = subject.source._sha(aligned_path)
        source_path.write_text(json.dumps(package, indent=2))
        provenance = json.loads(self.provenance.read_text())
        provenance['sourceUnitCount'] = 114
        self.provenance.write_text(json.dumps(provenance))
        out = self.root / 'artifacts/frozen-judge-test'
        frozen = subject.prepare(provenance_path=self.provenance, out_dir=out, profile=profile_v1(),
            resource_policy=self.policy, mfa=self.mfa, cli_path=self.cli, frozen_sample_dir=self.out)
        self.assertEqual(frozen['sourceASRCallsPlanned'], 0)
        self.assertIsNotNone(frozen['criticalFixtureIdentity']['frozenInputs'])
        calls = []
        def cli(prompt, **options):
            calls.append(1)
            return self.cli_result(prompt, **options)
        result = subject.execute(frozen['configPath'], cli_call=cli,
            api_transport=lambda *a: self.fail('No fresh source ASR'), aligner=lambda *a, **k: self.fail('No MFA'),
            mfa_preflight=lambda **k: self.fail('No MFA preflight'))
        self.assertEqual((result['sourceASRCalls'], result['mfaCalls']), (0, 0))
        self.assertEqual(len(calls), 8)
        self.assertFalse(result['productionEligible'])
        self.assertEqual((out / 'aligned-segments.json').read_bytes(), aligned_path.read_bytes())
        self.assertEqual((out / 'anchor.json').read_bytes(), anchor_path.read_bytes())
        self.assertEqual(result['actualAnchorCounts'], {'sourceUnits': 114, 'sourceSentences': 114})
        self.assertEqual(subject.execute(frozen['configPath'], cli_call=cli), result)
        self.assertEqual(len(calls), 8)

    def test_mfa_preflight_rejects_before_paid_source_calls(self):
        prepared = self.prepare()
        def fail(**kwargs):
            raise RuntimeError('synthetic no MFA')
        with self.assertRaisesRegex(RuntimeError, 'no MFA'):
            subject.execute(prepared['configPath'], api_transport=lambda *a: self.fail('Provider must not run'), mfa_preflight=fail)
        self.assertFalse((self.root / 'broker').exists())

    def test_session_rejection_precedes_asr_cli_and_mfa_dispatch(self):
        prepared = self.prepare()
        self.session.require_ready.side_effect = ValueError('spark_competition_not_released')
        api, cli, mfa = MagicMock(), MagicMock(), MagicMock()
        with self.assertRaisesRegex(ValueError, 'spark_competition_not_released'):
            subject.execute(prepared['configPath'], api_transport=api, cli_call=cli, aligner=mfa)
        api.assert_not_called(); cli.assert_not_called(); mfa.assert_not_called()
        self.session.start_job.assert_not_called()
        self.assertFalse((self.out / 'chunks').exists())

    def test_failed_source_preserves_host_hold(self):
        prepared = self.prepare()
        with self.assertRaisesRegex(RuntimeError, 'fixture preflight'):
            subject.execute(prepared['configPath'], mfa_preflight=MagicMock(side_effect=RuntimeError('fixture preflight')))
        self.session.start_job.assert_called_once()
        self.session.end_job.assert_not_called()
