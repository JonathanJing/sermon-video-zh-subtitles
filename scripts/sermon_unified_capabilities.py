"""Read-only, pre-production consumer capability checks; never approve future outputs."""
from __future__ import annotations
import argparse
import hashlib
import json
import shutil
import struct
import subprocess
from pathlib import Path
from scripts import delivery_contract as d
from scripts import sermon_unified_reviews as reviews
from scripts import target_language_policy as policies
from scripts import prepare_target_language_speech_job as speech

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'sermon-unified-consumer-capabilities-v2'
LEGACY_VERSION = 'sermon-unified-consumer-capabilities-v1'
SCHEMAS = {
    'source': 'sermon-english-source-package-v1',
    'candidate': 'sermon-target-language-candidate-v2',
    'speechJob': 'sermon-target-language-speech-job-v2',
    'audio': 'sermon-target-language-audio-package-v1',
    'study': 'sermon-study-artifact-v1',
    'catalog': 'sermon-multilingual-catalog-v3',
    'release': 'sermon-target-language-release-package-v3',
}
MACHINE_VERSION = 'sermon-unified-consumer-capabilities-v3'
# v3 also binds the machine-checked delivery schemas; human-reviewed locales keep catalog v3 / release v3.
MACHINE_SCHEMAS = {
    'machineCatalog': 'sermon-multilingual-catalog-v4',
    'machineRelease': 'sermon-target-language-release-package-v4',
    'machineContent': 'sermon-full-video-text-content-v3',
}


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def file_sha(path):
    with Path(path).open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256')
    return digest.hexdigest()


def pcm_roundtrip():
    """Exercise installed encoder and decoder through pipes, without temp files."""
    executable = shutil.which('ffmpeg')
    d.require(executable, 'consumer_encoder_decoder_missing:ffmpeg')
    pcm = b''.join(struct.pack('<h', (n % 100 - 50) * 100) for n in range(16000))
    prefix = [executable, '-hide_banner', '-loglevel', 'error', '-nostdin']
    encoded = subprocess.run(prefix + ['-f', 's16le', '-ar', '16000', '-ac', '1', '-i', 'pipe:0',
        '-c:a', 'pcm_s16le', '-f', 'wav', 'pipe:1'], input=pcm, capture_output=True, timeout=30, check=True).stdout
    decoded = subprocess.run(prefix + ['-i', 'pipe:0', '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le',
        '-f', 's16le', 'pipe:1'], input=encoded, capture_output=True, timeout=30, check=True).stdout
    d.require(decoded == pcm, 'consumer_pcm_roundtrip_mismatch')
    return {'sampleRateHz': 16000, 'channels': 1, 'format': 's16le', 'frames': 16000,
            'pcmSha256': hashlib.sha256(pcm).hexdigest(), 'status': 'passed',
            'executable': str(Path(executable).resolve()), 'executableSha256': file_sha(executable)}


def validate_voice(source, locale, adapter, registry, attestation):
    # preview_only here validates registry identity, NOT production permission.
    speech.validate_adapter(adapter, locale, registry, preview_only=True)
    reviews.schema(attestation, 'sermon-source-user-voice-attestation-v2.schema.json')
    window = {key: source['window'][key] for key in ('startSeconds', 'endSeconds')}
    d.require(attestation['sourceId'] == source['sourceId']
        and attestation['sourceMediaSha256'] == source['mediaSha256']
        and attestation['mediaDurationSeconds'] == source['durationSeconds']
        and attestation['approvedWindow'] == window
        and locale in attestation['targetLocales']
        and attestation['speakerId'] == adapter['speakerId']
        and attestation['voiceCheckpointSha256'] == adapter['conditioningSha256']
        and attestation['userStatement'].strip()
        and speech._reviewed_at(attestation['recordedAt']), 'consumer_voice_attestation_binding_changed')
    speaker = next(row for row in registry['speakers'] if row['speakerId'] == adapter['speakerId'])
    capability = next(row for row in speaker['localeCapabilities'] if row['targetLocale'] == locale)
    d.require(adapter['capabilityStatus'] == 'verified' and capability['status'] == 'human_reviewed'
              and bool(capability['reviewEvidence']), 'consumer_voice_locale_not_verified')
    return {'speakerId': adapter['speakerId'], 'checkpointSha256': adapter['conditioningSha256'],
            'attestationValidated': True, 'candidateBoundAuthorizationValidated': False}


def inspect(config_path):
    path = Path(config_path).resolve()
    config_bytes = path.read_bytes()
    value = json.loads(config_bytes)
    required = {'schemaVersion', 'source', 'bindings', 'locales', 'terminology', 'releaseIntents', 'routes', 'targetSchemaVersions'}
    d.require(set(value) in (required, required | {'inputSnapshotSha256'}), 'consumer_configuration_fields_invalid')
    d.require(value['schemaVersion'] in (VERSION,LEGACY_VERSION,MACHINE_VERSION), 'consumer_configuration_version_invalid')
    schemas = dict(SCHEMAS)
    if value['schemaVersion']==LEGACY_VERSION:
        schemas['release']='sermon-target-language-release-package-v2'
    if value['schemaVersion']==MACHINE_VERSION:
        schemas.update(MACHINE_SCHEMAS)
    base = path.parent
    inputs = {}
    def capture(name, ref, *, json_value=True):
        p = (base / ref).resolve()
        payload = p.read_bytes()
        inputs[name] = {'path': str(p), 'sha256': hashlib.sha256(payload).hexdigest()}
        return json.loads(payload) if json_value else p
    for name, row in value['bindings'].items():
        capture('binding:' + name, row['path'])
        d.require(inputs['binding:' + name]['sha256'] == row['sha256'], 'consumer_source_binding_changed:' + name)
    reviews.validate_window(value, base=base)
    source = value['source']
    d.require(0 <= source['window']['startSeconds'] < source['window']['endSeconds'] <= source['durationSeconds'], 'consumer_window_invalid')
    terminology = capture('terminology', value['terminology'], json_value=False)
    d.require(isinstance(value['locales'], dict) and bool(value['locales']), 'consumer_locales_required')
    locale_results = {}
    for locale, row in value['locales'].items():
        d.require(set(row) in ({'policy','adapter','registry','voiceAttestation'},
                              {'policy','rubric','adapter','registry','voiceAttestation'}), 'consumer_locale_inputs_invalid:' + locale)
        artifacts = {key: capture(locale + ':' + key, ref) for key, ref in row.items()}
        policy = artifacts['policy']
        d.require(policy['targetLocale'] == locale, 'consumer_policy_locale_changed')
        result = (policies.validate_strict_policy(policy, artifacts['rubric'], series_table=terminology)
                  if policy['schemaVersion'] == policies.POLICY_V3 else policies.validate_policy(policy, series_table=terminology))
        d.require(result['productionPolicyReady'], 'consumer_policy_not_ready:' + ','.join(result['unresolved']))
        locale_results[locale] = {'policySha256': d.sha(policy), 'policyFileSha256': inputs[locale + ':policy']['sha256'], **validate_voice(source, locale,
            artifacts['adapter'], artifacts['registry'], artifacts['voiceAttestation'])}
    d.require(set(value['releaseIntents']) == {'dev', 'production'}, 'consumer_both_environments_required')
    d.require(set(value['routes']) == {'dev', 'production'}, 'consumer_routes_invalid')
    for environment, intent in value['releaseIntents'].items():
        d.require(intent.get('environment') == environment, 'consumer_environment_changed')
        d.validate_intent(intent, value['routes'])
    d.require(value['releaseIntents']['dev']['site'] != value['releaseIntents']['production']['site'], 'consumer_environments_share_site')
    d.require(value['targetSchemaVersions'] == schemas, 'consumer_target_schema_versions_unsupported')
    for key, version in schemas.items():
        capture('schema:' + key, str(ROOT / 'schemas' / (version + '.schema.json')))
    codec = pcm_roundtrip()
    inputs['encoderDecoder'] = {'path': codec['executable'], 'sha256': codec['executableSha256']}
    # Include semantic configuration, with only the self-referential snapshot omitted.
    config = {key: item for key, item in value.items() if key != 'inputSnapshotSha256'}
    snapshot = d.sha({'configuration': config, 'inputs': inputs})
    if 'inputSnapshotSha256' in value:
        d.require(snapshot == value['inputSnapshotSha256'], 'consumer_input_snapshot_changed')
    d.require(path.read_bytes() == config_bytes and all(file_sha(row['path']) == row['sha256'] for row in inputs.values()), 'consumer_input_changed_during_inspection')
    return {'schemaVersion': value['schemaVersion'], 'targetSchemaVersions':schemas, 'status': 'capabilities_verified', 'snapshotBound': 'inputSnapshotSha256' in value,
            'inputSnapshotSha256': snapshot, 'inputHashes': inputs, 'configSha256': hashlib.sha256(config_bytes).hexdigest(),
            'sourceIdentity': source, 'locales': locale_results, 'codec': codec,
            'futureArtifactsValidated': False, 'modelCalls': 0,
            'requiredLaterGates': ['english_source_package', 'target_candidate', 'candidate_bound_voice_authorization',
                                   'audio_package', 'study_reviews', 'release_package', 'client_acceptance']}


def require_machine_capabilities(config_path):
    """Recheck frozen consumer evidence before accepting any machine waiver."""
    result = inspect(config_path)
    d.require(result['schemaVersion'] == MACHINE_VERSION and result['snapshotBound']
              and all(result['targetSchemaVersions'].get(key) == version
                      for key, version in MACHINE_SCHEMAS.items()),
              'consumer_machine_capabilities_required')
    return result


def freeze(config_path, output_path):
    path, output = Path(config_path).resolve(), Path(output_path).resolve()
    d.require(path.parent == output.parent, 'consumer_freeze_requires_same_directory_for_relative_paths')
    result = inspect(path)
    value = read(path)
    value['inputSnapshotSha256'] = result['inputSnapshotSha256']
    with output.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    return inspect(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('--freeze-out', type=Path)
    args = parser.parse_args()
    print(json.dumps(freeze(args.config, args.freeze_out) if args.freeze_out else inspect(args.config), ensure_ascii=False, indent=2))
