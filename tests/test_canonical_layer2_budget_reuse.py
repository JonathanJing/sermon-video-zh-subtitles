import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import canonical_layer2_budget as subject
from scripts import check_run_start as start_check
from scripts import sermon_review_budget as ledger
from scripts import sermon_workflow_jobs as jobs
from tests import test_canonical_layer2_budget as budget_fixtures


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

    def destination_caller(self, source):
        caller = subject.BudgetedCaller(self.base.auth, self.base.config, self.base.source,
                                        self.base.anchor, self.base.policy,
                                        transport=lambda *_: self.fail('reused response dispatched'))
        caller.root = self.destination
        caller.auth = {**caller.auth, 'reuseBudgetRoots': {'zh-Hans': [source]}, 'scope': 'run'}
        caller.store = ledger.BudgetStore(self.destination, self.base.auth['value']['authority'],
                                          reuse_roots=[source])
        return caller

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
