"""Read-only inspection of an isolated diagnostic's completed preview evidence.

No approval, formal audio package, release, provider call, model load or durable
state is created. The caller persists the returned hash-only report if desired.
"""
import hashlib
import math
import os
from pathlib import Path
import stat

from scripts import render_speculative_target_language_speech as preview
from scripts import sermon_diagnostic_context as diagnostic
from scripts import sermon_diagnostic_provider as provider
from scripts import sermon_diagnostic_preview_worker as worker
from scripts import sermon_diagnostic_source_evidence as source_evidence
from scripts import sermon_public_snapshot as public
from scripts import sermon_review_budget as budget
from scripts import sermon_review_contracts as c
from scripts.sermon_release_workflow import _safe_path

SCHEMA = 'sermon-diagnostic-delivery-preflight-v1'
WORKER_SCHEMA = 'sermon-diagnostic-preview-worker-receipt-v1'
PENDING_GATES = ('source_review', 'sermon_window', 'terminology', 'translation',
                 'listening', 'synchronization', 'formal_audio_package', 'delivery_acceptance')


class _Snapshot:
    def __init__(self):
        self.hashes = {}

    def path(self, value, root=None):
        c.require(isinstance(value, (str, Path)) and Path(value).is_absolute(),
                  'diagnostic_delivery_absolute_path_required')
        path = _safe_path(Path(value))
        c.require(root is None or path.is_relative_to(root), 'diagnostic_delivery_path_outside_run')
        return path

    def file(self, value, root=None):
        path = self.path(value, root)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            before = os.fstat(fd)
            c.require(stat.S_ISREG(before.st_mode), 'diagnostic_delivery_regular_file_required')
            digest = hashlib.sha256()
            with os.fdopen(os.dup(fd), 'rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(block)
            after, named = os.fstat(fd), path.stat(follow_symlinks=False)
            identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
            c.require(identity(before) == identity(after) == identity(named), 'diagnostic_delivery_file_changed')
        finally:
            os.close(fd)
        value = digest.hexdigest()
        c.require(path not in self.hashes or self.hashes[path] == value, 'diagnostic_delivery_file_changed')
        self.hashes[path] = value
        return value

    def json(self, value, root=None):
        path = self.path(value, root)
        digest = self.file(path)
        result, raw = public.read_snapshot(path)
        c.require(c.bytes_sha256(raw) == digest, 'diagnostic_delivery_file_changed')
        return result

    def refs(self, rows, root=None):
        c.require(type(rows) is list and rows, 'diagnostic_delivery_artifact_refs_required')
        seen = set()
        for row in rows:
            c.require(type(row) is dict and set(row) == {'path', 'fileBytesSha256'},
                      'diagnostic_delivery_artifact_ref_invalid')
            path = self.path(row['path'], root)
            c.require(path not in seen and self.file(path) == row['fileBytesSha256'],
                      'diagnostic_delivery_artifact_changed')
            seen.add(path)
        return seen

    def embedded(self, value):
        if type(value) is list:
            for row in value:
                self.embedded(row)
        elif type(value) is dict:
            for key, row in value.items():
                if key in ('path', 'checkpointPath') and isinstance(row, str):
                    path = self.path(row)
                    if path.is_file():
                        digest = self.file(path)
                        if key == 'path' and 'sha256' in value:
                            c.require(value['sha256'] == digest, 'diagnostic_delivery_embedded_artifact_changed')
                else:
                    self.embedded(row)

    def recheck(self):
        for path in list(self.hashes):
            self.file(path)


def _inspect_preview(root, subject, context, locale, envelope, files):
    c.require(type(envelope) is dict and {'receiptPath', 'receiptFileSha256', 'spec'} <= envelope.keys(),
              'diagnostic_delivery_worker_receipt_required')
    receipt_path = files.path(envelope['receiptPath'], root)
    receipt = files.json(receipt_path)
    c.require(files.file(receipt_path) == envelope['receiptFileSha256'] and receipt == {
        k: v for k, v in envelope.items() if k not in ('receiptPath', 'receiptFileSha256')},
        'diagnostic_delivery_worker_receipt_changed')
    c.require(receipt['schemaVersion'] in {WORKER_SCHEMA, worker.V2_SCHEMA, worker.SCHEMA} and receipt['status'] == 'preview_only'
        and receipt['humanAcceptance'] == 'pending' and receipt['productionEligible'] is False
        and receipt['runId'] == context['runId'] and receipt['storeSha256'] == context['storeSha256']
        and receipt['runConfigSha256'] == context['runConfigSha256']
        and receipt['diagnosticContextSha256'] == c.canonical_sha256(context),
        'diagnostic_delivery_worker_context_changed')
    spec = receipt['spec']
    if receipt['schemaVersion'] != WORKER_SCHEMA:
        c.require(type(receipt.get('clockHandshake')) is dict
            and set(receipt['clockHandshake']) == {'launch','finished','joined'}, 'diagnostic_delivery_worker_clock_missing')
        proof = receipt['clockHandshake']
        worker.clock.validate_worker_handshake(proof['launch'],proof['finished'],proof['joined'])
        if receipt['offlineFixture']:
            c.require(receipt.get('nativeRuntimeBinding') is None and 'runtime_manifest_path' not in spec,
                'diagnostic_delivery_fixture_cannot_claim_runtime')
        else:
            binding = worker.native_runtime.validate(files.path(spec['runtime_manifest_path']))
            c.require(receipt.get('nativeRuntimeBinding') == binding, 'diagnostic_delivery_native_runtime_changed')
    c.require(c.canonical_sha256(spec) == receipt['specSha256'], 'diagnostic_delivery_preview_spec_changed')
    out = files.path(spec['out'], root)
    c.require(receipt_path == out / 'worker-receipt.json', 'diagnostic_delivery_worker_receipt_path_changed')
    inputs = files.refs(receipt['inputs'])
    artifacts = files.refs(receipt['artifacts'], root)
    paths = {key: files.path(value) for key, value in spec['paths'].items()}
    checkpoint_map = files.path(spec['checkpoint_map_path'])
    operations = files.path(spec['operation_policies_path'])
    rubric_path = files.path(spec['strict_rubric_path'])
    c.require(set(paths.values()) | {checkpoint_map, operations, rubric_path} <= inputs,
              'diagnostic_delivery_worker_inputs_incomplete')
    for path in inputs:
        if path.suffix == '.json':
            files.embedded(files.json(path))
    mapping = files.json(checkpoint_map)
    for entry in mapping.get('checkpoints', []):
        checkpoint = files.path(entry['path'])
        _safe_path(checkpoint, recursive=True)
        files.file(checkpoint / 'model.safetensors')
        files.json(checkpoint / 'config.json')
    rubric = files.json(rubric_path)
    checked = preview.checked_context(paths, checkpoint_map, operations,
        strict_rubric=rubric, diagnostic_context=context)
    candidate = checked['candidate']
    c.require(candidate['targetLocale'] == locale and candidate['releaseEligible'] is False,
              'diagnostic_delivery_candidate_locale_or_approval_changed')
    source = checked['source']
    c.require(source['review']['humanApproval'] is False and source['translationEligible'] is False
        and source['source']['approvedWindow']['humanApproval'] is False,
        'diagnostic_delivery_original_source_not_pending')
    for name in ('source', 'anchor', 'candidate', 'policy', 'adapter', 'registry', 'strict_rubric', 'diagnostic_context'):
        path = out / (name + '.json')
        c.require(path in artifacts and files.json(path) == checked[name], 'diagnostic_delivery_preview_snapshot_changed')
    manifest_path = out / 'manifest.json'
    manifest = files.json(manifest_path)
    expected = dict(schemaVersion=preview.SCOPED_MANIFEST_VERSION, status='preview_only',
        synthesisEligible=False, releaseEligible=False, targetLocale=locale,
        candidateJsonSha256=c.canonical_sha256(candidate), sourceJsonSha256=c.canonical_sha256(source),
        anchorJsonSha256=c.canonical_sha256(checked['anchor']),
        translationPolicySha256=candidate['translationPolicySha256'],
        previewRendererSha256=files.file(Path(preview.__file__).absolute()),
        strictRubricSha256=c.canonical_sha256(rubric), diagnosticContextSha256=c.canonical_sha256(context),
        humanAcceptance='pending', productionEligible=False)
    c.require(manifest_path in artifacts and manifest == expected, 'diagnostic_delivery_preview_manifest_changed')
    groups = candidate['groups']
    selected = spec.get('group_ids')
    c.require(selected is None or (type(selected) is list and len(selected) == len(groups)
        and set(selected) == {g['translationGroupId'] for g in groups}), 'diagnostic_delivery_incomplete_preview')
    units = []
    for index, _ in enumerate(groups):
        audio_path, unit_path = out / f'units/unit-{index:04d}.wav', out / f'receipts/unit-{index:04d}.json'
        c.require(audio_path in artifacts and unit_path in artifacts and not audio_path.with_suffix('.partial.wav').exists(),
                  'diagnostic_delivery_incomplete_preview')
        unit = files.json(unit_path)
        sound = preview.sound_identity(checked, index, seed=spec.get('seed', 42),
            dtype=spec.get('dtype', 'bfloat16'), attention=spec.get('attention', 'sdpa'), instruct=spec.get('instruct'))
        c.require(unit.get('schemaVersion') == preview.UNIT_VERSION and unit.get('status') == 'preview_only'
            and unit.get('candidateJsonSha256') == expected['candidateJsonSha256']
            and unit.get('previewContextSha256') == c.canonical_sha256(manifest)
            and unit.get('soundIdentity') == sound and unit.get('audioSha256') == files.file(audio_path)
            and unit.get('fullDecode') == 'pass', 'diagnostic_delivery_preview_unit_changed')
        decoded = preview.integrity.probe_full_decode(audio_path)
        duration = unit.get('durationSeconds')
        c.require(type(duration) in (int, float) and math.isfinite(duration) and duration > 0
            and duration == decoded['durationSeconds'], 'diagnostic_delivery_preview_duration_changed')
        units.append({'unitReceiptSha256': files.file(unit_path), 'audioSha256': files.file(audio_path),
                      'durationSeconds': duration, 'fullDecode': 'pass'})
    # The worker owns attempt/request and original deadline/snapshot semantics.
    # Its read-only validator permits later settled provider requests, without
    # requiring old snapshot hashes to equal the entire current live ledger.
    worker.validate_preview_receipt(root, subject, context, envelope)
    return dict(workerReceiptSha256=files.file(receipt_path), manifestSha256=files.file(manifest_path),
        candidateSha256=expected['candidateJsonSha256'], previewStatus='preview_only',
        machineTranslationStatus='pass', realHumanAcceptance='pending', units=units,
        pendingRealGates={gate: 'pending' for gate in PENDING_GATES})


def inspect_delivery(root, subject, context, previews, *, expected_locales):
    """Inspect exact locale worker receipts without mutating any ledger or file."""
    files = _Snapshot()
    root = files.path(root)
    context = diagnostic.validate_context(context)
    c.require(type(subject) is provider.DiagnosticProvider and subject.store.root == root / 'budget',
              'diagnostic_delivery_existing_provider_required')
    diagnostic.validate_runtime(context, run_id=subject.config['runId'], store_sha256=subject.store.store_sha256)
    c.require(context['runConfigSha256'] == c.canonical_sha256(subject.config), 'diagnostic_delivery_provider_changed')
    c.require(type(expected_locales) in (list, tuple) and expected_locales
        and len(set(expected_locales)) == len(expected_locales) and set(expected_locales) <= {'zh-Hans', 'ko', 'es'}
        and type(previews) is dict and set(previews) == set(expected_locales), 'diagnostic_delivery_locale_coverage_changed')
    state_path = root / 'budget' / budget.STORE_ID / 'provider-run/state.json'
    budget_path = root / 'budget' / budget.STORE_ID / 'state.json'
    state, ledger = files.json(state_path), files.json(budget_path)
    c.require(state['config'] == subject.config and state['authoritySha256'] == subject.store.authority_sha256
        and ledger['authority'] == subject.store.authority and ledger['storeSha256'] == subject.store.store_sha256,
        'diagnostic_delivery_existing_ledger_changed')
    c.require(all(row['state'] in ('returned', 'rejected') for row in state['requests'].values()),
              'diagnostic_delivery_unknown_provider_outcome')
    for key, row in ledger['reservations'].items():
        subject.store._validate_row(key, row)
        c.require(row['phase'] == 'result' and row['result']['executionStatus'] != 'outcome_unknown',
                  'diagnostic_delivery_unknown_budget_outcome')
    original = source_evidence.validate_prior_source_evidence(root, state, context)
    locales = {locale: _inspect_preview(root, subject, context, locale, previews[locale], files)
               for locale in expected_locales}
    c.require(source_evidence.validate_prior_source_evidence(root, state, context) == original,
              'diagnostic_delivery_source_evidence_changed')
    files.recheck()
    result = dict(schemaVersion=SCHEMA, status='diagnostic_traversal_complete',
        diagnosticContextSha256=c.canonical_sha256(context), sourceEvidence=original,
        providerStateFileSha256=files.hashes[state_path], budgetStateFileSha256=files.hashes[budget_path],
        locales=locales, sourceMachineStatus='unconfirmed_findings_human_pending',
        humanAcceptance='pending', productionEligible=False, formalAudioPackageCreated=False,
        publicationAuthorized=False, modelCalls=0,
        pendingRealGates={gate: 'pending' for gate in PENDING_GATES})
    return dict(result, resultSha256=c.canonical_sha256(result))
