import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock

from scripts import sermon_release_workflow as flow


class ReleaseWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.week = '2026-09-20'
        self.path = self.root / 'config.json'
        self.row = {key: str(self.root / key) for key in flow.PATHS}
        self.row.update(project='sermon-project', site='sermon-listening', origin='https://sermon-listening.web.app')
        self.write(self.row['bridgeConfig'], {'schemaVersion': 'test-bridge'})
        self.save()
        self.plan = {'work': Path(self.row['work']), 'run': self.root / 'source', 'sourceId': 'source123'}
        self.bridge = Mock()
        self.bridge.inspect_bridge.return_value = ({'status': 'ready_to_prepare'}, self.plan)

    def write(self, path, value):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def save(self):
        self.write(self.path, {'schemaVersion': flow.SCHEMA, 'weeks': {self.week: self.row}})

    def test_configuration_rejects_arbitrary_commands_and_nonsunday(self):
        self.row['command'] = ['sh', '-c', 'unsafe']
        self.save()
        with self.assertRaises(ValueError):
            flow.load_config(self.path)
        self.row.pop('command')
        self.save()
        with self.assertRaises(ValueError):
            flow.snapshot(self.path, '2026-09-19')

    def test_deployment_target_cannot_be_unrelated_origin(self):
        self.row['origin'] = 'https://unrelated.example'
        self.save()
        with self.assertRaises(ValueError):
            flow.load_config(self.path)

    def test_overlapping_output_paths_rejected(self):
        self.row['release'] = self.row['candidate'] + '/release'
        self.save()
        with self.assertRaises(ValueError):
            flow.load_config(self.path)

    def test_current_bridge_controls_candidate_and_preserves_source_binding(self):
        with patch.object(flow, '_module', return_value=self.bridge):
            result = flow.snapshot(self.path, self.week)
        self.assertEqual(result['recommendedAction']['action'], 'generate_audio_candidate')
        self.assertFalse(result['humanActionRequired'])
        self.assertEqual(result['evidence']['sourceRunRoot'], str((self.root / 'source').resolve()))
        self.plan['work'] = self.root / 'wrong-source'
        with patch.object(flow, '_module', return_value=self.bridge):
            result = flow.snapshot(self.path, self.week)
        self.assertEqual(result['status'], 'waiting_evidence_repair')

    def test_uncertain_attempt_never_repeats_side_effect(self):
        config = flow.load_config(self.path)
        self.write(Path(self.row['stateDir']) / 'deploy_release.json', {'status': 'running', 'binding': flow._binding(config, self.week, self.row)})
        with patch.object(flow, 'bounded_process') as runner:
            result = flow.snapshot(self.path, self.week)
        self.assertEqual(result['status'], 'waiting_outcome_reconciliation')
        runner.assert_not_called()

    def test_failed_execution_retains_unknown_outcome_receipt(self):
        with patch.object(flow, '_module', return_value=self.bridge), patch.object(flow, 'bounded_process', side_effect=subprocess.TimeoutExpired('candidate', 1)):
            with self.assertRaises(subprocess.TimeoutExpired):
                flow.execute(self.path, self.week, 'generate_audio_candidate')
        receipt = flow.read(Path(self.row['stateDir']) / 'generate_audio_candidate.json')
        self.assertEqual(receipt['status'], 'outcome_unknown')
        with patch.object(flow, 'bounded_process') as runner:
            result = flow.execute(self.path, self.week, 'generate_audio_candidate')
        self.assertFalse(result['executed'])
        runner.assert_not_called()

    def test_zero_exit_without_evidence_is_not_completion(self):
        with patch.object(flow, '_module', return_value=self.bridge), patch.object(flow, 'bounded_process'):
            with self.assertRaisesRegex(ValueError, 'without advancing'):
                flow.execute(self.path, self.week, 'generate_audio_candidate')
        self.assertEqual(flow.read(Path(self.row['stateDir']) / 'generate_audio_candidate.json')['status'], 'outcome_unknown')

    def test_authorization_exact_artifact_and_target_binding(self):
        config = flow.load_config(self.path)
        release = Path(self.row['release'])
        self.write(release / 'build-report.json', {'files': []})
        plan = {'parentReleaseId': 'rel_parent', 'parentGeneration': 3}
        okay, expected = flow._authorization(config, self.week, self.row, {}, plan)
        self.assertFalse(okay)
        self.write(self.row['authorization'], {**expected, 'approvedBy': 'operator', 'approvedAt': '2026-09-19T12:00:00Z'})
        self.assertTrue(flow._authorization(config, self.week, self.row, {}, plan)[0])
        self.write(release / 'build-report.json', {'files': ['changed']})
        self.assertFalse(flow._authorization(config, self.week, self.row, {}, plan)[0])

    def test_cli_config_hash_detects_change_before_dispatch(self):
        with self.assertRaisesRegex(ValueError, 'changed since dispatch'):
            flow.main(['--config', str(self.path), '--sunday', self.week, '--expected-config-sha', '0' * 64])

    def test_command_is_fixed_and_never_preview(self):
        command = flow._command(self.row, self.week, 'build_page')
        self.assertNotIn('--review-preview', command)
        self.assertNotIn('--sync-preview', command)
        self.assertEqual(command[1], str(flow.POC / 'build_weekly_app.py'))
        with self.assertRaises(ValueError):
            flow.execute(self.path, self.week, 'shell')

    def test_release_transitions_require_exact_authorization_http_and_registry(self):
        # Inert release fixtures; audio validators are mocked, release manifests
        # and registry CAS/verification are the real production implementation.
        fixture = flow._module('test_weekly_release')
        releases = flow._module('weekly_release')
        base = fixture.release_fixture(self.root / 'base', [fixture.week('2026-09-13', 'old')])
        candidate = fixture.release_fixture(self.row['candidate'], [fixture.week(self.week, 'source123')])
        releases.bootstrap(Path(self.row['registry']), base, self.row['origin'])
        work = Path(self.row['work'])
        self.write(work / 'job.json', {'week': self.week, 'voice': {'checkpointSha256': 'checkpoint'}})
        self.write(work / 'synchronization/assembly.json', {})
        config = flow.load_config(self.path)
        audio_binding = {'frozen': 'fixture'}
        self.write(Path(self.row['stateDir']) / 'build_page.json', {
            'status': 'succeeded', 'binding': flow._binding(config, self.week, self.row),
            'audioBinding': audio_binding, 'outputSha256': flow.digest(candidate / 'build-report.json')})
        self.bridge.inspect_bridge.return_value = ({'status': 'waiting_conversation_review'}, self.plan)
        def module(name):
            return releases if name == 'weekly_release' else self.bridge
        with patch.object(flow, '_module', side_effect=module), patch.object(flow, '_review', return_value=True), patch.object(flow, '_audio_binding', return_value=audio_binding):
            self.assertEqual(flow.snapshot(self.path, self.week)['status'], 'prepare_release')
            release = Path(self.row['release'])
            releases.prepare(Path(self.row['registry']), candidate, release)
            waiting = flow.snapshot(self.path, self.week)
            self.assertEqual(waiting['status'], 'waiting_release_authorization')
            with patch.object(flow, 'bounded_process') as runner:
                self.assertFalse(flow.execute(self.path, self.week, 'deploy_release')['executed'])
                runner.assert_not_called()
            self.write(self.row['authorization'], {**waiting['evidence']['requiredReleaseAuthorization'], 'approvedBy': 'fixture', 'approvedAt': 'fixture'})
            self.assertEqual(flow.snapshot(self.path, self.week)['status'], 'deploy_release')
            self.write(release / 'deployment-receipt.json', {'status': 'deployed_http_verification_pending',
                'projectId': self.row['project'], 'siteId': self.row['site'], 'buildReportSha256': flow.digest(release / 'build-report.json')})
            self.assertEqual(flow.snapshot(self.path, self.week)['status'], 'verify_release')
            verified = fixture.verification(release)
            verified['origin'] = self.row['origin']
            self.write(release / 'http-verification.json', verified)
            self.assertEqual(flow.snapshot(self.path, self.week)['status'], 'record_published')
            releases.record_published(Path(self.row['registry']), release, verified)
            self.assertEqual(flow.snapshot(self.path, self.week)['status'], 'complete')
            # A prior complete receipt must not hide corruption of live inputs.
            (release / 'public/index.html').write_text('changed')
            self.assertEqual(flow.snapshot(self.path, self.week)['status'], 'waiting_evidence_repair')

    def test_full_review_can_validate_without_writing_receipt(self):
        fixture = flow._module('test_review_integrity')
        weekly = flow._module('weekly_dubbing')
        production = SimpleNamespace(local_completion_artifacts=Mock(return_value=True))
        work = self.root / 'review-fixture'
        work.mkdir()
        fixture.ReviewIntegrityTests().fixture(work)
        with patch.dict('sys.modules', {'scripts.run_codex_local_sermon_production': production}):
            weekly.validate_review(work, write_receipt=False)
        production.local_completion_artifacts.assert_called_once()
        self.assertFalse((work / 'saturday-completion.json').exists())

    def test_symlink_output_and_symlink_log_are_rejected(self):
        redirected = self.root / 'elsewhere'
        redirected.mkdir()
        Path(self.row['candidate']).symlink_to(redirected, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            flow.load_config(self.path)
        Path(self.row['candidate']).unlink()
        state = Path(self.row['stateDir'])
        state.mkdir()
        (state / 'generate_audio_candidate.log').symlink_to(redirected / 'private.txt')
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            flow.execute(self.path, self.week, 'generate_audio_candidate')

    def test_dispatched_source_is_rechecked_inside_execute(self):
        with patch.object(flow, '_module', return_value=self.bridge), patch.object(flow, 'bounded_process') as runner:
            with self.assertRaisesRegex(ValueError, 'source differs'):
                flow.execute(self.path, self.week, 'generate_audio_candidate', expected_source_run_root=self.root / 'different')
        runner.assert_not_called()

    def test_missing_sync_and_missing_or_stale_human_review_never_build(self):
        work = Path(self.row['work'])
        job = {'week': self.week, 'voice': {'checkpointSha256': 'checkpoint'}}
        self.write(work / 'job.json', job)
        self.write(work / 'synchronization/report.json', {'status': 'natural_timing_fits', 'failures': []})
        self.bridge.inspect_bridge.return_value = ({'status': 'waiting_conversation_review'}, self.plan)
        with patch.object(flow, '_module', return_value=self.bridge), patch.object(flow, 'bounded_process') as runner:
            self.assertEqual(flow.snapshot(self.path, self.week)['status'], 'sync_audio')
            self.assertFalse(flow.execute(self.path, self.week, 'build_page')['executed'])
            self.write(work / 'synchronization/assembly.json', {})
            self.assertEqual(flow.snapshot(self.path, self.week)['status'], 'waiting_audio_review')
            audio = work / 'synchronization/zh-synced.mp3'
            audio.write_bytes(b'fixture')
            self.write(work / 'audio-review-synced.json', {'humanApproval': True, 'reviewedBy': 'fixture', 'reviewedAt': 'fixture', 'jobSha256': 'stale'})
            self.assertEqual(flow.snapshot(self.path, self.week)['status'], 'waiting_audio_review')
            self.assertFalse(flow.execute(self.path, self.week, 'build_page')['executed'])
        runner.assert_not_called()


if __name__ == '__main__':
    unittest.main()
