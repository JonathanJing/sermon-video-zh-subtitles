"""Read-only existing formal-dev Layer 4 candidate inspection."""
from scripts import prepare_target_language_speech_job as handoff
from scripts import stage_formal_multilingual_dev as stage
from scripts.sermon_release_workflow import _safe_path
from scripts.sermon_workflow_jobs import _digest


def validate_configuration(config):
    if (not isinstance(config, dict) or set(config) != {'package', 'assetRoot', 'contentReview'}
            or any(not isinstance(value, str) or not value.strip() for value in config.values())):
        raise ValueError('invalid_release_inspection_configuration')


def inspect(root, config, *, page_id, locale, source, candidate, audio_path,
            audio_sha256, read_package, hashes, speech_job_path):
    validate_configuration(config)
    prefix = 'release.' + locale + '.'
    release = read_package(root, config['package'], hashes, prefix + 'package')
    handoff._validate_schema(release, 'sermon-target-language-release-package-v1.schema.json', 'release')
    read_package(root, config['contentReview'], hashes, prefix + 'contentReview')
    audio = read_package(root, str(audio_path), hashes, prefix + 'audio')
    if _digest(audio) != audio_sha256:
        raise ValueError('release_audio_changed_during_inspection')
    assets = _safe_path(root / config['assetRoot'], recursive=True)
    files, _ = stage.validate_release_assets(
        page_id=page_id, locale=locale, asset_root=assets, source=source, candidate=candidate,
        audio=audio, audio_path=_safe_path(audio_path), release=release,
        content_review_path=_safe_path(root / config['contentReview']),
        speech_job_path=_safe_path(speech_job_path))
    # All asset bytes are checked against the declared hashes by the shared gate.
    hashes[prefix + 'assets'] = _digest({url: sha for url, (_, sha) in files.items()})
    for field in ('package', 'contentReview'):
        expected = hashes[prefix + field]
        value = read_package(root, config[field], hashes, prefix + field)
        if _digest(value) != expected:
            raise ValueError('release_input_changed_during_inspection')
    return hashes[prefix + 'package']
