"""Closed native-parent cache inspection, never old execution or budget migration.

This module must be eagerly imported before freezing execution identity.
It copies known completed WAV bytes into a NEW worker output only while the
normal launcher holds its output lock. The normal current worker then measures
cache hits, full-decodes, and makes its own real clock/receipt evidence.
"""
from dataclasses import dataclass
from pathlib import Path
import os
import shutil
import time

from scripts import sermon_accounting as accounting  # eager identity inventory
from scripts import sermon_diagnostic_attempts as attempts
from scripts import sermon_diagnostic_delivery_preflight as delivery
from scripts import sermon_diagnostic_provider as provider
from scripts import sermon_diagnostic_preview_worker as worker
from scripts import sermon_public_snapshot as public
from scripts import sermon_review_budget as budget
from scripts import sermon_review_contracts as c

SCHEMA = 'sermon-historical-native-rebind-proof-v1'
# The accepted original native producer is reviewed source, not caller input.
FROZEN_PARENT_COMMIT = 'bc955f1424c3b7db4aefa5a23114c9e616a4e127'
FROZEN_PARENT_WORKER_SHA256 = '2ca16aac1ed10826307394ea6c277d37a4feeb117a4bb3bee67ea86e334d8172'


@dataclass(frozen=True)
class HistoricalSeed:
    parent_plan_path: str
    parent_receipt_path: str


def _ref(files, path):
    return dict(path=str(files.path(path)), fileBytesSha256=files.file(path))


def _closed_parent(plan_path, files):
    original = files.json(plan_path)
    plan, root = attempts._project(plan_path)
    c.require(files.path(plan_path) == root / 'run-plan.json', 'historical_seed_parent_plan_path_changed')
    identity = plan['executionIdentity']
    c.require(identity['gitCommit'] == FROZEN_PARENT_COMMIT
        and identity['loadedProjectCodeSha256'].get('scripts/sermon_diagnostic_preview_worker.py') == FROZEN_PARENT_WORKER_SHA256,
        'historical_seed_parent_worker_not_reviewed')
    evidence = attempts.terminal_parent(plan)
    # Require an explicit immutable closure, not a guessed process death or a
    # clock observation that could be changed by another caller.
    closure_path = root / 'budget' / budget.STORE_ID / 'provider-run/closed.json'
    closure = files.json(closure_path)
    projected = dict(projectedPlan=plan, runDirectory=str(root), snapshots=evidence['snapshots'],
        clockDomain=evidence['clockDomain'], startedMonotonic=evidence['startedMonotonic'],
        totalWallSeconds=evidence['totalWallSeconds'])
    c.require(attempts._unavailable(projected) is not None
        and closure['budgetStateFileSha256'] == evidence['snapshots'][1]['bytesSha256']
        and closure['closureEvidenceSha256'] == c.canonical_sha256(attempts.terminal_parent(plan, _legacy_observation=True)),
        'historical_seed_parent_close_changed')
    for row in evidence['snapshots']:
        c.require(files.file(row['path']) == row['bytesSha256'], 'historical_seed_parent_ledger_changed')
    subject = provider.DiagnosticProvider(budget.BudgetStore(root / 'budget', plan['authority']), plan['providerConfig'])
    return original, plan, root, subject, evidence, _ref(files, closure_path)


def _lineage(root, plan, original_parent, parent_root, files):
    history_path = root / 'linked-history.json'
    history = files.json(history_path)
    c.require(history['schemaVersion'] == attempts.SCHEMA_V2
        and history['newPlanSha256'] == c.canonical_sha256(plan)
        and history['oldLedgerAndDeadlineModified'] is False and history['oldReplayAllowed'] is False
        and history['productionEligible'] is False, 'historical_seed_new_lineage_changed')
    baseline = attempts.validate_baseline(history['legacyObservationBaseline'])
    c.require(history['parentEvidence'] == baseline['observations'], 'historical_seed_parent_closure_incomplete')
    rows = [row for row in baseline['observations'] if row['runDirectory'] == str(parent_root)]
    c.require(len(rows) == 1 and rows[0]['originalPlan'] == attempts._ref(parent_root / 'run-plan.json')
        and rows[0]['projectedPlan']['providerConfig']['codeSha256'] == original_parent['providerConfig']['codeSha256'],
        'historical_seed_parent_not_in_ancestor_closure')
    authorization = files.json(root / 'authorization.json')
    expected_plan, expected_history = attempts.prepare_new_attempt_v2(baseline['parentPlan']['path'],
        new_root=root, authorization=authorization, execution_identity=plan['executionIdentity'], baseline=baseline)
    c.require(expected_plan == plan and expected_history == history, 'historical_seed_new_attempt_binding_changed')
    successor_path, successor = attempts._successor_binding(plan, baseline, authorization)
    c.require(files.json(successor_path) == successor, 'historical_seed_successor_not_reserved')
    for row in baseline['snapshots']:
        c.require(files.file(row['path']) == row['bytesSha256'], 'historical_seed_ancestor_changed')
    for row in history['parentClosureSnapshots']:
        c.require(files.file(row['path']) == row['bytesSha256'], 'historical_seed_ancestor_close_changed')
    return [_ref(files, path) for path in (root / 'run-plan.json', history_path, root / 'authorization.json', successor_path)]


def _all_groups(spec, checked):
    ids = [group['translationGroupId'] for group in checked['candidate']['groups']]
    selected = spec.get('group_ids')
    c.require(ids and (selected is None or len(selected) == len(ids) and set(selected) == set(ids)),
        'historical_seed_complete_lane_required')
    return ids


def _sound(checked, spec, index):
    return worker.preview.sound_identity(checked, index, seed=spec.get('seed', 42),
        dtype=spec.get('dtype', 'bfloat16'), attention=spec.get('attention', 'sdpa'), instruct=spec.get('instruct'))


def preflight_parent(historical_seed):
    """Public zero-dispatch closed-parent check BEFORE preparing paid repairs.

    This is inspection evidence only. It grants no synthesis, approval or budget
    authority. Fresh must freeze/recheck these refs and seed.inspect independently
    validates every new sound identity before any cache is written.
    """
    c.require(type(historical_seed) is HistoricalSeed, 'historical_seed_trusted_type_required')
    files = delivery._Snapshot()
    original, plan, root, subject, evidence, closure = _closed_parent(historical_seed.parent_plan_path, files)
    path = files.path(historical_seed.parent_receipt_path, root)
    saved = files.json(path)
    c.require(saved.get('schemaVersion') == worker.V3_SCHEMA and saved.get('offlineFixture') is False
        and 'historicalSeedProof' not in saved, 'historical_seed_original_native_v3_required')
    context = files.json(Path(saved['spec']['out']) / 'diagnostic_context.json')
    envelope = dict(saved, receiptPath=str(path), receiptFileSha256=files.file(path))
    worker.validate_preview_receipt(root, subject, context, envelope)
    spec, checked, inputs = worker._spec(root, saved['spec'], context, False)
    _all_groups(spec, checked)
    request_path = Path(spec['out']) / 'worker-request.json'
    request = files.json(request_path)
    c.require(request['workerCodeSha256'] == FROZEN_PARENT_WORKER_SHA256,
        'historical_seed_original_worker_sha_changed')
    files.refs(inputs); files.refs(saved['artifacts'], root); files.recheck()
    return dict(schemaVersion='sermon-historical-native-parent-preflight-v1', status='closed_complete_native_parent_observed',
        grantsExecutionAuthority=False, productionEligible=False, humanAcceptance='pending',
        providerCalls=0, modelCalls=0, parentPlan=_ref(files, historical_seed.parent_plan_path), closure=closure,
        workerReceipt=_ref(files, path), workerRequest=_ref(files, request_path), originalArtifacts=saved['artifacts'],
        originalInputs=inputs, originalRunId=plan['providerConfig']['runId'], originalContextSha256=c.canonical_sha256(context),
        parentEvidenceSha256=c.canonical_sha256(evidence), targetLocale=checked['candidate']['targetLocale'],
        unitCount=len(checked['candidate']['groups']), nativeRuntimeBinding=checked['native_runtime_binding'],
        checkpointBinding=checked['checkpoint_binding'], sourceJsonSha256=c.canonical_sha256(checked['source']),
        anchorJsonSha256=c.canonical_sha256(checked['anchor']), candidateJsonSha256=c.canonical_sha256(checked['candidate']),
        soundIdentitySha256=[c.canonical_sha256(_sound(checked,spec,index)) for index in range(len(checked['candidate']['groups']))])


def inspect(root, subject, context, spec, checked, inputs, historical_seed):
    """Pure validation and a hash-bound copy plan; no synthesis, writes or clock renewal."""
    c.require(type(historical_seed) is HistoricalSeed, 'historical_seed_trusted_type_required')
    files = delivery._Snapshot(); root = files.path(root)
    c.require(type(subject) is provider.DiagnosticProvider and subject.store.root == root / 'budget',
        'historical_seed_trusted_provider_required')
    plan = files.json(root / 'run-plan.json')
    c.require(plan['runDirectory'] == str(root) and plan['providerConfig'] == subject.config
        and context['runId'] == subject.config['runId'] and context['runConfigSha256'] == c.canonical_sha256(subject.config)
        and context['storeSha256'] == subject.store.store_sha256, 'historical_seed_new_context_changed')
    old_original, old_plan, old_root, old_subject, parent_evidence, closed = _closed_parent(historical_seed.parent_plan_path, files)
    c.require(old_root != root and not old_root.is_relative_to(root) and not root.is_relative_to(old_root),
        'historical_seed_distinct_run_required')
    lineage = _lineage(root, plan, old_plan, old_root, files)
    saved_path = files.path(historical_seed.parent_receipt_path, old_root)
    saved = files.json(saved_path)
    c.require(saved.get('schemaVersion') == worker.V3_SCHEMA and saved.get('offlineFixture') is False
        and 'historicalSeedProof' not in saved, 'historical_seed_original_native_v3_required')
    old_context = files.json(Path(saved['spec']['out']) / 'diagnostic_context.json')
    envelope = dict(saved, receiptPath=str(saved_path), receiptFileSha256=files.file(saved_path))
    # Includes request/clock/deadline/full runtime and checkpoint inventory,
    # admission, consent, every committed unit, and original immutable snapshots.
    worker.validate_preview_receipt(old_root, old_subject, old_context, envelope)
    old_spec, old_checked, _ = worker._spec(old_root, saved['spec'], old_context, False)
    request = files.json(Path(old_spec['out']) / 'worker-request.json')
    c.require(request['workerCodeSha256'] == FROZEN_PARENT_WORKER_SHA256,
        'historical_seed_original_worker_sha_changed')
    normalized, actual_checked, actual_inputs = worker._spec(root, spec, context, False)
    c.require(normalized == spec and actual_checked == checked and actual_inputs == inputs,
        'historical_seed_new_inputs_changed')
    old_ids, ids = _all_groups(old_spec, old_checked), _all_groups(spec, checked)
    c.require(old_ids == ids and old_checked['native_runtime_binding'] == checked['native_runtime_binding'],
        'historical_seed_runtime_or_groups_changed')
    old_checkpoint, new_checkpoint = old_checked['checkpoint_binding'], checked['checkpoint_binding']
    # Stage declarations differ across plans; full checkpoint bindings must not.
    c.require(old_checkpoint == new_checkpoint and old_checkpoint is not None,
        'historical_seed_checkpoint_tree_changed')
    source_refs = [_ref(files, historical_seed.parent_plan_path), _ref(files, saved_path), closed]
    source_refs += [dict(row) for row in saved['inputs']] + [dict(row) for row in saved['artifacts']]
    source_refs = list({row['path']: row for row in source_refs}.values())
    for row in source_refs:
        c.require(files.file(row['path']) == row['fileBytesSha256'], 'historical_seed_old_artifact_changed')
    new_manifest = worker._manifest(checked)
    units = []
    for index in range(len(ids)):
        old_sound, sound = _sound(old_checked, old_spec, index), _sound(checked, spec, index)
        c.require(old_sound == sound, 'historical_seed_sound_identity_changed')
        old_unit_path = Path(old_spec['out']) / f'receipts/unit-{index:04d}.json'
        old_audio_path = Path(old_spec['out']) / f'units/unit-{index:04d}.wav'
        old_unit = files.json(old_unit_path)
        decoded = worker.preview.integrity.probe_full_decode(old_audio_path)
        audio_sha = files.file(old_audio_path)
        c.require(old_unit['audioSha256'] == audio_sha and old_unit['soundIdentity'] == sound
            and old_unit['fullDecode'] == 'pass' and old_unit['durationSeconds'] == decoded['durationSeconds'],
            'historical_seed_original_unit_changed')
        unit = dict(old_unit, candidateJsonSha256=c.canonical_sha256(checked['candidate']),
            previewContextSha256=c.canonical_sha256(new_manifest))
        units.append(dict(unitIndex=index, oldUnit=_ref(files, old_unit_path), oldAudio=_ref(files, old_audio_path),
            unit=unit, unitCanonicalSha256=c.canonical_sha256(unit), soundIdentitySha256=c.canonical_sha256(sound)))
    files.refs(inputs)
    files.recheck()
    proof = dict(schemaVersion=SCHEMA, status='historical_inspection_only', productionEligible=False,
        humanAcceptance='pending', modelExecutedCurrentAttempt=False, evidenceMode='historical_reuse',
        oldBudgetMoved=False, oldDeadlineModified=False, originalRunId=old_plan['providerConfig']['runId'],
        currentRunId=subject.config['runId'], currentContextSha256=c.canonical_sha256(context),
        currentSpecSha256=c.canonical_sha256(spec), currentManifestSha256=c.canonical_sha256(new_manifest),
        parentEvidenceSha256=c.canonical_sha256(parent_evidence), originalWorkerCodeSha256=FROZEN_PARENT_WORKER_SHA256,
        inspectorCode=_ref(files, Path(__file__).resolve()), originalRefs=source_refs, lineageRefs=lineage,
        currentInputs=inputs, units=units)
    return proof


def seed(root, subject, context, spec, checked, inputs, historical_seed, *, depends_on=None):
    """Called ONLY after launcher acquires output lock and requires empty out."""
    out = worker._tree(root, spec['out'])
    c.require(not out.exists() or not any(out.iterdir()), 'historical_seed_nonempty_output_requires_reconciliation')
    with accounting.stage('preview.historical_native_inspection', executor_type='deterministic_program',
                          depends_on=depends_on) as inspection_span:
        proof = inspect(root, subject, context, spec, checked, inputs, historical_seed)
        c.require(time.monotonic() < worker._read(Path(root) / 'budget' / budget.STORE_ID / 'provider-run/state.json')['startedMonotonic']
            + subject.config['totalWallSeconds'], 'preview_original_deadline_reached')
        # No rollback/retry of a partial seed. Any interruption is reconciled as
        # an unknown output; original files are never modified or hard-linked.
        out.mkdir(parents=True, exist_ok=True, mode=0o700)
        for name in (*worker.PATH_KEYS, 'strict_rubric', 'diagnostic_context'):
            public.save_once(out / (name + '.json'), checked[name])
        public.save_once(out / 'manifest.json', worker._manifest(checked))
        (out / 'units').mkdir(); (out / 'receipts').mkdir()
        for row in proof['units']:
            index = row['unitIndex']; path = out / f'units/unit-{index:04d}.wav'
            fd = os.open(row['oldAudio']['path'], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, 'rb') as source, path.open('xb') as target:
                shutil.copyfileobj(source, target); target.flush(); os.fsync(target.fileno())
            c.require(worker._ref(path)['fileBytesSha256'] == row['oldAudio']['fileBytesSha256'], 'historical_seed_copy_changed')
            public.save_once(out / f'receipts/unit-{index:04d}.json', row['unit'])
        # The renderer/worker rechecks every seed using its ordinary cache path.
        worker._outputs(root, spec, checked)
        worker._check_refs(proof['originalRefs']); worker._check_refs(inputs)
        proof_path = out / 'historical-rebind-proof.json'
        public.save_once(proof_path, proof)
        return worker._ref(proof_path), inspection_span


def validate_completed(root, subject, context, spec, checked, inputs, reference):
    """Pure semantic replay of an existing proof, not another seed or execution."""
    c.require(reference == worker._ref(Path(spec['out']) / 'historical-rebind-proof.json'),
        'historical_seed_proof_changed')
    proof = worker._read(reference['path'])
    parent_plans = [row for row in proof['originalRefs'] if row['path'].endswith('/run-plan.json')]
    receipts = [row for row in proof['originalRefs'] if row['path'].endswith('/worker-receipt.json')]
    c.require(len(parent_plans) == len(receipts) == 1, 'historical_seed_original_refs_invalid')
    expected = inspect(root, subject, context, spec, checked, inputs,
        HistoricalSeed(parent_plans[0]['path'], receipts[0]['path']))
    c.require(proof == expected, 'historical_seed_proof_changed')
    for row in proof['units']:
        c.require(worker._read(Path(spec['out']) / f"receipts/unit-{row['unitIndex']:04d}.json") == row['unit'],
            'historical_seed_rebound_unit_changed')
    worker._outputs(root, spec, checked)
    return reference


def match_seed(reference, historical_seed):
    """A replay must not silently switch the requested historical producer."""
    c.require(type(historical_seed) is HistoricalSeed, 'historical_seed_trusted_type_required')
    c.require(reference == worker._ref(reference['path']), 'historical_seed_proof_changed')
    proof = worker._read(reference['path'])
    plans = [row for row in proof['originalRefs'] if row['path'].endswith('/run-plan.json')]
    receipts = [row for row in proof['originalRefs'] if row['path'].endswith('/worker-receipt.json')]
    c.require(plans == [worker._ref(historical_seed.parent_plan_path)]
        and receipts == [worker._ref(historical_seed.parent_receipt_path)], 'historical_seed_requested_parent_changed')
