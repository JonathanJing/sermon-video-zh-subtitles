"""Actual Source/Anchor builders over genuine fixture provider receipts, no API."""
from copy import deepcopy
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

from scripts import sermon_fresh_diagnostic_source as fresh
from scripts import sermon_fresh_diagnostic as entry
from scripts import sermon_review_contracts as c
from scripts import sermon_review_budget as budget
from scripts import sermon_diagnostic_provider as provider
from scripts import sermon_log_profile as profile
from scripts import sermon_strict_layer2 as immutable
from scripts import sermon_accounting as accounting
from scripts import sermon_bounded_business_callbacks as callbacks
from tests.diagnostic_dag_fixture import DiagnosticDAGFixture


class FreshPreloadTests(unittest.TestCase):
    def test_cold_profile_session_preserves_actual_frozen_identity_without_dispatch(self):
        # A separate interpreter is essential: other profile tests have already
        # imported workflow evidence and would hide this production-start bug.
        child = textwrap.dedent('''
            import json
            import sys
            from pathlib import Path
            from unittest.mock import patch
            repository = Path(sys.argv[1])
            directory = Path(sys.argv[2])
            sys.path.insert(0, str(repository))
            from scripts import sermon_fresh_diagnostic as entry
            from scripts import sermon_accounting as accounting
            from scripts import sermon_log_profile as profile
            assert 'scripts.sermon_workflow_evidence' not in sys.modules
            with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('network forbidden')) as network:
                frozen = entry.preload_execution_modules([
                    repository / 'scripts/language_review_plugins/diagnostic_structural.py'])
                assert 'scripts/sermon_workflow_evidence.py' in frozen['loadedProjectCodeSha256']
                with profile.session(directory, 'fresh-preload-regression',
                                     work_kind='engineering', evidence_mode='synthetic'):
                    assert accounting.execution_identity() == frozen, 'identity changed at session start'
                assert accounting.execution_identity() == frozen, 'identity changed at session finish'
                network.assert_not_called()
            events = [json.loads(line) for line in (directory / 'events.jsonl').read_text().splitlines()]
            assert any(row['event'] == 'workflow_evidence' for row in events)
            assert any(row['event'] == 'run_finished' and row['status'] == 'completed' for row in events)
            assert not any(row['event'].startswith(('api_attempt', 'sdk_call_')) for row in events)
            assert not any(directory.parent.rglob('provider-run/state.json'))
            print(json.dumps({'identityUnchanged': True, 'dispatchEvents': 0}))
        ''')
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith('SERMON_ACCOUNTING_')}
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-I', '-B', '-c', child,
                                     str(Path(entry.__file__).resolve().parents[1]),
                                     str(Path(directory) / 'logs')], env=environment,
                                    capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'identityUnchanged': True, 'dispatchEvents': 0})


class FreshSourceTests(unittest.TestCase):
    def setUp(self):
        entry.preload_execution_modules([Path(entry.__file__).resolve().parent/'language_review_plugins/diagnostic_structural.py'])
        f=DiagnosticDAGFixture();f.setUp();self.addCleanup(f.doCleanups);self.f=f
        self.prior=f.root
        segments=deepcopy(f.aligned)
        for segment in segments:
            segment['referenceChunkId']='fresh-diagnostic'
            words=segment['text'].split();step=(segment['end']-segment['start'])/len(words)
            segment['wordTimes']=[{'text':word,'start':segment['start']+step*i,'end':segment['start']+step*(i+1)}
                                  for i,word in enumerate(words)]
        f.write('aligned-segments.json',segments)
        source=deepcopy(f.source)
        source['transcript']['artifact'].update(sha256=fresh._sha(f.root/'aligned-segments.json'),jsonSha256=c.canonical_sha256(segments))
        f.write('simulated-review-inputs/source.json',source)
        self.root=f.root/'fresh-run';self.root.mkdir()
        self.plan=deepcopy(f.plan);self.plan['runDirectory']=str(self.root)
        self.plan['executionIdentity']=f.execution_identity
        self.plan['providerConfig']['codeSha256']=c.canonical_sha256(f.execution_identity)
        self.subject=provider.DiagnosticProvider(budget.BudgetStore(self.root/'budget',f.store.authority),self.plan['providerConfig'],executor=f.transport)
        actual=callbacks.BoundedBusinessCallbacks(self.subject,self.root,source_clip=f.original.clip,
            fixture_id=f.transport.fixture_id,offline=True)
        with profile.session(self.root/'source-logs','fresh-source-inputs',work_kind='engineering',evidence_mode='synthetic'):
            actual.transcribe(f.original.raw);actual.source_check()
        self.audio=self.root/'source.wav';self.audio.write_bytes(f.original.raw)
        self.recipe=dict(prior_plan_path=f.root/'run-plan.json',prior_source_path=f.root/'simulated-review-inputs/source.json',
            prior_aligned_path=f.root/'aligned-segments.json',prior_summary_path=source['evidence']['pipelineSummary']['path'],audio_path=self.audio)
        self.authorization={'humanReviewMode':'default_pass_for_isolated_test_only','productionEligible':False}
        self.network=self.enterContext(patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('network forbidden')))

    def prepare(self,**kwargs):
        with profile.session(self.root/'logs','fresh-source-fixture',work_kind='engineering',evidence_mode='synthetic'):
            return fresh.prepare_source(self.plan,self.subject,**self.recipe,authorization=self.authorization,**kwargs)

    def test_actual_builder_cache_binding_pending_review_and_immutable_replay(self):
        before=fresh._sha(self.f.root/'budget'/budget.STORE_ID/'provider-run/state.json')
        out=self.prepare()
        self.assertEqual(out['evidence']['alignmentMode'],'validated_prior_alignment_cache')
        self.assertFalse(out['source']['translationEligible']);self.assertFalse(out['source']['review']['humanApproval'])
        self.assertFalse(out['context']['productionEligible']);self.assertEqual(out['context']['humanAcceptance'],'pending')
        self.assertEqual(out['source']['anchors']['artifact']['jsonSha256'],c.canonical_sha256(out['anchor']))
        self.assertEqual(out['evidence'],self.prepare()['evidence'])
        self.assertEqual(before,fresh._sha(self.f.root/'budget'/budget.STORE_ID/'provider-run/state.json'))
        self.network.assert_not_called()

    def test_alignment_and_audio_hash_mismatch_fail_before_downstream(self):
        self.audio.write_bytes(b'wrong')
        with self.assertRaisesRegex(ValueError,'audio_changed'):self.prepare()
        self.audio.write_bytes(self.f.original.raw)
        self.recipe['prior_aligned_path'].write_text('[]')
        with self.assertRaisesRegex(ValueError,'artifact_changed'):self.prepare()
        self.assertFalse((self.root/'source.json').exists())

    def test_changed_transcript_requires_actual_mfa_and_no_fabricated_alignment(self):
        original=fresh.returned_receipt
        def changed(root,config,operation,model):
            response,ref=original(root,config,operation,model)
            if Path(root)==self.root and operation=='transcription.initial':
                response=deepcopy(response);response['response']['text']+=' Changed.'
            return response,ref
        with patch.object(fresh,'returned_receipt',side_effect=changed),self.assertRaisesRegex(ValueError,'alignment_required'):
            self.prepare()
        self.assertFalse((self.root/'source.json').exists())

    def test_no_live_constructor_without_explicit_execute_or_fixture_adoption(self):
        with self.assertRaisesRegex(ValueError,'explicit_execute'):
            entry.FreshDiagnosticSession(self.plan,key='fixture-not-a-key')
        self.network.assert_not_called()

    def test_unknown_source_outcome_or_changed_receipt_remains_blocked(self):
        path=self.root/'budget'/budget.STORE_ID/'provider-run/state.json';state=c.read_snapshot(path)[0]
        next(iter(state['requests'].values()))['state']='outcome_unknown';path.write_bytes(c.canonical_bytes(state))
        with self.assertRaisesRegex(ValueError,'provider_outcome_unknown'):self.prepare()
        self.assertFalse((self.root/'source.json').exists())

    def test_fixed_fresh_session_source_freeze_ordinary_policy_and_replay_no_new_source_calls(self):
        identity=self.plan['executionIdentity']
        with patch.object(accounting,'execution_identity',return_value=identity):
            session=entry.FreshDiagnosticSession(self.plan,offline_transport=self.f.transport)
            before=len(self.f.transport.observations)
            with profile.session(self.root/'entry-logs','fresh-entry-fixture',work_kind='engineering',evidence_mode='synthetic'):
                prepared=session.prepare_source(self.recipe,self.authorization)
                draft=self.root/'policy-draft.json';rubric=self.root/'rubric-draft.json'
                immutable.save_once(draft,self.f.policy);immutable.save_once(rubric,self.f.rubric)
                specs=entry.freeze_locale_inputs(session,{'zh-Hans':{'policy':str(draft),'rubric':str(rubric),
                    'pluginPath':self.f.locale_specs['zh-Hans']['pluginPath']}})
                frozen=c.read_snapshot(specs['zh-Hans']['policy'])[0]
                self.assertEqual(frozen['languageReview']['registerRules'],self.f.policy['languageReview']['registerRules'])
                self.assertEqual(frozen['terminology'],self.f.policy['terminology'])
                self.assertEqual(prepared['evidence'],session.inspect_source()['sourceEvidence'])
            self.assertEqual(len(self.f.transport.observations),before)
            self.assertTrue((self.root/'fresh-source-recipe.json').exists())
