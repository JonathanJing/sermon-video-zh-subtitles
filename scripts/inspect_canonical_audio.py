"""Read-only Layer 3 inspection through the existing audio producer and gates.

Reconstructing a package validates existing media; it does not render audio or
write the reconstructed object. An independently saved package is still required.
"""
from scripts import build_target_language_audio_package as builder
from scripts import prepare_target_language_speech_job as handoff
from scripts import stage_formal_multilingual_dev as stage
from scripts.sermon_release_workflow import _safe_path
from scripts.sermon_workflow_jobs import _digest, _read


PATH_FIELDS = {
    'job': 'job', 'adapter': 'adapter', 'registry': 'registry',
    'clipTimelineMap': 'clip_timeline_map',
    'clipVoiceAuthorization': 'clip_voice_authorization',
    'sourceVoiceAuthorization': 'source_voice_authorization',
    'clipVoiceCapability': 'clip_voice_capability',
}
REQUIRED = {'job', 'adapter', 'registry', 'clipTimelineMap', 'renderManifest', 'artifactRoot', 'package'}
OPTIONAL = {'clipVoiceAuthorization', 'sourceVoiceAuthorization', 'clipVoiceCapability', 'humanReview', 'screening'}


def validate_configuration(config):
    if (not isinstance(config, dict) or not REQUIRED <= set(config)
            or set(config) - REQUIRED - OPTIONAL
            or any(not isinstance(value, str) or not value.strip() for value in config.values())):
        raise ValueError('invalid_audio_inspection_configuration')


def inspect(root, config, upstream_paths, read_package, hashes, locale):
    """Return hashes and gate evidence only; all review decisions pre-exist."""
    validate_configuration(config)
    prefix = 'audio.' + locale + '.'
    paths = {name: _safe_path(path) for name, path in upstream_paths.items()}
    for field, name in PATH_FIELDS.items():
        if field in config:
            read_package(root, config[field], hashes, prefix + field)
            paths[name] = _safe_path(root / config[field])
    read_package(root, config['renderManifest'], hashes, prefix + 'renderManifest')
    package = read_package(root, config['package'], hashes, prefix + 'package')
    handoff._validate_schema(package, 'sermon-target-language-audio-package-v1.schema.json', 'audio package')
    artifact_root = _safe_path(root / config['artifactRoot'], recursive=True)
    if not artifact_root.is_dir():
        raise ValueError('audio_artifacts_missing')
    # Capture the actual parsed upstream identities too. The caller checks these
    # against its Source/Text observation, preventing an intervening replacement.
    upstream = {name: _digest(_read(path)) for name, path in paths.items()}
    rebuilt = builder.build_package(paths, _safe_path(root / config['renderManifest']), artifact_root)
    if package['targetLocale'] != locale:
        raise ValueError('audio_locale_mismatch')
    reviewed = package['status'] == 'human_reviewed'
    review_fields = {'status', 'humanReview', 'downstreamInvalidationKey'}
    if reviewed:
        if ({k: v for k, v in package.items() if k not in review_fields}
                != {k: v for k, v in rebuilt.items() if k not in review_fields}
                or package['downstreamInvalidationKey'] != _digest({k: v for k, v in package.items()
                                                                      if k != 'downstreamInvalidationKey'})):
            raise ValueError('reviewed_audio_differs_from_producer')
    elif package != rebuilt:
        raise ValueError('audio_differs_from_producer')
    # Detect JSON input drift across the real producer validation pass.
    for name, path in paths.items():
        if _digest(_read(path)) != upstream[name]:
            raise ValueError('audio_input_changed_during_inspection')
    for field in ('renderManifest', 'package'):
        if _digest(_read(_safe_path(root / config[field]))) != hashes[prefix + field]:
            raise ValueError('audio_input_changed_during_inspection')
    result = {'outputSha256': hashes[prefix + 'package'], 'upstreamIdentities': upstream,
              'voiceAuthorizationSha256': _digest(upstream), 'listeningReviewSha256': None}
    if reviewed or 'humanReview' in config:
        if not reviewed or 'humanReview' not in config:
            raise ValueError('independent_audio_review_required')
        receipt = read_package(root, config['humanReview'], hashes, prefix + 'humanReview')
        version = receipt.get('schemaVersion')
        if version not in {'sermon-target-language-audio-human-review-receipt-v1',
                           'sermon-target-language-audio-human-review-receipt-v2'}:
            raise ValueError('unsupported_audio_review_version')
        handoff._validate_schema(receipt, version + '.schema.json', 'audio review')
        screening = None
        if 'screening' in config:
            screening = read_package(root, config['screening'], hashes, prefix + 'screening')
            handoff._validate_schema(screening, 'sermon-target-language-audio-screening-v1.schema.json', 'screening')
        stage.validate_audio_screening_review(package, receipt, screening)
        human = package['humanReview']
        candidate = _read(paths['candidate'])
        expected = {
            'targetLocale': locale, 'englishSourcePackageJsonSha256': upstream['source'],
            'targetLanguageCandidateJsonSha256': upstream['candidate'],
            'targetLanguageAudioPackageJsonSha256': hashes[prefix + 'package'],
            'trackSha256': package['track']['sha256'],
            'reviewedBy': human['reviewedBy'], 'reviewedAt': human['reviewedAt'],
            'reviewedUnitIds': [group['translationGroupId'] for group in candidate['groups']],
        }
        if (human['status'] != 'approved' or human['humanApproval'] is not True
                or human['fullPlayback'] != 'approved' or package['issues']
                or package['machineScreening']['status'] not in {'pass', 'requires_review'}
                or any(receipt.get(key) != value for key, value in expected.items())):
            raise ValueError('audio_review_not_bound')
        result['listeningReviewSha256'] = hashes[prefix + 'humanReview']
    return result
