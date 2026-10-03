"""Real local bundle/durable workflow integration over synthetic approved inputs.

No model/publisher/notifier is called. Synthetic receipts are fixture evidence,
never production approvals. Existing App validators/decoders run unmocked.
"""
import asyncio
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from scripts import sermon_app_delivery as app
from scripts import sermon_app_delivery_workflow as workflow
from scripts import sermon_end_to_end as end_to_end
from scripts import sermon_production_supervisor as supervisor
from scripts import sermon_workflow_jobs as jobs
from scripts import run_codex_local_sermon_production as local
from scripts import run_sermon_production_supervisor_agent as agent
from tests import test_sermon_app_delivery as fixtures
from tests import test_run_codex_local_sermon_production as local_fixtures


class AppDeliveryWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.fixture = fixtures.AppDeliveryTests('test_actual_source_arrays_audio_metadata_and_read_only_without_pdf')
        with patch('tempfile.tempdir', str(self.root)):
            self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.client_proof(); self.fixture.approve()
        self.fixture.write('plan.json', self.fixture.plan)
        self.path = self.root / 'app-workflow.json'
        self.configuration = {'schemaVersion': 'sermon-app-delivery-workflow-config-v1',
            'sunday': '2026-10-04', 'plan': self.fixture.root.name + '/plan.json',
            'jobRoot': 'durable-jobs', 'outputDirectory': 'app-bundles'}
        self.path.write_text(json.dumps(self.configuration))
        self.config = workflow.load_configuration(self.path)
        self.supervisor = supervisor.SupervisorConfig(sunday='2026-10-04', state_file='unused',
            work_root=self.root, gcs_bucket=None, app_delivery_config=self.path)
        self.addCleanup(self.wait_for_jobs)

    @contextlib.contextmanager
    def fail_worker_spawn(self, exception):
        original = subprocess.Popen
        def spawn(command, *args, **kwargs):
            if len(command) > 1 and command[1] == str(Path(jobs.__file__).resolve()):
                raise exception
            return original(command, *args, **kwargs)
        with patch.object(jobs.subprocess, 'Popen', side_effect=spawn):
            yield

    def wait_for_jobs(self):
        until = time.monotonic() + 10
        if not self.config.jobs.exists():
            return
        while time.monotonic() < until:
            active = [p for p in self.config.jobs.iterdir() if len(p.name) == 64
                      and jobs.peek_job(self.config.jobs, p.name)['status'] in jobs.ACTIVE]
            if not active:
                return
            time.sleep(.02)
        self.fail('App fixture worker did not terminate')

    def wait(self, key):
        until = time.monotonic() + 15
        while time.monotonic() < until:
            state = jobs.peek_job(self.config.jobs, key)
            if state['status'] not in jobs.ACTIVE:
                return state
            time.sleep(.02)
        self.fail('App fixture durable worker timed out')

    def launch(self):
        result = workflow.start(self.path)
        self.assertTrue(result['dispatched'])
        state = self.wait(result['job']['jobId'])
        self.assertEqual(state['status'], 'succeeded', (self.config.jobs/state['jobId']/'worker.log').read_text())
        return state['jobId']

    def snapshot_files(self, folder):
        return {str(p.relative_to(folder)): app.stage.file_sha(p) for p in folder.rglob('*') if p.is_file()}

    def test_real_bundle_worker_no_pdf_and_restart_uses_verified_completion(self):
        before = self.snapshot_files(self.fixture.root)
        initial = supervisor.production_snapshot(self.supervisor)
        self.assertEqual(initial['recommendedAction']['action'], 'prepare_app_delivery')
        self.assertFalse(initial['workflowComplete'])
        self.assertFalse(self.config.output.exists())
        key = self.launch()
        current = end_to_end.snapshot(self.supervisor, read_only=True)
        self.assertTrue(current['workflowComplete'])
        self.assertEqual(current['bundle']['status'], 'prepared_not_published')
        self.assertEqual(current['completionScope'], 'app_delivery_readiness')
        self.assertEqual(current['pdfAdHoc']['status'], 'not_requested')
        self.assertEqual(current['production']['ios_prod']['publication'], 'not_run')
        bundle = self.config.output/key
        manifest = app.read(bundle/'bundle-manifest.json')
        self.assertGreater(len(manifest['inventory']), 4)
        self.assertEqual(app.read(bundle/'assets'/'frozen-app-plan.json')['pdfAdHoc'], {'status':'not_requested'})
        self.assertTrue((bundle/'assets'/self.fixture.plan['products']['ko']['outline']['artifact']['path']).exists())
        saved = self.snapshot_files(bundle)
        with patch.object(jobs, 'start_job') as launch:
            report = workflow.run(self.path, mode='execute')
        launch.assert_not_called()
        self.assertTrue(report['workflowComplete'])
        self.assertEqual(report['completionLatch']['status'], 'already_prepared')
        self.assertEqual(report['publication'], 'not_run')
        self.assertEqual(self.snapshot_files(bundle), saved)
        self.assertEqual(self.snapshot_files(self.fixture.root), before)

    def test_local_entry_bypasses_legacy_pdf_latch_source_refresh_models_and_notifications(self):
        raw = local_fixtures.RunCodexLocalSermonProductionTest().automation_args(self.root)
        raw.sunday = '2026-10-04'; raw.app_delivery_config = self.path
        args = local.make_agent_args(raw)
        with patch.object(local, 'completed_production_report') as pdf_latch, \
             patch.object(local, 'refresh_source_state') as refresh, \
             patch.object(agent, 'access_secret') as secret, \
             patch.object(agent.Runner, 'run') as model, \
             contextlib.redirect_stdout(io.StringIO()):
            code, report = local.run_local_production(args)
        self.assertEqual(code, 0)
        self.assertEqual(report['workflowScope'], 'app_delivery_readiness')
        self.assertEqual(report['runtimeCodexTurns'], 0)
        self.assertFalse(report['approvalWritten'])
        self.assertEqual(report['notification']['status'], 'not_run')
        pdf_latch.assert_not_called(); refresh.assert_not_called(); secret.assert_not_called(); model.assert_not_called()
        key = report['attempt']['job']['jobId']
        self.assertEqual(self.wait(key)['status'], 'succeeded')
        with contextlib.redirect_stdout(io.StringIO()):
            code, final = local.run_local_production(args)
        self.assertEqual(code, 0); self.assertEqual(final['status'], 'complete')
        self.assertEqual(final['publication'], 'not_run')

    def test_two_actual_supervisor_cli_processes_admit_one_fixed_bundle_job(self):
        command = [sys.executable, '-m', 'scripts.run_codex_local_sermon_production',
            '--app-delivery-config', str(self.path), '--sunday', '2026-10-04',
            '--mode', 'execute', '--out', str(self.root/'first-report.json')]
        second = list(command); second[-1] = str(self.root/'second-report.json')
        children = [subprocess.Popen(argv, cwd=workflow.ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env={**os.environ, 'OPENAI_API_KEY':'', 'PYTHONDONTWRITEBYTECODE':'1'})
            for argv in (command, second)]
        for child in children:
            stdout, stderr = child.communicate(timeout=20)
            self.assertEqual(child.returncode, 0, (stdout, stderr))
        keys = [p.name for p in self.config.jobs.iterdir() if len(p.name)==64]
        self.assertEqual(len(keys), 1)
        self.assertEqual(self.wait(keys[0])['status'], 'succeeded')
        self.assertTrue(workflow.snapshot(self.path)['workflowComplete'])

    def test_pdf_failure_and_repair_do_not_change_bundle_identity_or_restart_job(self):
        key = self.launch()
        original = workflow.snapshot(self.path)
        self.fixture.plan['pdfAdHoc'] = {'status':'available',
            'artifact':{'path':'absent.pdf','sha256':'0'*64},
            'review':{'path':'absent-review.json','sha256':'0'*64}}
        self.fixture.write('plan.json', self.fixture.plan)
        failed = workflow.snapshot(self.path)
        self.assertTrue(failed['workflowComplete']); self.assertEqual(failed['pdfAdHoc']['status'], 'failed')
        self.assertEqual(failed['jobIdentity'], original['jobIdentity'])
        self.fixture.plan['pdfAdHoc'] = {'status':'not_requested'}
        self.fixture.write('plan.json', self.fixture.plan)
        with patch.object(jobs, 'start_job') as start:
            final = workflow.run(self.path, mode='execute')
        start.assert_not_called(); self.assertEqual(final['finalSnapshot']['bundle']['jobId'], key)

    def test_changed_product_rejects_old_capability_and_then_old_app_approval(self):
        key = self.launch()
        products = self.fixture.plan['products']['ko']
        row = products['outline']
        document = app.read(self.fixture.root/row['artifact']['path'])
        document['items'][0]['text'] += ' Revision.'
        row['artifact'] = self.fixture.write('ko-outline.json', document)
        self.fixture.modify_reference(row['review'], lambda receipt: receipt.update(
            artifactSha256=row['artifact']['sha256'], artifactJsonSha256=app.digest(document)))
        self.fixture.freeze()
        with patch.object(jobs, 'start_job') as start:
            with self.assertRaisesRegex(ValueError, 'client_capability_mismatch'):
                workflow.start(self.path)
            self.fixture.client_proof(); self.fixture.write('plan.json', self.fixture.plan)
            with self.assertRaisesRegex(ValueError, 'app_approval_binding_mismatch'):
                workflow.start(self.path)
        start.assert_not_called()
        self.fixture.approve(); self.fixture.write('plan.json', self.fixture.plan)
        revision = self.launch()
        self.assertNotEqual(key, revision)
        self.assertTrue((self.config.output/key/'bundle-manifest.json').exists())

    def test_input_drift_during_copy_preserves_partial_evidence_without_completion(self):
        _, _, _, identity = workflow.observe(self.config)
        original = workflow._copy_verified
        changed = False
        def drift(source, destination, expected):
            nonlocal changed
            original(source, destination, expected)
            if not changed:
                changed = True
                self.fixture.plan['contentRevision'] = 'stale-new-revision'
                self.fixture.write('plan.json', self.fixture.plan)
        with patch.object(workflow, '_copy_verified', side_effect=drift):
            with self.assertRaises(ValueError):
                workflow._prepare(self.config, identity)
        bundle = self.config.output/jobs._digest(identity)
        self.assertTrue((bundle/'prepare-intent.json').exists())
        self.assertFalse((bundle/'bundle-manifest.json').exists())

    def test_failed_spawn_is_not_retried_and_explicit_cli_recovery_keeps_old_evidence(self):
        with self.fail_worker_spawn(OSError('offline spawn failure')):
            launch = workflow.start(self.path)
        key = launch['job']['jobId']
        self.assertEqual(launch['job']['status'], 'failed')
        request = (self.config.jobs/key/'request.json').read_bytes()
        state = (self.config.jobs/key/'state.json').read_bytes()
        with patch.object(jobs, 'start_job') as start:
            self.assertFalse(workflow.start(self.path)['dispatched'])
        start.assert_not_called()
        process = subprocess.run([sys.executable, '-m', 'scripts.sermon_app_delivery_workflow',
            'recover', '--config', str(self.path), '--expected-job', key], cwd=workflow.ROOT,
            capture_output=True, text=True, timeout=20)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout)['status'], 'reconciled_prepared_not_published')
        self.assertEqual((self.config.jobs/key/'request.json').read_bytes(), request)
        self.assertEqual((self.config.jobs/key/'state.json').read_bytes(), state)
        self.assertTrue(workflow.snapshot(self.path)['workflowComplete'])

    def test_partial_asset_recovery_reuses_existing_bytes_and_rejects_tampering(self):
        with self.fail_worker_spawn(OSError('offline failure')):
            launch = workflow.start(self.path)
        key = launch['job']['jobId']
        _, _, inventory, identity = workflow.observe(self.config)
        original = workflow._copy_verified
        count = 0
        def interrupted(source, destination, expected):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError('fixture copy interrupted')
            original(source, destination, expected)
        with patch.object(workflow, '_copy_verified', side_effect=interrupted):
            with self.assertRaises(OSError):
                workflow.recover(self.path, key)
        first = self.config.output/key/'assets'/inventory[0]['path']
        before = first.stat().st_mtime_ns
        workflow.recover(self.path, key)
        self.assertEqual(first.stat().st_mtime_ns, before)
        self.assertTrue(workflow.snapshot(self.path)['workflowComplete'])
        first.write_bytes(b'changed')
        self.assertFalse(workflow.snapshot(self.path)['workflowComplete'])
        with self.assertRaises(ValueError):
            workflow.recover(self.path, key)

    def test_unknown_owner_occupies_capacity_after_new_approved_candidate(self):
        with self.fail_worker_spawn(KeyboardInterrupt('crash after intent')):
            with self.assertRaises(KeyboardInterrupt):
                workflow.start(self.path)
        observed = workflow.snapshot(self.path)
        self.assertEqual(observed['workflowJob']['status'], 'uncertain')
        self.fixture.plan['productionEnvironments']['ios_prod']['appVersion'] = 'new-app'
        self.fixture.approve(); self.fixture.write('plan.json', self.fixture.plan)
        with patch.object(jobs, 'start_job') as start:
            changed = workflow.start(self.path)
        self.assertFalse(changed['dispatched']); start.assert_not_called()
        self.assertEqual(changed['recommendedAction']['action'], 'inspect_app_delivery_job_failure')

    def test_configuration_cannot_hide_unknown_by_moving_job_or_bundle_roots(self):
        with self.fail_worker_spawn(KeyboardInterrupt('crash after intent')):
            with self.assertRaises(KeyboardInterrupt):
                workflow.start(self.path)
        old = workflow.snapshot(self.path)
        self.assertEqual(old['workflowJob']['status'], 'uncertain')
        before = self.snapshot_files(self.config.jobs)
        for field in ('jobRoot', 'outputDirectory', 'sunday'):
            changed = dict(self.configuration)
            changed[field] = '2026-10-11' if field == 'sunday' else 'different-' + field
            self.path.write_text(json.dumps(changed))
            with self.subTest(field=field), patch.object(jobs, 'start_job') as spawn:
                with self.assertRaisesRegex(ValueError, 'app_workflow_route_changed'):
                    workflow.start(self.path)
                spawn.assert_not_called()
        self.path.write_text(json.dumps(self.configuration))
        self.assertEqual(self.snapshot_files(self.config.jobs), before)
        self.assertFalse((self.root/'different-jobRoot').exists())
        self.assertFalse((self.root/'different-outputDirectory').exists())

    def test_one_publication_failure_and_supplied_success_do_not_regenerate_or_publish_bundle(self):
        key = self.launch()
        saved = self.snapshot_files(self.config.output/key)
        evidence = self.fixture.write('publication-fixture.json',
            {'note':'Synthetic observation only; no production publication was executed'})
        for environment, outcome in (('ios_prod', 'pass'), ('firebase_prod', 'fail')):
            observation = {'schemaVersion':'sermon-app-production-observation-v1',
                'environment':environment, 'client':dict(self.fixture.plan['productionEnvironments'][environment]),
                'candidateJsonSha256':app.candidate_identity(self.fixture.plan), 'publication':outcome,
                'deviceAcceptance':'not_run', 'observer':'Synthetic observer',
                'observedAt':'2026-10-03T13:00:00Z', 'evidence':evidence}
            self.fixture.plan['productionRuns'][environment] = self.fixture.write(environment+'.json', observation)
        self.fixture.write('plan.json', self.fixture.plan)
        with patch.object(jobs, 'start_job') as spawn:
            report = workflow.run(self.path, mode='execute')
        spawn.assert_not_called()
        self.assertTrue(report['workflowComplete'])
        self.assertEqual(report['publication'], 'not_run')
        self.assertEqual(report['finalSnapshot']['production']['ios_prod']['publication'], 'pass')
        self.assertEqual(report['finalSnapshot']['production']['firebase_prod']['publication'], 'fail')
        self.assertEqual(report['finalSnapshot']['bundle']['jobId'], key)
        self.assertEqual(self.snapshot_files(self.config.output/key), saved)

    def test_missing_or_stale_optional_publication_does_not_block_prepare_or_reuse(self):
        initial = workflow.snapshot(self.path)
        evidence = self.fixture.write('publication-fixture.json',
            {'note':'Synthetic optional observation; no publication was executed'})
        valid = {'schemaVersion':'sermon-app-production-observation-v1',
            'environment':'firebase_prod', 'client':dict(self.fixture.plan['productionEnvironments']['firebase_prod']),
            'candidateJsonSha256':app.candidate_identity(self.fixture.plan), 'publication':'pass',
            'deviceAcceptance':'not_run', 'observer':'Synthetic observer',
            'observedAt':'2026-10-03T13:00:00Z', 'evidence':evidence}
        self.fixture.plan['productionRuns']['firebase_prod'] = self.fixture.write('valid-publication.json', valid)
        stale = {**valid, 'environment':'ios_prod',
                 'client':dict(self.fixture.plan['productionEnvironments']['ios_prod']),
                 'candidateJsonSha256':'0'*64}
        invalid_references = ({'path':'missing-observation', 'sha256':'0'*64},
                              self.fixture.write('stale-publication.json', stale))
        for reference in invalid_references:
            self.fixture.plan['productionRuns']['ios_prod'] = reference
            self.fixture.write('plan.json', self.fixture.plan)
            before = workflow.snapshot(self.path)
            self.assertEqual(before['jobIdentity'], initial['jobIdentity'])
            self.assertEqual(before['recommendedAction']['action'], workflow.ACTION)
            self.assertEqual(before['production']['ios_prod']['publication'], 'not_run')
            self.assertEqual(before['production']['firebase_prod']['publication'], 'pass')
        key = self.launch()
        saved = self.snapshot_files(self.config.output/key)
        for reference in invalid_references:
            with self.subTest(reference=reference['path']):
                self.fixture.plan['productionRuns']['ios_prod'] = reference
                self.fixture.write('plan.json', self.fixture.plan)
                with patch.object(jobs, 'start_job') as spawn:
                    report = workflow.run(self.path, mode='execute')
                spawn.assert_not_called()
                self.assertTrue(report['workflowComplete'])
                self.assertEqual(report['finalSnapshot']['jobIdentity'], initial['jobIdentity'])
                self.assertEqual(report['finalSnapshot']['bundle']['jobId'], key)
                self.assertEqual(report['publication'], 'not_run')
                self.assertEqual(report['finalSnapshot']['production']['ios_prod']['publication'], 'not_run')
                self.assertEqual(report['finalSnapshot']['production']['firebase_prod']['publication'], 'pass')
                self.assertEqual(self.snapshot_files(self.config.output/key), saved)

    def test_recovery_refuses_active_owner_or_changed_source_and_preserves_legacy_scopes(self):
        _, _, _, identity = workflow.observe(self.config)
        key = jobs._digest(identity)
        with jobs._lock(self.config.jobs,key):
            with self.assertRaisesRegex(ValueError,'app_recovery_job_owner_active'):
                workflow.recover(self.path,key)
        default = supervisor.SupervisorConfig('2026-10-04','unused', gcs_bucket=None)
        self.assertIsNone(default.app_delivery_config)
        incompatible = supervisor.SupervisorConfig('2026-10-04','unused',
            app_delivery_config=self.path,release_workflow_config=self.path)
        with self.assertRaisesRegex(ValueError,'configured separately'):
            supervisor.production_snapshot(incompatible)
        self.configuration['jobRoot'] = self.fixture.root.name+'/jobs'
        self.path.write_text(json.dumps(self.configuration))
        with self.assertRaisesRegex(ValueError,'paths_overlap'):
            workflow.load_configuration(self.path)

    def test_shadow_no_job_bundle_write_and_end_to_end_dispatch_consumes_app_scope(self):
        initial = self.snapshot_files(self.root)
        observed = workflow.run(self.path, mode='shadow')
        self.assertEqual(observed['status'], 'observed')
        self.assertEqual(self.snapshot_files(self.root), initial)
        state = end_to_end.snapshot(self.supervisor)
        result = end_to_end.start_action(self.supervisor, workflow.ACTION,
            expected_state_revision=end_to_end.state_revision(state))
        self.assertTrue(result['dispatched'])
        self.assertEqual(self.wait(result['job']['jobId'])['status'], 'succeeded')

    def test_product_readiness_without_dual_review_never_prepares_delivery(self):
        self.fixture.plan['approvalReceipts'].pop('firebase_dev')
        self.fixture.write('plan.json', self.fixture.plan)
        state = supervisor.production_snapshot(self.supervisor)
        self.assertTrue(state['appProductsReady']); self.assertFalse(state['workflowComplete'])
        self.assertEqual(state['recommendedAction']['action'],'waiting_app_delivery_review')
        with patch.object(jobs,'start_job') as start:
            result = workflow.run(self.path,mode='execute')
        start.assert_not_called(); self.assertEqual(result['status'],'blocked')

    def test_copied_bundle_remains_consumable_when_original_inputs_are_unavailable(self):
        key = self.launch()
        original = self.fixture.root
        hidden = original.with_name(original.name + '-offline')
        original.rename(hidden)
        try:
            process = subprocess.run([sys.executable, '-m', 'scripts.sermon_app_delivery_workflow',
                'inspect-bundle', '--bundle', str(self.config.output/key)], cwd=workflow.ROOT,
                capture_output=True, text=True, timeout=20)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(json.loads(process.stdout)['status'], 'prepared_not_published')
        finally:
            hidden.rename(original)

    def test_extensionless_source_dependency_closure_with_optional_json_hash(self):
        original = self.fixture.root / self.fixture.plan['source']['path']
        target = original.with_name('english-source-package')
        original.rename(target)
        for include_json_hash in (True, False):
            reference = self.fixture.reference(target, is_json=include_json_hash)
            self.fixture.plan['source'] = reference
            self.fixture.approve(); self.fixture.write('plan.json', self.fixture.plan)
            with self.subTest(include_json_hash=include_json_hash):
                inspection, _, inventory, _ = workflow.observe(self.config)
                self.assertEqual(inspection['promotion']['status'], 'eligible_not_published')
                paths = {row['path'] for row in inventory}
                self.assertIn('english-source-package', paths)
                for nested in (self.fixture.source['anchors']['artifact'],
                               self.fixture.source['transcript']['artifact'],
                               self.fixture.source['review']['evidence'],
                               self.fixture.source['evidence']['pipelineSummary']):
                    self.assertIn(str(Path(nested['path']).relative_to(self.fixture.root)), paths)

    def test_extensionless_sha_only_packages_remain_self_contained_without_original_inputs(self):
        # A file suffix and jsonSha256 are not required by the artifact contract.
        source = self.fixture.root / self.fixture.plan['source']['path']
        source.rename(self.fixture.root/'english-source-package')
        self.fixture.plan['source'] = self.fixture.reference(self.fixture.root/'english-source-package', is_json=False)
        audio_ref = self.fixture.plan['products']['ko']['audio']['artifact']
        (self.fixture.root/audio_ref['path']).rename(self.fixture.root/'ko-audio-package')
        self.fixture.plan['products']['ko']['audio']['artifact'] = self.fixture.reference(
            self.fixture.root/'ko-audio-package', is_json=False)
        self.fixture.client_proof()
        for environment in app.TEST_ENVIRONMENTS:
            reference = self.fixture.plan['clientCapabilities']['ko'][environment]
            original = self.fixture.root/reference['path']
            target = original.with_suffix('')
            original.rename(target)
            self.fixture.plan['clientCapabilities']['ko'][environment] = self.fixture.reference(target, is_json=False)
        self.fixture.approve(); self.fixture.write('plan.json', self.fixture.plan)
        before = self.snapshot_files(self.fixture.root)
        key = self.launch()
        bundle = self.config.output/key
        inventory = app.read(bundle/'bundle-manifest.json')['inventory']
        self.assertIn('tone.wav', {row['path'] for row in inventory})
        self.assertIn('client-proof.json', {row['path'] for row in inventory})
        for row in inventory:
            self.assertEqual(app.stage.file_sha(bundle/'assets'/row['path']), before[row['path']])
        self.assertEqual(self.snapshot_files(self.fixture.root), before)
        original = self.fixture.root
        hidden = original.with_name(original.name+'-offline')
        original.rename(hidden)
        try:
            process = subprocess.run([sys.executable, '-m', 'scripts.sermon_app_delivery_workflow',
                'inspect-bundle', '--bundle', str(bundle)], cwd=workflow.ROOT,
                capture_output=True, text=True, timeout=20)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(json.loads(process.stdout)['status'], 'prepared_not_published')
        finally:
            hidden.rename(original)

    def test_opaque_sha_only_evidence_is_not_required_to_be_strict_json(self):
        opaque = self.fixture.root/'opaque-client-evidence'
        examples = (b'NaN', b'1e999', b'{"key":1,"key":2}')
        for raw in examples:
            with self.subTest(raw=raw):
                opaque.write_bytes(raw)
                reference = self.fixture.reference(opaque, is_json=False)
                for kind in ('opaque', 'declared', 'json_suffix', 'opaque'):
                    if kind == 'json_suffix':
                        json_path = opaque.with_suffix('.json')
                        json_path.write_bytes(raw)
                        evidence = self.fixture.reference(json_path, is_json=False)
                    else:
                        evidence = {**reference, **({'jsonSha256':'0'*64} if kind == 'declared' else {})}
                    for environment in app.TEST_ENVIRONMENTS:
                        self.fixture.modify_reference(self.fixture.plan['clientCapabilities']['ko'][environment],
                            lambda receipt: receipt.update(evidence=evidence))
                    self.fixture.approve(); self.fixture.write('plan.json', self.fixture.plan)
                    if kind != 'opaque':
                        with self.assertRaisesRegex(ValueError, 'nonfinite_json_number|duplicate_json_field'):
                            workflow.observe(self.config)
                    else:
                        inspection, _, inventory, _ = workflow.observe(self.config)
                        self.assertEqual(inspection['promotion']['status'], 'eligible_not_published')
                        self.assertIn(reference, inventory)
        key = self.launch()
        self.assertEqual((self.config.output/key/'assets'/opaque.name).read_bytes(), examples[-1])

    def test_recovery_never_treats_available_lock_as_authority_for_live_or_queued_owner(self):
        with self.fail_worker_spawn(OSError('offline spawn failure')):
            launch = workflow.start(self.path)
        key = launch['job']['jobId']
        folder = self.config.jobs/key
        owner = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        try:
            for status in ('queued', 'running', 'failed', 'uncertain'):
                with self.subTest(status=status):
                    jobs._write_state(folder, key, status, workerPid=owner.pid)
                    with self.assertRaises(ValueError):
                        workflow.recover(self.path,key)
                    self.assertFalse((self.config.output/key).exists())
        finally:
            owner.terminate(); owner.wait(timeout=5)
        # Even a dead raw queued/running record needs durable reconciliation.
        jobs._write_state(folder,key,'running',workerPid=owner.pid)
        with self.assertRaises(ValueError):
            workflow.recover(self.path,key)
        self.assertEqual(jobs.inspect_job(self.config.jobs,key)['status'],'uncertain')
        workflow.recover(self.path,key)
        self.assertTrue(workflow.snapshot(self.path)['workflowComplete'])

    def test_directory_ancestry_is_persisted_before_intent_and_copied_plan(self):
        _, _, _, identity = workflow.observe(self.config)
        synced = set()
        sync, persist = jobs._sync_directory_ancestry, jobs._persist
        def remember(path):
            sync(path); synced.add(Path(path))
        def check(path,value):
            if path.name in {'prepare-intent.json','frozen-app-plan.json'}:
                self.assertIn(path.parent,synced)
            persist(path,value)
        with patch.object(jobs,'_sync_directory_ancestry',side_effect=remember), \
             patch.object(jobs,'_persist',side_effect=check):
            prepared = workflow._prepare(self.config,identity)
        self.assertEqual(prepared['status'],'prepared_not_published')

    def test_changed_source_rejects_existing_delivery_evidence(self):
        key = self.launch()
        before = self.snapshot_files(self.config.output/key)
        self.fixture.plan['sourceId'] = 'other-source'
        self.fixture.write('plan.json',self.fixture.plan)
        with patch.object(jobs,'start_job') as start:
            with self.assertRaisesRegex(ValueError,'source_identity_mismatch'):
                workflow.start(self.path)
        start.assert_not_called()
        self.assertEqual(self.snapshot_files(self.config.output/key),before)


if __name__ == '__main__':
    unittest.main()
