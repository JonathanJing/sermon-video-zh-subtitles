from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from tongxing_production.observability import accounting
from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.observability import completion
from tongxing_production.observability import profile
from tongxing_production.review import contracts as c
from tongxing_production.source import producer_compatibility as compatibility
from tests.test_accounting_log_contract import fixture


def completion_fixture(*, synthetic):
    """In-memory schema-valid facts; no worker, provider or durable writes."""
    events = [fixture('stage-start'), fixture('stage-finish')]
    for row in events:
        row.update(productionRunId='a' * 64, stage='diagnostic.source_model',
            workUnitId='source.initial', dependsOn=['transcription-span'],
            evidenceMode='synthetic' if synthetic else 'current_execution')
        if synthetic:
            row.update(jobId='job', revisionId='revision')
    end = events[-1]
    end['artifactSha256'] = 'b' * 64
    handle = {key: end[key] for key in ('runId', 'traceId', 'spanId', 'stage',
        'workUnitId', 'attemptId', 'status', 'dependsOn', 'productionRunId')}
    handle.update(schemaVersion=completion.SYNTHETIC_SCHEMA if synthetic else completion.SCHEMA,
        terminalEventId=end['eventId'], terminalFactSha256=completion.log.fact_hash(end),
        artifactSha256='b' * 64, artifactKind='control_receipt' if synthetic else 'provider_receipt',
        executionMode='synthetic' if synthetic else 'current_execution')
    if synthetic:
        handle.update(evidenceMode='synthetic', jobId='job', revisionId='revision')
    return handle, events


class CompletionTests(unittest.TestCase):
    def test_generic_validation_requires_production_schema(self):
        handle, events = completion_fixture(synthetic=True)
        self.assertEqual(completion.log.replay_integrity(events)['status'], 'consistent')
        with self.assertRaisesRegex(c.ContractError, '^completion_binding_invalid$'):
            completion.validate(handle, events, production_run_id='a' * 64,
                stage='diagnostic.source_model', artifact_sha256='b' * 64,
                dependencies=['transcription-span'])

    def test_synthetic_validation_is_explicit_and_keeps_bindings(self):
        handle, events = completion_fixture(synthetic=True)
        arguments = dict(production_run_id='a' * 64, job_id='job', revision_id='revision',
            stage='diagnostic.source_model', artifact_sha256='b' * 64,
            dependencies=['transcription-span'])
        checked = completion.validate_synthetic(handle, events + events, **arguments)
        self.assertEqual(checked, handle)
        self.assertIsNot(checked, handle)
        for key, value in [('production_run_id', 'f' * 64), ('job_id', 'other'),
                ('revision_id', 'other'), ('stage', 'other'), ('artifact_sha256', 'f' * 64),
                ('dependencies', [])]:
            with self.subTest(key=key), self.assertRaises(c.ContractError):
                completion.validate_synthetic(handle, events, **{**arguments, key: value})
        production, production_events = completion_fixture(synthetic=False)
        self.assertEqual(completion.validate(production, production_events,
            production_run_id='a' * 64), production)
        with self.assertRaisesRegex(c.ContractError, '^completion_synthetic_version_required$'):
            completion.validate_synthetic(production, production_events, production_run_id='a' * 64)

    def test_source_predecessor_requires_production_completion(self):
        from tongxing_production.workflows.diagnostic import fresh_source as source

        # Isolate the real Source predecessor gate using in-memory upstream
        # inputs. Stop immediately after it, before alignment or output writes.
        with tempfile.TemporaryDirectory() as directory:
            # Resolve like _safe_path does (macOS /var -> /private/var).
            root = Path(directory).resolve()
            config = dict(runId='a' * 64, sourceAudioSha256='c' * 64,
                sourceMediaSha256='d' * 64, sourceClipSha256='e' * 64,
                sourceWindowSeconds=[0, 1], totalWallSeconds=60)
            plan = dict(providerConfig=config, runDirectory=str(root))
            subject = SimpleNamespace(config=config, store=SimpleNamespace(root=root/'budget'),
                _locked=lambda: nullcontext((None, {'startedMonotonic': 0})),
                _remaining=lambda state: None, source_check_payload=lambda: {})
            aligned = [{'text': 'Fixture source.'}]
            aligned_raw = c.canonical_bytes(aligned)
            summary = {}
            summary_raw = c.canonical_bytes(summary)
            prior_source = {'transcript': {'artifact': {'sha256': c.bytes_sha256(aligned_raw),
                'jsonSha256': c.canonical_sha256(aligned)}},
                'source': {'media': {'sha256': config['sourceMediaSha256']},
                    'approvedWindow': {'startSeconds': 0, 'endSeconds': 1}},
                'evidence': {'pipelineSummary': {'sha256': c.bytes_sha256(summary_raw)}}}
            asr = {'response': {'text': 'Fixture source.'}}
            review = {'payloadSha256': c.canonical_sha256({}),
                'response': {'choices': [{'finish_reason': 'stop', 'message': {'content': '{}'}}]}}
            for synthetic in (True, False):
                handle, events = completion_fixture(synthetic=synthetic)
                with self.subTest(synthetic=synthetic), \
                        patch.object(source, '_sha', return_value=config['sourceAudioSha256']), \
                        patch.object(source, 'returned_receipt', side_effect=[(asr, {}),
                            (review, {'receiptSha256': 'b' * 64}), (asr, {})]), \
                        patch.object(source, '_read', side_effect=[(plan, b''),
                            (prior_source, b''), (summary, summary_raw)]), \
                        patch.object(source, '_read_alignment', return_value=(aligned, aligned_raw)), \
                        patch.object(completion, 'current_events', return_value=(None, events)), \
                        patch.object(source.immutable, 'save_once',
                            side_effect=RuntimeError('source_predecessor_accepted')) as save, \
                        patch.object(source.mfa_backend, 'align_reference_chunks') as align, \
                        patch('urllib.request.OpenerDirector.open',
                            side_effect=AssertionError('network forbidden')) as network:
                    error = c.ContractError if synthetic else RuntimeError
                    code = 'completion_binding_invalid' if synthetic else 'source_predecessor_accepted'
                    with self.assertRaisesRegex(error, '^' + code + '$'):
                        source.prepare_source(plan, subject, prior_plan_path=root/'plan.json',
                            prior_source_path=root/'source.json', prior_aligned_path=root/'aligned.json',
                            prior_summary_path=root/'summary.json', audio_path=root/'audio.wav',
                            authorization={'productionEligible': False,
                                'humanReviewMode': 'default_pass_for_isolated_test_only'},
                            source_completions={'intake': {},
                                'transcription': {'spanId': 'transcription-span'}, 'sourceCheck': handle})
                    if synthetic:
                        save.assert_not_called()
                    else:
                        save.assert_called_once()
                    align.assert_not_called()
                    network.assert_not_called()

    def test_terminal_leaf_only_and_equivalent_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            with profile.session(Path(directory)/'logs','completion',work_kind='engineering',evidence_mode='synthetic',production_run_id='a'*64):
                with accounting.stage('parent',depends_on=[],work_unit_id='parent') as parent:
                    with accounting.stage('child',depends_on=[],work_unit_id='child') as child: pass
                handle=completion.capture(child,production_run_id='a'*64,artifact_sha256='b'*64,
                    artifact_kind='frozen_recipe')
                with self.assertRaisesRegex(c.ContractError,'container_forbidden'):
                    completion.capture(parent,production_run_id='a'*64,artifact_sha256='b'*64,
                        artifact_kind='frozen_recipe')
                _,events=completion.current_events()
                completion.validate(handle,events+events,production_run_id='a'*64)
                for key,value in [('attemptId','wrong'),('productionRunId','f'*64),('artifactSha256','f'*64)]:
                    bad=deepcopy(handle);bad[key]=value
                    with self.subTest(key=key),self.assertRaises(c.ContractError):
                        completion.validate(bad,events,production_run_id='a'*64,artifact_sha256='b'*64)

    def test_exact_reviewed_migration_only(self):
        binding={key:'a'*64 for key in ('parentPlanSha256','newPlanSha256','sourceCanonicalSha256',
            'anchorCanonicalSha256','alignmentBytesSha256','asrReceiptSha256','sourceCheckReceiptSha256')}
        current=compatibility.FOLLOWUP_SOURCE_SHA256
        repository=Path(__file__).resolve().parents[1]
        # The fresh producer changed again in v11 (D window); v3's current side is v11's historical side.
        self.assertEqual(compatibility.EXTRACTION_SOURCE_SHA256['scripts/sermon_fresh_diagnostic_source.py'],
            compatibility.FACADE_REMOVAL_HISTORICAL_SHA256['scripts/sermon_fresh_diagnostic_source.py'])
        latest=compatibility.TRANSPORT_MOVE_SOURCE_SHA256
        for path in {*compatibility.MOVE_CHANGED,*compatibility.PRODUCER_MOVE_CHANGED,*compatibility.TRANSPORT_MOVE_CHANGED}:
            self.assertEqual(latest[path],c.bytes_sha256((repository/compatibility.resolve(path)).read_bytes()))
        moved=compatibility.verify(compatibility.EXTRACTION_SOURCE_SHA256,compatibility.MOVE_SOURCE_SHA256,
            {compatibility.resolve(path):sha for path,sha in compatibility.MOVE_SOURCE_SHA256.items()},binding)
        self.assertEqual(moved['migrationId'],compatibility.MOVE_MIGRATION)
        self.assertEqual(moved['changedModules'],compatibility.MOVE_CHANGED)
        self.assertFalse(moved['productionEligible'])
        for before,after,migration,changed in (
                (compatibility.MOVE_SOURCE_SHA256,compatibility.PRODUCER_MOVE_SOURCE_SHA256,
                 compatibility.PRODUCER_MOVE_MIGRATION,compatibility.PRODUCER_MOVE_CHANGED),
                (compatibility.PRODUCER_MOVE_SOURCE_SHA256,latest,
                 compatibility.TRANSPORT_MOVE_MIGRATION,compatibility.TRANSPORT_MOVE_CHANGED)):
            step=compatibility.verify(before,after,
                {compatibility.resolve(path):sha for path,sha in after.items()},binding)
            self.assertEqual(step['migrationId'],migration)
            self.assertEqual(step['changedModules'],changed)
            self.assertEqual(step['newMFACalls'],0)
        for skipped in (compatibility.EXTRACTION_SOURCE_SHA256,compatibility.MOVE_SOURCE_SHA256):
            with self.assertRaises(c.ContractError):
                compatibility.verify(skipped,latest,latest,binding)
        with self.assertRaises(c.ContractError):
            compatibility.verify(compatibility.FOLLOWUP_SOURCE_SHA256,compatibility.MOVE_SOURCE_SHA256,
                compatibility.MOVE_SOURCE_SHA256,binding)
        extracted=compatibility.verify(current,compatibility.EXTRACTION_SOURCE_SHA256,
            compatibility.EXTRACTION_SOURCE_SHA256,binding)
        self.assertEqual(extracted['migrationId'],compatibility.EXTRACTION_MIGRATION)
        self.assertFalse(extracted['productionEligible'])
        self.assertEqual(extracted['newASRCalls'],0)
        with self.assertRaises(c.ContractError):
            compatibility.verify(compatibility.CURRENT_SOURCE_SHA256,compatibility.EXTRACTION_SOURCE_SHA256,
                compatibility.EXTRACTION_SOURCE_SHA256,binding)
        accepted=compatibility.verify(compatibility.CURRENT_SOURCE_SHA256,current,current,binding)
        self.assertEqual(accepted['migrationId'],compatibility.FOLLOWUP_MIGRATION)
        changed=dict(current);changed['scripts/mfa_alignment.py']='f'*64
        with self.assertRaises(c.ContractError):compatibility.verify(compatibility.CURRENT_SOURCE_SHA256,changed,changed,binding)
        with self.assertRaises(c.ContractError):compatibility.verify(compatibility.HISTORICAL_SOURCE_SHA256,current,current,binding)

    def test_contracts_split_generation_covers_only_the_split_file(self):
        binding={key:'a'*64 for key in ('parentPlanSha256','newPlanSha256','sourceCanonicalSha256',
            'anchorCanonicalSha256','alignmentBytesSha256','asrReceiptSha256','sourceCheckReceiptSha256')}
        repository=Path(__file__).resolve().parents[1]
        before,after=compatibility.CONTRACTS_SPLIT_HISTORICAL_SHA256,compatibility.CONTRACTS_SPLIT_SOURCE_SHA256
        for path in compatibility.CONTRACTS_SPLIT_CHANGED:
            self.assertEqual(after[path],c.bytes_sha256((repository/compatibility.resolve(path)).read_bytes()))
        self.assertEqual({path for path in after if after[path]!=before[path]},set(compatibility.CONTRACTS_SPLIT_CHANGED))
        planned={compatibility.resolve(path):sha for path,sha in after.items()}
        planned.update(compatibility.CONTRACTS_SPLIT_MEMBER_SHA256)
        step=compatibility.verify(before,after,planned,binding)
        self.assertEqual(step['migrationId'],compatibility.CONTRACTS_SPLIT_MIGRATION)
        self.assertEqual(step['changedModules'],compatibility.CONTRACTS_SPLIT_CHANGED)
        self.assertEqual(step['acceptedScope'],'read_only_original_source_under_package_move_no_new_inference')
        self.assertEqual((step['newASRCalls'],step['newMFACalls'],step['productionEligible']),(0,0,False))
        for member in compatibility.CONTRACTS_SPLIT_MEMBER_SHA256:
            changed_members=dict(planned);changed_members[member]='f'*64
            with self.assertRaises(c.ContractError):
                compatibility.verify(before,after,changed_members,binding)
        # The pre-I1 drift itself is not a reviewed step: only the exact pair is accepted.
        for skipped in (compatibility.TRANSPORT_MOVE_SOURCE_SHA256,):
            with self.assertRaises(c.ContractError):
                compatibility.verify(skipped,after,after,binding)
        with self.assertRaises(c.ContractError):
            compatibility.verify(compatibility.TRANSPORT_MOVE_SOURCE_SHA256,before,before,binding)


    def test_storage_move_generation_covers_only_the_moved_snapshot(self):
        binding={key:'a'*64 for key in ('parentPlanSha256','newPlanSha256','sourceCanonicalSha256',
            'anchorCanonicalSha256','alignmentBytesSha256','asrReceiptSha256','sourceCheckReceiptSha256')}
        repository=Path(__file__).resolve().parents[1]
        before,after=compatibility.STORAGE_MOVE_HISTORICAL_SHA256,compatibility.STORAGE_MOVE_SOURCE_SHA256
        # The snapshot changed again in v10 (G1); v8's current side is v10's historical side.
        for path in compatibility.STORAGE_MOVE_CHANGED:
            self.assertEqual(after[path],compatibility.JOBS_SPLIT_HISTORICAL_SHA256[path])
        for member,sha in compatibility.STORAGE_MOVE_MEMBER_SHA256.items():
            self.assertEqual(sha,c.bytes_sha256((repository/member).read_bytes()))
        self.assertEqual({path for path in after if after[path]!=before[path]},set(compatibility.STORAGE_MOVE_CHANGED))
        planned={compatibility.resolve(path):sha for path,sha in after.items()}
        planned.update(compatibility.STORAGE_MOVE_MEMBER_SHA256)
        step=compatibility.verify(before,after,planned,binding)
        self.assertEqual(step['migrationId'],compatibility.STORAGE_MOVE_MIGRATION)
        self.assertEqual(step['changedModules'],compatibility.STORAGE_MOVE_CHANGED)
        self.assertEqual(step['acceptedScope'],'read_only_original_source_under_package_move_no_new_inference')
        self.assertEqual((step['newASRCalls'],step['newMFACalls'],step['productionEligible']),(0,0,False))
        for member in compatibility.STORAGE_MOVE_MEMBER_SHA256:
            changed_members=dict(planned);changed_members[member]='f'*64
            with self.assertRaises(c.ContractError):
                compatibility.verify(before,after,changed_members,binding)
        # Generations do not compose: a pre-I1 parent cannot jump straight to the I2 checkout.
        with self.assertRaises(c.ContractError):
            compatibility.verify(compatibility.CONTRACTS_SPLIT_HISTORICAL_SHA256,after,planned,binding)

    def test_measure_move_generation_covers_only_the_moved_measure(self):
        binding={key:'a'*64 for key in ('parentPlanSha256','newPlanSha256','sourceCanonicalSha256',
            'anchorCanonicalSha256','alignmentBytesSha256','asrReceiptSha256','sourceCheckReceiptSha256')}
        repository=Path(__file__).resolve().parents[1]
        before,after=compatibility.MEASURE_MOVE_HISTORICAL_SHA256,compatibility.MEASURE_MOVE_SOURCE_SHA256
        for path in compatibility.MEASURE_MOVE_CHANGED:
            self.assertEqual(after[path],c.bytes_sha256((repository/compatibility.resolve(path)).read_bytes()))
        self.assertEqual({path for path in after if after[path]!=before[path]},set(compatibility.MEASURE_MOVE_CHANGED))
        planned={compatibility.resolve(path):sha for path,sha in after.items()}
        step=compatibility.verify(before,after,planned,binding)
        self.assertEqual(step['migrationId'],compatibility.MEASURE_MOVE_MIGRATION)
        self.assertEqual(step['changedModules'],compatibility.MEASURE_MOVE_CHANGED)
        self.assertEqual(step['acceptedScope'],'read_only_original_source_under_package_move_no_new_inference')
        self.assertEqual((step['newASRCalls'],step['newMFACalls'],step['productionEligible']),(0,0,False))
        # Generations do not compose: a v7-era parent cannot jump straight to the I4 checkout.
        with self.assertRaises(c.ContractError):
            compatibility.verify(compatibility.STORAGE_MOVE_HISTORICAL_SHA256,after,planned,binding)

    def test_jobs_split_generation_covers_only_the_snapshot_import_change(self):
        binding={key:'a'*64 for key in ('parentPlanSha256','newPlanSha256','sourceCanonicalSha256',
            'anchorCanonicalSha256','alignmentBytesSha256','asrReceiptSha256','sourceCheckReceiptSha256')}
        repository=Path(__file__).resolve().parents[1]
        before,after=compatibility.JOBS_SPLIT_HISTORICAL_SHA256,compatibility.JOBS_SPLIT_SOURCE_SHA256
        for path in compatibility.JOBS_SPLIT_CHANGED:
            self.assertEqual(after[path],c.bytes_sha256((repository/compatibility.resolve(path)).read_bytes()))
        for member,sha in compatibility.JOBS_SPLIT_MEMBER_SHA256.items():
            self.assertEqual(sha,c.bytes_sha256((repository/member).read_bytes()))
        self.assertEqual({path for path in after if after[path]!=before[path]},set(compatibility.JOBS_SPLIT_CHANGED))
        planned={compatibility.resolve(path):sha for path,sha in after.items()}
        planned.update(compatibility.JOBS_SPLIT_MEMBER_SHA256)
        step=compatibility.verify(before,after,planned,binding)
        self.assertEqual(step['migrationId'],compatibility.JOBS_SPLIT_MIGRATION)
        self.assertEqual(step['acceptedScope'],'read_only_original_source_under_package_move_no_new_inference')
        for member in compatibility.JOBS_SPLIT_MEMBER_SHA256:
            changed_members=dict(planned);changed_members[member]='f'*64
            with self.assertRaises(c.ContractError):
                compatibility.verify(before,after,changed_members,binding)

    def test_facade_removal_generation_covers_only_the_two_anchor_imports(self):
        binding={key:'a'*64 for key in ('parentPlanSha256','newPlanSha256','sourceCanonicalSha256',
            'anchorCanonicalSha256','alignmentBytesSha256','asrReceiptSha256','sourceCheckReceiptSha256')}
        repository=Path(__file__).resolve().parents[1]
        before,after=compatibility.FACADE_REMOVAL_HISTORICAL_SHA256,compatibility.FACADE_REMOVAL_SOURCE_SHA256
        # The two producers changed again in v12 (C batches); v11's current side is v12's historical side.
        self.assertEqual(after,compatibility.C_FACADE_REMOVAL_HISTORICAL_SHA256)
        self.assertEqual({path for path in after if after[path]!=before[path]},set(compatibility.FACADE_REMOVAL_CHANGED))
        planned={compatibility.resolve(path):sha for path,sha in after.items()}
        step=compatibility.verify(before,after,planned,binding)
        self.assertEqual(step['migrationId'],compatibility.FACADE_REMOVAL_MIGRATION)
        self.assertEqual(step['changedModules'],compatibility.FACADE_REMOVAL_CHANGED)
        self.assertEqual(step['acceptedScope'],'read_only_original_source_under_package_move_no_new_inference')
        self.assertEqual((step['newASRCalls'],step['newMFACalls'],step['productionEligible']),(0,0,False))
        # Generations do not compose: a v9 parent cannot jump straight to the D-window checkout.
        with self.assertRaises(c.ContractError):
            compatibility.verify(compatibility.JOBS_SPLIT_HISTORICAL_SHA256,after,planned,binding)

    def test_c_batch_generation_covers_only_the_two_producer_imports(self):
        binding={key:'a'*64 for key in ('parentPlanSha256','newPlanSha256','sourceCanonicalSha256',
            'anchorCanonicalSha256','alignmentBytesSha256','asrReceiptSha256','sourceCheckReceiptSha256')}
        repository=Path(__file__).resolve().parents[1]
        before,after=compatibility.C_FACADE_REMOVAL_HISTORICAL_SHA256,compatibility.C_FACADE_REMOVAL_SOURCE_SHA256
        # The two producers moved in v13 (D-5 window); v12's current side is v13's historical side.
        self.assertEqual(after,compatibility.D5_MOVE_HISTORICAL_SHA256)
        self.assertEqual({path for path in after if after[path]!=before[path]},set(compatibility.C_FACADE_REMOVAL_CHANGED))
        planned={compatibility.resolve(path):sha for path,sha in after.items()}
        step=compatibility.verify(before,after,planned,binding)
        self.assertEqual(step['migrationId'],compatibility.C_FACADE_REMOVAL_MIGRATION)
        self.assertEqual(step['changedModules'],compatibility.C_FACADE_REMOVAL_CHANGED)
        self.assertEqual(step['acceptedScope'],'read_only_original_source_under_package_move_no_new_inference')
        self.assertEqual((step['newASRCalls'],step['newMFACalls'],step['productionEligible']),(0,0,False))
        # Generations do not compose: a v10 parent cannot jump straight to the C-batch checkout.
        with self.assertRaises(c.ContractError):
            compatibility.verify(compatibility.FACADE_REMOVAL_HISTORICAL_SHA256,after,planned,binding)

    def test_d5_generation_covers_only_the_two_moved_producers(self):
        binding={key:'a'*64 for key in ('parentPlanSha256','newPlanSha256','sourceCanonicalSha256',
            'anchorCanonicalSha256','alignmentBytesSha256','asrReceiptSha256','sourceCheckReceiptSha256')}
        repository=Path(__file__).resolve().parents[1]
        before,after=compatibility.D5_MOVE_HISTORICAL_SHA256,compatibility.D5_MOVE_SOURCE_SHA256
        # Every key reads the file it names today; only the two moved producers changed bytes.
        for path,sha in after.items():
            self.assertEqual(sha,c.bytes_sha256((repository/compatibility.resolve(path)).read_bytes()),path)
        self.assertEqual(compatibility.resolve('scripts/sermon_fresh_diagnostic_source.py'),
                         'packages/production/src/tongxing_production/workflows/diagnostic/fresh_source.py')
        self.assertEqual({path for path in after if after[path]!=before[path]},set(compatibility.D5_MOVE_CHANGED))
        planned={compatibility.resolve(path):sha for path,sha in after.items()}
        step=compatibility.verify(before,after,planned,binding)
        self.assertEqual(step['migrationId'],compatibility.D5_MOVE_MIGRATION)
        self.assertEqual(step['changedModules'],compatibility.D5_MOVE_CHANGED)
        self.assertEqual(step['acceptedScope'],'read_only_original_source_under_package_move_no_new_inference')
        self.assertEqual((step['newASRCalls'],step['newMFACalls'],step['newSourceCheckCalls'],step['productionEligible'],
                          step['historicalSourcePreserved']),(0,0,0,False,True))
        # Generations do not compose: a v11 parent cannot jump straight to the D-5 checkout.
        with self.assertRaises(c.ContractError):
            compatibility.verify(compatibility.C_FACADE_REMOVAL_HISTORICAL_SHA256,after,planned,binding)

if __name__=='__main__':unittest.main()
