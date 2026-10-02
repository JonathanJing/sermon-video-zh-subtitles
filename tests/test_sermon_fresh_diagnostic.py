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
from scripts import sermon_public_snapshot as aggregate
from tests.diagnostic_dag_fixture import DiagnosticDAGFixture


class FreshTerminalFailureTests(unittest.TestCase):
    def test_private_messages_and_unapproved_contract_codes_are_not_persisted(self):
        from types import SimpleNamespace
        for error in (ValueError('/private/audio secret model text'),
                      c.ContractError('dev_unknown_/private/secret'),
                      c.ContractError('fresh_private_unapproved_code')):
            with self.subTest(errorType=type(error).__name__),tempfile.TemporaryDirectory() as directory:
                session=SimpleNamespace(root=Path(directory),plan={'fixture':True},
                    subject=SimpleNamespace(config={'runId':'a'*64}),context={'pending':True},
                    binding={'sourceEvidence':{'fixture':True}})
                with self.assertRaises(type(error)) as caught:
                    with entry._terminal_failure_receipt(session):raise error
                self.assertIs(caught.exception,error)
                files=list((session.root/'fresh-diagnostic-failures').glob('*.json'));self.assertEqual(len(files),1)
                receipt,raw=c.read_snapshot(files[0])
                self.assertEqual(receipt['reasonCode'],'unclassified_stage_failure')
                self.assertEqual(receipt['lastCompletedResultRef'],None)
                self.assertNotIn(b'secret',raw);self.assertNotIn(b'private',raw)

    def test_accounting_failure_is_reraised_without_business_failure_sidecar(self):
        from types import SimpleNamespace
        flagged=RuntimeError('receipt logging failed');flagged.sermon_logging_failed=True
        for error in (accounting.AccountingWriteError('structured_logging_write_failed'),flagged):
            with self.subTest(errorType=type(error).__name__),tempfile.TemporaryDirectory() as directory:
                session=SimpleNamespace(root=Path(directory))
                with self.assertRaises(type(error)) as caught:
                    with entry._terminal_failure_receipt(session):raise error
                self.assertIs(caught.exception,error)
                self.assertEqual(list(session.root.iterdir()),[])


class FreshHistoricalPlumbingTests(unittest.TestCase):
    def test_real_closed_parent_resolver_is_frozen_and_forwarded_with_drift_rejected(self):
        from types import SimpleNamespace
        from tests.test_sermon_historical_layer2 import HistoricalLayer2Tests
        from scripts import sermon_historical_layer2 as historical
        fixture=HistoricalLayer2Tests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        plan=fixture.build(failed=True);parent_before={path:path.read_bytes() for path in fixture.parent.rglob('*.json')}
        # Source and accounting validity have independent integration suites;
        # this unit isolates the immutable input handoff with a genuine closed
        # parent, linked successor, actual paid fixture receipts and fixed type.
        session=entry.FreshDiagnosticSession.__new__(entry.FreshDiagnosticSession)
        session.root=fixture.new;session.plan=plan
        session.subject=SimpleNamespace(config=plan['providerConfig'])
        session.context={'fixture':'pending'};session.binding={}
        session._historical_reuse={};session._historical_specification=None
        with patch.object(session,'_check'):
            session.configure_historical_locales({'zh-Hans':fixture.spec},['zh-Hans'])
        self.assertIs(type(session._historical_reuse['zh-Hans']),historical.HistoricalLayer2Reuse)
        session._check_historical_inputs()
        sidecar=session.root/'fresh-historical-layer2-inputs.json';frozen,raw=c.read_snapshot(sidecar)
        self.assertEqual(session.binding['historicalLayer2Inputs']['bytesSha256'],c.bytes_sha256(raw))
        self.assertEqual(frozen['runId'],plan['providerConfig']['runId'])
        with patch.object(entry.sessions.DiagnosticSession,'run_locale',return_value={'fixture':'forwarded'}) as call:
            result=session.run_locale('zh-Hans',{'fixture':'current'},depends_on=['parent-span'])
        self.assertEqual(result,{'fixture':'forwarded'})
        self.assertIs(call.call_args.kwargs['historical_reuse'],session._historical_reuse['zh-Hans'])
        self.assertEqual(call.call_args.kwargs['depends_on'],['parent-span'])
        self.assertFalse((session.root/'budget').exists());self.assertEqual(len(fixture.f.calls),2)
        session._historical_reuse['zh-Hans'].spec['parentPluginRef']['bytesSha256']='0'*64
        with self.assertRaisesRegex(c.ContractError,'fresh_historical_layer2_inputs_changed'):
            session._check_historical_inputs()
        session._historical_reuse['zh-Hans'].spec=deepcopy(fixture.spec)
        sidecar.write_bytes(raw+b' ')
        with self.assertRaisesRegex(c.ContractError,'fresh_historical_layer2_inputs_changed'):
            session._check_historical_inputs()
        self.assertEqual(parent_before,{path:path.read_bytes() for path in parent_before})


class FreshPreloadTests(unittest.TestCase):
    def test_cold_real_generation_freeze_and_review_preserve_frozen_identity(self):
        # Execute the atomic candidate writer, not just an already assembled
        # bridge. The first real generation imported trace_artifacts lazily.
        child = textwrap.dedent('''
            import json, sys
            from pathlib import Path
            from unittest.mock import patch
            sys.path.insert(0, sys.argv[1])
            from scripts import sermon_fresh_diagnostic as entry
            from scripts import sermon_accounting as accounting
            from scripts import sermon_strict_layer2 as strict
            from tests.test_sermon_strict_layer2 import StrictAdapterTests
            fixture = StrictAdapterTests()
            fixture.setUp()
            try:
                assert 'scripts.sermon_trace_artifacts' not in sys.modules
                frozen = entry.preload_execution_modules([
                    Path(sys.argv[1]) / 'scripts/language_review_plugins/diagnostic_structural.py'])
                assert 'scripts/sermon_trace_artifacts.py' in frozen['loadedProjectCodeSha256']
                with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('network forbidden')) as network:
                    with fixture.session():
                        fixture.generate()
                        assert accounting.execution_identity() == frozen, 'identity changed at candidate freeze'
                        receipt = fixture.review()
                        assert receipt['reviewVerdict'] == 'pass'
                        assert accounting.execution_identity() == frozen, 'identity changed at review'
                        calls = len(fixture.calls)
                        strict.generate(fixture.prepared, fixture.root/'revision', 'candidate', 'r1',
                            'fixture', fixture.transport, cache_only=True)
                        strict.review(fixture.prepared, fixture.root/'revision', 'candidate', 'r1',
                            'fixture', fixture.transport, cache_only=True)
                        assert len(fixture.calls) == calls == 2
                        assert accounting.execution_identity() == frozen, 'identity changed at cache replay'
                    network.assert_not_called()
                assert not any(fixture.root.rglob('provider-run/state.json'))
                print(json.dumps({'identityUnchanged': True, 'fixtureCalls': 2, 'networkCalls': 0}))
            finally:
                fixture.doCleanups()
        ''')
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith('SERMON_ACCOUNTING_')}
        result = subprocess.run([sys.executable, '-I', '-B', '-c', child,
                                 str(Path(entry.__file__).resolve().parents[1])], env=environment,
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout),
                         {'identityUnchanged': True, 'fixtureCalls': 2, 'networkCalls': 0})

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
                                    capture_output=True, text=True, timeout=60)
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

    def test_large_alignment_actual_builders_hash_binding_and_restart(self):
        aligned=c.read_snapshot(self.recipe['prior_aligned_path'])[0]
        # Same genuine word/time shape as the small fixture, with aggregate
        # alignment diagnostics large enough to expose the private-record cap.
        aligned[0]['alignmentDiagnostics']={'tokenTrace':'fixture ' * 40000}
        self.recipe['prior_aligned_path'].write_bytes(c.canonical_bytes(aligned)+b'\n')
        self.assertGreater(self.recipe['prior_aligned_path'].stat().st_size,c.MAX_BYTES)
        prior=c.read_snapshot(self.recipe['prior_source_path'])[0]
        prior['transcript']['artifact'].update(sha256=fresh._sha(self.recipe['prior_aligned_path']),
                                             jsonSha256=c.canonical_sha256(aligned))
        self.recipe['prior_source_path'].write_bytes(c.canonical_bytes(prior))
        before=fresh._sha(self.root/'budget'/budget.STORE_ID/'provider-run/state.json')
        prepared=self.prepare()
        self.assertEqual(prepared['anchor']['sourceUnits'],self.prepare()['anchor']['sourceUnits'])
        self.assertEqual(prepared['source']['transcript']['artifact']['sha256'],
                         fresh._sha(self.root/'aligned-segments.json'))
        self.assertEqual(aggregate.read_snapshot(self.root/'aligned-segments.json')[0],aligned)
        self.assertFalse(prepared['source']['translationEligible'])
        self.assertEqual(before,fresh._sha(self.root/'budget'/budget.STORE_ID/'provider-run/state.json'))
        self.network.assert_not_called()
        # A large but altered aggregate must still fail its upstream byte hash.
        aligned[0]['alignmentDiagnostics']['tokenTrace']+='changed'
        self.recipe['prior_aligned_path'].write_bytes(c.canonical_bytes(aligned))
        with self.assertRaisesRegex(ValueError,'fresh_alignment_prior_artifact_changed'):
            self.prepare()

    def test_alignment_aggregate_json_shape_and_size_fail_with_safe_domain_reason(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'alignment.json'
            for raw in (b'{',b'{}',b'[1]',b'[{"text":NaN}]',b'[{"text":"a","text":"b"}]'):
                path.write_bytes(raw)
                with self.subTest(raw=raw),self.assertRaisesRegex(c.ContractError,'^fresh_alignment_snapshot_invalid$'):
                    fresh._read_alignment(path)
            with path.open('wb') as stream:stream.truncate(aggregate.MAX_BYTES+1)
            with self.assertRaisesRegex(c.ContractError,'^fresh_alignment_snapshot_invalid$'):
                fresh._read_alignment(path)
        self.assertEqual(c.MAX_BYTES,262144)

    def test_large_alignment_does_not_weaken_source_identity_guard(self):
        aligned=c.read_snapshot(self.recipe['prior_aligned_path'])[0]
        aligned[0]['alignmentDiagnostics']={'tokenTrace':'fixture ' * 40000}
        self.recipe['prior_aligned_path'].write_bytes(c.canonical_bytes(aligned))
        prior=c.read_snapshot(self.recipe['prior_source_path'])[0]
        prior['transcript']['artifact'].update(sha256=fresh._sha(self.recipe['prior_aligned_path']),
                                             jsonSha256=c.canonical_sha256(aligned))
        prior['source']['media']['sha256']='0'*64
        self.recipe['prior_source_path'].write_bytes(c.canonical_bytes(prior))
        with self.assertRaisesRegex(c.ContractError,'fresh_alignment_prior_artifact_changed'):
            self.prepare()
        self.assertFalse((self.root/'source.json').exists())

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


class FreshDeliveryRoutingTests(unittest.TestCase):
    def test_fixed_fresh_override_passes_actual_bound_plan_context_evidence(self):
        from scripts import sermon_diagnostic_delivery_preflight as delivery
        session = entry.FreshDiagnosticSession.__new__(entry.FreshDiagnosticSession)
        session.root = Path('/synthetic/frozen-root'); session.subject = object()
        session.context = {'bound': 'context'}; session.plan = {'bound': 'plan'}
        evidence = {'bound': 'actual-fresh-evidence'}; previews = {'zh-Hans': {'bound': 'worker'}}
        with patch.object(session, '_check', return_value=evidence) as check, \
             patch.object(delivery, 'inspect_fresh_delivery', return_value={'modelCalls': 0}) as inspect:
            self.assertEqual(session.inspect_delivery(previews, ('zh-Hans',)), {'modelCalls': 0})
        check.assert_called_once_with()
        inspect.assert_called_once_with(session.root, session.subject, session.context, previews,
            expected_locales=('zh-Hans',), plan=session.plan, source_evidence=evidence)
        with patch.object(session, '_check', return_value=None), patch.object(delivery, 'inspect_fresh_delivery') as inspect:
            with self.assertRaisesRegex(c.ContractError, 'source_preparation_required'):
                session.inspect_delivery(previews, ('zh-Hans',))
        inspect.assert_not_called()

    def test_new_fresh_validator_dependencies_are_eagerly_frozen(self):
        frozen = entry.preload_execution_modules()
        for path in ('scripts/sermon_fresh_source_evidence.py', 'scripts/sermon_transcription_request.py'):
            self.assertEqual(frozen['loadedProjectCodeSha256'][path], c.bytes_sha256((Path(entry.__file__).resolve().parents[1]/path).read_bytes()))


class ActualFreshDeliverySessionTests(unittest.TestCase):
    def test_actual_check_source_profile_frozen_identity_and_delivery_without_late_import_or_dispatch(self):
        from scripts import sermon_diagnostic_delivery_preflight as delivery
        f = FreshSourceTests(); f.setUp(); self.addCleanup(f.doCleanups)
        actual_identity = accounting.execution_identity
        def fixture_clean_identity():
            # Only the clean checkout flag is normalized for this editable unit
            # fixture. Actual loaded modules/bytes/HEAD are reread every time.
            current = actual_identity(); current['trackedWorkingTreeDirty'] = False
            return current
        with patch.object(accounting, 'execution_identity', side_effect=fixture_clean_identity):
            self.assertEqual(fixture_clean_identity(), f.plan['executionIdentity'])
            session = entry.FreshDiagnosticSession(f.plan, offline_transport=f.f.transport)
            calls = len(f.f.transport.observations)
            with profile.session(f.root/'actual-delivery-logs', 'fresh-delivery-fixture',
                    work_kind='engineering', evidence_mode='synthetic'):
                prepared = session.prepare_source(f.recipe, f.authorization)
                frozen = fixture_clean_identity()
                before = {p: p.read_bytes() for p in f.root.rglob('*') if p.is_file() and 'actual-delivery-logs' not in p.parts}
                with patch.object(delivery, '_inspect_preview', return_value={'previewStatus': 'preview_only'}) as native:
                    first = session.inspect_delivery({'zh-Hans': {}}, ('zh-Hans',))
                    second = session.inspect_delivery({'zh-Hans': {}}, ('zh-Hans',))
                self.assertEqual(first, second); self.assertEqual(native.call_count, 2)
                self.assertEqual(first['sourceEvidence']['sourceEvidenceCanonicalSha256'], c.canonical_sha256(prepared['evidence']))
                self.assertEqual(first['sourceEvidence']['currentSourceProviderCalls'], 2)
                self.assertEqual(first['modelCalls'], 0); self.assertEqual(first['humanAcceptance'], 'pending')
                self.assertEqual(fixture_clean_identity(), frozen)
                self.assertEqual(before, {p: p.read_bytes() for p in f.root.rglob('*') if p.is_file() and 'actual-delivery-logs' not in p.parts})
            self.assertEqual(fixture_clean_identity(), frozen)
            self.assertEqual(calls, len(f.f.transport.observations))
