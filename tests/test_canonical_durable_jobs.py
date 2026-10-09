"""Actual package validators and durable receipts, without model or publication calls."""
import copy
import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

from scripts import canonical_durable_jobs as subject
from scripts import inspect_canonical_packages as packages
from scripts import sermon_workflow_jobs as jobs
from scripts import target_language_policy as policies
from tests import test_inspect_canonical_packages as fixtures


class CanonicalDurableJobsTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PackageInspectionTests('test_real_source_candidate_validators_inspect_without_approval_or_writes')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.path = self.fixture.path
        self.root = self.fixture.root / 'durable-jobs'
        self.run_id = 'a' * 64
        self.base = packages.inspect(self.path)

    def inspect(self):
        return subject.inspect(self.path, self.root, self.run_id)

    def persist_job(self, status, *, unit='text.zh-Hans', ident=None):
        ident = ident or subject.identity(self.base, self.run_id, unit)
        key = jobs._digest(ident)
        folder = self.root / key
        folder.mkdir(parents=True, exist_ok=True)
        command = [sys.executable, '-c', 'raise SystemExit(0)']
        request = {'schemaVersion': jobs.SCHEMA, 'jobId': key, 'identity': ident,
                   'command': command, 'commandSha256': jobs._digest(command), 'timeoutSeconds': 5.0}
        jobs._persist(folder / 'request.json', request)
        jobs._persist(folder / 'state.json', {'schemaVersion': jobs.SCHEMA, 'jobId': key,
                       'status': status, 'requestSha256': jobs._digest(request)})
        return key

    def files(self):
        return {str(p.relative_to(self.fixture.root)): (p.read_bytes(), p.stat().st_mode, p.stat().st_mtime_ns)
                for p in self.fixture.root.rglob('*') if p.is_file()}

    def test_empty_root_is_not_created_and_shadow_never_launches(self):
        before = self.files()
        with patch.object(jobs, 'start_job') as start:
            view = self.inspect()
        start.assert_not_called()
        self.assertEqual(view['nodes'], self.base['nodes'])
        self.assertFalse(self.root.exists())
        self.assertEqual(before, self.files())
        self.assertFalse(view['dispatchEnabled'])
        self.assertTrue(view['durableJobInspection']['readOnly'])
        self.assertNotIn(str(self.fixture.root), json.dumps(view))

    def test_live_queued_and_running_jobs_block_downstream_without_writing(self):
        for status in ('queued', 'running'):
            key = self.persist_job(status)
            with jobs._lock(self.root, key) as (_, _, held):
                self.assertTrue(held)
                before = self.files()
                view = self.inspect()
                self.assertEqual(before, self.files())
                self.assertEqual(view['nodes']['text.zh-Hans']['status'], 'waiting_job')
                self.assertEqual(view['nodes']['audio.zh-Hans']['status'], 'waiting_dependency')
                self.assertEqual(view['nodes']['page.zh-Hans']['status'], 'waiting_dependency')
                self.assertEqual(view['nodes']['source']['status'], 'validated')

    def test_abandoned_queued_and_running_are_uncertain_without_rewriting_any_evidence(self):
        for status in ('queued', 'running'):
            with self.subTest(status=status):
                key = self.persist_job(status)
                before = self.files()
                view = self.inspect()
                self.assertEqual(before, self.files())
                self.assertFalse((self.root / '.locks').exists())
                self.assertEqual(view['nodes']['text.zh-Hans']['status'], 'reconciliation_required')
                self.assertEqual(view['durableJobInspection']['jobs'][0]['status'], 'uncertain')
                self.assertEqual(jobs._read(self.root / key / 'state.json')['status'], status)

    def test_changed_actual_policy_cannot_abandon_live_job(self):
        key = self.persist_job('queued')
        policy = copy.deepcopy(self.fixture.fixture.policy)
        policy.pop('componentSha256')
        policy['translator']['promptVersion'] += '-new-revision'
        self.fixture.write('policy.json', policies.freeze_policy(policy))
        with jobs._lock(self.root, key):
            view = self.inspect()
        self.assertEqual(view['nodes']['text.zh-Hans']['status'], 'reconciliation_required')
        fresh = packages.inspect(self.path)
        old = subject.identity(self.base, self.run_id, 'text.zh-Hans')
        changed = subject.identity(fresh, self.run_id, 'text.zh-Hans')
        self.assertEqual(old['nodeIdentity'], changed['nodeIdentity'])
        self.assertNotEqual(old['inputIdentitySha256'], changed['inputIdentitySha256'])

    def test_job_success_requires_actual_validated_output_and_cannot_retry_missing_artifact(self):
        self.fixture.config['locales']['zh-Hans'].pop('candidate')
        self.fixture.write('inspection.json', self.fixture.config)
        self.base = packages.inspect(self.path)
        ident = subject.identity(self.base, self.run_id, 'text.zh-Hans')
        command = [sys.executable, '-c', 'pass']
        first = jobs.start_job(self.root, ident, command, 3)
        until = time.monotonic() + 8
        while time.monotonic() < until:
            if jobs.peek_job(self.root, first['jobId'])['status'] == 'succeeded':
                break
            time.sleep(.025)
        self.assertEqual(jobs.peek_job(self.root, first['jobId'])['status'], 'succeeded')
        with patch.object(jobs.subprocess, 'Popen') as spawn:
            self.assertEqual(jobs.start_job(self.root, ident, command, 3)['status'], 'succeeded')
        spawn.assert_not_called()
        view = self.inspect()
        self.assertEqual(view['nodes']['text.zh-Hans']['reasonCode'], 'job_success_without_validated_package')
        self.assertEqual(view['nodes']['audio.zh-Hans']['status'], 'waiting_dependency')
        self.fixture.config['locales']['zh-Hans']['candidate'] = 'candidate.json'
        self.fixture.write('inspection.json', self.fixture.config)
        complete = self.inspect()
        self.assertEqual(complete['nodes']['text.zh-Hans']['status'], 'validated')
        self.assertNotEqual(view['stateRevision'], complete['stateRevision'])

    def test_failed_job_blocks_even_when_preexisting_candidate_is_valid(self):
        self.persist_job('failed')
        view = self.inspect()
        self.assertEqual(view['nodes']['text.zh-Hans']['status'], 'blocked')
        self.assertEqual(view['nodes']['text.zh-Hans']['reasonCode'], 'failed_durable_job')
        self.assertEqual(view['nodes']['audio.zh-Hans']['status'], 'waiting_dependency')

    def test_changed_node_unknown_job_and_corrupt_request_fail_closed(self):
        for field, value in (('nodeIdentity', 'b' * 64), ('productionRunId', 'b' * 64),
                             ('workflowDefinitionVersion', 'future-version'), ('workUnitId', 'text.unknown')):
            with self.subTest(field=field):
                old_root = self.root
                self.root = self.fixture.root / field
                ident = subject.identity(self.base, self.run_id, 'text.zh-Hans')
                ident[field] = value
                self.persist_job('running', ident=ident)
                view = self.inspect()
                self.assertEqual(view['nodes']['text.zh-Hans']['status'], 'reconciliation_required')
                self.root = old_root
        key = self.persist_job('succeeded')
        (self.root / key / 'request.json').write_text('{}')
        view = self.inspect()
        self.assertTrue(view['durableJobInspection']['diagnostics'])
        self.assertTrue(all(n['status'] == 'reconciliation_required' for n in view['nodes'].values()))

    def test_request_drift_and_corrupt_state_never_join_unbound_status(self):
        key = self.persist_job('succeeded')
        request_path = self.root / key / 'request.json'
        original = jobs._read
        count = 0
        def changed(path):
            nonlocal count
            result = original(path)
            if Path(path).resolve() == request_path.resolve():
                count += 1
                if count > 1:
                    result = {**result, 'timeoutSeconds': 7.0}
            return result
        with patch.object(jobs, '_read', side_effect=changed):
            view = self.inspect()
        self.assertTrue(view['durableJobInspection']['diagnostics'])
        self.assertEqual(view['nodes']['text.zh-Hans']['status'], 'reconciliation_required')
        (self.root / key / 'state.json').write_text('{}')
        before = self.files()
        view = self.inspect()
        self.assertEqual(before, self.files())
        self.assertEqual(view['nodes']['text.zh-Hans']['status'], 'reconciliation_required')

    def with_notes(self, digest):
        view = copy.deepcopy(self.base)
        view['packageIdentities']['sourceMeaningNotes'] = digest
        return view

    def reopen(self, key, following, *, name=None):
        folder = self.root / key
        request, state = jobs._read(folder / 'request.json'), jobs._read(folder / 'state.json')
        receipt = {'schemaVersion': subject.REOPEN_SCHEMA, 'jobId': key, 'requestSha256': jobs._digest(request),
                   'stateSha256': jobs._digest(state), 'identity': request['identity'], 'nextIdentity': following,
                   'configurationSha256': 'c' * 64, 'codeIdentitySha256': 'd' * 64,
                   'repairLedgerHeadSha256': 'e' * 64, 'repairLedgerSequence': 2,
                   'meaningNotesSha256': 'f' * 64, 'reopenedGroups': ['g1'], 'resolution': subject.REOPEN_RESOLUTION}
        jobs._persist(folder / (name or subject.reopen_file(following)), receipt)
        return receipt

    def test_a_reopened_failed_job_yields_only_to_the_identity_its_receipt_names(self):
        # Meaning notes are an input of the text job only; the other nodes keep their identities.
        unit = 'text.zh-Hans'
        views = {name: self.with_notes(name * 64) for name in 'bcd'}
        idents = {name: subject.identity(view, self.run_id, unit) for name, view in views.items()}
        idents['a'] = subject.identity(self.base, self.run_id, unit)
        self.assertEqual(len({jobs._digest(value) for value in idents.values()}), 4)
        self.assertEqual(subject.identity(views['b'], self.run_id, 'source'), subject.identity(self.base, self.run_id, 'source'))
        first = self.persist_job('failed', ident=idents['a'])
        node = subject.project(views['b'], self.root, self.run_id)['nodes'][unit]
        self.assertEqual(node['reasonCode'], 'unknown_or_changed_identity_job')
        self.reopen(first, idents['b'])
        view = subject.project(views['b'], self.root, self.run_id)
        self.assertEqual(view['nodes'][unit], self.base['nodes'][unit])
        row = view['durableJobInspection']['jobs'][0]
        self.assertEqual((row['status'], row['originalJobStatus'], row['supersededBy']),
                         ('superseded', 'failed', jobs._digest(idents['b'])))
        # Inputs no receipt named, or the failed job's own identity, block again.
        for name, view_now in (('d', views['d']), ('a', self.base)):
            with self.subTest(expected=name):
                self.assertIn(subject.project(view_now, self.root, self.run_id)['nodes'][unit]['status'],
                              {'reconciliation_required', 'blocked'})
        # The reopened job fails too and is reopened toward newer notes: both yield along the chain.
        second = self.persist_job('failed', ident=idents['b'])
        self.assertEqual(subject.project(views['b'], self.root, self.run_id)['nodes'][unit]['reasonCode'],
                         'failed_durable_job')
        self.reopen(second, idents['c'])
        view = subject.project(views['c'], self.root, self.run_id)
        self.assertEqual(view['nodes'][unit], self.base['nodes'][unit])
        self.assertEqual(sorted(row['status'] for row in view['durableJobInspection']['jobs']), ['superseded'] * 2)
        # Notes that change again before a reopened job starts add a receipt; none is rewritten.
        self.reopen(first, idents['d'])
        self.assertEqual([row['status'] for row in subject.project(views['d'], self.root, self.run_id)
                          ['durableJobInspection']['jobs'] if row['jobId'] == first], ['superseded'])
        # A receipt filed under another identity, or beside a job that did not fail, is unbound evidence.
        self.reopen(first, idents['c'], name=subject.reopen_file(idents['b']).replace('canonical-reopen-', 'x'))
        self.reopen(first, idents['c'], name='canonical-reopen-' + 'f' * 64 + '.json')
        self.assertEqual(subject.project(views['c'], self.root, self.run_id)['durableJobInspection']['diagnostics'],
                         ['unreadable_or_unbound_canonical_job'])

    def test_completed_old_revision_cannot_claim_new_revision_complete(self):
        old = subject.identity(self.base, self.run_id, 'text.zh-Hans')
        old['inputIdentitySha256'] = 'd' * 64
        self.persist_job('succeeded', ident=old)
        self.fixture.config['locales']['zh-Hans'].pop('candidate')
        self.fixture.write('inspection.json', self.fixture.config)
        view = self.inspect()
        self.assertEqual(view['nodes']['text.zh-Hans']['status'], 'ready')
        self.assertEqual(view['nodes']['audio.zh-Hans']['status'], 'waiting_dependency')

    def test_source_job_blocks_every_locale_but_lane_job_preserves_independent_lane(self):
        policy = copy.deepcopy(self.fixture.fixture.policy)
        policy.pop('componentSha256'); policy['targetLocale'] = 'ko'
        self.fixture.write('ko-policy.json', policies.freeze_policy(policy))
        self.fixture.config['locales']['ko'] = {'policy': 'ko-policy.json'}
        self.fixture.write('inspection.json', self.fixture.config)
        self.base = packages.inspect(self.path)
        self.assertEqual(self.base['nodes']['text.ko']['status'], 'ready')
        key = self.persist_job('queued')
        with jobs._lock(self.root, key):
            view = self.inspect()
            self.assertEqual(view['nodes']['text.ko']['status'], 'ready')
            self.assertEqual(view['nodes']['text.zh-Hans']['status'], 'waiting_job')
        self.persist_job('uncertain', unit='source')
        view = self.inspect()
        self.assertEqual(view['nodes']['source']['status'], 'reconciliation_required')
        self.assertEqual(view['nodes']['text.ko']['status'], 'waiting_dependency')

    def test_unrelated_locale_hash_does_not_change_admission_identity(self):
        old = subject.identity(self.base, self.run_id, 'text.zh-Hans')
        changed = copy.deepcopy(self.base)
        changed['packageIdentities'].update({'candidate.ko': 'd'*64, 'audio.ko.package': 'c'*64,
                                             'configuration': 'e'*64})
        self.assertEqual(old, subject.identity(changed, self.run_id, 'text.zh-Hans'))

    def test_symlinks_unknown_entries_and_scan_budget_cannot_disappear_from_view(self):
        self.root.mkdir()
        extra = self.root / 'unexpected'
        extra.write_text('unrecognized intent')
        self.assertTrue(self.inspect()['durableJobInspection']['diagnostics'])
        extra.unlink()
        self.persist_job('succeeded')
        with patch.object(subject, 'MAX_JOBS', 0):
            self.assertTrue(self.inspect()['durableJobInspection']['diagnostics'])
        link = self.fixture.root / 'linked-jobs'
        link.symlink_to(self.root)
        with self.assertRaises(ValueError):
            subject.inspect(self.path, link, self.run_id)


if __name__ == '__main__':
    unittest.main()
