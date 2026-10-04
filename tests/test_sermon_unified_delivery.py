from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import pytest
from jsonschema import ValidationError
from scripts import sermon_unified_delivery as app
from scripts import delivery_contract as d


def test_closed_configuration_rejects_injected_command(tmp_path):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({'schemaVersion': 'sermon-unified-delivery-v1', 'command': ['sh', '-c', 'true']}))
    with pytest.raises(ValidationError):
        app.inspect(path)


def test_existing_release_authorization_binds_exact_seal_and_target(tmp_path):
    seal = tmp_path / 'seal-report.json'; seal.write_text('{}')
    plan = tmp_path / 'plan.json'; plan.write_text(json.dumps({'parentGeneration': 3}))
    receipt = tmp_path / 'authorization.json'
    value = {'date': '2026-10-04', 'intent': {'project': 'project', 'site': 'site', 'origin': 'https://site.web.app'}, 'baseline': {'version': 'old'}}
    state = {'planHash': 'a' * 64}
    auth = {'schemaVersion': 'sermon-release-authorization-v1', 'decision': 'approved', 'sunday': value['date'], 'configSha256': state['planHash'],
            'project': 'project', 'site': 'site', 'origin': 'https://site.web.app', 'buildReportSha256': app.file_sha(seal),
            'parentReleaseId': 'old', 'parentGeneration': 3, 'approvedBy': 'test-operator', 'approvedAt': '2026-10-04T20:00:00Z'}
    receipt.write_text(json.dumps(auth))
    paths = {'authorization': receipt, 'releasePlan': plan}
    assert app._authorization(value, paths, state, tmp_path)['decision'] == 'approved'
    for key in ('configSha256', 'project', 'site', 'origin', 'buildReportSha256', 'parentReleaseId', 'parentGeneration'):
        receipt.write_text(json.dumps({**auth, key: 'old-or-wrong'}))
        with pytest.raises(ValueError, match='exact target'):
            app._authorization(value, paths, state, tmp_path)


def test_http_failure_writes_failure_and_never_promotes(tmp_path):
    payload = b'expected'; digest = hashlib.sha256(payload).hexdigest()
    report = {'catalogSha256': digest, 'files': [{'path': '/multilingual-v3.json', 'sha256': digest, 'bytes': len(payload)}]}
    (tmp_path / 'seal-report.json').write_text(json.dumps(report))
    attempt = d.new_attempt({'origin': 'https://site.web.app'}, catalog_sha=digest, assets_sha=d.sha(report['files']), baseline_version='old')
    attempt.update(status='deployed', newVersion='new', completedAt=datetime.now(timezone.utc).isoformat())
    with pytest.raises(ValueError, match='HTTP verification failed'):
        app._verify_publication(tmp_path, attempt, lambda url: (200, b'old'))
    recorded = json.loads((tmp_path / 'publication-http-v2.json').read_text())
    assert recorded['passed'] is False and recorded['failures'] == ['/multilingual-v3.json']
    assert app._verify_publication(tmp_path, attempt, lambda url: (200, payload))['publication'] == 'published_http_verified'


def test_nested_input_snapshot_rejects_replaced_artifact(tmp_path):
    nested = tmp_path / 'track.mp3'; nested.write_bytes(b'original media')
    package = tmp_path / 'package.json'
    package.write_text(json.dumps({'track': {'path': nested.name, 'sha256': app.file_sha(nested)}}))
    value = {'inputs': {'source': {'path': package.name, 'sha256': app.file_sha(package)}}}
    first = app._input_snapshot(value, tmp_path, {})
    assert set(first['dependencies']) == {str(package), str(nested)}
    nested.write_bytes(b'replaced media')
    with pytest.raises(ValueError, match='Nested delivery input changed'):
        app._input_snapshot(value, tmp_path, {})
