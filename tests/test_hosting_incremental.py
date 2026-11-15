import gzip
import hashlib
import json

import pytest

from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.delivery import hosting_incremental


def test_digest_is_the_hash_of_the_gzip_body():
    # Hosting stores the sha256 of the gzip-encoded upload, not of the raw file.
    path = __import__('pathlib').Path(__file__).with_name('test_hosting_incremental.py')
    raw = path.read_bytes()
    assert hosting_incremental.digest(path) == hashlib.sha256(gzip.compress(raw, mtime=0)).hexdigest()


def test_ignore_matcher_follows_the_hosting_glob_rules():
    match = hosting_incremental.ignore_matcher(['firebase.json', '**/node_modules/**', '**/*.map'])
    assert match('firebase.json')
    assert match('a/node_modules/pkg/index.js')
    assert match('deep/dir/app.js.map')
    assert not match('index.html')
    assert not match('node_modules-notes.txt')


def test_local_files_skips_hidden_entries_and_ignored_globs(tmp_path):
    public = tmp_path / 'public'
    (public / 'media').mkdir(parents=True)
    (public / 'index.html').write_bytes(b'<html>')
    (public / 'media' / 'episode.mp3').write_bytes(b'audio')
    (public / '.well-known-dir').mkdir()
    (public / '.well-known-dir' / 'app.json').write_bytes(b'{}')
    (public / '.DS_Store').write_bytes(b'junk')
    (public / 'bundle.js.map').write_bytes(b'map')
    files = hosting_incremental.local_files(public, ['**/*.map'])
    assert sorted(files) == ['/index.html', '/media/episode.mp3']
    assert files['/media/episode.mp3'] == public / 'media' / 'episode.mp3'


def receipt(tmp_path, **overrides):
    path = tmp_path / 'incremental-publish.json'
    body = {'schemaVersion': hosting_incremental.RECEIPT_SCHEMA, 'site': 'site',
            'baselineVersion': 'sites/site/versions/old', 'clonedVersion': 'sites/site/versions/new',
            'release': {'name': 'sites/site/releases/1', 'version': 'sites/site/versions/new'}}
    body.update(overrides)
    path.write_text(json.dumps(body))
    return path


def test_receipt_version_names_the_cloned_version(tmp_path):
    path = receipt(tmp_path)
    assert hosting_incremental.receipt_version(path, site='site',
                                               baseline_version='sites/site/versions/old') == 'sites/site/versions/new'


@pytest.mark.parametrize('overrides', [
    {'schemaVersion': 'other'},
    {'site': 'other'},
    {'clonedVersion': 'sites/site/versions/old'},          # the baseline is never our version
    {'clonedVersion': 'sites/other/versions/new'},         # another site's version
    {'release': {'version': 'sites/site/versions/other'}},  # release does not carry this version
])
def test_receipt_version_rejects_a_receipt_that_does_not_name_this_deployment(tmp_path, overrides):
    path = receipt(tmp_path, **overrides)
    with pytest.raises(ValueError, match='Incremental deployment receipt'):
        hosting_incremental.receipt_version(path, site='site',
                                           baseline_version='sites/site/versions/old')


def test_receipt_version_requires_the_receipt_to_exist(tmp_path):
    with pytest.raises(ValueError, match='explicit reconciliation required'):
        hosting_incremental.receipt_version(tmp_path / 'missing.json', site='site',
                                            baseline_version='sites/site/versions/old')


def test_remote_files_reads_every_page_of_a_version_listing():
    calls = []

    def request(method, url, **kwargs):
        calls.append(url)
        if 'pageToken=second' in url:
            return {'files': [{'path': '/b.html', 'hash': 'h2'}]}
        return {'files': [{'path': '/a.html', 'hash': 'h1'}], 'nextPageToken': 'second'}

    assert hosting_incremental.remote_files(request, 'site', 'sites/site/versions/old') == {
        '/a.html': 'h1', '/b.html': 'h2'}
    assert calls[0].endswith('/versions/old/files?pageSize=1000')
    assert 'pageToken=second' in calls[1]
