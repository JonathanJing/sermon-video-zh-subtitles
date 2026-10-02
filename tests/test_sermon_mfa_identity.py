"""Offline identity receipts: real file hashes, synthetic MFA output, no model."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import sermon_mfa_identity as identity, sermon_review_contracts as c


def runtime_fixture(root):
    files = {}
    for name in ('mfa_executable', 'dictionary_path', 'acoustic_model'):
        path = root/'env'/'bin'/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(('synthetic never execute ' + name).encode())
        if name == 'mfa_executable': path.chmod(0o700)
        files[name] = {'path': str(path), 'sha256': c.bytes_sha256(path.read_bytes())}
    files.update(g2p_model=None, spoken_forms_path=None)
    return {'schemaVersion': 1, 'backend': 'macbook-local', 'runtime': {
        'version': '3.3.9', 'executionPlatform': 'Darwin', 'executionHost': 'private-old-host',
        'adapterSha256': c.bytes_sha256((Path(identity.__file__).resolve().parents[1]/identity.ADAPTER).read_bytes()),
        'files': files, 'nativeKalpy': {}, 'condaRecords': {}}}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(c.canonical_bytes(value))


def alignment_fixture(plan, runtime, chunks, segments):
    root = Path(plan['runDirectory'])/'mfa'
    root.mkdir(parents=True, exist_ok=True)
    write_json(root/'backend.json', runtime)
    values = runtime['runtime']; files = values['files']
    manifest_identity = {'schemaVersion': 1, 'adapterSha256': values['adapterSha256'],
        'audioSha256': plan['providerConfig']['sourceAudioSha256'], 'skippedEmptyReferenceChunks': [],
        'mfa': {**files['mfa_executable'], 'version': values['version']},
        'dictionarySha256': files['dictionary_path']['sha256'], 'acousticSha256': files['acoustic_model']['sha256'],
        'g2pSha256': None, 'spokenFormsSha256': None,
        'options': ['single_speaker', 'no_textgrid_cleanup', 'json', 'mono_16000_pcm16'],
        'chunks': [{**chunk, 'text': ' '.join(chunk['text'].split()), 'spokenWords': chunk['text'].lower().split(),
                    'mapping': []} for chunk in chunks]}
    run = root/'mfa_alignment'/hashlib.sha256(json.dumps(manifest_identity, sort_keys=True).encode()).hexdigest()
    run.mkdir(parents=True, exist_ok=True)
    manifest = run/'manifest.json'
    for row in segments:
        row['mfaManifest'] = str(manifest)
        row.pop('alignmentExecutionBackend', None)
    write_json(run/'segments.json', segments)
    output = run/'aligned/speaker/chunk_0000.json'
    write_json(output, {'synthetic': True, 'neverExecuted': True})
    (run/'dictionary.dict').write_bytes(b'synthetic dictionary output')
    write_json(manifest, {'schemaVersion': 1, 'identity': manifest_identity,
        'outputHashes': {'aligned/speaker/chunk_0000.json': c.bytes_sha256(output.read_bytes())},
        'dictionaryUsedSha256': c.bytes_sha256((run/'dictionary.dict').read_bytes()),
        'normalizationEvents': [], 'requires_operator_review': True, 'limitations': ['synthetic fixture']})
    for row in segments:
        row['alignmentExecutionBackend'] = 'macbook-local'
    write_json(Path(plan['runDirectory'])/'reference-chunks.json', chunks)
    return segments


class MFAIdentityTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.runtime = runtime_fixture(self.root)
        self.plan = {'runDirectory': str(self.root/'run'), 'executionIdentity': {'loadedProjectCodeSha256': {
            identity.ADAPTER: self.runtime['runtime']['adapterSha256']}}, 'providerConfig': {
                'runId': 'run-one', 'sourceAudioSha256': 'a'*64, 'sourceMediaSha256': 'b'*64,
                'sourceClipSha256': 'c'*64, 'sourceWindowSeconds': [10, 20]}}
        self.seed = deepcopy(self.runtime)
        self.seed['runtime']['adapterSha256'] = 'd'*64
        self.seed_path = self.root/'seed.json'; write_json(self.seed_path, self.seed)
        self.runtime['runtime']['executionHost'] = 'private-new-host'
        self.chunks = [{'id': 'fresh-diagnostic', 'start': 0., 'end': 10., 'text': 'Hello world.'}]
        self.aligned = alignment_fixture(self.plan, self.runtime, self.chunks,
            [{'id': 0, 'start': 0., 'end': 10., 'text': 'Hello world.'}])
        self.observed = Path(self.plan['runDirectory'])/'mfa/backend.json'
        self.enterContext(patch('subprocess.run', side_effect=AssertionError('no execution permitted')))
        self.enterContext(patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('no network permitted')))

    def inspect(self, **kwargs):
        return identity.validate_alignment(self.plan, self.seed_path, self.observed,
            aligned_segments=self.aligned, reference_chunks=self.chunks, **kwargs)

    def assert_artifact_rejection_receipt(self, error, *, preflight=None, observed_at=None):
        receipt = error.identity_comparison
        self.assertEqual(identity.validate_receipt(receipt), receipt)
        self.assertEqual(receipt['acceptance'], {'result': 'rejected',
            'rejectionReason': 'alignment_artifact_changed',
            'preflightReceiptSha256': c.canonical_sha256(preflight) if preflight is not None else None})
        self.assertEqual(receipt['observedAt'], observed_at)
        self.assertEqual(receipt['observationStatus'],
            'observed' if observed_at else 'historical_event_time_unavailable')
        rows = {row['field']: row for row in receipt['comparisons']}
        self.assertEqual(rows['alignment_artifacts'], {
            'category': 'execution_provenance', 'field': 'alignment_artifacts',
            'expectedSha256': c.canonical_sha256(True), 'observedSha256': c.canonical_sha256(False),
            'hashSemantics': 'canonical_json_value', 'matchSemantics': 'bound_alignment_artifacts',
            'matchResult': 'mismatch', 'rejectionReason': 'alignment_artifact_changed',
            'evidenceRefs': ['frozen_plan', 'execution_runtime', 'alignment_artifacts']})
        self.assertEqual(next(ref['sha256'] for ref in receipt['evidence']
            if ref['role'] == 'alignment_artifacts'), c.canonical_sha256(None))
        for field in (*identity.DEPENDENCIES, 'executionHost'):
            self.assertEqual(rows[field]['expectedSha256'], c.canonical_sha256(self.seed['runtime'][field]))
            self.assertEqual(rows[field]['observedSha256'], c.canonical_sha256(self.runtime['runtime'][field]))
        self.assertTrue(all(row['matchResult'] == 'match' for field, row in rows.items()
            if field != 'alignment_artifacts'))
        for private in (str(self.root), 'private-old-host', 'private-new-host',
                        'Hello world.', 'Wrong transcript.', 'tampered output'):
            self.assertNotIn(private, json.dumps(receipt))

    def test_current_frozen_adapter_and_host_evolution_accepted_with_safe_receipt(self):
        preflight = identity.require_accepted(identity.preflight(self.plan, self.seed_path))
        result = identity.require_accepted(self.inspect(preflight_receipt=preflight))
        self.assertEqual(result, self.inspect(preflight_receipt=preflight, expected_receipt=result))
        raw = json.dumps(result)
        for private in (str(self.root), 'private-old-host', 'private-new-host', 'Hello world.'):
            self.assertNotIn(private, raw)
        self.assertEqual(result['acceptance']['preflightReceiptSha256'], c.canonical_sha256(preflight))
        host = next(row for row in result['comparisons'] if row['field'] == 'executionHost')
        self.assertNotEqual(host['expectedSha256'], host['observedSha256'])
        self.assertEqual(host['matchSemantics'], 'record_execution_provenance')

    def test_dependency_metadata_unknown_runtime_and_unfrozen_adapter_rejected(self):
        for key, value in (('version', 'unknown-version'), ('adapterSha256', 'f'*64),
                           ('executionPlatform', 'Linux'), ('unrecognized', 'raw-secret')):
            changed = deepcopy(self.runtime); changed['runtime'][key] = value
            write_json(self.observed, changed)
            with self.subTest(key=key), self.assertRaises(c.ContractError) as raised:
                identity.require_accepted(self.inspect())
            self.assertIsNotNone(raised.exception.identity_comparison)
            self.assertNotIn('raw-secret', json.dumps(raised.exception.identity_comparison))
        write_json(self.observed, self.runtime)

    def test_changed_missing_dependency_and_unlisted_native_record_fail_health(self):
        path = Path(self.runtime['runtime']['files']['acoustic_model']['path'])
        raw = path.read_bytes()
        for operation in ('changed', 'missing'):
            if operation == 'changed': path.write_bytes(b'corrupt model')
            else: path.unlink()
            with self.subTest(operation=operation), self.assertRaisesRegex(c.ContractError, 'dependency_file_changed'):
                identity.require_accepted(identity.preflight(self.plan, self.seed_path))
            path.write_bytes(raw)
        executable = Path(self.runtime['runtime']['files']['mfa_executable']['path'])
        executable.chmod(0o600)
        with self.assertRaisesRegex(c.ContractError, 'dependency_file_changed'):
            identity.require_accepted(identity.preflight(self.plan, self.seed_path))
        executable.chmod(0o700)
        record = path.parent.parent/'conda-meta/extra.json'; write_json(record, {'unexpected': True})
        with self.assertRaisesRegex(c.ContractError, 'dependency_file_changed'):
            identity.require_accepted(identity.preflight(self.plan, self.seed_path))

    def test_preflight_rejects_unfrozen_current_adapter_without_dispatch(self):
        self.plan['executionIdentity']['loadedProjectCodeSha256'][identity.ADAPTER] = 'e'*64
        with self.assertRaisesRegex(c.ContractError, 'producer_not_frozen'):
            identity.require_accepted(identity.preflight(self.plan, self.seed_path))

    def test_receipt_tamper_stale_host_cross_run_and_input_binding_rejected(self):
        preflight = identity.preflight(self.plan, self.seed_path)
        result = self.inspect(preflight_receipt=preflight)
        changed = deepcopy(result); changed['comparisons'][1]['observedSha256'] = 'e'*64
        with self.assertRaisesRegex(c.ContractError, 'receipt_invalid'):
            identity.validate_receipt(changed)
        changed = deepcopy(result); changed['comparisons'][0]['privatePath'] = '/private/sensitive'
        with self.assertRaisesRegex(c.ContractError, 'receipt_invalid'):
            identity.validate_receipt(changed)
        self.runtime['runtime']['executionHost'] = 'another-host'; write_json(self.observed, self.runtime)
        with self.assertRaisesRegex(c.ContractError, 'receipt_changed'):
            self.inspect(preflight_receipt=preflight, expected_receipt=result)
        self.plan['providerConfig']['runId'] = 'different-run'
        with self.assertRaisesRegex(c.ContractError, 'preflight_changed'):
            identity.require_accepted(self.inspect(preflight_receipt=preflight))
        self.plan['providerConfig']['sourceAudioSha256'] = 'f'*64
        with self.assertRaisesRegex(c.ContractError, 'alignment_artifact_changed'):
            identity.require_accepted(self.inspect())

    def test_manifest_output_reference_and_cross_run_paths_fail(self):
        manifest = Path(self.aligned[0]['mfaManifest'])
        output = manifest.parent/'aligned/speaker/chunk_0000.json'
        raw = output.read_bytes(); output.write_bytes(b'tampered output')
        with self.assertRaisesRegex(c.ContractError, 'alignment_artifact_changed'):
            identity.require_accepted(self.inspect())
        output.write_bytes(raw)
        self.chunks[0]['text'] = 'Wrong transcript.'
        with self.assertRaisesRegex(c.ContractError, 'alignment_artifact_changed'):
            identity.require_accepted(self.inspect())
        self.chunks[0]['text'] = 'Hello world.'
        self.plan['runDirectory'] = str(self.root/'other-run')
        with self.assertRaisesRegex(c.ContractError, 'input_changed'):
            identity.require_accepted(self.inspect())

    def test_artifact_contract_errors_attach_safe_receipt_with_expected_receipt(self):
        observed_at = '2026-01-01T00:00:00Z'
        preflight = identity.require_accepted(identity.preflight(self.plan, self.seed_path,
            observed_at=observed_at))
        accepted = identity.require_accepted(self.inspect(preflight_receipt=preflight, observed_at=observed_at))
        original_accepted = deepcopy(accepted)
        root = Path(self.plan['runDirectory'])
        write_json(root/'mfa-identity-preflight.json', preflight)
        write_json(root/'mfa-identity-comparison.json', accepted)
        output = Path(self.aligned[0]['mfaManifest']).parent/'aligned/speaker/chunk_0000.json'
        raw = output.read_bytes()
        for mutation, code in (('raw_output', 'alignment_output_changed'),
                               ('reference_chunks', 'alignment_input_changed')):
            with self.subTest(mutation=mutation):
                output.write_bytes(b'tampered output' if mutation == 'raw_output' else raw)
                self.chunks[0]['text'] = 'Wrong transcript.' if mutation == 'reference_chunks' else 'Hello world.'
                before = {path: path.read_bytes() for path in root.rglob('*') if path.is_file()}
                with self.assertRaisesRegex(c.ContractError, code) as underlying:
                    identity._alignment_artifacts(self.plan, self.runtime['runtime'], self.aligned,
                        self.chunks, identity._file_sha)
                # ContractError already belongs to validate_alignment's ValueError handler.
                self.assertIsInstance(underlying.exception, ValueError)
                with self.assertRaisesRegex(c.ContractError, 'mfa_identity_alignment_artifact_changed') as raised:
                    self.inspect(preflight_receipt=preflight, expected_receipt=accepted)
                self.assert_artifact_rejection_receipt(raised.exception, preflight=preflight, observed_at=observed_at)
                self.assertEqual(accepted, original_accepted)
                self.assertEqual(before, {path: path.read_bytes() for path in root.rglob('*') if path.is_file()})

    def test_legacy_artifact_rejection_preserves_history_without_backfilling_receipts(self):
        root = Path(self.plan['runDirectory'])
        evidence = {'schemaVersion': 'sermon-fresh-diagnostic-source-evidence-v1',
            'asr': {}, 'sourceCheck': {}, 'alignmentMode': 'fresh_local_mfa',
            'sourceCanonicalSha256': 'a'*64, 'anchorCanonicalSha256': 'b'*64,
            'alignedSegmentsSha256': c.canonical_sha256(self.aligned), 'sourceReviewStatus': 'pending',
            'sourceReviewContentSha256': 'c'*64, 'contextSha256': 'd'*64,
            'productionEligible': False, 'humanAcceptance': 'pending'}
        write_json(root/'source-evidence.json', evidence)
        recipe = {'runMFA': True, 'files': {'local_runtime_path': {
            'path': str(self.seed_path), 'sha256': c.bytes_sha256(self.seed_path.read_bytes())}}}
        output = Path(self.aligned[0]['mfaManifest']).parent/'aligned/speaker/chunk_0000.json'
        raw = output.read_bytes()
        for mutation in ('raw_output', 'reference_chunks'):
            with self.subTest(mutation=mutation):
                output.write_bytes(b'tampered output' if mutation == 'raw_output' else raw)
                chunks = deepcopy(self.chunks)
                if mutation == 'reference_chunks': chunks[0]['text'] = 'Wrong transcript.'
                write_json(root/'reference-chunks.json', chunks)
                before = {path: path.read_bytes() for path in root.rglob('*') if path.is_file()}
                with self.assertRaisesRegex(c.ContractError, 'mfa_identity_alignment_artifact_changed') as raised:
                    identity.inspect_source_alignment(self.plan, recipe, evidence, self.aligned)
                self.assert_artifact_rejection_receipt(raised.exception)
                self.assertEqual(before, {path: path.read_bytes() for path in root.rglob('*') if path.is_file()})
                self.assertFalse((root/'mfa-identity-preflight.json').exists())
                self.assertFalse((root/'mfa-identity-comparison.json').exists())

    def test_legacy_manifest_requires_exact_producer_raw_output_set(self):
        manifest_path = Path(self.aligned[0]['mfaManifest'])
        original = json.loads(manifest_path.read_bytes())
        raw_output = manifest_path.parent/'aligned/speaker/chunk_0000.json'
        raw_bytes = raw_output.read_bytes()
        alternate = manifest_path.parent/'aligned/speaker/chunk_0001.json'
        alternate.write_bytes(raw_bytes)
        replacements = (
            {},
            {'dictionary.dict': original['dictionaryUsedSha256']},
            {**original['outputHashes'], 'dictionary.dict': original['dictionaryUsedSha256']},
            {'aligned/speaker/chunk_0001.json': c.bytes_sha256(raw_bytes)},
        )
        for index, outputs in enumerate(replacements):
            changed = deepcopy(original); changed['outputHashes'] = outputs
            write_json(manifest_path, changed)
            # Reproduce the historical path without a frozen v2 comparison.
            # Omission/substitution must fail whether the raw file exists or not.
            for exists in (True, False):
                if exists: raw_output.write_bytes(raw_bytes)
                elif raw_output.exists(): raw_output.unlink()
                with self.subTest(case=index, rawFileExists=exists), self.assertRaisesRegex(
                        c.ContractError, 'alignment_artifact_changed'):
                    identity.require_accepted(self.inspect(observed_at=None))
        raw_output.write_bytes(raw_bytes); write_json(manifest_path, original)
        identity.require_accepted(self.inspect(observed_at=None))

    def test_historical_producer_uses_parent_frozen_bytes_and_no_fabricated_time(self):
        # Inspectors evolve independently; post-alignment does not consult the
        # current repository adapter. Existing closed-parent migration is separate.
        with patch.object(identity, '_file_sha', wraps=identity._file_sha) as hasher:
            result = identity.require_accepted(self.inspect(observed_at=None))
        self.assertIsNone(result['observedAt'])
        self.assertEqual(result['observationStatus'], 'historical_event_time_unavailable')
        self.assertFalse(any(str(call.args[0]).endswith(identity.ADAPTER) for call in hasher.call_args_list))


if __name__ == '__main__':
    unittest.main()
