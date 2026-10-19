"""Approved direct provenance and operation fences for cross-root reuse."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
from threading import Event
import unittest

from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.source import budget as subject
from tongxing_production.orchestration import jobs
from tests.test_source_budget_reuse import store
from tests.test_source_budget_settlement import BOUNDS, IDENTITY, OPERATION, USAGE, call, ledger


class ReuseFenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.paid, self.middle, self.destination = [self.root / name for name in ('paid', 'middle', 'destination')]

    def test_intermediate_reuse_is_rejected_without_dispatch(self):
        call(store(self.paid))
        call(store(self.middle, reuse=[self.paid]))
        for approved in ([self.middle], [self.paid, self.middle]):
            with self.subTest(approved=approved):
                with self.assertRaisesRegex(ValueError, 'source_reuse_requires_direct_paid_root'):
                    call(store(self.destination, reuse=approved, transport=lambda *args: self.fail('dispatch')))
        # Naming the original paid root directly still permits free reuse.
        self.assertEqual(call(store(self.destination, reuse=[self.paid])), call(store(self.paid)))

    def test_old_transitive_receipt_is_rejected_on_local_replay(self):
        call(store(self.paid))
        call(store(self.middle, reuse=[self.paid]))
        response = next((self.middle / 'responses').iterdir())
        saved = jobs._read(response)
        saved['reusedFrom']['originalSettlement'] = saved['settlement']
        jobs._persist(response, saved)
        value = ledger(self.middle)
        value['requests'][OPERATION]['responseSha256'] = jobs._digest(saved)
        jobs._persist(self.middle / 'source-budget.json', value)
        with self.assertRaisesRegex(ValueError, 'source_reused_provenance_changed'):
            call(store(self.middle, reuse=[self.paid], transport=lambda *args: self.fail('dispatch')))

    def test_legacy_source_cannot_hide_reuse_as_a_paid_response(self):
        call(store(self.paid))
        call(store(self.middle, reuse=[self.paid]))
        value = ledger(self.middle)
        value.update(schemaVersion=subject.LEDGER_V2)
        value.pop('reuseBudgetRoots')
        value['requests'][OPERATION].pop('settlement')
        jobs._persist(self.middle / 'source-budget.json', value)
        with self.assertRaisesRegex(ValueError, 'source_reuse_requires_direct_paid_root'):
            call(store(self.destination, reuse=[self.middle], transport=lambda *args: self.fail('dispatch')))

    def test_cache_miss_fences_source_dispatch_and_preserves_business_files(self):
        # Seed a different operation: the matching source lock does not exist yet.
        source = store(self.paid)
        source.call(operation='judge.' + 'd' * 64, identity=dict(IDENTITY, index=2), bounds=BOUNDS,
                    request=b'fixture', api_key='', content_type='fixture', endpoint='fixture')
        before = {path.relative_to(self.paid): (path.read_bytes(), path.stat().st_mtime_ns)
                  for path in self.paid.rglob('*') if path.is_file()}
        calls = []
        for destination in (self.destination, self.root / 'second-destination'):
            with self.assertRaisesRegex(ValueError, 'source_reuse_operation_missing'):
                call(store(destination, reuse=[self.paid], transport=lambda *args: calls.append('destination')))
        self.assertEqual(calls, [])
        for relative, original in before.items():
            path = self.paid / relative
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), original)
        after = {path.relative_to(self.paid) for path in self.paid.rglob('*') if path.is_file()}
        self.assertEqual(after - set(before), {Path('live-owners') / (jobs._digest(OPERATION) + '.lock')})
        # A later source worker pays once, then both destinations reuse its row.
        result = call(store(self.paid, transport=lambda *args: calls.append('source') or
                            {'model': 'gpt-6.1-sol', 'usage': USAGE}))
        for destination in (self.destination, self.root / 'second-destination'):
            self.assertEqual(call(store(destination, reuse=[self.paid],
                                        transport=lambda *args: self.fail('dispatch'))), result)
        self.assertEqual(calls, ['source'])

    def test_partial_approved_roots_allow_existing_paid_response(self):
        result = call(store(self.paid))
        with store(self.middle)._locked() as (value, path):
            jobs._persist(path, value)
        for roots in ([self.middle, self.paid], [self.paid, self.middle]):
            self.assertEqual(call(store(self.destination, reuse=roots,
                                        transport=lambda *args: self.fail('dispatch'))), result)
            # Each destination freezes its ordered roots, so use a new root.
            self.destination = self.root / 'another-destination'

    def test_changed_source_identity_never_falls_through_to_paid_dispatch(self):
        call(store(self.paid))
        with self.assertRaisesRegex(ValueError, 'source_reuse_identity_changed'):
            store(self.destination, reuse=[self.paid], transport=lambda *args: self.fail('dispatch')).call(
                operation=OPERATION, identity=dict(IDENTITY, index=2), bounds=BOUNDS,
                request=b'fixture', api_key='', content_type='fixture', endpoint='fixture')

    def test_active_source_blocks_destination_then_returned_source_is_reused(self):
        entered, release = Event(), Event()
        calls = []

        def dispatch(*args):
            calls.append('source')
            entered.set()
            if not release.wait(3):
                raise AssertionError('test failed to release fake dispatch')
            return {'model': 'gpt-6.1-sol', 'usage': USAGE}

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(call, store(self.paid, transport=dispatch))
            try:
                self.assertTrue(entered.wait(3))
                with self.assertRaisesRegex(ValueError, 'source_operation_live'):
                    call(store(self.destination, reuse=[self.paid], transport=lambda *args: calls.append('destination')))
            finally:
                release.set()
            result = future.result(timeout=3)
        self.assertEqual(call(store(self.destination, reuse=[self.paid], transport=lambda *args: self.fail('dispatch'))), result)
        self.assertEqual(calls, ['source'])
