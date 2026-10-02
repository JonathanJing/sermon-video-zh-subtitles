from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from scripts import sermon_accounting as accounting
from scripts import sermon_completion as completion
from scripts import sermon_log_profile as profile
from scripts import sermon_review_contracts as c
from scripts import sermon_source_producer_compatibility as compatibility
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
        from scripts import sermon_fresh_diagnostic_source as source

        # Isolate the real Source predecessor gate using in-memory upstream
        # inputs. Stop immediately after it, before alignment or output writes.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
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
        actual=c.bytes_sha256((Path(compatibility.__file__).parent/'sermon_fresh_diagnostic_source.py').read_bytes())
        self.assertEqual(compatibility.EXTRACTION_SOURCE_SHA256['scripts/sermon_fresh_diagnostic_source.py'],actual)
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


if __name__=='__main__':unittest.main()
