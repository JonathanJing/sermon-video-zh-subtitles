"""Actual D3 files + real public bridge, synthetic provider/human fixtures only."""
import copy
from dataclasses import replace
import json
import shutil
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import unittest

from scripts import sermon_strict_gate_admission as admission
from scripts import sermon_review_budget as budget
from scripts import sermon_review_contracts as c
from scripts import sermon_strict_layer2 as strict
from scripts import sermon_strict_budget_adapter as adapter
from scripts import sermon_strict_candidate_bridge as bridge
from scripts import review_target_language_candidate as human
from scripts import sermon_workflow_jobs as jobs
from tests import test_sermon_strict_layer2 as fixtures
from tests import test_sermon_strict_budget_adapter as budget_fixtures

NOW = '2026-09-30T00:00:00Z'


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.StrictAdapterTests()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        self.f = SimpleNamespace(f=fixture, groups=copy.deepcopy(fixture.f.evidence['groups']), revisions=[])
        self.f.compile = lambda: bridge.compile_candidate(*fixture.args, self.f.revisions,
            plugin_path=fixture.f.plugin_path, expected_plugin_sha256=fixture.f.plugin_sha)
        self.root = self.f.f.root
        paths = {}
        for name, raw in zip(('source', 'anchor', 'policy', 'rubric'), self.f.f.args):
            paths[name] = self.root / (name + '.json')
            paths[name].write_bytes(raw)
        self.paths = paths
        authority = {'approvalSha256': 'a' * 64,
            'globalBounds': {k: 1000000 for k in budget.METRICS},
            'unitBounds': {k: 1000000 for k in budget.METRICS},
            'limits': dict(budget.DEFAULT_LIMITS)}
        self.store = budget.BudgetStore(self.root / 'budget', authority)
        self.generate_groups()
        self.approve()
        self.config = admission.Configuration('b' * 64, 'zh-Hans', self.root / 'jobs',
            self.root, tuple(root for root, _ in self.f.revisions),
            **paths, public_candidate=self.root / 'public.json', human_receipt=self.root / 'human.json',
            plugin=self.f.f.f.plugin_path, plugin_sha256=self.f.f.f.plugin_sha)
        self.boundary = admission.AdmissionBoundary(self.config, self.store)

    def test_policy_preview_tampering_cannot_enter_admission(self):
        root = self.f.revisions[0][0]
        path = root / 'generator.policy-preview.json'
        original = c.read_snapshot(path)[0]
        for changes in ({'humanApproval': True}, {'status': 'approved'},
                        {'payload': {'changed': True}, 'payloadSha256': c.canonical_sha256({'changed': True})}):
            with self.subTest(changes=changes):
                path.write_bytes(c.canonical_bytes({**original, **changes}))
                with self.assertRaisesRegex(c.ContractError, 'admission_policy_preview_changed'):
                    self.boundary.snapshot()
                path.write_bytes(c.canonical_bytes(original))
        self.boundary.snapshot()

    def approve(self, evidence="Synthetic test only, not actual human acceptance"):
        pending = self.f.compile()['candidate']
        source, anchor, policy, rubric = [c.decode_json(b) for b in self.f.f.args]
        worksheet = human.build_worksheet(source, anchor, pending, policy, strict_rubric=rubric)
        reviewed = human.apply_batch_approval(worksheet, reviewer='Synthetic fixture', reviewed_at=NOW,
            evidence=evidence)
        approved, receipt = human.approve_worksheet(source, anchor, pending, policy, reviewed, strict_rubric=rubric)
        (self.root / 'public.json').write_bytes(c.canonical_bytes(approved))
        (self.root / 'human.json').write_bytes(c.canonical_bytes(receipt))

    def generate_groups(self, first_mode='pass'):
        self.subject = adapter.StrictBudgetAdapter(self.store)
        self.f.revisions = []
        self.f.f.calls.clear()
        with self.f.f.session():
            for index, group in enumerate(self.f.groups):
                root = self.root / group['translationGroupId']
                if root.exists(): shutil.rmtree(root)
                self.f.f.f.evidence['groups'][0] = group
                prepared = strict.prepare(*self.f.f.args, {k: group[k] for k in ('translationGroupId', 'sourceUnitIds')})
                self.subject.generate(prepared, root, 'candidate', 'r1', 'fixture', self.f.f.transport,
                    bounds=budget_fixtures.bounds(), usage_resolver=budget_fixtures.measured)
                self.f.f.mode = first_mode if index == 0 else 'pass'
                self.subject.review(prepared, root, 'candidate', 'r1', 'fixture', self.f.f.transport,
                    bounds=budget_fixtures.bounds(), usage_resolver=budget_fixtures.measured)
                self.f.revisions.append((root, 1))

    def admit(self, revision=None):
        return self.boundary.admit(expected_state_revision=revision or self.boundary.snapshot().state_revision,
                                   created_at=NOW)

    def test_real_bridge_admits_whole_locale_once_and_reconciles(self):
        result = self.admit()
        self.assertEqual(result['status'], 'committed', result)
        self.assertEqual(len(result['intent']['decisions']), 2)
        self.assertEqual(result['intent']['publicCandidateSha256'],
                         c.canonical_sha256(c.read_snapshot(self.root / 'public.json')[0]))
        self.assertFalse(result['dispatched'])
        self.assertEqual(self.admit()['status'], 'existing')
        self.assertEqual(len(self.boundary.reconcile()['intents']), 1)
        self.assertEqual(len(self.f.f.calls), 4)

    def test_reissued_receipt_binds_new_intent_without_changing_candidate(self):
        old = self.admit()['intent']
        candidate = (self.root / 'public.json').read_bytes()
        calls = len(self.f.f.calls)
        self.approve(evidence='Synthetic reissued per-group evidence')
        self.assertEqual((self.root / 'public.json').read_bytes(), candidate)
        new = self.admit()
        self.assertEqual(new['status'], 'committed', new)
        self.assertNotEqual(new['intent']['intentId'], old['intentId'])
        self.assertNotEqual(new['intent']['humanReceiptSha256'], old['humanReceiptSha256'])
        self.assertEqual(new['intent']['identity']['humanReceiptSha256'],
                         new['intent']['humanReceiptSha256'])
        self.assertEqual(self.admit()['intent'], new['intent'])
        self.assertEqual(len(self.boundary.reconcile()['intents']), 2)
        self.assertEqual(len(self.f.f.calls), calls)

    def test_legacy_intent_reuse_requires_exact_current_human_receipt(self):
        current = self.admit()['intent']
        legacy = copy.deepcopy(current)
        legacy['identity'].pop('humanReceiptSha256', None)
        legacy['intentId'] = c.canonical_sha256(legacy['identity'])
        with self.boundary._locked() as (path, record, _, _):
            record['intents'] = {legacy['intentId']: legacy}
            jobs._persist(path, record)
        self.assertEqual(self.admit()['intent'], legacy)
        self.approve(evidence='Synthetic renewed evidence for legacy intent')
        new = self.admit()
        self.assertEqual(new['status'], 'committed', new)
        self.assertNotEqual(new['intent']['intentId'], legacy['intentId'])
        self.assertEqual(len(self.boundary.reconcile()['intents']), 2)

    def test_profile_records_group_decisions_and_commit_failure_keeps_unique_intent(self):
        from scripts import sermon_accounting as accounting
        with self.f.f.session():
            with patch.object(accounting,'record_log',side_effect=accounting.AccountingWriteError('fault')):
                result=self.admit()
            self.assertEqual(result['status'],'outcome_unknown')
            self.assertEqual(len(self.boundary.reconcile()['intents']),1)
            self.assertEqual(self.admit()['status'],'existing')
        rows,_=accounting.read_events(self.root/'logs')
        gates=[row for row in rows if row['event']=='rqc_observation' and row['role']=='gate']
        self.assertEqual({r['rqcEvidence']['admissionStatus'] for r in gates},{'admitted'})
        self.assertEqual({r['workUnitId'] for r in gates},{'l2.zh-Hans.g1','l2.zh-Hans.g2'})
        self.assertEqual(len(self.f.f.calls),4)

    def test_known_execution_failure_recovers_only_latest_bound_pass(self):
        self.store = budget.BudgetStore(self.root / 'recovery-budget', self.store.authority)
        self.generate_groups(first_mode='rewrite')
        root = self.f.revisions[0][0]
        group = self.f.groups[0]
        prepared = strict.prepare(*self.f.f.args, {k: group[k] for k in ('translationGroupId', 'sourceUnitIds')})
        self.assertEqual(c.read_snapshot(root / 'review-receipt.json')[0]['executionStatus'], 'failed')
        self.f.f.mode = 'pass'
        with self.f.f.session():
            self.subject.review(prepared, root, 'candidate', 'r1', 'fixture', self.f.f.transport,
                attempt_number=2, bounds=budget_fixtures.bounds(), usage_resolver=budget_fixtures.measured)
        self.f.revisions[0] = (root, 2)
        self.approve()
        self.boundary = admission.AdmissionBoundary(self.config, self.store)
        result = self.admit()
        self.assertEqual(result['status'], 'committed', result)
        self.assertEqual(len(result['intent']['decisions'][0]['reviewReceiptRefs']), 2)

    def test_repaired_group_requires_current_and_root_generation_reservations(self):
        self.store = budget.BudgetStore(self.root / 'repair-budget', self.store.authority)
        self.generate_groups(first_mode='fail')
        parent_root = self.f.revisions[0][0]
        parent = c.read_snapshot(parent_root / 'revision.json')[0]
        review = c.read_snapshot(parent_root / 'review-receipt.json')[0]
        helper = budget_fixtures.StrictBudgetTests()
        helper.f, helper.store = self.f.f, self.store
        repair, _ = helper.repair_context(parent, review, parent_root)
        child_root = self.root / 'repair-2'
        self.f.f.f.evidence['groups'][0] = self.f.groups[0]
        with self.f.f.session():
            child = self.subject.generate(self.f.f.prepared, child_root, 'candidate', repair['plan']['toRevisionId'],
                'fixture', self.f.f.transport, bounds=budget_fixtures.bounds(),
                usage_resolver=budget_fixtures.measured, repair=repair)['artifact']
            self.f.f.mode = 'pass'
            self.subject.review(self.f.f.prepared, child_root, 'candidate', child['revisionId'], 'fixture',
                self.f.f.transport, bounds=budget_fixtures.bounds(), usage_resolver=budget_fixtures.measured)
        self.f.revisions[0] = (child_root, 1)
        self.approve()
        self.config = replace(self.config, revision_roots=tuple(root for root, _ in self.f.revisions))
        self.boundary = admission.AdmissionBoundary(self.config, self.store)
        snapshot = self.boundary.snapshot()
        self.assertIsNotNone(snapshot.groups[0].parent_revision)
        self.assertEqual(self.admit(snapshot.state_revision)['status'], 'committed')
        self.assertEqual(c.read_snapshot(parent_root / 'revision.json')[0], parent)

    def test_missing_or_corrupt_existing_registry_never_resets(self):
        self.admit()
        path = self.store.root / budget.STORE_ID / ('gate-' + self.boundary.key) / 'state.json'
        path.unlink()
        with self.assertRaises(OSError): self.boundary.snapshot()
        self.assertFalse(path.exists())

    def test_missing_generation_and_changed_budget_proof_cannot_adopt_cached_d3(self):
        state = self.boundary.snapshot().state_revision
        root = self.f.revisions[0][0]
        proof = root / 'generator.budget-call.json'
        original = proof.read_bytes()
        value = c.decode_json(original)
        value['reservationId'] = 'f' * 64
        proof.write_bytes(c.canonical_bytes(value))
        self.assertEqual(self.admit(state)['status'], 'blocked')
        proof.write_bytes(original)
        ledger_path = self.store.root / budget.STORE_ID / 'state.json'
        ledger = c.read_snapshot(ledger_path)[0]
        unit = c.read_snapshot(root / 'revision.json')[0]['workUnitIds'][0]
        ledger['reservations'] = {key: row for key, row in ledger['reservations'].items()
            if not (row['request']['identity']['workUnitId'] == unit and row['request']['kind'] == 'initial_generation')}
        jobs._persist(ledger_path, ledger)
        snapshot = self.boundary.snapshot()
        self.assertIn('generation_budget_binding_mismatch', snapshot.diagnostics)
        self.assertEqual(self.admit(snapshot.state_revision)['status'], 'blocked')
        self.assertEqual(self.boundary.reconcile()['intents'], [])

    def test_copying_revision_directory_cannot_create_second_intent(self):
        original = self.admit()['intent']['intentId']
        copied = self.root / 'copied-group'
        shutil.copytree(self.config.revision_roots[0], copied)
        config = replace(self.config, revision_roots=(copied, self.config.revision_roots[1]))
        subject = admission.AdmissionBoundary(config, self.store)
        result = subject.admit(expected_state_revision=subject.snapshot().state_revision, created_at=NOW)
        self.assertEqual(result['status'], 'existing')
        self.assertEqual(result['intent']['intentId'], original)
        self.assertEqual(len(subject.reconcile()['intents']), 1)

    def test_stale_bytes_and_mutation_during_real_bridge_block(self):
        before = self.boundary.snapshot().state_revision
        path = self.root / 'human.json'
        path.write_bytes(path.read_bytes() + b' ')
        self.assertEqual(self.admit(before)['status'], 'stale')
        original = bridge.validate_approved_chain
        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            path.write_bytes(path.read_bytes() + b' ')
            return result
        with patch.object(bridge, 'validate_approved_chain', side_effect=changed):
            self.assertEqual(self.admit()['status'], 'stale')
        self.assertEqual(self.boundary.reconcile()['intents'], [])

    def test_pending_other_group_and_omitted_reservation_block_locale(self):
        root = self.f.revisions[1][0]
        manifest = c.read_snapshot(root / 'revision.json')[0]
        ident = {key: manifest[key] for key in budget.IDENTITY_FIELDS if key not in ('workUnitId', 'rubricSha256')}
        ident.update(workUnitId=manifest['workUnitIds'][0], rubricSha256=c.canonical_sha256(c.decode_json(self.f.f.args[3])))
        self.store.reserve(ident, operation_id='proposal', kind='decision_proposal', revision_id='r1',
            revision_number=1, input_sha256='f' * 64, bounds={k: 1 for k in budget.METRICS})
        self.assertEqual(self.admit()['status'], 'blocked')
        smaller = admission.AdmissionBoundary(replace(self.config, revision_roots=self.config.revision_roots[:1]), self.store)
        snap = smaller.snapshot()
        self.assertIn('locale_group_inventory_incomplete', snap.diagnostics)
        self.assertEqual(smaller.admit(expected_state_revision=snap.state_revision, created_at=NOW)['status'], 'blocked')

    def test_unreserved_attempt_and_unknown_inventory_block(self):
        root = self.f.revisions[1][0]
        (root / 'reviewer-2.call.json').write_text('{}')
        self.assertEqual(self.admit()['status'], 'blocked')
        (root / 'reviewer-2.call.json').unlink()
        (root / 'review-receipt-3.json').write_text('{}')
        with self.assertRaises(ValueError): self.boundary.snapshot()

    def test_other_group_content_conflict_cannot_be_hidden_by_latest_pass(self):
        revision = self.boundary.snapshot().state_revision
        root = self.f.revisions[1][0]
        # A fresh, real failing second attempt remains in the full inventory.
        group = self.f.groups[1]
        prepared = strict.prepare(*self.f.f.args, {k: group[k] for k in ('translationGroupId', 'sourceUnitIds')})
        self.f.f.mode = 'fail'
        with self.f.f.session():
            strict.review(prepared, root, 'candidate', 'r1', 'fixture', self.f.f.transport, attempt_number=2)
        self.assertEqual(self.admit(revision)['status'], 'blocked')
        self.assertEqual(self.boundary.reconcile()['intents'], [])

    def test_crash_before_and_after_atomic_persist_reconcile_without_second_intent(self):
        revision = self.boundary.snapshot().state_revision
        original = jobs._persist
        def before(path, value):
            if path.parent.name.startswith('gate-') and value['intents']: raise OSError('before replace')
            return original(path, value)
        with patch.object(jobs, '_persist', side_effect=before):
            self.assertEqual(self.admit(revision)['status'], 'outcome_unknown')
        self.assertEqual(self.boundary.reconcile()['intents'], [])
        def after(path, value):
            original(path, value)
            if path.parent.name.startswith('gate-') and value['intents']: raise OSError('after replace')
        with patch.object(jobs, '_persist', side_effect=after):
            self.assertEqual(self.admit(revision)['status'], 'outcome_unknown')
        self.assertEqual(len(self.boundary.reconcile()['intents']), 1)
        self.assertEqual(self.admit()['status'], 'existing')

    def test_concurrent_duplicate_and_output_directory_reset(self):
        revision = self.boundary.snapshot().state_revision
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.admit(revision), range(2)))
        self.assertEqual(sum(r['status'] == 'committed' for r in results), 1, results)
        self.assertEqual(len(self.boundary.reconcile()['intents']), 1)
        changed = admission.AdmissionBoundary(replace(self.config, public_candidate=self.root / 'new-public.json'), self.store)
        with self.assertRaisesRegex(ValueError, 'admission_registry_changed'): changed.snapshot()


class FailedReviewInventoryTests(unittest.TestCase):
    def test_two_failed_attempts_remain_distinct_through_planner_and_admission(self):
        import io
        import urllib.error
        from scripts import sermon_pipeline as pipeline
        from scripts.sermon_strict_repair_planner import RepairPlanner

        class InvalidJSONResponse:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def read(self):
                return json.dumps(dict(id='invalid-json-response',model='gpt-6-sol',
                    choices=[dict(finish_reason='stop',message={'content':'not JSON'})],
                    usage={'input_tokens':100,'output_tokens':20})).encode()

        for second_kind in ('invalid_json', 'rejection'):
            with self.subTest(second_kind=second_kind):
                runtime=budget_fixtures.StrictBudgetTests();self.addCleanup(runtime.doCleanups)
                runtime.setUp()
                fixture=runtime.f;root=fixture.root
                paths={}
                for name,raw in zip(('source','anchor','policy','rubric'),fixture.args):
                    paths[name]=root/(name+'.json');paths[name].write_bytes(raw)
                # Intentionally no public/human approval: failure inventories must
                # remain inspectable before any public-candidate bridge can run.
                (root/'public.json').write_text('{}');(root/'human.json').write_text('{}')
                first_error=urllib.error.HTTPError(pipeline.CHAT_URL,400,'synthetic',{},io.BytesIO(b''))
                second=(InvalidJSONResponse() if second_kind=='invalid_json' else
                    urllib.error.HTTPError(pipeline.CHAT_URL,429,'synthetic',{},io.BytesIO(b'')))
                with fixture.session():
                    runtime.generate();candidate_bytes=(runtime.root/'candidate.json').read_bytes()
                    with patch.object(pipeline.urllib.request,'urlopen',side_effect=[first_error,second]) as calls:
                        one=runtime.review(caller=fixture.http_caller)
                        two=runtime.review(caller=fixture.http_caller,attempt_number=2)
                        self.assertEqual(one['executionStatus'],'failed')
                        self.assertEqual(two['executionStatus'],'failed')
                        self.assertEqual(runtime.review(caller=fixture.http_caller,attempt_number=2),two)
                        with self.assertRaisesRegex(ValueError,'invalid_review_attempt_number'):
                            runtime.review(caller=fixture.http_caller,attempt_number=3)
                        self.assertEqual(calls.call_count,2)
                    first_ids={r['artifactId'] for r in one['artifact']['evidenceRefs']}
                    second_ids={r['artifactId'] for r in two['artifact']['evidenceRefs']}
                    self.assertFalse(first_ids & second_ids)
                    self.assertIn('review-execution-failure-2',second_ids)
                    renamed=copy.deepcopy(two['artifact'])
                    for ref in renamed['evidenceRefs']:ref['artifactId']=ref['artifactId'].removesuffix('-2')
                    with self.assertRaisesRegex(ValueError,'strict_review_failure_evidence_changed'):
                        strict._validate_cached_review_evidence(renamed,
                            c.read_snapshot(runtime.root/'revision.json')[0],runtime.root/'reviewer-2.json')
                    if second_kind=='rejection':self.assertIn('review-transport-rejection-2',second_ids)
                    result=RepairPlanner(runtime.store,root/'jobs','7'*64).plan_group(
                        fixture.prepared,runtime.root,
                        [dict(workUnitId=fixture.prepared['workUnitId'],layer=2,targetLocale='zh-Hans',dependsOn=[])],
                        created_at=NOW)
                    self.assertEqual(result['planning']['reasonCode'],'review_execution_limit_reached')
                    self.assertIsNone(result['repair'])
                    config=admission.Configuration('7'*64,'zh-Hans',root/'jobs',root,(runtime.root,),
                        **paths,public_candidate=root/'public.json',human_receipt=root/'human.json',
                        plugin=fixture.f.plugin_path,plugin_sha256=fixture.f.plugin_sha)
                    boundary=admission.AdmissionBoundary(config,runtime.store)
                    snapshot=boundary.snapshot()
                    self.assertEqual(len(snapshot.groups[0].reviews),2)
                    self.assertIn('latest_review_not_passed',snapshot.diagnostics)
                    outcome=boundary.admit(expected_state_revision=snapshot.state_revision,created_at=NOW)
                    self.assertEqual(outcome['status'],'blocked')
                    self.assertIn('latest_review_not_passed',outcome['reasons'])
                    self.assertEqual((runtime.root/'candidate.json').read_bytes(),candidate_bytes)
                    self.assertEqual(len(fixture.calls),1)
                    sidecar=runtime.root/('reviewer-2.structural-diagnostic.json' if second_kind=='invalid_json'
                        else 'reviewer-2.rejection-diagnostic.json')
                    value=json.loads(sidecar.read_text())
                    value['payloadSha256']='0'*64
                    sidecar.write_text(json.dumps(value))
                    with self.assertRaises(ValueError):boundary.snapshot()
                    self.assertEqual(len(fixture.calls),1)


if __name__ == '__main__': unittest.main()
