"""The Layer 2 worker's stat-guarded binding memo: unchanged inputs skip the full re-digest,
and every change the full check catches is still caught."""
import builtins
import copy
import dataclasses
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from scripts import tongxing_host  # noqa: F401  binds the production package ports
from scripts import inspect_canonical_packages as inspection
from tongxing_production.contracts import schemas as contract_schemas
from tongxing_production.text import backend as text_backend
from tongxing_production.text import controller as layer2
from tongxing_production.text import controller as subject
from tongxing_production.text import policy as policy_tools
from tongxing_production.text import stat_memo
from tests import test_canonical_layer2_controller as controller_fixtures
from tests import test_canonical_layer2_controller_payload_cache as payload_fixtures


def rewrite_same_size(path, old, new):
    """Replace bytes in place without changing the size, then restore atime/mtime."""
    assert len(old) == len(new)
    before = os.stat(path)
    data = path.read_bytes()
    assert old in data, (path, old)
    time.sleep(0.01)  # step past the clock tick that stamped the previous ctime
    path.write_bytes(data.replace(old, new, 1))
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    after = os.stat(path)
    assert (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns)
    assert after.st_ctime_ns != before.st_ctime_ns


def flip_digit(path):
    """A same-size edit of the last digit in the file (a digest or count, not a schema name)."""
    data = path.read_bytes()
    index = max(i for i, c in enumerate(data) if 48 <= c <= 57)
    rewrite_same_size(path, data[:index + 1], data[:index] + (b'1' if data[index:index + 1] == b'0' else b'0'))


class Counting:
    def __init__(self, function):
        self.function, self.calls = function, 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        return self.function(*args, **kwargs)


class StatMemoTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        racy = patch.object(stat_memo, 'RACY_NS', 0)  # fixture files are "old" as soon as they exist
        racy.start()
        self.addCleanup(racy.stop)
        self.memo = stat_memo.StatMemo()
        (self.root / 'a.json').write_text('{"a": 1}')
        (self.root / 'b.json').write_text('{"b": 2}')

    def digest(self):
        return sorted((p.name, p.read_bytes()) for p in self.root.iterdir() if p.is_file())

    def get(self, compute, fingerprint=None):
        return self.memo.get('key', fingerprint or (lambda: stat_memo.listing(self.root)), compute)

    def test_unchanged_inputs_skip_the_recomputation(self):
        compute = Counting(self.digest)
        first = self.get(compute)
        self.assertEqual([self.get(compute) for _ in range(3)], [first] * 3)
        self.assertEqual(compute.calls, 1)
        self.assertEqual((self.memo.hits, self.memo.misses), (3, 1))

    def test_same_size_rewrite_with_restored_mtime_is_detected(self):
        compute = Counting(self.digest)
        self.get(compute)
        rewrite_same_size(self.root / 'a.json', b'1', b'9')
        self.assertIn(('a.json', b'{"a": 9}'), self.get(compute))
        self.assertEqual(compute.calls, 2)

    def test_created_removed_renamed_and_replaced_entries_are_detected(self):
        compute = Counting(self.digest)
        self.get(compute)
        steps = (lambda: (self.root / 'c.json').write_text('{}'),
                 lambda: (self.root / 'c.json').unlink(),
                 lambda: (self.root / 'b.json').rename(self.root / 'd.json'),
                 lambda: os.replace(self._sibling('{"a": 7}'), self.root / 'a.json'))
        for count, step in enumerate(steps, start=2):
            step()
            self.assertEqual(self.get(compute), self.digest())
            self.assertEqual(compute.calls, count)

    def _sibling(self, text):
        path = self.root.parent / (self.root.name + '-replacement')
        path.write_text(text)
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        return path

    def test_recently_changed_inputs_are_never_memoized(self):
        compute = Counting(self.digest)
        with patch.object(stat_memo, 'RACY_NS', 3_600 * 10**9):
            self.get(compute)
            self.get(compute)
        self.assertEqual(compute.calls, 2)

    def test_input_changed_while_computing_is_not_memoized(self):
        def racing():
            value = self.digest()
            (self.root / 'a.json').write_text('{"a": 2}')
            return value
        compute = Counting(racing)
        self.get(compute)
        self.get(Counting(self.digest))
        self.assertEqual(self.memo.misses, 2)

    def test_failure_is_never_memoized(self):
        def failing():
            raise ValueError('invalid')
        for _ in range(2):
            with self.assertRaises(ValueError):
                self.get(failing)
        self.assertEqual(self.memo.misses, 2)

    def test_tree_tracks_matching_files_and_symlinks_only(self):
        nested = self.root / 'pkg' / 'sub'
        nested.mkdir(parents=True)
        (nested / 'm.py').write_text('x = 1\n')
        fingerprint = lambda: stat_memo.tree(self.root / 'pkg', ('.py',))
        compute = Counting(lambda: sorted(str(p) for p in (self.root / 'pkg').rglob('*.py')))
        self.get(compute, fingerprint)
        (nested / 'notes.txt').write_text('ignored')
        (nested / '__pycache__').mkdir()
        self.get(compute, fingerprint)
        self.assertEqual(compute.calls, 1)
        (nested / '__pycache__' / 'new.py').write_text('')
        self.get(compute, fingerprint)
        self.assertEqual(compute.calls, 2)
        os.symlink(nested, self.root / 'pkg' / 'link')
        self.get(compute, fingerprint)
        self.assertEqual(compute.calls, 3)

    def test_missing_path_and_directory_swap_are_detected(self):
        target = self.root / 'dir'
        compute = Counting(lambda: target.is_dir())
        fingerprint = lambda: stat_memo.listing(target)
        self.assertFalse(self.get(compute, fingerprint))
        target.mkdir()
        self.assertTrue(self.get(compute, fingerprint))
        target.rmdir()
        target.write_text('file')
        self.assertFalse(self.get(compute, fingerprint))
        self.assertEqual(compute.calls, 3)


class ControllerBindingMemoTests(unittest.TestCase):
    """The worker's real derivations under the memo, on the v7 payload-cache fixture."""

    def setUp(self):
        self.fixture = payload_fixtures.CanonicalLayer2PayloadCacheTests(
            'test_v7_partial_round_binds_failed_job_round_budget_and_successor_command')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.make_prior()
        self.failed_jobs, self.failed_job_id, self.budget_root = self.fixture.enable_v7_partial_recovery()
        self.path = self.fixture.base.path
        self.memo = stat_memo.StatMemo()
        self.payload = Counting(layer2._payload_cache_snapshot_of)
        self.recovery = Counting(layer2._partial_recovery_snapshot_of)
        for patcher in (patch.object(stat_memo, 'RACY_NS', 0), patch.object(layer2, '_BINDING_MEMO', self.memo),
                        patch.object(layer2, '_payload_cache_snapshot_of', self.payload),
                        patch.object(layer2, '_partial_recovery_snapshot_of', self.recovery)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.baseline = subject.load_configuration(self.path)
        self.assertEqual((self.payload.calls, self.recovery.calls), (1, 1))

    def recomputed(self):
        return self.payload.calls - 1, self.recovery.calls - 1

    def test_unchanged_inputs_reuse_both_snapshots_with_the_same_identity(self):
        for _ in range(3):
            config = subject.load_configuration(self.path)
            self.assertEqual(config.sha256, self.baseline.sha256)
            self.assertEqual(config.payload_cache, self.baseline.payload_cache)
            self.assertEqual(config.partial_recovery, self.baseline.partial_recovery)
        self.assertEqual(self.recomputed(), (0, 0))
        with patch.object(layer2, '_BINDING_MEMO', stat_memo.StatMemo()):
            self.assertEqual(subject.load_configuration(self.path).sha256, self.baseline.sha256)

    def test_configuration_edit_is_detected(self):
        self.fixture.base.config_data['productionRunId'] = 'b' * 64
        self.fixture.base.save_config()
        self.assertNotEqual(subject.load_configuration(self.path).sha256, self.baseline.sha256)

    def test_payload_cache_file_edit_is_detected(self):
        flip_digit(sorted(self.fixture.prior.glob('group-*-astra.raw.json'))[0])
        config = subject.load_configuration(self.path)
        self.assertNotEqual(config.sha256, self.baseline.sha256)
        self.assertNotEqual(config.payload_cache['zh-Hans']['identity'],
                            self.baseline.payload_cache['zh-Hans']['identity'])
        self.assertEqual(self.recomputed(), (1, 1))  # the prior root is also the recovery round

    def test_payload_cache_new_entry_is_detected(self):
        (self.fixture.prior / 'group-9999-astra.started.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'unknown_paid_outcome'):
            subject.load_configuration(self.path)

    def test_recovery_failed_job_and_budget_ledger_edits_are_detected(self):
        state = self.failed_jobs / self.failed_job_id / 'state.json'
        rewrite_same_size(state, b'"returnCode": 1', b'"returnCode": 2')
        config = subject.load_configuration(self.path)
        self.assertNotEqual(config.partial_recovery['zh-Hans']['identity'],
                            self.baseline.partial_recovery['zh-Hans']['identity'])
        self.assertEqual(self.recomputed(), (0, 1))
        ledger = next(self.budget_root.glob('*/state.json'))
        changed = config.sha256
        rewrite_same_size(ledger, b'"contentStatus": "not_assessed"', b'"contentStatus": "not_assessex"')
        with self.assertRaises(ValueError):  # the ledger row no longer validates
            subject.load_configuration(self.path)
        rewrite_same_size(ledger, b'"contentStatus": "not_assessex"', b'"contentStatus": "not_assessed"')
        self.assertEqual(subject.load_configuration(self.path).sha256, changed)

    def test_worker_cache_hits_recheck_through_the_memo_and_still_catch_a_prior_edit(self):
        caller = self.fixture.api_caller(forbidden=True)
        changed = False

        def mutate_prior(_key):
            nonlocal changed
            caller.verifications += 1
            if caller.verifications == 3 and not changed:
                changed = True
                receipt = sorted(self.fixture.prior.glob('*-payload-cache-success.json'))[0]
                flip_digit(receipt)

        caller.verify_execution = mutate_prior
        caller.validate_recovery_source = lambda *_: None
        with patch.object(subject, 'code_identity', return_value='c' * 64), \
                self.fixture.active() as (config, code, key, _):
            hits = self.memo.hits
            with self.assertRaisesRegex(ValueError, 'worker_configuration_or_code_changed'):
                subject.execute(config.path, 'zh-Hans', config.sha256, code, key,
                                caller=caller, api_key='fixture-key',
                                expected_payload_cache=config.payload_cache['zh-Hans']['identity'],
                                expected_partial_recovery=config.partial_recovery['zh-Hans']['identity'])
        self.assertTrue(changed)
        self.assertGreater(self.memo.hits, hits)  # the checks before the edit were memo hits
        self.assertEqual(self.fixture.base.calls, [])

    def test_worker_exact_hit_rederives_each_snapshot_once(self):
        caller = self.fixture.api_caller(forbidden=True)
        caller.validate_recovery_source = lambda *_: None
        with patch.object(subject, 'code_identity', return_value='c' * 64), \
                self.fixture.active() as (config, code, key, _):
            # Files written into the job root by active() are not snapshot inputs.
            before = self.recomputed()
            result = subject.execute(config.path, 'zh-Hans', config.sha256, code, key,
                                     caller=caller, api_key='fixture-key',
                                     expected_payload_cache=config.payload_cache['zh-Hans']['identity'],
                                     expected_partial_recovery=config.partial_recovery['zh-Hans']['identity'])
        self.assertEqual(result['status'], 'machine_review_pass_human_review_pending')
        self.assertEqual(self.recomputed(), before)
        self.assertGreaterEqual(self.memo.hits, 10)


class CodeIdentityMemoTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        for name, text in (('scripts/tool.py', 'A = 1\n'), ('scripts/deep/inner.py', 'B = 2\n'),
                           ('packages/production/src/pkg/mod.py', 'C = 3\n'), ('schemas/s.schema.json', '{}'),
                           ('docs/series-terminology.zh.md', 'terms\n'),
                           ('tools/ops/sermon_unified_preflight.py', 'P = 1\n'), ('tools/ops/run.py', 'R = 1\n')):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        current = text_backend.current()
        bound = dataclasses.replace(current, core=dataclasses.replace(current.core, repo_root=self.root))
        self.compute = Counting(layer2._code_identity_of)
        for patcher in (patch.object(text_backend, '_current', bound), patch.object(stat_memo, 'RACY_NS', 0),
                        patch.object(layer2, '_BINDING_MEMO', stat_memo.StatMemo()),
                        patch.object(layer2, '_code_identity_of', self.compute)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.baseline = layer2.code_identity()

    def test_unchanged_code_is_hashed_once(self):
        self.assertEqual([layer2.code_identity() for _ in range(3)], [self.baseline] * 3)
        self.assertEqual(self.compute.calls, 1)

    def test_every_code_edit_changes_the_identity(self):
        edits = (lambda: rewrite_same_size(self.root / 'scripts/deep/inner.py', b'2', b'9'),
                 lambda: rewrite_same_size(self.root / 'packages/production/src/pkg/mod.py', b'3', b'8'),
                 lambda: (self.root / 'schemas/s.schema.json').write_text('{"x": 1}'),
                 lambda: rewrite_same_size(self.root / 'tools/ops/run.py', b'1', b'2'),
                 lambda: rewrite_same_size(self.root / 'docs/series-terminology.zh.md', b'terms', b'TERMS'),
                 lambda: (self.root / 'packages/production/src/pkg/new.py').write_text(''))
        seen = {self.baseline}
        for edit in edits:
            edit()
            identity = layer2.code_identity()
            self.assertNotIn(identity, seen)
            seen.add(identity)
        self.assertEqual(self.compute.calls, 1 + len(edits))
        with patch.object(layer2, '_BINDING_MEMO', stat_memo.StatMemo()):
            self.assertEqual(layer2.code_identity(), identity)

    def test_removed_file_changes_the_identity(self):
        (self.root / 'scripts/tool.py').unlink()
        self.assertNotEqual(layer2.code_identity(), self.baseline)


class SharedListingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'a.json').write_text('{"a": 1}')
        racy = patch.object(stat_memo, 'RACY_NS', 0)
        racy.start()
        self.addCleanup(racy.stop)
        self.memo = stat_memo.StatMemo()
        self.listings = Counting(stat_memo._listing)
        patcher = patch.object(stat_memo, '_listing', self.listings)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_one_listing_serves_every_check_in_the_block(self):
        fingerprint = lambda: stat_memo.listing(self.root)
        self.memo.get('a', fingerprint, lambda: 1)
        self.memo.get('b', fingerprint, lambda: 2)
        self.listings.calls = 0
        with stat_memo.shared_listings():
            self.assertEqual((self.memo.get('a', fingerprint, lambda: 0), self.memo.get('b', fingerprint, lambda: 0)),
                             (1, 2))
        self.assertEqual(self.listings.calls, 1)
        self.assertEqual(self.memo.get('a', fingerprint, lambda: 0), 1)
        self.assertEqual(self.listings.calls, 2)  # outside the block every check lists

    def test_a_change_while_computing_is_seen_by_the_fresh_recheck(self):
        def racing():
            (self.root / 'a.json').write_text('{"a": 2}')
            return 'stale'
        fingerprint = lambda: stat_memo.listing(self.root)
        with stat_memo.shared_listings():
            self.memo.get('a', fingerprint, racing)
        self.assertNotIn('a', self.memo._entries)  # the recheck listed afresh instead of reusing the block's listing
        self.assertEqual(self.memo.get('a', fingerprint, lambda: 'fresh'), 'fresh')

    def test_keep_false_returns_without_storing(self):
        fingerprint = lambda: stat_memo.listing(self.root)
        for _ in range(2):
            self.assertEqual(self.memo.get('a', fingerprint, lambda: 'failed', keep=lambda value: False), 'failed')
        self.assertEqual(self.memo.misses, 2)

    def test_ancestor_swapped_for_a_symlink_changes_the_fingerprint(self):
        nested = self.root / 'dir'
        nested.mkdir()
        (nested / 'f.json').write_text('{}')
        before = stat_memo.files(nested / 'f.json') + stat_memo.ancestors(nested / 'f.json')
        (nested / 'g.json').write_text('{}')  # a sibling write moves the directory's timestamps only
        self.assertEqual(stat_memo.files(nested / 'f.json') + stat_memo.ancestors(nested / 'f.json'), before)
        nested.rename(self.root / 'moved')
        os.symlink(self.root / 'moved', nested)
        # The file's own lstat is unchanged through the link; only the ancestor's kind shows the swap.
        self.assertEqual(stat_memo.files(nested / 'f.json'), before[:1])
        self.assertNotEqual(stat_memo.files(nested / 'f.json') + stat_memo.ancestors(nested / 'f.json'), before)


class PackageViewMemoTests(unittest.TestCase):
    """package_view's inspection under the memo, on the controller's real source/anchor/policy fixture."""

    def setUp(self):
        self.base = controller_fixtures.CanonicalLayer2ControllerTests('test_default_shadow_is_read_only_and_never_loads_credentials_or_dispatches')
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.memo = stat_memo.StatMemo()
        self.inspections = Counting(inspection.inspect_configuration)
        for patcher in (patch.object(stat_memo, 'RACY_NS', 0), patch.object(layer2, '_BINDING_MEMO', self.memo),
                        patch.object(inspection, 'inspect_configuration', self.inspections)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.config = layer2.load_configuration(self.base.path)
        self.baseline = layer2.package_view(self.config)
        self.assertEqual(self.baseline['nodes']['text.zh-Hans']['status'], 'ready')
        self.assertEqual(self.baseline['inspectionDiagnostics'], {})
        source = self.config.inspection_root / self.config.inspection['source']
        summary, window, aligned, review = layer2._source_names(source)
        root = self.config.inspection_root
        self.inputs = {'source': source, 'anchor': root / self.config.inspection['anchor'],
                       'policy': root / self.config.inspection['locales']['zh-Hans']['policy'],
                       'summary': root / summary, 'window': root / window, 'aligned': root / aligned,
                       'review': root / review}

    def unmemoized(self):
        with patch.object(layer2, '_BINDING_MEMO', stat_memo.StatMemo()):
            return layer2.package_view(layer2.load_configuration(self.base.path))

    def test_unchanged_inputs_inspect_once_with_the_same_view(self):
        views = [layer2.package_view(self.config) for _ in range(3)]
        self.assertEqual(views, [self.baseline] * 3)
        self.assertEqual(self.inspections.calls, 1)
        self.assertEqual(self.unmemoized(), self.baseline)
        views[0]['packageIdentities']['x'] = 'mutated'  # each caller gets its own copy
        self.assertNotIn('x', layer2.package_view(self.config)['packageIdentities'])

    def test_every_input_edit_is_detected(self):
        for name, path in self.inputs.items():
            with self.subTest(input=name):
                original = path.read_bytes()
                flip_digit(path)
                changed = layer2.package_view(self.config)
                self.assertEqual(changed, self.unmemoized())
                self.assertNotEqual(changed, self.baseline)
                path.write_bytes(original)
                self.assertEqual(layer2.package_view(self.config), self.baseline)

    def test_terminology_and_schema_edits_are_detected(self):
        copies = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, copies)
        table, real_table = copies / 'series-terminology.zh.md', policy_tools._series_table()
        shutil.copyfile(real_table, table)
        schemas = copies / 'schemas'
        shutil.copytree(contract_schemas.root(), schemas)
        original_root = contract_schemas.root()
        contract_schemas.configure(schemas)
        self.addCleanup(contract_schemas.configure, original_root)
        current = text_backend.current()
        bound = dataclasses.replace(current, terminology=dataclasses.replace(current.terminology, table_path=lambda: table))
        with patch.object(text_backend, '_current', bound):
            self.memo.clear()
            baseline = layer2.package_view(self.config)
            self.assertEqual(baseline, self.baseline)
            calls = self.inspections.calls
            rewrite_same_size(table, b'|', b'!')
            self.assertNotEqual(layer2.package_view(self.config), baseline)
            shutil.copyfile(real_table, table)
            self.assertEqual(layer2.package_view(self.config), baseline)
            self.assertEqual(layer2.package_view(self.config), baseline)
            self.assertEqual(self.inspections.calls, calls + 2)  # the restored table is memoized again
            source_schema = schemas / 'sermon-english-source-package-v1.schema.json'
            text = source_schema.read_text()
            source_schema.write_text(text.replace('"properties"', '"required": ["notAField"], "properties"', 1))
            self.assertNotEqual(layer2.package_view(self.config), baseline)
            source_schema.write_text(text)
            self.assertEqual(layer2.package_view(self.config), baseline)
            self.assertEqual(self.inspections.calls, calls + 4)

    def test_ancestor_symlink_swap_is_rejected_as_before(self):
        folder = self.inputs['summary'].parent
        moved = folder.with_name(folder.name + '-moved')
        folder.rename(moved)
        os.symlink(moved, folder)
        self.addCleanup(lambda: (folder.unlink(), moved.rename(folder)))
        changed = layer2.package_view(self.config)
        self.assertEqual(changed['inspectionDiagnostics'], {'source': 'source_or_anchor_not_validated'})
        self.assertEqual(changed, self.unmemoized())

    def test_failed_inspection_is_recomputed_every_time(self):
        self.inputs['window'].unlink()
        calls = self.inspections.calls
        for _ in range(2):
            self.assertIn('source', layer2.package_view(self.config)['inspectionDiagnostics'])
        self.assertEqual(self.inspections.calls, calls + 2)

    def test_registered_candidate_appearing_is_validated_without_the_memo(self):
        self.base.output.mkdir(parents=True, exist_ok=True)
        self.base.fixture.write('outputs/zh-Hans/candidate.json', self.base.fixture.candidate)
        calls = self.inspections.calls
        view = layer2.package_view(self.config)
        self.assertEqual(view['nodes']['text.zh-Hans']['status'], 'validated')
        self.assertEqual(view, self.unmemoized())
        layer2.package_view(self.config)
        self.assertEqual(self.inspections.calls, calls + 3)  # never memoized while a candidate exists
        self.assertEqual(self.memo.hits, 0)

    def test_every_path_a_full_inspection_touches_is_in_the_fingerprint(self):
        """Trace stat, lstat, open and listing calls of an unmemoized inspection; each must be covered."""
        effective = copy.deepcopy(self.config.inspection)
        effective['locales']['zh-Hans'].pop('candidate', None)
        digest, files, trees = layer2._inspection_reads(self.config.inspection_root, effective, 'production')
        covered = {path for path, _ in layer2._inspection_fingerprint(files, trees)}
        touched, descriptors = set(), {}

        def traced(function, name):
            def call(path, *args, **kwargs):
                if isinstance(path, int):
                    seen = descriptors.get(path)
                else:
                    seen = os.fspath(path)
                    if kwargs.get('dir_fd') is not None:
                        seen = os.path.join(descriptors[kwargs['dir_fd']], seen)
                if seen is not None:
                    touched.add((name, os.path.abspath(seen)))
                result = function(path, *args, **kwargs)
                if name == 'open' and isinstance(result, int) and isinstance(seen, str):
                    descriptors[result] = os.path.abspath(seen)
                return result
            return call

        inspection.inspect_configuration(self.config.inspection_root, effective)  # warm lazy imports
        patchers = [patch.object(os, name, traced(getattr(os, name), name))
                    for name in ('stat', 'lstat', 'open', 'scandir', 'listdir')]
        patchers += [patch.object(builtins, 'open', traced(builtins.open, 'io_open')),
                     patch.object(io, 'open', traced(io.open, 'io_open'))]
        for patcher in patchers:
            patcher.start()
        try:
            view = self.inspections.function(self.config.inspection_root, effective)
        finally:
            for patcher in reversed(patchers):
                patcher.stop()
        self.assertEqual(view['inspectionDiagnostics'], {})
        self.assertIn(('io_open', str(self.inputs['aligned'])), touched)
        missing = sorted(path for _, path in touched if path not in covered)
        self.assertEqual(missing, [])
        self.assertEqual(digest, layer2.jobs._digest(effective))


class BindingDigestTests(unittest.TestCase):
    def setUp(self):
        fixture = payload_fixtures.CanonicalLayer2PayloadCacheTests(
            'test_v7_partial_round_binds_failed_job_round_budget_and_successor_command')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.make_prior()
        fixture.enable_v7_partial_recovery()
        self.path = fixture.base.path
        for patcher in (patch.object(stat_memo, 'RACY_NS', 0), patch.object(layer2, '_BINDING_MEMO', stat_memo.StatMemo()),
                        patch.object(layer2, '_BINDING_DIGESTS', {})):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_reused_digest_equals_the_full_digest(self):
        captured = []
        original = layer2._binding_digest
        with patch.object(layer2, '_binding_digest', lambda binding: captured.append(binding) or original(binding)):
            first = layer2.load_configuration(self.path).sha256
            second = layer2.load_configuration(self.path).sha256
        self.assertEqual(first, second)
        self.assertEqual(len(layer2._BINDING_DIGESTS), 1)
        self.assertIs(captured[0]['partialRecoverySnapshots']['zh-Hans'],
                      captured[1]['partialRecoverySnapshots']['zh-Hans'])  # the memo's shared snapshot
        for binding in captured:
            self.assertEqual(original(binding), layer2.jobs._digest(binding))
        # An equal snapshot that is another object, or any other changed field, is digested in full.
        copied = dict(captured[0], partialRecoverySnapshots={'zh-Hans': copy.deepcopy(
            captured[0]['partialRecoverySnapshots']['zh-Hans'])})
        self.assertEqual(original(copied), first)
        self.assertEqual(len(layer2._BINDING_DIGESTS), 2)
        snapshot = captured[0]['partialRecoverySnapshots']['zh-Hans']
        altered = dict(captured[0], partialRecoverySnapshots={'zh-Hans': dict(snapshot, sha256='0' * 64)})
        self.assertNotEqual(original(altered), first)
        self.assertEqual(original(altered), layer2.jobs._digest(altered))
        changed = dict(captured[0], plugins={'zh-Hans': '0' * 64})
        self.assertEqual(original(changed), layer2.jobs._digest(changed))
        self.assertNotEqual(original(changed), first)

    def test_one_round_listing_per_load(self):
        listings = Counting(stat_memo._listing)
        layer2.load_configuration(self.path)
        with patch.object(stat_memo, '_listing', listings):
            layer2.load_configuration(self.path)
        # failed job folder, round (shared by payload cache and recovery), budget root, its locks and store
        self.assertEqual(listings.calls, 5)


if __name__ == '__main__':
    unittest.main()
