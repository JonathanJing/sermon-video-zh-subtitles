import hashlib
import json
import pytest
from scripts import guarded_hosting_publish as p


class Remote:
    def __init__(self): self.held = False; self.version = 'old'; self.deleted = False
    def __call__(self, method, url, **kwargs):
        if '/channels/live' in url: return {'release': {'version': {'name': 'sites/site/versions/' + self.version}}}
        if method == 'POST':
            if self.held: raise ValueError('HTTP 412')
            self.held = True
            return {'generation': '5'}
        if method == 'GET': return {'generation': '5'}
        if method == 'DELETE':
            assert 'ifGenerationMatch=5' in url
            self.held = False; self.deleted = True
            return {}


def test_deployed_receipt_with_failed_lease_release_is_recoverable(tmp_path):
    public = tmp_path / 'public'; public.mkdir()
    data = b'{"pages": []}'
    (public / 'multilingual-v3.json').write_bytes(data)
    sha = hashlib.sha256(data).hexdigest()
    report = {'catalogSha256': sha, 'files': [{'path': '/multilingual-v3.json', 'sha256': sha, 'bytes': len(data)}]}
    (tmp_path / 'seal-report.json').write_text(json.dumps(report))
    intent = {'schemaVersion': 'sermon-release-intent-v1', 'environment': 'dev', 'channel': 'dev', 'project': 'project', 'site': 'site', 'origin': 'https://site.web.app'}
    remote = Remote()
    def run(*args, **kwargs): remote.version = 'new'
    failing = {'on': True}
    def flaky(method, url, **kwargs):
        if method == 'DELETE' and failing['on']: raise ValueError('Remote operation rejected: HTTP 503')
        if method == 'GET' and '/channels/live' not in url and not remote.held: raise ValueError('Remote operation rejected: HTTP 404')
        return remote(method, url, **kwargs)
    with pytest.raises(ValueError, match='HTTP 503'):
        p.publish(tmp_path, intent=intent, routes={'dev': intent}, baseline_version='sites/site/versions/old', baseline_catalog_sha=sha, lease_bucket='bucket', request=flaky, reader=lambda url: (200, data), run=run)
    receipt_path = tmp_path / 'deployment-attempt-v2.json'
    before = receipt_path.read_text()
    assert json.loads(before)['status'] == 'deployed' and remote.held
    failing['on'] = False
    result = p.reconcile(tmp_path, request=flaky, reader=lambda url: (200, data), confirmed_version='sites/site/versions/new')
    assert result['status'] == 'deployed' and remote.deleted and not remote.held
    assert receipt_path.read_text() == before
    again = p.reconcile(tmp_path, request=flaky, reader=lambda url: (200, data), confirmed_version='sites/site/versions/new')
    assert again['status'] == 'deployed'
