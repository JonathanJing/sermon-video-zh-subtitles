import hashlib
import json
from pathlib import Path
import pytest
from scripts import guarded_hosting_publish as p


def setup(tmp_path):
    public = tmp_path / 'public'; public.mkdir()
    data = b'{"pages": []}'
    (public / 'multilingual-v3.json').write_bytes(data)
    sha = hashlib.sha256(data).hexdigest()
    report = {'catalogSha256': sha, 'files': [{'path': '/multilingual-v3.json', 'sha256': sha, 'bytes': len(data)}]}
    (tmp_path / 'seal-report.json').write_text(json.dumps(report))
    intent = {'schemaVersion': 'sermon-release-intent-v1', 'environment': 'dev', 'channel': 'dev', 'project': 'project', 'site': 'site', 'origin': 'https://site.web.app'}
    return intent, data, sha


class Remote:
    def __init__(self): self.held = False; self.version = 'old'; self.deleted = False
    def __call__(self, method, url, **kwargs):
        if '/channels/live' in url: return {'release': {'version': {'name': 'sites/site/versions/' + self.version}}}
        if method == 'POST':
            if self.held: raise ValueError('HTTP 412')
            self.held = True
            assert 'ifGenerationMatch=0' in url
            return {'generation': '5'}
        if method == 'GET': return {'generation': '5'}
        if method == 'DELETE':
            assert 'ifGenerationMatch=5' in url
            self.held = False; self.deleted = True
            return {}


def test_remote_lease_success_and_repeat_refusal(tmp_path):
    intent, data, sha = setup(tmp_path); remote = Remote()
    def run(*args, **kwargs): remote.version = 'new'
    args = dict(intent=intent, routes={'dev': intent}, baseline_version='sites/site/versions/old', baseline_catalog_sha=sha, lease_bucket='bucket', request=remote, reader=lambda url: (200, data), run=run)
    receipt = p.publish(tmp_path, **args)
    assert receipt['status'] == 'deployed' and remote.deleted
    with pytest.raises(ValueError, match='Existing attempt'):
        p.publish(tmp_path, **args)


def test_concurrent_version_change_rebuilds_without_deployment(tmp_path):
    intent, data, sha = setup(tmp_path); remote = Remote(); remote.version = 'other'
    def run(*args, **kwargs): pytest.fail('Deployment must not run')
    with pytest.raises(ValueError, match='Live version changed'):
        p.publish(tmp_path, intent=intent, routes={'dev': intent}, baseline_version='sites/site/versions/old', baseline_catalog_sha=sha, lease_bucket='bucket', request=remote, reader=lambda url: (200, data), run=run)
    assert remote.deleted
    assert json.loads((tmp_path / 'deployment-attempt-v2.json').read_text())['status'] == 'rebuild_required'


def test_unknown_deploy_retains_lease_and_reconciles_explicitly(tmp_path):
    intent, data, sha = setup(tmp_path); remote = Remote()
    def run(*args, **kwargs):
        remote.version = 'new'
        raise TimeoutError('unknown remote outcome')
    with pytest.raises(TimeoutError):
        p.publish(tmp_path, intent=intent, routes={'dev': intent}, baseline_version='sites/site/versions/old', baseline_catalog_sha=sha, lease_bucket='bucket', request=remote, reader=lambda url: (200, data), run=run)
    assert remote.held
    result = p.reconcile(tmp_path, request=remote, reader=lambda url: (200, data), confirmed_version='sites/site/versions/new')
    assert result['status'] == 'deployed' and remote.deleted
