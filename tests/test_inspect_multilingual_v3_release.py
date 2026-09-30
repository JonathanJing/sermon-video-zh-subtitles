"""Read-only local preflight, using the actual v3 candidate assembler."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from scripts import inspect_multilingual_v3_release as subject
from tests import test_assemble_multilingual_v3_update as fixtures


class LocalV3InspectionTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.AssembleMultilingualV3UpdateTests('test_adds_new_week_and_preserves_prior_site_bytes')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.candidate = self.f.root / 'candidate'
        self.report = fixtures.update.assemble(self.f.base, self.f.stage, self.f.manifest, self.candidate)
        self.commit = 'a' * 40
        self.code = patch.object(subject, '_code_snapshot', return_value={'commit': self.commit, 'workingTreeClean': True})
        self.code.start(); self.addCleanup(self.code.stop)

    def inspect(self, **kwargs):
        args = {'expected_commit': self.commit, 'expected_report_sha256': fixtures.update.digest(self.candidate / 'build-report.json'),
                'project': subject.target.PROJECT, 'site': subject.target.SITE}
        args.update(kwargs)
        return subject.inspect(self.candidate, self.f.base, **args)

    def files(self):
        return {str(p.relative_to(self.f.root)): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.f.root.rglob('*') if p.is_file()}

    def rewrite_report(self):
        fixtures.write(self.candidate / 'build-report.json', self.report)

    def test_actual_candidate_is_read_only_and_keeps_all_release_gates_open(self):
        before = self.files()
        with patch.object(subject.subprocess, 'run', side_effect=AssertionError('external action')):
            receipt = self.inspect()
        self.assertEqual(self.files(), before)
        self.assertFalse(receipt['deploymentAllowed'])
        self.assertFalse(receipt['networkAccessed'])
        self.assertEqual(receipt['humanAcceptance'], 'not_evaluated')
        self.assertEqual(receipt['deviceAcceptance'], 'not_run')
        self.assertEqual(receipt['venueAcceptance'], 'not_run')
        self.assertEqual(len(receipt['files']['add']), 21)
        self.assertEqual(receipt['files']['replace'], ['multilingual-v3.json'])
        self.assertIn('app.mjs', receipt['files']['preserve'])
        self.assertEqual(set(receipt['upstreamPackageBindings']), {'zh-Hans', 'ko', 'es'})
        self.assertIn('upstream_human_approval_receipts', receipt['requiredIndependentGates'])
        self.assertNotIn(str(self.f.root), json.dumps(receipt))
        self.assertEqual(receipt, self.inspect())

    def test_wrong_target_stale_code_dirty_checkout_and_selected_report_fail(self):
        for kwargs in ({'project': 'different-project'}, {'site': 'different-site'},
                       {'expected_commit': 'b'*40}, {'expected_report_sha256': 'b'*64}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.inspect(**kwargs)
        with patch.object(subject, '_code_snapshot', return_value={'commit': self.commit, 'workingTreeClean': False}):
            with self.assertRaisesRegex(ValueError, 'code_checkout_changed_or_dirty'):
                self.inspect()

    def test_changed_baseline_reader_is_rejected_even_when_catalog_is_unchanged(self):
        (self.f.base / 'app.mjs').write_bytes(b'new online snapshot reader')
        with self.assertRaisesRegex(ValueError, 'baseline_asset_changed_or_removed'):
            self.inspect()

    def test_manifest_tamper_extra_file_duplicate_unsafe_and_count_rejected(self):
        original = copy.deepcopy(self.report)
        for mutate in (lambda r: r['files'].append(dict(r['files'][0])),
                       lambda r: r['files'][0].update(path='../escape'),
                       lambda r: r['files'][0].update(bytes=True),
                       lambda r: r.update(addedFileCount=20)):
            self.report = copy.deepcopy(original); mutate(self.report); self.rewrite_report()
            with self.subTest(report=self.report['addedFileCount']), self.assertRaises(ValueError):
                self.inspect()
        self.report = original; self.rewrite_report()
        extra = self.candidate / 'public/unlisted.txt'; extra.write_text('unexpected')
        with self.assertRaisesRegex(ValueError, 'candidate_manifest_mismatch'):
            self.inspect()
        extra.unlink()
        (self.candidate / 'unexpected-metadata.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'unlisted_candidate_metadata'):
            self.inspect()

    def test_rollback_and_symlinked_candidate_rejected(self):
        rollback = self.candidate / ('rollback-' + fixtures.update.CATALOG)
        original = rollback.read_bytes(); rollback.write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError, 'baseline_or_rollback_changed'):
            self.inspect()
        rollback.write_bytes(original)
        alias = self.candidate / 'public/alias'; alias.symlink_to(self.f.base / 'app.mjs')
        with self.assertRaises(ValueError):
            self.inspect()

    def test_missing_review_claim_cannot_pass_after_rehashing_candidate(self):
        name = 'releases-v2/new-week/zh-Hans.json'
        release = fixtures.update.load(self.candidate / 'public' / name)
        release['contentStatus'] = 'machine_reviewed'
        sha = fixtures.write(self.candidate / 'public' / name, release)
        catalog_path = self.candidate / 'public' / fixtures.update.CATALOG
        catalog = fixtures.update.load(catalog_path)
        page = next(p for p in catalog['pages'] if p['id'] == 'new-week')
        page['targets']['zh-Hans']['releasePackageJsonSha256'] = sha
        # Keep the selected build report and every file hash coherent. The
        # semantic review requirement must reject this, not a stale hash.
        self.report['newCatalogSha256'] = fixtures.write(catalog_path, catalog)
        for row in self.report['files']:
            if row['path'] in {name, fixtures.update.CATALOG}:
                path = self.candidate / 'public' / row['path']
                row.update(sha256=fixtures.update.digest(path), bytes=path.stat().st_size)
        self.rewrite_report()
        with self.assertRaisesRegex(ValueError, 'Release identity/status mismatch'):
            self.inspect()

    def test_identity_drift_during_validation_never_returns_a_mixed_receipt(self):
        original = fixtures.update.validate_page
        calls = 0
        def mutate(root, page):
            nonlocal calls
            value = original(root, page); calls += 1
            if calls == 3:
                (self.candidate / 'public/app.mjs').write_bytes(b'concurrent replacement')
            return value
        with patch.object(fixtures.update, 'validate_page', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'inspection_inputs_changed'):
                self.inspect()

    def test_code_drift_at_final_check_is_rejected(self):
        with patch.object(subject, '_code_snapshot', side_effect=[
                {'commit': self.commit, 'workingTreeClean': True}, {'commit': 'b'*40, 'workingTreeClean': True}]):
            with self.assertRaisesRegex(ValueError, 'inspection_inputs_changed'):
                self.inspect()

    def test_bucket_profile_requires_bound_local_video_and_correct_hosting_target(self):
        self.f.test_bucket_profile_keeps_video_out_of_hosting()
        self.candidate = self.f.root / 'bucket-candidate'
        self.report = fixtures.update.load(self.candidate / 'build-report.json')
        video = self.f.root / 'video.mp4'
        with self.assertRaisesRegex(ValueError, 'unexpected_candidate_hosting_target'):
            self.inspect(video_file=video)
        config_path = self.candidate / 'firebase.json'
        config = fixtures.update.load(config_path)
        config['hosting']['site'] = subject.target.SITE
        self.report['firebaseConfigSha256'] = fixtures.write(config_path, config)
        self.rewrite_report()
        with self.assertRaisesRegex(ValueError, 'local_bucket_video_required'):
            self.inspect()
        before = self.files()
        receipt = self.inspect(video_file=video)
        self.assertEqual(len(receipt['files']['add']), 20)
        self.assertEqual(receipt['bucketVideo']['sha256'], fixtures.update.digest(video))
        self.assertEqual(before, self.files())
        video.write_bytes(b'changed video')
        with self.assertRaisesRegex(ValueError, 'local_bucket_video_changed'):
            self.inspect(video_file=video)

    def test_cli_checks_actual_git_identity_without_network_or_writes(self):
        # The CLI checks this real checkout. This test is run again on a clean
        # committed head; dirty development trees correctly reject the command.
        self.code.stop()
        try:
            code = subject._code_snapshot()
            expected = code['commit']
            command = [sys.executable, str(Path(subject.__file__).resolve()),
                       '--candidate', str(self.candidate), '--baseline', str(self.f.base),
                       '--expected-commit', expected,
                       '--expected-report-sha256', fixtures.update.digest(self.candidate / 'build-report.json'),
                       '--project', subject.target.PROJECT, '--site', subject.target.SITE]
            before = self.files()
            result = subprocess.run(command, capture_output=True, text=True, timeout=20)
            self.assertEqual(self.files(), before)
            if code['workingTreeClean']:
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(json.loads(result.stdout)['deploymentAllowed'])
            else:
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('code_checkout_changed_or_dirty', result.stderr)
        finally:
            self.code.start()
