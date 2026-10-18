import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from scripts import canonical_layer2_budget as subject
from scripts import check_run_start as start_check
from scripts import sermon_review_budget as ledger
from scripts import sermon_workflow_jobs as jobs
from tests import test_canonical_layer2_budget as budget_fixtures
from tongxing_production.contracts import canonical as canonical_contracts
from tongxing_production.text import policy as policy_tools
from tongxing_production.text import policy_preview


class CanonicalLayer2BudgetReuseTests(unittest.TestCase):
    def setUp(self):
        self.base = budget_fixtures.CanonicalLayer2BudgetTests()
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.destination = Path(temporary.name) / 'destination'

    def paid(self):
        caller = subject.BudgetedCaller(self.base.auth, self.base.config, self.base.source,
                                        self.base.anchor, self.base.policy,
                                        transport=lambda *_: {'id': 'paid-response',
                                            'model': 'gpt-6-astra',
                                            'usage': {'prompt_tokens': 11, 'completion_tokens': 7},
                                            'choices': [{'finish_reason': 'stop', 'message': {'content': '{}'}}]})
        response = caller('', self.base.payload)
        provenance = caller.paid_response_provenance('', self.base.payload, response)
        return caller, response, provenance

    def destination_caller(self, source, *, root=None, policy=None):
        root = self.destination if root is None else root
        caller = subject.BudgetedCaller(self.base.auth, self.base.config, self.base.source,
                                        self.base.anchor, policy or self.base.policy,
                                        transport=lambda *_: self.fail('reused response dispatched'))
        caller.root = root
        caller.auth = {**caller.auth, 'reuseBudgetRoots': {'zh-Hans': [source]}, 'scope': 'run'}
        caller.store = ledger.BudgetStore(root, self.base.auth['value']['authority'],
                                          reuse_roots=[source])
        return caller

    def plugin_only_policy(self):
        value = copy.deepcopy(self.base.policy)
        value.pop('componentSha256')
        value['languageReview']['pluginId'] += '-repaired'
        value['languageReview']['pluginImplementationSha256'] = 'f' * 64
        return policy_tools.freeze_policy(value)

    def test_direct_paid_response_records_zero_charge_without_a_reservation(self):
        source, response, provenance = self.paid()
        destination = self.destination_caller(source.root)
        with patch.object(destination, 'verify_execution'):
            result = destination.record_reuse('', self.base.payload, response, provenance)
        self.assertEqual(result['status'], 'succeeded')
        state = jobs._read(self.destination / ledger.STORE_ID / 'state.json')
        row = next(iter(state['reservations'].values()))
        self.assertEqual(row['settlement']['costStatus'], 'reused')
        self.assertEqual(row['settlement']['costMicrousd'], 0)
        self.assertEqual(ledger._charge(row), dict.fromkeys(ledger.METRICS, 0))
        self.assertEqual(ledger._sum(state['reservations'].values()),
                         dict.fromkeys(ledger.METRICS, 0))
        self.assertEqual(row['result']['usage'], dict.fromkeys(ledger.METRICS, 0))

    def test_paid_provenance_coordinates_with_concurrent_ledger_writer(self):
        caller, response, expected = self.paid()
        other_payload = json.loads(json.dumps(self.base.payload))
        other_payload['messages'][0]['content'] += ' '
        start_writer = threading.Event()
        writer_done = threading.Event()
        writer_errors = []

        def write_another_result():
            start_writer.wait()
            try:
                caller('', other_payload)
            except BaseException as error:  # Preserve the worker failure for the main assertion.
                writer_errors.append(error)
            finally:
                writer_done.set()

        writer = threading.Thread(target=write_another_result)
        writer.start()
        self.addCleanup(lambda: writer.join(timeout=5))
        reader_thread = threading.get_ident()
        first_reader_stat = True
        real_fstat = canonical_contracts.os.fstat

        def pause_after_open(fd):
            nonlocal first_reader_stat
            observed = real_fstat(fd)
            if threading.get_ident() == reader_thread and first_reader_stat:
                first_reader_stat = False
                start_writer.set()
                # Without reader/writer coordination the writer replaces state.json here,
                # reproducing the production snapshot_changed_during_read failure. With
                # the fix it waits for the provenance reader's BudgetStore lock instead.
                writer_done.wait(timeout=2)
            return observed

        with patch.object(caller, 'verify_execution'), \
                patch.object(canonical_contracts.os, 'fstat', side_effect=pause_after_open):
            actual = caller.paid_response_provenance('', self.base.payload, response)
        writer.join(timeout=5)
        self.assertFalse(writer.is_alive())
        self.assertEqual(writer_errors, [])
        self.assertEqual(actual, expected)
        state = jobs._read(caller.root / ledger.STORE_ID / 'state.json')
        self.assertEqual(len(state['reservations']), 2)

    def test_current_paid_provenance_lock_preserves_fail_closed_checks(self):
        caller, response, provenance = self.paid()
        _, folder, _ = jobs._paths(caller.root, ledger.STORE_ID)
        state_path = folder / 'state.json'
        original = jobs._read(state_path)
        rid = provenance['reservationId']

        unknown = json.loads(json.dumps(original))
        unknown['reservations'][rid].update(phase='request')
        unknown['reservations'][rid].pop('result')
        jobs._persist(state_path, unknown)
        with patch.object(caller, 'verify_execution'), self.assertRaisesRegex(
                ValueError, 'provider_outcome_unknown'):
            caller.paid_response_provenance('', self.base.payload, response)

        jobs._persist(state_path, original)
        response_path = caller.root / 'responses' / (provenance['inputSha256'] + '.json')
        damaged = jobs._read(response_path)
        damaged['response'] = {'forged': True}
        jobs._persist(response_path, damaged)
        with patch.object(caller, 'verify_execution'), self.assertRaisesRegex(
                ValueError, 'reconciliation_required'):
            caller.paid_response_provenance('', self.base.payload, response)

    def test_later_round_reuses_same_job_direct_paid_response_without_rewriting_ledger(self):
        external = self.destination / 'approved-prior'
        with ledger.BudgetStore(external, self.base.auth['value']['authority'])._locked():
            pass
        current = self.destination_caller(external)
        current.transport = lambda *_: {'id': 'paid-response',
            'model': 'gpt-6-astra',
            'usage': {'prompt_tokens': 11, 'completion_tokens': 7},
            'choices': [{'finish_reason': 'stop', 'message': {'content': '{}'}}]}
        with patch.object(current, 'verify_execution'):
            response = current('', self.base.payload)
            provenance = current.paid_response_provenance('', self.base.payload, response)
        state_path = next(self.destination.glob('*/state.json'))
        before = state_path.read_bytes()

        with patch.object(current, 'verify_execution'):
            result = current.record_reuse('', self.base.payload, response, provenance)

        self.assertEqual(result['status'], 'succeeded')
        self.assertFalse(result['created'])
        self.assertFalse(result['executionAllowed'])
        self.assertEqual(state_path.read_bytes(), before)
        state = jobs._read(state_path)
        row = next(iter(state['reservations'].values()))
        self.assertNotIn('settlement', row)
        self.assertEqual(row['result']['usage']['requests'], 1)

        unapproved, _, unapproved_provenance = self.paid()
        self.assertNotEqual(unapproved.root, external.resolve())
        with patch.object(current, 'verify_execution'), self.assertRaisesRegex(
                ValueError, 'layer2_reuse_operation_missing'):
            current.record_reuse('', self.base.payload, response, unapproved_provenance)

    def test_plugin_only_policy_migration_recovers_and_records_real_budget_provenance(self):
        source, response, _ = self.paid()
        changed = self.plugin_only_policy()
        destination = self.destination_caller(source.root, policy=changed)
        migration = {
            'before': policy_preview.payload_preview('translator', self.base.payload, self.base.policy),
            'after': policy_preview.payload_preview('translator', self.base.payload, changed),
        }

        with patch.object(destination, 'verify_execution'):
            provenance = destination.recover_returned_response(
                '', self.base.payload, response, source.root,
                policy_migration=migration)
            result = destination.record_reuse(
                '', self.base.payload, response, provenance)

        self.assertEqual(result['status'], 'succeeded')
        state = jobs._read(self.destination / ledger.STORE_ID / 'state.json')
        row = next(iter(state['reservations'].values()))
        self.assertEqual(row['request']['identity']['policySha256'], jobs._digest(changed))
        self.assertEqual(row['settlement']['costStatus'], 'reused')
        self.assertEqual(row['settlement']['reusedFrom'], provenance)
        self.assertEqual(row['result']['usage'], dict.fromkeys(ledger.METRICS, 0))

    def test_plugin_policy_migration_rejects_model_payload_or_nonplugin_policy_change(self):
        source, response, _ = self.paid()
        changed = self.plugin_only_policy()
        destination = self.destination_caller(source.root, policy=changed)
        before = policy_preview.payload_preview('translator', self.base.payload, self.base.policy)
        changed_payload = copy.deepcopy(self.base.payload)
        changed_payload['messages'][0]['content'] += ' changed'
        payload_migration = {
            'before': before,
            'after': policy_preview.payload_preview('translator', changed_payload, changed),
        }
        with patch.object(destination, 'verify_execution'), self.assertRaisesRegex(
                ValueError, 'layer2_plugin_policy_migration_required'):
            destination.recover_returned_response(
                '', changed_payload, response, source.root,
                policy_migration=payload_migration)

        nonplugin = copy.deepcopy(self.base.policy)
        nonplugin.pop('componentSha256')
        nonplugin['translator']['promptVersion'] += '-changed'
        nonplugin = policy_tools.freeze_policy(nonplugin)
        destination = self.destination_caller(
            source.root, root=self.destination / 'nonplugin', policy=nonplugin)
        policy_migration = {
            'before': before,
            'after': policy_preview.payload_preview('translator', self.base.payload, nonplugin),
        }
        with patch.object(destination, 'verify_execution'), self.assertRaisesRegex(
                ValueError, 'layer2_plugin_policy_migration_required'):
            destination.recover_returned_response(
                '', self.base.payload, response, source.root,
                policy_migration=policy_migration)

    def test_plugin_policy_migration_never_promotes_an_intermediate_reused_root(self):
        source, response, provenance = self.paid()
        intermediate_root = self.destination / 'intermediate'
        intermediate = self.destination_caller(source.root, root=intermediate_root)
        with patch.object(intermediate, 'verify_execution'):
            intermediate.record_reuse('', self.base.payload, response, provenance)

        changed = self.plugin_only_policy()
        destination = self.destination_caller(
            intermediate.store.root, root=self.destination / 'final', policy=changed)
        migration = {
            'before': policy_preview.payload_preview('translator', self.base.payload, self.base.policy),
            'after': policy_preview.payload_preview('translator', self.base.payload, changed),
        }
        with patch.object(destination, 'verify_execution'), self.assertRaisesRegex(
                ValueError, 'layer2_reuse_requires_direct_paid_root'):
            destination.recover_returned_response(
                '', self.base.payload, response, intermediate.store.root,
                policy_migration=migration)

    def test_unknown_damaged_or_intermediate_source_never_falls_through(self):
        source, response, provenance = self.paid()
        destination = self.destination_caller(source.root)
        _, folder, _ = jobs._paths(source.root, ledger.STORE_ID)
        state_path = folder / 'state.json'
        original = jobs._read(state_path)
        rid = provenance['reservationId']
        cases = []
        unknown = json.loads(json.dumps(original)); unknown['reservations'][rid].update(phase='request'); unknown['reservations'][rid].pop('result')
        cases.append((unknown, 'provider_outcome_unknown'))
        intermediate = json.loads(json.dumps(original)); intermediate['schemaVersion'] = ledger.REUSE_SCHEMA
        intermediate['reuseBudgetRoots'] = [str(self.destination.resolve())]
        intermediate['migration'] = None
        intermediate_provenance = {**provenance, 'budgetRoot': str(self.destination.resolve())}
        intermediate['reservations'][rid]['settlement'] = {'costStatus': 'reused', 'costMicrousd': 0,
            'reusedFrom': intermediate_provenance}
        intermediate['reservations'][rid]['result']['usage'] = dict.fromkeys(ledger.METRICS, 0)
        cases.append((intermediate, 'requires_direct_paid_root'))
        for index, (value, message) in enumerate(cases):
            with self.subTest(index=index):
                jobs._persist(state_path, value)
                with patch.object(destination, 'verify_execution'), self.assertRaisesRegex(ValueError, message):
                    destination.record_reuse('', self.base.payload, response, provenance)
                self.assertFalse(self.destination.exists())
        jobs._persist(state_path, original)
        response_path = source.root / 'responses' / (provenance['inputSha256'] + '.json')
        saved = jobs._read(response_path); saved['response'] = {'forged': True}; jobs._persist(response_path, saved)
        with patch.object(destination, 'verify_execution'), self.assertRaisesRegex(ValueError, 'reconciliation_required'):
            destination.record_reuse('', self.base.payload, response, provenance)
        self.assertFalse(self.destination.exists())

    def test_missing_payload_sidecar_cannot_rebuy_a_known_paid_payload(self):
        source, _, _ = self.paid()
        destination = self.destination_caller(source.root)
        with patch.object(destination, 'verify_execution'), self.assertRaisesRegex(
                ValueError, 'success_receipt_required'):
            destination('', self.base.payload)
        self.assertFalse(self.destination.exists())

    def test_v1_ledger_requires_explicit_migration_before_reuse(self):
        paid, _, _ = self.paid()
        _, paid_folder, _ = jobs._paths(paid.root, ledger.STORE_ID)
        paid_before = jobs._read(paid_folder / 'state.json')['reservations']
        next_authority = json.loads(json.dumps(self.base.auth['value']['authority']))
        next_authority['approvalSha256'] = 'e' * 64
        paid_upgrade = ledger.BudgetStore(paid.root, next_authority,
                                          reuse_roots=[self.destination])
        self.assertEqual(paid_upgrade.migrate_to_v2()['reservations'], 1)
        migrated = jobs._read(paid_folder / 'state.json')
        self.assertEqual(migrated['reservations'], paid_before)
        self.assertEqual(migrated['authority'], next_authority)
        self.assertEqual(migrated['migration']['priorApprovalSha256'],
                         self.base.auth['value']['authority']['approvalSha256'])

        root = self.destination / 'empty'
        old = ledger.BudgetStore(root, self.base.auth['value']['authority'])
        with old._locked():
            pass
        upgraded = ledger.BudgetStore(root, self.base.auth['value']['authority'],
                                      reuse_roots=[self.base.auth['root']])
        with self.assertRaisesRegex(ValueError, 'explicit_migration'):
            with upgraded._locked():
                pass
        self.assertEqual(upgraded.migrate_to_v2()['status'], 'migrated')
        with upgraded._locked() as (_, value):
            self.assertEqual(value['schemaVersion'], ledger.REUSE_SCHEMA)
            self.assertEqual(value['reuseBudgetRoots'], [str(self.base.auth['root'].resolve())])

        _, upgraded_folder, _ = jobs._paths(root, ledger.STORE_ID)
        damaged = jobs._read(upgraded_folder / 'state.json')
        damaged['authority']['approvalSha256'] = '0' * 64
        jobs._persist(upgraded_folder / 'state.json', damaged)
        with self.assertRaisesRegex(ValueError, 'budget_reuse_roots_changed'):
            upgraded.migrate_to_v2()

    def test_damaged_reuse_row_cannot_name_an_unapproved_source(self):
        source, response, provenance = self.paid()
        destination = self.destination_caller(source.root)
        with patch.object(destination, 'verify_execution'):
            destination.record_reuse('', self.base.payload, response, provenance)
        _, folder, _ = jobs._paths(self.destination, ledger.STORE_ID)
        value = jobs._read(folder / 'state.json')
        row = next(iter(value['reservations'].values()))
        row['settlement']['reusedFrom']['budgetRoot'] = str((self.destination / 'unapproved').resolve())
        jobs._persist(folder / 'state.json', value)
        with self.assertRaisesRegex(ValueError, 'budget_reuse_source_not_approved'):
            with destination.store._locked():
                pass

    def test_start_check_requires_migration_and_rejects_intermediate_source(self):
        source, _, provenance = self.paid()
        old = ledger.BudgetStore(self.destination, self.base.auth['value']['authority'])
        with old._locked():
            pass
        with self.assertRaisesRegex(ValueError, 'explicit v2 migration'):
            start_check.inspect_layer2_root(self.destination, self.base.auth['value']['authority'],
                locale_scope=False, reuse_roots=[source.root])
        upgraded = ledger.BudgetStore(self.destination, self.base.auth['value']['authority'],
                                      reuse_roots=[source.root])
        upgraded.migrate_to_v2()
        start_check.inspect_layer2_root(self.destination, self.base.auth['value']['authority'],
            locale_scope=False, reuse_roots=[source.root])
        _, folder, _ = jobs._paths(source.root, ledger.STORE_ID)
        value = jobs._read(folder / 'state.json');rid = provenance['reservationId']
        value.update(schemaVersion=ledger.REUSE_SCHEMA,
                     reuseBudgetRoots=[str(self.destination.resolve())],migration=None)
        value['reservations'][rid]['result']['usage'] = dict.fromkeys(ledger.METRICS, 0)
        intermediate_provenance = {**provenance, 'budgetRoot': str(self.destination.resolve())}
        value['reservations'][rid]['settlement'] = {'costStatus':'reused','costMicrousd':0,
                                                    'reusedFrom':intermediate_provenance}
        jobs._persist(folder / 'state.json', value)
        jobs._persist(folder / (rid+'.result.json'), {'reservationId':rid,
            'result':value['reservations'][rid]['result'],
            'settlement':value['reservations'][rid]['settlement']})
        with self.assertRaisesRegex(ValueError, 'direct paid source root'):
            start_check.inspect_layer2_root(source.root, None, locale_scope=False,
                                            as_reuse_source=True)


if __name__ == '__main__':
    unittest.main()
