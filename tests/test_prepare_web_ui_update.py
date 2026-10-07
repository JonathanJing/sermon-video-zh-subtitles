"""Check production identity and preservation before UI-only Hosting updates."""
import json

import pytest

from scripts import prepare_dev_simulated_publication as staging
from scripts import prepare_dev_web_ui_update as ui


def baseline(tmp_path, environment='production'):
    target = staging.hosting_target(environment)
    base = tmp_path / 'baseline'
    public = base / 'public'
    public.mkdir(parents=True)
    (public / 'multilingual-v3.json').write_text(json.dumps({'pages': []}))
    (public / 'old.mp3').write_bytes(b'existing approved audio')
    (public / 'index.html').write_text('old UI')
    config = {'hosting': {'site': target['site'], 'public': 'public', 'rewrites': [
        {'source': '/api/**', 'run': {'serviceId': 'sermon-feedback-api', 'region': 'us-west1'}}]}}
    staging.write(base / 'firebase.json', config)
    catalog_sha = staging.digest(public / 'multilingual-v3.json')
    staging.write(base / 'seal-report.json', {'catalogSha256': catalog_sha,
                                            'files': staging.files_report(public)})
    staging.write(base / 'baseline-receipt.json', {
        **{key: target[key] for key in ('project', 'site', 'origin')},
        'status': 'complete_verified_not_deployed', 'catalogSha256': catalog_sha,
        'baselineVersion': 'sites/' + target['site'] + '/versions/initial'})
    return base


def test_production_overlay_preserves_catalog_media_and_backend_config(tmp_path, monkeypatch):
    base = baseline(tmp_path)
    source = tmp_path / 'source'
    source.mkdir()
    for name in ui.UI_FILES:
        (source / name).write_text('new UI: ' + name)
    monkeypatch.setattr(ui.builder, 'RUNTIME_WEB_ROOT', source)
    monkeypatch.setattr(ui.builder, 'runtime_web_files', lambda: None)
    out = tmp_path / 'candidate'
    ui.prepare(base, out, environment='production')
    for name in ('old.mp3', 'multilingual-v3.json'):
        assert (out / 'public' / name).read_bytes() == (base / 'public' / name).read_bytes()
    assert (out / 'firebase.json').read_bytes() == (base / 'firebase.json').read_bytes()
    config = staging.read(out / 'publish-config.json')
    assert config['intent']['project'] == 'ai-for-god-caption-dev'
    assert config['intent']['site'] == 'ai-for-god-sermon-audio'
    assert config['intent']['environment'] == 'production'
    assert config['intent']['channel'] == 'production_web'
    assert config['lease_bucket'] == 'ai-for-god-sermon-media-prod'
    assert config['routes']['production']['channels'] == ['production_web']


@pytest.mark.parametrize('environment,requested', [('dev', 'production'), ('production', 'dev')])
def test_cross_environment_baseline_rejected_before_output(tmp_path, environment, requested):
    base = baseline(tmp_path, environment)
    out = tmp_path / 'candidate'
    with pytest.raises(ValueError, match='target differs'):
        ui.prepare(base, out, environment=requested)
    assert not out.exists()
    with pytest.raises(ValueError, match='target differs'):
        staging.publication_config(base, out, environment=requested)


@pytest.mark.parametrize('field,value', [('status', 'outcome_unknown'),
    ('catalogSha256', 'stale'), ('baselineVersion', 'sites/another-site/versions/initial')])
def test_unbound_baseline_rejected_before_output(tmp_path, field, value):
    base = baseline(tmp_path)
    path = base / 'baseline-receipt.json'
    receipt = staging.read(path)
    path.write_text(json.dumps({**receipt, field: value}))
    out = tmp_path / 'candidate'
    with pytest.raises(ValueError, match='live-bound'):
        ui.prepare(base, out, environment='production')
    assert not out.exists()


def test_unknown_environment_rejected():
    with pytest.raises(ValueError, match='Unknown Hosting environment'):
        staging.hosting_target('anything-else')


def test_prior_unknown_production_outcome_cannot_start_another_publish(tmp_path):
    base = baseline(tmp_path)
    staging.write(base / 'deployment-attempt-v2.json', {'status': 'outcome_unknown'})
    with pytest.raises(ValueError, match='uncertain or differs'):
        staging.publication_config(base, tmp_path / 'candidate', environment='production')
