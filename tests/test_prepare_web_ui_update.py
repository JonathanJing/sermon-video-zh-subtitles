"""Check production identity and preservation before UI-only Hosting updates."""
import json
import subprocess

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
    (public / 'fingerprint-worker.mjs').write_text('deployed acoustic matcher')
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
        'firebaseJsonSha256': staging.digest(base / 'firebase.json'),
        'baselineVersion': 'sites/' + target['site'] + '/versions/initial'})
    return base


def committed_ui(tmp_path, monkeypatch):
    repo = tmp_path / 'source-repo'
    source = repo / 'experiments/sermon-dubbing-poc/web'
    source.mkdir(parents=True)
    for name in ui.ui_files('production'):
        (source / name).write_text('new UI: ' + name)
    monkeypatch.setattr(ui.builder, 'RUNTIME_WEB_ROOT', source)
    monkeypatch.setattr(ui.builder, 'ROOT', repo)
    monkeypatch.setattr(ui.builder, 'runtime_web_files', lambda *_: ())
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    subprocess.run(['git', 'add', '.'], cwd=repo, check=True)
    subprocess.run(['git', '-c', 'user.name=Reader test', '-c', 'user.email=reader@example.invalid',
                    'commit', '-qm', 'Frozen UI source'], cwd=repo, check=True)
    return repo, source


def test_production_overlay_preserves_catalog_media_and_backend_config(tmp_path, monkeypatch):
    base = baseline(tmp_path)
    repo, _ = committed_ui(tmp_path, monkeypatch)
    # Unrelated work does not invalidate this scoped source binding.
    (repo / 'unrelated.txt').write_text('another agent is working')
    out = tmp_path / 'candidate'
    ui.prepare(base, out, environment='production')
    for name in ('old.mp3', 'multilingual-v3.json', 'fingerprint-worker.mjs'):
        assert (out / 'public' / name).read_bytes() == (base / 'public' / name).read_bytes()
    assert (out / 'firebase.json').read_bytes() == (base / 'firebase.json').read_bytes()
    config = staging.read(out / 'publish-config.json')
    assert config['intent']['project'] == 'ai-for-god-caption-dev'
    assert config['intent']['site'] == 'ai-for-god-sermon-audio'
    assert config['intent']['environment'] == 'production'
    assert config['intent']['channel'] == 'production_web'
    assert config['lease_bucket'] == 'ai-for-god-sermon-media-prod'
    assert config['routes']['production']['channels'] == ['production_web']
    plan = staging.read(out / 'ui-update-plan.json')
    assert plan['sourceCommit'] == subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
    assert plan['sourceFiles']['app.mjs'] == staging.digest(out / 'public/app.mjs')


@pytest.mark.parametrize('staged', [False, True])
def test_modified_copied_ui_rejected_before_output(tmp_path, monkeypatch, staged):
    base = baseline(tmp_path)
    repo, source = committed_ui(tmp_path, monkeypatch)
    (source / 'app.mjs').write_text('uncommitted UI')
    if staged:
        subprocess.run(['git', 'add', '.'], cwd=repo, check=True)
    out = tmp_path / 'candidate'
    with pytest.raises(ValueError, match='differs from recorded commit'):
        ui.prepare(base, out, environment='production')
    assert not out.exists()


def test_untracked_read_dependency_rejected_before_output(tmp_path, monkeypatch):
    base = baseline(tmp_path)
    _, source = committed_ui(tmp_path, monkeypatch)
    (source / 'extra.mjs').write_text('uncommitted dependency')
    monkeypatch.setattr(ui.builder, 'runtime_web_files', lambda *_: ('extra.mjs',))
    out = tmp_path / 'candidate'
    with pytest.raises(ValueError, match='differs from recorded commit'):
        ui.prepare(base, out, environment='production')
    assert not out.exists()


def test_modified_hosting_config_rejected_before_output(tmp_path):
    base = baseline(tmp_path)
    config = staging.read(base / 'firebase.json')
    config['hosting']['rewrites'][0]['run']['serviceId'] = 'another-backend'
    (base / 'firebase.json').write_text(json.dumps(config))
    out = tmp_path / 'candidate'
    with pytest.raises(ValueError, match='configuration differs from receipt'):
        ui.prepare(base, out, environment='production')
    assert not out.exists()


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


def test_production_overlay_is_accepted_by_dev_shell_without_copying_baseline_modules(tmp_path, monkeypatch):
    from scripts import firebase_dev_app_shell_update as shell
    base = baseline(tmp_path)
    repo, _ = committed_ui(tmp_path, monkeypatch)
    out = tmp_path / 'candidate'
    ui.prepare(base, out, environment='production')
    monkeypatch.setattr(shell, 'ROOT', repo)
    plan = shell.read_plan(out / 'public', out / 'ui-update-plan.json')
    replaced, _ = shell.shell_names(shell.dev.files(out / 'public'), plan)
    assert 'app.mjs' in replaced
    assert 'fingerprint-worker.mjs' not in replaced
    assert 'fingerprint-worker.mjs' not in plan['sourceFiles']
    assert (out / 'public/fingerprint-worker.mjs').read_bytes() == (base / 'public/fingerprint-worker.mjs').read_bytes()
