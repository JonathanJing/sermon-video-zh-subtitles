"""The Layer 2 worker's stat-guarded binding memo: unchanged inputs skip the full re-digest,
and every change the full check catches is still caught."""
import dataclasses
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from scripts import canonical_layer2_controller as subject
from scripts import sermon_workflow_jobs as jobs
from tongxing_production.text import backend as text_backend
from tongxing_production.text import controller as layer2
from tongxing_production.text import stat_memo
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


if __name__ == '__main__':
    unittest.main()
