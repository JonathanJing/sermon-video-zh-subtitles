"""Original Source/context, shared quota and pending-gate continuation checks."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import sermon_accounting as accounting
from scripts import sermon_diagnostic_dag_session as session
from scripts import sermon_review_budget as budget
from scripts import sermon_review_contracts as c
from tests.diagnostic_dag_fixture import DiagnosticDAGFixture


class DiagnosticSessionTests(unittest.TestCase):
    def setUp(self):
        self.f = DiagnosticDAGFixture()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        # Development working trees may be dirty. Only the code-identity gate
        # is substituted in these unit checks; source/budget/receipts are real.
        self.identity = self.f.continuation['executionIdentity']
        self.enterContext(patch.object(accounting, 'execution_identity', return_value=self.identity))

    def make(self, transport=None, **kwargs):
        return session.DiagnosticSession(self.f.plan, self.f.continuation,
            offline_transport=transport or self.f.transport, request_limits=self.f.request_limits, **kwargs)

    def test_full_existing_source_locale_replay_keeps_original_calls_and_pending_gates(self):
        current = self.make()
        before = c.read_snapshot(self.f.root/'budget'/budget.STORE_ID/'provider-run/state.json')[0]
        with self.f.session():
            source = current.inspect_source()
            result = current.run_locale('zh-Hans', self.f.locale_specs['zh-Hans'])
            replay = self.make().run_locale('zh-Hans', self.f.locale_specs['zh-Hans'])
        self.assertEqual(source['newASRCalls'], 0)
        self.assertEqual(source['newSourceCheckCalls'], 0)
        self.assertEqual(result['status'], 'waiting_human')
        self.assertEqual(result['candidateSha256'], replay['candidateSha256'])
        self.assertEqual(len(self.f.transport.observations), 6)
        after = c.read_snapshot(self.f.root/'budget'/budget.STORE_ID/'provider-run/state.json')[0]
        self.assertEqual(before['startedMonotonic'], after['startedMonotonic'])
        self.assertEqual(before['config'], after['config'])
        for call, receipt in before['requests'].items():
            self.assertEqual(receipt, after['requests'][call])
        candidate = c.read_snapshot(Path(result['output'])/'candidate.json')[0]
        self.assertEqual(candidate['humanReview']['translation'], 'pending')
        self.assertFalse(candidate['releaseEligible'])

    def migration_config(self):
        from scripts import sermon_diagnostic_prefect_flow as flow
        return {'schemaVersion': flow.SCHEMA, 'locales': {locale: {
            'localeSpec': self.f.locale_specs[locale],
            'previewSpec': self.f.preview_specs[locale]} for locale in self.f.locale_specs}}

    def legacy_plan(self, current, *, with_limits, change=None):
        from scripts import sermon_diagnostic_prefect_flow as flow
        binding = deepcopy(flow.DiagnosticDAG(current, self.migration_config()).binding)
        binding['sessionBinding']['schemaVersion'] = 'sermon-diagnostic-dag-session-v1'
        binding['sessionBinding']['implementationSha256'] = 'a' * 64
        binding['codeSha256'] = 'b' * 64
        if not with_limits:
            del binding['sessionBinding']['requestLimits']
        if change is not None:
            change(binding)
        root = self.f.root / 'diagnostic-prefect' / c.canonical_sha256(binding)
        from scripts import sermon_public_snapshot as public
        root.mkdir(parents=True, exist_ok=True)
        public.save_once(root / 'plan.json', binding)
        return root / 'plan.json'

    def test_rejected_limits_do_not_poison_legacy_snapshot(self):
        from scripts import sermon_diagnostic_prefect_flow as flow
        current = self.make()
        path = self.legacy_plan(current, with_limits=True)
        limits_path = self.f.root/'continuation-request-limits.json'
        limits_path.unlink()
        old = c.read_snapshot(path)[0]
        lower = {**self.f.request_limits, 'maxInputTokens':8192}
        with self.assertRaisesRegex(ValueError, 'migration_identity_changed'):
            session.DiagnosticSession(self.f.plan, self.f.continuation,
                offline_transport=self.f.transport, request_limits=lower,
                resume_binding=old['sessionBinding'])
        self.assertFalse(limits_path.exists())
        correct = session.DiagnosticSession(self.f.plan, self.f.continuation,
            offline_transport=self.f.transport,
            resume_binding=old['sessionBinding'])
        self.assertFalse(limits_path.exists())
        flow.DiagnosticDAG(correct, self.migration_config(), resume_plan=path).freeze()
        self.assertEqual(c.read_snapshot(limits_path)[0], self.f.request_limits)

    def test_v1_migration_keeps_original_plan_directory_and_receipts(self):
        from scripts import sermon_diagnostic_prefect_flow as flow
        current = self.make()
        self.assertEqual(current.binding['schemaVersion'], 'sermon-diagnostic-dag-session-v2')
        with self.f.session():
            candidate_result = current.run_locale('zh-Hans', self.f.locale_specs['zh-Hans'])
        candidate_path = Path(candidate_result['output']) / 'candidate.json'
        candidate_before = candidate_path.read_bytes()
        for with_limits in (False, True):
            with self.subTest(with_limits=with_limits):
                path = self.legacy_plan(current, with_limits=with_limits)
                before = path.read_bytes()
                receipt = path.parent / 'observations' / 'original.json'
                receipt.parent.mkdir(exist_ok=True)
                receipt.write_bytes(b'{"original":"immutable"}\n')
                receipt_before = receipt.read_bytes()
                calls = len(self.f.transport.observations)
                dag = flow.DiagnosticDAG(current, self.migration_config(), resume_plan=path)
                dag.freeze()
                self.assertEqual(dag.root, path.parent)
                self.assertEqual(dag.plan_sha256, path.parent.name)
                migration = c.read_snapshot(dag.root/'session-binding-migration-v2.json')[0]
                self.assertEqual(migration['executionBinding']['sessionBinding'], current.binding)
                self.assertFalse(migration['providerRetry'])
                with self.f.session():
                    self.assertTrue(dag.execute('source.existing')['readyForDownstream'])
                    self.assertTrue(dag.execute('text.zh-Hans')['readyForDownstream'])
                again = flow.DiagnosticDAG(self.make(), self.migration_config(), resume_plan=path)
                again.freeze()
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(receipt.read_bytes(), receipt_before)
                self.assertEqual(candidate_path.read_bytes(), candidate_before)
                self.assertEqual(len(self.f.transport.observations), calls)

    def test_cross_continuation_reuses_existing_preview_and_delivery_context(self):
        from scripts import sermon_diagnostic_prefect_flow as flow
        legacy_authority = deepcopy(self.f.continuation)
        first = self.make()
        with self.f.session():
            first.run_locale('zh-Hans',self.f.locale_specs['zh-Hans'])
            preview = first.preview('zh-Hans',self.f.preview_specs['zh-Hans'])
            original_delivery = first.inspect_delivery({'zh-Hans':preview},['zh-Hans'])
        old = self.legacy_plan(first,with_limits=True)
        current_authority = deepcopy(legacy_authority)
        new_identity = deepcopy(self.identity)
        new_identity['gitCommit'] = 'a'*40 if self.identity['gitCommit'] != 'a'*40 else 'b'*40
        current_authority['executionIdentity'] = new_identity
        current_authority['diagnosticContext']['continuationCodeCommit'] = new_identity['gitCommit']
        calls = len(self.f.transport.observations)
        with patch.object(accounting,'execution_identity',return_value=new_identity):
            active = session.DiagnosticSession(self.f.plan,current_authority,
                offline_transport=self.f.transport,
                resume_binding=c.read_snapshot(old)[0]['sessionBinding'],
                legacy_continuation=legacy_authority)
            migrated = flow.DiagnosticDAG(active,self.migration_config(),resume_plan=old)
            migrated.freeze()
            with self.f.session():
                active.run_locale('zh-Hans',self.f.locale_specs['zh-Hans'])
                reused = active.preview('zh-Hans',self.f.preview_specs['zh-Hans'])
                delivery = active.inspect_delivery({'zh-Hans':reused},['zh-Hans'])
                self.assertTrue(migrated._validate('preview','zh-Hans',reused)[0])
        self.assertEqual(reused['receiptFileSha256'],preview['receiptFileSha256'])
        self.assertEqual(delivery['status'],original_delivery['status'])
        self.assertEqual(len(self.f.transport.observations),calls)

    def test_v1_migration_rejects_semantic_inputs_and_limits_changes(self):
        from scripts import sermon_diagnostic_prefect_flow as flow
        current = self.make()
        changes = [lambda x: x['sessionBinding'].__setitem__('originalPlanSha256', 'c'*64),
                   lambda x: x['sessionBinding'].__setitem__('deadlineMonotonic', 1),
                   lambda x: x['sessionBinding'].__setitem__('sourceEvidence', {}),
                   lambda x: x['sessionBinding'].__setitem__('storeSha256', 'c'*64),
                   lambda x: x['sessionBinding']['requestLimits'].__setitem__('maxInputTokens', 8192),
                   lambda x: x.__setitem__('inputFiles', {}),
                   lambda x: x.__setitem__('maxWorkers', 2)]
        before = self.f.subject.snapshot()
        for change in changes:
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'migration_.*changed'):
                flow.DiagnosticDAG(current, self.migration_config(),
                    resume_plan=self.legacy_plan(current, with_limits=True, change=change))
        self.assertEqual(self.f.subject.snapshot(), before)

    def test_resume_plan_requires_legacy_version_and_original_hashed_path(self):
        from scripts import sermon_diagnostic_prefect_flow as flow
        current = self.make()
        normal = flow.DiagnosticDAG(current, self.migration_config())
        normal.freeze()
        self.assertIsNone(normal._migration)
        self.assertFalse((normal.root/'session-binding-migration-v2.json').exists())
        with self.assertRaisesRegex(ValueError, 'migration_version_invalid'):
            flow.DiagnosticDAG(current, self.migration_config(), resume_plan=normal.root/'plan.json')
        old = self.legacy_plan(current, with_limits=False)
        misplaced, _ = self.f.write('misplaced-plan.json', c.read_snapshot(old)[0])
        with self.assertRaisesRegex(ValueError, 'resume_plan_path_invalid'):
            flow.DiagnosticDAG(current, self.migration_config(), resume_plan=misplaced)
        malformed, _ = self.f.write('malformed-plan.json', [])
        with self.assertRaisesRegex(ValueError, 'resume_plan_invalid'):
            flow.DiagnosticDAG(current, self.migration_config(), resume_plan=malformed)

    def test_v1_migration_is_frozen_and_does_not_weaken_code_guard(self):
        from scripts import sermon_diagnostic_prefect_flow as flow
        current = self.make()
        path = self.legacy_plan(current, with_limits=False)
        dag = flow.DiagnosticDAG(current, self.migration_config(), resume_plan=path)
        current.binding['requestLimits']['maxInputTokens'] = 8192
        with self.assertRaisesRegex(ValueError, 'migration_changed'):
            dag.freeze()
        current = self.make()
        dag = flow.DiagnosticDAG(current, self.migration_config(), resume_plan=path)
        dag.freeze()
        with self.f.session(), patch.object(accounting, 'execution_identity', return_value={}):
            with self.assertRaisesRegex(ValueError, 'continuation_code_changed'):
                current.inspect_source()
        migration = path.parent / 'session-binding-migration-v2.json'
        migration_bytes = migration.read_bytes()
        migration.unlink()
        with self.assertRaisesRegex(ValueError, 'migration_missing'):
            dag._check()
        migration.write_bytes(migration_bytes)
        path.unlink()
        with self.assertRaisesRegex(ValueError, 'resume_plan_missing'):
            dag.freeze()

    def test_omitted_limits_resume_original_expanded_reviewer_bound(self):
        current = self.make()
        resumed = session.DiagnosticSession(self.f.plan, self.f.continuation,
            offline_transport=self.f.transport)
        self.assertEqual(resumed.binding['requestLimits'], self.f.request_limits)
        self.assertEqual(resumed.subject.limits['maxInputTokens'], 16384)
        with self.f.session():
            result = resumed.run_locale('zh-Hans', self.f.locale_specs['zh-Hans'])
        self.assertEqual(result['status'], 'waiting_human')
        self.assertEqual(len(self.f.transport.observations), 6)
        self.assertEqual(current.binding['requestLimits'], resumed.binding['requestLimits'])

    def test_initial_omitted_limits_require_explicit_binding_without_dispatch(self):
        before = self.f.subject.snapshot()
        with self.assertRaisesRegex(ValueError, 'continuation_request_limits_required'):
            session.DiagnosticSession(self.f.plan, self.f.continuation,
                offline_transport=self.f.transport)
        self.assertEqual(self.f.subject.snapshot(), before)
        self.assertFalse((self.f.root/'continuation-request-limits.json').exists())
        self.assertEqual(len(self.f.transport.observations), 2)

    def test_invalid_saved_limits_do_not_fall_back_to_defaults(self):
        self.make()
        path = self.f.root/'continuation-request-limits.json'
        path.write_bytes(c.canonical_bytes({}))
        before = self.f.subject.snapshot()
        with self.assertRaises(ValueError):
            session.DiagnosticSession(self.f.plan, self.f.continuation,
                offline_transport=self.f.transport)
        self.assertEqual(self.f.subject.snapshot(), before)
        self.assertEqual(len(self.f.transport.observations), 2)

    def test_prefect_cli_forwards_explicit_resume_plan(self):
        from scripts import sermon_diagnostic_prefect_flow as flow
        current = self.make()
        old = self.legacy_plan(current, with_limits=False)
        plan, _ = self.f.write('cli-plan.json', self.f.plan)
        spec, _ = self.f.write('cli-spec.json', self.migration_config())
        captured = []
        def inspect_only(active, config, *, resume_plan):
            captured.append(flow.DiagnosticDAG(active, config, resume_plan=resume_plan))
            captured[-1].freeze()
            return {'status': 'migration_bound_without_dispatch'}
        with patch.object(flow, 'fixture_transport', return_value=self.f.transport), \
                patch.object(flow, 'run', side_effect=inspect_only), patch('builtins.print'):
            flow.main(['--plan', str(plan), '--continuation', str(self.f.root/'continuation.json'),
                       '--spec', str(spec), '--fixture-responses', str(self.f.root/'unused.json'),
                       '--offline-fixture', '--resume-plan', str(old)])
        self.assertEqual(captured[0].root, old.parent)
        self.assertEqual(len(self.f.transport.observations), 2)

    def test_both_cli_resumes_load_limits_without_an_option(self):
        from scripts import sermon_diagnostic_prefect_flow as flow
        from scripts import sermon_mock_tts_dag as mock_tts
        self.make()
        plan_path, _ = self.f.write('cli-plan.json', self.f.plan)
        spec_path, _ = self.f.write('cli-spec.json', {})
        for cli in (flow, mock_tts):
            captured = []
            def capture(current, config, **kwargs):
                captured.append(current.binding['requestLimits'])
                return {'status': 'bound_only'}
            with self.subTest(cli=cli.__name__), \
                    patch.object(flow, 'fixture_transport', return_value=self.f.transport), \
                    patch.object(cli, 'run', side_effect=capture), \
                    patch('builtins.print'):
                cli.main(['--plan', str(plan_path), '--continuation', str(self.f.root/'continuation.json'),
                          '--spec', str(spec_path), '--fixture-responses', str(self.f.root/'unused.json'),
                          '--offline-fixture'])
            self.assertEqual(captured, [self.f.request_limits])
        self.assertEqual(len(self.f.transport.observations), 2)

    def test_both_cli_initial_limits_option_freezes_the_selected_bound(self):
        from scripts import sermon_diagnostic_prefect_flow as flow
        from scripts import sermon_mock_tts_dag as mock_tts
        plan_path, _ = self.f.write('cli-plan.json', self.f.plan)
        spec_path, _ = self.f.write('cli-spec.json', {})
        limits_path, _ = self.f.write('cli-limits.json', self.f.request_limits)
        for cli in (flow, mock_tts):
            (self.f.root/'continuation-request-limits.json').unlink(missing_ok=True)
            with self.subTest(cli=cli.__name__), \
                    patch.object(flow, 'fixture_transport', return_value=self.f.transport), \
                    patch.object(cli, 'run', return_value={'status': 'bound_only'}), \
                    patch('builtins.print'):
                cli.main(['--plan', str(plan_path), '--continuation', str(self.f.root/'continuation.json'),
                          '--spec', str(spec_path), '--fixture-responses', str(self.f.root/'unused.json'),
                          '--offline-fixture', '--request-limits', str(limits_path)])
            saved, _ = c.read_snapshot(self.f.root/'continuation-request-limits.json')
            self.assertEqual(saved, self.f.request_limits)
        self.assertEqual(len(self.f.transport.observations), 2)

    def test_explicit_limits_are_frozen_across_continuation_restart(self):
        current = self.make()
        lower = {**self.f.request_limits, 'maxInputTokens': 8192}
        with self.assertRaisesRegex(ValueError, 'immutable_strict_artifact_changed'):
            session.DiagnosticSession(self.f.plan, self.f.continuation,
                offline_transport=self.f.transport, request_limits=lower)
        self.assertEqual(current.binding['requestLimits'], self.f.request_limits)
        self.assertEqual(len(self.f.transport.observations), 2)
        current.subject.limits = lower
        with self.f.session(), self.assertRaisesRegex(ValueError, 'diagnostic_dag_binding_changed'):
            current.inspect_source()
        self.assertEqual(len(self.f.transport.observations), 2)

    def test_real_credentials_or_missing_offline_marker_cannot_adopt_existing_run(self):
        state = self.f.root/'budget'/budget.STORE_ID/'provider-run/state.json'
        before = state.read_bytes()
        with self.assertRaisesRegex(ValueError, 'explicit_transport_required'):
            self.make(key='not-a-real-key')
        (self.f.root/'offline-business-scope.json').unlink()
        with self.assertRaises((ValueError, OSError)):
            self.make()
        self.assertEqual(state.read_bytes(), before)
        self.assertEqual(len(self.f.transport.observations), 2)

    def test_live_mode_requires_explicit_execute_and_cannot_use_fixture_store(self):
        with self.assertRaisesRegex(ValueError, 'explicit_transport_required'):
            session.DiagnosticSession(self.f.plan, self.f.continuation, key='fixture-not-a-key')
        with self.assertRaisesRegex(ValueError, 'fixture_cannot_become_live'):
            session.DiagnosticSession(self.f.plan, self.f.continuation,
                                      key='fixture-not-a-key', execute=True)
        self.assertEqual(len(self.f.transport.observations), 2)

    def test_unknown_or_expired_original_provider_blocks_without_renewal(self):
        path = self.f.root/'budget'/budget.STORE_ID/'provider-run/state.json'
        original = path.read_bytes()
        for mode in ('unknown', 'expired'):
            state = c.decode_json(original)
            if mode == 'unknown':
                next(iter(state['requests'].values()))['state'] = 'outcome_unknown'
            else:
                state['startedMonotonic'] -= state['config']['totalWallSeconds'] + 1
            path.write_bytes(c.canonical_bytes(state))
            before = path.read_bytes()
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.make()
            self.assertEqual(path.read_bytes(), before)
        self.assertEqual(len(self.f.transport.observations), 2)

    def test_changed_source_and_outside_locale_input_rejected_before_new_call(self):
        current = self.make()
        spec = deepcopy(self.f.locale_specs['zh-Hans'])
        outside = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()/'policy.json'
        outside.write_bytes(Path(spec['policy']).read_bytes())
        spec['policy'] = str(outside)
        with self.f.session(), self.assertRaisesRegex(ValueError, 'outside_scope'):
            current.run_locale('zh-Hans', spec)
        original = self.f.root/'source-review-request.json'
        value = json.loads(original.read_text())
        value['machineIssues'][0]['reviewStatus'] = 'approved'
        original.write_text(json.dumps(value))
        with self.f.session(), self.assertRaises(ValueError):
            current.inspect_source()
        self.assertEqual(len(self.f.transport.observations), 2)

    def test_preview_cannot_substitute_candidate_or_skip_failed_machine_review(self):
        current = self.make()
        with self.f.session(), self.assertRaisesRegex(ValueError, 'machine_candidate_required'):
            current.preview('zh-Hans', self.f.preview_specs['zh-Hans'])
        with self.f.session():
            current.run_locale('zh-Hans', self.f.locale_specs['zh-Hans'])
            spec = deepcopy(self.f.preview_specs['zh-Hans'])
            spec['paths']['candidate'] = str(self.f.root/'arbitrary.json')
            with self.assertRaisesRegex(ValueError, 'candidate_owned_by_locale'):
                current.preview('zh-Hans', spec)
        self.assertFalse((self.f.root/'diagnostic-previews').exists())


if __name__ == '__main__':
    unittest.main()


class CrossCommitMigrationTests(unittest.TestCase):
    def test_two_real_commits_accept_new_authorization_without_code_gate_mock(self):
        import os
        import shutil
        import subprocess
        import sys
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            repo = Path(directory)
            source = Path(__file__).resolve().parents[1]
            for name in ('scripts','tests','schemas','config'):
                shutil.copytree(source/name,repo/name,
                    ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
            (repo/'docs').mkdir()
            shutil.copy2(source/'docs/series-terminology.zh.md',repo/'docs/series-terminology.zh.md')
            def command(*args):
                return subprocess.run(args,cwd=repo,check=True,capture_output=True,text=True)
            command('git','init','-q')
            command('git','add','.')
            command('git','-c','user.name=Fixture','-c','user.email=fixture@example.invalid',
                    'commit','-qm','old code')
            code = r"""
from copy import deepcopy
from pathlib import Path
import subprocess
from scripts import sermon_accounting as accounting
from scripts import sermon_review_contracts as c
from scripts import sermon_public_snapshot as public
from scripts.sermon_diagnostic_dag_session import DiagnosticSession
from scripts import sermon_diagnostic_prefect_flow as flow
from tests.diagnostic_dag_fixture import DiagnosticDAGFixture
f=DiagnosticDAGFixture();f.setUp()
try:
    old_authority=deepcopy(f.continuation)
    first=DiagnosticSession(f.plan,old_authority,offline_transport=f.transport,request_limits=f.request_limits)
    config={'schemaVersion':flow.SCHEMA,'locales':{locale:{'localeSpec':f.locale_specs[locale],
        'previewSpec':f.preview_specs[locale]} for locale in f.locale_specs}}
    old=deepcopy(flow.DiagnosticDAG(first,config).binding)
    old['sessionBinding']['schemaVersion']='sermon-diagnostic-dag-session-v1'
    path=f.root/'diagnostic-prefect'/c.canonical_sha256(old)/'plan.json'
    path.parent.mkdir(parents=True);public.save_once(path,old)
    Path('scripts/migration_commit_marker.py').write_text('# second code commit\n')
    subprocess.run(['git','add','.'],check=True)
    subprocess.run(['git','-c','user.name=Fixture','-c','user.email=fixture@example.invalid',
        'commit','-qm','new code'],check=True)
    identity=accounting.execution_identity()
    assert not identity['trackedWorkingTreeDirty']
    assert identity['gitCommit'] != old_authority['executionIdentity']['gitCommit']
    current=deepcopy(old_authority)
    current['executionIdentity']=identity
    current['diagnosticContext']['continuationCodeCommit']=identity['gitCommit']
    before=f.subject.snapshot()
    try:
        DiagnosticSession(f.plan,old_authority,offline_transport=f.transport,request_limits=f.request_limits,
            resume_binding=old['sessionBinding'])
    except ValueError as error:
        assert 'code_changed' in str(error)
    else: raise AssertionError('old code authorization unexpectedly accepted')
    active=DiagnosticSession(f.plan,current,offline_transport=f.transport,request_limits=f.request_limits,
        resume_binding=old['sessionBinding'],legacy_continuation=old_authority)
    migrated=flow.DiagnosticDAG(active,config,resume_plan=path);migrated.freeze()
    assert migrated.root == path.parent
    assert active.locale_context == old_authority['diagnosticContext']
    receipt=public.read_snapshot(path.parent/'session-binding-migration-v2.json')[0]
    assert receipt['currentContinuation'] == current
    assert receipt['legacyContinuation'] == old_authority
    assert f.subject.snapshot() == before
    assert len(f.transport.observations) == 2
finally: f.doCleanups()
"""
            result = subprocess.run([sys.executable,'-c',code],cwd=repo,
                env={**os.environ,'PYTHONPATH':str(repo),'PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,text=True,timeout=90)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
