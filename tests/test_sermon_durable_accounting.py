"""Offline controller restarts, durable fact replay, and typed synthetic leaves."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import sermon_accounting as accounting
from scripts import sermon_completion as completion
from scripts import sermon_durable_accounting as durable
from scripts import sermon_log_contract as contract
from scripts import sermon_log_outbox as outbox
from scripts import sermon_log_profile as profile
from scripts import export_observability_trace as safe_export
from scripts import export_sermon_trace as trace
from scripts import weekly_pipeline_report as weekly
from tests.test_accounting_log_contract import fixture

BINDING = dict(scope_id='scope', plan_sha256='a' * 64, production_run_id='b' * 64, purpose='dag')


def transition(before, after):
    return {'event': 'step_state_changed', 'stepId': 'step', 'attemptId': 'step.1',
        'workUnitId': 'step', 'fromState': before, 'toState': after,
        'stateRevision': contract.fact_hash([before, after]), 'reasonCode': 'observed'}


def send(stream, before, after):
    return stream.write(transition(before, after), delivery_key='step.' + after)


def build(stream, before=None, after='pending'):
    def builder(event_id, producer_id, sequence):
        return profile._build(transition(before, after),
            {'schemaVersion': accounting.SCHEMA, 'runId': stream.run_id,
             'workflowId': stream.workflow_id, 'spanId': None,
             'recordedAt': '2026-10-02T00:00:00+00:00'},
            {'workKind': 'control', 'evidenceMode': 'synthetic', 'productionRunId': 'b' * 64},
            event_id, producer_id, sequence)
    return builder


class DurableStreamTests(unittest.TestCase):
    def child(self, directory, source, expected=0):
        root = str(Path(__file__).resolve().parents[1])
        setup = ('from scripts import sermon_durable_accounting as durable\n'
            'from scripts import sermon_log_outbox as outbox\n'
            'from tests.test_sermon_durable_accounting import BINDING, send\n'
            'import os, sys\n'
            's=durable.open_stream(sys.argv[1], **BINDING)\n')
        result = subprocess.run([sys.executable, '-c', setup + source, str(directory)],
            cwd=root, env={k: v for k, v in os.environ.items() if not k.startswith('SERMON_ACCOUNTING_')},
            capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, expected, result.stderr)
        return result

    def test_actual_process_restart_keeps_run_producer_and_order(self):
        with tempfile.TemporaryDirectory() as directory:
            s = durable.open_stream(directory, **BINDING, create=True)
            first = send(s, None, 'pending')
            self.child(directory, "send(s, 'pending', 'ready')\n")
            self.child(directory, "send(s, 'ready', 'running')\n")
            rows, errors = accounting.read_events(directory)
            self.assertFalse(errors)
            self.assertEqual([r['sequence'] for r in rows], [1, 2, 3])
            self.assertEqual({r['runId'] for r in rows}, {first['runId']})
            self.assertEqual({r['producerId'] for r in rows}, {first['producerId']})
            self.assertEqual(contract.replay_integrity(rows)['status'], 'consistent')

    def test_preappend_process_exit_recovers_exact_pending_and_next_sequence(self):
        with tempfile.TemporaryDirectory() as directory:
            durable.open_stream(directory, **BINDING, create=True)
            self.child(directory, "outbox._append=lambda *args: os._exit(71)\nsend(s,None,'pending')\n", 71)
            pending = next(Path(directory, '.pending-events').iterdir())
            original = json.loads(pending.read_text())
            self.child(directory, "send(s,None,'pending')\nsend(s,'pending','ready')\n")
            rows, _ = accounting.read_events(directory)
            self.assertEqual(rows[0], original)
            self.assertEqual(rows[1]['sequence'], 2)
            self.assertEqual(list(Path(directory, '.pending-events').iterdir()), [])

    def test_postappend_preack_process_exit_retrieves_original_event(self):
        with tempfile.TemporaryDirectory() as directory:
            durable.open_stream(directory, **BINDING, create=True)
            self.child(directory, "original=outbox._append\ndef fail(fd,event):\n original(fd,event)\n os._exit(72)\noutbox._append=fail\nsend(s,None,'pending')\n", 72)
            original = accounting.read_events(directory)[0][0]
            self.child(directory, "send(s,None,'pending')\nsend(s,'pending','ready')\n")
            rows, _ = accounting.read_events(directory)
            self.assertEqual(rows[:2], [original, original])
            self.assertEqual(rows[2]['sequence'], 2)
            checked = contract.replay_integrity(rows)
            self.assertEqual(checked['status'], 'consistent')
            self.assertEqual(checked['equivalentDuplicatesIgnored'], 1)

    def test_prepare_freezes_exact_event_and_same_intent_does_not_rebuild(self):
        with tempfile.TemporaryDirectory() as directory:
            s = durable.open_stream(directory, **BINDING, create=True)
            original = s.prepare('pending', {'state': 'pending'}, build(s))
            self.assertEqual(accounting.read_events(directory)[0], [])
            self.assertEqual(json.loads(next(Path(directory, '.pending-events').iterdir()).read_text()), original)
            s = durable.open_stream(directory, **BINDING)
            def forbidden(*args):
                raise AssertionError('replayed intent must not rebuild timestamps')
            self.assertEqual(s.prepare('pending', {'state': 'pending'}, forbidden), original)
            s.deliver(original)
            self.assertEqual(s.prepare('pending', {'state': 'pending'}, forbidden), original)
            with self.assertRaisesRegex(ValueError, 'intent_conflict'):
                s.prepare('pending', {'state': 'running'}, forbidden)

    def test_pending_union_allocates_and_delivers_in_order(self):
        with tempfile.TemporaryDirectory() as directory:
            s = durable.open_stream(directory, **BINDING, create=True)
            first = s.prepare('pending', {}, build(s))
            second = s.prepare('ready', {}, build(s, 'pending', 'ready'))
            self.assertEqual(second['sequence'], 2)
            s.deliver(second)
            self.assertEqual(accounting.read_events(directory)[0], [first, second])

    def test_ordinary_writer_cannot_claim_controller_state_or_foreign_run(self):
        with tempfile.TemporaryDirectory() as directory:
            s = durable.open_stream(directory, **BINDING, create=True)
            row = build(s)('c' * 32, 'd' * 32, 1)
            with self.assertRaisesRegex(ValueError, 'state_producer_required'):
                outbox.deliver(directory, row)
            row['event'] = 'log'
            for key in ('stepId', 'fromState', 'toState', 'stateRevision', 'reasonCode'):
                row.pop(key)
            row.update(code='observed', level='INFO', fields={}, runId='foreign')
            with self.assertRaisesRegex(ValueError, 'run_scope_conflict'):
                outbox.deliver(directory, row)
            self.assertEqual(accounting.read_events(directory)[0], [])

    def test_bad_sequence_and_foreign_event_rejected_before_reservation(self):
        for key, value in [('sequence', 2), ('producerId', 'f' * 32), ('runId', 'foreign'),
                           ('productionRunId', 'f' * 64), ('evidenceMode', 'current_execution')]:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as directory:
                s = durable.open_stream(directory, **BINDING, create=True)
                good = build(s)
                with self.assertRaises(ValueError):
                    s.prepare('bad', {}, lambda *args: dict(good(*args), **{key: value}))
                self.assertEqual(send(s, None, 'pending')['sequence'], 1)

    def test_foreign_scope_changed_binding_and_missing_binding_fail_closed(self):
        for field, value in [('scope_id', 'foreign'), ('plan_sha256', 'f' * 64),
                              ('production_run_id', 'f' * 64), ('purpose', 'foreign')]:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                s = durable.open_stream(directory, **BINDING, create=True)
                send(s, None, 'pending')
                with self.assertRaisesRegex(ValueError, 'scope_conflict'):
                    durable.open_stream(directory, **{**BINDING, field: value}, create=True)
        with tempfile.TemporaryDirectory() as directory:
            s = durable.open_stream(directory, **BINDING, create=True)
            send(s, None, 'pending')
            marker = Path(directory, durable.BINDING_NAME)
            binding = json.loads(marker.read_text())
            marker.write_text(json.dumps({**binding, 'producerId': 'f' * 32}))
            with self.assertRaisesRegex(ValueError, 'binding_changed'):
                durable.open_stream(directory, **BINDING)
            marker.unlink()
            with self.assertRaisesRegex(ValueError, 'established_binding_missing'):
                durable.open_stream(directory, **BINDING, create=True)

    def test_tamper_gaps_missing_records_and_pending_disagreement_are_blocked(self):
        for mode in ('gap', 'record', 'pending', 'deleted'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                s = durable.open_stream(directory, **BINDING, create=True)
                first = s.prepare('pending', {}, build(s))
                record_path = next(Path(directory, durable.DELIVERY_DIRECTORY).iterdir())
                pending_path = next(Path(directory, '.pending-events').iterdir())
                record = json.loads(record_path.read_text())
                if mode == 'gap':
                    record['event']['sequence'] = 2
                    record['eventSha256'] = contract.fact_hash(record['event'])
                    record_path.write_text(json.dumps(record))
                    pending_path.write_text(json.dumps(record['event']))
                elif mode == 'record':
                    record['event']['reasonCode'] = 'tampered'
                    record_path.write_text(json.dumps(record))
                elif mode == 'pending':
                    pending_path.write_text(json.dumps({**first, 'reasonCode': 'tampered'}))
                else:
                    record_path.unlink()
                with self.assertRaises(ValueError):
                    durable.open_stream(directory, **BINDING)

    def test_symlinks_oversized_files_and_torn_ledger_are_not_repaired(self):
        for target in (durable.BINDING_NAME, durable.DELIVERY_DIRECTORY, '.pending-events'):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as directory:
                s = durable.open_stream(directory, **BINDING, create=True)
                path = Path(directory, target)
                if path.is_dir(): path.rmdir()
                else: path.unlink()
                other = Path(directory, 'other')
                other.mkdir() if target != durable.BINDING_NAME else other.write_text('{}')
                path.symlink_to(other)
                with self.assertRaises((ValueError, OSError)):
                    durable.open_stream(directory, **BINDING)
        with tempfile.TemporaryDirectory() as directory:
            s = durable.open_stream(directory, **BINDING, create=True)
            send(s, None, 'pending')
            path = Path(directory, 'events.jsonl')
            original = path.read_bytes() + b'{"torn":'
            path.write_bytes(original)
            with self.assertRaisesRegex(ValueError, 'damaged'):
                send(s, 'pending', 'ready')
            with self.assertRaisesRegex(ValueError, 'damaged'):
                outbox.replay_pending(directory)
            self.assertEqual(path.read_bytes(), original)
        with tempfile.TemporaryDirectory() as directory:
            durable.open_stream(directory, **BINDING, create=True)
            Path(directory, durable.BINDING_NAME).write_bytes(b' ' * 4097)
            with self.assertRaisesRegex(ValueError, 'size_limit'):
                durable.open_stream(directory, **BINDING)

    def test_recursive_logger_builder_is_rejected_not_deadlocked(self):
        with tempfile.TemporaryDirectory() as directory:
            s = durable.open_stream(directory, **BINDING, create=True)
            with s.context():
                with self.assertRaises(accounting.AccountingWriteError) as error:
                    s.prepare('bad', {}, lambda *args: accounting.record_log('nested'))
                self.assertEqual(str(error.exception.__cause__), 'recursive_accounting_ledger_lock')
            self.assertEqual(send(s, None, 'pending')['sequence'], 1)

    def test_context_has_no_automatic_lifecycle_or_durable_child_producer(self):
        with tempfile.TemporaryDirectory() as directory:
            s = durable.open_stream(directory, **BINDING, create=True)
            with s.context():
                child = profile.job_context('c' * 64)
                self.assertEqual(child['environment'][accounting.ENV_KEYS[1]], s.run_id)
                self.assertNotIn(s.producer_id, json.dumps(child))
                with self.assertRaisesRegex(ValueError, 'already_active'):
                    with s.context(): pass
                with accounting.stage('ordinary', work_unit_id='ordinary', depends_on=[]): pass
            rows, errors = accounting.read_events(directory)
            self.assertFalse(errors)
            self.assertFalse(any(r['event'] in {'run_started', 'workflow_started', 'run_finished', 'workflow_finished'} for r in rows))
            self.assertNotIn(s.producer_id, {r['producerId'] for r in rows})

    def test_same_process_concurrent_ordinary_prepares_freeze_before_reservation(self):
        with tempfile.TemporaryDirectory() as directory:
            s = durable.open_stream(directory, **BINDING, create=True)
            def ordinary(index):
                def builder(event_id, producer_id, sequence):
                    row = build(s)(event_id, producer_id, sequence)
                    row['event'] = 'log'
                    for key in ('stepId', 'fromState', 'toState', 'stateRevision', 'reasonCode'):
                        row.pop(key)
                    return {**row, 'code': 'ordinary', 'level': 'INFO', 'fields': {'count': index}}
                return outbox.prepare(directory, builder)
            with ThreadPoolExecutor(max_workers=4) as pool:
                prepared = list(pool.map(ordinary, range(8)))
            self.assertEqual(accounting.read_events(directory)[0], [])
            self.assertEqual(len(list(Path(directory, '.pending-events').iterdir())), 8)
            for row in reversed(prepared):
                outbox.deliver(directory, row)
            rows = accounting.read_events(directory)[0]
            self.assertEqual(sorted(r['sequence'] for r in rows), list(range(1, 9)))
            self.assertEqual(contract.replay_integrity(rows)['status'], 'consistent')


class ExplicitOutcomeTests(unittest.TestCase):
    def test_explicit_statuses_actual_endpoint_and_reader_compatibility(self):
        for status in ('completed', 'failed', 'outcome_unknown', 'cancelled'):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                s = durable.open_stream(directory, **BINDING, create=True)
                clock = ['2026-10-02T00:00:00+00:00']
                with s.context(), patch.object(accounting, 'now', side_effect=lambda: clock[0]):
                    with accounting.stage_outcome('observed', work_unit_id='observed', depends_on=[]) as outcome:
                        clock[0] = '2026-10-02T00:00:01+00:00'
                        outcome.finish(status)
                        clock[0] = '2026-10-02T00:00:09+00:00'
                rows, errors = accounting.read_events(directory)
                end = next(r for r in rows if r['event'] == 'stage_finished')
                self.assertFalse(errors)
                self.assertEqual(end['status'], status)
                self.assertEqual(end['completedAt'], '2026-10-02T00:00:01Z')
                self.assertEqual(end['recordedAt'], '2026-10-02T00:00:09Z')
                before = deepcopy(end)
                outbox.deliver(directory, end)
                self.assertEqual(accounting.read_events(directory)[0][-1], before)
                self.assertEqual(contract.replay_integrity(accounting.read_events(directory)[0])['status'], 'consistent')
                accounting.summarize(directory)
                weekly.project(directory)
                trace.export(directory)
                safe_export.export(Path(directory), Path(directory) / 'safe')
                exported, damaged = accounting.read_events(Path(directory) / 'safe')
                self.assertFalse(damaged)
                self.assertTrue(any(r.get('status') == status for r in exported))

    def test_missing_finish_and_contradictory_exception_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            s = durable.open_stream(directory, **BINDING, create=True)
            with s.context():
                with self.assertRaisesRegex(ValueError, 'stage_outcome_required'):
                    with accounting.stage_outcome('omitted', depends_on=[]): pass
                with self.assertRaisesRegex(RuntimeError, 'business failure'):
                    with accounting.stage_outcome('contradiction', depends_on=[]) as outcome:
                        outcome.finish('completed', artifact_sha256='d' * 64)
                        raise RuntimeError('business failure')
            ends = [r for r in accounting.read_events(directory)[0] if r['event'] == 'stage_finished']
            self.assertEqual([r['status'] for r in ends], ['outcome_unknown', 'failed'])
            self.assertNotIn('artifactSha256', ends[1])
            self.assertEqual(len(ends), 2)

    def test_unknown_observer_is_distinct_from_later_worker_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            s = durable.open_stream(directory, **BINDING, create=True)
            with s.context(), profile.context(jobId='job', revisionId='revision'):
                with accounting.stage_outcome('wait', work_unit_id='wait', attempt_id='observer.1', depends_on=[]) as observer:
                    observer.finish('outcome_unknown')
                with accounting.stage_outcome('worker', work_unit_id='worker', attempt_id='worker.1', depends_on=[]) as worker:
                    worker.finish('completed', artifact_sha256='d' * 64)
                handle = completion.capture_synthetic(worker.span_id, production_run_id='b' * 64,
                    artifact_sha256='d' * 64, artifact_kind='mock_wav', job_id='job', revision_id='revision')
            rows = accounting.read_events(directory)[0]
            completion.validate_synthetic(handle, rows, production_run_id='b' * 64)
            unknown = next(r for r in rows if r['event'] == 'stage_finished' and r['attemptId'] == 'observer.1')
            self.assertEqual(unknown['status'], 'outcome_unknown')
            self.assertNotEqual(unknown['spanId'], handle['spanId'])
            s.write({'event': 'attempt_reconciled', 'reconcilesAttemptId': 'observer.1',
                'result': 'succeeded', 'evidenceSha256': handle['terminalFactSha256'],
                'reasonCode': 'worker_receipt_verified'}, delivery_key='observer.reconciled')
            updated = accounting.read_events(directory)[0]
            self.assertEqual(next(r for r in updated if r['eventId'] == unknown['eventId']), unknown)
            self.assertEqual(contract.replay_integrity(updated)['status'], 'consistent')


class SyntheticCompletionTests(unittest.TestCase):
    def test_binding_container_and_source_kind_negatives(self):
        with tempfile.TemporaryDirectory() as directory:
            s = durable.open_stream(directory, **BINDING, create=True)
            with s.context(), profile.context(jobId='job', revisionId='revision'):
                with accounting.stage_outcome('parent', work_unit_id='parent', depends_on=[]) as parent:
                    with accounting.stage_outcome('child', work_unit_id='child', depends_on=[]) as child:
                        child.finish('completed', artifact_sha256='d' * 64)
                    parent.finish('completed', artifact_sha256='e' * 64)
                args = dict(production_run_id='b' * 64, artifact_sha256='d' * 64,
                    artifact_kind='mock_wav', job_id='job', revision_id='revision')
                handle = completion.capture_synthetic(child.span_id, **args)
                for field, value in [('artifact_sha256', 'f' * 64), ('job_id', 'foreign'),
                                     ('revision_id', 'foreign'), ('artifact_kind', 'source_package')]:
                    with self.subTest(field=field), self.assertRaises(ValueError):
                        completion.capture_synthetic(child.span_id, **{**args, field: value})
                with self.assertRaisesRegex(ValueError, 'container_forbidden'):
                    completion.capture_synthetic(parent.span_id, **{**args, 'artifact_sha256': 'e' * 64})
                _, rows = completion.current_events()
                self.assertEqual(completion.validate_synthetic(handle, rows + rows,
                    production_run_id='b' * 64), handle)
                for key, value in [('evidenceMode', 'current_execution'), ('artifactKind', 'source_package'),
                                   ('attemptId', 'foreign'), ('jobId', 'foreign'), ('revisionId', 'foreign')]:
                    with self.subTest(key=key), self.assertRaises(ValueError):
                        completion.validate_synthetic({**handle, key: value}, rows, production_run_id='b' * 64)
                self.assertEqual(completion.validate_synthetic_shape(handle), handle)


class ValidationCacheTests(unittest.TestCase):
    def setUp(self):
        contract._validate_frozen_event.cache_clear()

    def test_cache_returns_original_and_nested_mutation_never_reuses_success(self):
        row = fixture('stage-start')
        self.assertIs(contract.validate_event(row), row)
        other = deepcopy(row)
        self.assertIs(contract.validate_event(other), other)
        self.assertEqual(contract._validate_frozen_event.cache_info().hits, 1)
        other['missingReasons']['queuedAt'] = 'invented_reason'
        with self.assertRaises(contract.ContractError): contract.validate_event(other)
        self.assertEqual(contract._validate_frozen_event.cache_info().currsize, 1)

    def test_python_types_and_nonfinite_are_checked_before_lookup(self):
        row = fixture('stage-start')
        contract.validate_event(row)
        for key, value in [('dependsOn', ()), ('sequence', True), ('sequence', 1.0),
                           ('elapsedSeconds', float('nan')), ('elapsedSeconds', float('inf'))]:
            with self.subTest(key=key, value=repr(value)), self.assertRaises(contract.ContractError):
                contract.validate_event({**row, key: value})
        self.assertEqual(contract._validate_frozen_event.cache_info().currsize, 1)

    def test_semantic_failure_does_not_populate_success_cache(self):
        row = fixture('stage-finish')
        row['monotonicEndNs'] = '9000000000'
        with self.assertRaisesRegex(contract.ContractError, 'monotonic_duration_conflict'):
            contract.validate_event(row)
        self.assertEqual(contract._validate_frozen_event.cache_info().currsize, 0)

    def test_changed_schema_or_contract_version_invalidates_cached_success(self):
        row = fixture('stage-start')
        contract.validate_event(row)
        properties = contract.validator().schema['properties']
        previous = deepcopy(properties['sequence'])
        try:
            properties['sequence'] = {'type': 'integer', 'minimum': 2}
            with self.assertRaises(contract.ContractError): contract.validate_event(row)
        finally:
            properties['sequence'] = previous
        with patch.object(contract, 'VERSION', 'future'):
            with self.assertRaises(contract.ContractError): contract.validate_event(row)
        self.assertIs(contract.validate_event(row), row)

    def test_large_events_are_validated_without_retained_payload_keys(self):
        row = fixture('stage-start')
        row['dependsOn'] = [f'edge-{i:02d}-' + 'x' * 92 for i in range(64)]
        row['blockedBy'] = [f'wait-{i:02d}-' + 'x' * 92 for i in range(64)]
        self.assertGreater(len(contract.canonical_bytes(row)), contract.MAX_CACHED_EVENT_BYTES)
        self.assertIs(contract.validate_event(row), row)
        self.assertEqual(contract._validate_frozen_event.cache_info().currsize, 0)
        self.assertEqual(contract._validate_frozen_event.cache_info().maxsize,
            contract.MAX_VALIDATION_CACHE_ENTRIES)
        row['unexpected'] = 'x' * contract.MAX_EVENT_BYTES
        with self.assertRaisesRegex(contract.ContractError, 'event_size_limit'):
            contract.validate_event(row)
        self.assertEqual(contract._validate_frozen_event.cache_info().currsize, 0)


if __name__ == '__main__': unittest.main()
